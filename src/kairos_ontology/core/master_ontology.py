# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Textual, marker-based ``_master.ttl`` ``owl:imports`` synchronization (issue #393).

A hub's ``_master.ttl`` is meant to unify every authored domain ontology under one
``owl:imports`` closure so the hub has a single entry point. Nothing enforced that
before this module existed: a domain could be fully authored, cataloged, bound, and
validated, yet never be imported by ``_master.ttl`` -- silently unreachable from the
hub's own single ontology entry point.

This mirrors :mod:`kairos_ontology.core.catalog_utils`'s ``sync_domain_catalog_entry``:
that function was deliberately rewritten away from a whole-file ``ElementTree``
round-trip because re-serializing the *entire* file drops prolog comments,
blank lines, and formatting that are worth preserving. The identical risk applies
here -- rdflib's Turtle serializer does not preserve original comments/formatting at
all, and ``_master.ttl``'s scaffold template ships real prose comments. So every edit
below is textual: either a small, well-anchored insertion, or nothing (idempotent
no-op) when the requested import is already present. The file is never parsed and
reserialized as a whole. This module itself never calls ``rdflib`` directly; the only
rdflib use, in both cases a read-only, non-semantic parse, lives in
:mod:`kairos_ontology.core.catalog_utils` -- ``validate_turtle_text`` validates the
proposed new text before it is written, and ``_declared_ontology_iri`` reads the
master ontology's own declared IRI.
"""

from __future__ import annotations

import re
from pathlib import Path

from .catalog_utils import _declared_ontology_iri, validate_turtle_text

# The scaffold template's exact marker comment text (see
# ``scaffold/ontology-hub/model/ontologies/master.ttl.template``):
#   ## -- Add owl:imports for each domain ontology below --
# Matched as plain text (not a compiled comment token) since this literal is itself
# only ever found inside a Turtle comment; it does not need masking to be found.
_MASTER_IMPORT_MARKER_TEXT = "Add owl:imports for each domain ontology below"

# A live (non-commented) ``owl:imports <IRI>`` triple/predicate-object pair.
_IMPORTS_RE = re.compile(r"owl:imports\s+<([^>]+)>")


class MasterOntologySyncError(Exception):
    """Raised when ``_master.ttl`` cannot be safely synced via textual editing.

    Callers (e.g. ``kairos-ontology init --domain``) should catch this, print a
    warning telling the user to add the ``owl:imports`` triple manually, and
    continue -- this is a secondary, best-effort step and must never fail the
    surrounding command.
    """


def _mask_turtle_comments(text: str) -> str:
    """Return *text* with every ``#``-to-end-of-line Turtle comment blanked out.

    Unlike XML, a bare ``#`` is not unambiguously a comment starter in Turtle: it is
    also the fragment separator inside a document IRI (``<https://.../ont/master#it>``)
    and can appear inside a quoted string literal. A naive "blank from first '#' to
    end of line" mask would corrupt either of those. This walks the text once,
    tracking whether the cursor is inside an IRI (``<...>``) or a quoted string
    literal, and only treats a ``#`` reached in neither state as a comment start.

    Masking blanks characters in place (preserving string length and line
    structure, except that line-ending characters are always kept as-is) so match
    spans found against the masked text are directly reusable as slice indices into
    the original, unmasked text -- the same technique
    :func:`kairos_ontology.core.catalog_utils._mask_comments` uses for XML.
    """
    out = list(text)
    in_iri = False
    in_string = False
    string_quote = ""
    in_comment = False
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if in_comment:
            if ch in ("\r", "\n"):
                in_comment = False
            else:
                out[i] = " "
        elif in_string:
            if ch == "\\":
                i += 1  # skip the escaped character untouched (e.g. \" or \\)
            elif ch == string_quote:
                in_string = False
        elif in_iri:
            if ch == ">":
                in_iri = False
        else:
            if ch == "<":
                in_iri = True
            elif ch in ("'", '"'):
                in_string = True
                string_quote = ch
            elif ch == "#":
                in_comment = True
                out[i] = " "
        i += 1
    return "".join(out)


def list_active_master_imports(master_path: Path) -> set[str]:
    """Return the set of IRIs from LIVE (non-commented) ``owl:imports <IRI>`` triples.

    The shipped scaffold template ships a commented-out example ``owl:imports``
    block; masking Turtle comments first ensures that example is never mistaken
    for a live import.
    """
    with open(master_path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    masked = _mask_turtle_comments(text)
    return {match.group(1) for match in _IMPORTS_RE.finditer(masked)}


def _detect_newline(text: str) -> str:
    """Return the dominant line ending used in *text* (CRLF if present, else LF)."""
    return "\r\n" if "\r\n" in text else "\n"


def _line_end(text: str, pos: int) -> int:
    """Return the index just past the end of the line containing *pos*."""
    nl_pos = text.find("\n", pos)
    return len(text) if nl_pos == -1 else nl_pos + 1


def sync_master_ontology_import(master_path: Path, ontology_iri: str) -> bool:
    """Ensure ``_master.ttl`` carries a live ``owl:imports <ontology_iri>`` triple.

    Idempotent: checks by IRI (not by line text) before inserting, so calling this
    twice with the same IRI never produces a duplicate import. Returns ``True`` when
    a new import was inserted, ``False`` when it was already present (no-op).

    Insertion anchor priority:
      1. Immediately after the last existing *live* ``owl:imports <...>`` occurrence,
         if any exist.
      2. Otherwise, immediately after the scaffold's
         ``## -- Add owl:imports for each domain ontology below --`` marker comment.
      3. Last resort (marker removed/edited away, no existing imports found): append
         a new standalone ``<master-iri> owl:imports <IRI> .`` triple at end of file.

    Every insertion is written as its own standalone
    ``<master-iri> owl:imports <IRI> .`` triple rather than trying to extend an
    existing statement with a ``;`` continuation -- safer than guessing where an
    existing statement's ``.`` terminator is and risking breaking it, and always
    valid Turtle regardless of what precedes it.

    Before writing, the proposed new full text is validated as parseable Turtle;
    on failure, nothing is written and :class:`MasterOntologySyncError` is raised
    instead (see that class's docstring for the expected caller behavior). The
    same happens if the *existing* file cannot be read for its own declared
    ``owl:Ontology`` IRI (e.g. a corrupted ``_master.ttl``) -- the file is never
    touched in that case either.
    """
    with master_path.open("r", encoding="utf-8", newline="") as fh:
        text = fh.read()

    normalized_target = ontology_iri.rstrip("/")
    live_imports = {iri.rstrip("/") for iri in list_active_master_imports(master_path)}
    if normalized_target in live_imports:
        return False

    try:
        master_iri = _declared_ontology_iri(master_path)
    except Exception as exc:  # noqa: BLE001 - rdflib raises many parser-specific types
        raise MasterOntologySyncError(
            f"Could not read the owl:Ontology declaration from {master_path}: {exc}"
        ) from exc
    if not master_iri:
        raise MasterOntologySyncError(
            f"No owl:Ontology declaration found in {master_path}; cannot anchor a "
            "new owl:imports triple."
        )

    nl = _detect_newline(text)
    new_line = f"<{master_iri}> owl:imports <{ontology_iri}> ."

    masked = _mask_turtle_comments(text)
    import_matches = list(_IMPORTS_RE.finditer(masked))
    if import_matches:
        insert_pos = _line_end(text, import_matches[-1].end())
        new_text = text[:insert_pos] + new_line + nl + text[insert_pos:]
    else:
        marker_idx = text.find(_MASTER_IMPORT_MARKER_TEXT)
        if marker_idx != -1:
            insert_pos = _line_end(text, marker_idx)
            new_text = text[:insert_pos] + new_line + nl + text[insert_pos:]
        else:
            separator = "" if not text or text.endswith(("\n", "\r")) else nl
            new_text = text + separator + new_line + nl

    try:
        validate_turtle_text(new_text, context=master_path)
    except ValueError as exc:
        raise MasterOntologySyncError(str(exc)) from exc

    with master_path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(new_text)
    return True
