# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Shared helpers for projection modules.

This module consolidates utility functions that were previously duplicated
across the medallion projectors (silver, gold, dbt). Projectors should
import from here rather than maintaining local copies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF

# ---------------------------------------------------------------------------
# Typed dataclasses for structured projection data
# ---------------------------------------------------------------------------


@dataclass
class OntologyClassInfo:
    """Typed representation of an ontology class passed to projectors."""

    uri: str
    name: str
    label: str
    comment: str

    def to_dict(self) -> dict[str, str]:
        """Convert to the legacy dict format expected by projectors."""
        return {
            "uri": self.uri,
            "name": self.name,
            "label": self.label,
            "comment": self.comment,
        }


@dataclass
class OntologyMetadata:
    """Provenance metadata extracted from an owl:Ontology declaration."""

    label: str = ""
    version: str = ""
    namespace: str = ""
    file_name: str = ""
    description: str = ""


# ---------------------------------------------------------------------------
# kairos-ext namespace (shared across all medallion projectors)
# ---------------------------------------------------------------------------
KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")


# ---------------------------------------------------------------------------
# Name conversion helpers
# ---------------------------------------------------------------------------

def camel_to_snake(name: str) -> str:
    """Convert CamelCase or camelCase to snake_case (R4).

    Examples:
        InvoiceLine → invoice_line
        accountCode → account_code
    """
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def local_name(uri: str) -> str:
    """Extract local name from an ontology URI.

    Handles fragment (#), path (/), and URN (:) based URIs.

    Examples:
        http://example.org/ont#Person → Person
        http://example.org/ont/Person → Person
        urn:example:ont:Person → Person
    """
    if not uri:
        return ""
    if "#" in uri:
        return uri.rsplit("#", 1)[1]
    if "/" in uri:
        return uri.rsplit("/", 1)[1]
    if ":" in uri:
        return uri.rsplit(":", 1)[1]
    return uri


# ---------------------------------------------------------------------------
# RDF graph value accessors
# ---------------------------------------------------------------------------

def str_val(graph: Graph, subject: URIRef, predicate: URIRef,
            default: str = "") -> str:
    """Get a string literal value from the graph, with a default."""
    val = graph.value(subject, predicate)
    return str(val) if val is not None else default


def bool_val(graph: Graph, subject: URIRef, predicate: URIRef,
             default: bool = False) -> bool:
    """Get a boolean literal value from the graph, with a default."""
    val = graph.value(subject, predicate)
    if val is None:
        return default
    return str(val).lower() in ("true", "1", "yes")


def int_val(graph: Graph, subject: URIRef, predicate: URIRef,
            default: int = 0) -> int:
    """Get an integer literal value from the graph, with a default.

    Returns *default* if the value is missing or cannot be parsed as int.
    """
    val = graph.value(subject, predicate)
    if val is None:
        return default
    try:
        return int(str(val))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Ontology URI detection
# ---------------------------------------------------------------------------

def detect_ontology_uri(graph: Graph, namespace: str) -> URIRef:
    """Return the owl:Ontology URI declared in the graph for *namespace*."""
    for s in graph.subjects(RDF.type, OWL.Ontology):
        if str(s).startswith(namespace.rstrip("#/")):
            return s
    return URIRef(namespace.rstrip("#/"))


# ---------------------------------------------------------------------------
# Mermaid helpers
# ---------------------------------------------------------------------------

def mmd_type(sql_type: str) -> str:
    """Sanitise a SQL type for use as a Mermaid erDiagram attribute type.

    Mermaid ATTRIBUTE_WORD only allows ``[A-Za-z0-9_]``.

    Examples:
        DECIMAL(18,4) → DECIMAL_18_4_
        STRING        → STRING
    """
    return re.sub(r"[^A-Za-z0-9_]", "_", sql_type).strip("_")


# ---------------------------------------------------------------------------
# Graph merge utility
# ---------------------------------------------------------------------------

def merge_ext_graph(base_graph: Graph, ext_path: Optional[Path]) -> Graph:
    """Create a working copy of *base_graph* with extension triples merged in.

    Always returns a new Graph instance to avoid mutating the caller's graph.
    If *ext_path* is None or doesn't exist, returns a plain copy.
    """
    merged = Graph()
    for triple in base_graph:
        merged.add(triple)
    if ext_path and Path(ext_path).exists():
        ext_graph = Graph()
        ext_graph.parse(str(ext_path), format="turtle")
        for triple in ext_graph:
            merged.add(triple)
    return merged
