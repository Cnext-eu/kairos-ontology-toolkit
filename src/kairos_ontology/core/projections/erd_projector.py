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
from collections.abc import Iterable
from typing import Optional

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS

from .shared import (
    class_ancestors,
    effective_domain_classes,
    mermaid_provenance_comment,
    named_parents,
)
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


def _declared_classes(local_graph: Optional[Graph], closure: Graph) -> set[URIRef]:
    """Return the classes the domain file itself declares, whatever namespace they are in.

    ``kairos-design-domain`` directs authors to reuse a reference-model class rather than
    mint a local one, re-declaring the imported IRI in the domain ``.ttl`` to attach
    ``rdfs:label``/``rdfs:comment``. Such a class keeps its reference-model IRI, so an
    IRI-prefix test never sees it as local and a domain modelled entirely that way
    produced no diagram at all (#805).

    Subject-side only: a class merely *referenced* by the domain file -- ``:SeaLeg
    rdfs:subClassOf imo-pc:SeaLeg`` names ``imo-pc:SeaLeg`` as an object -- stays external,
    which is what keeps a domain-scoped diagram domain-scoped. The class test is applied
    against the *closure*, because the domain file may attach an annotation without
    repeating ``a owl:Class``.
    """
    if local_graph is None:
        return set()
    typed = set(closure.subjects(RDF.type, OWL.Class)) | set(closure.subjects(RDF.type, RDFS.Class))
    return {
        subject
        for subject in set(local_graph.subjects(None, None))
        if isinstance(subject, URIRef) and subject in typed
    }


def _collect_classes(
    graph: Graph, namespace: str, local_graph: Optional[Graph] = None
) -> list[URIRef]:
    """Return every domain-local ``owl:Class`` (or ``rdfs:Class``), sorted by URI.

    Locality is the union of two signals: the IRI sits under the domain namespace, or the
    domain file declares it (#805). The union keeps a hub that mints local IRIs rendering
    exactly as before; *local_graph* is optional because the in-memory ``project_graph``
    entry point has no source file to offer.
    """
    classes = {
        cls
        for cls in set(graph.subjects(RDF.type, OWL.Class))
        | set(graph.subjects(RDF.type, RDFS.Class))
        if isinstance(cls, URIRef) and str(cls).startswith(namespace)
    }
    return sorted(classes | _declared_classes(local_graph, graph), key=str)


# The hierarchy walkers used to live here; they are now the shared projector-level authority
# in ``projections/shared.py`` so the SHACL/dbt path can honour ``sh:targetClass`` on an
# ancestor the same way this diagram does (#729). Blank-node ``rdfs:subClassOf`` objects are
# restrictions, walked separately by :func:`_restriction_bounds`.
_named_parents = named_parents
_ancestors = class_ancestors

#: ``(left, declared_on, property, range, inherited, folded_inverse)`` -- one drawn edge.
Edge = tuple[URIRef, URIRef, URIRef, URIRef, bool, Optional[URIRef]]


def _effective_bounds(
    graph: Graph, drawn: URIRef, declared_on: URIRef, prop: URIRef
) -> tuple[Optional[int], Optional[int]]:
    """Return the nearest OWL cardinality restriction on *prop* that applies to *drawn*.

    A restriction sits on whichever class the modeller chose: the class declaring the
    property, or a subclass tightening it -- ``:PortCallRecord rdfs:subClassOf
    [ owl:onProperty portcall:partOfVoyage ; owl:minCardinality 1 ; owl:maxCardinality 1 ]``
    on a hub subclass of a reference-model class. Reading only *declared_on* (the
    superclass, for an inherited edge) missed the subclass's restriction and rendered
    ``0..*`` (#753). The drawn class is checked first, then its ancestors nearest-first,
    then the declaring class; the first class carrying any bound wins.
    """
    seen: set[URIRef] = set()
    for owner in (drawn, *_ancestors(graph, drawn), declared_on):
        if owner in seen:
            continue
        seen.add(owner)
        bounds = _restriction_bounds(graph, owner, prop)
        if bounds != (None, None):
            return bounds
    return None, None


def _fold_inverses(graph: Graph, edges: list[Edge]) -> list[Edge]:
    """Collapse an ``owl:inverseOf`` pair drawn in both directions into one association.

    ``p`` and its inverse ``q`` are one relationship read from either end, but both are
    ``owl:ObjectProperty`` so each yielded its own edge and the pair drew twice (#753).
    When both directions are present between the same two classes, the edge whose property
    IRI sorts first is kept as the canonical direction and carries the inverse's name in
    its label; the other is dropped. An inverse declared but drawn in only one direction is
    left alone -- there is nothing to fold.
    """
    inverses: dict[URIRef, set[URIRef]] = {}
    for subject, obj in graph.subject_objects(OWL.inverseOf):
        if isinstance(subject, URIRef) and isinstance(obj, URIRef) and subject != obj:
            inverses.setdefault(subject, set()).add(obj)
            inverses.setdefault(obj, set()).add(subject)
    if not inverses:
        return edges
    present = {(left, prop, range_cls) for left, _, prop, range_cls, _, _ in edges}
    folded: list[Edge] = []
    for left, declared_on, prop, range_cls, inherited, _ in edges:
        partners = sorted(
            (other for other in inverses.get(prop, ()) if (range_cls, other, left) in present),
            key=str,
        )
        if any(str(other) < str(prop) for other in partners):
            continue  # the inverse direction is canonical and carries this name
        inverse = partners[0] if partners else None
        folded.append((left, declared_on, prop, range_cls, inherited, inverse))
    return folded


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


def _node_ids(classes: Iterable[URIRef]) -> dict[URIRef, str]:
    """Assign one Mermaid node id per class, disambiguating shared local names.

    The node id was the local name alone, so two distinct IRIs with the same fragment
    became the same node: ``:SeaLeg rdfs:subClassOf imo-pc:SeaLeg`` -- the style
    ``kairos-design-domain`` recommends -- rendered two ``class SeaLeg`` blocks that
    Mermaid merged, plus an inheritance edge from the node to itself, so the diagram
    asserted something the ontology does not (#806).

    A name claimed by exactly one class is left untouched: these diagrams are tracked and
    drift-gated in hubs, so existing output must stay byte-identical. A contested name
    takes the source-model label as a suffix (``SeaLeg_imo_port_call``), and IRI order
    breaks any residual tie so the result stays deterministic.
    """
    by_name: dict[str, list[URIRef]] = {}
    for cls in sorted(set(classes), key=str):
        by_name.setdefault(_sanitize(extract_local_name(str(cls))), []).append(cls)

    ids: dict[URIRef, str] = {}
    for name, claimants in by_name.items():
        if len(claimants) == 1:
            ids[claimants[0]] = name
            continue
        used: set[str] = set()
        for cls in claimants:
            candidate = f"{name}_{_sanitize(_external_label(cls))}"
            if candidate in used or candidate == name:
                candidate = f"{candidate}_{len(used) + 1}"
            used.add(candidate)
            ids[cls] = candidate
    return ids


def _collect_relationships(graph: Graph, classes: list[URIRef]) -> list[Edge]:
    """Return ``(left, declared_on, property, range, inherited, inverse)`` edges to render.

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

    ``declared_on`` is kept separate from ``left`` so :func:`_effective_bounds` can fall
    back to the declaring class after the drawn class and its ancestors have been checked
    for a cardinality restriction (#753). ``inverse`` is the ``owl:inverseOf`` partner
    folded into this edge by :func:`_fold_inverses`, or ``None``.
    """
    class_set = set(classes)
    ancestry = {cls: set(_ancestors(graph, cls)) for cls in classes}
    edges: list[Edge] = []
    for prop in sorted(set(graph.subjects(RDF.type, OWL.ObjectProperty)), key=str):
        range_value = graph.value(prop, RDFS.range)
        if not isinstance(range_value, URIRef):
            continue
        for domain_cls in sorted(effective_domain_classes(graph, prop), key=str):
            if domain_cls in class_set:
                edges.append((domain_cls, domain_cls, prop, range_value, False, None))
                continue
            heirs = sorted(
                (cls for cls in classes if domain_cls in ancestry[cls]),
                key=str,
            )
            if heirs:
                for heir in heirs:
                    edges.append((heir, domain_cls, prop, range_value, True, None))
            elif range_value in class_set:
                edges.append((domain_cls, domain_cls, prop, range_value, False, None))
    edges.sort(key=lambda item: (str(item[0]), str(item[2]), str(item[3]), str(item[1])))
    return _fold_inverses(graph, edges)


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


def _class_block(
    graph: Graph,
    cls: URIRef,
    *,
    stub: bool = False,
    external: bool = False,
    node_id: Optional[str] = None,
) -> str:
    """Render one Mermaid ``classDiagram`` class block.

    A *stub* carries a stereotype naming its source model and no members. That is right
    for an **inheritance ancestor** -- its attributes are already listed on the domain
    classes that inherit them, prefixed ``#``, so repeating them here would double every
    inherited attribute in the diagram. It is wrong for a class reached only across an
    object property: nothing inherits from it, so blanking it means its attributes
    appear nowhere in the diagram at all (#804). The caller decides which case applies.

    *external* is the separate question of whether the class comes from another model,
    and drives the stereotype alone. Every imported class carries one, members or not --
    without it a class drawn with members is indistinguishable from a domain-local one.

    For a domain class, attributes declared on a superclass are included and prefixed
    ``#``. Without them a reviewer reads the box as the whole model -- the reported case
    was a party class rendering 5 of its 14 attributes, so a reader reasonably concluded
    the model had no party name or registration number (#678).
    """
    node = node_id or _sanitize(extract_local_name(str(cls)))
    lines = [f"    class {node} {{"]
    if stub or external:
        lines.append(f"        <<{_external_label(cls)}>>")
    if stub:
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
        lines.append(
            f"        {_attribute_type(graph, prop)} {_sanitize(extract_local_name(str(prop)))}"
        )
    for prop in sorted(inherited, key=str):
        lines.append(
            f"        #{_attribute_type(graph, prop)} {_sanitize(extract_local_name(str(prop)))}"
        )
    if not own and not inherited and not (stub or external):
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
    local_graph: Optional[Graph] = None,
) -> dict:
    """Generate a binding-independent canonical class diagram for one ontology domain.

    Returns ``{}`` only when the domain has no local classes at all; unlike ``ddd``,
    this target has no opt-in overlay vocabulary to gate on, so any modeled class or
    relationship renders regardless of ``EntityBinding``/compile-plan/DDD status.

    *local_graph* is the domain ``.ttl``'s own parsed graph, without its import closure.
    It is what decides which classes are local; without it locality falls back to the
    IRI-prefix test, which misses a domain that re-declares imported IRIs (#805).

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

    classes = _collect_classes(working_graph, namespace, local_graph)
    if not classes:
        return {}

    lines = [
        # Which toolkit drew this, stamped into the artifact. These diagrams are
        # tracked and drift-gated, so a wall-clock time would fail the gate on every
        # run; *when* is what git history records, and only *which version* cannot be
        # recovered afterwards (#774).
        mermaid_provenance_comment(indent=""),
        "%% Canonical ontology class diagram: binding-independent, reflects the",
        "%% ontology graph rather than compile-plan coverage.",
        "%% An imported class is stereotyped with the model it comes from. One reached as",
        "%% a superclass is drawn as a stub with no members -- they are listed, prefixed #,",
        "%% on the classes that inherit them. One reached across a relationship lists its",
        "%% own members, because nothing else in the diagram carries them.",
        "%% A member prefixed # is inherited from a superclass; an edge labelled",
        "%% (inherited) is declared on a superclass and applies to this class.",
        "%% An edge labelled a / b is one owl:inverseOf pair drawn once: read left to right",
        "%% it is a, right to left it is b.",
        "classDiagram",
    ]
    lines.extend(_render_class_diagram(working_graph, classes))
    return {f"{domain}-erd.mmd": "\n".join(lines) + "\n"}


def _render_class_diagram(working_graph: Graph, classes: list[URIRef]) -> list[str]:
    """Render the ``classDiagram`` body -- blocks, then edges -- for *classes*.

    Shared by the per-domain diagram and the hub-wide master, so the two can never
    disagree about how a class, an inheritance edge or a relationship is drawn. *classes*
    are the local ones; anything they reach is drawn as an external.
    """
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
            + [left for left, _, _, _, _, _ in relationships]
            + [range_cls for _, _, _, range_cls, _, _ in relationships]
        )
        if node not in local
    }

    # Blank only what inheritance already renders inline. A class reached solely as a
    # relationship endpoint has no heir to carry its attributes, so drawing it empty
    # hides them completely -- the mirror image of the #678 defect, one hop across an
    # edge (#804). A class that is both keeps the stub: the heir still lists its members.
    lines: list[str] = []
    inheritance_stubs = {parent for parent, _ in inheritance}
    inheritance_stubs |= {subclass for _, subclass in inheritance}
    # Ids are assigned once over every class the diagram will draw, because a collision
    # is a property of the rendered set rather than of any one class (#806).
    node_ids = _node_ids(local | external)
    for cls in classes:
        lines.append(_class_block(working_graph, cls, node_id=node_ids[cls]))
    for cls in sorted(external, key=str):
        lines.append(
            _class_block(
                working_graph,
                cls,
                stub=cls in inheritance_stubs,
                external=True,
                node_id=node_ids[cls],
            )
        )

    for superclass, subclass in inheritance:
        parent = node_ids[superclass]
        child = node_ids[subclass]
        lines.append(f"    {parent} <|-- {child}")

    for domain_cls, declared_on, prop, range_cls, inherited, inverse in relationships:
        left = node_ids[domain_cls]
        right = node_ids[range_cls]
        min_bound, max_bound = _effective_bounds(working_graph, domain_cls, declared_on, prop)
        if max_bound is None and (prop, RDF.type, OWL.FunctionalProperty) in working_graph:
            max_bound = 1
        # OWL restrictions are declared on the class holding the property, i.e. the domain
        # side, which is what `_effective_bounds` captured for the right side above. The
        # left side has two signals: inverse-functionality of the forward property (at
        # most one domain instance per range value) and, when an owl:inverseOf partner was
        # folded into this edge, the partner's own restriction on the range class -- that
        # partner is declared there, so its bounds are exactly the left multiplicity.
        left_min: Optional[int] = None
        left_max = 1 if (prop, RDF.type, OWL.InverseFunctionalProperty) in working_graph else None
        if inverse is not None:
            left_min, inverse_max = _effective_bounds(working_graph, range_cls, range_cls, inverse)
            if inverse_max is not None:
                left_max = inverse_max
            elif (inverse, RDF.type, OWL.FunctionalProperty) in working_graph:
                left_max = 1
        left_mult = _multiplicity(left_min, left_max)
        right_mult = _multiplicity(min_bound, max_bound)
        label = _sanitize(extract_local_name(str(prop)))
        if inverse is not None:
            label = f"{label} / {_sanitize(extract_local_name(str(inverse)))}"
        if inherited:
            label = f"{label} (inherited)"
        lines.append(f'    {left} "{left_mult}" --> "{right_mult}" {right} : {label}')

    return lines


#: The hub-wide master, written beside the per-domain ``{domain}-erd.mmd`` files (#753).
MASTER_CLASS_DIAGRAM_NAME = "master-class-diagram.mmd"

#: One domain's contribution to the master: its import closure, the namespace that decides
#: IRI-prefix locality, and its own file's graph for declared locality (#805).
MasterErdDomain = tuple[Graph, str, Optional[Graph]]


def generate_master_class_diagram(
    domains: Iterable[MasterErdDomain], hub_name: str = "master"
) -> Optional[str]:
    """Render every domain's canonical classes into one hub-wide ``classDiagram``.

    Drawn from the graphs, not merged from the per-domain files. A text merge keyed on
    the Mermaid node id -- the class's local name -- collapsed two different classes that
    share a name (``party:Address`` and ``billing:Address``) into one block and dropped
    the other silently, and drew one IRI as several nodes wherever two domains had
    disambiguated it differently, because #806 assigns ids per rendered set. Here the
    rendered set *is* the whole hub: ``_node_ids`` disambiguates once, hub-wide, and one
    IRI is one node by construction. A per-domain file left behind by a renamed domain no
    longer leaks into the master either.

    Returns ``None`` when no domain has a class to draw, which the caller reports rather
    than writing an empty diagram.
    """
    merged = Graph()
    classes: set[URIRef] = set()
    for graph, namespace, local_graph in domains:
        classes.update(_collect_classes(graph, namespace, local_graph))
        for triple in graph:
            merged.add(triple)
    if not classes:
        return None

    lines = [
        mermaid_provenance_comment(indent=""),
        f"%% Master canonical class diagram for {hub_name}: every domain merged into one.",
        "%% Binding-independent: reflects the ontology graph, not compile-plan coverage.",
        "%% Drawn from the domain graphs together: a class two domains reach is one node,",
        "%% and two classes that merely share a local name stay two.",
        "classDiagram",
    ]
    lines.extend(_render_class_diagram(merged, sorted(classes, key=str)))
    return "\n".join(lines) + "\n"
