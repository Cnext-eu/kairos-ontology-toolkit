# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Binding-archetype catalog + loader for ``scaffold-binding``.

A small versioned catalog (``scaffold/binding-archetypes/<id>.yaml``, schema-validated against
a bundled JSON Schema) describes each ``scaffold-binding`` archetype's shape as *data* --
tier, grain/identity derivation policy, and which optional blocks (conformance, a worked
relationship example) it scaffolds -- rather than hardcoding one Python branch per archetype.

This mirrors the *shape* of the DD-090 archetype-catalog pattern
(:mod:`kairos_ontology.core.archetype_loader`: a versioned catalog + a loader that lists what
is available) but is a distinct, unrelated concept: DD-090 catalogs business-discovery concept
archetypes fetched from an external ``kairos-ontology-referencemodels`` checkout; this catalog
describes EntityBinding scaffold shapes and ships **inside this package** -- it is never
fetched externally and has no reference-models-root resolution step.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator

#: Schema version this loader supports (hard fail on mismatch, mirrors DD-090).
SUPPORTED_SCHEMA_VERSION = 1

#: The ordered, closed set of archetype ids this catalog is expected to define.
VALID_ARCHETYPE_IDS: tuple[str, ...] = (
    "passthrough",
    "single-source-master",
    "merged-master",
    "event-stream",
    "line-item-child",
)

_SCHEMA_FILENAME = "binding-archetype.schema.json"

#: Bundled catalog directory (``src/kairos_ontology/scaffold/binding-archetypes``). ``scaffold/``
#: is a plain packaged-data directory (no ``__init__.py``), so it is resolved as a relative
#: filesystem path from this module's location -- the same convention
#: ``kairos_ontology.cli.shared._SCAFFOLD_DIR`` uses -- rather than ``importlib.resources``.
_CATALOG_DIR = Path(__file__).resolve().parent.parent / "scaffold" / "binding-archetypes"


class BindingArchetypeError(ValueError):
    """Raised for a malformed, unknown, or unsupported binding archetype."""


@dataclass(frozen=True, slots=True)
class BindingArchetype:
    """One loaded, schema-validated ``scaffold-binding`` archetype definition."""

    id: str
    label: str
    description: str
    tier: str
    grain_mode: str
    identity_mode: str
    load_mode: str
    grain_hint_mode: str = "none"
    scaffold_conformance: bool = False
    scaffold_relationship_example: bool = False
    promotable_from: tuple[str, ...] = ()
    source_path: Path = Path()


def _load_schema() -> dict[str, Any]:
    path = _CATALOG_DIR / "_schema" / _SCHEMA_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


def _catalog_paths() -> list[Path]:
    if not _CATALOG_DIR.is_dir():
        return []
    return sorted(
        path
        for path in _CATALOG_DIR.glob("*.yaml")
        if path.is_file() and not path.name.startswith(".")
    )


def list_archetype_ids() -> tuple[str, ...]:
    """Return the sorted archetype ids available in the bundled catalog."""
    return tuple(sorted(path.stem for path in _catalog_paths()))


def list_binding_archetypes() -> tuple[BindingArchetype, ...]:
    """Load and return every archetype in the bundled catalog, sorted by id."""
    return tuple(load_binding_archetype(archetype_id) for archetype_id in list_archetype_ids())


def load_binding_archetype(archetype_id: str) -> BindingArchetype:
    """Load and fully validate the archetype catalog entry for *archetype_id*.

    Raises:
        BindingArchetypeError: if the archetype is unknown, malformed, fails schema
            validation, or declares a filename/id mismatch or unsupported schema version.
    """
    path = _CATALOG_DIR / f"{archetype_id}.yaml"
    if not path.is_file():
        available = ", ".join(list_archetype_ids()) or "(none)"
        raise BindingArchetypeError(
            f"Unknown scaffold-binding archetype {archetype_id!r}. Available: {available}."
        )

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise BindingArchetypeError(f"Archetype catalog is not a mapping: {path}")

    validator = Draft7Validator(_load_schema())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors[:8]
        )
        raise BindingArchetypeError(
            f"Archetype catalog {path.name!r} failed schema validation: {details}"
        )

    if data.get("schema_version") != SUPPORTED_SCHEMA_VERSION:
        raise BindingArchetypeError(
            f"Unsupported binding-archetype schema_version {data.get('schema_version')!r} "
            f"in {path.name}; this toolkit supports schema_version {SUPPORTED_SCHEMA_VERSION}."
        )
    if data.get("id") != archetype_id:
        raise BindingArchetypeError(
            f"Archetype id {data.get('id')!r} does not match filename stem {archetype_id!r} "
            f"({path.name})."
        )

    return BindingArchetype(
        id=data["id"],
        label=data["label"],
        description=data["description"],
        tier=data["tier"],
        grain_mode=data["grainMode"],
        identity_mode=data["identityMode"],
        load_mode=data["loadMode"],
        grain_hint_mode=data.get("grainHintMode", "none"),
        scaffold_conformance=bool(data.get("scaffoldConformance", False)),
        scaffold_relationship_example=bool(data.get("scaffoldRelationshipExample", False)),
        promotable_from=tuple(data.get("promotableFrom", ())),
        source_path=path,
    )
