# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Silver Layer Projector — generate MS Fabric Warehouse silver DDL, FK reference,
and Mermaid ERD from OWL ontologies annotated with kairos-ext: projection extensions.

Common annotation rules R1–R16 define the shared ``kairos-ext:`` vocabulary.
Silver Fabric rules S1–S8 control Warehouse-specific output behaviour:

  S1 — Spark SQL types (BOOLEAN, TIMESTAMP, STRING, DOUBLE)
  S2 — PK/FK/UNIQUE as DDL comments (Fabric can't enforce constraints)
  S3 — Flatten ALL inheritance to single table + discriminator
  S4 — Inline small reference tables (≤3 columns) into parent
  S5 — ``_row_hash`` BINARY column for incremental MERGE
  S6 — ``_deleted_at`` TIMESTAMP soft-delete column
  S7 — Canonical schema ownership (no cross-domain table duplication)
  S8 — No ``dim_``/``fact_`` prefixes (reserved for Gold layer)

Namespace:  kairos-ext:  https://kairos.cnext.eu/ext#
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace, URIRef, Literal, XSD
from rdflib.namespace import OWL, RDF, RDFS

from .uri_utils import camel_to_snake, local_name

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# kairos-ext namespace
# ---------------------------------------------------------------------------
KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")

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


def _mmd_type(sql_type: str) -> str:
    """Sanitize a SQL type for use in a Mermaid erDiagram attribute.

    Mermaid ATTRIBUTE_WORD only allows ``[A-Za-z0-9_]``.
    Examples:
      DECIMAL(18,4)   → DECIMAL_18_4
      STRING          → STRING   (unchanged)
      BOOLEAN         → BOOLEAN  (unchanged)
    """
    return re.sub(r"[^A-Za-z0-9_]", "_", sql_type).strip("_")


def _local_name(uri: str) -> str:
    """Extract local name from a URI."""
    return local_name(uri)


def _str_val(graph: Graph, subject: URIRef, predicate: URIRef, default: str = "") -> str:
    val = graph.value(subject, predicate)
    return str(val) if val is not None else default


def _bool_val(graph: Graph, subject: URIRef, predicate: URIRef, default: bool = False) -> bool:
    val = graph.value(subject, predicate)
    if val is None:
        return default
    return str(val).lower() in ("true", "1", "yes")


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


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

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

    Returns:
        ``{filename: content}`` mapping for DDL, ALTER, and .mmd files.
    """
    # Merge projection extension into working graph (R15)
    merged = Graph()
    for triple in graph:
        merged.add(triple)
    if projection_ext_path and projection_ext_path.exists():
        ext_graph = Graph()
        ext_graph.parse(str(projection_ext_path), format="turtle")
        for triple in ext_graph:
            merged.add(triple)

    # Merge SHACL shapes for NOT NULL inference (R11)
    shacl_graph: Optional[Graph] = None
    if shapes_dir and shapes_dir.exists():
        shacl_graph = Graph()
        for shacl_file in shapes_dir.glob("*.ttl"):
            shacl_graph.parse(str(shacl_file), format="turtle")

    # Read ontology-level annotations
    onto_uri = _detect_ontology_uri(merged, namespace)
    schema_name = _str_val(merged, onto_uri, KAIROS_EXT.silverSchema,
                           f"silver_{ontology_name}")
    naming_conv = _str_val(merged, onto_uri, KAIROS_EXT.namingConvention, "camel-to-snake")
    include_iri = _bool_val(merged, onto_uri, KAIROS_EXT.includeNaturalKeyColumn, True)
    audit_str = _str_val(merged, onto_uri, KAIROS_EXT.auditEnvelope, _DEFAULT_AUDIT)
    audit_cols = _parse_audit_envelope(audit_str)

    def table_name_for(cls_uri: URIRef, local: str) -> str:
        override = _str_val(merged, cls_uri, KAIROS_EXT.silverTableName)
        if override:
            return override
        if naming_conv == "camel-to-snake":
            name = _camel_to_snake(local)
        else:
            name = local.lower()
        # Reference data → prefix with ref_
        is_ref = _bool_val(merged, cls_uri, KAIROS_EXT.isReferenceData, False)
        if is_ref and not name.startswith("ref_"):
            name = f"ref_{name}"
        return name

    # Build class map: uri → TableDef
    tables: dict[str, TableDef] = {}
    # IMP-1 / BUG-3: Filter to domain-owned classes only.
    # Classes whose URI doesn't start with this domain's namespace are imported
    # copies — they should NOT be materialized. Cross-domain FK references are
    # resolved via _resolve_external_table to point at the canonical schema.
    domain_classes = [c for c in classes if c["uri"].startswith(namespace)]
    class_uris = {c["uri"] for c in domain_classes}

    # GDPR PII warning: scan for PII-like properties on unprotected classes
    _warn_unprotected_pii(merged, domain_classes, namespace)

    # S3: Track all subtypes to flatten into parent tables
    folded_subtypes: dict[str, list[str]] = {}  # parent_uri → [subtype names]
    # Map of subtype_uri → parent_uri for property merging
    subtype_parents: dict[str, str] = {}

    # Pre-scan: identify all subtype relationships and build folded_subtypes map
    for cls_info in domain_classes:
        cls_uri = URIRef(cls_info["uri"])
        gdpr_parent = merged.value(cls_uri, KAIROS_EXT.gdprSatelliteOf)
        if gdpr_parent is not None:
            continue  # GDPR satellites are never flattened
        for parent in merged.objects(cls_uri, RDFS.subClassOf):
            if isinstance(parent, URIRef) and str(parent) in class_uris:
                subtype_parents[cls_info["uri"]] = str(parent)
                # BUG-2 fix: use set-like append to avoid duplicates from import paths
                existing = folded_subtypes.setdefault(str(parent), [])
                if cls_info["name"] not in existing:
                    existing.append(cls_info["name"])
                break

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
        # Determine inheritance: is this a subtype?
        # ----------------------------------------------------------------
        supertype_uri = None
        if cls_info["uri"] in subtype_parents:
            supertype_uri = URIRef(subtype_parents[cls_info["uri"]])
        is_subtype = supertype_uri is not None

        # ----------------------------------------------------------------
        # S3 — Flatten ALL subtypes into parent table (except GDPR)
        # Silver always uses single-table inheritance with discriminator.
        # ----------------------------------------------------------------
        if is_subtype and not is_gdpr:
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
        _add_object_property_fk_cols(merged, cls_uri, tbl, table_name_for, schema_name,
                                     class_uris, naming_conv)

        # 4. Discriminator column (R6 + S3 — auto-add if class has subtypes)
        disc_col = _str_val(merged, cls_uri, KAIROS_EXT.discriminatorColumn)
        if not disc_col and cls_info["uri"] in folded_subtypes:
            # S3: auto-generate discriminator for parent with flattened subtypes
            disc_col = f"{tbl_name}_type"
        if disc_col:
            tbl.columns.append(ColumnDef(disc_col, "STRING", nullable=False,
                                         comment="Type discriminator"))

        # 5. Data properties (business columns)
        _add_data_properties(merged, cls_uri, tbl, shacl_graph, naming_conv)

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
    for parent_uri_str, subtype_names in folded_subtypes.items():
        if parent_uri_str not in tables:
            continue
        parent_tbl = tables[parent_uri_str]
        # Find subtype class URIs and merge their properties
        for cls_info in domain_classes:
            if cls_info["name"] not in subtype_names:
                continue
            sub_uri = URIRef(cls_info["uri"])
            # Merge data properties as nullable columns with subtype comment
            _add_data_properties(
                merged, sub_uri, parent_tbl, shacl_graph, naming_conv,
                comment_prefix=f"from {cls_info['name']}"
            )
            # Merge object property FK columns
            _add_object_property_fk_cols(
                merged, sub_uri, parent_tbl, table_name_for, schema_name,
                class_uris, naming_conv,
                comment_prefix=f"from {cls_info['name']}"
            )

    # ----------------------------------------------------------------
    # S4 post-pass: inline small reference tables into parent
    # ----------------------------------------------------------------
    inline_threshold = 3  # default: inline ref tables with ≤3 business columns
    onto_threshold = merged.value(onto_uri, KAIROS_EXT.inlineRefThreshold)
    if onto_threshold is not None:
        inline_threshold = int(str(onto_threshold))
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
        f"-- Schema",
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
        f"-- Fabric Warehouse cannot enforce PK/FK/UNIQUE constraints.",
        f"-- These are provided as reference for data engineers.",
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

def _detect_ontology_uri(graph: Graph, namespace: str) -> URIRef:
    """Return the owl:Ontology URI for the given namespace, or a synthetic one."""
    for s in graph.subjects(RDF.type, OWL.Ontology):
        if str(s).startswith(namespace.rstrip("#/")):
            return s
    return URIRef(namespace.rstrip("#/"))


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


def _has_own_properties(graph: Graph, cls_uri: URIRef) -> bool:
    """Return True if the class has any DatatypeProperty or ObjectProperty
    whose ``rdfs:domain`` points directly to it (R16 check)."""
    for prop in graph.subjects(RDFS.domain, cls_uri):
        if (prop, RDF.type, OWL.DatatypeProperty) in graph:
            return True
        if (prop, RDF.type, OWL.ObjectProperty) in graph:
            return True
    return False


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
                if min_count is not None and int(str(min_count)) >= 1:
                    return True
    return False


def _add_data_properties(graph: Graph, cls_uri: URIRef, tbl: TableDef,
                          shacl_graph: Optional[Graph], naming_conv: str,
                          comment_prefix: str = "") -> None:
    """Add OWL DatatypeProperty columns to the table (business columns, R4, R11).

    Args:
        comment_prefix: If set (S3 flattening), prepended to column comment and
            forces nullable=True (subtype columns are always nullable on parent).
    """
    existing_col_names = {c.name for c in tbl.columns}
    for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
        domain = graph.value(prop, RDFS.domain)
        if domain != cls_uri:
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
        label = _str_val(graph, prop, RDFS.label, "")
        comment = f"{comment_prefix}; {label}" if comment_prefix and label else (
            comment_prefix or label
        )
        tbl.columns.append(ColumnDef(col_name, sql_type, nullable=nullable, comment=comment))


def _add_object_property_fk_cols(
    graph: Graph, cls_uri: URIRef, tbl: TableDef,
    table_name_for, schema_name: str, class_uris: set[str], naming_conv: str,
    comment_prefix: str = "",
) -> None:
    """Add FK columns from max-cardinality-1 object properties (R12).

    A property qualifies as a FK column when ANY of:
      - it has an explicit ``kairos-ext:silverColumnName`` annotation,
      - it is declared ``owl:FunctionalProperty``,
      - the domain class has an ``owl:maxQualifiedCardinality 1`` or
        ``owl:maxCardinality 1`` restriction on the property.

    Junction-table properties (R13) are always skipped.

    Handles duplicate column names (e.g. two self-referential FKs to the same
    range class) by appending the property name as a disambiguator.

    Args:
        comment_prefix: If set (S3 flattening), appended to FK comment and
            forces nullable=True (subtype FK columns are always nullable on parent).
    """
    # Track existing column names to avoid duplicates (PK, IRI, discriminator, etc.)
    existing_cols = {col.name for col in tbl.columns}

    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        domain = graph.value(prop, RDFS.domain)
        if domain != cls_uri:
            continue
        # Skip if this property has a junctionTableName (R13)
        if graph.value(prop, KAIROS_EXT.junctionTableName):
            continue
        # Determine if this is a many-to-one FK column
        has_explicit_col = bool(_str_val(graph, prop, KAIROS_EXT.silverColumnName))
        is_functional = (prop, RDF.type, OWL.FunctionalProperty) in graph
        if not has_explicit_col and not is_functional \
                and not _has_max_cardinality_1(graph, cls_uri, prop):
            continue
        range_cls = graph.value(prop, RDFS.range)
        if range_cls is None:
            continue

        # Resolve target table — same domain or cross-domain
        is_cross_domain = str(range_cls) not in class_uris
        if is_cross_domain:
            ref_schema, range_tbl = _resolve_external_table(
                graph, range_cls, naming_conv,
            )
            ref_full = f"{ref_schema}.{range_tbl}"
        else:
            range_local = _local_name(str(range_cls))
            range_tbl = table_name_for(range_cls, range_local)
            ref_full = f"{schema_name}.{range_tbl}"

        col_name_override = _str_val(graph, prop, KAIROS_EXT.silverColumnName)
        col_name = col_name_override or f"{range_tbl}_sk"

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
            nullable_ann = graph.value(prop, KAIROS_EXT.nullable)
            if nullable_ann is not None:
                nullable = str(nullable_ann).lower() not in ("false", "0")
            else:
                nullable = True

        # Conditional nullable (R14)
        cond_on = _str_val(graph, prop, KAIROS_EXT.conditionalOnType)
        cross_note = f"cross-domain FK → {ref_full}" if is_cross_domain else ""
        comment_parts = [p for p in [
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


def _has_max_cardinality_1(graph: Graph, cls_uri: URIRef, prop: URIRef) -> bool:
    """Return True if an owl:maxQualifiedCardinality 1 restriction exists (R12)."""
    for restriction in graph.subjects(OWL.onProperty, prop):
        if graph.value(restriction, OWL.maxQualifiedCardinality) == Literal(1, datatype=XSD.nonNegativeInteger):
            # Check restriction applies to this class
            for parent in graph.objects(cls_uri, RDFS.subClassOf):
                if parent == restriction:
                    return True
    # Also accept maxCardinality 1
    for restriction in graph.subjects(OWL.onProperty, prop):
        if graph.value(restriction, OWL.maxCardinality) == Literal(1, datatype=XSD.nonNegativeInteger):
            for parent in graph.objects(cls_uri, RDFS.subClassOf):
                if parent == restriction:
                    return True
    return False


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
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired):
        return None
