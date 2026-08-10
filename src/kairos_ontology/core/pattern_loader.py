# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Pattern-library loader for the authoring-time design-domain flow (#262 §3).

Consumes the **pattern library** published by ``kairos-ontology-referencemodels`` under
``blueprints/patterns/<id>/pattern.yaml`` — sector-neutral modelling craft (naming
conventions + anti-patterns) harvested from client hub implementations.

This is an **advisory, authoring-time** consumer owned by the ``kairos-design-domain``
skill (where classes/properties are named), *not* the discovery-time
``discovery-conformance`` flow.  It surfaces normative naming conventions so an ontology
designer copies the shared vocabulary (e.g. the requested/planned/estimated/actual
timestamp quartet) instead of inventing synonyms, and surfaces anti-patterns as
rejection guidance.

The library is ``v0.2 — markdown-first, parse-guarded, no JSON Schema yet`` (see the
folder README), so this loader is deliberately **lenient**: it reads whatever keys a
``pattern.yaml`` declares, tolerates optional/unknown fields, and *skips* a malformed
pattern directory with a warning rather than raising — advisory surfacing must never
break the design loop.  Like :mod:`kairos_ontology.core.archetype_loader`, it never
fetches over the network and uses ``yaml.safe_load`` only.

.. warning::
   Leniency is correct for callers and useless as a quality signal: a skipped pattern is
   an *absent* pattern, and a caller cannot tell "the library has four patterns" from
   "the library has five, one of which will not parse".  Reference-models
   ``temporal-quartet`` shipped unparseable in v1.13.0 and stayed that way for two minor
   versions — :func:`load_patterns` warned and ``list-patterns`` printed it, exactly as
   designed, and nobody was looking.  Callers wanting a *guarantee* rather than best
   effort must use :func:`load_pattern` (fail-fast) or assert that :func:`load_patterns`
   returned no warnings; see ``tests/test_refmodels_contract.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .archetype_loader import normalize_refmodels_root

logger = logging.getLogger(__name__)

#: Relative location of the pattern library inside a normalized reference-models root.
_PATTERNS_SUBDIR = Path("blueprints/patterns")

#: Per-pattern catalog file name (one directory per pattern).
_PATTERN_FILENAME = "pattern.yaml"

#: Directory names under ``blueprints/patterns/`` that are not patterns.
_PATTERN_DIR_EXCLUDES = {"_schema"}


class PatternError(Exception):
    """Raised for an explicitly requested pattern that cannot be loaded (fail-fast case)."""


@dataclass(frozen=True)
class Pattern:
    """A loaded pattern-library entry (best-effort, schema-lenient).

    Only ``id`` is guaranteed.  Every other field mirrors an optional block of the
    ``pattern.yaml`` and defaults to empty when absent, because the library ships
    markdown-first without a JSON Schema.  ``extra`` preserves any additional top-level
    keys so nothing declared by an author is silently dropped.

    ``naming_conventions`` is deliberately untyped: published patterns use a different key set
    each (``qualifier``/``start_or_arrival`` in ``temporal-quartet``, ``element``/``convention``
    in ``deferred-relationship``, ``link``/``property`` in ``multimodal-order-leg``), so no
    fixed-column table can be derived from it generically — consumers must read it as-is.

    Only keys the whole library ships are promoted to fields.  Pattern-specific blocks
    (``mode_bindings``, ``participants``, ``naming_rule``, ``closes_gap``, …) stay in ``extra``
    and still reach consumers, because :meth:`to_payload` flattens it — promoting a key that
    only one pattern declares would make every other pattern emit an empty placeholder.
    """

    id: str
    problem: str
    applicability: str
    normativity: dict[str, Any]
    naming_conventions: Any
    anti_patterns: list[Any]
    source_path: Path
    grain_collisions: list[Any] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON/YAML-friendly dict (drops the local filesystem path)."""
        payload: dict[str, Any] = {
            "id": self.id,
            "problem": self.problem,
            "applicability": self.applicability,
            "normativity": self.normativity,
            "naming_conventions": self.naming_conventions,
            "anti_patterns": self.anti_patterns,
            "grain_collisions": self.grain_collisions,
        }
        payload.update(self.extra)
        return payload


def _patterns_dir(refmodels_root: Path) -> Path:
    """Return the ``blueprints/patterns/`` directory inside the normalized root."""
    return normalize_refmodels_root(refmodels_root) / _PATTERNS_SUBDIR


def list_patterns(refmodels_root: Path) -> list[str]:
    """Return the sorted pattern ids available under the reference-models root.

    A pattern id is a sub-directory of ``blueprints/patterns/`` that contains a
    ``pattern.yaml`` file.  ``_schema/`` and dot-directories are excluded.  Returns an
    empty list when the library is absent (a hub may predate the pattern folder).
    """
    patterns_dir = _patterns_dir(refmodels_root)
    if not patterns_dir.is_dir():
        return []
    ids: list[str] = []
    for entry in patterns_dir.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name in _PATTERN_DIR_EXCLUDES:
            continue
        if (entry / _PATTERN_FILENAME).is_file():
            ids.append(entry.name)
    return sorted(ids)


def _build_pattern(pattern_id: str, data: dict[str, Any], source_path: Path) -> Pattern:
    """Assemble a :class:`Pattern` from parsed YAML, preserving unknown keys in ``extra``."""
    known = {
        "id",
        "problem",
        "applicability",
        "normativity",
        "naming_conventions",
        "anti_patterns",
        "grain_collisions",
    }
    normativity = data.get("normativity") or {}
    anti_patterns = data.get("anti_patterns") or []
    grain_collisions = data.get("grain_collisions") or []
    return Pattern(
        id=str(data.get("id") or pattern_id),
        problem=str(data.get("problem") or "").strip(),
        applicability=str(data.get("applicability") or "").strip(),
        normativity=normativity if isinstance(normativity, dict) else {},
        naming_conventions=data.get("naming_conventions"),
        anti_patterns=anti_patterns if isinstance(anti_patterns, list) else [],
        source_path=source_path,
        grain_collisions=grain_collisions if isinstance(grain_collisions, list) else [],
        extra={k: v for k, v in data.items() if k not in known},
    )


def load_pattern(refmodels_root: Path, pattern_id: str) -> Pattern:
    """Load a single pattern by id.

    Raises:
        PatternError: if the pattern directory or its ``pattern.yaml`` is missing, or the
            YAML is not a mapping.  (Explicit single-pattern requests fail fast; bulk
            loading via :func:`load_patterns` is lenient instead.)
    """
    patterns_dir = _patterns_dir(refmodels_root)
    pattern_file = patterns_dir / pattern_id / _PATTERN_FILENAME
    if not pattern_file.is_file():
        raise PatternError(
            f"Pattern '{pattern_id}' not found: expected "
            f"'{(_PATTERNS_SUBDIR / pattern_id / _PATTERN_FILENAME).as_posix()}' under the "
            "reference-models root."
        )
    try:
        data = yaml.safe_load(pattern_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PatternError(f"Pattern '{pattern_id}' YAML is invalid: {exc}") from exc
    if not isinstance(data, dict):
        raise PatternError(
            f"Pattern '{pattern_id}' must be a YAML mapping, got {type(data).__name__}."
        )
    return _build_pattern(pattern_id, data, pattern_file)


def pattern_quality_warnings(pattern: Pattern) -> list[str]:
    """Return advisory warnings about a pattern that *parses* but is not usable as authored.

    Valid YAML is only the floor. A pattern can parse, carry the right ``id``, and still be
    hollow — declaring ``normativity.naming: normative`` while shipping no
    ``naming_conventions``, or an anti-pattern with no ``rejection_reason`` for the design
    skill to cite. Reference-models has no ``_schema/pattern.schema.json`` yet, so nothing
    catches that at authoring time and this loader's leniency means nothing catches it at
    load time either: the pattern is simply *quietly useless*.

    This is deliberately **consumer-side detection, not enforcement**. It makes a hollow
    pattern visible instead of silent; it cannot prevent a bad publish. The authoring-time
    fix belongs in reference-models (#262).

    Never raises — a quality problem is a warning, exactly like a parse failure.
    """
    warnings: list[str] = []
    naming_normativity = str((pattern.normativity or {}).get("naming") or "").strip()

    if pattern.naming_conventions is not None and not isinstance(
        pattern.naming_conventions, list
    ):
        warnings.append(
            f"Pattern '{pattern.id}': naming_conventions is "
            f"{type(pattern.naming_conventions).__name__}, expected a list of entries — "
            "the library's own structural rule. Consumers reading it as a list will see nothing."
        )
    elif naming_normativity == "normative" and not pattern.naming_conventions:
        warnings.append(
            f"Pattern '{pattern.id}': declares normativity.naming 'normative' but ships no "
            "naming_conventions, so there is no normative name for the design skill to prefer."
        )

    for index, entry in enumerate(pattern.anti_patterns):
        if not isinstance(entry, dict):
            warnings.append(
                f"Pattern '{pattern.id}': anti_patterns[{index}] is "
                f"{type(entry).__name__}, expected a mapping with id/description/"
                "rejection_reason."
            )
            continue
        if not str(entry.get("rejection_reason") or "").strip():
            label = str(entry.get("id") or f"index {index}")
            warnings.append(
                f"Pattern '{pattern.id}': anti_pattern '{label}' has no rejection_reason — "
                "the design skill is told to cite one when steering a user away."
            )
    return warnings


def load_patterns(refmodels_root: Path) -> tuple[list[Pattern], list[str]]:
    """Load every pattern, best-effort.

    Returns a ``(patterns, warnings)`` tuple: patterns that parse cleanly are returned
    sorted by id; a directory whose ``pattern.yaml`` is malformed contributes a warning
    string and is skipped rather than raising, so advisory surfacing never breaks the
    design loop.  An absent library yields ``([], [])``.

    Warnings also cover patterns that parsed but are hollow — see
    :func:`pattern_quality_warnings`. Those patterns are still returned; only the warning
    tells you they cannot deliver what they claim.
    """
    patterns: list[Pattern] = []
    warnings: list[str] = []
    for pattern_id in list_patterns(refmodels_root):
        try:
            pattern = load_pattern(refmodels_root, pattern_id)
        except PatternError as exc:
            warnings.append(f"Skipped pattern '{pattern_id}': {exc}")
            logger.debug("Skipping malformed pattern '%s': %s", pattern_id, exc)
            continue
        patterns.append(pattern)
        warnings.extend(pattern_quality_warnings(pattern))
    return patterns, warnings
