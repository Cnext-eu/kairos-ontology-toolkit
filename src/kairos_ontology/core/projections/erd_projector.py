# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Canonical ontology ERD projector (DD-209 / issue #631).

One-way, documentation-only projection of the raw ontology graph into a Mermaid
``erDiagram`` per domain -- independent of ``EntityBinding``/compile-plan coverage.
Every existing diagram-like target either only shows what has been bound to a source
(``dbt``/``silver``/``gold``/``mdm-profile``) or requires explicit DDD-overlay vocabulary
(``ddd``). This target walks ``owl:Class``/``owl:ObjectProperty`` directly off the loaded
ontology graph so a canonical class or relationship that is modeled but not yet bound (or
not DDD-annotated) is still visible in at least one diagram output.

Output is deterministic (sorted, no embedded timestamps) and, like ``ddd_projector.py``,
never influences silver/gold/dbt/Power BI generation.
"""

from __future__ import annotations

import re
from typing import Optional

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from .shared import effective_domain_classes
from .uri_utils import extract_local_name


def _sanitize(node_id: str) -> str:
    """Make a Mermaid-safe entity/attribute identifier from a local name."""
    return re.sub(r"[^0-9A-Za-z_]", "_", node_id)


def _attribute_type(graph: Graph, prop: URIRef) -> str:
    """Return a short, Mermaid-safe type name for a datatype property's range."""
    range_value = graph.value(prop, RDFS.range)
    if range_value is None:
        return "string"
    local = extract_local_name(str(range_value))
    sanitized = _sanitize(local) if local else "string"
    return sanitized or "string"


def _as_int(value: object) -> Optional[int]:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _restriction_bounds(
    graph: Graph, owner: URIRef, prop: URIRef
) -> tuple[Optional[int], Optional[int]]:
    """Return the ``(min, max)`` OWL cardinality declared on *prop* for *owner*.

    ``None`` for a bound means "not declared". Handles the exact form
    (``owl:cardinality``/``owl:qualifiedCardinality``) and the separate min/max forms
    (``owl:minCardinality``/``owl:maxCardinality`` and their qualified counterparts),
    mirroring the restriction-walking pattern already used for FK cardinality-one
    detection in ``projections/shared.py`` (``owl:onProperty`` + ``rdfs:subClassOf``).
    """
    min_bound: Optional[int] = None
    max_bound: Optional[int] = None
    for restriction in graph.subjects(OWL.onProperty, prop):
        if (owner, RDFS.subClassOf, restriction) not in graph:
            continue
        exact = graph.value(restriction, OWL.cardinality) or graph.value(
            restriction, OWL.qualifiedCardinality
        )
        if exact is not None:
            n = _as_int(exact)
            if n is not None:
                min_bound = n
                max_bound = n
            continue
        mn = graph.value(restriction, OWL.minCardinality) or graph.value(
            restriction, OWL.minQualifiedCardinality
        )
        mx = graph.value(restriction, OWL.maxCardinality) or graph.value(
            restriction, OWL.maxQualifiedCardinality
        )
        if mn is not None:
            n = _as_int(mn)
            if n is not None:
                min_bound = n
        if mx is not None:
            n = _as_int(mx)
            if n is not None:
                max_bound = n
    return min_bound, max_bound


def _left_token(min_bound: Optional[int], max_bound: Optional[int]) -> str:
    """Mermaid cardinality token for the entity on the left of a relationship."""
    at_least_one = (min_bound or 0) >= 1
    if max_bound == 1:
        return "||" if at_least_one else "|o"
    return "}|" if at_least_one else "}o"


def _right_token(min_bound: Optional[int], max_bound: Optional[int]) -> str:
    """Mermaid cardinality token for the entity on the right of a relationship."""
    at_least_one = (min_bound or 0) >= 1
    if max_bound == 1:
        return "||" if at_least_one else "o|"
    return "|{" if at_least_one else "o{"


def _collect_classes(graph: Graph, namespace: str) -> list[URIRef]:
    """Return every domain-local ``owl:Class`` (or ``rdfs:Class``), sorted by URI."""
    classes = {
        cls
        for cls in set(graph.subjects(RDF.type, OWL.Class))
        | set(graph.subjects(RDF.type, RDFS.Class))
        if isinstance(cls, URIRef) and str(cls).startswith(namespace)
    }
    return sorted(classes, key=str)


def _collect_relationships(
    graph: Graph, classes: list[URIRef]
) -> list[tuple[URIRef, URIRef, URIRef]]:
    """Return ``(property, domain_class, range_class)`` triples for domain-local classes.

    Uses :func:`effective_domain_classes` (DD-131) so multi-class ``rdfs:domain``
    (``owl:unionOf``) and ``schema:domainIncludes`` are both honored -- the same
    domain-resolution authority the silver/dbt projectors already use.
    """
    class_set = set(classes)
    relationships: list[tuple[URIRef, URIRef, URIRef]] = []
    for prop in sorted(set(graph.subjects(RDF.type, OWL.ObjectProperty)), key=str):
        range_value = graph.value(prop, RDFS.range)
        if not isinstance(range_value, URIRef):
            continue
        for domain_cls in sorted(effective_domain_classes(graph, prop), key=str):
            if domain_cls in class_set:
                relationships.append((prop, domain_cls, range_value))
    relationships.sort(key=lambda item: tuple(str(part) for part in item))
    return relationships


def _entity_block(graph: Graph, cls: URIRef) -> str:
    """Render one Mermaid ``erDiagram`` entity block with its datatype attributes."""
    node = _sanitize(extract_local_name(str(cls)))
    props = sorted(
        (
            prop
            for prop in graph.subjects(RDF.type, OWL.DatatypeProperty)
            if isinstance(prop, URIRef) and cls in effective_domain_classes(graph, prop)
        ),
        key=str,
    )
    lines = [f"    {node} {{"]
    if props:
        for prop in props:
            attr_name = _sanitize(extract_local_name(str(prop)))
            lines.append(f"        {_attribute_type(graph, prop)} {attr_name}")
    else:
        # Every entity renders with at least one attribute so the block is always a
        # valid, visible Mermaid entity even for classes with no declared datatype
        # properties (e.g. pure relationship hubs, or classes only bound downstream).
        lines.append("        string uri")
    lines.append("    }")
    return "\n".join(lines)


def generate_erd_artifacts(
    graph: Graph,
    namespace: str,
    ontology_name: str,
    ontology_metadata: Optional[dict] = None,
) -> dict:
    """Generate a binding-independent canonical ERD for one ontology domain.

    Returns ``{}`` only when the domain has no local classes at all; unlike ``ddd``,
    this target has no opt-in overlay vocabulary to gate on, so any modeled class or
    relationship renders regardless of ``EntityBinding``/compile-plan/DDD status.
    """
    del ontology_metadata  # reserved for parity with other projector signatures
    domain = ontology_name or "domain"
    classes = _collect_classes(graph, namespace)
    if not classes:
        return {}

    relationships = _collect_relationships(graph, classes)

    lines = [
        "%% Canonical ontology ERD (generated by kairos-ontology — do not edit)",
        "%% Binding-independent: reflects the ontology graph, not compile-plan coverage.",
        "erDiagram",
    ]
    for cls in classes:
        lines.append(_entity_block(graph, cls))

    for prop, domain_cls, range_cls in relationships:
        left = _sanitize(extract_local_name(str(domain_cls)))
        right = _sanitize(extract_local_name(str(range_cls)))
        min_bound, max_bound = _restriction_bounds(graph, domain_cls, prop)
        if max_bound is None and (prop, RDF.type, OWL.FunctionalProperty) in graph:
            max_bound = 1
        # The left (domain-class) side has no restriction to read directly from --
        # OWL restrictions are declared on the class holding the property, i.e. the
        # domain side, which is exactly what `_restriction_bounds` already captured
        # for the right side above. The only signal available for the left side is
        # inverse-functionality (at most one domain instance per range value).
        left_max = 1 if (prop, RDF.type, OWL.InverseFunctionalProperty) in graph else None
        left_token = _left_token(None, left_max)
        right_token = _right_token(min_bound, max_bound)
        label = _sanitize(extract_local_name(str(prop)))
        lines.append(f"    {left} {left_token}--{right_token} {right} : {label}")

    return {f"{domain}-erd.mmd": "\n".join(lines) + "\n"}
