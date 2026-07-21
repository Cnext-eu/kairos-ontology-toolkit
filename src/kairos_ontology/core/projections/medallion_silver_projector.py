# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Silver Layer Projector — generate MS Fabric Warehouse silver DDL, FK reference,
and Mermaid ERD from OWL ontologies annotated with kairos-ext: projection extensions.

Common annotation rules R1–R16 define the shared ``kairos-ext:`` vocabulary.
Silver Fabric rules S1–S8 control Warehouse-specific output behaviour:

  S1 — Spark SQL types (BOOLEAN, TIMESTAMP, STRING, DOUBLE)
  S2 — PK/FK/UNIQUE as DDL comments (Fabric can't enforce constraints)
  S3 — Flatten inheritance to single table + discriminator (opt-in via annotation)
  S4 — Inline small reference tables (≤3 columns) into parent
  S5 — ``_row_hash`` BINARY column for incremental MERGE
  S6 — ``_deleted_at`` TIMESTAMP soft-delete column
  S7 — Canonical schema ownership (no cross-domain table duplication)
  S8 — No ``dim_``/``fact_`` prefixes (reserved for Gold layer)

Default inheritance strategy is **Table-Per-Concrete-class (TPC)**: each concrete
class gets its own table inheriting parent properties.  S3 discriminator flattening
is activated only when the parent class has:
  ``kairos-ext:inheritanceStrategy "discriminator"``

Namespace:  kairos-ext:  https://kairos.cnext.eu/ext#
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace, URIRef, XSD
from rdflib.namespace import OWL, RDF, RDFS

from .shared import (
    ForeignKeyClassification,
    KAIROS_EXT,
    camel_to_snake,
    classify_foreign_keys,
    local_name,
    str_val as _str_val,
    bool_val as _bool_val,
    detect_ontology_uri as _detect_ontology_uri,
    mmd_type as _mmd_type,
    merge_ext_graph,
    silver_naming_convention,
    silver_schema_name,
    silver_table_name,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# XSD → SQL type mapping (S1 — Spark SQL types for MS Fabric Warehouse)
# ---------------------------------------------------------------------------
XSD_TO_SQL: dict[str, str] = {
    str(XSD.string): "STRING",
    str(XSD.normalizedString): "STRING",
    str(XSD.token): "STRING",
    str(XSD.integer): "BIGINT",
    str(XSD.int): "INT",
    str(XSD.long): "BIGINT",
    str(XSD.short): "SMALLINT",
    str(XSD.decimal): "DECIMAL(18,4)",
    str(XSD.float): "DOUBLE",
    str(XSD.double): "DOUBLE",
    str(XSD.boolean): "BOOLEAN",
    str(XSD.date): "DATE",
    str(XSD.dateTime): "TIMESTAMP",
    str(XSD.time): "STRING",
    str(XSD.gYear): "INT",
    str(XSD.anyURI): "STRING",
}

# Default audit envelope columns (R9)
_DEFAULT_AUDIT = (
    "_created_at TIMESTAMP, _updated_at TIMESTAMP, "
    "_source_system STRING, _load_date DATE, _batch_id STRING"
)


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase or camelCase to snake_case (R4)."""
    return camel_to_snake(name)


def _local_name(uri: str) -> str:
    """Extract local name from a URI."""
    return local_name(uri)


def _prefixed_iri(uri: str) -> str:
    """Derive a compact prefixed IRI from a full URI.

    Given ``https://acme.example/ontology/party#website``, returns ``party:website``.
    Falls back to the full local name if no path segment is found.
    """
    local = local_name(uri)
    # Strip fragment/local to get the namespace
    if "#" in uri:
        ns = uri.rsplit("#", 1)[0]
    elif "/" in uri:
        ns = uri.rsplit("/", 1)[0]
    else:
        return local
    # Last path segment of the namespace is the prefix
    prefix = ns.rsplit("/", 1)[-1] if "/" in ns else ns
    return f"{prefix}:{local}"


def _get_class_and_ancestors(
    graph: Graph, cls_uri: URIRef, class_uris: set[str],
    inherit_from: set[str] | None = None,
) -> set[URIRef]:
    """Resolve the full rdfs:subClassOf chain for *cls_uri*.

    Returns a set of URIRefs including *cls_uri* itself plus all ancestor classes
    that are NOT already in *class_uris* (separately projected — S3 handles those),
    UNLESS they appear in *inherit_from* (TPC parents whose properties should be
    inherited by the child table).
    Stops at owl:Thing and W3C namespace URIs.  Includes cycle protection.
    """
    result: set[URIRef] = {cls_uri}
    visited: set[str] = {str(cls_uri)}
    queue = [cls_uri]
    while queue:
        current = queue.pop()
        for parent in graph.objects(current, RDFS.subClassOf):
            if not isinstance(parent, URIRef):
                continue
            parent_str = str(parent)
            if parent_str in visited:
                continue
            visited.add(parent_str)
            # Stop at W3C vocabulary URIs (owl:Thing, rdfs:Resource, etc.)
            if parent_str.startswith("http://www.w3.org/"):
                continue
            # Skip ancestors that are separately projected (S3 handles them)
            # UNLESS they are TPC parents we should inherit from
            if parent_str in class_uris:
                if inherit_from and parent_str in inherit_from:
                    result.add(parent)
                    queue.append(parent)
                continue
            result.add(parent)
            queue.append(parent)
    return result


def _nearest_claimed_ancestor(
    graph: Graph, cls_uri: URIRef, class_uris: set[str],
) -> URIRef | None:
    """Find the nearest claimed (separately-projected) ancestor of *cls_uri*.

    Walks ``rdfs:subClassOf`` breadth-first, traversing ONLY through *unclaimed*
    intermediate classes, and returns the first claimed ancestor (a class whose
    URI is in *class_uris*) encountered. This lets S3 discriminator folding reach
    a claimed discriminator ancestor through unclaimed intermediates, e.g.
    ``CargoOperator -> Carrier(unclaimed) -> TradeParty(claimed)``.

    Returns the ancestor URIRef, or ``None`` if no claimed ancestor exists.

    Deterministic: parents are visited in sorted-URI order, level by level, so
    "nearest" means the smallest ``rdfs:subClassOf`` depth. If several claimed
    ancestors are reached at the same minimal depth with *conflicting*
    inheritance strategies, a warning is emitted and the lexicographically
    smallest URI is chosen. Cycle-safe; stops at W3C vocabulary URIs.

    For the common single-inheritance case this is equivalent to picking the
    claimed direct parent, so depth-1 folding behaviour is unchanged.
    """
    visited: set[str] = {str(cls_uri)}
    frontier: list[URIRef] = [cls_uri]
    while frontier:
        claimed_here: list[URIRef] = []
        next_frontier: list[URIRef] = []
        for current in frontier:
            parents = sorted(
                (p for p in graph.objects(current, RDFS.subClassOf)
                 if isinstance(p, URIRef)),
                key=str,
            )
            for parent in parents:
                parent_str = str(parent)
                if parent_str in visited:
                    continue
                visited.add(parent_str)
                if parent_str.startswith("http://www.w3.org/"):
                    continue
                if parent_str in class_uris:
                    claimed_here.append(parent)
                else:
                    next_frontier.append(parent)
        if claimed_here:
            claimed_here.sort(key=str)
            if len(claimed_here) > 1:
                strategies = {
                    (_str_val(graph, c, KAIROS_EXT.inheritanceStrategy) or "")
                    for c in claimed_here
                }
                if len(strategies) > 1:
                    logger.warning(
                        "Class %s reaches multiple nearest claimed ancestors with "
                        "conflicting inheritance strategies (%s); using %s. "
                        "Declare an explicit strategy to disambiguate.",
                        cls_uri,
                        ", ".join(str(c) for c in claimed_here),
                        claimed_here[0],
                    )
            return claimed_here[0]
        frontier = sorted(next_frontier, key=str)
    return None


def _resolve_s3_projected_class(
    cls_uri: URIRef,
    subtype_parents: dict[str, str] | None,
) -> URIRef:
    """Return the table-owning class URI after S3 discriminator folding."""
    if not subtype_parents:
        return cls_uri
    return URIRef(subtype_parents.get(str(cls_uri), str(cls_uri)))


# PII keywords for projection-time GDPR warning (mirrors validator.PII_KEYWORDS)
_PII_KEYWORDS: list[str] = [
    "first_name", "last_name", "date_of_birth", "national_id", "iban",
    "phone", "email", "address", "ssn", "passport", "tax_id", "gender",
    "ethnicity", "religion", "health", "maiden_name", "birth_place",
    "nationality", "marital_status",
]


def _warn_unprotected_pii(
    graph: Graph,
    domain_classes: list[dict],
    namespace: str,
) -> None:
    """Emit warnings for classes with PII-like properties lacking gdprSatelliteOf."""
    protected: set[str] = set()
    for subj in graph.subjects(KAIROS_EXT.gdprSatelliteOf, None):
        protected.add(str(subj))
    parents_with_sat: set[str] = set()
    for subj, obj in graph.subject_objects(KAIROS_EXT.gdprSatelliteOf):
        parents_with_sat.add(str(obj))

    for cls_info in domain_classes:
        cls_uri_str = cls_info["uri"]
        if cls_uri_str in protected or cls_uri_str in parents_with_sat:
            continue
        cls_uri = URIRef(cls_uri_str)
        for prop in graph.subjects(RDFS.domain, cls_uri):
            if (prop, RDF.type, OWL.DatatypeProperty) not in graph:
                continue
            local = _local_name(str(prop))
            snake = _camel_to_snake(local)
            for kw in _PII_KEYWORDS:
                if kw in snake:
                    logger.warning(
                        "GDPR: %s.%s matches PII keyword '%s' but class has no "
                        "gdprSatelliteOf annotation",
                        cls_info["name"], local, kw,
                    )
                    break


def _warn_unclaimed_parents(
    graph: Graph,
    domain_classes: list[dict],
) -> list[str]:
    """Emit an informational notice when a class has an unclaimed parent (DD-021).

    Properties from unclaimed parents are still inherited automatically via
    ``_get_class_and_ancestors()`` — this notice is informational only.  It alerts
    users that a parent exists outside the projected set so they can decide whether
    the parent warrants its own table (via ``silverInclude``).

    Returns a list of info messages (also logged) for inclusion in reports.
    """
    class_uris = {c["uri"] for c in domain_classes}
    notices: list[str] = []
    for cls_info in domain_classes:
        cls_uri = URIRef(cls_info["uri"])
        for parent in graph.objects(cls_uri, RDFS.subClassOf):
            if not isinstance(parent, URIRef):
                continue
            parent_str = str(parent)
            # Skip W3C base classes (owl:Thing, etc.)
            if parent_str.startswith("http://www.w3.org/"):
                continue
            if parent_str not in class_uris:
                parent_local = _local_name(parent_str)
                msg = (
                    f"DD-021 info: {cls_info['name']} extends {parent_local} "
                    f"which is not claimed for projection. Properties from "
                    f"{parent_local} are inherited automatically into the "
                    f"child table. To project {parent_local} as its own "
                    f"table, add kairos-ext:silverInclude true to "
                    f"<{parent_str}>."
                )
                logger.info(msg)
                notices.append(msg)
    return notices


def _warn_silver_exclude_dependents(
    graph: Graph,
    excluded_uris: set[str],
    class_uris: set[str],
) -> list[str]:
    """Warn when a ``silverExclude``d class is depended on by materialised classes.

    An excluded class produces no table and is treated like an unclaimed /
    cross-domain FK target. That is usually intentional, but it can silently drop
    a discriminator fold target or an FK/junction target that retained classes
    rely on. This surfaces those cases (A — issue #172).

    Returns a list of warning messages (also logged).
    """
    warnings: list[str] = []
    for excl in sorted(excluded_uris):
        excl_uri = URIRef(excl)
        excl_local = _local_name(excl)
        # A retained class subclasses the excluded class (fold/inheritance target)
        subclassed_by = [
            str(s) for s in graph.subjects(RDFS.subClassOf, excl_uri)
            if str(s) in class_uris
        ]
        # A retained class FKs/junctions to the excluded class (object property range)
        referenced_by = sorted({
            str(graph.value(prop, RDFS.domain))
            for prop in graph.subjects(RDFS.range, excl_uri)
            if (prop, RDF.type, OWL.ObjectProperty) in graph
            and str(graph.value(prop, RDFS.domain)) in class_uris
        })
        if subclassed_by or referenced_by:
            deps = sorted({_local_name(u) for u in subclassed_by + referenced_by})
            msg = (
                f"silverExclude: {excl_local} is excluded from projection but is "
                f"referenced by materialised class(es) {', '.join(deps)}. Their "
                f"inherited columns / FK targets may be affected. {excl_local} is "
                f"treated as an unclaimed (cross-domain) target."
            )
            logger.warning(msg)
            warnings.append(msg)
    return warnings


def _warn_incomplete_fk_annotations(
    fk_classification: ForeignKeyClassification,
) -> list[str]:
    """Warn when silverForeignKey is set but rdfs:domain or rdfs:range is missing.

    Without ``rdfs:domain`` the projector cannot determine which table receives
    the FK column. Without ``rdfs:range`` it cannot resolve the target table.
    Properties in this state are silently skipped during projection — this
    warning surfaces the issue early.

    Returns a list of warning messages (also logged).
    """
    warnings = [
        diagnostic.message
        for diagnostic in fk_classification.diagnostics
        if diagnostic.kind == "incomplete_silver_foreign_key"
    ]
    for msg in warnings:
        logger.warning(msg)
    return warnings

class ColumnDef:
    def __init__(self, name: str, sql_type: str, nullable: bool = True,
                 comment: str = ""):
        self.name = name
        self.sql_type = sql_type
        self.nullable = nullable
        self.comment = comment

    def ddl_fragment(self) -> str:
        null_clause = "NULL" if self.nullable else "NOT NULL"
        comment_clause = f"  -- {self.comment}" if self.comment else ""
        return f"    {self.name:<35} {self.sql_type} {null_clause}{comment_clause}"


class TableDef:
    def __init__(self, name: str, schema: str):
        self.name = name
        self.schema = schema
        self.full_name = f"{schema}.{name}"
        self.columns: list[ColumnDef] = []
        self.pk_column: Optional[str] = None
        self.unique_columns: list[str] = []
        # (col, ref_table, ref_col, label) — label used in ERD relationships
        self.fk_constraints: list[tuple[str, str, str, str]] = []
        self.partition_by: Optional[str] = None
        self.cluster_by: Optional[str] = None
        self.is_reference = False
        self.table_type: str = "root"  # root | subtype | satellite | reference

    def render_create(self) -> str:
        """Render CREATE TABLE with constraints as comments (S2)."""
        lines = [f"CREATE TABLE {self.full_name} ("]
        col_lines = [c.ddl_fragment() for c in self.columns]
        lines.append(",\n".join(col_lines))
        lines.append(")")
        # Partitioning / clustering
        if self.partition_by:
            lines.append(f"PARTITIONED BY ({self.partition_by})")
        if self.cluster_by:
            lines.append(f"CLUSTER BY ({self.cluster_by})")
        result = "\n".join(lines) + ";"
        # S2: PK/FK/UNIQUE as comments (Fabric Warehouse cannot enforce constraints)
        constraint_comments = []
        if self.pk_column:
            constraint_comments.append(f"-- PK: {self.pk_column}")
        for col in self.unique_columns:
            constraint_comments.append(f"-- UNIQUE: {col}")
        for col, ref_table, ref_col, *_label in self.fk_constraints:
            constraint_comments.append(f"-- FK: {col} -> {ref_table} ({ref_col})")
        if constraint_comments:
            result += "\n" + "\n".join(constraint_comments)
        return result

    def render_alter(self) -> list[str]:
        """Render constraints as documentation-only comments (S2)."""
        stmts = []
        for col in self.unique_columns:
            stmts.append(
                f"-- ALTER TABLE {self.full_name}\n"
                f"--     ADD CONSTRAINT u_{self.name}_{col} UNIQUE ({col});"
            )
        seen_constraints: set[str] = set()
        for col, ref_table, ref_col, *_label in self.fk_constraints:
            constraint_name = f"fk_{self.name}_{col}"
            if constraint_name in seen_constraints:
                continue
            seen_constraints.add(constraint_name)
            stmts.append(
                f"-- ALTER TABLE {self.full_name}\n"
                f"--     ADD CONSTRAINT {constraint_name}"
                f" FOREIGN KEY ({col}) REFERENCES {ref_table} ({ref_col});"
            )
        return stmts


# ---------------------------------------------------------------------------
# Main projector function
# ---------------------------------------------------------------------------

def generate_silver_artifacts(
    classes: list[dict],
    graph: Graph,
    namespace: str,
    shapes_dir: Optional[Path] = None,
    ontology_name: str = "domain",
    projection_ext_path: Optional[Path] = None,
    ontology_metadata: Optional[dict] = None,
    ref_model_defaults: Optional[list] = None,
) -> dict[str, str]:
    """Generate silver layer DDL, ALTER script, and Mermaid ERD.

    Args:
        classes: Pre-extracted list of ``{uri, name, label, comment}`` dicts.
        graph: Loaded domain ontology graph.
        namespace: Domain namespace URI string.
        shapes_dir: Optional SHACL shapes directory (for NOT NULL inference, R11).
        ontology_name: Domain name (used for filenames and default schema).
        projection_ext_path: Optional path to ``*-silver-ext.ttl`` annotation file.
        ontology_metadata: Provenance metadata from ``extract_ontology_metadata()``.
        ref_model_defaults: Optional list of Paths to reference model default
            extension files (DD-023). Loaded as fallback beneath domain extension.

    Returns:
        ``{filename: content}`` mapping for DDL, ALTER, and .mmd files.
    """
    # Merge projection extension into working graph (R15) with fallback defaults (DD-023)
    merged = merge_ext_graph(graph, projection_ext_path, fallback_paths=ref_model_defaults)

    # Merge SHACL shapes for NOT NULL inference (R11)
    shacl_graph: Optional[Graph] = None
    if shapes_dir and shapes_dir.exists():
        shacl_graph = Graph()
        for shacl_file in shapes_dir.glob("*.ttl"):
            shacl_graph.parse(str(shacl_file), format="turtle")

    # Read ontology-level annotations
    onto_uri = _detect_ontology_uri(merged, namespace)
    schema_name = silver_schema_name(merged, onto_uri, ontology_name)
    naming_conv = silver_naming_convention(merged, onto_uri)
    include_iri = _bool_val(merged, onto_uri, KAIROS_EXT.includeNaturalKeyColumn, True)
    audit_str = _str_val(merged, onto_uri, KAIROS_EXT.auditEnvelope, _DEFAULT_AUDIT)
    audit_cols = _parse_audit_envelope(audit_str)

    def table_name_for(cls_uri: URIRef, local: str) -> str:
        return silver_table_name(merged, cls_uri, local, naming_conv)

    # Build class map: uri → TableDef
    tables: dict[str, TableDef] = {}
    # IMP-1 / BUG-3 + DD-021: Accept all classes passed by the caller.
    # The caller (_run_projection) already applies namespace filtering for local
    # classes AND import whitelisting for claimed imported classes (DD-021).
    # Imported classes claimed via kairos-ext:silverInclude are materialized in
    # this domain's schema; unclaimed imports are excluded upstream.
    domain_classes = list(classes)
    # A — kairos-ext:silverExclude (mirror gold's goldExclude): drop classes that
    # should not materialise as their own table. Exclude OVERRIDES silverInclude /
    # silverIncludeImports (this filter runs after upstream include selection).
    # An excluded class still contributes inherited properties to descendants (the
    # `merged` graph is read by URI), and is treated as an unclaimed / cross-domain
    # FK target by the FK logic below.
    excluded_uris = {
        c["uri"] for c in domain_classes
        if _bool_val(merged, URIRef(c["uri"]), KAIROS_EXT.silverExclude, False)
    }
    if excluded_uris:
        domain_classes = [c for c in domain_classes if c["uri"] not in excluded_uris]
    class_uris = {c["uri"] for c in domain_classes}
    if excluded_uris:
        _warn_silver_exclude_dependents(merged, excluded_uris, class_uris)

    # Normalize OWL + authored Silver FK annotations once for every downstream pass.
    fk_classification = classify_foreign_keys(merged)

    # GDPR PII warning: scan for PII-like properties on unprotected classes
    _warn_unprotected_pii(merged, domain_classes, namespace)

    # DD-021: Warn about claimed classes with unclaimed parents
    _warn_unclaimed_parents(merged, domain_classes)

    # Warn about silverForeignKey annotations missing domain/range
    _warn_incomplete_fk_annotations(fk_classification)

    # S3: Track subtypes to flatten into parent tables (discriminator strategy only)
    folded_subtypes: dict[str, list[str]] = {}  # parent_uri → [subtype URIs]
    # Map of subtype_uri → parent_uri for property merging (discriminator only)
    subtype_parents: dict[str, str] = {}
    # TPC parents: parents that use table-per-concrete-class (children inherit props)
    tpc_parents: set[str] = set()

    # Pre-scan: identify subtype relationships and classify inheritance strategy.
    # B (issue #172): folding is TRANSITIVE — a subtype reaching a claimed
    # discriminator ancestor only through *unclaimed* intermediates still folds.
    for cls_info in domain_classes:
        cls_uri = URIRef(cls_info["uri"])
        gdpr_parent = merged.value(cls_uri, KAIROS_EXT.gdprSatelliteOf)
        if gdpr_parent is not None:
            continue  # GDPR satellites are never flattened
        ancestor = _nearest_claimed_ancestor(merged, cls_uri, class_uris)
        if ancestor is None:
            continue
        parent_strategy = _str_val(merged, ancestor, KAIROS_EXT.inheritanceStrategy)
        if parent_strategy == "discriminator":
            # S3: flatten into the (possibly transitive) discriminator ancestor
            subtype_parents[cls_info["uri"]] = str(ancestor)
            existing = folded_subtypes.setdefault(str(ancestor), [])
            if cls_info["uri"] not in existing:
                existing.append(cls_info["uri"])
        else:
            # TPC: child gets its own table, inheriting parent properties
            tpc_parents.add(str(ancestor))

    for cls_info in domain_classes:
        cls_uri = URIRef(cls_info["uri"])
        local = cls_info["name"]
        tbl_name = table_name_for(cls_uri, local)

        # Detect table type flags
        is_ref = _bool_val(merged, cls_uri, KAIROS_EXT.isReferenceData, False)
        gdpr_parent = merged.value(cls_uri, KAIROS_EXT.gdprSatelliteOf)
        is_gdpr = gdpr_parent is not None
        scd = _str_val(merged, cls_uri, KAIROS_EXT.scdType, "1" if is_ref else "2")

        tbl = TableDef(tbl_name, schema_name)
        tbl.is_reference = is_ref
        tbl.partition_by = _str_val(merged, cls_uri, KAIROS_EXT.partitionBy) or None
        tbl.cluster_by = _str_val(merged, cls_uri, KAIROS_EXT.clusterBy) or None

        # ----------------------------------------------------------------
        # Determine inheritance: is this a discriminator subtype?
        # ----------------------------------------------------------------
        supertype_uri = None
        if cls_info["uri"] in subtype_parents:
            supertype_uri = URIRef(subtype_parents[cls_info["uri"]])
        is_disc_subtype = supertype_uri is not None

        # ----------------------------------------------------------------
        # S3 — Flatten discriminator subtypes into parent table (except GDPR)
        # Only when parent declares inheritanceStrategy "discriminator".
        # TPC subtypes (default) generate their own table below.
        # ----------------------------------------------------------------
        if is_disc_subtype and not is_gdpr:
            continue  # skip table generation — properties merged in post-pass

        # ----------------------------------------------------------------
        # Column ordering: SK → IRI → FK → discriminator → data → SCD → audit
        # ----------------------------------------------------------------

        # 1. Surrogate key (R2)
        if not is_gdpr:
            sk_col = ColumnDef(f"{tbl_name}_sk", "STRING", nullable=False,
                               comment="Surrogate key (UUID)")
            tbl.columns.append(sk_col)
            tbl.pk_column = f"{tbl_name}_sk"
        else:
            # GDPR satellite: PK = FK to parent (R7)
            parent_local = _local_name(str(gdpr_parent))
            parent_tbl = table_name_for(gdpr_parent, parent_local)
            sk_col = ColumnDef(f"{parent_tbl}_sk", "STRING", nullable=False,
                               comment=f"PK/FK → {parent_tbl} (GDPR satellite)")
            tbl.columns.append(sk_col)
            tbl.pk_column = f"{parent_tbl}_sk"
            tbl.fk_constraints.append(
                (f"{parent_tbl}_sk", f"{schema_name}.{parent_tbl}",
                 f"{parent_tbl}_sk", "gdpr_satellite_of")
            )
            tbl.table_type = "satellite"

        # 2. IRI lineage column (R3, S7) — skip for ref and GDPR satellites
        if include_iri and not is_gdpr and not is_ref:
            iri_col = ColumnDef(f"{tbl_name}_iri", "STRING", nullable=False,
                                comment="OWL IRI lineage")
            tbl.columns.append(iri_col)
            tbl.unique_columns.append(f"{tbl_name}_iri")

        # 3. FK columns from max-cardinality-1 object properties (R12)
        # TPC subtypes inherit parent's FK columns via inherit_from
        _add_object_property_fk_cols(
            merged, fk_classification, cls_uri, tbl, table_name_for, schema_name,
            class_uris, naming_conv, subtype_parents=subtype_parents,
            inherit_ancestors=True,
            inherit_from=tpc_parents if tpc_parents else None,
        )

        # 4. Discriminator column (R6 + S3 — auto-add if class has subtypes)
        disc_col = _str_val(merged, cls_uri, KAIROS_EXT.discriminatorColumn)
        if not disc_col and cls_info["uri"] in folded_subtypes:
            # S3: auto-generate discriminator for parent with flattened subtypes
            disc_col = f"{tbl_name}_type"
        if disc_col:
            tbl.columns.append(ColumnDef(disc_col, "STRING", nullable=False,
                                         comment="Type discriminator"))

        # 5. Data properties (business columns)
        # TPC subtypes inherit parent properties via inherit_from
        _add_data_properties(merged, cls_uri, tbl, shacl_graph, naming_conv,
                             class_uris=class_uris,
                             inherit_from=tpc_parents if tpc_parents else None)

        # 6. SCD Type 2 columns (R5)
        if scd == "2":
            tbl.columns.append(ColumnDef("valid_from", "DATE", nullable=False))
            tbl.columns.append(ColumnDef("valid_to", "DATE", nullable=True,
                                         comment="NULL = current record"))
            tbl.columns.append(ColumnDef("is_current", "BOOLEAN", nullable=False,
                                         comment="DEFAULT 1"))

        # 7. Audit envelope (R9) — skip for reference tables
        if not is_ref:
            tbl.columns.extend(audit_cols)
            # S5: _row_hash for incremental MERGE (always added, not customizable)
            tbl.columns.append(ColumnDef("_row_hash", "BINARY", nullable=True,
                                         comment="S5: SHA-256 hash for incremental MERGE"))
            # S6: _deleted_at for soft-delete tracking (always added, not customizable)
            tbl.columns.append(ColumnDef("_deleted_at", "TIMESTAMP", nullable=True,
                                         comment="S6: soft-delete timestamp"))

        if is_ref:
            tbl.table_type = "reference"

        tables[cls_info["uri"]] = tbl

    # ----------------------------------------------------------------
    # S3 post-pass: merge subtype properties into parent tables
    # ----------------------------------------------------------------
    # folded_subtypes maps parent_uri → [subtype URIs] (URI-keyed for namespace
    # safety). For each folded subtype we merge its OWN properties plus those of
    # any *unclaimed* intermediate ancestors up to (but excluding) the claimed
    # fold target — class_uris makes _get_class_and_ancestors stop at claimed
    # ancestors, so the parent's own columns are not duplicated.
    name_by_uri = {c["uri"]: c["name"] for c in domain_classes}
    for parent_uri_str, subtype_uris in folded_subtypes.items():
        if parent_uri_str not in tables:
            continue
        parent_tbl = tables[parent_uri_str]
        for sub_uri_str in subtype_uris:
            sub_uri = URIRef(sub_uri_str)
            sub_name = name_by_uri.get(sub_uri_str, _local_name(sub_uri_str))
            # Merge data properties (incl. unclaimed-intermediate ancestors) as
            # nullable columns with a subtype comment.
            _add_data_properties(
                merged, sub_uri, parent_tbl, shacl_graph, naming_conv,
                comment_prefix=f"from {sub_name}",
                class_uris=class_uris,
            )
            # Merge object property FK columns (incl. unclaimed-intermediate ancestors)
            _add_object_property_fk_cols(
                merged, fk_classification, sub_uri, parent_tbl, table_name_for, schema_name,
                class_uris, naming_conv,
                subtype_parents=subtype_parents,
                inherit_ancestors=True,
                comment_prefix=f"from {sub_name}"
            )

    # ----------------------------------------------------------------
    # DD-022 post-pass: inject redirected FK columns (silverForeignKeyOn)
    # ----------------------------------------------------------------
    _add_redirected_fk_cols(
        merged, fk_classification, tables, table_name_for, schema_name,
        class_uris, naming_conv, subtype_parents,
    )

    # ----------------------------------------------------------------
    # S4 post-pass: inline small reference tables into parent
    # ----------------------------------------------------------------
    inline_threshold = 3  # default: inline ref tables with ≤3 business columns
    onto_threshold = merged.value(onto_uri, KAIROS_EXT.inlineRefThreshold)
    if onto_threshold is not None:
        try:
            inline_threshold = int(str(onto_threshold))
        except ValueError:
            logger.warning("Invalid inlineRefThreshold value '%s' — using default %d",
                           onto_threshold, inline_threshold)
    _inline_small_ref_tables(tables, inline_threshold)

    # ----------------------------------------------------------------
    # Junction tables from many-to-many object properties (R13)
    # ----------------------------------------------------------------
    junction_tables = _build_junction_tables(merged, class_uris, tables, schema_name,
                                             table_name_for, audit_cols, naming_conv)

    # ----------------------------------------------------------------
    # Sort tables per ordering convention
    # ----------------------------------------------------------------
    all_tables = _sort_tables(list(tables.values()) + junction_tables)

    # ----------------------------------------------------------------
    # Build provenance header lines (reused across DDL, ALTER, ERD)
    # ----------------------------------------------------------------
    meta = ontology_metadata or {}
    prov_sql = [
        f"-- Silver layer DDL: {schema_name}",
        f"-- Domain: {ontology_name}",
    ]
    if meta.get("iri"):
        prov_sql.append(f"-- Ontology IRI: {meta['iri']}")
    if meta.get("version"):
        prov_sql.append(f"-- Ontology version: {meta['version']}")
    if meta.get("toolkit_version"):
        prov_sql.append(f"-- Toolkit version: {meta['toolkit_version']}")
    if meta.get("generated_at"):
        prov_sql.append(f"-- Generated at: {meta['generated_at']}")

    # ----------------------------------------------------------------
    # Render DDL
    # ----------------------------------------------------------------
    ddl_lines = prov_sql + [
        "",
        "-- Schema",
        f"CREATE SCHEMA IF NOT EXISTS {schema_name};",
        "",
    ]
    for tbl in all_tables:
        ddl_lines.append(f"-- {tbl.table_type.upper()}: {tbl.full_name}")
        # R16: note folded subtypes on parent tables
        parent_uri_candidates = [
            uri for uri, t in tables.items() if t is tbl
        ]
        for puri in parent_uri_candidates:
            if puri in folded_subtypes:
                names = ", ".join(folded_subtypes[puri])
                ddl_lines.append(
                    f"-- S3: subtypes flattened into this table: {names}"
                )
        ddl_lines.append(tbl.render_create())
        ddl_lines.append("")

    # ----------------------------------------------------------------
    # Render ALTER TABLE script
    # ----------------------------------------------------------------
    alter_lines = [
        f"-- Silver layer constraints (documentation only — S2): {schema_name}",
        "-- Fabric Warehouse cannot enforce PK/FK/UNIQUE constraints.",
        "-- These are provided as reference for data engineers.",
        f"-- Domain: {ontology_name}",
    ]
    if meta.get("iri"):
        alter_lines.append(f"-- Ontology IRI: {meta['iri']}")
    if meta.get("version"):
        alter_lines.append(f"-- Ontology version: {meta['version']}")
    alter_lines.append("")
    for tbl in all_tables:
        stmts = tbl.render_alter()
        if stmts:
            alter_lines.append(f"-- {tbl.full_name}")
            alter_lines.extend(stmts)
            alter_lines.append("")

    # ----------------------------------------------------------------
    # Render Mermaid ERD
    # ----------------------------------------------------------------
    mmd_lines = [
        "erDiagram",
        f'    %% Silver ERD: {schema_name} / {ontology_name}',
    ]
    if meta.get("iri"):
        mmd_lines.append(f"    %% Ontology IRI: {meta['iri']}")
    if meta.get("version"):
        mmd_lines.append(f"    %% Ontology version: {meta['version']}")
    if meta.get("toolkit_version"):
        mmd_lines.append(f"    %% Toolkit version: {meta['toolkit_version']}")
    mmd_lines.append("")
    for tbl in all_tables:
        mmd_lines.append(f"    {tbl.name.upper()} {{")
        for col in tbl.columns:
            mmd_lines.append(f"        {_mmd_type(col.sql_type)} {col.name}")
        mmd_lines.append("    }")
        mmd_lines.append("")
    # FK relationships in ERD
    for tbl in all_tables:
        for col, ref_full, ref_col, label in tbl.fk_constraints:
            ref_tbl_name = ref_full.split(".")[-1].upper()
            mmd_lines.append(
                f"    {ref_tbl_name} ||--o{{ {tbl.name.upper()} : \"{label}\""
            )

    # DDL/ALTER → analyses/{domain}/ (dbt non-DAG reference SQL)
    # ERD → docs/diagrams/{domain}/ (dbt supplemental docs)
    return {
        f"analyses/{ontology_name}/{ontology_name}-ddl.sql": "\n".join(ddl_lines),
        f"analyses/{ontology_name}/{ontology_name}-alter.sql": "\n".join(alter_lines),
        f"docs/diagrams/{ontology_name}/{ontology_name}-erd.mmd": "\n".join(mmd_lines),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_external_table(
    graph: Graph, range_cls: URIRef, naming_conv: str,
) -> tuple[str, str]:
    """Derive ``(schema, table_name)`` for a class outside the current domain.

    Resolution order:

    1. ``kairos-ext:silverTableName`` on the class → table name.
    2. ``kairos-ext:silverSchema`` on the class's ontology → schema.
    3. Fallback: ``silver_{domain}`` derived from the class namespace, and
       ``snake_case(local_name)`` for the table.
    """
    # Table name: explicit annotation or derive from local name
    tbl_override = _str_val(graph, range_cls, KAIROS_EXT.silverTableName)
    local = _local_name(str(range_cls))
    tbl_name = tbl_override or (
        _camel_to_snake(local) if naming_conv == "camel-to-snake" else local.lower()
    )

    # Reference data → prefix with ref_ (mirrors table_name_for logic)
    is_ref = _bool_val(graph, range_cls, KAIROS_EXT.isReferenceData, False)
    if is_ref and not tbl_name.startswith("ref_"):
        tbl_name = f"ref_{tbl_name}"

    # Schema: look for the ontology that owns this class
    cls_str = str(range_cls)
    if "#" in cls_str:
        ext_ns = cls_str.rsplit("#", 1)[0]
    elif "/" in cls_str:
        ext_ns = cls_str.rsplit("/", 1)[0]
    else:
        ext_ns = cls_str

    # Try to find silverSchema on the external ontology URI
    schema = None
    for candidate in (URIRef(ext_ns), URIRef(ext_ns + "#"), URIRef(ext_ns + "/")):
        val = _str_val(graph, candidate, KAIROS_EXT.silverSchema)
        if val:
            schema = val
            break

    if not schema:
        # Derive from namespace: last path segment as domain name
        domain_part = ext_ns.rstrip("/").rsplit("/", 1)[-1]
        schema = f"silver_{domain_part}"

    return schema, tbl_name


def _s4_inlined_name(ref_prefix: str, col_name: str) -> str:
    """Build a short inlined column name avoiding redundant prefix segments.

    Examples:
      ("gender", "gender_code")                     → "gender_code"
      ("shareholder_property_right", "property_right_name_en")
                                                     → "shareholder_property_right_name_en"
      ("professional_role", "role_code")             → "professional_role_code"
      ("acceptance_status", "acceptance_status_name")→ "acceptance_status_name"
    """
    # If the column already starts with the full prefix, use as-is
    if col_name.startswith(f"{ref_prefix}_"):
        return col_name

    # Find the longest suffix of ref_prefix segments that matches a prefix of col_name
    prefix_parts = ref_prefix.split("_")
    for i in range(len(prefix_parts)):
        suffix = "_".join(prefix_parts[i:])
        if col_name.startswith(f"{suffix}_") or col_name == suffix:
            # Keep only the prefix segments NOT in the overlap
            unique_prefix = "_".join(prefix_parts[:i]) if i > 0 else ref_prefix
            return f"{unique_prefix}_{col_name}" if unique_prefix else col_name

    # No overlap — use full prefix
    return f"{ref_prefix}_{col_name}"


def _inline_small_ref_tables(
    tables: dict[str, TableDef],
    threshold: int = 3,
) -> None:
    """S4: Inline small reference tables (≤threshold business columns) into parents.

    For each FK relationship pointing to a reference table with few business columns,
    replace the FK column with the ref table's business columns (denormalized).
    The reference table is then removed from the output.
    """
    # Identify small ref tables (count business columns = non-PK, non-audit, non-SCD)
    audit_prefixes = ("_created_at", "_updated_at", "_source_system", "_load_date",
                      "_batch_id", "_row_hash", "_deleted_at")
    scd_names = ("valid_from", "valid_to", "is_current")

    small_refs: dict[str, list[ColumnDef]] = {}  # full_name → business columns
    for uri, tbl in tables.items():
        if not tbl.is_reference:
            continue
        biz_cols = [
            c for c in tbl.columns
            if c.name != tbl.pk_column
            and c.name not in audit_prefixes
            and c.name not in scd_names
            and not c.name.endswith("_iri")
        ]
        if len(biz_cols) <= threshold:
            small_refs[tbl.full_name] = biz_cols

    if not small_refs:
        return

    # Inline into parent tables
    refs_to_remove: set[str] = set()
    for uri, tbl in tables.items():
        if tbl.is_reference:
            continue
        new_fk_constraints = []
        for fk_col, ref_table, ref_col, *label in tbl.fk_constraints:
            if ref_table in small_refs:
                # Remove the FK column
                tbl.columns = [c for c in tbl.columns if c.name != fk_col]
                # Inline the ref table's business columns
                ref_prefix = ref_table.split(".")[-1].replace("ref_", "")
                existing = {c.name for c in tbl.columns}
                for biz_col in small_refs[ref_table]:
                    inlined_name = _s4_inlined_name(ref_prefix, biz_col.name)
                    if inlined_name in existing:
                        continue
                    existing.add(inlined_name)
                    tbl.columns.insert(
                        _find_insert_pos(tbl, fk_col),
                        ColumnDef(
                            inlined_name, biz_col.sql_type, nullable=True,
                            comment=f"S4: inlined from {ref_table}"
                        )
                    )
                refs_to_remove.add(ref_table)
            else:
                new_fk_constraints.append((fk_col, ref_table, ref_col, *label))
        tbl.fk_constraints = new_fk_constraints

    # Remove inlined ref tables from output
    to_delete = [uri for uri, tbl in tables.items() if tbl.full_name in refs_to_remove]
    for uri in to_delete:
        del tables[uri]


def _find_insert_pos(tbl: TableDef, after_col: str) -> int:
    """Find the position after the given column name, or end of columns."""
    for i, c in enumerate(tbl.columns):
        if c.name == after_col:
            return i + 1
    return len(tbl.columns)


def _parse_audit_envelope(audit_str: str) -> list[ColumnDef]:
    """Parse comma-separated ``name TYPE`` audit column definitions.

    Commas inside parentheses (e.g. ``DECIMAL(18, 4)``) are preserved.
    """
    cols = []
    for part in re.split(r",\s*(?![^()]*\))", audit_str):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) >= 2:
            cols.append(ColumnDef(tokens[0], " ".join(tokens[1:]), nullable=True))
    return cols


def _not_null_from_shacl(shacl_graph: Optional[Graph], prop_uri: URIRef,
                          cls_uri: URIRef) -> bool:
    """Return True if SHACL shape has sh:minCount 1 for this property on this class (R11)."""
    if shacl_graph is None:
        return False
    SH = Namespace("http://www.w3.org/ns/shacl#")
    for shape in shacl_graph.subjects(SH.targetClass, cls_uri):
        for prop_shape in shacl_graph.objects(shape, SH.property):
            path = shacl_graph.value(prop_shape, SH.path)
            if path == prop_uri:
                min_count = shacl_graph.value(prop_shape, SH.minCount)
                if min_count is not None:
                    try:
                        if int(str(min_count)) >= 1:
                            return True
                    except ValueError:
                        pass
    return False


def _add_data_properties(graph: Graph, cls_uri: URIRef, tbl: TableDef,
                          shacl_graph: Optional[Graph], naming_conv: str,
                          comment_prefix: str = "",
                          class_uris: set[str] | None = None,
                          inherit_from: set[str] | None = None) -> None:
    """Add OWL DatatypeProperty columns to the table (business columns, R4, R11).

    Args:
        comment_prefix: If set (S3 flattening), prepended to column comment and
            forces nullable=True (subtype columns are always nullable on parent).
        class_uris: If provided, enables inheritance traversal — properties from
            unprojected ancestor classes are included.
        inherit_from: If provided (TPC parents), properties from these ancestors
            are included even though they are separately projected.
    """
    # Determine which domains to match (inheritance traversal)
    if class_uris is not None:
        domains_to_match = _get_class_and_ancestors(graph, cls_uri, class_uris,
                                                    inherit_from=inherit_from)
    else:
        domains_to_match = {cls_uri}

    existing_col_names = {c.name for c in tbl.columns}
    for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
        domain = graph.value(prop, RDFS.domain)
        if domain not in domains_to_match:
            continue
        range_uri = graph.value(prop, RDFS.range)
        sql_type = XSD_TO_SQL.get(str(range_uri), "STRING") if range_uri else "STRING"
        # Override from annotation
        override_type = _str_val(graph, prop, KAIROS_EXT.silverDataType)
        if override_type:
            sql_type = override_type
        # Column name
        prop_local = _local_name(str(prop))
        col_name_override = _str_val(graph, prop, KAIROS_EXT.silverColumnName)
        col_name = col_name_override or (
            _camel_to_snake(prop_local) if naming_conv == "camel-to-snake" else prop_local.lower()
        )
        # Skip if a column with the same name already exists (e.g. discriminator)
        if col_name in existing_col_names:
            logger.debug(
                "S3 flattening: skipping duplicate column '%s' from %s",
                col_name, _local_name(str(cls_uri)),
            )
            continue
        existing_col_names.add(col_name)
        # Nullability: S3 subtype columns are always nullable on parent
        if comment_prefix:
            nullable = True
        else:
            nullable_ann = graph.value(prop, KAIROS_EXT.nullable)
            if nullable_ann is not None:
                nullable = str(nullable_ann).lower() not in ("false", "0")
            else:
                nullable = not _not_null_from_shacl(shacl_graph, prop, cls_uri)
        prop_iri = _prefixed_iri(str(prop))
        comment = f"{comment_prefix}; {prop_iri}" if comment_prefix else prop_iri
        tbl.columns.append(ColumnDef(col_name, sql_type, nullable=nullable, comment=comment))


def _add_object_property_fk_cols(
    graph: Graph, fk_classification: ForeignKeyClassification,
    cls_uri: URIRef, tbl: TableDef,
    table_name_for, schema_name: str, class_uris: set[str], naming_conv: str,
    subtype_parents: dict[str, str] | None = None,
    comment_prefix: str = "",
    inherit_ancestors: bool = False,
    inherit_from: set[str] | None = None,
) -> None:
    """Add FK columns from max-cardinality-1 object properties (R12).

    A property qualifies as a FK column when ANY of:
      - it has an explicit ``kairos-ext:silverColumnName`` annotation,
      - it is declared ``owl:FunctionalProperty``,
      - the domain class has an ``owl:maxQualifiedCardinality 1`` or
        ``owl:maxCardinality 1`` restriction on the property,
      - it has ``kairos-ext:silverForeignKey true`` (DD-022).

    Properties with ``kairos-ext:silverForeignKeyOn`` are skipped here and
    handled by :func:`_add_redirected_fk_cols` after the main pass.

    Junction-table properties (R13) are always skipped.

    Handles duplicate column names (e.g. two self-referential FKs to the same
    range class) by appending the property name as a disambiguator.

    Args:
        comment_prefix: If set (S3 flattening), appended to FK comment and
            forces nullable=True (subtype FK columns are always nullable on parent).
        inherit_ancestors: If True, include object properties from unprojected
            ancestor classes (inheritance traversal).
        inherit_from: If provided (TPC parents), properties from these ancestors
            are included even though they are separately projected.
    """
    # Determine which domains to match (inheritance traversal)
    if inherit_ancestors:
        domains_to_match = _get_class_and_ancestors(graph, cls_uri, class_uris,
                                                    inherit_from=inherit_from)
    else:
        domains_to_match = {cls_uri}

    # Track existing column names to avoid duplicates (PK, IRI, discriminator, etc.)
    existing_cols = {col.name for col in tbl.columns}

    for fk in fk_classification.descriptors:
        if fk.redirected or fk.domain_class not in domains_to_match:
            continue
        # Skip if this property has a junctionTableName (R13)
        if fk.junction_table_name:
            continue
        if not fk.is_silver_fk:
            continue
        prop = fk.property_uri
        range_cls = fk.target_class

        # Resolve target table — same domain or cross-domain
        is_cross_domain = str(range_cls) not in class_uris
        if is_cross_domain:
            ref_schema, range_tbl = _resolve_external_table(
                graph, range_cls, naming_conv,
            )
            ref_full = f"{ref_schema}.{range_tbl}"
        else:
            effective_range_cls = _resolve_s3_projected_class(range_cls, subtype_parents)
            range_local = _local_name(str(effective_range_cls))
            range_tbl = table_name_for(effective_range_cls, range_local)
            ref_full = f"{schema_name}.{range_tbl}"

        col_name = fk.physical_column_name(range_tbl, layer="silver")

        # Disambiguate duplicate column names (e.g. two FKs → same target table)
        if col_name in existing_cols:
            prop_suffix = _camel_to_snake(_local_name(str(prop)))
            col_name = f"{prop_suffix}_sk"
            # Final fallback if still duplicate
            if col_name in existing_cols:
                col_name = f"{range_tbl}_{prop_suffix}_sk"

        existing_cols.add(col_name)

        # Nullability: S3 subtype FK columns are always nullable on parent
        if comment_prefix:
            nullable = True
        else:
            if fk.nullable is not None:
                nullable = fk.nullable
            else:
                nullable = True

        # Conditional nullable (R14)
        cond_on = fk.conditional_on_type
        prop_iri = _prefixed_iri(str(prop))
        cross_note = f"cross-domain FK → {ref_full}" if is_cross_domain else ""
        comment_parts = [p for p in [
            prop_iri,
            comment_prefix,
            f"nullable: active when type IN ({cond_on})" if cond_on else "",
            cross_note,
        ] if p]
        comment = "; ".join(comment_parts)
        prop_label = _camel_to_snake(_local_name(str(prop)))
        tbl.columns.append(ColumnDef(col_name, "STRING", nullable=nullable, comment=comment))
        tbl.fk_constraints.append(
            (col_name, ref_full, f"{range_tbl}_sk", prop_label)
        )


def _add_redirected_fk_cols(
    graph: Graph,
    fk_classification: ForeignKeyClassification,
    tables: dict[str, TableDef],
    table_name_for,
    schema_name: str,
    class_uris: set[str],
    naming_conv: str,
    subtype_parents: dict[str, str] | None = None,
) -> None:
    """Inject FK columns for properties with ``silverForeignKeyOn`` (DD-022).

    When ``silverForeignKeyOn`` is set to the **range** class, the FK column is
    placed on the range class's table pointing back to the domain class (reverse
    placement).  When set to the **domain** class, it behaves like a normal FK.

    ``silverForeignKeyOn`` implies ``silverForeignKey true`` — both annotations
    need not be present.

    Called after the main per-class pass and S3 subtype folding so that all
    target tables already exist.
    """
    for diagnostic in fk_classification.diagnostics:
        if diagnostic.kind in {
            "incomplete_silver_foreign_key_on",
            "invalid_silver_foreign_key_on",
        }:
            logger.warning(diagnostic.message)

    for fk in fk_classification.descriptors:
        if not fk.redirected or fk.junction_table_name:
            continue

        prop = fk.property_uri
        prop_local = _local_name(str(prop))
        fk_holder_uri = fk.source_class
        referenced_uri = fk.target_class

        # Find the holder table
        fk_holder_uri_str = str(fk_holder_uri)
        holder_tbl = tables.get(fk_holder_uri_str)
        if holder_tbl is None:
            # Holder may have been folded into a parent (S3)
            logger.warning(
                "silverForeignKeyOn on %s — target table for %s not found "
                "(possibly folded by S3). Skipped.",
                prop_local, _local_name(fk_holder_uri_str),
            )
            continue

        # Resolve referenced table
        ref_uri_str = str(referenced_uri)
        if ref_uri_str in class_uris:
            effective_ref_uri = _resolve_s3_projected_class(referenced_uri, subtype_parents)
            ref_local = _local_name(str(effective_ref_uri))
            ref_tbl = table_name_for(effective_ref_uri, ref_local)
            ref_full = f"{schema_name}.{ref_tbl}"
        else:
            ref_schema, ref_tbl = _resolve_external_table(
                graph, referenced_uri, naming_conv,
            )
            ref_full = f"{ref_schema}.{ref_tbl}"

        # Column name: use silverColumnName override or default to {ref_tbl}_sk
        col_name = fk.physical_column_name(ref_tbl, layer="silver")

        # Disambiguate if column already exists
        existing_cols = {col.name for col in holder_tbl.columns}
        if col_name in existing_cols:
            prop_suffix = _camel_to_snake(prop_local)
            col_name = f"{prop_suffix}_sk"
            if col_name in existing_cols:
                col_name = f"{ref_tbl}_{prop_suffix}_sk"

        # Nullability
        if fk.nullable is not None:
            nullable = fk.nullable
        else:
            nullable = True

        cond_on = fk.conditional_on_type
        direction = "reverse" if fk.reverse else "normal"
        comment_parts = [p for p in [
            f"DD-022 {direction} FK via silverForeignKeyOn",
            f"nullable: active when type IN ({cond_on})" if cond_on else "",
        ] if p]
        comment = "; ".join(comment_parts)

        holder_tbl.columns.append(
            ColumnDef(col_name, "STRING", nullable=nullable, comment=comment)
        )
        holder_tbl.fk_constraints.append(
            (col_name, ref_full, f"{ref_tbl}_sk",
             _camel_to_snake(prop_local))
        )


def _build_junction_tables(
    graph: Graph, class_uris: set[str],
    tables: dict[str, TableDef],
    schema_name: str,
    table_name_for,
    audit_cols: list[ColumnDef],
    naming_conv: str = "camel-to-snake",
) -> list[TableDef]:
    """Build junction (bridge) tables for many-to-many object properties (R13)."""
    junctions: list[TableDef] = []
    seen_junctions: set[str] = set()

    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        jct_name = _str_val(graph, prop, KAIROS_EXT.junctionTableName)
        if not jct_name or jct_name in seen_junctions:
            continue
        seen_junctions.add(jct_name)

        domain_cls = graph.value(prop, RDFS.domain)
        range_cls = graph.value(prop, RDFS.range)
        if domain_cls is None or range_cls is None:
            continue
        # At least one side must be in the current domain
        dom_in_domain = str(domain_cls) in class_uris
        rng_in_domain = str(range_cls) in class_uris
        if not dom_in_domain and not rng_in_domain:
            continue

        # Resolve domain table
        if dom_in_domain:
            dom_local = _local_name(str(domain_cls))
            dom_tbl = table_name_for(domain_cls, dom_local)
            dom_ref = f"{schema_name}.{dom_tbl}"
        else:
            dom_schema, dom_tbl = _resolve_external_table(
                graph, domain_cls, naming_conv)
            dom_ref = f"{dom_schema}.{dom_tbl}"

        # Resolve range table
        if rng_in_domain:
            rng_local = _local_name(str(range_cls))
            rng_tbl = table_name_for(range_cls, rng_local)
            rng_ref = f"{schema_name}.{rng_tbl}"
        else:
            rng_schema, rng_tbl = _resolve_external_table(
                graph, range_cls, naming_conv)
            rng_ref = f"{rng_schema}.{rng_tbl}"

        jct = TableDef(jct_name, schema_name)
        jct.table_type = "satellite"
        # SK
        jct.columns.append(ColumnDef(f"{jct_name}_sk", "STRING", nullable=False,
                                      comment="Surrogate key (UUID)"))
        jct.pk_column = f"{jct_name}_sk"
        prop_label = _camel_to_snake(_local_name(str(prop)))
        # FK to domain
        jct.columns.append(ColumnDef(f"{dom_tbl}_sk", "STRING", nullable=False))
        jct.fk_constraints.append(
            (f"{dom_tbl}_sk", dom_ref, f"{dom_tbl}_sk",
             f"{prop_label}_domain")
        )
        # FK to range
        jct.columns.append(ColumnDef(f"{rng_tbl}_sk", "STRING", nullable=False))
        jct.fk_constraints.append(
            (f"{rng_tbl}_sk", rng_ref, f"{rng_tbl}_sk",
             f"{prop_label}_range")
        )
        # SCD 2
        jct.columns.extend([
            ColumnDef("valid_from", "DATE", nullable=False),
            ColumnDef("valid_to", "DATE", nullable=True, comment="NULL = current"),
            ColumnDef("is_current", "BOOLEAN", nullable=False, comment="DEFAULT 1"),
        ])
        # Audit
        jct.columns.extend(audit_cols)
        junctions.append(jct)

    return junctions


def _sort_tables(tables: list[TableDef]) -> list[TableDef]:
    """Sort tables per ordering convention: root → subtype → satellite → reference."""
    order = {"root": 0, "subtype": 1, "satellite": 2, "reference": 3}
    return sorted(tables, key=lambda t: order.get(t.table_type, 0))


def generate_master_erd(dbt_output_path: Path, hub_name: str = "master") -> Optional[str]:
    """Merge all per-domain ``*-erd.mmd`` files into one cross-domain master ERD.

    Reads every ``docs/diagrams/<domain>/<domain>-erd.mmd`` file under
    *dbt_output_path*, strips the per-file ``erDiagram`` header and domain
    comment, then re-emits them under a single ``erDiagram`` block with a
    section comment per domain.

    Args:
        dbt_output_path: Path to the ``output/medallion/dbt/`` directory.
        hub_name: Label used in the master ERD header comment.

    Returns:
        Mermaid ERD string, or ``None`` if no domain ERDs were found.
    """
    diagrams_dir = dbt_output_path / "docs" / "diagrams"
    if not diagrams_dir.exists():
        return None
    domain_erds: list[tuple[str, str]] = []
    for mmd_file in sorted(diagrams_dir.rglob("*-erd.mmd")):
        if mmd_file.name == "master-erd.mmd":
            continue
        domain = mmd_file.parent.name
        content = mmd_file.read_text(encoding="utf-8")
        # Strip the erDiagram header and leading comment lines
        body_lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "erDiagram" or stripped.startswith("%% Silver ERD:"):
                continue
            body_lines.append(line)
        # Trim leading/trailing blank lines from the body
        body = "\n".join(body_lines).strip()
        if body:
            domain_erds.append((domain, body))

    if not domain_erds:
        return None

    lines = [
        "erDiagram",
        f"    %% Master ERD — {hub_name} (all domains)",
        "",
    ]
    for domain, body in domain_erds:
        lines.append(f"    %% --- Domain: {domain} ---")
        lines.append(body)
        lines.append("")

    return "\n".join(lines)


def render_mermaid_svg(mmd_path: Path) -> Optional[Path]:
    """Render a ``.mmd`` file to SVG using the Mermaid CLI (``mmdc``).

    Looks for ``mmdc`` on ``PATH`` or in ``./node_modules/.bin/``.
    Returns the SVG path on success, or ``None`` if ``mmdc`` is unavailable.
    """
    import shutil
    import subprocess

    # Try local node_modules first, then global PATH
    mmdc = None
    search_dir = mmd_path.parent
    while search_dir != search_dir.parent:
        cmd_candidate = search_dir / "node_modules" / ".bin" / "mmdc.cmd"
        sh_candidate = search_dir / "node_modules" / ".bin" / "mmdc"
        if cmd_candidate.exists():
            mmdc = str(cmd_candidate)
            break
        if sh_candidate.exists():
            mmdc = str(sh_candidate)
            break
        search_dir = search_dir.parent

    if not mmdc:
        mmdc = shutil.which("mmdc")
    if not mmdc:
        return None

    svg_path = mmd_path.with_suffix(".svg")
    try:
        subprocess.run(
            [mmdc, "-i", str(mmd_path), "-o", str(svg_path), "-q"],
            check=True,
            capture_output=True,
            timeout=60,
        )
        return svg_path
    except subprocess.CalledProcessError as exc:
        logger.warning("Mermaid render failed for %s: %s",
                       mmd_path.name, exc.stderr.decode(errors="replace").strip())
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Mermaid render error for %s: %s", mmd_path.name, exc)
        return None
