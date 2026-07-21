# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Shared helpers for projection modules.

This module consolidates utility functions that were previously duplicated
across the medallion projectors (silver, gold, dbt). Projectors should
import from here rather than maintaining local copies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS

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
# Canonical foreign-key projection contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ForeignKeyDiagnostic:
    """An invalid authored FK annotation discovered during normalization."""

    kind: str
    property_uri: URIRef
    message: str


@dataclass(frozen=True, slots=True)
class ForeignKeyDescriptor:
    """Immutable normalized relationship consumed by all medallion projectors.

    ``domain_class`` and ``range_class`` retain the authored OWL direction.
    ``source_class`` is the class whose projected table owns the FK column and
    ``target_class`` is the referenced class after applying ``silverForeignKeyOn``.
    """

    property_uri: URIRef
    domain_class: URIRef
    range_class: URIRef
    source_class: URIRef
    target_class: URIRef
    is_functional: bool
    max_cardinality_classes: frozenset[URIRef]
    silver_foreign_key: bool
    silver_column_name: Optional[str]
    gold_column_name: Optional[str]
    redirected: bool
    reverse: bool
    junction_table_name: Optional[str]
    degenerate_dimension: bool
    nullable: Optional[bool]
    conditional_on_type: str

    @property
    def is_silver_fk(self) -> bool:
        """Whether the relationship has any canonical Silver FK signal."""
        return (
            self.redirected
            or self.silver_foreign_key
            or self.silver_column_name is not None
            or self.is_functional
            or bool(self.max_cardinality_classes)
        )

    def qualifies_silver(self, class_uri: URIRef | str | None = None) -> bool:
        """Return whether this relationship qualifies for Silver projection.

        When *class_uri* is supplied, a cardinality-only relationship qualifies
        only when the restriction applies to that class. Other signals are
        property-level and therefore independent of the class argument.
        """
        property_signal = (
            self.redirected
            or self.silver_foreign_key
            or self.silver_column_name is not None
            or self.is_functional
        )
        if property_signal:
            return True
        if class_uri is None:
            return bool(self.max_cardinality_classes)
        return URIRef(str(class_uri)) in self.max_cardinality_classes

    def qualifies_gold(
        self,
        *,
        explicit_fact: bool = False,
    ) -> bool:
        """Return whether this relationship qualifies for Gold projection."""
        return (
            explicit_fact
            or self.gold_column_name is not None
            or self.is_silver_fk
        )

    def physical_column_name(self, target_key_stem: str, *, layer: str) -> str:
        """Resolve the FK's physical source-column name for a projection layer."""
        override = self.gold_column_name if layer == "gold" else self.silver_column_name
        return portable_sql_identifier(
            override or f"{target_key_stem}_sk",
            annotation=f"{layer} foreign-key column",
        )


@dataclass(frozen=True, slots=True)
class ForeignKeyClassification:
    """Immutable result of normalizing every object-property relationship."""

    descriptors: tuple[ForeignKeyDescriptor, ...]
    diagnostics: tuple[ForeignKeyDiagnostic, ...]
    outgoing_relationship_sources: tuple[URIRef, ...]


def _max_cardinality_classes(graph: Graph, prop: URIRef) -> frozenset[URIRef]:
    """Classes with an OWL max-cardinality-one restriction on *prop*."""
    classes: set[URIRef] = set()
    for restriction in graph.subjects(OWL.onProperty, prop):
        values = (
            graph.value(restriction, OWL.maxQualifiedCardinality),
            graph.value(restriction, OWL.maxCardinality),
        )
        if not any(value is not None and _is_cardinality_one(value) for value in values):
            continue
        classes.update(
            owner
            for owner in graph.subjects(RDFS.subClassOf, restriction)
            if isinstance(owner, URIRef)
        )
    return frozenset(classes)


def _is_cardinality_one(value: object) -> bool:
    """Accept the RDF integer datatypes commonly used for cardinality literals."""
    try:
        return int(str(value)) == 1
    except (TypeError, ValueError):
        return False


def _nullable_annotation(graph: Graph, prop: URIRef) -> Optional[bool]:
    value = graph.value(prop, KAIROS_EXT.nullable)
    if value is None:
        return None
    return str(value).lower() not in ("false", "0")


def classify_foreign_keys(graph: Graph) -> ForeignKeyClassification:
    """Normalize authored OWL and Silver FK signals into one projection contract.

    Invalid ``silverForeignKey``/``silverForeignKeyOn`` annotations are retained
    as deterministic diagnostics but never become descriptors.
    """
    descriptors: list[ForeignKeyDescriptor] = []
    diagnostics: list[ForeignKeyDiagnostic] = []
    outgoing_relationship_sources: list[URIRef] = []

    for prop in sorted(graph.subjects(RDF.type, OWL.ObjectProperty), key=str):
        domain = graph.value(prop, RDFS.domain)
        range_class = graph.value(prop, RDFS.range)
        fk_on = graph.value(prop, KAIROS_EXT.silverForeignKeyOn)
        silver_foreign_key = bool_val(
            graph, prop, KAIROS_EXT.silverForeignKey, False,
        )
        prop_local = local_name(str(prop))
        junction_table_name = (
            str_val(graph, prop, KAIROS_EXT.junctionTableName) or None
        )
        degenerate_dimension = bool_val(
            graph, prop, KAIROS_EXT.degenerateDimension, False,
        )

        if domain is None or range_class is None:
            if fk_on is not None:
                diagnostics.append(ForeignKeyDiagnostic(
                    kind="incomplete_silver_foreign_key_on",
                    property_uri=prop,
                    message=(
                        f"silverForeignKeyOn on {prop_local} skipped "
                        "— missing rdfs:domain or rdfs:range."
                    ),
                ))
            elif silver_foreign_key:
                if domain is None and range_class is None:
                    missing = "rdfs:domain and rdfs:range"
                elif domain is None:
                    missing = "rdfs:domain"
                else:
                    missing = "rdfs:range"
                diagnostics.append(ForeignKeyDiagnostic(
                    kind="incomplete_silver_foreign_key",
                    property_uri=prop,
                    message=(
                        f"silverForeignKey on {prop_local} will be skipped "
                        f"— missing {missing}. Resolve via: kairos-design-domain"
                    ),
                ))
            continue

        if not isinstance(domain, URIRef) or not isinstance(range_class, URIRef):
            continue

        redirected = fk_on is not None
        reverse = False
        source_class = domain
        target_class = range_class
        if redirected:
            if fk_on != domain and fk_on != range_class:
                if not junction_table_name and not degenerate_dimension:
                    # Preserve the established Gold heuristic for an invalid
                    # annotation while still excluding it from FK projection.
                    outgoing_relationship_sources.append(domain)
                diagnostics.append(ForeignKeyDiagnostic(
                    kind="invalid_silver_foreign_key_on",
                    property_uri=prop,
                    message=(
                        f"silverForeignKeyOn on {prop_local} specifies "
                        f"{local_name(str(fk_on))} which is neither domain "
                        f"({local_name(str(domain))}) nor range "
                        f"({local_name(str(range_class))}) — skipped."
                    ),
                ))
                continue
            if fk_on == range_class:
                source_class = range_class
                target_class = domain
                reverse = True

        if not junction_table_name and not degenerate_dimension:
            outgoing_relationship_sources.append(source_class)

        silver_column_name = str_val(graph, prop, KAIROS_EXT.silverColumnName) or None
        gold_column_name = str_val(graph, prop, KAIROS_EXT.goldColumnName) or None
        descriptors.append(ForeignKeyDescriptor(
            property_uri=prop,
            domain_class=domain,
            range_class=range_class,
            source_class=source_class,
            target_class=target_class,
            is_functional=(prop, RDF.type, OWL.FunctionalProperty) in graph,
            max_cardinality_classes=_max_cardinality_classes(graph, prop),
            silver_foreign_key=silver_foreign_key,
            silver_column_name=silver_column_name,
            gold_column_name=gold_column_name,
            redirected=redirected,
            reverse=reverse,
            junction_table_name=junction_table_name,
            degenerate_dimension=degenerate_dimension,
            nullable=_nullable_annotation(graph, prop),
            conditional_on_type=str_val(
                graph, prop, KAIROS_EXT.conditionalOnType,
            ),
        ))

    return ForeignKeyClassification(
        tuple(descriptors),
        tuple(diagnostics),
        tuple(outgoing_relationship_sources),
    )


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
# Physical (silver) naming — single source of truth (issue #219, DD)
# ---------------------------------------------------------------------------
#
# Both the silver DDL projector and the dbt projector must derive identical
# physical schema/table/key names from the Silver extension graph. These helpers
# are the shared implementation so the two targets can never drift.
#
# Defaults are chosen so that, absent any ``kairos-ext:`` annotation, output is
# byte-identical to the previous hardcoded behaviour:
#   schema → ``silver_{ontology_name}``  (silverSchema override)
#   table  → ``camel_to_snake(local)``   (silverTableName / ref_ / namingConvention)


def silver_naming_convention(graph: "Graph", onto_uri: "URIRef") -> str:
    """Return the domain's silver naming convention (``camel-to-snake`` default)."""
    return str_val(graph, onto_uri, KAIROS_EXT.namingConvention, "camel-to-snake")


def silver_schema_name(graph: "Graph", onto_uri: "URIRef", ontology_name: str) -> str:
    """Resolve the physical silver schema name for a domain.

    Honours ``kairos-ext:silverSchema`` on the ``owl:Ontology`` node, falling
    back to ``silver_{ontology_name}``.
    """
    override = str_val(graph, onto_uri, KAIROS_EXT.silverSchema)
    if override:
        return portable_sql_identifier(override, annotation="kairos-ext:silverSchema")
    derived = re.sub(r"[^A-Za-z0-9_]", "_", f"silver_{ontology_name}")
    return portable_sql_identifier(derived, annotation="derived Silver schema")


def silver_table_name(
    graph: "Graph", cls_uri: "URIRef", local: str,
    naming_convention: str = "camel-to-snake",
) -> str:
    """Resolve the physical silver table/model name for a class.

    Precedence: ``kairos-ext:silverTableName`` override → naming-convention
    transform of the local name → ``ref_`` prefix when the class is reference
    data (``kairos-ext:isReferenceData``).
    """
    override = str_val(graph, cls_uri, KAIROS_EXT.silverTableName)
    if override:
        return portable_sql_identifier(
            override, annotation="kairos-ext:silverTableName",
        )
    if naming_convention == "camel-to-snake":
        name = camel_to_snake(local)
    else:
        name = local.lower()
    is_ref = bool_val(graph, cls_uri, KAIROS_EXT.isReferenceData, False)
    if is_ref and not name.startswith("ref_"):
        name = f"ref_{name}"
    derived = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return portable_sql_identifier(derived, annotation="derived Silver table")


def portable_sql_identifier(value: str, *, annotation: str) -> str:
    """Validate an unquoted identifier shared by Fabric and Databricks."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(
            f"{annotation} value {value!r} is not a portable SQL identifier; "
            "use letters, digits, and underscores, starting with a letter or underscore."
        )
    return value


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

def merge_ext_graph(
    base_graph: Graph,
    ext_path: Optional[Path],
    fallback_paths: Optional[list] = None,
    peer_ext_paths: Optional[list] = None,
) -> Graph:
    """Create a working copy of *base_graph* with extension triples merged in.

    Always returns a new Graph instance to avoid mutating the caller's graph.

    Merge order (DD-023, updated for cross-domain NK resolution):
      1. base_graph triples (the domain ontology)
      2. fallback_paths triples (reference model defaults) — only added if the
         subject+predicate pair is not already declared in the domain extension
         (*ext_path*) or peer extensions.
      3. peer_ext_paths triples (other domain extensions) — added for cross-domain
         naturalKey resolution, but only if not already declared in the domain's
         own extension (*ext_path*).  Domain-own extension always takes priority.
      4. ext_path triples (hub domain extension) — highest priority, always added.

    If *ext_path* is None or doesn't exist, returns base + peers + fallbacks.
    If *peer_ext_paths* is None or empty, behaves identically to the original
    signature (backward-compatible).
    If *fallback_paths* is None or empty, behaves identically to the original
    signature (backward-compatible).
    """
    merged = Graph()
    for triple in base_graph:
        merged.add(triple)

    # Load domain extension into a separate graph for priority checking
    ext_graph = Graph()
    if ext_path and Path(ext_path).exists():
        ext_graph.parse(str(ext_path), format="turtle")

    # Collect subject+predicate pairs from domain extension for override check
    ext_sp_pairs: set = set()
    for s, p, _o in ext_graph:
        ext_sp_pairs.add((s, p))

    # Collect peer extension triples and their (s,p) pairs.
    # Peers override fallbacks but yield to domain ext.
    peer_sp_pairs: set = set()
    peer_triples: list = []
    if peer_ext_paths:
        for peer_path in peer_ext_paths:
            if peer_path and Path(peer_path).exists():
                try:
                    peer_graph = Graph()
                    peer_graph.parse(str(peer_path), format="turtle")
                    for s, p, o in peer_graph:
                        if (s, p) not in ext_sp_pairs:
                            peer_sp_pairs.add((s, p))
                            peer_triples.append((s, p, o))
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).warning(
                        "Could not parse peer ext file %s: %s", peer_path, exc,
                    )

    # Add fallback triples — lowest priority: skip if domain ext OR peers define s+p
    if fallback_paths:
        for fb_path in fallback_paths:
            if fb_path and Path(fb_path).exists():
                fb_graph = Graph()
                fb_graph.parse(str(fb_path), format="turtle")
                for s, p, o in fb_graph:
                    if (s, p) not in ext_sp_pairs and (s, p) not in peer_sp_pairs:
                        merged.add((s, p, o))

    # Add peer extension triples (override fallbacks, yield to domain ext)
    for triple in peer_triples:
        merged.add(triple)

    # Add domain extension triples last (always wins)
    for triple in ext_graph:
        merged.add(triple)

    return merged
