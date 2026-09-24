# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""SHACL counts on relationships, checked against the OWL they should not restate (DD-241).

Relationship (object-property) cardinality is declared once, in OWL: the class diagrams,
the contract ERD and the compiler's binding cross-check all read it there. A hand-authored
``sh:minCount``/``sh:maxCount`` on an object property is either a second copy that can
drift, a contradiction, or a bound only SHACL knows about -- which no diagram and no
compile check will ever see. On one real hub all 29 relationship bounds were declared in
both, because nothing said which one the toolkit reads (#999).

Warnings only: the shapes still validate data exactly as before. Datatype-property counts
(a required identifier literal, say) are SHACL's job and are never reported.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, SH

from .ontology_integrity import IntegrityDiagnostic

DUPLICATES = "cardinality.shacl-duplicates-owl"
CONTRADICTS = "cardinality.shacl-contradicts-owl"
SHACL_ONLY = "cardinality.shacl-only"

_REMEDIATION = (
    "Declare relationship cardinality in OWL only (docs/toolkit/how-to/"
    "declare-relationship-cardinality.md) and remove the sh:minCount/sh:maxCount on the "
    "object property."
)


def _count(graph: Graph, shape, predicate) -> Optional[int]:
    value = graph.value(shape, predicate)
    try:
        return int(str(value)) if value is not None else None
    except ValueError:
        return None


def hand_authored_shapes(shapes_path: Optional[Path]) -> list[Path]:
    """The hub's own shapes files: not the toolkit-managed ``kairos-*-shapes.shacl.ttl``."""
    if shapes_path is None or not Path(shapes_path).is_dir():
        return []
    return sorted(
        path
        for path in Path(shapes_path).glob("**/*.shacl.ttl")
        if not (path.name.startswith("kairos-") and path.name.endswith("-shapes.shacl.ttl"))
    )


def audit_shacl_cardinality(
    ontology_files: list[Path],
    shapes: list[tuple[str, Graph]],
    catalog_path: Optional[Path] = None,
) -> list[IntegrityDiagnostic]:
    """Report SHACL counts on object properties that duplicate, contradict or replace OWL.

    *shapes* is ``(domain, parsed shapes graph)`` per hand-authored file, parsed by the
    caller (the validator owns shape parsing). A shapes file is paired with the ontology
    of the same stem (``party.shacl.ttl`` with ``party.ttl``), the documented convention;
    one with no such ontology is skipped, as is an ontology that fails to load -- syntax
    and SHACL are reported by their own phases.
    """
    from .ontology_loader import SemanticProfile, load_ontology
    from .projections.erd_projector import edge_multiplicities

    by_stem = {path.stem: path for path in ontology_files}
    diagnostics: list[IntegrityDiagnostic] = []
    for domain, shapes_graph in shapes:
        ontology_file = by_stem.get(domain)
        if ontology_file is None:
            continue
        try:
            graph = load_ontology(
                ontology_file,
                catalog_path=Path(catalog_path) if catalog_path else None,
                profile=SemanticProfile.RDFS,
                degraded=True,
            ).graph
        except Exception:  # noqa: BLE001 - another phase reports a file that does not load
            continue
        for node_shape in sorted(set(shapes_graph.subjects(SH.property, None)), key=str):
            targets = [
                item
                for item in shapes_graph.objects(node_shape, SH.targetClass)
                if isinstance(item, URIRef)
            ]
            for property_shape in shapes_graph.objects(node_shape, SH.property):
                path = shapes_graph.value(property_shape, SH.path)
                if (
                    not isinstance(path, URIRef)
                    or (path, RDF.type, OWL.ObjectProperty) not in graph
                ):
                    continue
                shacl_min = _count(shapes_graph, property_shape, SH.minCount)
                shacl_max = _count(shapes_graph, property_shape, SH.maxCount)
                if shacl_min is None and shacl_max is None:
                    continue
                for target in sorted(targets, key=str):
                    _, (owl_min, owl_max) = edge_multiplicities(graph, target, target, path, target)
                    diagnostic = _judge(
                        domain, target, path, (shacl_min, shacl_max), (owl_min, owl_max)
                    )
                    if diagnostic is not None:
                        diagnostics.append(diagnostic)
    return diagnostics


def _judge(domain, target, path, shacl, owl) -> Optional[IntegrityDiagnostic]:
    pairs = [
        (label, stated, declared)
        for label, stated, declared in (("min", shacl[0], owl[0]), ("max", shacl[1], owl[1]))
        if stated is not None
    ]
    from .projections.uri_utils import extract_local_name

    where = f"{extract_local_name(str(target))}.{extract_local_name(str(path))}"
    contradictions = [
        f"sh:{label}Count {stated} vs OWL {declared}"
        for label, stated, declared in pairs
        if declared is not None and declared != stated
    ]
    if contradictions:
        return IntegrityDiagnostic(
            "warning",
            CONTRADICTS,
            f"{where}: SHACL and OWL disagree on the relationship's cardinality "
            f"({'; '.join(contradictions)}). The diagrams and compile read OWL.",
            domain,
            str(path),
            _REMEDIATION,
        )
    if all(declared is not None for _, _, declared in pairs):
        return IntegrityDiagnostic(
            "warning",
            DUPLICATES,
            f"{where}: the SHACL count restates the OWL bound; two copies of one bound drift.",
            domain,
            str(path),
            _REMEDIATION,
        )
    missing = ", ".join(
        f"{label} {stated}" for label, stated, declared in pairs if declared is None
    )
    return IntegrityDiagnostic(
        "warning",
        SHACL_ONLY,
        f"{where}: the bound ({missing}) exists only in SHACL, so the class and contract "
        "diagrams and the compile cross-check never see it. Declare it as an OWL "
        "restriction.",
        domain,
        str(path),
        _REMEDIATION,
    )
