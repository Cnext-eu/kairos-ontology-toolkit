# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Versioned semantic index for canonical ontology closures (DD-103)."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Iterable

from rdflib import BNode, Graph, Literal, OWL, RDF, RDFS, URIRef
from rdflib.collection import Collection

from .ontology_loader import OntologyLoadResult, SemanticProfile

SEMANTIC_INDEX_VERSION = "1.0"


def _local_name(uri: str) -> str:
    return uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


@dataclass(frozen=True)
class TermProvenance:
    """Source module provenance for an indexed term or fact."""

    source_identity: str
    import_depth: int
    asserted: bool = True


@dataclass(frozen=True)
class SemanticLink:
    """URI relation with inference and source provenance."""

    uri: str
    provenance: TermProvenance
    distance: int = 1


@dataclass(frozen=True)
class RestrictionRecord:
    """Supported OWL restriction attached to a class."""

    on_property: str
    kind: str
    value: str | int
    qualified_class: str | None
    provenance: TermProvenance


@dataclass(frozen=True)
class ClassRecord:
    """Indexed ontology class."""

    uri: str
    name: str
    label: str
    comment: str
    provenance: TermProvenance
    ancestors: tuple[SemanticLink, ...]
    descendants: tuple[SemanticLink, ...]
    direct_properties: tuple[SemanticLink, ...]
    inherited_properties: tuple[SemanticLink, ...]
    equivalent_classes: tuple[SemanticLink, ...]
    restrictions: tuple[RestrictionRecord, ...]
    intersection_members: tuple[SemanticLink, ...]
    union_members: tuple[SemanticLink, ...]


@dataclass(frozen=True)
class PropertyRecord:
    """Indexed RDF/OWL property."""

    uri: str
    name: str
    label: str
    comment: str
    property_type: str
    provenance: TermProvenance
    domains: tuple[SemanticLink, ...]
    ranges: tuple[SemanticLink, ...]
    superproperties: tuple[SemanticLink, ...]
    subproperties: tuple[SemanticLink, ...]
    equivalent_properties: tuple[SemanticLink, ...]
    inverse_properties: tuple[SemanticLink, ...]


@dataclass(frozen=True)
class IndividualRecord:
    """Indexed named individual and its asserted/inferred classes."""

    uri: str
    name: str
    label: str
    provenance: TermProvenance
    classes: tuple[SemanticLink, ...]


@dataclass(frozen=True)
class SemanticIndex:
    """Deterministic immutable semantic view of one ontology closure."""

    version: str
    profile: SemanticProfile
    closure_hash: str
    import_complete: bool
    classes: tuple[ClassRecord, ...]
    properties: tuple[PropertyRecord, ...]
    individuals: tuple[IndividualRecord, ...]

    def class_by_uri(self, uri: str) -> ClassRecord | None:
        """Return a class by full URI."""
        return next((item for item in self.classes if item.uri == uri), None)

    def property_by_uri(self, uri: str) -> PropertyRecord | None:
        """Return a property by full URI."""
        return next((item for item in self.properties if item.uri == uri), None)

    def term(self, uri: str) -> ClassRecord | PropertyRecord | IndividualRecord | None:
        """Return any indexed term by full URI."""
        return (
            self.class_by_uri(uri)
            or self.property_by_uri(uri)
            or next((item for item in self.individuals if item.uri == uri), None)
        )

    def to_dict(self) -> dict[str, Any]:
        """Return deterministic JSON/YAML-compatible index data."""
        return {
            "semantic_index_version": self.version,
            "semantic_profile": self.profile.value,
            "closure_hash": self.closure_hash,
            "import_complete": self.import_complete,
            "classes": [_record_dict(item) for item in self.classes],
            "properties": [_record_dict(item) for item in self.properties],
            "individuals": [_record_dict(item) for item in self.individuals],
        }

    def slice(
        self,
        *,
        class_uris: Iterable[str] | None = None,
        max_classes: int | None = None,
        selection_rule: str = "uri-order",
    ) -> dict[str, Any]:
        """Return a bounded class slice with mandatory coverage disclosure."""
        requested = set(class_uris or ())
        candidates = [
            item for item in self.classes if not requested or item.uri in requested
        ]
        included = candidates[:max_classes] if max_classes is not None else candidates
        included_uris = {item.uri for item in included}
        omitted_modules = sorted(
            {
                item.provenance.source_identity
                for item in candidates
                if item.uri not in included_uris
            }
        )
        return {
            "metadata": {
                "semantic_index_version": self.version,
                "semantic_profile": self.profile.value,
                "closure_hash": self.closure_hash,
                "import_complete": self.import_complete,
                "total_class_count": len(self.classes),
                "candidate_class_count": len(candidates),
                "included_class_count": len(included),
                "selection_rule": selection_rule,
                "truncated": len(included) < len(candidates),
                "omitted_modules": omitted_modules,
            },
            "classes": [_record_dict(item) for item in included],
        }


def _record_dict(record: Any) -> dict[str, Any]:
    data = asdict(record)
    return data


def _term_provenance(
    result: OntologyLoadResult,
    subject: URIRef | BNode,
    predicate: URIRef | None = None,
    obj: Any | None = None,
    *,
    asserted: bool = True,
) -> TermProvenance:
    for source in result.sources:
        if predicate is None:
            if any(source.graph.triples((subject, None, None))):
                return TermProvenance(
                    source.manifest.source_identity,
                    source.manifest.import_depth,
                    asserted,
                )
        elif (subject, predicate, obj) in source.graph:
            return TermProvenance(
                source.manifest.source_identity,
                source.manifest.import_depth,
                asserted,
            )
    root = result.manifest[0]
    return TermProvenance(root.source_identity, root.import_depth, asserted)


def _is_asserted(
    result: OntologyLoadResult,
    subject: Any,
    predicate: Any,
    obj: Any,
) -> bool:
    return any((subject, predicate, obj) in source.graph for source in result.sources)


def _uri_objects(graph: Graph, subject: Any, predicate: URIRef) -> set[URIRef]:
    return {
        value
        for value in graph.objects(subject, predicate)
        if isinstance(value, URIRef)
    }


def _transitive_links(
    graph: Graph,
    result: OntologyLoadResult,
    start: URIRef,
    predicate: URIRef,
    *,
    inverse: bool = False,
    transitive: bool,
) -> tuple[SemanticLink, ...]:
    links: dict[str, SemanticLink] = {}
    queue: deque[tuple[URIRef, int]] = deque([(start, 0)])
    visited = {start}
    while queue:
        current, distance = queue.popleft()
        values = (
            graph.subjects(predicate, current)
            if inverse
            else graph.objects(current, predicate)
        )
        for value in values:
            if not isinstance(value, URIRef) or value in visited:
                continue
            visited.add(value)
            fact_subject, fact_object = (value, current) if inverse else (current, value)
            asserted = distance == 0
            provenance = _term_provenance(
                result,
                fact_subject,
                predicate,
                fact_object,
                asserted=asserted,
            )
            links[str(value)] = SemanticLink(
                uri=str(value),
                provenance=provenance,
                distance=distance + 1,
            )
            if transitive:
                queue.append((value, distance + 1))
    return tuple(sorted(links.values(), key=lambda item: (item.distance, item.uri)))


def _symmetric_links(
    graph: Graph,
    result: OntologyLoadResult,
    start: URIRef,
    predicate: URIRef,
    *,
    transitive: bool,
) -> tuple[SemanticLink, ...]:
    """Traverse a symmetric relation in both asserted directions."""
    links: dict[str, SemanticLink] = {}
    queue: deque[tuple[URIRef, int]] = deque([(start, 0)])
    visited = {start}
    while queue:
        current, distance = queue.popleft()
        pairs = [
            (current, value)
            for value in graph.objects(current, predicate)
            if isinstance(value, URIRef)
        ]
        pairs.extend(
            (subject, current)
            for subject in graph.subjects(predicate, current)
            if isinstance(subject, URIRef)
        )
        for fact_subject, fact_object in pairs:
            value = fact_object if fact_subject == current else fact_subject
            if value in visited:
                continue
            visited.add(value)
            provenance = _term_provenance(
                result,
                fact_subject,
                predicate,
                fact_object,
                asserted=distance == 0,
            )
            links[str(value)] = SemanticLink(
                str(value),
                provenance,
                distance + 1,
            )
            if transitive:
                queue.append((value, distance + 1))
    return tuple(sorted(links.values(), key=lambda item: (item.distance, item.uri)))


def _list_members(graph: Graph, head: Any) -> tuple[URIRef, ...]:
    if not isinstance(head, BNode):
        return ()
    try:
        return tuple(item for item in Collection(graph, head) if isinstance(item, URIRef))
    except ValueError:
        return ()


def _restriction_records(
    graph: Graph,
    result: OntologyLoadResult,
    cls: URIRef,
) -> tuple[RestrictionRecord, ...]:
    records: list[RestrictionRecord] = []
    predicates = (
        ("someValuesFrom", OWL.someValuesFrom),
        ("allValuesFrom", OWL.allValuesFrom),
        ("minCardinality", OWL.minCardinality),
        ("maxCardinality", OWL.maxCardinality),
        ("cardinality", OWL.cardinality),
        ("minQualifiedCardinality", OWL.minQualifiedCardinality),
        ("maxQualifiedCardinality", OWL.maxQualifiedCardinality),
        ("qualifiedCardinality", OWL.qualifiedCardinality),
    )
    for restriction in graph.objects(cls, RDFS.subClassOf):
        if not isinstance(restriction, BNode):
            continue
        on_property = graph.value(restriction, OWL.onProperty)
        if not isinstance(on_property, URIRef):
            continue
        qualified = graph.value(restriction, OWL.onClass)
        qualified_uri = str(qualified) if isinstance(qualified, URIRef) else None
        provenance = _term_provenance(result, cls, RDFS.subClassOf, restriction)
        for kind, predicate in predicates:
            value = graph.value(restriction, predicate)
            if value is None:
                continue
            normalized: str | int
            if isinstance(value, Literal) and kind.lower().endswith("cardinality"):
                normalized = int(value)
            else:
                normalized = str(value)
            records.append(
                RestrictionRecord(
                    on_property=str(on_property),
                    kind=kind,
                    value=normalized,
                    qualified_class=qualified_uri,
                    provenance=provenance,
                )
            )
    return tuple(
        sorted(
            records,
            key=lambda item: (
                item.on_property,
                item.kind,
                str(item.value),
                item.qualified_class or "",
            ),
        )
    )


def _collection_links(
    graph: Graph,
    result: OntologyLoadResult,
    cls: URIRef,
    predicate: URIRef,
) -> tuple[SemanticLink, ...]:
    members: set[URIRef] = set()
    for expression in graph.objects(cls, OWL.equivalentClass):
        head = graph.value(expression, predicate)
        members.update(_list_members(graph, head))
    provenance = _term_provenance(result, cls)
    return tuple(
        SemanticLink(str(member), provenance)
        for member in sorted(members, key=str)
    )


def _property_type(graph: Graph, prop: URIRef) -> str:
    if (prop, RDF.type, OWL.ObjectProperty) in graph:
        return "object"
    if (prop, RDF.type, OWL.DatatypeProperty) in graph:
        return "datatype"
    if (prop, RDF.type, OWL.AnnotationProperty) in graph:
        return "annotation"
    return "rdf"


def _class_uris(graph: Graph) -> set[URIRef]:
    classes = {
        subject
        for class_type in (OWL.Class, RDFS.Class)
        for subject in graph.subjects(RDF.type, class_type)
        if isinstance(subject, URIRef)
    }
    classes.update(
        subject
        for subject in graph.subjects(RDFS.subClassOf, None)
        if isinstance(subject, URIRef)
    )
    classes.update(
        value
        for value in graph.objects(None, RDFS.subClassOf)
        if isinstance(value, URIRef)
    )
    return classes


def _property_uris(graph: Graph) -> set[URIRef]:
    properties = {
        subject
        for property_type in (
            RDF.Property,
            OWL.ObjectProperty,
            OWL.DatatypeProperty,
            OWL.AnnotationProperty,
        )
        for subject in graph.subjects(RDF.type, property_type)
        if isinstance(subject, URIRef)
    }
    for predicate in (RDFS.domain, RDFS.range, RDFS.subPropertyOf):
        properties.update(
            subject
            for subject in graph.subjects(predicate, None)
            if isinstance(subject, URIRef)
        )
    return properties


def _semantic_graph(result: OntologyLoadResult, profile: SemanticProfile) -> Graph:
    graph = Graph()
    graph += result.graph
    if profile is SemanticProfile.OWL_RL:
        from owlrl import DeductiveClosure, OWLRL_Semantics

        DeductiveClosure(OWLRL_Semantics).expand(graph)
    return graph


def build_semantic_index(
    result: OntologyLoadResult,
    profile: SemanticProfile | str,
) -> SemanticIndex:
    """Build the deterministic semantic index for *result* and *profile*."""
    selected_profile = SemanticProfile(profile)
    graph = _semantic_graph(result, selected_profile)
    transitive = selected_profile is not SemanticProfile.ASSERTED
    design = selected_profile in {SemanticProfile.KAIROS_DESIGN, SemanticProfile.OWL_RL}
    class_uris = _class_uris(graph)
    property_uris = _property_uris(graph)

    direct_properties: dict[URIRef, set[URIRef]] = {
        cls: {
            prop
            for prop in graph.subjects(RDFS.domain, cls)
            if isinstance(prop, URIRef)
        }
        for cls in class_uris
    }

    class_records: list[ClassRecord] = []
    for cls in sorted(class_uris, key=str):
        provenance = _term_provenance(result, cls)
        ancestors = _transitive_links(
            graph,
            result,
            cls,
            RDFS.subClassOf,
            transitive=transitive,
        )
        descendants = _transitive_links(
            graph,
            result,
            cls,
            RDFS.subClassOf,
            inverse=True,
            transitive=transitive,
        )
        direct = tuple(
            SemanticLink(str(prop), _term_provenance(result, prop))
            for prop in sorted(direct_properties.get(cls, set()), key=str)
        )
        inherited: dict[str, SemanticLink] = {}
        if transitive:
            for ancestor in ancestors:
                for prop in direct_properties.get(URIRef(ancestor.uri), set()):
                    inherited[str(prop)] = SemanticLink(
                        str(prop),
                        TermProvenance(
                            _term_provenance(result, prop).source_identity,
                            _term_provenance(result, prop).import_depth,
                            asserted=False,
                        ),
                        distance=ancestor.distance,
                    )
        equivalents = (
            _symmetric_links(
                graph,
                result,
                cls,
                OWL.equivalentClass,
                transitive=True,
            )
            if design
            else ()
        )
        class_records.append(
            ClassRecord(
                uri=str(cls),
                name=_local_name(str(cls)),
                label=str(graph.value(cls, RDFS.label) or _local_name(str(cls))),
                comment=str(graph.value(cls, RDFS.comment) or ""),
                provenance=provenance,
                ancestors=ancestors,
                descendants=descendants,
                direct_properties=direct,
                inherited_properties=tuple(
                    sorted(inherited.values(), key=lambda item: item.uri)
                ),
                equivalent_classes=equivalents,
                restrictions=_restriction_records(graph, result, cls) if design else (),
                intersection_members=(
                    _collection_links(graph, result, cls, OWL.intersectionOf)
                    if design
                    else ()
                ),
                union_members=(
                    _collection_links(graph, result, cls, OWL.unionOf)
                    if design
                    else ()
                ),
            )
        )

    property_records: list[PropertyRecord] = []
    for prop in sorted(property_uris, key=str):
        provenance = _term_provenance(result, prop)
        superproperties = _transitive_links(
            graph,
            result,
            prop,
            RDFS.subPropertyOf,
            transitive=transitive,
        )
        domains = _uri_objects(graph, prop, RDFS.domain)
        ranges = _uri_objects(graph, prop, RDFS.range)
        if transitive:
            for superproperty in superproperties:
                domains.update(
                    _uri_objects(graph, URIRef(superproperty.uri), RDFS.domain)
                )
                ranges.update(
                    _uri_objects(graph, URIRef(superproperty.uri), RDFS.range)
                )
        property_records.append(
            PropertyRecord(
                uri=str(prop),
                name=_local_name(str(prop)),
                label=str(graph.value(prop, RDFS.label) or _local_name(str(prop))),
                comment=str(graph.value(prop, RDFS.comment) or ""),
                property_type=_property_type(graph, prop),
                provenance=provenance,
                domains=tuple(
                    SemanticLink(
                        str(uri),
                        _term_provenance(
                            result,
                            prop,
                            RDFS.domain,
                            uri,
                            asserted=_is_asserted(
                                result, prop, RDFS.domain, uri
                            ),
                        ),
                    )
                    for uri in sorted(domains, key=str)
                ),
                ranges=tuple(
                    SemanticLink(
                        str(uri),
                        _term_provenance(
                            result,
                            prop,
                            RDFS.range,
                            uri,
                            asserted=_is_asserted(
                                result, prop, RDFS.range, uri
                            ),
                        ),
                    )
                    for uri in sorted(ranges, key=str)
                ),
                superproperties=superproperties,
                subproperties=_transitive_links(
                    graph,
                    result,
                    prop,
                    RDFS.subPropertyOf,
                    inverse=True,
                    transitive=transitive,
                ),
                equivalent_properties=(
                    _symmetric_links(
                        graph,
                        result,
                        prop,
                        OWL.equivalentProperty,
                        transitive=True,
                    )
                    if design
                    else ()
                ),
                inverse_properties=(
                    _symmetric_links(
                        graph,
                        result,
                        prop,
                        OWL.inverseOf,
                        transitive=False,
                    )
                    if design
                    else ()
                ),
            )
        )

    meta_types = {
        OWL.Class,
        RDFS.Class,
        RDF.Property,
        OWL.ObjectProperty,
        OWL.DatatypeProperty,
        OWL.AnnotationProperty,
        OWL.Ontology,
        OWL.Restriction,
    }
    individuals: list[IndividualRecord] = []
    if design:
        individual_uris = {
            subject
            for subject, _, class_uri in graph.triples((None, RDF.type, None))
            if isinstance(subject, URIRef)
            and isinstance(class_uri, URIRef)
            and class_uri not in meta_types
            and subject not in class_uris
            and subject not in property_uris
        }
        for individual in sorted(individual_uris, key=str):
            provenance = _term_provenance(result, individual)
            classes = sorted(
                _uri_objects(graph, individual, RDF.type),
                key=str,
            )
            individuals.append(
                IndividualRecord(
                    uri=str(individual),
                    name=_local_name(str(individual)),
                    label=str(
                        graph.value(individual, RDFS.label)
                        or _local_name(str(individual))
                    ),
                    provenance=provenance,
                    classes=tuple(
                        SemanticLink(
                            str(cls),
                            _term_provenance(result, individual, RDF.type, cls),
                        )
                        for cls in classes
                        if cls not in meta_types
                    ),
                )
            )

    return SemanticIndex(
        version=SEMANTIC_INDEX_VERSION,
        profile=selected_profile,
        closure_hash=result.closure_hash,
        import_complete=result.complete,
        classes=tuple(class_records),
        properties=tuple(property_records),
        individuals=tuple(individuals),
    )
