# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Loader for the accelerator pack's ``entity-projections.yaml`` (DD-188, issue #531).

An *entity projection* is a recognition rule: a set of scalar columns on one source
table that together evidence a separate entity the source system flattened away —
``billing_street`` + ``billing_city`` + ``billing_postal_code`` are three columns and
one Address.

Under DD-188 the *logic* of that detection is the toolkit's and the *vocabulary* is
the reference models'.  This module carries only the vocabulary side: it reads the
pack-scoped file and hands back typed, inert data.  Nothing here knows what an
address is; ``postal-address`` is simply the one projection the ``logistics`` pack
happens to author today, and ``financial-services`` is free to ship none.

Why a module of its own rather than a function beside
:func:`kairos_ontology.core.analyse_sources.load_data_domains` (the precedent this
loader deliberately copies) or inside :mod:`kairos_ontology.core.pattern_loader`:

* ``pattern_loader`` is scoped to the *global* ``blueprints/patterns/`` library.  The
  whole premise of DD-188 is that ``logistics`` needs ``pickup``/``origin``/
  ``destination`` and ``financial-services`` needs none of them, which a global file
  cannot express — so a pack-scoped loader does not belong in it.
* ``analyse_sources`` is a 2000-line shared module and this is more than one
  function: the schema needs types, and the ``weak`` / ``requires: context`` gating
  rules need somewhere to be documented next to the fields they gate.

Resolution and error behaviour mirror ``load_data_domains`` exactly — same
``accelerator-packs/<pack>/client-hub-blueprint/`` directory, same glob shape, same
"first match wins" when no accelerator is named: take the first path that parses,
warn-and-continue on a malformed file, and return an *empty* result when nothing is
found.  Empty is a real answer — see :class:`ProjectionConfig`.  ``financial-services``
ships no such file on purpose, so the empty path is exercised, not hypothetical.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

#: Pack-scoped filename, one per accelerator pack, many ``projections`` inside it.
PROJECTIONS_FILENAME = "entity-projections.yaml"

#: The pack's hub-facing blueprint directory — a sibling of ``current/``, and the
#: exact directory ``data-domains.yaml`` is read from.  Deliberately NOT
#: ``current/blueprint/``: that is the logistics-only blueprint dossier (canonical
#: class registry, overlap register, evidence) with its own logistics-specific
#: ``_schema/``, and ``financial-services/current/`` has no ``blueprint/`` at all —
#: a path the second pack structurally cannot use is fatal for a fix whose whole
#: purpose is that two packs ship different vocabularies.
_BLUEPRINT_SUBDIR = "client-hub-blueprint"

#: ``requires:`` value meaning "a context token specifically; a role qualifier is
#: not enough".  Stricter than ``weak``.
REQUIRES_CONTEXT = "context"


@dataclass(frozen=True)
class PartKind:
    """One canonical part kind of a projection, and the tokens that recognise it.

    ``tokens`` match against the column's *token set* (so ``street`` matches
    ``SHIPPER_STREET`` and ``shipperStreet`` but not ``streetlight``); ``compact``
    entries match as substrings of the compacted name only, which is what lets
    ``postal_code`` and ``PostalCode`` both reach the ``postal`` kind without
    ``code`` becoming a token of interest.

    Two gates weaken a kind, and they are not interchangeable:

    ``weak``
        The kind alone is not evidence.  It counts only when the column name also
        carries a role qualifier *or* a context token.  This is the guard that stops
        a bare ``country`` column being read as an address when it is citizenship.

    ``requires == "context"``
        Stricter: a role qualifier does **not** satisfy it, only a context token
        does.  ``region`` is the motivating case — ``shipper_region`` is a sales
        region as readily as a subdivision, while ``shipper_location_region`` is not.
    """

    kind: str
    tokens: frozenset[str] = frozenset()
    compact: tuple[str, ...] = ()
    weak: bool = False
    requires: str = ""

    @property
    def needs_context(self) -> bool:
        """True when only a context token can confirm this kind."""
        return self.requires == REQUIRES_CONTEXT

    @property
    def needs_confirmation(self) -> bool:
        """True when the kind cannot stand on its own name alone."""
        return self.weak or self.needs_context


@dataclass(frozen=True)
class EntityProjection:
    """One projection rule — the pack's answer to "what does an X look like flattened"."""

    id: str
    target_concept: str
    target_candidates: tuple[str, ...] = ()
    min_complementary_parts: int = 2
    relationship_naming: str = ""
    default_relationship: str = ""
    cardinality: str = "1:n"
    part_kinds: tuple[PartKind, ...] = ()
    role_qualifiers: frozenset[str] = frozenset()
    context_tokens: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ProjectionConfig:
    """Everything the detector needs, or nothing at all.

    A config with no ``projections`` is the documented no-config state: the detector
    emits no candidates and says so.  There is deliberately no built-in vocabulary to
    fall back to (DD-188) — a silent fallback would make externalising the vocabulary
    cosmetic, and would keep shipping one industry's tokens to every other industry.
    """

    projections: tuple[EntityProjection, ...] = ()
    schema_version: int = 0
    source_path: Path | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return bool(self.projections)


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    """Coerce a YAML scalar-or-list into a tuple of non-empty lowercase-safe strings."""
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _build_part_kind(raw: Any) -> PartKind | None:
    """Build one :class:`PartKind`, or ``None`` when the entry names no kind."""
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip()
    if not kind:
        return None
    return PartKind(
        kind=kind,
        tokens=frozenset(t.lower() for t in _as_str_tuple(raw.get("tokens"))),
        compact=tuple(c.lower() for c in _as_str_tuple(raw.get("compact"))),
        weak=bool(raw.get("weak", False)),
        requires=str(raw.get("requires") or "").strip().lower(),
    )


def _build_projection(raw: Any, warnings: list[str]) -> EntityProjection | None:
    """Build one :class:`EntityProjection`, or ``None`` when it is unusable.

    Unusable means "carries no id" or "declares no part kinds" — a projection with
    nothing to recognise can never fire, and returning it would only make the
    detector look configured when it is not.
    """
    if not isinstance(raw, dict):
        warnings.append(f"projection entry is {type(raw).__name__}, expected a mapping")
        return None
    projection_id = str(raw.get("id") or "").strip()
    if not projection_id:
        warnings.append("projection entry has no 'id'")
        return None
    part_kinds = tuple(
        pk for pk in (_build_part_kind(p) for p in raw.get("part_kinds") or []) if pk
    )
    if not part_kinds:
        warnings.append(f"projection '{projection_id}' declares no usable part_kinds")
        return None
    try:
        min_parts = int(raw.get("min_complementary_parts", 2))
    except (TypeError, ValueError):
        warnings.append(
            f"projection '{projection_id}': min_complementary_parts "
            f"{raw.get('min_complementary_parts')!r} is not an integer; using 2"
        )
        min_parts = 2
    return EntityProjection(
        id=projection_id,
        target_concept=str(raw.get("target_concept") or "").strip(),
        target_candidates=_as_str_tuple(raw.get("target_candidates")),
        min_complementary_parts=max(1, min_parts),
        relationship_naming=str(raw.get("relationship_naming") or "").strip(),
        default_relationship=str(raw.get("default_relationship") or "").strip(),
        cardinality=str(raw.get("cardinality") or "1:n").strip(),
        part_kinds=part_kinds,
        role_qualifiers=frozenset(r.lower() for r in _as_str_tuple(raw.get("role_qualifiers"))),
        context_tokens=frozenset(c.lower() for c in _as_str_tuple(raw.get("context_tokens"))),
    )


def parse_entity_projections(payload: Any, source_path: Path | None = None) -> ProjectionConfig:
    """Build a :class:`ProjectionConfig` from an already-parsed YAML mapping.

    Split out from :func:`load_entity_projections` so the schema can be tested from a
    fixture rather than from whichever pack happens to be installed.
    """
    warnings: list[str] = []
    if not isinstance(payload, dict):
        return ProjectionConfig(
            source_path=source_path,
            warnings=(f"expected a YAML mapping, got {type(payload).__name__}",),
        )
    # Not ``or []``: a ``projections:`` block authored as a mapping is a schema
    # error worth a warning, while ``or []`` would silently make it look like a
    # pack that ships none — the one case that must stay unambiguous.
    raw_projections = payload.get("projections")
    if raw_projections is None:
        raw_projections = []
    if not isinstance(raw_projections, list):
        return ProjectionConfig(
            source_path=source_path,
            warnings=(f"'projections' is {type(raw_projections).__name__}, expected a list",),
        )
    projections: list[EntityProjection] = []
    seen: set[str] = set()
    for raw in raw_projections:
        projection = _build_projection(raw, warnings)
        if projection is None:
            continue
        if projection.id in seen:
            warnings.append(f"duplicate projection id '{projection.id}'; keeping the first")
            continue
        seen.add(projection.id)
        projections.append(projection)
    try:
        schema_version = int(payload.get("schema_version", 0))
    except (TypeError, ValueError):
        schema_version = 0
    return ProjectionConfig(
        projections=tuple(projections),
        schema_version=schema_version,
        source_path=source_path,
        warnings=tuple(warnings),
    )


def entity_projection_paths(ref_models_dir: Path, accelerator: str | None = None) -> list[Path]:
    """Return the candidate ``entity-projections.yaml`` paths, in resolution order.

    The glob is character-for-character the one ``load_data_domains`` uses, with a
    different filename: an explicit *accelerator* pins one pack, omitting it globs
    every pack and lets the first sorted match win.
    """
    packs = accelerator if accelerator else "*"
    pattern = f"accelerator-packs/{packs}/{_BLUEPRINT_SUBDIR}/{PROJECTIONS_FILENAME}"
    return sorted(Path(ref_models_dir).glob(pattern))


def load_entity_projections(
    ref_models_dir: Path | None, accelerator: str | None = None
) -> ProjectionConfig:
    """Load the pack's entity-projection vocabulary (DD-188).

    Mirrors :func:`kairos_ontology.core.analyse_sources.load_data_domains`: the file
    is pack-scoped under the pack's blueprint directory, an explicit *accelerator*
    pins which pack is read, omitting it means "first match wins", and a file that
    cannot be parsed is warned about and skipped rather than raising — an advisory
    detector must never fail a run.

    Returns an **empty** :class:`ProjectionConfig` when the pack ships no such file.
    Callers must treat that as "emit no candidates", never as "use a built-in
    vocabulary": there is none, on purpose.
    """
    if ref_models_dir is None:
        logger.info(
            "No reference-models directory available; entity-projection detection is "
            "disabled (DD-188: the toolkit ships no built-in projection vocabulary)."
        )
        return ProjectionConfig()

    for path in entity_projection_paths(Path(ref_models_dir), accelerator):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - advisory input, never fails a run
            logger.warning("Failed to load %s: %s", path, exc)
            continue
        config = parse_entity_projections(payload, source_path=path)
        for warning in config.warnings:
            logger.warning("%s: %s", path, warning)
        if not config.projections:
            logger.warning(
                "%s parsed but declares no usable projections; entity-projection "
                "detection emits no candidates.",
                path,
            )
            continue
        logger.info(
            "Loaded %d entity projection(s) from %s: %s",
            len(config.projections),
            path,
            ", ".join(p.id for p in config.projections),
        )
        return config

    logger.info(
        "No %s found under %s for accelerator '%s'; entity-projection detection emits "
        "no candidates (DD-188: the toolkit ships no built-in projection vocabulary, "
        "so an older reference-models pin simply produces none).",
        PROJECTIONS_FILENAME,
        ref_models_dir,
        accelerator or "*",
    )
    return ProjectionConfig()
