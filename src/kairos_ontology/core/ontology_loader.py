# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Canonical catalog-aware ontology closure loading (DD-103)."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from rdflib import Graph, OWL, RDF, URIRef

from .catalog_utils import CatalogResolver, _get_rdf_format


class SemanticProfile(str, Enum):
    """Supported ontology interpretation profiles."""

    ASSERTED = "asserted"
    RDFS = "rdfs"
    KAIROS_DESIGN = "kairos-design"
    OWL_RL = "owl-rl"


class ImportRequirement(str, Enum):
    """Whether an import must resolve for a complete closure."""

    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class OntologyDiagnostic:
    """Structured ontology loading diagnostic."""

    level: str
    code: str
    message: str
    import_uri: str | None = None
    source_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-compatible representation."""
        return asdict(self)


@dataclass(frozen=True)
class ImportManifestEntry:
    """One parsed source in an ontology import closure."""

    ontology_iri: str | None
    source_path: str
    source_identity: str
    parent_import: str | None
    import_uri: str | None
    import_depth: int
    ontology_version: str | None
    source_sha256: str
    rdf_format: str
    requirement: ImportRequirement

    def to_dict(self) -> dict[str, Any]:
        """Return a deterministic JSON-compatible representation."""
        data = asdict(self)
        data["requirement"] = self.requirement.value
        return data


@dataclass(frozen=True)
class OntologyLoadResult:
    """Complete result of canonical ontology loading."""

    graph: Graph
    manifest: tuple[ImportManifestEntry, ...]
    diagnostics: tuple[OntologyDiagnostic, ...]
    complete: bool
    closure_hash: str
    profile: SemanticProfile
    semantic_index: Any | None = None
    sources: tuple["LoadedOntologySource", ...] = ()

    def warnings(self) -> list[str]:
        """Return warning-level diagnostic messages."""
        return [item.message for item in self.diagnostics if item.level == "warning"]

    def manifest_dicts(self) -> list[dict[str, Any]]:
        """Return manifest records in deterministic order."""
        return [entry.to_dict() for entry in self.manifest]


class OntologyLoadError(RuntimeError):
    """Raised when a required ontology closure cannot be loaded completely."""

    def __init__(self, message: str, result: OntologyLoadResult):
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class LoadedOntologySource:
    """A parsed closure source retained for provenance without reparsing."""

    manifest: ImportManifestEntry
    graph: Graph


@dataclass(frozen=True)
class _PendingSource:
    path: Path
    import_uri: str | None
    parent_import: str | None
    depth: int
    requirement: ImportRequirement
    ancestors: tuple[Path, ...]


def _source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ontology_metadata(graph: Graph) -> tuple[str | None, str | None]:
    ontologies = sorted(
        (subject for subject in graph.subjects(RDF.type, OWL.Ontology) if isinstance(subject, URIRef)),
        key=str,
    )
    if not ontologies:
        return None, None
    ontology = ontologies[0]
    version = graph.value(ontology, OWL.versionInfo)
    if version is None:
        version = graph.value(ontology, OWL.versionIRI)
    return str(ontology), str(version) if version is not None else None


def _relative_identity(path: Path, identity_root: Path) -> str:
    try:
        return path.resolve().relative_to(identity_root.resolve()).as_posix()
    except ValueError:
        return path.name


def _closure_hash(manifest: Iterable[ImportManifestEntry]) -> str:
    records = [
        {
            "identity": entry.source_identity,
            "ontology_iri": entry.ontology_iri,
            "version": entry.ontology_version,
            "sha256": entry.source_sha256,
        }
        for entry in manifest
    ]
    payload = json.dumps(
        sorted(records, key=lambda item: (item["identity"], item["sha256"])),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _empty_result(
    *,
    graph: Graph,
    manifest: list[ImportManifestEntry],
    diagnostics: list[OntologyDiagnostic],
    complete: bool,
    profile: SemanticProfile,
    sources: list[LoadedOntologySource] | None = None,
) -> OntologyLoadResult:
    ordered_manifest = tuple(
        sorted(manifest, key=lambda item: (item.import_depth, item.source_identity))
    )
    ordered_diagnostics = tuple(
        sorted(
            diagnostics,
            key=lambda item: (
                item.code,
                item.import_uri or "",
                item.source_path or "",
                item.message,
            ),
        )
    )
    return OntologyLoadResult(
        graph=graph,
        manifest=ordered_manifest,
        diagnostics=ordered_diagnostics,
        complete=complete,
        closure_hash=_closure_hash(ordered_manifest),
        profile=profile,
        sources=tuple(
            sorted(
                sources or [],
                key=lambda item: (
                    item.manifest.import_depth,
                    item.manifest.source_identity,
                ),
            )
        ),
    )


def load_ontology(
    ontology_path: Path,
    *,
    catalog_path: Path | None = None,
    profile: SemanticProfile | str = SemanticProfile.ASSERTED,
    degraded: bool = False,
    optional_imports: Iterable[str] = (),
    identity_root: Path | None = None,
) -> OntologyLoadResult:
    """Load a complete ontology import closure through one deterministic API."""
    root_path = Path(ontology_path).resolve()
    if catalog_path is None:
        catalog_path = next(
            (
                parent / "catalog-v001.xml"
                for parent in (root_path.parent, *root_path.parents)
                if (parent / "catalog-v001.xml").is_file()
            ),
            None,
        )
    selected_profile = SemanticProfile(profile)
    optional = frozenset(str(uri) for uri in optional_imports)
    stable_root = (
        Path(identity_root).resolve()
        if identity_root is not None
        else Path(catalog_path).resolve().parent
        if catalog_path is not None
        else root_path.parent
    )

    resolver = CatalogResolver(Path(catalog_path)) if catalog_path is not None else None
    graph = Graph()
    manifest: list[ImportManifestEntry] = []
    diagnostics: list[OntologyDiagnostic] = []
    sources: list[LoadedOntologySource] = []
    complete = True
    visited_paths: set[Path] = set()
    visited_imports: set[str] = set()
    queue = deque(
        [
            _PendingSource(
                path=root_path,
                import_uri=None,
                parent_import=None,
                depth=0,
                requirement=ImportRequirement.REQUIRED,
                ancestors=(),
            )
        ]
    )

    if resolver is not None:
        diagnostics.extend(
            OntologyDiagnostic(
                level=item["level"],
                code=item.get("code", "catalog_diagnostic"),
                message=item["message"],
            )
            for item in resolver.diagnostics
        )

    while queue:
        pending = queue.popleft()
        path = pending.path.resolve()
        if path in visited_paths:
            continue
        visited_paths.add(path)

        source_graph = Graph()
        rdf_format = _get_rdf_format(path)
        try:
            source_graph.parse(path, format=rdf_format)
        except Exception as exc:
            complete = False
            code = "root_parse_error" if pending.depth == 0 else "import_parse_error"
            diagnostics.append(
                OntologyDiagnostic(
                    level="error",
                    code=code,
                    message=f"Error loading {path}: {exc}",
                    import_uri=pending.import_uri,
                    source_path=str(path),
                )
            )
            if pending.depth == 0 or (
                pending.requirement is ImportRequirement.REQUIRED and not degraded
            ):
                result = _empty_result(
                    graph=graph,
                    manifest=manifest,
                    diagnostics=diagnostics,
                    complete=False,
                    profile=selected_profile,
                    sources=sources,
                )
                raise OntologyLoadError(diagnostics[-1].message, result) from exc
            continue

        graph += source_graph
        ontology_iri, ontology_version = _ontology_metadata(source_graph)
        identity = (
            ontology_iri
            or pending.import_uri
            or f"root:{_relative_identity(path, stable_root)}"
        )
        manifest_entry = ImportManifestEntry(
                ontology_iri=ontology_iri,
                source_path=str(path),
                source_identity=identity,
                parent_import=pending.parent_import,
                import_uri=pending.import_uri,
                import_depth=pending.depth,
                ontology_version=ontology_version,
                source_sha256=_source_hash(path),
                rdf_format=rdf_format,
                requirement=pending.requirement,
            )
        manifest.append(manifest_entry)
        sources.append(
            LoadedOntologySource(
                manifest=manifest_entry,
                graph=source_graph,
            )
        )

        imports = sorted({str(value) for value in source_graph.objects(predicate=OWL.imports)})
        for import_uri in imports:
            requirement = (
                ImportRequirement.OPTIONAL
                if import_uri in optional
                else ImportRequirement.REQUIRED
            )
            if import_uri.startswith("file://"):
                if requirement is ImportRequirement.REQUIRED:
                    complete = False
                diagnostics.append(
                    OntologyDiagnostic(
                        level="warning" if degraded or requirement is ImportRequirement.OPTIONAL else "error",
                        code="unsupported_file_import",
                        message=f"Unsupported file import: {import_uri}",
                        import_uri=import_uri,
                        source_path=str(path),
                    )
                )
                continue

            resolution = resolver.resolve_detailed(import_uri) if resolver else None
            resolved_path = resolution.path.resolve() if resolution and resolution.path else None
            if resolved_path is None or not resolved_path.is_file():
                if requirement is ImportRequirement.REQUIRED:
                    complete = False
                diagnostics.append(
                    OntologyDiagnostic(
                        level="warning" if degraded or requirement is ImportRequirement.OPTIONAL else "error",
                        code="missing_import",
                        message=f"No catalog mapping for required import: {import_uri}",
                        import_uri=import_uri,
                        source_path=str(path),
                    )
                )
                continue

            if resolution and resolution.ambiguous:
                complete = False
                diagnostics.append(
                    OntologyDiagnostic(
                        level="warning" if degraded else "error",
                        code="ambiguous_import",
                        message=(
                            f"Ambiguous catalog resolution for {import_uri}: "
                            + ", ".join(str(item) for item in resolution.candidates)
                        ),
                        import_uri=import_uri,
                        source_path=str(path),
                    )
                )
                if not degraded and requirement is ImportRequirement.REQUIRED:
                    continue

            if resolution and resolution.method == "hash_fallback":
                diagnostics.append(
                    OntologyDiagnostic(
                        level="warning",
                        code="hash_fallback",
                        message=(
                            f"Hash mismatch: owl:imports <{import_uri}> resolved via "
                            "'#' fallback."
                        ),
                        import_uri=import_uri,
                        source_path=str(resolved_path),
                    )
                )
            if resolution and resolution.method == "rewrite_extension":
                diagnostics.append(
                    OntologyDiagnostic(
                        level="info",
                        code="rewrite_extension",
                        message=(
                            f"Resolved via rewriteURI extension fallback: "
                            f"<{import_uri}> -> {resolved_path}"
                        ),
                        import_uri=import_uri,
                        source_path=str(resolved_path),
                    )
                )

            if resolved_path in pending.ancestors or resolved_path == path:
                diagnostics.append(
                    OntologyDiagnostic(
                        level="warning",
                        code="import_cycle",
                        message=f"Import cycle detected at: {import_uri}",
                        import_uri=import_uri,
                        source_path=str(resolved_path),
                    )
                )
                continue
            if import_uri in visited_imports or resolved_path in visited_paths:
                diagnostics.append(
                    OntologyDiagnostic(
                        level="info",
                        code="duplicate_import",
                        message=f"Import already loaded: {import_uri}",
                        import_uri=import_uri,
                        source_path=str(resolved_path),
                    )
                )
                continue

            visited_imports.add(import_uri)
            queue.append(
                _PendingSource(
                    path=resolved_path,
                    import_uri=import_uri,
                    parent_import=pending.import_uri or ontology_iri,
                    depth=pending.depth + 1,
                    requirement=requirement,
                    ancestors=pending.ancestors + (path,),
                )
            )

    result = _empty_result(
        graph=graph,
        manifest=manifest,
        diagnostics=diagnostics,
        complete=complete,
        profile=selected_profile,
        sources=sources,
    )
    if not complete and not degraded:
        raise OntologyLoadError(
            "Ontology closure is incomplete; rerun with degraded=True only when partial "
            "semantics are explicitly acceptable.",
            result,
        )
    from .semantic_index import build_semantic_index

    return OntologyLoadResult(
        graph=result.graph,
        manifest=result.manifest,
        diagnostics=result.diagnostics,
        complete=result.complete,
        closure_hash=result.closure_hash,
        profile=result.profile,
        semantic_index=build_semantic_index(result, selected_profile),
        sources=result.sources,
    )
