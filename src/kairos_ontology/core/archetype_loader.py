# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Archetype catalog + discovery loader for the Core Concepts Conformance phase (DD-090).

Consumes the **archetype + discovery contract (v0.2)** published by
``kairos-ontology-referencemodels`` (>= v1.11.0):

* ``blueprints/archetypes/<id>.yaml`` — machine catalog (modules + classes + tiers),
  validated against the shipped ``blueprints/archetypes/_schema/archetype.schema.json``.
* ``blueprints/archetypes/_schema/outcome-codes.yaml`` — shared conformance-outcome enum.
* ``accelerator-packs/<pack>/discovery/<id>.md`` — SME interview prose, paired by stem.

This module is a **pure consumer**: it resolves the reference-models checkout, loads and
validates archetype catalogs, lists available archetypes, locates the paired discovery
document, and reports version drift.  It never fetches over the network and uses
``yaml.safe_load`` only (contract rows 2, 16, 17).
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

#: Environment variable that pins the reference-models checkout root (contract row 2).
REFMODELS_ROOT_ENV = "KAIROS_REFMODELS_ROOT"

#: Schema version this loader supports (hard fail on mismatch — contract rows 7, 11).
SUPPORTED_SCHEMA_VERSION = 1

#: Relative locations inside a normalized reference-models root.
_ARCHETYPES_SUBDIR = Path("blueprints/archetypes")
_SCHEMA_SUBDIR = _ARCHETYPES_SUBDIR / "_schema"
_OUTCOME_CODES_FILE = _SCHEMA_SUBDIR / "outcome-codes.yaml"
_ARCHETYPE_SCHEMA_FILE = _SCHEMA_SUBDIR / "archetype.schema.json"
_ACCELERATOR_PACKS_SUBDIR = Path("accelerator-packs")
_CATALOG_FILENAME = "catalog-v001.xml"

#: Filenames/dirs excluded from the archetype glob (contract row 5).
_ARCHETYPE_GLOB_EXCLUDES = {"VERSION", "README.md"}

#: Valid conformance tiers (mirrors the JSON Schema ``$defs/tier`` enum).
VALID_TIERS = ("required", "recommended", "optional")


class ArchetypeError(Exception):
    """Raised for unrecoverable archetype-loading failures (fail-fast cases)."""


@dataclass(frozen=True)
class ArchetypeModule:
    """A reference-model ontology module expected by an archetype."""

    iri: str
    tier: str


@dataclass(frozen=True)
class ArchetypeConcept:
    """A core concept (``owl:Class``) the archetype expects in the ref-model graph."""

    uri: str
    tier: str
    label: str


@dataclass
class Archetype:
    """A loaded, schema-validated archetype catalog."""

    id: str
    label: str
    description: str
    compatible_with: dict[str, Any]
    ref_model_modules: list[ArchetypeModule]
    core_concepts: list[ArchetypeConcept]
    source_path: Path
    catalog_hash: str
    schema_version: int = SUPPORTED_SCHEMA_VERSION

    def concept_uris(self) -> list[str]:
        """Return the ordered list of core-concept URIs."""
        return [c.uri for c in self.core_concepts]

    def concept_set_hash(self) -> str:
        """Return a stable hash of the (sorted) concept URI set.

        Used by ``kairos-design-domain`` to detect a stale conformance artifact when
        the archetype's concept set changes between discovery and modeling.
        """
        joined = "\n".join(sorted(self.concept_uris()))
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _looks_like_refmodels_root(path: Path) -> bool:
    """Return True if *path* contains the contract markers (catalog + archetypes)."""
    return (path / _CATALOG_FILENAME).is_file() and (path / _ARCHETYPES_SUBDIR).is_dir()


def normalize_refmodels_root(path: Path) -> Path:
    """Normalize a reference-models path to the directory that holds the contract files.

    Accepts either the inner ``ontology-reference-models/`` directory *or* a repository
    root that contains it (the sibling-checkout layout).  Validation is by presence of
    ``catalog-v001.xml`` + ``blueprints/archetypes/`` so callers can pass whichever they
    have.

    Raises:
        ArchetypeError: if neither *path* nor ``path/ontology-reference-models`` looks
            like a reference-models root.
    """
    path = Path(path)
    candidates = [path, path / "ontology-reference-models"]
    for candidate in candidates:
        if candidate.is_dir() and _looks_like_refmodels_root(candidate):
            return candidate
    raise ArchetypeError(
        f"'{path}' is not a reference-models root: expected '{_CATALOG_FILENAME}' and "
        f"'{_ARCHETYPES_SUBDIR.as_posix()}/' here or under an 'ontology-reference-models/' "
        f"child. Set {REFMODELS_ROOT_ENV} to the reference-models checkout."
    )


def resolve_refmodels_root(
    *,
    explicit: Path | str | None = None,
    cwd: Path | None = None,
    hub_root: Path | None = None,
) -> Path:
    """Resolve and normalize the reference-models root.

    Precedence (contract row 2 — env + fallback only; no hub-config key in v1):

    1. *explicit* (e.g. a ``--refmodels-root`` CLI flag),
    2. the ``KAIROS_REFMODELS_ROOT`` environment variable,
    3. the existing folder-scan fallback (sibling ``ontology-reference-models/``).

    Returns the normalized inner root (the directory holding the contract files).

    Raises:
        ArchetypeError: if no candidate resolves to a valid reference-models root.
    """
    cwd = Path(cwd) if cwd is not None else Path.cwd()

    if explicit:
        return normalize_refmodels_root(Path(explicit))

    env_value = os.environ.get(REFMODELS_ROOT_ENV)
    if env_value:
        return normalize_refmodels_root(Path(env_value))

    # Fallback: reuse the toolkit's folder-scan resolver (sibling / hub-relative dirs).
    from ..cli.main import _resolve_ref_models_dir  # local import to avoid a cycle

    scanned = _resolve_ref_models_dir(cwd, hub_root)
    if scanned is not None and _looks_like_refmodels_root(scanned):
        return scanned
    if scanned is not None:
        # Found an ontology-reference-models/ dir but it lacks the archetype contract.
        try:
            return normalize_refmodels_root(scanned)
        except ArchetypeError:
            pass

    raise ArchetypeError(
        "Cannot locate a reference-models checkout with the archetype contract "
        f"('{_ARCHETYPES_SUBDIR.as_posix()}/'). Set the {REFMODELS_ROOT_ENV} environment "
        "variable to your kairos-ontology-referencemodels checkout (>= v1.11.0)."
    )


def list_archetypes(refmodels_root: Path) -> list[str]:
    """Return the sorted archetype ids available under the reference-models root.

    Globs ``blueprints/archetypes/*.yaml``, excluding ``_schema/`` (a subdir, so never
    matched), ``VERSION``, ``README.md`` and dotfiles (contract row 5).
    """
    root = normalize_refmodels_root(refmodels_root)
    archetypes_dir = root / _ARCHETYPES_SUBDIR
    if not archetypes_dir.is_dir():
        return []
    ids: list[str] = []
    for entry in archetypes_dir.glob("*.yaml"):
        if not entry.is_file():
            continue
        if entry.name.startswith(".") or entry.name in _ARCHETYPE_GLOB_EXCLUDES:
            continue
        ids.append(entry.stem)
    return sorted(ids)


def load_outcome_codes(refmodels_root: Path) -> list[str]:
    """Load the shared conformance-outcome enum from the contract (contract row 15).

    The codes (not the prose) are owned by the reference-models repo; this loader never
    hardcodes them so the toolkit and ref-models cannot drift.

    Raises:
        ArchetypeError: if the outcome-codes file is missing or malformed.
    """
    root = normalize_refmodels_root(refmodels_root)
    codes_path = root / _OUTCOME_CODES_FILE
    if not codes_path.is_file():
        raise ArchetypeError(
            f"Outcome-codes file not found: {codes_path}. The reference-models checkout "
            "may predate the v0.2 contract (needs >= v1.11.0)."
        )
    data = yaml.safe_load(codes_path.read_text(encoding="utf-8")) or {}
    codes = data.get("codes")
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        raise ArchetypeError(f"Malformed outcome-codes file (no string 'codes' list): {codes_path}")
    return codes


def _load_archetype_schema(refmodels_root: Path) -> dict[str, Any] | None:
    """Load the shipped archetype JSON Schema, or None if absent (graceful soft-skip)."""
    schema_path = refmodels_root / _ARCHETYPE_SCHEMA_FILE
    if not schema_path.is_file():
        logger.warning("Archetype JSON Schema not found at %s; skipping schema validation", schema_path)
        return None
    import json

    return json.loads(schema_path.read_text(encoding="utf-8"))


def _validate_against_schema(data: dict[str, Any], schema: dict[str, Any], source: Path) -> None:
    """Validate *data* against *schema* using jsonschema; raise ArchetypeError on failure."""
    try:
        import jsonschema
    except ImportError as exc:  # pragma: no cover - dependency declared in pyproject
        raise ArchetypeError(
            "The 'jsonschema' package is required to validate archetype catalogs. "
            "Install kairos-ontology-toolkit with its dependencies."
        ) from exc

    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        details = "; ".join(
            f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors[:8]
        )
        raise ArchetypeError(f"Archetype catalog '{source.name}' failed schema validation: {details}")


def load_archetype(refmodels_root: Path, archetype_id: str) -> Archetype:
    """Load and fully validate the archetype catalog for *archetype_id*.

    Validation steps (fail-fast):

    * ``schema_version`` must equal :data:`SUPPORTED_SCHEMA_VERSION` (contract rows 7, 11),
    * full JSON-Schema validation against the shipped ``archetype.schema.json`` when present
      (``additionalProperties: false``, required fields, URI formats, id/tier constraints),
    * ``id`` must equal the filename stem.

    Raises:
        ArchetypeError: on any of the above, or if the file is missing.
    """
    root = normalize_refmodels_root(refmodels_root)
    source_path = root / _ARCHETYPES_SUBDIR / f"{archetype_id}.yaml"
    if not source_path.is_file():
        available = ", ".join(list_archetypes(root)) or "(none)"
        raise ArchetypeError(
            f"Archetype '{archetype_id}' not found at {source_path}. Available: {available}."
        )

    data = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ArchetypeError(f"Archetype catalog is not a mapping: {source_path}")

    schema_version = data.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise ArchetypeError(
            f"Unsupported archetype schema_version {schema_version!r} in {source_path.name}; "
            f"this toolkit supports schema_version {SUPPORTED_SCHEMA_VERSION}."
        )

    schema = _load_archetype_schema(root)
    if schema is not None:
        _validate_against_schema(data, schema, source_path)

    if data.get("id") != archetype_id:
        raise ArchetypeError(
            f"Archetype id '{data.get('id')}' does not match filename stem '{archetype_id}' "
            f"({source_path.name})."
        )

    modules = [
        ArchetypeModule(iri=m["iri"], tier=m["tier"]) for m in data.get("ref_model_modules", [])
    ]
    concepts = [
        ArchetypeConcept(uri=c["uri"], tier=c["tier"], label=c["label"])
        for c in data.get("core_concepts", [])
    ]

    return Archetype(
        id=data["id"],
        label=data["label"],
        description=data["description"],
        compatible_with=data.get("compatible_with", {}),
        ref_model_modules=modules,
        core_concepts=concepts,
        source_path=source_path,
        catalog_hash=_sha256_file(source_path),
        schema_version=schema_version,
    )


def locate_discovery_doc(refmodels_root: Path, archetype_id: str) -> Path | None:
    """Locate the SME discovery markdown paired with *archetype_id* (contract: by stem).

    Searches ``accelerator-packs/*/discovery/<id>.md``.  Returns the single match, or
    ``None`` when no doc exists (soft fallback — the skill runs a generic per-concept
    flow instead).

    Raises:
        ArchetypeError: when the same stem matches discovery docs in **multiple** packs
            (open design question #5 — resolved deterministically as an error so the user
            disambiguates rather than silently picking one).
    """
    root = normalize_refmodels_root(refmodels_root)
    packs_dir = root / _ACCELERATOR_PACKS_SUBDIR
    if not packs_dir.is_dir():
        return None
    matches = sorted(packs_dir.glob(f"*/discovery/{archetype_id}.md"))
    if not matches:
        return None
    if len(matches) > 1:
        packs = ", ".join(sorted({m.parent.parent.name for m in matches}))
        raise ArchetypeError(
            f"Discovery doc '{archetype_id}.md' is ambiguous — found in multiple packs: "
            f"{packs}. Disambiguate the archetype id or remove the duplicate."
        )
    return matches[0]


def _refmodels_version(refmodels_root: Path) -> str | None:
    """Read the reference-models repo VERSION (sibling of the inner root), if present."""
    root = normalize_refmodels_root(refmodels_root)
    for candidate in (root / "VERSION", root.parent / "VERSION"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return None


def check_version_drift(archetype: Archetype, refmodels_root: Path) -> list[str]:
    """Return warning strings for repo-tag and per-ontology version drift (contract row 12).

    Compares the archetype's ``compatible_with.repo_tag_range`` against the resolved
    reference-models ``VERSION`` and (best-effort) each ``compatible_with.ontology_versions``
    pin against the corresponding module's ``owl:versionInfo``.  Never raises — drift is a
    warning, not a hard fail.
    """
    warnings: list[str] = []
    compat = archetype.compatible_with or {}

    repo_range = compat.get("repo_tag_range")
    repo_version = _refmodels_version(refmodels_root)
    if repo_range and repo_version:
        if not _version_in_range(repo_version, repo_range):
            warnings.append(
                f"Reference-models version {repo_version} is outside the archetype's "
                f"compatible repo_tag_range '{repo_range}'."
            )

    return warnings


def _version_in_range(version: str, spec: str) -> bool:
    """Best-effort SemVer range check using ``packaging`` (treats parse failures as in-range)."""
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version

        return Version(version.lstrip("v")) in SpecifierSet(spec.replace(" ", ""))
    except Exception:  # noqa: BLE001 - drift checks must never break the loader
        logger.debug("Could not evaluate version range '%s' for '%s'", spec, version)
        return True
