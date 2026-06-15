# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Claim-driven projection sync (Slice 2).

Deterministic bridge between the Claim Registry and projection-facing authored
surfaces:

* domain ontology ``owl:imports`` (A1: imports generated from approved imported
  class claims),
* silver extension per-class ``kairos-ext:silverInclude`` assertions.

This module is AI-free and purely structural.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, XSD

from .claim_registry import load_registry
from .projections.shared import KAIROS_EXT


def _truthy(value: object) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes"}


def _class_uri_to_import_uri(class_uri: str) -> str:
    if "#" in class_uri:
        return class_uri.rsplit("#", 1)[0]
    if "/" in class_uri:
        return class_uri.rsplit("/", 1)[0]
    return class_uri


def _ontology_subject(graph: Graph) -> URIRef | None:
    for subject in graph.subjects(RDF.type, OWL.Ontology):
        if isinstance(subject, URIRef):
            return subject
    return None


def _domain_namespace_variants(ontology_iri: str) -> tuple[str, str]:
    bare = ontology_iri.rstrip("#/")
    return bare + "#", bare + "/"


def _is_local_class_uri(class_uri: str, ontology_iri: str) -> bool:
    hash_ns, slash_ns = _domain_namespace_variants(ontology_iri)
    return class_uri.startswith(hash_ns) or class_uri.startswith(slash_ns)


def _approved_imported_class_uris(registry, ontology_iri: str) -> set[str]:
    uris: set[str] = set()
    for claim in registry.claims:
        if claim.status != "approved":
            continue
        if claim.origin != "imported":
            continue
        if claim.disposition not in {"claim", "specialize"}:
            continue
        if not claim.class_uri:
            continue
        if _is_local_class_uri(claim.class_uri, ontology_iri):
            continue
        uris.add(claim.class_uri)
    return uris


def _expected_external_imports(approved_imported_class_uris: set[str]) -> set[str]:
    return {_class_uri_to_import_uri(uri).rstrip("#/") for uri in approved_imported_class_uris}


def _collect_hub_domain_bases(ontologies_dir: Path) -> set[str]:
    bases: set[str] = set()
    if not ontologies_dir.is_dir():
        return bases
    for path in sorted(ontologies_dir.glob("*.ttl")):
        if path.name.startswith("_") or path.name.endswith("-ext.ttl"):
            continue
        try:
            graph = Graph()
            graph.parse(path, format="turtle")
            subj = _ontology_subject(graph)
            if subj is not None:
                bases.add(str(subj).rstrip("#/"))
        except Exception:
            continue
    return bases


@dataclass
class DomainProjectionSync:
    domain: str
    claims_file: Path
    ontology_file: Path
    extension_file: Path
    missing_imports: list[str] = field(default_factory=list)
    extra_imports: list[str] = field(default_factory=list)
    missing_includes: list[str] = field(default_factory=list)
    extra_includes: list[str] = field(default_factory=list)
    has_bulk_include_imports: bool = False
    error: str | None = None

    @property
    def in_sync(self) -> bool:
        return (
            self.error is None
            and not self.missing_imports
            and not self.extra_imports
            and not self.missing_includes
            and not self.extra_includes
            and not self.has_bulk_include_imports
        )


@dataclass
class ProjectionSyncReport:
    domains: list[DomainProjectionSync] = field(default_factory=list)

    @property
    def out_of_sync(self) -> list[DomainProjectionSync]:
        return [d for d in self.domains if not d.in_sync]

    @property
    def is_blocking(self) -> bool:
        return bool(self.out_of_sync)


def evaluate_domain_projection_sync(
    *,
    domain: str,
    claims_file: Path,
    ontology_file: Path,
    extension_file: Path,
    hub_domain_bases: set[str],
) -> DomainProjectionSync:
    status = DomainProjectionSync(
        domain=domain,
        claims_file=claims_file,
        ontology_file=ontology_file,
        extension_file=extension_file,
    )

    if not claims_file.exists():
        status.error = f"missing claims file: {claims_file}"
        return status
    if not ontology_file.exists():
        status.error = f"missing ontology file: {ontology_file}"
        return status
    if not extension_file.exists():
        status.error = f"missing extension file: {extension_file}"
        return status

    try:
        registry = load_registry(claims_file)
        ontology_graph = Graph()
        ontology_graph.parse(ontology_file, format="turtle")
        ext_graph = Graph()
        ext_graph.parse(extension_file, format="turtle")
    except Exception as exc:  # noqa: BLE001
        status.error = str(exc)
        return status

    ontology_subj = _ontology_subject(ontology_graph)
    if ontology_subj is None:
        status.error = f"no owl:Ontology found in {ontology_file.name}"
        return status
    ontology_iri = str(ontology_subj)

    expected_includes = _approved_imported_class_uris(registry, ontology_iri)
    expected_imports = _expected_external_imports(expected_includes)

    actual_imports: set[str] = set()
    for obj in ontology_graph.objects(ontology_subj, OWL.imports):
        iri = str(obj).rstrip("#/")
        if iri in hub_domain_bases:
            continue
        actual_imports.add(iri)

    actual_includes: set[str] = set()
    for subj in ext_graph.subjects(KAIROS_EXT.silverInclude, None):
        subj_iri = str(subj)
        if _is_local_class_uri(subj_iri, ontology_iri):
            continue
        if _truthy(ext_graph.value(subj, KAIROS_EXT.silverInclude)):
            actual_includes.add(subj_iri)

    bulk_subj = URIRef(ontology_iri.rstrip("#/"))
    status.has_bulk_include_imports = _truthy(ext_graph.value(bulk_subj, KAIROS_EXT.silverIncludeImports))

    status.missing_imports = sorted(expected_imports - actual_imports)
    status.extra_imports = sorted(actual_imports - expected_imports)
    status.missing_includes = sorted(expected_includes - actual_includes)
    status.extra_includes = sorted(actual_includes - expected_includes)
    return status


def evaluate_projection_sync(
    *,
    claims_dir: Path,
    ontologies_dir: Path,
    extensions_dir: Path,
    domains_filter: list[str] | None = None,
) -> ProjectionSyncReport:
    report = ProjectionSyncReport()
    if not claims_dir.is_dir():
        return report

    lowers = [d.lower() for d in domains_filter] if domains_filter else None

    def _in_scope(name: str) -> bool:
        if lowers is None:
            return True
        return any(token in name.lower() for token in lowers)

    hub_domain_bases = _collect_hub_domain_bases(ontologies_dir)

    for claims_file in sorted(claims_dir.glob("*-claims.yaml")):
        domain = claims_file.name.replace("-claims.yaml", "")
        if not _in_scope(domain):
            continue
        ontology_file = ontologies_dir / f"{domain}.ttl"
        extension_file = extensions_dir / f"{domain}-silver-ext.ttl"
        report.domains.append(
            evaluate_domain_projection_sync(
                domain=domain,
                claims_file=claims_file,
                ontology_file=ontology_file,
                extension_file=extension_file,
                hub_domain_bases=hub_domain_bases,
            )
        )
    return report


def _rewrite_domain_projection_surfaces(
    *,
    claims_file: Path,
    ontology_file: Path,
    extension_file: Path,
    hub_domain_bases: set[str],
) -> None:
    registry = load_registry(claims_file)
    ontology_graph = Graph()
    ontology_graph.parse(ontology_file, format="turtle")
    ext_graph = Graph()
    ext_graph.parse(extension_file, format="turtle")

    ontology_subj = _ontology_subject(ontology_graph)
    if ontology_subj is None:
        raise ValueError(f"{ontology_file}: no owl:Ontology declaration found")
    ontology_iri = str(ontology_subj)
    expected_includes = _approved_imported_class_uris(registry, ontology_iri)
    expected_imports = _expected_external_imports(expected_includes)

    # Rewrite external imports according to approved imported claims (A1).
    for obj in list(ontology_graph.objects(ontology_subj, OWL.imports)):
        iri = str(obj).rstrip("#/")
        if iri in hub_domain_bases:
            continue
        ontology_graph.remove((ontology_subj, OWL.imports, obj))
    for iri in sorted(expected_imports):
        ontology_graph.add((ontology_subj, OWL.imports, URIRef(iri)))

    # Rewrite imported class silverInclude set from approved imported claims.
    for subj, obj in list(ext_graph.subject_objects(KAIROS_EXT.silverInclude)):
        subj_iri = str(subj)
        if _is_local_class_uri(subj_iri, ontology_iri):
            continue
        ext_graph.remove((subj, KAIROS_EXT.silverInclude, obj))
    for class_uri in sorted(expected_includes):
        ext_graph.set(
            (
                URIRef(class_uri),
                KAIROS_EXT.silverInclude,
                Literal(True, datatype=XSD.boolean),
            )
        )

    # A1 forbids bulk include-imports as a bypass.
    bulk_subj = URIRef(ontology_iri.rstrip("#/"))
    for obj in list(ext_graph.objects(bulk_subj, KAIROS_EXT.silverIncludeImports)):
        ext_graph.remove((bulk_subj, KAIROS_EXT.silverIncludeImports, obj))

    ontology_graph.serialize(destination=str(ontology_file), format="turtle")
    ext_graph.serialize(destination=str(extension_file), format="turtle")


def apply_projection_sync(
    *,
    claims_dir: Path,
    ontologies_dir: Path,
    extensions_dir: Path,
    domains_filter: list[str] | None = None,
) -> ProjectionSyncReport:
    report = evaluate_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=ontologies_dir,
        extensions_dir=extensions_dir,
        domains_filter=domains_filter,
    )
    hub_domain_bases = _collect_hub_domain_bases(ontologies_dir)
    for status in report.out_of_sync:
        if status.error is not None:
            continue
        _rewrite_domain_projection_surfaces(
            claims_file=status.claims_file,
            ontology_file=status.ontology_file,
            extension_file=status.extension_file,
            hub_domain_bases=hub_domain_bases,
        )
    return evaluate_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=ontologies_dir,
        extensions_dir=extensions_dir,
        domains_filter=domains_filter,
    )
