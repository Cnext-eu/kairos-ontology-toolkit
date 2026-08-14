# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Materialized YAML inventory generation for ontologies and reference models (DD-044).

Produces structured YAML files that capture classes, properties, and specialization
trees.  These inventories are consumed by LLM-based tools (``analyse-sources``,
``propose-alignment``) and ``coverage-report`` as a cached, designer-reviewable
alternative to re-parsing TTL files on every run.

Inventory files live in ``referencemodels-unpacked/`` and are committed to git.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from rdflib import Graph, OWL, RDF, RDFS

from .analyse_sources import parse_reference_model
from .determinism import resolve_generated_at
from .pattern_loader import _PATTERNS_SUBDIR

logger = logging.getLogger(__name__)

INVENTORY_VERSION = "2.0"


class InventoryMigrationRequiredError(ValueError):
    """Raised when a runtime reader encounters a retired stem-named inventory."""


@dataclass(frozen=True)
class LegacyInventoryFile:
    """A stem-named reference inventory that must be migrated before it is read."""

    path: Path
    source_paths: tuple[Path, ...]
    canonical_filenames: tuple[str, ...]
    error: str | None = None


def compute_source_hash(path: Path) -> str:
    """Return the SHA-256 hex digest of a source TTL file's bytes."""
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def inventory_filename(
    ttl_path: Path,
    *,
    ref_models_dir: Path | None = None,
) -> str:
    """Return the inventory filename for a source TTL (DD-054).

    Reference-model modules are namespaced by their owning model so that
    same-named modules from different models (e.g. ``party.ttl`` in BSP, IMO,
    DCSA…) no longer collide into a single ``{stem}-inventory.yaml`` (the
    last-write-wins data-loss bug).  Hub-owned ontologies keep plain stem naming
    because their stems are unique within a hub.

    Naming rules:
      - Reference-model TTL under ``derived-ontologies/`` →
        ``{model}-{stem}-inventory.yaml`` (model = the path segment directly
        after ``derived-ontologies``, lower-cased).
      - Anything else → ``{stem}-inventory.yaml``.

    The result is deterministic and used by both ``generate-inventory`` and
    ``check_inventories`` so source→inventory mapping always agrees.
    """
    stem = ttl_path.stem
    model = _ref_model_id(ttl_path, ref_models_dir=ref_models_dir)
    if model:
        return f"{model}-{stem}-inventory.yaml"
    return f"{stem}-inventory.yaml"


def _ref_model_id(ttl_path: Path, *, ref_models_dir: Path | None) -> str | None:
    """Return the lower-cased reference-model id owning *ttl_path*, or None.

    The model id is the path segment immediately following ``derived-ontologies``
    (e.g. ``BSP``, ``DCSA``).  Intermediate segments such as DCSA's
    ``shared-kernel`` are ignored — only the model directory disambiguates.
    """
    parts: tuple[str, ...]
    if ref_models_dir is not None:
        try:
            parts = ttl_path.resolve().relative_to(ref_models_dir.resolve()).parts
        except ValueError:
            parts = ttl_path.parts
    else:
        parts = ttl_path.parts

    marker = "derived-ontologies"
    if marker in parts:
        idx = parts.index(marker)
        if idx + 1 < len(parts):
            return parts[idx + 1].lower()
    return None


def _provenance_path(ttl_path: Path, *, relative_to: Path | None) -> str:
    """Portable, committed-artifact-safe provenance for *ttl_path* (POSIX, relative).

    An absolute machine-local path (e.g. ``C:\\Git\\hub\\...``) baked into a
    committed inventory produces spurious diffs for every other clone of the
    hub (issue #404). Relativising to *relative_to* — the same root passed to
    :func:`inventory_filename` at the call site — keeps ``generated_from``
    portable while staying symmetric with :func:`_ref_model_id`'s own fallback
    chain, which is what makes write and read derivation agree. Falls back to
    a ``derived-ontologies``-rooted path (mirroring the read-side marker
    search in :func:`_ref_model_id`), then to the bare filename.
    """
    if relative_to is not None:
        try:
            return ttl_path.resolve().relative_to(relative_to.resolve()).as_posix()
        except (ValueError, OSError):
            pass
    parts = ttl_path.parts
    if "derived-ontologies" in parts:
        idx = parts.index("derived-ontologies")
        return PurePosixPath(*parts[idx:]).as_posix()
    return ttl_path.name


def is_archived_ref_model_source(ttl_path: Path, *, ref_models_dir: Path | None = None) -> bool:
    """Return True when *ttl_path* is under an archived reference-model version."""
    if ref_models_dir is not None:
        try:
            parts = ttl_path.resolve().relative_to(ref_models_dir.resolve()).parts
        except ValueError:
            parts = ttl_path.parts
    else:
        parts = ttl_path.parts
    return any(part.lower() == "archive" for part in parts)


#: Mirrors ``core/pattern_loader.py``'s ``_PATTERNS_SUBDIR`` ("blueprints/patterns", a
#: two-segment path — unlike the single-segment ``archive`` check above, so this is
#: matched as a subsequence over ``.parts``, not a single-part membership test).
#: ``pattern_loader`` (and its ``archetype_loader`` dependency) import cleanly with no
#: module-level cycle back to this module — verified before adding this import — so
#: the constant is imported directly rather than duplicated as a literal here.
_PATTERN_LIBRARY_SUBDIR_PARTS: tuple[str, ...] = tuple(
    part.lower() for part in _PATTERNS_SUBDIR.parts
)


def is_pattern_template_source(ttl_path: Path, *, ref_models_dir: Path | None = None) -> bool:
    """Return True when *ttl_path* is a pattern-library authoring stub, not real content.

    ``blueprints/patterns/<id>/template.ttl`` files (see ``core/pattern_loader.py``)
    are copyable examples: they carry placeholder ``https://example.org/`` namespaces
    and deliberately no ``owl:versionInfo``. ``_ref_model_id`` only namespaces paths
    under ``derived-ontologies``, so every pattern's ``template.ttl`` collapses onto the
    same ``template-inventory.yaml`` name — a collision that scales with the pattern
    library, not a two-file accident (issue #406). These files should never have been
    inventoried in the first place, so they are excluded at the source here rather than
    patched around downstream.

    Matches ``blueprints/patterns`` as a two-segment subsequence of *ttl_path*'s parts
    (unlike the single-segment ``archive`` check in
    :func:`is_archived_ref_model_source`), and normalizes relative to *ref_models_dir*
    the same way that function does, so the predicate does not miss on an
    un-normalized root.
    """
    if ref_models_dir is not None:
        try:
            parts = ttl_path.resolve().relative_to(ref_models_dir.resolve()).parts
        except ValueError:
            parts = ttl_path.parts
    else:
        parts = ttl_path.parts

    parts_lower = tuple(p.lower() for p in parts)
    n = len(_PATTERN_LIBRARY_SUBDIR_PARTS)
    return any(
        parts_lower[i : i + n] == _PATTERN_LIBRARY_SUBDIR_PARTS
        for i in range(len(parts_lower) - n + 1)
    )


def iter_reference_inventory_sources(ref_models_dir: Path) -> list[Path]:
    """Return current reference-model TTLs that should produce/check inventories."""
    return [
        ttl
        for ttl in sorted(ref_models_dir.glob("**/*.ttl"))
        if not is_archived_ref_model_source(ttl, ref_models_dir=ref_models_dir)
        and not is_pattern_template_source(ttl, ref_models_dir=ref_models_dir)
    ]


def _canonical_filename_from_generated_from(inventory: dict[str, Any]) -> str | None:
    """Derive the required filename from inventory provenance when it is a ref model."""
    generated_from = inventory.get("generated_from")
    if not generated_from or generated_from == "(graph)":
        return None
    source_path = Path(str(generated_from))
    if _ref_model_id(source_path, ref_models_dir=None) is None:
        return None
    return inventory_filename(source_path)


def find_legacy_inventory_files(
    *,
    ref_models_dir: Path | None,
    inventory_dir: Path,
    ontology_dir: Path | None = None,
) -> list[LegacyInventoryFile]:
    """Find retired stem-named inventories for namespaced reference-model sources.

    A live local ontology canonically owns its ``{stem}-inventory.yaml`` filename.
    Those files are excluded before provenance inspection so stale or malformed local
    inventories are handled by the normal freshness check instead of ref migration.
    """
    if ref_models_dir is None or not ref_models_dir.is_dir() or not inventory_dir.is_dir():
        return []

    local_inventory_names = (
        {inventory_filename(source_path) for source_path in sorted(ontology_dir.glob("**/*.ttl"))}
        if ontology_dir is not None and ontology_dir.is_dir()
        else set()
    )
    sources_by_legacy_name: dict[str, list[Path]] = {}
    for source_path in iter_reference_inventory_sources(ref_models_dir):
        canonical = inventory_filename(source_path, ref_models_dir=ref_models_dir)
        legacy_name = f"{source_path.stem}-inventory.yaml"
        if canonical != legacy_name:
            sources_by_legacy_name.setdefault(legacy_name, []).append(source_path)

    findings: list[LegacyInventoryFile] = []
    for legacy_name, source_paths in sorted(sources_by_legacy_name.items()):
        path = inventory_dir / legacy_name
        if not path.is_file():
            continue
        if legacy_name in local_inventory_names:
            continue

        ordered_sources = tuple(sorted(source_paths))
        canonical_filenames = tuple(
            sorted(
                {
                    inventory_filename(source_path, ref_models_dir=ref_models_dir)
                    for source_path in ordered_sources
                }
            )
        )
        error: str | None = None
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            error = f"cannot read valid YAML: {exc}"
        else:
            if not isinstance(raw, dict):
                error = "does not contain a YAML mapping"
            else:
                provenance_filename = _canonical_filename_from_generated_from(raw)
                if provenance_filename == path.name:
                    # A valid local-domain inventory happens to share the old stem.
                    continue
                if provenance_filename and provenance_filename not in canonical_filenames:
                    error = (
                        "provenance identifies a different reference-model source "
                        f"({provenance_filename})"
                    )

        findings.append(
            LegacyInventoryFile(
                path=path,
                source_paths=ordered_sources,
                canonical_filenames=canonical_filenames,
                error=error,
            )
        )
    return findings


def legacy_inventory_error(finding: LegacyInventoryFile) -> str:
    """Return an actionable diagnostic for a retired inventory filename."""
    targets = ", ".join(finding.canonical_filenames)
    message = (
        f"{finding.path.name} uses retired stem-based reference inventory naming; "
        f"migrate it to {targets} with `kairos-ontology migrate --hub <hub>`."
    )
    if finding.error:
        return (
            f"{message} Migration cannot proceed until the legacy file is fixed: {finding.error}."
        )
    if len(finding.canonical_filenames) > 1:
        return (
            f"{message} Its stem collides across reference models, so the toolkit will not "
            "guess which canonical inventory owns it. Preserve it, resolve the collision, "
            "then rerun the migration."
        )
    return message


def generate_inventory(
    ttl_path: Path | None = None,
    *,
    graph: Graph | None = None,
    domain_name: str | None = None,
    include_specializations: bool = True,
    catalog_path: Path | None = None,
    relative_to: Path | None = None,
) -> dict[str, Any]:
    """Generate a materialized inventory from an ontology or reference model.

    Delegates to ``parse_reference_model()`` with ``include_specializations=True``
    and wraps the result in an inventory envelope with version and provenance.

    Args:
        ttl_path: Path to a TTL file (mutually exclusive with *graph*).
        graph: Pre-loaded rdflib Graph.
        domain_name: Override domain name.
        include_specializations: Walk ``subClassOf`` downward (default True).
        relative_to: Root *ttl_path*'s ``generated_from`` provenance is made
            relative to (issue #404) — pass the same root used to compute the
            inventory's filename via :func:`inventory_filename` so
            ``generated_from`` derivation stays symmetric with it. ``None``
            (the default) falls back to a ``derived-ontologies``-rooted path
            or the bare filename; see :func:`_provenance_path`.

    Returns:
        Dict suitable for YAML serialization.
    """
    load_result = None
    if ttl_path is not None:
        from .ontology_loader import SemanticProfile, load_ontology

        load_result = load_ontology(
            ttl_path,
            catalog_path=catalog_path,
            profile=SemanticProfile.KAIROS_DESIGN,
        )
        parsed = _inventory_view_from_index(
            load_result.semantic_index,
            load_result.graph,
            domain_name=domain_name or ttl_path.stem,
            include_specializations=include_specializations,
        )
    else:
        parsed = parse_reference_model(
            graph=graph,
            domain_name=domain_name,
            include_specializations=include_specializations,
        )

    inventory: dict[str, Any] = {
        "version": INVENTORY_VERSION,
        "generated_at": resolve_generated_at().isoformat(timespec="seconds"),
        "generated_from": _provenance_path(ttl_path, relative_to=relative_to)
        if ttl_path
        else "(graph)",
        "source_sha256": compute_source_hash(ttl_path) if ttl_path else None,
        "closure_hash": load_result.closure_hash if load_result else None,
        "semantic_profile": (load_result.profile.value if load_result else "asserted"),
        "semantic_index_version": (load_result.semantic_index.version if load_result else None),
        "import_complete": load_result.complete if load_result else True,
        "imports": (
            [
                {
                    "ontology_iri": entry.ontology_iri,
                    "source_identity": entry.source_identity,
                    "parent_import": entry.parent_import,
                    "import_depth": entry.import_depth,
                    "ontology_version": entry.ontology_version,
                    "source_sha256": entry.source_sha256,
                }
                for entry in load_result.manifest
            ]
            if load_result
            else []
        ),
        "domain_name": parsed["domain_name"],
        "classes": parsed["classes"],
    }

    return inventory


def _inventory_view_from_index(
    index,
    graph: Graph,
    *,
    domain_name: str,
    include_specializations: bool,
) -> dict[str, Any]:
    """Render the compatibility inventory view from the semantic index."""
    for ontology in graph.subjects(RDF.type, OWL.Ontology):
        label = graph.value(ontology, RDFS.label)
        if label:
            domain_name = str(label)
            break

    property_by_uri = {item.uri: item for item in index.properties}

    def render_property(link, *, inherited: bool) -> dict[str, Any]:
        prop = property_by_uri[link.uri]
        range_uri = prop.ranges[0].uri if prop.ranges else ""
        return {
            "uri": prop.uri,
            "name": prop.name,
            "label": prop.label,
            "comment": prop.comment,
            "range": range_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1],
            "range_uri": range_uri,
            "type": prop.property_type,
            "inherited": inherited,
            "provenance": {
                "source_identity": link.provenance.source_identity,
                "import_depth": link.provenance.import_depth,
                "asserted": link.provenance.asserted,
            },
        }

    class_by_uri = {item.uri: item for item in index.classes}
    classes: list[dict[str, Any]] = []
    for cls in index.classes:
        item: dict[str, Any] = {
            "uri": cls.uri,
            "name": cls.name,
            "label": cls.label,
            "comment": cls.comment,
            "provenance": {
                "source_identity": cls.provenance.source_identity,
                "import_depth": cls.provenance.import_depth,
                "asserted": cls.provenance.asserted,
            },
            "properties": [render_property(link, inherited=False) for link in cls.direct_properties]
            + [render_property(link, inherited=True) for link in cls.inherited_properties],
        }
        if include_specializations:
            specializations = []
            for descendant in cls.descendants:
                child = class_by_uri[descendant.uri]
                specializations.append(
                    {
                        "class": child.name,
                        "class_uri": child.uri,
                        "distance": descendant.distance,
                        "properties": [
                            render_property(link, inherited=False)
                            for link in child.direct_properties
                        ],
                    }
                )
            item["specializations"] = specializations
        classes.append(item)
    return {"domain_name": domain_name, "classes": classes}


def write_inventory(inventory: dict[str, Any], output_path: Path) -> Path:
    """Write an inventory dict to a YAML file.

    Creates parent directories if needed.  Returns the written path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(
            inventory,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
            width=120,
        )
    logger.info("Wrote inventory to %s", output_path)
    return output_path


def load_inventory(path: Path, *, allow_legacy: bool = False) -> dict[str, Any]:
    """Load a previously generated inventory from YAML.

    Raises:
        FileNotFoundError: If the path does not exist.
        yaml.YAMLError: If the file is not valid YAML.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Inventory file {path} does not contain a YAML mapping")
    expected_filename = _canonical_filename_from_generated_from(data)
    if not allow_legacy and expected_filename and path.name != expected_filename:
        finding = LegacyInventoryFile(
            path=path,
            source_paths=(),
            canonical_filenames=(expected_filename,),
        )
        raise InventoryMigrationRequiredError(legacy_inventory_error(finding))
    return data


@dataclass
class InventoryCheckReport:
    """Result of a deterministic inventory freshness check (DD-047).

    Each list holds the inventory key (filename without the ``-inventory.yaml``
    suffix, e.g. ``bsp-party``); *orphan* holds full inventory file names.
    """

    missing: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)
    unbuildable: list[str] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)
    orphan: list[str] = field(default_factory=list)
    migration_required: list[str] = field(default_factory=list)

    @property
    def is_blocking(self) -> bool:
        """True when an inventory is missing, stale, or requires format migration.

        ``unbuildable`` is deliberately excluded — exactly like ``unverifiable`` — it is
        non-blocking by default and only escalates under ``--strict`` (see
        ``check_inventory_cmd``'s ``blocking`` derivation).
        """
        return bool(self.missing or self.stale or self.migration_required)

    @property
    def has_warnings(self) -> bool:
        """True when an unverifiable, unbuildable, or orphan inventory exists."""
        return bool(self.unverifiable or self.unbuildable or self.orphan)


def _source_has_classes(ttl_path: Path, *, include_specializations: bool) -> bool:
    """Return True if a source TTL yields at least one class (mirrors generate-inventory).

    Raises whatever :func:`~kairos_ontology.core.analyse_sources.parse_reference_model`
    raises when *ttl_path* cannot be parsed at all — the caller classifies that as
    ``unbuildable`` rather than guessing. A source that cannot be parsed is not
    "missing an inventory" (running ``generate-inventory`` cannot fix it either), so
    silently treating it as if it had classes collapsed a closure failure into a
    misleading, unactionable "missing" remediation (see :class:`InventoryCheckReport`).
    """
    parsed = parse_reference_model(ttl_path, include_specializations=include_specializations)
    return bool(parsed["classes"])


def check_inventories(
    *,
    ontology_dir: Path | None,
    ref_models_dir: Path | None,
    inventory_dir: Path,
    catalog_path: Path | None = None,
) -> InventoryCheckReport:
    """Deterministically verify that ``referencemodels-unpacked/`` is present and fresh (DD-047).

    For every source TTL under *ontology_dir* / *ref_models_dir* that would yield
    classes, checks that a matching inventory file (named via
    :func:`inventory_filename`, e.g. ``bsp-party-inventory.yaml``) exists and that
    its stored ``source_sha256`` matches the current file content.

    Classification:
      - **missing**  — source has classes but no inventory file → blocking.
      - **stale**    — inventory exists but its stored hash differs → blocking.
      - **unverifiable** — inventory exists but has no stored hash (pre-DD-047) → warn.
      - **unbuildable** — the source TTL itself cannot be parsed (a closure failure,
        not staleness) → warn by default, ``--strict``-eligible. ``generate-inventory``
        cannot produce a fresh inventory for a source that does not parse, so this is
        kept distinct from **missing**/**stale** (whose remediation — "run
        generate-inventory" — is actionable and would not be for this case).
      - **ok**       — inventory exists and hash matches.
      - **orphan**   — inventory file with no corresponding source TTL → warn.
      - **migration_required** — retired stem-named ref inventory → blocking.
    """
    report = InventoryCheckReport()
    seen_files: set[str] = set()
    legacy_files = find_legacy_inventory_files(
        ref_models_dir=ref_models_dir,
        inventory_dir=inventory_dir,
        ontology_dir=ontology_dir,
    )
    report.migration_required = [legacy_inventory_error(finding) for finding in legacy_files]
    legacy_names = {finding.path.name for finding in legacy_files}

    sources: list[tuple[Path, bool]] = []
    if ref_models_dir and ref_models_dir.is_dir():
        sources += [(p, True) for p in iter_reference_inventory_sources(ref_models_dir)]
    if ontology_dir and ontology_dir.is_dir():
        sources += [(p, False) for p in sorted(ontology_dir.glob("**/*.ttl"))]

    for ttl_file, include_specializations in sources:
        fname = inventory_filename(
            ttl_file,
            ref_models_dir=ref_models_dir if include_specializations else None,
        )
        key = fname[: -len("-inventory.yaml")]
        yaml_path = inventory_dir / fname
        seen_files.add(fname)

        if not yaml_path.exists():
            try:
                has_classes = _source_has_classes(
                    ttl_file, include_specializations=include_specializations
                )
            except Exception:
                report.unbuildable.append(key)
                continue
            if has_classes:
                report.missing.append(key)
            continue

        try:
            inv = load_inventory(yaml_path)
        except Exception:
            report.stale.append(key)
            continue

        if str(inv.get("version", "")) != INVENTORY_VERSION:
            report.migration_required.append(
                f"{yaml_path.name} uses inventory schema "
                f"{inv.get('version', 'unknown')}; regenerate schema {INVENTORY_VERSION}."
            )
            continue

        stored = inv.get("closure_hash")
        if not stored:
            report.unverifiable.append(key)
            continue

        try:
            current = generate_inventory(
                ttl_file,
                include_specializations=include_specializations,
                catalog_path=catalog_path,
            ).get("closure_hash")
        except Exception:
            # The source no longer parses — a closure failure, not a hash mismatch.
            # "stale" implies regenerating would fix it; it would not here.
            report.unbuildable.append(key)
            continue
        if stored != current:
            report.stale.append(key)
        else:
            report.ok.append(key)

    if inventory_dir.is_dir():
        for inv_file in sorted(inventory_dir.glob("*-inventory.yaml")):
            if inv_file.name not in seen_files and inv_file.name not in legacy_names:
                report.orphan.append(inv_file.name)

    return report


@dataclass
class DomainScope:
    """Domain-scoped inventory readiness (toolkit-optimizations F5).

    Built by :func:`scope_inventory_report` from a repository-wide
    :class:`InventoryCheckReport` plus a domain→inventory-key mapping. Lets skill
    workflows report whether the *active* domain is ready separately from unrelated
    repository-wide failures.

    ``keys`` is the set of inventory keys (e.g. ``bsp-party``) owned by the selected
    domain(s). The status lists are the intersection of that set with the
    repository-wide report. ``unresolved`` holds domain import URIs the catalog
    could not resolve to a source TTL (surfaced so a scope gap is never silent).
    """

    domains: list[str] = field(default_factory=list)
    keys: set[str] = field(default_factory=set)
    missing: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)
    unbuildable: list[str] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    migration_required: list[str] = field(default_factory=list)

    @property
    def is_blocking(self) -> bool:
        """True when an in-scope inventory is missing or stale.

        ``unbuildable`` — like ``unverifiable`` — is deliberately excluded; it is
        non-blocking by default and only escalates under ``--strict``.
        """
        return bool(self.missing or self.stale or self.migration_required)


def resolve_domain_inventory_keys(
    domains: list[str],
    *,
    ref_models_dir: Path | None,
    catalog_path: Path | None,
    accelerator: str | None = None,
) -> tuple[dict[str, set[str]], dict[str, list[str]]]:
    """Map each selected data-domain to its reference-model inventory keys (F5).

    Resolves each domain's import URIs (from the accelerator ``data-domains.yaml``)
    through the catalog to concrete source TTL paths, then derives the inventory key
    via :func:`inventory_filename` (matching the keys produced by
    :func:`check_inventories`). This is the deterministic domain→inventory mapping
    the repository-wide check lacks.

    Returns ``(keys_by_domain, unresolved_by_domain)`` where the first maps each
    (case-insensitive substring-matched) domain id to its set of inventory keys, and
    the second maps it to the list of import URIs that could not be resolved.
    """
    from .analyse_sources import load_data_domains
    from .catalog_utils import CatalogResolver

    keys_by_domain: dict[str, set[str]] = {}
    unresolved_by_domain: dict[str, list[str]] = {}
    if not ref_models_dir or not ref_models_dir.is_dir():
        return keys_by_domain, unresolved_by_domain

    data_domains = load_data_domains(ref_models_dir, accelerator=accelerator)
    if not data_domains:
        return keys_by_domain, unresolved_by_domain

    resolver = CatalogResolver(catalog_path) if catalog_path else None
    lower_filter = [d.lower() for d in domains]

    for domain_id, meta in data_domains.items():
        if lower_filter and not any(f in domain_id.lower() for f in lower_filter):
            continue
        keys: set[str] = set()
        unresolved: list[str] = []
        for uri in meta.get("uris", []) or []:
            ttl = resolver.resolve(uri) if resolver else None
            if ttl is None:
                unresolved.append(uri)
                continue
            keys.add(
                inventory_filename(Path(ttl), ref_models_dir=ref_models_dir)[
                    : -len("-inventory.yaml")
                ]
            )
        keys_by_domain[domain_id] = keys
        if unresolved:
            unresolved_by_domain[domain_id] = unresolved

    return keys_by_domain, unresolved_by_domain


def scope_inventory_report(
    report: InventoryCheckReport,
    keys_by_domain: dict[str, set[str]],
    unresolved_by_domain: dict[str, list[str]] | None = None,
) -> DomainScope:
    """Intersect a repository-wide report with the selected domains' inventory keys.

    The repository-wide *report* is unchanged (still surfaces global failures); this
    projects it onto the active domains so a skill workflow can decide readiness
    without being blocked by unrelated missing/stale inventories (F5).
    """
    scope = DomainScope(domains=sorted(keys_by_domain))
    for keys in keys_by_domain.values():
        scope.keys |= keys
    scope.missing = sorted(k for k in report.missing if k in scope.keys)
    scope.stale = sorted(k for k in report.stale if k in scope.keys)
    scope.unverifiable = sorted(k for k in report.unverifiable if k in scope.keys)
    scope.unbuildable = sorted(k for k in report.unbuildable if k in scope.keys)
    scope.ok = sorted(k for k in report.ok if k in scope.keys)
    # Stem-named reference inventories are globally unsafe: a scoped workflow must
    # not silently consume one while another domain is being modeled.
    scope.migration_required = sorted(report.migration_required)
    if unresolved_by_domain:
        merged: list[str] = []
        for uris in unresolved_by_domain.values():
            merged.extend(uris)
        scope.unresolved = sorted(set(merged))
    return scope


#: Explicit scoped-inventory status labels (never the ambiguous "(none matched)").
DIRECT_PROFILE = "direct-profile"
ACCELERATOR_PROFILE = "accelerator-profile"
NO_PROFILE = "no-profile"


def classify_domain_scope(
    domain: str,
    keys_by_domain: dict[str, set[str]],
    report: "InventoryCheckReport",
) -> tuple[str, set[str]]:
    """Classify one requested ``--domains`` token's scoped-inventory readiness.

    A scoped ``check-inventory`` result must never claim a domain is ready via the
    ambiguous ``"(none matched)"`` wording (toolkit-optimizations DX finding
    "check-inventory reports (none matched) and then says the domain is ready").
    Returns ``(status, keys)`` where *status* is one of:

    - :data:`ACCELERATOR_PROFILE`: the domain matched an accelerator
      ``data-domains.yaml`` entry (via :func:`resolve_domain_inventory_keys`) that
      resolved to one or more inventory keys.
    - :data:`DIRECT_PROFILE`: no accelerator registry entry resolved keys, but the
      domain name directly matches one or more materialized inventory stems already
      present in the repository-wide *report* — the inventory set that makes this
      scoped result ready even without accelerator ownership metadata.
    - :data:`NO_PROFILE`: neither an accelerator registry entry nor a direct
      inventory-stem match was found for *domain* — the scoped result cannot be
      evaluated for it (surfaced explicitly rather than silently dropped).
    """
    lower = domain.lower()
    keys: set[str] = set()
    for domain_id, domain_keys in keys_by_domain.items():
        if lower in domain_id.lower() or domain_id.lower() in lower:
            keys |= domain_keys
    if keys:
        return ACCELERATOR_PROFILE, keys

    all_keys = (
        set(report.ok)
        | set(report.missing)
        | set(report.stale)
        | set(report.unverifiable)
        | set(report.unbuildable)
    )
    direct = {k for k in all_keys if lower in k.lower() or k.lower() in lower}
    if direct:
        return DIRECT_PROFILE, direct

    return NO_PROFILE, set()
