# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Canonical ontology class-diagram projector (DD-209 / issue #631).

One-way, documentation-only projection of the raw ontology graph into a Mermaid
``classDiagram`` per domain -- independent of ``EntityBinding``/compile-plan coverage.
Every existing diagram-like target either only shows what has been bound to a source
(``dbt``/``silver``/``gold``/``mdm-profile``) or requires explicit DDD-overlay vocabulary
(``ddd``). This target walks ``owl:Class``/``owl:ObjectProperty``/``rdfs:subClassOf``
directly off the loaded ontology graph so a canonical class, relationship, or class
hierarchy that is modeled but not yet bound (or not DDD-annotated) is still visible in at
least one diagram output.

Mermaid ``classDiagram`` was chosen over ``erDiagram`` specifically because OWL class
hierarchies are ordinary, common modeling content that ``erDiagram`` has no syntax for at
all (entity-relationship diagrams have no notion of inheritance). ``classDiagram``
renders that hierarchy as real inheritance arrows using the same ``mmdc`` CLI already
used elsewhere in this codebase -- no new diagram tooling. The Silver/Gold bound ERDs
stay on ``erDiagram``: they describe physical dbt tables, which have no class-hierarchy
concept.

Output is deterministic (sorted, no embedded timestamps) and, like ``ddd_projector.py``,
never influences silver/gold/dbt/Power BI generation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from .shared import class_ancestors, effective_domain_classes, named_parents
from .uri_utils import extract_local_name


def _sanitize(node_id: str) -> str:
    """Make a Mermaid-safe class/attribute identifier from a local name."""
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


def _multiplicity(min_bound: Optional[int], max_bound: Optional[int]) -> str:
    """Mermaid ``classDiagram`` multiplicity string for one end of an association.

    Same semantics as the crow's-foot tokens this replaced: an undeclared upper bound
    (``None``) or any bound greater than one renders as unbounded (``*``).
    """
    at_least_one = (min_bound or 0) >= 1
    if max_bound == 1:
        return "1" if at_least_one else "0..1"
    return "1..*" if at_least_one else "0..*"


def _collect_classes(graph: Graph, namespace: str) -> list[URIRef]:
    """Return every domain-local ``owl:Class`` (or ``rdfs:Class``), sorted by URI."""
    classes = {
        cls
        for cls in set(graph.subjects(RDF.type, OWL.Class))
        | set(graph.subjects(RDF.type, RDFS.Class))
        if isinstance(cls, URIRef) and str(cls).startswith(namespace)
    }
    return sorted(classes, key=str)


# The hierarchy walkers used to live here; they are now the shared projector-level authority
# in ``projections/shared.py`` so the SHACL/dbt path can honour ``sh:targetClass`` on an
# ancestor the same way this diagram does (#729). Blank-node ``rdfs:subClassOf`` objects are
# restrictions, walked separately by :func:`_restriction_bounds`.
_named_parents = named_parents
_ancestors = class_ancestors


def _external_label(cls: URIRef) -> str:
    """Return a short Mermaid stereotype naming the model an imported class came from.

    The last two path segments read well for the reference models in practice --
    ``https://kairosflow.ai/ont/bsp/party#TradeParty`` becomes ``bsp/party`` -- and are
    enough to answer "which model does this come from?" without widening the box.
    """
    text = str(cls).split("://", 1)[-1]
    text = text.split("#", 1)[0].rstrip("/")
    segments = [segment for segment in text.split("/") if segment][1:]
    label = "/".join(segments[-2:]) if segments else text
    return re.sub(r"[^0-9A-Za-z_./-]", "_", label) or "imported"


def _collect_relationships(
    graph: Graph, classes: list[URIRef]
) -> list[tuple[URIRef, URIRef, URIRef, URIRef, bool]]:
    """Return ``(left, declared_on, property, range, inherited)`` edges to render.

    Uses :func:`effective_domain_classes` (DD-131) so multi-class ``rdfs:domain``
    (``owl:unionOf``) and ``schema:domainIncludes`` are both honored -- the same
    domain-resolution authority the silver/dbt projectors already use. That function is
    deliberately **not** widened with ``rdfs:subClassOf`` entailment: it is the shared
    authority the silver/dbt projectors read, so inherited properties would start
    materializing as Silver columns project-wide. The inheritance walk lives here.

    Three cases, where previously only the first was kept (#678/#704):

    * the domain is domain-local -- the class's own relationship;
    * the domain is a *superclass* of a domain-local class, so that class has the
      relationship by inheritance. Rendered from the subclass, because that is the class
      whose instances carry it, and flagged so the diagram can say so;
    * neither, but the *range* is domain-local -- an imported class pointing **at** this
      domain, which the domain-scoped view should not hide either.

    ``declared_on`` is kept separate from ``left`` so :func:`_restriction_bounds` reads
    the cardinality from the class that actually declares the restriction.
    """
    class_set = set(classes)
    ancestry = {cls: set(_ancestors(graph, cls)) for cls in classes}
    edges: list[tuple[URIRef, URIRef, URIRef, URIRef, bool]] = []
    for prop in sorted(set(graph.subjects(RDF.type, OWL.ObjectProperty)), key=str):
        range_value = graph.value(prop, RDFS.range)
        if not isinstance(range_value, URIRef):
            continue
        for domain_cls in sorted(effective_domain_classes(graph, prop), key=str):
            if domain_cls in class_set:
                edges.append((domain_cls, domain_cls, prop, range_value, False))
                continue
            heirs = sorted(
                (cls for cls in classes if domain_cls in ancestry[cls]),
                key=str,
            )
            if heirs:
                for heir in heirs:
                    edges.append((heir, domain_cls, prop, range_value, True))
            elif range_value in class_set:
                edges.append((domain_cls, domain_cls, prop, range_value, False))
    edges.sort(key=lambda item: (str(item[0]), str(item[2]), str(item[3]), str(item[1])))
    return edges


def _collect_inheritance(graph: Graph, classes: list[URIRef]) -> list[tuple[URIRef, URIRef]]:
    """Return ``(superclass, subclass)`` pairs for every domain-local subclass.

    The superclass is no longer required to be domain-local (#678). Requiring it made
    the edge unreachable for the modeling style ``kairos-design-domain`` recommends --
    specializing an imported reference-model class -- which is precisely the case DD-212
    chose ``classDiagram`` over ``erDiagram`` to serve.
    """
    class_set = set(classes)
    pairs: list[tuple[URIRef, URIRef]] = []
    for cls in classes:
        for parent in _named_parents(graph, cls):
            if parent != cls:
                pairs.append((parent, cls))
    # An imported subclass of a local class is inbound structure, kept for the same
    # reason the inbound relationship case above is.
    for cls in sorted(set(graph.subjects(RDFS.subClassOf, None)), key=str):
        if not isinstance(cls, URIRef) or cls in class_set:
            continue
        for parent in _named_parents(graph, cls):
            if parent in class_set:
                pairs.append((parent, cls))
    pairs.sort(key=lambda item: tuple(str(part) for part in item))
    return pairs


def _datatype_properties(graph: Graph, owner: URIRef) -> list[URIRef]:
    return sorted(
        (
            prop
            for prop in graph.subjects(RDF.type, OWL.DatatypeProperty)
            if isinstance(prop, URIRef) and owner in effective_domain_classes(graph, prop)
        ),
        key=str,
    )


def _class_block(graph: Graph, cls: URIRef, *, stub: bool = False) -> str:
    """Render one Mermaid ``classDiagram`` class block.

    A *stub* is a class outside the domain namespace, drawn only because a domain class
    inherits from or references it. It carries a stereotype naming its source model and
    no members: its own attributes are listed on the domain classes that inherit them,
    so repeating them here would double every inherited attribute in the diagram.

    For a domain class, attributes declared on a superclass are included and prefixed
    ``#``. Without them a reviewer reads the box as the whole model -- the reported case
    was a party class rendering 5 of its 14 attributes, so a reader reasonably concluded
    the model had no party name or registration number (#678).
    """
    node = _sanitize(extract_local_name(str(cls)))
    lines = [f"    class {node} {{"]
    if stub:
        lines.append(f"        <<{_external_label(cls)}>>")
        lines.append("    }")
        return "\n".join(lines)

    own = _datatype_properties(graph, cls)
    seen = {str(prop) for prop in own}
    inherited: list[URIRef] = []
    for ancestor in _ancestors(graph, cls):
        for prop in _datatype_properties(graph, ancestor):
            if str(prop) not in seen:
                seen.add(str(prop))
                inherited.append(prop)

    for prop in own:
        lines.append(f"        {_attribute_type(graph, prop)} {_sanitize(extract_local_name(str(prop)))}")
    for prop in sorted(inherited, key=str):
        lines.append(
            f"        #{_attribute_type(graph, prop)} {_sanitize(extract_local_name(str(prop)))}"
        )
    if not own and not inherited:
        # Every class renders with at least one attribute so the block is always a
        # valid, visible Mermaid class even for classes with no declared datatype
        # properties (e.g. pure relationship hubs, or classes only bound downstream).
        lines.append("        string uri")
    lines.append("    }")
    return "\n".join(lines)


def generate_erd_artifacts(
    graph: Graph,
    namespace: str,
    ontology_name: str,
    ontology_metadata: Optional[dict] = None,
    overlay_path: Optional[Path] = None,
) -> dict:
    """Generate a binding-independent canonical class diagram for one ontology domain.

    Returns ``{}`` only when the domain has no local classes at all; unlike ``ddd``,
    this target has no opt-in overlay vocabulary to gate on, so any modeled class or
    relationship renders regardless of ``EntityBinding``/compile-plan/DDD status.

    *overlay_path* is an optional ``{domain}-erd-ext.ttl`` file (mirroring the ``ddd``
    overlay convention) whose triples are merged into the working graph before rendering.
    No packaged vocabulary exists for it yet -- this is plumbing only, so passing
    ``None`` (the default) leaves output byte-identical to before this parameter existed.
    """
    del ontology_metadata  # reserved for parity with other projector signatures
    domain = ontology_name or "domain"

    working_graph = graph
    if overlay_path is not None and Path(overlay_path).exists():
        working_graph = Graph()
        for triple in graph:
            working_graph.add(triple)
        working_graph.parse(overlay_path, format="turtle")

    classes = _collect_classes(working_graph, namespace)
    if not classes:
        return {}

    relationships = _collect_relationships(working_graph, classes)
    inheritance = _collect_inheritance(working_graph, classes)

    # Classes outside the namespace are drawn only where a domain class actually
    # reaches them -- as a superclass, or as either end of a rendered edge. An
    # unrelated imported class stays out, which is what keeps a domain-scoped diagram
    # domain-scoped while still showing the whole of what the domain classes are.
    local = set(classes)
    external = {
        node
        for node in (
            [parent for parent, _ in inheritance]
            + [subclass for _, subclass in inheritance]
            + [left for left, _, _, _, _ in relationships]
            + [range_cls for _, _, _, range_cls, _ in relationships]
        )
        if node not in local
    }

    lines = [
        "%% Canonical ontology class diagram (generated by kairos-ontology — do not edit)",
        "%% Binding-independent: reflects the ontology graph, not compile-plan coverage.",
        "%% A class outside this domain's namespace is drawn as a stub -- stereotyped with",
        "%% the model it comes from, and with no members of its own listed.",
        "%% A member prefixed # is inherited from a superclass; an edge labelled",
        "%% (inherited) is declared on a superclass and applies to this class.",
        "classDiagram",
    ]
    for cls in classes:
        lines.append(_class_block(working_graph, cls))
    for cls in sorted(external, key=str):
        lines.append(_class_block(working_graph, cls, stub=True))

    for superclass, subclass in inheritance:
        parent = _sanitize(extract_local_name(str(superclass)))
        child = _sanitize(extract_local_name(str(subclass)))
        lines.append(f"    {parent} <|-- {child}")

    for domain_cls, declared_on, prop, range_cls, inherited in relationships:
        left = _sanitize(extract_local_name(str(domain_cls)))
        right = _sanitize(extract_local_name(str(range_cls)))
        min_bound, max_bound = _restriction_bounds(working_graph, declared_on, prop)
        if max_bound is None and (prop, RDF.type, OWL.FunctionalProperty) in working_graph:
            max_bound = 1
        # The left (domain-class) side has no restriction to read directly from --
        # OWL restrictions are declared on the class holding the property, i.e. the
        # domain side, which is exactly what `_restriction_bounds` already captured
        # for the right side above. The only signal available for the left side is
        # inverse-functionality (at most one domain instance per range value).
        left_max = (
            1 if (prop, RDF.type, OWL.InverseFunctionalProperty) in working_graph else None
        )
        left_mult = _multiplicity(None, left_max)
        right_mult = _multiplicity(min_bound, max_bound)
        label = _sanitize(extract_local_name(str(prop)))
        if inherited:
            label = f"{label} (inherited)"
        lines.append(f'    {left} "{left_mult}" --> "{right_mult}" {right} : {label}')

    return {f"{domain}-erd.mmd": "\n".join(lines) + "\n"}
