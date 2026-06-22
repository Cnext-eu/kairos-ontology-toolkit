# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Relationship-topology derivation for the Core Concepts Conformance phase (DD-090).

Given a loaded :class:`~kairos_ontology.archetype_loader.Archetype`, this module:

* resolves and parses **each ``ref_model_modules[].iri`` directly** via
  :class:`~kairos_ontology.catalog_utils.CatalogResolver` — it does *not* rely on
  ``owl:imports`` from an umbrella ontology (a DCSA umbrella file only follows its direct
  imports, so the archetype's leaf concepts never load that way),
* reports which ``core_concepts`` are present/missing in the resolved graph,
* projects the subgraph of ``owl:ObjectProperty`` edges whose ``rdfs:domain`` and
  ``rdfs:range`` both fall inside the concept set, and
* captures declared OWL cardinality (``min``/``max``/exact + qualified variants) and
  ``owl:FunctionalProperty`` so the interview only *asks* about genuinely-undeclared
  1-vs-many relationships.

All loading is local (no network); diagnostics are returned, never printed, so callers can
emit clean machine output.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rdflib import OWL, RDF, RDFS, Graph, URIRef

from .archetype_loader import Archetype, normalize_refmodels_root

logger = logging.getLogger(__name__)

_CATALOG_FILENAME = "catalog-v001.xml"


@dataclass
class TopologyEdge:
    """A directed object-property relationship between two core concepts."""

    property_uri: str
    property_label: str | None
    domain_uri: str
    range_uri: str
    #: Declared cardinality on the property via ``owl:Restriction`` (may be empty).
    min_cardinality: int | None = None
    max_cardinality: int | None = None
    exact_cardinality: int | None = None
    functional: bool = False

    @property
    def cardinality_declared(self) -> bool:
        """True when the ontology already pins the upper bound (no need to ask 1-vs-many)."""
        return (
            self.max_cardinality is not None
            or self.exact_cardinality is not None
            or self.functional
        )

    @property
    def mandatory(self) -> bool:
        """True when ``owl:minCardinality``/exact >= 1 declares the relationship required."""
        if self.exact_cardinality is not None:
            return self.exact_cardinality >= 1
        return self.min_cardinality is not None and self.min_cardinality >= 1


@dataclass
class TopologyResult:
    """Outcome of topology derivation for an archetype."""

    edges: list[TopologyEdge] = field(default_factory=list)
    present_concepts: list[str] = field(default_factory=list)
    missing_concepts: list[str] = field(default_factory=list)
    loaded_modules: list[str] = field(default_factory=list)
    diagnostics: list[dict[str, str]] = field(default_factory=list)

    def warnings(self) -> list[str]:
        """Return only warning-level diagnostic messages."""
        return [d["message"] for d in self.diagnostics if d["level"] == "warning"]


def build_concept_graph(refmodels_root: Path, archetype: Archetype) -> tuple[Graph, list[str], list[dict[str, str]]]:
    """Parse each archetype module directly and return ``(graph, loaded_iris, diagnostics)``.

    Modules that cannot be resolved or parsed produce a warning diagnostic and are skipped
    (the conformance flow continues with whatever resolved — contract row 10).
    """
    from .catalog_utils import CatalogResolver  # local import keeps module import cheap

    root = normalize_refmodels_root(refmodels_root)
    catalog_path = root / _CATALOG_FILENAME
    diagnostics: list[dict[str, str]] = []
    graph = Graph()
    loaded: list[str] = []

    if not catalog_path.is_file():
        diagnostics.append(
            {"level": "error", "message": f"Catalog not found at {catalog_path}; cannot resolve modules."}
        )
        return graph, loaded, diagnostics

    resolver = CatalogResolver(catalog_path)
    for module in archetype.ref_model_modules:
        local = resolver.resolve(module.iri)
        if local is None or not Path(local).is_file():
            diagnostics.append(
                {"level": "warning", "message": f"Could not resolve module <{module.iri}> via catalog; skipped."}
            )
            continue
        try:
            graph.parse(str(local), format="turtle")
            loaded.append(module.iri)
        except Exception as exc:  # noqa: BLE001 - one bad module must not abort the rest
            diagnostics.append(
                {"level": "warning", "message": f"Failed to parse module <{module.iri}> ({local}): {exc}"}
            )
    return graph, loaded, diagnostics


def _classify_concepts(graph: Graph, archetype: Archetype) -> tuple[list[str], list[str]]:
    """Split the archetype's core concepts into present / missing in the resolved graph."""
    present: list[str] = []
    missing: list[str] = []
    for uri in archetype.concept_uris():
        ref = URIRef(uri)
        if (ref, RDF.type, OWL.Class) in graph or (ref, RDF.type, RDFS.Class) in graph:
            present.append(uri)
        else:
            missing.append(uri)
    return present, missing


def _collect_cardinality(graph: Graph) -> dict[URIRef, dict[str, Any]]:
    """Map each property to its declared OWL cardinality across all ``owl:Restriction`` nodes.

    Captures ``owl:minCardinality``/``maxCardinality``/``cardinality`` and the qualified
    variants (``owl:minQualifiedCardinality`` etc.).  When a property carries several
    restrictions the tightest declared bound wins.
    """
    out: dict[URIRef, dict[str, Any]] = {}
    card_preds = {
        OWL.minCardinality: "min",
        OWL.minQualifiedCardinality: "min",
        OWL.maxCardinality: "max",
        OWL.maxQualifiedCardinality: "max",
        OWL.cardinality: "exact",
        OWL.qualifiedCardinality: "exact",
    }
    for restriction in graph.subjects(RDF.type, OWL.Restriction):
        prop = graph.value(restriction, OWL.onProperty)
        if not isinstance(prop, URIRef):
            continue
        bucket = out.setdefault(prop, {})
        for pred, key in card_preds.items():
            val = graph.value(restriction, pred)
            if val is None:
                continue
            try:
                num = int(val)
            except (TypeError, ValueError):
                continue
            if key == "min":
                bucket["min"] = max(bucket.get("min", num), num)
            elif key == "max":
                bucket["max"] = min(bucket.get("max", num), num)
            else:
                bucket["exact"] = num
    return out


def derive_topology(graph: Graph, archetype: Archetype) -> TopologyResult:
    """Derive the relationship topology for *archetype* from a resolved *graph*."""
    present, missing = _classify_concepts(graph, archetype)
    concept_set = {URIRef(u) for u in archetype.concept_uris()}
    cardinality = _collect_cardinality(graph)

    functional_props = set(graph.subjects(RDF.type, OWL.FunctionalProperty))

    edges: list[TopologyEdge] = []
    seen: set[tuple[str, str, str]] = set()
    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        if not isinstance(prop, URIRef):
            continue
        domains = [d for d in graph.objects(prop, RDFS.domain) if isinstance(d, URIRef)]
        ranges = [r for r in graph.objects(prop, RDFS.range) if isinstance(r, URIRef)]
        label = graph.value(prop, RDFS.label)
        card = cardinality.get(prop, {})
        for dom in domains:
            if dom not in concept_set:
                continue
            for rng in ranges:
                if rng not in concept_set:
                    continue
                key = (str(prop), str(dom), str(rng))
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    TopologyEdge(
                        property_uri=str(prop),
                        property_label=str(label) if label is not None else None,
                        domain_uri=str(dom),
                        range_uri=str(rng),
                        min_cardinality=card.get("min"),
                        max_cardinality=card.get("max"),
                        exact_cardinality=card.get("exact"),
                        functional=prop in functional_props,
                    )
                )

    edges.sort(key=lambda e: (e.domain_uri, e.property_uri, e.range_uri))
    return TopologyResult(
        edges=edges,
        present_concepts=present,
        missing_concepts=missing,
    )


def derive_archetype_topology(refmodels_root: Path, archetype: Archetype) -> TopologyResult:
    """Convenience wrapper: load each module's graph, then derive topology + concept coverage."""
    graph, loaded, diagnostics = build_concept_graph(refmodels_root, archetype)
    result = derive_topology(graph, archetype)
    result.loaded_modules = loaded
    result.diagnostics = diagnostics + result.diagnostics
    for uri in result.missing_concepts:
        result.diagnostics.append(
            {"level": "warning", "message": f"Core concept <{uri}> not found in resolved modules; skipped."}
        )
    return result
