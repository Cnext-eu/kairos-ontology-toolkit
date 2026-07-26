# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""URI-first table-anchor resolution from confirmed discovery evidence.

``propose-alignment`` previously chose a table's reference-model class purely
from the LLM's semantic guess, with a lexical name-similarity fallback
(:func:`propose_alignment._score_ref_class`) when the model's pick was invalid.
Both paths can silently converge on the *nearest* class even when the business
has already **confirmed** — via the ``kairos-design-discovery`` Core Concepts
Conformance artifact (DD-090) — exactly which reference-model concept a
business term identifies, including an explicit rename
(``outcome: conforms-with-rename`` / ``rename_to``).

This module builds a **confirmed alias index** from that artifact (the only
input this feature treats as authoritative — human-approved during discovery,
not an LLM inference) and resolves a table's affinity-derived
``likely_entity`` against it *before* class selection runs. Three outcomes:

* ``"confirmed"``  — exactly one confirmed concept URI matches, and it is
  present in the table's candidate reference-model classes. The URI wins over
  any name-similarity/LLM guess (see ``propose_alignment.align_table``'s
  ``anchor_override``).
* ``"ambiguous"``  — the confirmed evidence itself names more than one
  distinct concept URI for the same alias (contradictory discovery data, or
  two archetypes sharing a business term). Never silently resolved to the
  "nearest" one — surfaced as an :mod:`unresolved_anchors` record instead.
* ``"none"``       — no confirmed alias matched. Falls through to the
  existing (unchanged) LLM / lexical-similarity path.

Pure and side-effect free: callers own reading the conformance artifact file.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

#: Core Concepts Conformance outcomes (DD-090) that represent a human-confirmed
#: identification of a business term with a reference-model concept — i.e. the
#: only outcomes this module treats as an authoritative alias source. Mirrors
#: ``derive_claims.CONFORMANCE_OUTCOME_TO_DISPOSITION``'s "claim" keys.
CONFIRMED_OUTCOMES = frozenset({"conforms", "conforms-with-rename"})

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _normalize_alias(value: str) -> str:
    """Lower-cased, punctuation-collapsed alias key for index lookups."""
    return "".join(_TOKEN_RE.findall(value or "")).lower()


def _local_name(uri: str) -> str:
    parsed = urlsplit(uri)
    return parsed.fragment or parsed.path.rstrip("/").rsplit("/", 1)[-1]


@dataclass(frozen=True)
class ConfirmedAlias:
    """One confirmed alias → canonical concept URI, from the conformance artifact."""

    alias: str
    canonical_uri: str
    canonical_label: str
    outcome: str


def build_confirmed_alias_index(
    conformance_artifact: dict[str, Any] | None,
) -> dict[str, list[ConfirmedAlias]]:
    """Build an alias index from a (already-loaded) conformance artifact mapping.

    Returns ``{normalized_alias: [ConfirmedAlias, ...]}``. Multiple entries under
    one alias signal contradictory confirmed evidence (surfaced as "ambiguous"
    by :func:`resolve_table_anchor`, never collapsed). Tolerant of a malformed or
    partial artifact — unusable entries are skipped rather than raising, since
    this is advisory pre-selection evidence, not the artifact's own governance
    validation (see ``conformance_artifact.validate_artifact`` for that).
    """
    index: dict[str, list[ConfirmedAlias]] = {}
    if not isinstance(conformance_artifact, dict):
        return index

    concepts = conformance_artifact.get("core_concepts")
    if not isinstance(concepts, list):
        return index

    for concept in concepts:
        if not isinstance(concept, dict):
            continue
        outcome = concept.get("outcome")
        if outcome not in CONFIRMED_OUTCOMES:
            continue
        uri = concept.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            continue
        label = str(concept.get("label", "") or "")
        aliases = {label, _local_name(uri)}
        rename_to = concept.get("rename_to")
        if isinstance(rename_to, str) and rename_to.strip():
            aliases.add(rename_to)
        entry = ConfirmedAlias(
            alias="", canonical_uri=uri, canonical_label=label or _local_name(uri),
            outcome=outcome,
        )
        for alias in aliases:
            key = _normalize_alias(alias)
            if not key:
                continue
            dated = ConfirmedAlias(
                alias=alias, canonical_uri=entry.canonical_uri,
                canonical_label=entry.canonical_label, outcome=entry.outcome,
            )
            bucket = index.setdefault(key, [])
            if not any(a.canonical_uri == uri for a in bucket):
                bucket.append(dated)

    return index


def load_confirmed_alias_index(
    conformance_path: Path | None,
) -> dict[str, list[ConfirmedAlias]]:
    """Load the confirmed alias index from a conformance artifact file.

    Tolerant: a missing path, missing file, or unparsable/invalid YAML returns
    an empty index (never raises) — the anchor-resolution feature is additive
    pre-selection evidence, so its absence must fall through to the existing
    LLM/lexical-similarity path unchanged, not fail the run.
    """
    if conformance_path is None:
        return {}
    path = Path(conformance_path)
    if not path.is_file():
        return {}
    try:
        from .conformance_artifact import read_artifact

        artifact = read_artifact(path)
    except Exception as exc:  # noqa: BLE001 — advisory input, never fatal here
        logger.warning("Could not read conformance artifact %s: %s", path, exc)
        return {}
    return build_confirmed_alias_index(artifact)


@dataclass(frozen=True)
class AnchorResolution:
    """Result of resolving one table's anchor against confirmed evidence."""

    #: ``"confirmed"`` | ``"ambiguous"`` | ``"none"``.
    status: str
    resolved_uri: str | None = None
    resolved_name: str | None = None
    candidate_uris: tuple[str, ...] = ()
    evidence: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_confirmed(self) -> bool:
        return self.status == "confirmed"

    @property
    def is_ambiguous(self) -> bool:
        return self.status == "ambiguous"


_NONE_RESOLUTION = AnchorResolution(status="none")


def resolve_table_anchor(
    likely_entity: str,
    alias_index: dict[str, list[ConfirmedAlias]],
    ref_classes: list[dict[str, Any]],
) -> AnchorResolution:
    """Resolve a table's anchor from confirmed discovery evidence.

    *likely_entity* is the affinity-derived candidate business entity name
    (``analyse-sources``' ``likely_entity``). *ref_classes* is the table's
    candidate reference-model class pool (each with a ``uri``/``name``) — a
    confirmed URI not present in this pool cannot be applied this run (the
    class' owning module is not imported/available) and resolves to
    ``"none"`` so the existing path still runs rather than silently failing.
    """
    if not likely_entity or not alias_index:
        return _NONE_RESOLUTION

    key = _normalize_alias(likely_entity)
    if not key:
        return _NONE_RESOLUTION

    matches = alias_index.get(key)
    if not matches:
        return _NONE_RESOLUTION

    distinct_uris = sorted({m.canonical_uri for m in matches})
    if len(distinct_uris) > 1:
        return AnchorResolution(
            status="ambiguous",
            candidate_uris=tuple(distinct_uris),
            evidence=tuple(
                f"confirmed alias {m.alias!r} -> {m.canonical_uri} "
                f"(outcome: {m.outcome})"
                for m in matches
            ),
        )

    uri = distinct_uris[0]
    ref_class = next(
        (c for c in ref_classes if str(c.get("uri", "")) == uri), None
    )
    if ref_class is None:
        # Confirmed, but the concept's module is not in this table's candidate
        # pool — cannot anchor this run. Fall through unchanged (not "ambiguous":
        # there is exactly one confirmed candidate, it is just unavailable here).
        return _NONE_RESOLUTION

    matched = next(m for m in matches if m.canonical_uri == uri)
    return AnchorResolution(
        status="confirmed",
        resolved_uri=uri,
        resolved_name=str(ref_class.get("name", "")),
        candidate_uris=(uri,),
        evidence=(
            f"confirmed alias {matched.alias!r} -> {uri} "
            f"(outcome: {matched.outcome})",
        ),
    )
