# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Projection orchestrator - generates downstream artifacts."""

from __future__ import annotations

import json
import logging
import traceback as _tb
from collections.abc import Iterable, Mapping
from datetime import datetime
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from .determinism import generated_at_iso, resolve_generated_at
from .hub_utils import is_domain_ontology_stem
from .projections.uri_utils import extract_local_name
from .projections.shared import OntologyClassInfo

if TYPE_CHECKING:
    from .compiler.plan import CompilePlan


class OutputCategory(StrEnum):
    """High-level placement of a projection target's generated artifacts."""

    STANDARD = "standard"
    MEDALLION = "medallion"
    ARCHITECTURE = "architecture"
    REPORTS = "reports"
    EXTERNAL = "external"


class ExecutionPhase(StrEnum):
    """When a target runs relative to the per-domain projection loop."""

    PER_DOMAIN = "per-domain"
    POST_DOMAIN = "post-domain"


class ExtensionDiscovery(Protocol):
    """Callable that locates an external target's extension for one domain."""

    def __call__(
        self,
        ontology_name: str,
        source_file: Path,
        extensions_dir: Optional[Path],
    ) -> Optional[Path]: ...


class ExternalProjector(Protocol):
    """Callable that projects one domain for a target contributed outside core."""

    def __call__(
        self,
        *,
        graph: Graph,
        namespace: Optional[str],
        ontology_name: str,
        ext_path: Optional[Path],
        ontology_metadata: Dict[str, Any],
    ) -> Dict[str, str]: ...


class ExternalCompilePlanProjector(Protocol):
    """Callable that projects an extension from the canonical compiler plan."""

    def __call__(
        self,
        *,
        compile_plan: CompilePlan,
        ext_path: Optional[Path],
        ontology_metadata: Dict[str, Any],
    ) -> Dict[str, str]: ...


@dataclass(frozen=True, slots=True)
class ExternalDispatch:
    """Extension discovery and projection callbacks for an external target."""

    discover_ext: ExtensionDiscovery
    project: ExternalProjector
    project_compile_plan: Optional[ExternalCompilePlanProjector] = None


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """The complete registration record for one canonical projection target."""

    canonical_name: str
    output_subdir: str
    output_category: OutputCategory
    execution_phase: ExecutionPhase = ExecutionPhase.PER_DOMAIN
    aliases: tuple[str, ...] = ()
    compatibility_name: Optional[str] = None
    include_in_all: bool = True
    external_dispatch: Optional[ExternalDispatch] = None

    @property
    def accepted_names(self) -> tuple[str, ...]:
        """Return the canonical name followed by its accepted aliases."""
        return (self.canonical_name, *self.aliases)

    @property
    def valid_target_name(self) -> str:
        """Name exposed through the historical :data:`VALID_TARGETS` API."""
        return self.compatibility_name or self.canonical_name

    def output_path(self, root: Path) -> Path:
        """Resolve this target's registry-owned output location below *root*."""
        return root.joinpath(*PurePosixPath(self.output_subdir).parts)


_TARGET_REGISTRY: dict[str, TargetSpec] = {}
TARGET_REGISTRY: Mapping[str, TargetSpec] = MappingProxyType(_TARGET_REGISTRY)
RETIRED_COMPILER_TARGETS = ("dbt", "silver")
COMPILE_PLAN_ONLY_TARGETS = ("powerbi", "gold", "mdm-profile")

# Compatibility list retained for callers that import or hold a reference to it.
# Its contents are refreshed exclusively from TARGET_REGISTRY.
VALID_TARGETS: list[str] = []


def _validate_target_name(name: str, *, label: str) -> None:
    if not name or name != name.strip():
        raise ValueError(f"{label} must be a non-empty, trimmed string")
    if name == "all":
        raise ValueError(f"{label} 'all' is reserved")
    if not all(char.isalnum() or char in {"-", "_"} for char in name):
        raise ValueError(f"{label} '{name}' contains unsupported characters")


def _validate_target_spec(spec: TargetSpec) -> None:
    _validate_target_name(spec.canonical_name, label="Target name")
    retired_names = set(RETIRED_COMPILER_TARGETS)
    if spec.canonical_name in retired_names or retired_names.intersection(spec.aliases):
        raise ValueError(
            "Projection target names 'dbt' and 'silver' are reserved for the compile command"
        )
    seen = {spec.canonical_name}
    for alias in spec.aliases:
        _validate_target_name(alias, label="Target alias")
        if alias in seen:
            raise ValueError(f"Target alias '{alias}' is duplicated")
        seen.add(alias)

    if spec.compatibility_name is not None and spec.compatibility_name not in seen:
        raise ValueError(
            "compatibility_name must be the canonical target name or one of its aliases"
        )

    subdir = spec.output_subdir.replace("\\", "/")
    path = PurePosixPath(subdir)
    if (
        not subdir
        or subdir != spec.output_subdir
        or path.is_absolute()
        or path == PurePosixPath(".")
        or ".." in path.parts
        or ":" in subdir
    ):
        raise ValueError(
            f"Target '{spec.canonical_name}' output_subdir must be a relative POSIX path"
        )

    dispatch = spec.external_dispatch
    if dispatch is not None:
        if not callable(dispatch.discover_ext) or not callable(dispatch.project):
            raise ValueError(
                f"Target '{spec.canonical_name}' external dispatch callbacks must be callable"
            )
        if dispatch.project_compile_plan is not None and not callable(
            dispatch.project_compile_plan
        ):
            raise ValueError(
                f"Target '{spec.canonical_name}' compiler-plan callback must be callable"
            )
        if spec.execution_phase is ExecutionPhase.POST_DOMAIN:
            raise ValueError("External post-domain targets are not supported")


def _refresh_valid_targets() -> None:
    VALID_TARGETS[:] = [spec.valid_target_name for spec in _TARGET_REGISTRY.values()]


def _register_target_spec(spec: TargetSpec) -> TargetSpec:
    _validate_target_spec(spec)
    existing = _TARGET_REGISTRY.get(spec.canonical_name)
    if existing == spec:
        return existing
    if existing is not None:
        raise ValueError(
            f"Target '{spec.canonical_name}' is already registered with different metadata"
        )

    requested_names = set(spec.accepted_names)
    for registered in _TARGET_REGISTRY.values():
        collisions = requested_names.intersection(registered.accepted_names)
        if collisions:
            collision = sorted(collisions)[0]
            raise ValueError(
                f"Target name or alias '{collision}' is already registered "
                f"for '{registered.canonical_name}'"
            )

    _TARGET_REGISTRY[spec.canonical_name] = spec
    _refresh_valid_targets()
    return spec


for _target_spec in (
    TargetSpec("neo4j", "neo4j", OutputCategory.STANDARD),
    TargetSpec("azure-search", "azure-search", OutputCategory.STANDARD),
    TargetSpec("a2ui", "a2ui", OutputCategory.STANDARD),
    TargetSpec("prompt", "prompt", OutputCategory.STANDARD),
    TargetSpec(
        "powerbi",
        "powerbi",
        OutputCategory.STANDARD,
        aliases=("gold",),
        compatibility_name="gold",
        include_in_all=False,
    ),
    TargetSpec(
        "report",
        "reports/details",
        OutputCategory.REPORTS,
        execution_phase=ExecutionPhase.POST_DOMAIN,
    ),
    TargetSpec("ddd", "architecture/ddd", OutputCategory.ARCHITECTURE),
):
    _register_target_spec(_target_spec)
del _target_spec


def get_target_spec(name: str) -> Optional[TargetSpec]:
    """Resolve a canonical target name or alias to its registry specification."""
    canonical = _TARGET_REGISTRY.get(name)
    if canonical is not None:
        return canonical
    return next(
        (spec for spec in _TARGET_REGISTRY.values() if name in spec.aliases),
        None,
    )


def projection_target_choices() -> tuple[str, ...]:
    """Return canonical target names in stable user-visible CLI order."""
    return tuple(_TARGET_REGISTRY)


def projection_targets_for_all() -> tuple[str, ...]:
    """Return canonical built-in targets included by ``--target all`` in order."""
    return tuple(spec.canonical_name for spec in _TARGET_REGISTRY.values() if spec.include_in_all)


def register_target(
    name: str,
    *,
    discover_ext: ExtensionDiscovery,
    project: ExternalProjector,
    project_compile_plan: Optional[ExternalCompilePlanProjector] = None,
    output_subdir: str,
    aliases: Iterable[str] = (),
    output_category: OutputCategory | str = OutputCategory.EXTERNAL,
    execution_phase: ExecutionPhase | str = ExecutionPhase.PER_DOMAIN,
    include_in_all: bool = False,
) -> None:
    """Register one external projection target and all of its metadata.

    Repeating an identical registration is a no-op. Reusing any canonical name or
    alias with different metadata raises :class:`ValueError`. The default keeps
    external targets opt-in rather than adding them to ``--target all``.
    """
    try:
        category = OutputCategory(output_category)
    except ValueError as exc:
        raise ValueError(f"Unknown output category '{output_category}'") from exc
    try:
        phase = ExecutionPhase(execution_phase)
    except ValueError as exc:
        raise ValueError(f"Unknown execution phase '{execution_phase}'") from exc

    _register_target_spec(
        TargetSpec(
            canonical_name=name,
            aliases=tuple(aliases),
            compatibility_name=name,
            output_subdir=output_subdir,
            output_category=category,
            execution_phase=phase,
            include_in_all=include_in_all,
            external_dispatch=ExternalDispatch(
                discover_ext=discover_ext,
                project=project,
                project_compile_plan=project_compile_plan,
            ),
        )
    )


def project_downstream_compile_plan(
    target: str,
    compile_plan: CompilePlan,
    *,
    ext_path: Optional[Path] = None,
    ontology_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Project one optional downstream target from a typed compiler plan."""
    target_spec = get_target_spec(target)
    if target_spec is None:
        raise ValueError(f"Unknown projection target '{target}'")
    if target_spec.canonical_name == "powerbi":
        from .projections.medallion_gold_projector import generate_gold_from_compile_plan

        return generate_gold_from_compile_plan(compile_plan)
    dispatch = target_spec.external_dispatch
    if dispatch is None or dispatch.project_compile_plan is None:
        raise ValueError(
            f"Projection target '{target_spec.canonical_name}' does not consume compiler plans"
        )
    return dispatch.project_compile_plan(
        compile_plan=compile_plan,
        ext_path=ext_path,
        ontology_metadata=ontology_metadata or {},
    )


_logger = logging.getLogger(__name__)


class ProjectionRunError(RuntimeError):
    """Raised after reporting one or more fatal projection-target failures."""


def _reject_retired_compiler_targets(targets: Iterable[str]) -> None:
    retired = sorted(set(RETIRED_COMPILER_TARGETS).intersection(targets))
    if retired:
        selected = ", ".join(retired)
        raise ProjectionRunError(
            f"project target(s) {selected} are retired; canonical Silver/dbt generation "
            "must use `kairos-ontology compile <domain> --emit`"
        )
    compile_plan_only = sorted(
        {
            target
            for target in targets
            if target in COMPILE_PLAN_ONLY_TARGETS
            or (
                (spec := get_target_spec(target)) is not None
                and spec.canonical_name in {"powerbi", "mdm-profile"}
            )
        }
    )
    if compile_plan_only:
        selected = ", ".join(compile_plan_only)
        raise ProjectionRunError(
            f"project target(s) {selected} are disabled because legacy graph projection "
            "bypasses the immutable CompilePlan; use `kairos-ontology compile <domain> "
            "--check|--explain|--emit`. Gold and MDM consumers must receive "
            "that compiler-produced CompilePlan through the typed downstream registry."
        )


# Thin alias kept for existing call sites below. The actual predicate lives in
# hub_utils.is_domain_ontology_stem — a leaf module shared with core/validator.py,
# core/hub_inspection.py, and core/catalog_test.py — so the four copies cannot drift
# apart again (issue #289).
def _is_domain_ontology(path: Path) -> bool:
    """Return True if *path* looks like a domain ontology file.

    Excludes annotation/configuration files such as ``*-silver-ext.ttl``
    and metadata files whose name starts with ``_`` (e.g. ``_master.ttl``).
    """
    return is_domain_ontology_stem(path.stem)


def project_graph(
    graph: Graph,
    targets: Optional[List[str]] = None,
    namespace: Optional[str] = None,
    ontology_name: str = "ontology",
    shapes_dir: Optional[Path] = None,
) -> Dict[str, Dict[str, str]]:
    """Generate projection artifacts from an in-memory rdflib Graph.

    Args:
        graph: Loaded rdflib Graph.
        targets: List of retained graph projection targets (e.g. ``["neo4j"]``).
                 Defaults to targets included in ``project --target all``.
        namespace: Base namespace to filter classes.  Auto-detected if ``None``.
        ontology_name: Name used in output filenames.
        shapes_dir: Optional path to SHACL shapes directory.

    Returns:
        ``{target: {filename: content}}`` mapping.
    """
    requested_targets = targets or list(projection_targets_for_all())
    _reject_retired_compiler_targets(requested_targets)

    generated_at = resolve_generated_at()
    targets = requested_targets
    template_base = Path(__file__).parent.parent / "templates"
    ns = namespace or _auto_detect_namespace(graph)
    meta = extract_ontology_metadata(graph, ns, generated_at=generated_at)

    results: Dict[str, Dict[str, str]] = {}
    for target_name in targets:
        target_spec = get_target_spec(target_name)
        if target_name not in VALID_TARGETS or target_spec is None:
            continue
        try:
            artifacts = _run_projection(
                target_spec.canonical_name,
                graph,
                Path("."),
                template_base,
                ns,
                shapes_dir,
                ontology_name,
                ontology_metadata=meta,
            )
            if artifacts:
                results[target_name] = artifacts
        except Exception:
            _logger.exception("Projection target %s failed for %s", target_name, ontology_name)
    return results


def _discover_extensions(
    target_name: str,
    onto_name: str,
    onto_info: dict,
    extensions_dir: Optional[Path],
) -> tuple[Optional[Path], Optional[Path]]:
    """Discover extension files for a given target and ontology domain.

    Returns:
        (ext_path, gold_ext_path) tuple. Either may be None.
    """
    ext_path: Optional[Path] = None
    gold_ext_path: Optional[Path] = None
    src_file: Path = onto_info["file"]

    if target_name == "silver":
        # Look in model/extensions/ first (new layout)
        if extensions_dir and extensions_dir.exists():
            candidates = list(extensions_dir.glob(f"{onto_name}-silver-ext.ttl"))
            candidates += list(extensions_dir.glob("*-silver-ext.ttl"))
            ext_path = candidates[0] if candidates else None
        # Fallback: check alongside the ontology file (legacy layout)
        if not ext_path:
            candidates = list(src_file.parent.glob(f"{onto_name}-silver-ext.ttl"))
            candidates += list(src_file.parent.glob("*-silver-ext.ttl"))
            ext_path = candidates[0] if candidates else None

    elif target_name == "powerbi":
        if extensions_dir and extensions_dir.exists():
            candidates = list(extensions_dir.glob(f"{onto_name}-silver-ext.ttl"))
            candidates += list(extensions_dir.glob("*-silver-ext.ttl"))
            ext_path = candidates[0] if candidates else None
        if not ext_path:
            candidates = list(src_file.parent.glob(f"{onto_name}-silver-ext.ttl"))
            candidates += list(src_file.parent.glob("*-silver-ext.ttl"))
            ext_path = candidates[0] if candidates else None
        if extensions_dir and extensions_dir.exists():
            candidates = list(extensions_dir.glob(f"{onto_name}-gold-ext.ttl"))
            candidates += list(extensions_dir.glob("*-gold-ext.ttl"))
            gold_ext_path = candidates[0] if candidates else None
        if not gold_ext_path:
            candidates = list(src_file.parent.glob(f"{onto_name}-gold-ext.ttl"))
            candidates += list(src_file.parent.glob("*-gold-ext.ttl"))
            gold_ext_path = candidates[0] if candidates else None

    elif target_name == "dbt":
        # dbt needs silver-ext.ttl for naturalKey/silver annotations
        if extensions_dir and extensions_dir.exists():
            candidates = list(extensions_dir.glob(f"{onto_name}-silver-ext.ttl"))
            candidates += list(extensions_dir.glob("*-silver-ext.ttl"))
            ext_path = candidates[0] if candidates else None
        if not ext_path:
            candidates = list(src_file.parent.glob(f"{onto_name}-silver-ext.ttl"))
            candidates += list(src_file.parent.glob("*-silver-ext.ttl"))
            ext_path = candidates[0] if candidates else None
        # dbt also needs gold-ext.ttl for gold model generation
        if extensions_dir and extensions_dir.exists():
            candidates = list(extensions_dir.glob(f"{onto_name}-gold-ext.ttl"))
            candidates += list(extensions_dir.glob("*-gold-ext.ttl"))
            gold_ext_path = candidates[0] if candidates else None
        if not gold_ext_path:
            candidates = list(src_file.parent.glob(f"{onto_name}-gold-ext.ttl"))
            candidates += list(src_file.parent.glob("*-gold-ext.ttl"))
            gold_ext_path = candidates[0] if candidates else None

    elif target_name == "ddd":
        # DDD overlay documentation projection (DD-091): {onto}-ddd-ext.ttl
        if extensions_dir and extensions_dir.exists():
            candidates = list(extensions_dir.glob(f"{onto_name}-ddd-ext.ttl"))
            ext_path = candidates[0] if candidates else None
        if not ext_path:
            candidates = list(src_file.parent.glob(f"{onto_name}-ddd-ext.ttl"))
            ext_path = candidates[0] if candidates else None

    else:
        target_spec = get_target_spec(target_name)
        external_dispatch = target_spec.external_dispatch if target_spec else None
        if external_dispatch is None:
            return ext_path, gold_ext_path
        # Externally-registered target (e.g. mdm-profile) supplies its own
        # extension-discovery callable — core stays agnostic of the package.
        ext_path = external_dispatch.discover_ext(onto_name, src_file, extensions_dir)

    return ext_path, gold_ext_path


def _discover_silver_extension_for_sync(
    onto_name: str,
    onto_info: dict,
    extensions_dir: Optional[Path],
) -> Path:
    """Return the exact silver extension path used by the claim sync gate.

    Projection discovery has legacy wildcard fallbacks. The claim-authority gate
    must not borrow another domain's silver extension, because that can mask or
    create drift in multi-domain hubs.
    """
    filename = f"{onto_name}-silver-ext.ttl"
    src_file: Path = onto_info["file"]

    grouped_exact = extensions_dir / filename if extensions_dir is not None else None
    if grouped_exact is not None and grouped_exact.exists():
        return grouped_exact

    legacy_exact = src_file.parent / filename
    if legacy_exact.exists():
        return legacy_exact

    return grouped_exact if grouped_exact is not None else legacy_exact


def _write_artifacts(artifacts: dict[str, str], target_output: Path) -> int:
    """Write projection artifacts to disk.

    Args:
        artifacts: Mapping of relative file path to content.
        target_output: Base output directory.

    Returns:
        Number of files written.
    """
    for file_path, content in artifacts.items():
        output_file = target_output / file_path
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(content, encoding="utf-8")
    return len(artifacts)


#: Manifest of toolkit-generated files, written at a target output root so a later
#: projection can delete artifacts it no longer produces. Deleting only
#: files this manifest recorded guarantees hand-authored files are never touched.
_PROJECTION_MANIFEST_NAME = ".kairos-projection-manifest.json"


def _reconcile_managed_output(target_output: Path, current_paths: Iterable[str]) -> int:
    """Delete previously generated files no longer produced, then record the new set.

    Reads the prior manifest at ``target_output/{_PROJECTION_MANIFEST_NAME}``, removes
    any file it listed that is absent from *current_paths* (pruning newly empty
    directories), and writes the updated manifest. This makes re-projection converge
    on the current output. Only files the toolkit itself recorded are ever deleted;
    user-authored files are never in the manifest.

    Returns the number of stale files removed.
    """
    manifest_path = target_output / _PROJECTION_MANIFEST_NAME
    current = sorted(str(p) for p in current_paths)

    prior: list[str] = []
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                loaded = loaded.get("files", [])
            if isinstance(loaded, list):
                prior = [str(p) for p in loaded]
        except (ValueError, OSError):
            prior = []

    removed = 0
    stale = sorted(set(prior) - set(current))
    for rel in stale:
        stale_file = target_output / rel
        try:
            if stale_file.is_file():
                stale_file.unlink()
                removed += 1
                # Prune now-empty parent directories, but never the output root.
                parent = stale_file.parent
                while parent != target_output and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
        except OSError:
            pass

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"files": current}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return removed


#: Glob-safe shape of the ``YYYY-MM-DD-HHMMSS`` slug that older toolkit versions
#: embedded in report filenames (now replaced by stable names). Used only to prune
#: those legacy files; it matches the exact digit layout so hand-authored files are
#: never touched.


# Issue #220: package-level dbt artifacts are owned by the orchestrator (regenerated once
# after the per-domain loop by ``generate_dbt_project_config``), not by any single domain.
# Each domain's ``generate_dbt_artifacts`` emits its own per-domain "fallback" copy for
# standalone callers, so the merge must not treat differing copies as collisions.
_DBT_PACKAGE_LEVEL_ARTIFACTS = frozenset({"dbt_project.yml", "README.md", "packages.yml"})


def _is_shared_sources_artifact(path: str) -> bool:
    """A per-source-system ``_sources.yml`` shared by every domain using that system."""
    return path.startswith("models/silver/") and path.endswith("__sources.yml")


class SourcesUnionError(ValueError):
    """Two shared ``_sources.yml`` renderings disagree on source or table metadata.

    Issues #584/#586 made the union fail closed: dbt allows exactly one definition per
    source name, so silently keeping the first-seen header (or first-seen table entry)
    would let one domain's stale vocabulary quietly win over another's. The caller
    surfaces this as an artifact collision before any file is written.
    """


def _union_sources_yaml(existing: str, incoming: str) -> str:
    """Deterministically union the ``tables`` of two rendered ``_sources.yml`` docs.

    Two domains that map tables from the same source system each emit a
    ``_{system}__sources.yml`` filtered to *their* mapped tables. The package-level
    file must declare the union of those tables exactly once. The source header
    (name/description/database/schema) must be identical for a given system and any
    same-named table entries must be identical; a mismatch raises
    :class:`SourcesUnionError` (fail closed) rather than silently keeping the
    first-seen variant. Non-conflicting output is byte-identical to the historical
    first-wins union.
    """
    import yaml

    existing_doc = yaml.safe_load(existing) or {}
    incoming_doc = yaml.safe_load(incoming) or {}
    sources_by_name: dict[str, dict] = {}
    order: list[str] = []
    for doc in (existing_doc, incoming_doc):
        for src in doc.get("sources", []) or []:
            name = src.get("name")
            header = {k: v for k, v in src.items() if k != "tables"}
            if name not in sources_by_name:
                header["_tables"] = {}
                sources_by_name[name] = header
                order.append(name)
            else:
                existing_header = {k: v for k, v in sources_by_name[name].items() if k != "_tables"}
                if existing_header != header:
                    raise SourcesUnionError(
                        f"conflicting source metadata for source {name!r}: "
                        f"{existing_header!r} != {header!r}"
                    )
            tables = sources_by_name[name]["_tables"]
            for tbl in src.get("tables", []) or []:
                table_name = tbl.get("name")
                previous = tables.get(table_name)
                if previous is not None and previous != tbl:
                    raise SourcesUnionError(
                        f"conflicting table entry {table_name!r} in source {name!r}: "
                        f"{previous!r} != {tbl!r}"
                    )
                # The fail-closed check above makes first-wins unreachable; assign
                # directly rather than keeping the retired silent-merge setdefault idiom.
                tables[table_name] = tbl
    merged_sources: list[dict] = []
    for name in order:
        entry = sources_by_name[name]
        table_map = entry.pop("_tables")
        entry["tables"] = [table_map[t] for t in sorted(table_map)]
        merged_sources.append(entry)
    return yaml.safe_dump(
        {
            "version": existing_doc.get("version", incoming_doc.get("version", 2)),
            "sources": merged_sources,
        },
        sort_keys=False,
        default_flow_style=False,
    )


def _merge_dbt_artifacts(
    destination: dict[str, str],
    incoming: dict[str, str],
    *,
    context: str,
) -> None:
    """Merge per-domain dbt artifacts, reconciling package-level and shared files.

    Issue #220: the blunt identical-bytes merge rejected legitimate package-level and
    shared artifacts as collisions on a multi-domain hub. This classifier:

    * accepts package-level config (``dbt_project.yml``/``README.md``/``packages.yml``)
      last-wins — the orchestrator regenerates the definitive version after the loop;
    * unions shared per-source ``_sources.yml`` table lists deterministically;
    * still raises on any genuine content collision for domain-owned artifacts.
    """
    collisions: list[str] = []
    for path, content in incoming.items():
        if path in _DBT_PACKAGE_LEVEL_ARTIFACTS:
            destination[path] = content
            continue
        if path in destination and destination[path] != content:
            if _is_shared_sources_artifact(path):
                try:
                    destination[path] = _union_sources_yaml(destination[path], content)
                except SourcesUnionError as exc:
                    # Same fail-closed UX as compile --emit: report the colliding path
                    # in this function's documented collision style instead of letting
                    # a raw ValueError traceback escape the legacy generate path.
                    raise RuntimeError(f"{context}: {path!r}: {exc}") from exc
                continue
            collisions.append(path)
            continue
        destination[path] = content
    if collisions:
        raise RuntimeError(f"{context}: {sorted(collisions)}")


def run_projections(
    ontologies_path: Path,
    catalog_path: Path,
    output_path: Path,
    target: str,
    namespace: str = None,
    platform: str = "fabric",
    degraded: bool = False,
    ref_models_dir: Path | None = None,
    accelerator: str | None = None,
    check_only: bool = False,
    diagnostic_mode: str = "fail_fast",
):
    """Run projection generation.

    Args:
        ontologies_path: Path to ontology files
        catalog_path: Path to XML catalog for imports
        output_path: Where to write generated files
        target: Projection target (dbt, neo4j, etc.) or 'all'
        namespace: Base namespace to project (e.g., 'http://example.org/ont/').
                   If None, auto-detects from ontology.
        platform: dbt SQL adapter platform (``fabric`` or ``databricks``).
    """
    _reject_retired_compiler_targets((target,))

    # Resolve the generation timestamp once for the whole run so generated
    # artifacts from one invocation never mix clocks.
    generated_at = resolve_generated_at()
    fatal_target_errors: list[str] = []

    print("🚀 Kairos Ontology Projections")
    print("=" * 50)

    # Get ontology files. `ontologies_path` may be the model/ontologies directory
    # or one concrete ontology file selected by `kairos-ontology project --ontology`.
    ontology_root = ontologies_path.parent if ontologies_path.is_file() else ontologies_path
    if ontologies_path.is_file():
        ontology_files = [ontologies_path] if ontologies_path.suffix in {".ttl", ".rdf"} else []
    else:
        ontology_files = list(ontologies_path.glob("**/*.ttl")) + list(
            ontologies_path.glob("**/*.rdf")
        )
    # Skip non-domain files: silver-ext annotations, _master imports, etc.
    ontology_files = [f for f in ontology_files if _is_domain_ontology(f)]

    if not ontology_files:
        print(f"  ⚠️  No ontology files found in {ontologies_path}")
        return None

    print(f"\nFound {len(ontology_files)} ontology file(s)")
    print("Each ontology will generate separate output files per domain\n")

    # Process each ontology file separately (each represents a data domain)
    print("Loading ontologies...")
    ontology_graphs = []

    for onto_file in ontology_files:
        try:
            from .ontology_loader import SemanticProfile, load_ontology

            load_result = load_ontology(
                onto_file,
                catalog_path=(catalog_path if catalog_path and catalog_path.exists() else None),
                profile=SemanticProfile.KAIROS_DESIGN,
                degraded=degraded,
            )
            file_graph = load_result.graph

            # Store graph with its source file info
            ontology_graphs.append(
                {
                    "file": onto_file,
                    "graph": file_graph,
                    "name": onto_file.stem,
                    "load_result": load_result,
                }
            )
            print(f"  ✓ Loaded {onto_file.name} ({len(file_graph)} triples)")
        except Exception as e:
            print(f"  ⚠️  Could not parse {onto_file.name}: {e}")
            fatal_target_errors.append(f"{onto_file.stem}: ontology load failed: {e}")

    if not ontology_graphs:
        print("  ⚠️  No ontologies loaded - check ontology files exist")
        if fatal_target_errors:
            raise ProjectionRunError("; ".join(fatal_target_errors))
        return None

    print()

    # DD-021: Collect hub domain namespaces (for import whitelisting).
    # Used to distinguish peer hub imports from external reference models.
    hub_domain_namespaces: set = set()
    for info in ontology_graphs:
        ns = _auto_detect_namespace(info["graph"])
        if ns:
            hub_domain_namespaces.add(ns)
            # Also add without trailing separator for robust matching
            hub_domain_namespaces.add(ns.rstrip("#/"))
    # Issue #220 (Fix B): the loaded graphs are only the *selected* domains — with
    # `project --ontology consignment.ttl` just one domain loads, so peer-domain bases
    # (booking/party/reference-data) would be missing here and their required local
    # `owl:imports` would be mis-flagged as claim/projection drift by the authority gate.
    # Collect every intra-hub `owl:Ontology` base from the full ontologies directory
    # (independent of `--ontology` scoping) so peer imports are recognised as intra-hub.
    from .ontology_scope import collect_hub_domain_bases

    try:
        for base in collect_hub_domain_bases(ontology_root):
            hub_domain_namespaces.add(base)
            hub_domain_namespaces.add(base + "#")
            hub_domain_namespaces.add(base + "/")
    except ValueError as exc:
        # A malformed peer .ttl must not abort projection of the selected domain.
        _logger.warning("Could not collect hub domain bases: %s", exc)
    # Create output directories
    if not check_only:
        output_path.mkdir(parents=True, exist_ok=True)

    # Determine template directory
    template_base = Path(__file__).parent.parent / "templates"

    # Look for SHACL shapes directory — hub layout: model/ontologies/, model/shapes/
    hub_root = ontology_root.parent.parent if ontology_root.parent else None
    shapes_dir = hub_root / "model" / "shapes" if hub_root else None
    if shapes_dir and shapes_dir.exists():
        print(f"  Found SHACL shapes directory: {shapes_dir}\n")

    # Look for source system reference docs (with bronze vocab) and SKOS mappings
    sources_dir = hub_root / "integration" / "sources" if hub_root else None
    mappings_dir = hub_root / "model" / "mappings" if hub_root else None
    extensions_dir = hub_root / "model" / "extensions" if hub_root else None
    if ref_models_dir is None and hub_root:
        ref_models_dir = next(
            (
                candidate
                for candidate in (
                    hub_root / "ontology-reference-models",
                    hub_root.parent / "ontology-reference-models",
                    hub_root / "model" / "reference-models",
                )
                if candidate.is_dir()
            ),
            None,
        )
    from .reference_modules import build_reference_module_context

    scoped_domains = {info["file"].stem for info in ontology_graphs}
    imported_ontology_iris = {
        str(imported)
        for info in ontology_graphs
        for imported in info["graph"].objects(predicate=OWL.imports)
    }

    module_context = build_reference_module_context(
        ref_models_dir,
        catalog_path=catalog_path,
        accelerator=accelerator,
        requested_domains=scoped_domains,
        imported_ontology_iris=imported_ontology_iris,
        include_domain_activation=not imported_ontology_iris,
    )
    if sources_dir and sources_dir.exists():
        print(f"  Found source system references: {sources_dir}")
    if mappings_dir and mappings_dir.exists():
        print(f"  Found SKOS mappings directory: {mappings_dir}\n")

    targets_to_run = (
        list(projection_targets_for_all())
        if target == "all"
        else [
            (
                target_spec.canonical_name
                if (target_spec := get_target_spec(target)) is not None
                else target
            )
        ]
    )

    for target_name in targets_to_run:
        target_spec = get_target_spec(target_name)
        # Report target is handled after the per-domain loop (spans all domains)
        if target_spec is not None and target_spec.execution_phase is ExecutionPhase.POST_DOMAIN:
            continue
        print(f"📦 Generating {target_name} projection...")
        target_output = (
            target_spec.output_path(output_path)
            if target_spec is not None
            else output_path / target_name
        )
        if not check_only:
            target_output.mkdir(parents=True, exist_ok=True)

        total_files = 0
        target_failed = False
        pending_dbt_artifacts: dict[str, str] = {}
        contract_registry: dict = {}
        transforms_dir = hub_root / "integration" / "transforms" / "dbt" if hub_root else None
        if target_name == "dbt" and transforms_dir and transforms_dir.is_dir():
            from .dbt_contracts import discover_dbt_contracts

            try:
                contracts = discover_dbt_contracts(transforms_dir, hub_root)
                contract_registry = {contract.name: contract for contract in contracts}
            except Exception as exc:
                message = f"dbt preflight failed: {exc}"
                fatal_target_errors.append(message)
                print(f"  ✗ {message}\n")
                continue
        # Track which domains produce artifacts for dbt project config
        dbt_domain_names: list[str] = []
        dbt_gold_domains: list[str] = []
        # Collect per-domain coverage data for merged coverage-report.json
        dbt_coverage_data: dict[str, dict] = {}

        # Collect all silver extension file paths for cross-domain NK resolution.
        # Medallion targets use peer Silver policy for cross-domain authority.
        all_silver_ext_paths: list[Path] = []
        if (
            target_name in ("dbt", "silver", "powerbi")
            and extensions_dir
            and extensions_dir.exists()
        ):
            all_silver_ext_paths = sorted(extensions_dir.glob("*-silver-ext.ttl"))

        for onto_info in ontology_graphs:
            onto_graph = onto_info["graph"]
            onto_name = onto_info["name"]
            load_result = onto_info["load_result"]

            # Auto-detect namespace for this ontology if not provided
            onto_namespace = namespace
            if onto_namespace is None:
                onto_namespace = _auto_detect_namespace(onto_graph)
                print(f"  [{onto_name}] Auto-detected namespace: {onto_namespace}")

            # Extract ontology provenance metadata
            onto_meta = extract_ontology_metadata(
                onto_graph, onto_namespace, generated_at=generated_at
            )
            onto_meta.update(
                {
                    "semantic_profile": load_result.profile.value,
                    "closure_hash": load_result.closure_hash,
                    "import_complete": load_result.complete,
                }
            )

            try:
                # Discover extension files for this target/domain
                ext_path, gold_ext_path = _discover_extensions(
                    target_name, onto_name, onto_info, extensions_dir
                )
                if ext_path:
                    label = "silver ext" if target_name == "dbt" else "projection ext"
                    print(f"  [{onto_name}] Using {label}: {ext_path.name}")
                if gold_ext_path:
                    print(f"  [{onto_name}] Using gold ext: {gold_ext_path.name}")

                # DD-023: Discover reference model default extensions
                ref_defaults = _discover_ref_model_defaults(
                    onto_info["file"],
                    catalog_path,
                    target="silver",
                )
                if module_context and target_name in ("silver", "dbt", "powerbi"):
                    from .reference_modules import active_default_annotation_paths

                    ref_defaults = sorted(
                        {
                            *ref_defaults,
                            *active_default_annotation_paths(module_context, onto_name),
                        }
                    )
                if ref_defaults:
                    names = ", ".join(p.name for p in ref_defaults)
                    print(f"  [{onto_name}] Using ref-model defaults: {names}")
                    default_packages: list[str] = []
                    fallback_graph = Graph()
                    for default_path in ref_defaults:
                        default_graph = Graph()
                        default_graph.parse(str(default_path), format="turtle")
                        fallback_graph += default_graph
                        ontology_iri = next(
                            default_graph.subjects(RDF.type, OWL.Ontology),
                            URIRef(default_path.stem),
                        )
                        version = default_graph.value(ontology_iri, OWL.versionInfo)
                        default_packages.append(f"{ontology_iri}@{version or 'unversioned'}")
                    onto_meta["silver_default_packages"] = sorted(default_packages)

                    if ext_path and ext_path.exists():
                        hub_ext_graph = Graph()
                        hub_ext_graph.parse(str(ext_path), format="turtle")
                        fallback_pairs = {(s, p) for s, p, _ in fallback_graph}
                        onto_meta["silver_overrides"] = sorted(
                            f"{s} {p}" for s, p, _ in hub_ext_graph if (s, p) in fallback_pairs
                        )

                peer_exts = (
                    [p for p in all_silver_ext_paths if p != ext_path]
                    if all_silver_ext_paths
                    else None
                )
                artifacts = _run_projection(
                    target_name,
                    onto_graph,
                    target_output,
                    template_base,
                    onto_namespace,
                    shapes_dir,
                    onto_name,
                    projection_ext_path=ext_path,
                    gold_ext_path=gold_ext_path,
                    ontology_metadata=onto_meta,
                    sources_dir=sources_dir,
                    mappings_dir=mappings_dir,
                    hub_domain_namespaces=hub_domain_namespaces,
                    ref_model_defaults=ref_defaults,
                    peer_ext_paths=peer_exts,
                    target_platform=platform,
                    contract_registry=contract_registry,
                    semantic_index=load_result.semantic_index,
                    plan_only=check_only,
                    diagnostic_mode=diagnostic_mode,
                )
                if check_only:
                    continue
                if artifacts:
                    # Extract coverage data before writing (not a real file artifact)
                    if target_name in {"dbt", "silver"} and "__coverage_data__" in artifacts:
                        dbt_coverage_data[onto_name] = artifacts.pop("__coverage_data__")
                    if (
                        target_name in {"dbt", "silver", "powerbi"}
                        and "__release_data__" in artifacts
                    ):
                        artifacts.pop("__release_data__")

                    if target_name in {"dbt", "silver"}:
                        _merge_dbt_artifacts(
                            pending_dbt_artifacts,
                            artifacts,
                            context="Generated dbt artifact collisions",
                        )
                    else:
                        total_files += _write_artifacts(artifacts, target_output)
                    print(f"  [{onto_name}] ✓ Generated {len(artifacts)} file(s)")

                    # Track dbt domains for project config generation
                    if target_name in {"dbt", "silver"}:
                        dbt_domain_names.append(onto_name)
                        # Check if gold models were produced
                        if any(k.startswith("models/gold/") for k in artifacts):
                            dbt_gold_domains.append(onto_name)
            except Exception as e:
                target_failed = True
                print(f"  [{onto_name}] ✗ Failed: {e}")
                _tb.print_exc()

        if check_only:
            continue

        # After all domains: generate dbt project config (once, with all domains)
        if target_name in {"dbt", "silver"} and dbt_domain_names and not target_failed:
            try:
                from .projections.medallion_dbt_projector import generate_dbt_project_config

                dbt_template_dir = Path(__file__).parent.parent / "templates" / "dbt"
                hub_name = ontologies_path.parent.parent.name if ontologies_path.parent else "hub"
                project_config = generate_dbt_project_config(
                    systems=[],
                    ontology_names=dbt_domain_names,
                    template_dir=dbt_template_dir,
                    project_name=f"{hub_name}_project",
                    gold_domain_names=dbt_gold_domains,
                    platform=platform,
                )
                for path in project_config:
                    pending_dbt_artifacts.pop(path, None)
                pending_dbt_artifacts.update(project_config)

                if contract_registry and transforms_dir is not None:
                    from .dbt_bundle import assemble_dbt_bundle

                    bundle = assemble_dbt_bundle(
                        transforms_dir,
                        tuple(contract_registry.values()),
                        generated_artifacts=tuple(pending_dbt_artifacts),
                    )
                    bundle_collisions = sorted(set(pending_dbt_artifacts) & set(bundle.artifacts))
                    if bundle_collisions:
                        raise RuntimeError(
                            f"Custom/generated dbt artifact collisions: {bundle_collisions}"
                        )
                    pending_dbt_artifacts.update(bundle.artifacts)

                total_files += _write_artifacts(pending_dbt_artifacts, target_output)
                # Remove dbt artifacts this run no longer produces so re-projection
                # converges on the current output.
                removed = _reconcile_managed_output(target_output, pending_dbt_artifacts.keys())
                if removed:
                    _logger.info("Removed %d obsolete dbt artifact(s)", removed)
                _logger.info("Generated project config for %d domain(s)", len(dbt_domain_names))
            except Exception as exc:
                target_failed = True
                message = f"dbt assembly failed; no dbt artifacts were written: {exc}"
                fatal_target_errors.append(message)
                print(f"  ✗ {message}\n")
        elif target_name in {"dbt", "silver"} and target_failed:
            message = f"{target_name} projection failed; no dbt artifacts were written"
            fatal_target_errors.append(message)
            print(f"  ✗ {message}\n")

        # After all domains: merge per-domain coverage data into a single report
        if target_name in {"dbt", "silver"} and dbt_coverage_data and not target_failed:
            import json as _json

            merged_coverage = {
                "domains": dbt_coverage_data,
                "summary": _build_coverage_summary(dbt_coverage_data),
            }
            coverage_content = _json.dumps(merged_coverage, indent=2, ensure_ascii=False)
            reports_dir = output_path / "reports"
            reports_dir.mkdir(parents=True, exist_ok=True)
            coverage_artifacts = {"coverage-silver.json": coverage_content}
            # Generate human-readable Markdown rendering
            md_content = _render_silver_coverage_md(merged_coverage, generated_at=generated_at)
            coverage_artifacts["coverage-silver.md"] = md_content
            total_files += _write_artifacts(coverage_artifacts, reports_dir)
            _reconcile_managed_output(reports_dir, coverage_artifacts.keys())
            print(f"  ✓ Merged coverage report for {len(dbt_coverage_data)} domain(s)")

        # DD-110: dbt and the explicit Silver facade emit the same physical ERDs.
        if target_name in {"dbt", "silver"} and total_files > 0:
            from .projections.medallion_silver_projector import (
                generate_master_erd,
                render_mermaid_svg,
            )

            dbt_output = output_path / "medallion" / "dbt"
            hub_name = (
                ontologies_path.parent.parent.name if ontologies_path.parent else "ontology-hub"
            )
            master_mmd = generate_master_erd(dbt_output, hub_name=hub_name)
            if master_mmd:
                diagrams_dir = dbt_output / "docs" / "diagrams"
                diagrams_dir.mkdir(parents=True, exist_ok=True)
                master_path = diagrams_dir / "master-erd.mmd"
                master_path.write_text(master_mmd, encoding="utf-8")
                total_files += 1
                print("  ✓ Master ERD written: dbt/docs/diagrams/master-erd.mmd")
            # Render all .mmd files to SVG via Mermaid CLI (if available)
            svg_count = 0
            diagrams_root = dbt_output / "docs" / "diagrams"
            if diagrams_root.exists():
                for mmd_file in sorted(diagrams_root.rglob("*.mmd")):
                    svg = render_mermaid_svg(mmd_file)
                    if svg:
                        svg_count += 1
            if svg_count:
                total_files += svg_count
                print(f"  ✓ Rendered {svg_count} SVG file(s) via Mermaid CLI")
            else:
                print(
                    "  [info] Mermaid CLI (mmdc) not found -- SVG export skipped."
                    " Install: npm install -D @mermaid-js/mermaid-cli"
                )

        # After all domains: generate master gold ERD
        if target_name == "powerbi" and total_files > 0:
            from .projections.medallion_gold_projector import generate_master_gold_erd
            from .projections.medallion_silver_projector import render_mermaid_svg

            gold_output = output_path / "powerbi"
            hub_name = (
                ontologies_path.parent.parent.name if ontologies_path.parent else "ontology-hub"
            )
            master_mmd = generate_master_gold_erd(gold_output, hub_name=hub_name)
            if master_mmd:
                master_path = gold_output / "master-gold-erd.mmd"
                master_path.write_text(master_mmd, encoding="utf-8")
                total_files += 1
                print("  ✓ Master Gold ERD written: powerbi/master-gold-erd.mmd")
            svg_count = 0
            if gold_output.exists():
                for mmd_file in sorted(gold_output.rglob("*.mmd")):
                    svg = render_mermaid_svg(mmd_file)
                    if svg:
                        svg_count += 1
            if svg_count:
                total_files += svg_count
                print(f"  ✓ Rendered {svg_count} SVG file(s) via Mermaid CLI")
            else:
                print(
                    "  [info] Mermaid CLI (mmdc) not found -- SVG export skipped."
                    " Install: npm install -D @mermaid-js/mermaid-cli"
                )

        print(f"  ✓ {target_name} projection completed: {total_files} total files\n")

    if check_only:
        return None

    # ── Post-domain targets (span all ontology domains) ──────────────────
    if "report" in targets_to_run:
        print("📦 Generating report projection...")
        report_output = TARGET_REGISTRY["report"].output_path(output_path)
        report_output.mkdir(parents=True, exist_ok=True)
        managed_detail_files: list[str] = []

        # Merge all domain ontology graphs for cross-domain property lookup
        merged_classes: dict = {}
        for onto_info in ontology_graphs:
            onto_ns = namespace or _auto_detect_namespace(onto_info["graph"])
            if onto_ns:
                from .projections.report_projector import (
                    _extract_ontology_properties,
                )

                domain_classes = _extract_ontology_properties(onto_info["graph"], onto_ns)
                merged_classes.update(domain_classes)

        from .projections.report_projector import generate_mapping_report

        report_artifacts = generate_mapping_report(
            ontology_classes=merged_classes,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            template_dir=template_base,
        )
        report_count = 0
        for fname, html in report_artifacts.items():
            out_file = report_output / fname
            out_file.write_text(html, encoding="utf-8")
            managed_detail_files.append(fname)
            report_count += 1
            print(f"  ✓ {fname}")
        print(f"  ✓ report projection completed: {report_count} total files\n")

        # Generate domain overview report
        from .projections.report_projector import generate_domain_overview_report

        ontology_dir = hub_root / "model" / "ontologies" if hub_root else None
        if ontology_dir and ontology_dir.is_dir():
            overview_artifacts = generate_domain_overview_report(
                ontology_dir=ontology_dir,
                template_dir=template_base,
            )
            for fname, content in overview_artifacts.items():
                out_file = report_output / fname
                out_file.write_text(content, encoding="utf-8")
                managed_detail_files.append(fname)
                report_count += 1
                print(f"  ✓ {fname}")

        # Generate source landscape report
        from .projections.report_projector import generate_source_landscape_report

        if sources_dir and sources_dir.is_dir():
            landscape_artifacts = generate_source_landscape_report(
                sources_dir=sources_dir,
                mappings_dir=mappings_dir,
                ontology_dir=ontology_dir,
                template_dir=template_base,
            )
            for fname, content in landscape_artifacts.items():
                out_file = report_output / fname
                out_file.write_text(content, encoding="utf-8")
                managed_detail_files.append(fname)
                report_count += 1
                print(f"  ✓ {fname}")

        # Generate mapping progress dashboard
        from .projections.report_projector import generate_mapping_progress_report

        if sources_dir and sources_dir.is_dir():
            progress_artifacts = generate_mapping_progress_report(
                sources_dir=sources_dir,
                mappings_dir=mappings_dir,
                ontology_dir=ontology_dir,
                template_dir=template_base,
            )
            for fname, content in progress_artifacts.items():
                out_file = report_output / fname
                out_file.write_text(content, encoding="utf-8")
                managed_detail_files.append(fname)
                report_count += 1
                print(f"  ✓ {fname}")

        # Record the managed detail-report set so a later run prunes report files
        # it no longer produces (convergent output, DD-096 C3 style).
        _reconcile_managed_output(report_output, managed_detail_files)

    print("✅ Projection generation completed!")
    print(f"   Generated artifacts for {len(ontology_graphs)} data domain(s)")

    if fatal_target_errors:
        raise ProjectionRunError("; ".join(fatal_target_errors))


def _build_coverage_summary(domain_data: dict[str, dict]) -> dict:
    """Aggregate per-domain coverage stats into an overall summary."""
    total_properties = 0
    total_populated = 0
    total_always_null = 0
    total_missing_required = 0
    for entities in domain_data.values():
        for entity in entities.values():
            total_properties += entity.get("ontology_properties_total", 0)
            total_populated += entity.get("populated_from_source", 0)
            total_always_null += entity.get("always_null", 0)
            total_missing_required += len(entity.get("missing_required_mappings", []))
    return {
        "domains_count": len(domain_data),
        "total_properties": total_properties,
        "populated_from_source": total_populated,
        "always_null": total_always_null,
        "missing_required_mappings": total_missing_required,
        "populated_pct": round(total_populated / total_properties * 100) if total_properties else 0,
    }


def _render_silver_coverage_md(merged: dict, *, generated_at: datetime | None = None) -> str:
    """Render merged silver coverage data as human-readable Markdown."""
    summary = merged.get("summary", {})
    domains = merged.get("domains", {})
    stamp = resolve_generated_at() if generated_at is None else generated_at
    lines = [
        "# Silver Layer Coverage Report",
        "",
        f"**Generated:** {stamp.strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
        f"**Domains:** {summary.get('domains_count', 0)}  ",
        f"**Overall populated:** {summary.get('populated_pct', 0)}%"
        f" ({summary.get('populated_from_source', 0)}"
        f"/{summary.get('total_properties', 0)} properties)  ",
        f"**Always NULL:** {summary.get('always_null', 0)}  ",
        f"**Missing required:** {summary.get('missing_required_mappings', 0)}",
        "",
    ]
    for domain_name, entities in domains.items():
        lines.append(f"## {domain_name}")
        lines.append("")
        lines.append("| Entity | Properties | Populated | NULL | Missing Required |")
        lines.append("|--------|-----------|-----------|------|-----------------|")
        for entity_name, stats in entities.items():
            total = stats.get("ontology_properties_total", 0)
            pop = stats.get("populated_from_source", 0)
            null = stats.get("always_null", 0)
            missing = stats.get("missing_required_mappings", [])
            pct = round(pop / total * 100) if total else 0
            missing_str = ", ".join(missing) if missing else "—"
            lines.append(f"| {entity_name} | {total} | {pop} ({pct}%) | {null} | {missing_str} |")
        lines.append("")

        # Show NULL columns detail
        has_nulls = any(stats.get("null_columns") for stats in entities.values())
        if has_nulls:
            lines.append("### Columns that will be NULL")
            lines.append("")
            for entity_name, stats in entities.items():
                null_cols = stats.get("null_columns", [])
                if null_cols:
                    lines.append(f"**{entity_name}:** {', '.join(null_cols)}")
            lines.append("")

    return "\n".join(lines)


def extract_ontology_metadata(
    graph: Graph, namespace: str, *, generated_at: datetime | None = None
) -> dict:
    """Extract provenance metadata from the owl:Ontology declaration.

    Returns a dict with keys: ``iri``, ``version``, ``label``, ``namespace``,
    ``toolkit_version``, and ``generated_at``.  Missing values default to
    sensible placeholders so callers can always rely on the keys being present.

    Args:
        generated_at: The run's pinned generation time.  When ``None`` (a direct
            caller outside a projection run) it is resolved from the environment;
            a projection run resolves it once and threads the same value here so
            every target's ``-- Generated at:`` stamp matches the report.
    """
    from kairos_ontology import __version__ as toolkit_version

    iri: str = namespace.rstrip("#/")
    version: str = ""
    label: str = ""

    # Find the owl:Ontology that lives in the given namespace
    for subj in graph.subjects(predicate=None, object=OWL.Ontology):
        subj_str = str(subj)
        if subj_str.startswith(namespace.rstrip("#/")):
            iri = subj_str
            ver = graph.value(subj, OWL.versionInfo)
            if ver:
                version = str(ver)
            lbl = graph.value(subj, RDFS.label)
            if lbl:
                label = str(lbl)
            break

    return {
        "iri": iri,
        "version": version,
        "label": label,
        "namespace": namespace,
        "toolkit_version": toolkit_version,
        "generated_at": generated_at_iso(generated_at),
    }


def _auto_detect_namespace(graph: Graph) -> str:
    """Auto-detect the ontology's base namespace using semantic web best practices.

    Method 1: Check owl:Ontology declaration (preferred - semantic web standard)
    Method 2: Exclude owl:imports and count classes in remaining namespaces
    Method 3: Fallback to URN format

    This approach scales to any external ontology without hardcoded exclusion lists.
    """

    # Method 1: Look for owl:Ontology declaration (BEST PRACTICE)
    # The namespace containing the owl:Ontology instance is the main ontology namespace
    ontology_query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>

    SELECT ?ontology
    WHERE {
        ?ontology a owl:Ontology .
    }
    """

    # Standard W3C namespaces to always exclude
    standard_namespaces = {
        "http://www.w3.org/2002/07/owl#",
        "http://www.w3.org/2000/01/rdf-schema#",
        "http://www.w3.org/2004/02/skos/core#",
        "http://www.w3.org/2001/XMLSchema#",
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    }

    ontology_namespaces = []
    for row in graph.query(ontology_query):
        onto_uri = str(row["ontology"])

        # Extract namespace from ontology URI.
        # Key insight: many ontologies declare URI without '#' (e.g.
        # https://example.com/ont/client) but their classes use '#' fragments
        # (e.g. https://example.com/ont/client#Client).  In that case the
        # namespace is '{onto_uri}#', NOT the parent path.
        if "#" in onto_uri:
            namespace = onto_uri.rsplit("#", 1)[0] + "#"
        else:
            # Probe: do any owl:Class URIs start with '{onto_uri}#'?
            hash_ns = onto_uri + "#"
            has_hash_classes = any(
                str(cls).startswith(hash_ns)
                for cls in graph.subjects(RDF.type, OWL.Class)
                if isinstance(cls, URIRef)
            )
            if has_hash_classes:
                namespace = hash_ns
            elif "/" in onto_uri:
                namespace = onto_uri.rsplit("/", 1)[0] + "/"
            else:
                namespace = onto_uri + ":"  # URN format

        # Skip standard W3C ontologies
        if namespace not in standard_namespaces:
            ontology_namespaces.append(namespace)

    # Method 2: Get imported ontology namespaces to exclude
    imports_query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>

    SELECT ?imported
    WHERE {
        ?ontology owl:imports ?imported .
    }
    """

    imported_namespaces = set()
    for row in graph.query(imports_query):
        import_uri = str(row["imported"])

        # Extract namespace from import URI
        if "#" in import_uri:
            namespace = import_uri.rsplit("#", 1)[0] + "#"
        elif "/" in import_uri:
            namespace = import_uri.rsplit("/", 1)[0] + "/"
        else:
            namespace = import_uri + ":"

        imported_namespaces.add(namespace)

    # If we found owl:Ontology declarations, prefer the one that's NOT imported
    if ontology_namespaces:
        for onto_ns in ontology_namespaces:
            # Check if this ontology namespace is NOT in the imports
            if onto_ns not in imported_namespaces:
                return onto_ns

        # If all ontology namespaces are imported (rare), return the first one
        return ontology_namespaces[0]

    # Method 3: Fallback - count classes per namespace, excluding imports and standards
    class_query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>

    SELECT ?class
    WHERE {
        ?class a owl:Class .
        FILTER(isIRI(?class))
    }
    """

    namespace_counts = {}
    for row in graph.query(class_query):
        class_uri = str(row["class"])

        # Extract namespace
        if "#" in class_uri:
            namespace = class_uri.rsplit("#", 1)[0] + "#"
        elif "/" in class_uri:
            namespace = class_uri.rsplit("/", 1)[0] + "/"
        else:
            namespace = class_uri.rsplit(":", 1)[0] + ":"

        # Skip standard W3C namespaces
        if namespace in standard_namespaces:
            continue

        # Skip imported namespaces
        if namespace in imported_namespaces:
            continue

        namespace_counts[namespace] = namespace_counts.get(namespace, 0) + 1

    if namespace_counts:
        # Return namespace with most classes
        return max(namespace_counts, key=namespace_counts.get)

    # Ultimate fallback
    return "urn:kairos:ont:core:"


# ---------------------------------------------------------------------------
# DD-023: Reference model extension defaults discovery
# ---------------------------------------------------------------------------

_DEFAULTS_SUFFIXES = {
    "silver": "-silver-defaults.ttl",
    "gold": "-gold-defaults.ttl",
}


def _discover_ref_model_defaults(
    ontology_file: Path,
    catalog_path: Optional[Path],
    target: str,
) -> list[Path]:
    """Discover extension default files shipped alongside imported reference models.

    For each ``owl:imports`` resolved via the catalog, looks for a sibling file
    matching ``{stem}-{target}-defaults.ttl`` (e.g., ``bsp-party-silver-defaults.ttl``).
    Also checks a sibling ``extensions/`` directory.

    Args:
        ontology_file: Path to the domain ontology file being projected.
        catalog_path: Path to catalog-v001.xml (may be None).
        target: Projection target — ``"silver"`` or ``"gold"``.

    Returns:
        List of Paths to discovered defaults files (may be empty).
    """
    if not catalog_path or not catalog_path.exists():
        return []

    suffix = _DEFAULTS_SUFFIXES.get(target)
    if not suffix:
        return []

    from .catalog_utils import resolve_import_paths

    resolved = resolve_import_paths(ontology_file, catalog_path)
    defaults: list[Path] = []

    for _uri, local_path in resolved.items():
        stem = local_path.stem
        # Check alongside the resolved ontology file
        candidate = local_path.parent / f"{stem}{suffix}"
        if candidate.exists():
            defaults.append(candidate)
            continue
        # Check in a sibling extensions/ directory
        ext_dir = local_path.parent / "extensions"
        if ext_dir.is_dir():
            candidate = ext_dir / f"{stem}{suffix}"
            if candidate.exists():
                defaults.append(candidate)

    return defaults


# ---------------------------------------------------------------------------
# DD-021: Import whitelisting helpers
# ---------------------------------------------------------------------------


def _get_reference_model_namespaces(
    graph: Graph,
    domain_namespace: str,
    hub_domain_namespaces: set,
) -> list:
    """Return namespace bases of reference model imports (excluding peer hub domains).

    Only first-level ``owl:imports`` are considered — transitive imports are not
    included to avoid pulling in large upstream dependency trees.

    For each import, both ``#`` and ``/`` namespace variants are returned so
    that class URI matching works regardless of separator convention.
    """
    # Find the actual owl:Ontology subject in the graph
    onto_iri = _find_ontology_subject(graph, domain_namespace)
    imported = []
    for obj in graph.objects(onto_iri, OWL.imports):
        ns = str(obj)
        bare = ns.rstrip("#/")
        # Skip peer domain imports (other hub .ttl files)
        if bare in hub_domain_namespaces:
            continue
        if (bare + "#") in hub_domain_namespaces or (bare + "/") in hub_domain_namespaces:
            continue
        if ns in hub_domain_namespaces:
            continue
        # Add both separator variants for robust class URI matching
        imported.append(bare + "#")
        imported.append(bare + "/")
    return imported


def _find_ontology_subject(graph: Graph, namespace: str) -> URIRef:
    """Find the owl:Ontology subject in *graph* that matches *namespace*.

    Handles both ``#`` and ``/`` namespace conventions. Falls back to
    stripping the separator from the provided namespace.
    """
    bare = namespace.rstrip("#/")
    for s in graph.subjects(RDF.type, OWL.Ontology):
        if str(s).startswith(bare):
            return s
    return URIRef(bare)


def _discover_whitelisted_imports(
    graph: Graph,
    namespace: str,
    all_class_rows: list,
    *,
    projection_ext_path: Optional[Path],
    gold_ext_path: Optional[Path],
    target: str,
    hub_domain_namespaces: set,
    ref_model_defaults: Optional[list] = None,
) -> list:
    """Return imported classes that are whitelisted for projection (DD-021).

    Two mechanisms:
    1. Per-class: ``kairos-ext:silverInclude true`` (or ``goldInclude``)
    2. Bulk:      ``kairos-ext:silverIncludeImports true`` (or ``goldIncludeImports``)
       on the ``owl:Ontology`` resource — includes all first-level reference model
       imports (peer hub domains are excluded).

    DD-023: ``silverInclude`` may also be declared in reference model default
    extension files, which are passed as *ref_model_defaults* fallback paths.
    """
    from .projections.shared import KAIROS_EXT, merge_ext_graph

    # Determine which annotations to check based on target
    if target in ("silver", "dbt"):
        include_prop = KAIROS_EXT.silverInclude
        bulk_prop = KAIROS_EXT.silverIncludeImports
        ext_path = projection_ext_path
    else:  # powerbi / gold
        include_prop = KAIROS_EXT.goldInclude
        bulk_prop = KAIROS_EXT.goldIncludeImports
        ext_path = gold_ext_path or projection_ext_path

    # Build merged graph with extension + fallback defaults (DD-023)
    merged = merge_ext_graph(graph, ext_path, fallback_paths=ref_model_defaults)

    # Detect ontology URI for bulk flag check (handles both # and / conventions)
    onto_iri = _find_ontology_subject(merged, namespace)

    # Check bulk flag
    bulk_val = merged.value(onto_iri, bulk_prop)
    bulk_include = bulk_val is not None and str(bulk_val).lower() in ("true", "1")

    # Collect whitelisted imported class URIs
    whitelisted_uris: set = set()

    if bulk_include:
        # Include all classes from first-level reference model imports
        ref_namespaces = _get_reference_model_namespaces(graph, namespace, hub_domain_namespaces)
        for class_uri, _row in all_class_rows:
            if class_uri.startswith(namespace):
                continue  # skip local classes (already collected)
            if any(class_uri.startswith(ns) for ns in ref_namespaces):
                whitelisted_uris.add(class_uri)

    # Per-class silverInclude / goldInclude (additive to bulk)
    for class_uri, _row in all_class_rows:
        if class_uri.startswith(namespace):
            continue
        cls_ref = URIRef(class_uri)
        val = merged.value(cls_ref, include_prop)
        if val is not None and str(val).lower() in ("true", "1"):
            whitelisted_uris.add(class_uri)

    # Build class info dicts for whitelisted imports
    imported_classes = []
    for class_uri, row in all_class_rows:
        if class_uri not in whitelisted_uris:
            continue
        class_name = extract_local_name(class_uri)
        imported_classes.append(
            OntologyClassInfo(
                uri=class_uri,
                name=class_name,
                label=str(row.label) if row.label else class_name,
                comment=str(row.comment) if row.comment else f"{class_name} entity",
            ).to_dict()
        )

    return imported_classes


def _run_projection(
    target: str,
    graph: Graph,
    output_path: Path,
    template_base: Path,
    namespace: str,
    shapes_dir: Path = None,
    ontology_name: str = None,
    projection_ext_path: Optional[Path] = None,
    gold_ext_path: Optional[Path] = None,
    ontology_metadata: Optional[dict] = None,
    sources_dir: Optional[Path] = None,
    mappings_dir: Optional[Path] = None,
    hub_domain_namespaces: Optional[set] = None,
    ref_model_defaults: Optional[list] = None,
    peer_ext_paths: Optional[list] = None,
    target_platform: str = "fabric",
    contract_registry: Optional[dict] = None,
    semantic_index=None,
    plan_only: bool = False,
    diagnostic_mode: str = "fail_fast",
) -> dict:
    """Run a specific projection type using simplified logic.

    Args:
        target: Projection type (dbt, neo4j, azure-search, a2ui, prompt, silver)
        graph: RDFLib graph for this specific ontology
        output_path: Base output path for this target
        template_base: Path to templates
        namespace: Namespace to filter classes
        shapes_dir: Optional SHACL shapes directory
        ontology_name: Name of the ontology file (without extension)
        projection_ext_path: Optional path to *-silver-ext.ttl (silver target only)
        gold_ext_path: Optional path to *-gold-ext.ttl (dbt target — for gold models)
        ontology_metadata: Provenance metadata from extract_ontology_metadata()
        sources_dir: Optional path to integration/sources/ directory (dbt target)
        mappings_dir: Optional path to mappings/ SKOS directory (dbt target)
        hub_domain_namespaces: Set of namespaces for all hub domains (for import
            whitelisting — distinguishes peer hub imports from reference model imports)
        ref_model_defaults: Optional list of Paths to reference model default
            extension files (DD-023). Loaded as fallback beneath domain extension.
        target_platform: dbt SQL adapter platform.
        contract_registry: Validated custom dbt contracts keyed by model name.
    """
    _reject_retired_compiler_targets((target,))

    if plan_only and target not in {"dbt", "silver", "powerbi"}:
        return {"__plan__": target}

    # DDD documentation overlay (DD-091) — handled before class collection so
    # that import-only domains with DDD overlays still produce documentation.
    if target == "ddd":
        from .projections.ddd_projector import generate_ddd_artifacts

        return generate_ddd_artifacts(
            graph=graph,
            namespace=namespace,
            ontology_name=ontology_name or "domain",
            overlay_path=projection_ext_path,
            ontology_metadata=ontology_metadata or {},
        )

    # Externally-registered targets (e.g. mdm-profile) — dispatched via the
    # registry so core never imports the contributing package (MDM-DD-002).
    target_spec = get_target_spec(target)
    external_dispatch = target_spec.external_dispatch if target_spec else None
    if external_dispatch is not None:
        return external_dispatch.project(
            graph=graph,
            namespace=namespace,
            ontology_name=ontology_name or "domain",
            ext_path=projection_ext_path,
            ontology_metadata=ontology_metadata or {},
        )

    query = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT ?class ?label ?comment
    WHERE {
        ?class a owl:Class .
        OPTIONAL { ?class rdfs:label ?label }
        OPTIONAL { ?class rdfs:comment ?comment }
        FILTER(isIRI(?class))
    }
    """

    # Collect ALL classes from the graph (local + imported)
    all_class_rows = []
    for row in graph.query(query):
        class_uri = str(row["class"])
        all_class_rows.append((class_uri, row))

    # Local classes: those in the domain namespace
    classes = []
    for class_uri, row in all_class_rows:
        if not class_uri.startswith(namespace):
            continue
        class_name = extract_local_name(class_uri)
        classes.append(
            OntologyClassInfo(
                uri=class_uri,
                name=class_name,
                label=str(row.label) if row.label else class_name,
                comment=str(row.comment) if row.comment else f"{class_name} entity",
            ).to_dict()
        )

    # DD-021: Import whitelisting — include claimed imported classes
    # For silver/gold/dbt targets, check extension files for silverInclude/goldInclude
    # and the bulk silverIncludeImports/goldIncludeImports flags
    if target in ("silver", "powerbi", "dbt"):
        imported_classes = _discover_whitelisted_imports(
            graph,
            namespace,
            all_class_rows,
            projection_ext_path=projection_ext_path,
            gold_ext_path=gold_ext_path,
            target=target,
            hub_domain_namespaces=hub_domain_namespaces or set(),
            ref_model_defaults=ref_model_defaults,
        )
        classes.extend(imported_classes)
        if target == "powerbi" and projection_ext_path:
            silver_imported = _discover_whitelisted_imports(
                graph,
                namespace,
                all_class_rows,
                projection_ext_path=projection_ext_path,
                gold_ext_path=gold_ext_path,
                target="silver",
                hub_domain_namespaces=hub_domain_namespaces or set(),
                ref_model_defaults=ref_model_defaults,
            )
            existing_uris = {item["uri"] for item in classes}
            for imported in silver_imported:
                if imported["uri"] not in existing_uris:
                    classes.append(imported)
                    existing_uris.add(imported["uri"])
        # dbt generates both silver AND gold models — also discover gold claims
        # so that goldInclude-only imports are available for gold model generation.
        if target == "dbt" and gold_ext_path:
            gold_imported = _discover_whitelisted_imports(
                graph,
                namespace,
                all_class_rows,
                projection_ext_path=projection_ext_path,
                gold_ext_path=gold_ext_path,
                target="powerbi",
                hub_domain_namespaces=hub_domain_namespaces or set(),
                ref_model_defaults=ref_model_defaults,
            )
            # Add gold-only claims (avoid duplicates)
            existing_uris = {c["uri"] for c in classes}
            for cls in gold_imported:
                if cls["uri"] not in existing_uris:
                    classes.append(cls)
    if target == "powerbi" and peer_ext_paths:
        from .projections.shared import KAIROS_EXT

        peer_graph = Graph()
        for peer_path in peer_ext_paths:
            if peer_path and Path(peer_path).is_file():
                peer_graph.parse(peer_path, format="turtle")
        peer_silver_classes = {
            str(subject)
            for predicate in (
                KAIROS_EXT.silverTableName,
                KAIROS_EXT.identityStrategy,
            )
            for subject in peer_graph.subjects(predicate, None)
            if isinstance(subject, URIRef)
        }
        existing_uris = {item["uri"] for item in classes}
        for class_uri, row in all_class_rows:
            if class_uri not in peer_silver_classes or class_uri in existing_uris:
                continue
            class_name = extract_local_name(class_uri)
            classes.append(
                OntologyClassInfo(
                    uri=class_uri,
                    name=class_name,
                    label=str(row.label) if row.label else class_name,
                    comment=(str(row.comment) if row.comment else f"{class_name} entity"),
                ).to_dict()
            )
            existing_uris.add(class_uri)

    if not classes:
        return {}

    meta = ontology_metadata or {}

    # Generate based on target using full-featured projector classes
    # Pass ontology_name so each projector can create domain-specific filenames
    if target == "neo4j":
        from .projections.neo4j_projector import generate_neo4j_artifacts

        return generate_neo4j_artifacts(
            classes,
            graph,
            template_base / "neo4j",
            namespace,
            ontology_name,
            ontology_metadata=meta,
        )
    elif target == "azure-search":
        from .projections.azure_search_projector import generate_azure_search_artifacts

        return generate_azure_search_artifacts(
            classes,
            graph,
            template_base / "azure-search",
            namespace,
            ontology_name,
            ontology_metadata=meta,
        )
    elif target == "a2ui":
        from .projections.a2ui_projector import generate_a2ui_artifacts

        return generate_a2ui_artifacts(
            classes,
            graph,
            template_base / "a2ui",
            namespace,
            ontology_name,
            ontology_metadata=meta,
        )
    elif target == "prompt":
        from .projections.prompt_projector import generate_prompt_artifacts

        return generate_prompt_artifacts(
            classes,
            graph,
            template_base / "prompt",
            namespace,
            ontology_name,
            ontology_metadata=meta,
            semantic_index=semantic_index,
        )
    elif target == "powerbi":
        from .projections.medallion_gold_projector import (
            generate_gold_artifacts,
            plan_gold_projection,
        )

        peer_ontology_paths: list[Path] = []
        for peer_extension in peer_ext_paths or ():
            peer_name = Path(peer_extension).stem.removesuffix("-silver-ext")
            candidates = (
                Path(peer_extension).parent.parent / "ontologies" / f"{peer_name}.ttl",
                Path(peer_extension).parent / f"{peer_name}.ttl",
            )
            peer_ontology = next(
                (candidate for candidate in candidates if candidate.is_file()),
                None,
            )
            if peer_ontology is not None:
                peer_ontology_paths.append(peer_ontology)
        runner = plan_gold_projection if plan_only else generate_gold_artifacts
        from .projections.dbt import ExecutionMode

        result = runner(
            classes=classes,
            graph=graph,
            template_dir=template_base / "dbt",
            namespace=namespace,
            shapes_dir=shapes_dir,
            ontology_name=ontology_name or "domain",
            ontology_metadata=meta,
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
            gold_ext_path=gold_ext_path,
            silver_ext_path=projection_ext_path,
            ref_model_defaults=ref_model_defaults,
            peer_ext_paths=peer_ext_paths,
            peer_ontology_paths=peer_ontology_paths,
            target_platform=target_platform,
            contract_registry=contract_registry,
            **({"diagnostic_mode": ExecutionMode(diagnostic_mode)} if plan_only else {}),
        )
        return {"__plan__": result[1]} if plan_only else result

    return {}
