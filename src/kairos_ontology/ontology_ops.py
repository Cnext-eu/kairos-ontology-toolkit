# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Ontology CRUD operations on in-memory rdflib Graphs."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from .projections.uri_utils import extract_local_name


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PropertyInfo:
    uri: str
    name: str
    label: str
    comment: str
    range_uri: str
    range_name: str
    is_object_property: bool = False


@dataclass
class ClassInfo:
    uri: str
    name: str
    label: str
    comment: str
    superclasses: List[str] = field(default_factory=list)
    properties: List[PropertyInfo] = field(default_factory=list)


@dataclass
class RelationshipInfo:
    uri: str
    name: str
    label: str
    comment: str
    domain: str
    range: str


@dataclass
class OntologyInfo:
    namespace: str
    classes: List[ClassInfo]
    relationships: List[RelationshipInfo]


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _detect_namespace(graph: Graph) -> str:
    """Detect the base namespace of an ontology graph."""
    for s in graph.subjects(RDF.type, OWL.Ontology):
        uri = str(s)
        if "#" in uri:
            return uri.rsplit("#", 1)[0] + "#"
        elif "/" in uri:
            return uri.rsplit("/", 1)[0] + "/"
        return uri + ":"
    # Fallback: most-common class namespace
    counts: Dict[str, int] = {}
    for s in graph.subjects(RDF.type, OWL.Class):
        uri = str(s)
        if "#" in uri:
            ns = uri.rsplit("#", 1)[0] + "#"
        elif "/" in uri:
            ns = uri.rsplit("/", 1)[0] + "/"
        else:
            ns = uri.rsplit(":", 1)[0] + ":"
        counts[ns] = counts.get(ns, 0) + 1
    return max(counts, key=counts.get) if counts else "urn:kairos:ont:core:"


def parse_ontology(path: str, format: str = "turtle") -> OntologyInfo:
    """Parse an ontology file into an :class:`OntologyInfo`."""
    graph = Graph()
    graph.parse(path, format=format)
    return _graph_to_info(graph)


def parse_ontology_content(content: str, format: str = "turtle") -> OntologyInfo:
    """Parse ontology TTL content (string) into an :class:`OntologyInfo`."""
    graph = Graph()
    graph.parse(data=content, format=format)
    return _graph_to_info(graph)


def _graph_to_info(graph: Graph) -> OntologyInfo:
    ns = _detect_namespace(graph)
    return OntologyInfo(
        namespace=ns,
        classes=list_classes(graph, ns),
        relationships=list_relationships(graph, ns),
    )


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def list_classes(graph: Graph, namespace: Optional[str] = None) -> List[ClassInfo]:
    """Return all ``owl:Class`` instances in *namespace* (or all if ``None``)."""
    namespace = namespace or _detect_namespace(graph)
    results: List[ClassInfo] = []
    for cls_uri in graph.subjects(RDF.type, OWL.Class):
        uri = str(cls_uri)
        if not uri.startswith(namespace):
            continue
        name = extract_local_name(uri)
        label = _first_literal(graph, cls_uri, RDFS.label) or name
        comment = _first_literal(graph, cls_uri, RDFS.comment) or ""
        supers = [
            extract_local_name(str(sc))
            for sc in graph.objects(cls_uri, RDFS.subClassOf)
            if str(sc).startswith(namespace)
        ]
        props = list_properties(graph, uri)
        results.append(ClassInfo(uri=uri, name=name, label=label, comment=comment,
                                 superclasses=supers, properties=props))
    return results


def list_properties(graph: Graph, class_uri: str) -> List[PropertyInfo]:
    """Return all datatype + object properties whose ``rdfs:domain`` is *class_uri*."""
    cls_ref = URIRef(class_uri)
    results: List[PropertyInfo] = []

    for prop_type, is_obj in [(OWL.DatatypeProperty, False), (OWL.ObjectProperty, True)]:
        for prop in graph.subjects(RDF.type, prop_type):
            domains = list(graph.objects(prop, RDFS.domain))
            if cls_ref not in domains:
                continue
            uri = str(prop)
            name = extract_local_name(uri)
            label = _first_literal(graph, prop, RDFS.label) or name
            comment = _first_literal(graph, prop, RDFS.comment) or ""
            rng = _first_object(graph, prop, RDFS.range)
            rng_uri = str(rng) if rng else str(XSD.string)
            rng_name = extract_local_name(rng_uri)
            results.append(PropertyInfo(
                uri=uri, name=name, label=label, comment=comment,
                range_uri=rng_uri, range_name=rng_name, is_object_property=is_obj,
            ))
    return results


def list_relationships(graph: Graph, namespace: Optional[str] = None) -> List[RelationshipInfo]:
    """Return all ``owl:ObjectProperty`` instances in *namespace*."""
    namespace = namespace or _detect_namespace(graph)
    results: List[RelationshipInfo] = []
    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        uri = str(prop)
        if not uri.startswith(namespace):
            continue
        name = extract_local_name(uri)
        label = _first_literal(graph, prop, RDFS.label) or name
        comment = _first_literal(graph, prop, RDFS.comment) or ""
        domain = _first_object(graph, prop, RDFS.domain)
        rng = _first_object(graph, prop, RDFS.range)
        results.append(RelationshipInfo(
            uri=uri, name=name, label=label, comment=comment,
            domain=extract_local_name(str(domain)) if domain else "Any",
            range=extract_local_name(str(rng)) if rng else "Any",
        ))
    return results


# ---------------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------------

def add_class(
    graph: Graph,
    namespace: str,
    class_name: str,
    label: Optional[str] = None,
    comment: Optional[str] = None,
    superclass_uri: Optional[str] = None,
) -> Graph:
    """Add an ``owl:Class`` to *graph*. Returns the same graph for chaining."""
    ns = Namespace(namespace)
    cls = ns[class_name]
    graph.add((cls, RDF.type, OWL.Class))
    graph.add((cls, RDFS.label, Literal(label or class_name)))
    if comment:
        graph.add((cls, RDFS.comment, Literal(comment)))
    if superclass_uri:
        graph.add((cls, RDFS.subClassOf, URIRef(superclass_uri)))
    return graph


def add_property(
    graph: Graph,
    namespace: str,
    property_name: str,
    domain_uri: str,
    range_uri: str = str(XSD.string),
    label: Optional[str] = None,
    comment: Optional[str] = None,
    is_object_property: bool = False,
) -> Graph:
    """Add a datatype or object property to *graph*."""
    ns = Namespace(namespace)
    prop = ns[property_name]
    prop_type = OWL.ObjectProperty if is_object_property else OWL.DatatypeProperty
    graph.add((prop, RDF.type, prop_type))
    graph.add((prop, RDFS.domain, URIRef(domain_uri)))
    graph.add((prop, RDFS.range, URIRef(range_uri)))
    graph.add((prop, RDFS.label, Literal(label or property_name)))
    if comment:
        graph.add((prop, RDFS.comment, Literal(comment)))
    return graph


def modify_class(
    graph: Graph,
    class_uri: str,
    label: Optional[str] = None,
    comment: Optional[str] = None,
) -> Graph:
    """Update label/comment of an existing class."""
    cls = URIRef(class_uri)
    if label is not None:
        graph.remove((cls, RDFS.label, None))
        graph.add((cls, RDFS.label, Literal(label)))
    if comment is not None:
        graph.remove((cls, RDFS.comment, None))
        graph.add((cls, RDFS.comment, Literal(comment)))
    return graph


def remove_class(graph: Graph, class_uri: str) -> Graph:
    """Remove a class and all triples where it appears as subject or object."""
    cls = URIRef(class_uri)
    graph.remove((cls, None, None))
    graph.remove((None, None, cls))
    return graph


def remove_property(graph: Graph, property_uri: str) -> Graph:
    """Remove a property and all triples where it appears as subject or object."""
    prop = URIRef(property_uri)
    graph.remove((prop, None, None))
    graph.remove((None, None, prop))
    return graph


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def serialize_graph(graph: Graph, format: str = "turtle") -> str:
    """Serialize a graph back to a string (default Turtle)."""
    return graph.serialize(format=format)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _first_literal(graph: Graph, subject, predicate) -> Optional[str]:
    for obj in graph.objects(subject, predicate):
        return str(obj)
    return None


def _first_object(graph: Graph, subject, predicate):
    for obj in graph.objects(subject, predicate):
        return obj
    return None
