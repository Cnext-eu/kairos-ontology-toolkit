# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Gold Layer Projector — generate Power BI star-schema DDL, TMDL semantic model,
DAX measures, and Mermaid ERD from OWL ontologies annotated with kairos-ext:
projection extensions.

Common annotation rules R1–R16 define the shared ``kairos-ext:`` vocabulary.
Gold Power BI rules G1–G8 control star-schema-specific output behaviour:

  G1 — Star schema classification (fact/dimension/bridge by relationship patterns)
  G2 — dim_/fact_/bridge_ prefixes for Power BI naming conventions
  G3 — SCD Type 2 on dimensions (valid_from, valid_to, is_current)
  G4 — GDPR satellite → secured dimension + RLS role
  G5 — Class-per-table inheritance (default: subclasses → separate tables with shared PK/FK)
  G6 — Reference data → shared dimension with dim_ prefix
  G7 — Aggregate tables (deferred — placeholder)
  G8 — Power BI optimised types (BIT, INT date keys, INT surrogate keys)

Namespace:  kairos-ext:  https://kairos.cnext.eu/ext#
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace, URIRef, Literal, XSD
from rdflib.namespace import OWL, RDF, RDFS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# kairos-ext namespace
# ---------------------------------------------------------------------------
KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")

# ---------------------------------------------------------------------------
# XSD → SQL type mapping (G8 — Power BI / DirectLake optimised types)
# ---------------------------------------------------------------------------
XSD_TO_GOLD_SQL: dict[str, str] = {
    str(XSD.string): "VARCHAR(256)",
    str(XSD.normalizedString): "VARCHAR(256)",
    str(XSD.token): "VARCHAR(128)",
    str(XSD.integer): "BIGINT",
    str(XSD.int): "INT",
    str(XSD.long): "BIGINT",
    str(XSD.short): "SMALLINT",
    str(XSD.decimal): "DECIMAL(18,4)",
    str(XSD.float): "FLOAT",
    str(XSD.double): "FLOAT",
    str(XSD.boolean): "BIT",           # G8: Power BI prefers BIT over BOOLEAN
    str(XSD.date): "DATE",
    str(XSD.dateTime): "DATETIME2(6)",
    str(XSD.time): "VARCHAR(16)",
    str(XSD.gYear): "INT",
    str(XSD.anyURI): "VARCHAR(512)",
}

# G8: XSD → TMDL data type mapping for Power BI semantic model
XSD_TO_TMDL: dict[str, str] = {
    str(XSD.string): "String",
    str(XSD.normalizedString): "String",
    str(XSD.token): "String",
    str(XSD.integer): "Int64",
    str(XSD.int): "Int64",
    str(XSD.long): "Int64",
    str(XSD.short): "Int64",
    str(XSD.decimal): "Decimal",
    str(XSD.float): "Double",
    str(XSD.double): "Double",
    str(XSD.boolean): "Boolean",
    str(XSD.date): "DateTime",
    str(XSD.dateTime): "DateTime",
    str(XSD.time): "String",
    str(XSD.gYear): "Int64",
    str(XSD.anyURI): "String",
}


# ---------------------------------------------------------------------------
# Helpers (shared with silver but gold-specific overrides)
# ---------------------------------------------------------------------------

def _camel_to_snake(name: str) -> str:
    """Convert CamelCase or camelCase to snake_case (R4)."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _to_pascal_case(name: str) -> str:
    """Convert a domain name (snake_case or kebab-case) to PascalCase."""
    return "".join(part.capitalize() for part in re.split(r"[-_ ]+", name))


def _mmd_type(sql_type: str) -> str:
    """Sanitise SQL type for Mermaid erDiagram attribute."""
    return re.sub(r"[^A-Za-z0-9_]", "_", sql_type).strip("_")


def _local_name(uri: str) -> str:
    """Extract local name from a URI."""
    if "#" in uri:
        return uri.rsplit("#", 1)[1]
    return uri.rsplit("/", 1)[1]


def _str_val(graph: Graph, subject: URIRef, predicate: URIRef,
             default: str = "") -> str:
    val = graph.value(subject, predicate)
    return str(val) if val is not None else default


def _bool_val(graph: Graph, subject: URIRef, predicate: URIRef,
              default: bool = False) -> bool:
    val = graph.value(subject, predicate)
    if val is None:
        return default
    return str(val).lower() in ("true", "1", "yes")


def _int_val(graph: Graph, subject: URIRef, predicate: URIRef,
             default: int = 0) -> int:
    val = graph.value(subject, predicate)
    if val is None:
        return default
    try:
        return int(str(val))
    except ValueError:
        return default


def _detect_ontology_uri(graph: Graph, namespace: str) -> URIRef:
    """Return the owl:Ontology URI for the given namespace."""
    for s in graph.subjects(RDF.type, OWL.Ontology):
        if str(s).startswith(namespace.rstrip("#/")):
            return s
    return URIRef(namespace.rstrip("#/"))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class GoldColumnDef:
    """A column in a gold-layer table."""

    def __init__(self, name: str, sql_type: str, tmdl_type: str = "String",
                 nullable: bool = True, comment: str = "",
                 is_measure: bool = False, measure_expr: str = "",
                 measure_format: str = "", hierarchy_name: str = "",
                 hierarchy_level: int = 0, ols_restricted: bool = False):
        self.name = name
        self.sql_type = sql_type
        self.tmdl_type = tmdl_type
        self.nullable = nullable
        self.comment = comment
        self.is_measure = is_measure
        self.measure_expr = measure_expr
        self.measure_format = measure_format
        self.hierarchy_name = hierarchy_name
        self.hierarchy_level = hierarchy_level
        self.ols_restricted = ols_restricted

    def ddl_fragment(self) -> str:
        null_clause = "NULL" if self.nullable else "NOT NULL"
        comment_clause = f"  -- {self.comment}" if self.comment else ""
        return f"    {self.name:<35} {self.sql_type} {null_clause}{comment_clause}"


class GoldTableDef:
    """A table in the gold star schema."""

    def __init__(self, name: str, schema: str, table_type: str = "dimension"):
        self.name = name
        self.schema = schema
        self.full_name = f"{schema}.{name}"
        self.table_type = table_type  # fact | dimension | bridge
        self.columns: list[GoldColumnDef] = []
        self.pk_column: Optional[str] = None
        self.fk_constraints: list[tuple[str, str, str, str]] = []
        self.partition_by: Optional[str] = None
        self.scd_type: str = "1"
        self.is_gdpr: bool = False
        self.gdpr_parent_table: Optional[str] = None
        self.source_class_uri: Optional[str] = None
        self.source_class_label: str = ""
        self.is_subtype_cpt: bool = False
        self.parent_class_uri: Optional[str] = None
        self.measures: list[GoldColumnDef] = []
        self.hierarchies: dict[str, list[GoldColumnDef]] = {}
        self.perspectives: set[str] = set()
        self.incremental_column: Optional[str] = None

    def render_create(self) -> str:
        """Render CREATE TABLE statement (Spark SQL for Fabric Warehouse)."""
        lines = [f"CREATE TABLE {self.full_name} ("]
        col_lines = [c.ddl_fragment() for c in self.columns]
        lines.append(",\n".join(col_lines))
        lines.append(")")
        if self.partition_by:
            lines[-1] += f"\nPARTITIONED BY ({self.partition_by})"
        lines.append(";")
        return "\n".join(lines)

    def render_alter(self) -> list[str]:
        """Render constraint documentation (informational — Fabric can't enforce)."""
        stmts = []
        if self.pk_column:
            stmts.append(
                f"-- PK: {self.pk_column}")
        for col, ref_full, ref_col, label in self.fk_constraints:
            stmts.append(
                f"-- FK: {col} -> {ref_full} ({ref_col})")
        return stmts


# ---------------------------------------------------------------------------
# G1 — Star schema classifier
# ---------------------------------------------------------------------------

def _classify_tables(
    graph: Graph,
    domain_classes: list[dict],
    class_uris: set[str],
) -> dict[str, str]:
    """Classify OWL classes as 'fact', 'dimension', or 'bridge'.

    G1 heuristic:
    - Classes with explicit goldTableType annotation → use it
    - isReferenceData = true → 'dimension' (G6)
    - gdprSatelliteOf set → 'dimension' (G4)
    - Classes with ≥2 outgoing FK object properties → 'fact'
    - Everything else → 'dimension'
    """
    classifications: dict[str, str] = {}

    # Count outgoing FK-style object properties per class
    outgoing_fks: dict[str, int] = {c["uri"]: 0 for c in domain_classes}
    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        domain = graph.value(prop, RDFS.domain)
        if domain is None or str(domain) not in class_uris:
            continue
        range_cls = graph.value(prop, RDFS.range)
        if range_cls is None:
            continue
        # Junction tables don't count as FK
        if graph.value(prop, KAIROS_EXT.junctionTableName):
            continue
        # Degenerate dimensions don't count
        if _bool_val(graph, prop, KAIROS_EXT.degenerateDimension, False):
            continue
        outgoing_fks[str(domain)] = outgoing_fks.get(str(domain), 0) + 1

    for cls_info in domain_classes:
        cls_uri = URIRef(cls_info["uri"])
        uri_str = cls_info["uri"]

        # Explicit override
        explicit_type = _str_val(graph, cls_uri, KAIROS_EXT.goldTableType)
        if explicit_type in ("fact", "dimension", "bridge"):
            classifications[uri_str] = explicit_type
            continue

        # G6: Reference data → always dimension
        if _bool_val(graph, cls_uri, KAIROS_EXT.isReferenceData, False):
            classifications[uri_str] = "dimension"
            continue

        # G4: GDPR satellite → dimension
        if graph.value(cls_uri, KAIROS_EXT.gdprSatelliteOf) is not None:
            classifications[uri_str] = "dimension"
            continue

        # G1 heuristic: ≥2 outgoing FK → fact
        if outgoing_fks.get(uri_str, 0) >= 2:
            classifications[uri_str] = "fact"
        else:
            classifications[uri_str] = "dimension"

    return classifications


# ---------------------------------------------------------------------------
# G5 — Hierarchy helpers
# ---------------------------------------------------------------------------

def _collect_hierarchies(
    graph: Graph, cls_uri: URIRef,
) -> dict[str, list[tuple[int, str, str]]]:
    """Collect hierarchy definitions from property annotations.

    Returns: {hierarchy_name: [(level, col_name, prop_uri_str), ...]} sorted by level.
    """
    hierarchies: dict[str, list[tuple[int, str, str]]] = {}
    for prop in graph.subjects(RDFS.domain, cls_uri):
        h_name = _str_val(graph, prop, KAIROS_EXT.hierarchyName)
        if not h_name:
            continue
        h_level = _int_val(graph, prop, KAIROS_EXT.hierarchyLevel, 99)
        prop_local = _local_name(str(prop))
        col_name = _str_val(graph, prop, KAIROS_EXT.goldColumnName) or _camel_to_snake(
            prop_local)
        hierarchies.setdefault(h_name, []).append((h_level, col_name, str(prop)))

    # Sort each hierarchy by level
    for h_name in hierarchies:
        hierarchies[h_name].sort(key=lambda x: x[0])

    return hierarchies


# ---------------------------------------------------------------------------
# dim_date generator
# ---------------------------------------------------------------------------

def _generate_date_dimension(schema: str) -> GoldTableDef:
    """Generate a standard dim_date table with YYYYMMDD integer key."""
    tbl = GoldTableDef("dim_date", schema, "dimension")
    tbl.scd_type = "1"

    cols = [
        ("date_key", "INT", "Int64", False, "YYYYMMDD integer key"),
        ("full_date", "DATE", "DateTime", False, "Calendar date"),
        ("day_of_week", "SMALLINT", "Int64", True, "1=Monday, 7=Sunday"),
        ("day_of_month", "SMALLINT", "Int64", True, "Day number in month"),
        ("day_of_year", "SMALLINT", "Int64", True, "Day number in year"),
        ("day_name", "VARCHAR(16)", "String", True, "Monday, Tuesday, ..."),
        ("week_of_year", "SMALLINT", "Int64", True, "ISO week number"),
        ("month_number", "SMALLINT", "Int64", True, "1-12"),
        ("month_name", "VARCHAR(16)", "String", True, "January, February, ..."),
        ("month_short", "VARCHAR(3)", "String", True, "Jan, Feb, ..."),
        ("quarter_number", "SMALLINT", "Int64", True, "1-4"),
        ("quarter_name", "VARCHAR(4)", "String", True, "Q1, Q2, Q3, Q4"),
        ("year_number", "INT", "Int64", True, "Calendar year (e.g. 2026)"),
        ("year_month", "VARCHAR(8)", "String", True, "YYYY-MM"),
        ("year_quarter", "VARCHAR(8)", "String", True, "YYYY-Q1"),
        ("is_weekend", "BIT", "Boolean", True, "1 if Saturday or Sunday"),
        ("is_holiday", "BIT", "Boolean", True, "1 if public holiday (populate manually)"),
        ("fiscal_year", "INT", "Int64", True, "Fiscal year (populate per org)"),
        ("fiscal_quarter", "SMALLINT", "Int64", True, "Fiscal quarter (populate per org)"),
        ("fiscal_month", "SMALLINT", "Int64", True, "Fiscal month (populate per org)"),
    ]
    for name, sql_t, tmdl_t, nullable, comment in cols:
        tbl.columns.append(GoldColumnDef(name, sql_t, tmdl_t, nullable, comment))
    tbl.pk_column = "date_key"

    # Standard calendar hierarchy
    tbl.hierarchies["Calendar"] = [
        (1, "year_number", ""),
        (2, "quarter_name", ""),
        (3, "month_name", ""),
        (4, "full_date", ""),
    ]

    return tbl


# ---------------------------------------------------------------------------
# Public helper: build gold table definitions (reused by dbt projector)
# ---------------------------------------------------------------------------

def build_gold_tables(
    classes: list[dict],
    graph: Graph,
    namespace: str,
    shapes_dir: Optional[Path] = None,
    ontology_name: str = "domain",
    projection_ext_path: Optional[Path] = None,
) -> list[GoldTableDef]:
    """Build gold table definitions without rendering output files.

    This is the shared logic used by both the gold projector (DDL/TMDL/DAX)
    and the dbt projector (gold dbt models).  Returns the ordered list of
    ``GoldTableDef`` objects ready for rendering.

    Args:
        classes: Pre-extracted list of ``{uri, name, label, comment}`` dicts.
        graph: Loaded domain ontology graph.
        namespace: Domain namespace URI string.
        shapes_dir: Optional SHACL shapes directory.
        ontology_name: Domain name (used for default schema).
        projection_ext_path: Optional path to ``*-gold-ext.ttl`` annotation file.

    Returns:
        Ordered list of ``GoldTableDef`` (date dim → dimensions → facts → bridges).
    """
    # Merge projection extension into working graph
    merged = Graph()
    for triple in graph:
        merged.add(triple)
    if projection_ext_path and projection_ext_path.exists():
        ext_graph = Graph()
        ext_graph.parse(str(projection_ext_path), format="turtle")
        for triple in ext_graph:
            merged.add(triple)

    # Merge SHACL shapes
    shacl_graph: Optional[Graph] = None
    if shapes_dir and shapes_dir.exists():
        shacl_graph = Graph()
        for shacl_file in shapes_dir.glob("*.ttl"):
            shacl_graph.parse(str(shacl_file), format="turtle")

    # Read ontology-level annotations
    onto_uri = _detect_ontology_uri(merged, namespace)
    schema_name = _str_val(merged, onto_uri, KAIROS_EXT.goldSchema,
                           f"gold_{ontology_name}")
    naming_conv = _str_val(merged, onto_uri, KAIROS_EXT.namingConvention,
                           "camel-to-snake")
    gen_date_dim = _bool_val(merged, onto_uri, KAIROS_EXT.generateDateDimension,
                             True)
    gen_time_intel = _bool_val(merged, onto_uri,
                               KAIROS_EXT.generateTimeIntelligence, False)
    default_inheritance = _str_val(merged, onto_uri,
                                   KAIROS_EXT.goldInheritanceStrategy,
                                   "class-per-table")

    # Filter to domain-owned classes only
    domain_classes = [c for c in classes if c["uri"].startswith(namespace)]
    class_uris = {c["uri"] for c in domain_classes}

    # Filter out excluded classes
    domain_classes = [
        c for c in domain_classes
        if not _bool_val(merged, URIRef(c["uri"]), KAIROS_EXT.goldExclude, False)
    ]
    class_uris = {c["uri"] for c in domain_classes}

    if not domain_classes:
        return []

    # G1 — Classify tables
    classifications = _classify_tables(merged, domain_classes, class_uris)

    # Track subtype relationships for G5 inheritance handling
    subtype_parents: dict[str, str] = {}
    folded_subtypes: dict[str, list[str]] = {}
    for cls_info in domain_classes:
        cls_uri = URIRef(cls_info["uri"])
        gdpr_parent = merged.value(cls_uri, KAIROS_EXT.gdprSatelliteOf)
        if gdpr_parent is not None:
            continue
        for parent in merged.objects(cls_uri, RDFS.subClassOf):
            if isinstance(parent, URIRef) and str(parent) in class_uris:
                subtype_parents[cls_info["uri"]] = str(parent)
                existing = folded_subtypes.setdefault(str(parent), [])
                if cls_info["name"] not in existing:
                    existing.append(cls_info["name"])
                break

    def _class_inheritance(cls_uri: URIRef) -> str:
        """Return inheritance strategy for a class (per-class override or default)."""
        return _str_val(merged, cls_uri, KAIROS_EXT.goldInheritanceStrategy,
                        default_inheritance)

    def gold_table_name(cls_uri_arg: URIRef, local: str, table_type: str) -> str:
        override = _str_val(merged, cls_uri_arg, KAIROS_EXT.goldTableName)
        base = override or (
            _camel_to_snake(local) if naming_conv == "camel-to-snake" else local.lower()
        )
        if table_type == "fact" and not base.startswith("fact_"):
            return f"fact_{base}"
        elif table_type == "dimension" and not base.startswith("dim_"):
            return f"dim_{base}"
        elif table_type == "bridge" and not base.startswith("bridge_"):
            return f"bridge_{base}"
        return base

    def base_table_name(cls_uri_arg: URIRef, local: str) -> str:
        override = _str_val(merged, cls_uri_arg, KAIROS_EXT.goldTableName)
        return override or (
            _camel_to_snake(local) if naming_conv == "camel-to-snake" else local.lower()
        )

    # Build tables
    tables: dict[str, GoldTableDef] = {}

    # Determine which subtypes use discriminator (fold) vs class-per-table (separate)
    disc_parents: set[str] = set()  # parents using discriminator strategy
    for parent_uri_str, subtype_names in folded_subtypes.items():
        parent_strategy = _class_inheritance(URIRef(parent_uri_str))
        if parent_strategy == "discriminator":
            disc_parents.add(parent_uri_str)

    for cls_info in domain_classes:
        cls_uri = URIRef(cls_info["uri"])
        local = cls_info["name"]
        uri_str = cls_info["uri"]

        # G5: skip subtypes only when parent uses discriminator strategy
        if uri_str in subtype_parents:
            parent_uri = subtype_parents[uri_str]
            if parent_uri in disc_parents:
                continue  # will be merged in post-pass

        table_type = classifications.get(uri_str, "dimension")
        is_subtype_cpt = uri_str in subtype_parents and \
            subtype_parents[uri_str] not in disc_parents
        tbl_name = gold_table_name(cls_uri, local, table_type)

        tbl = GoldTableDef(tbl_name, schema_name, table_type)
        tbl.source_class_uri = uri_str
        tbl.source_class_label = cls_info.get("label", local)
        is_ref = _bool_val(merged, cls_uri, KAIROS_EXT.isReferenceData, False)
        gdpr_parent = merged.value(cls_uri, KAIROS_EXT.gdprSatelliteOf)
        is_gdpr = gdpr_parent is not None
        scd = _str_val(merged, cls_uri, KAIROS_EXT.scdType,
                        "1" if is_ref else "2")
        tbl.scd_type = scd
        tbl.is_gdpr = is_gdpr
        tbl.partition_by = (
            _str_val(merged, cls_uri, KAIROS_EXT.partitionBy) or None
        ) if table_type == "fact" else None
        tbl.incremental_column = (
            _str_val(merged, cls_uri, KAIROS_EXT.incrementalColumn) or None
        )

        if is_subtype_cpt:
            # G5 class-per-table: PK = parent's SK, also FK to parent table
            parent_uri_str = subtype_parents[uri_str]
            parent_cls_uri = URIRef(parent_uri_str)
            parent_local = _local_name(parent_uri_str)
            parent_base = base_table_name(parent_cls_uri, parent_local)
            parent_type = classifications.get(parent_uri_str, "dimension")
            parent_tbl_name = gold_table_name(parent_cls_uri, parent_local,
                                              parent_type)
            sk_name = f"{parent_base}_sk"
            tbl.columns.append(GoldColumnDef(
                sk_name, "INT", "Int64", nullable=False,
                comment=f"PK/FK → {parent_tbl_name} (G5 class-per-table)"))
            tbl.pk_column = sk_name
            tbl.fk_constraints.append(
                (sk_name, f"{schema_name}.{parent_tbl_name}",
                 sk_name, "subclass_of"))
            tbl.is_subtype_cpt = True
            tbl.parent_class_uri = parent_uri_str
        elif not is_gdpr:
            base_name = base_table_name(cls_uri, local)
            sk_name = f"{base_name}_sk"
            tbl.columns.append(GoldColumnDef(
                sk_name, "INT", "Int64", nullable=False,
                comment="Surrogate key (INT IDENTITY)"))
            tbl.pk_column = sk_name
        else:
            parent_local = _local_name(str(gdpr_parent))
            parent_base = base_table_name(gdpr_parent, parent_local)
            parent_type = classifications.get(str(gdpr_parent), "dimension")
            parent_tbl_name = gold_table_name(gdpr_parent, parent_local, parent_type)
            sk_name = f"{parent_base}_sk"
            tbl.columns.append(GoldColumnDef(
                sk_name, "INT", "Int64", nullable=False,
                comment=f"PK/FK → {parent_tbl_name} (GDPR satellite)"))
            tbl.pk_column = sk_name
            tbl.gdpr_parent_table = parent_tbl_name
            tbl.fk_constraints.append(
                (sk_name, f"{schema_name}.{parent_tbl_name}",
                 sk_name, "gdpr_satellite_of"))

        _add_gold_fk_columns(
            merged, cls_uri, tbl, class_uris, classifications,
            schema_name, gold_table_name, base_table_name, naming_conv)

        # Discriminator column: only for parents using discriminator strategy
        disc_col = _str_val(merged, cls_uri, KAIROS_EXT.discriminatorColumn)
        if not disc_col and uri_str in folded_subtypes and uri_str in disc_parents:
            base = base_table_name(cls_uri, local)
            disc_col = f"{base}_type"
        if disc_col:
            tbl.columns.append(GoldColumnDef(
                disc_col, "VARCHAR(64)", "String", nullable=False,
                comment="Type discriminator (G5)"))

        _add_gold_data_properties(
            merged, cls_uri, tbl, shacl_graph, naming_conv)

        if table_type == "dimension" and scd == "2" and not is_ref:
            tbl.columns.append(GoldColumnDef(
                "valid_from", "DATE", "DateTime", nullable=False))
            tbl.columns.append(GoldColumnDef(
                "valid_to", "DATE", "DateTime", nullable=True,
                comment="NULL = current record"))
            tbl.columns.append(GoldColumnDef(
                "is_current", "BIT", "Boolean", nullable=False,
                comment="1 = current record"))

        tbl.hierarchies = _collect_hierarchies(merged, cls_uri)

        # Perspectives: assign table to named perspective groups
        perspective = _str_val(merged, cls_uri, KAIROS_EXT.perspective)
        if perspective:
            for p in perspective.split():
                tbl.perspectives.add(p)

        tables[uri_str] = tbl

    # G5 post-pass: merge subtype properties into parent (discriminator only)
    for parent_uri_str, subtype_names in folded_subtypes.items():
        if parent_uri_str not in disc_parents:
            continue
        if parent_uri_str not in tables:
            continue
        parent_tbl = tables[parent_uri_str]
        for cls_info in domain_classes:
            if cls_info["name"] not in subtype_names:
                continue
            sub_uri = URIRef(cls_info["uri"])
            _add_gold_data_properties(
                merged, sub_uri, parent_tbl, shacl_graph, naming_conv,
                comment_prefix=f"from {cls_info['name']}")
            _add_gold_fk_columns(
                merged, sub_uri, parent_tbl, class_uris, classifications,
                schema_name, gold_table_name, base_table_name, naming_conv,
                comment_prefix=f"from {cls_info['name']}")

    # Bridge tables from many-to-many (R13)
    bridge_tables = _build_gold_bridge_tables(
        merged, class_uris, classifications, tables, schema_name,
        gold_table_name, base_table_name, naming_conv)

    # Date dimension (G8)
    date_dim: Optional[GoldTableDef] = None
    if gen_date_dim:
        date_dim = _generate_date_dimension(schema_name)

    # Collect all tables in order
    all_tables: list[GoldTableDef] = []
    if date_dim:
        all_tables.append(date_dim)
    dims = [t for t in tables.values() if t.table_type == "dimension"]
    facts = [t for t in tables.values() if t.table_type == "fact"]
    bridges = [t for t in tables.values() if t.table_type == "bridge"]
    all_tables.extend(sorted(dims, key=lambda t: t.name))
    all_tables.extend(sorted(facts, key=lambda t: t.name))
    all_tables.extend(sorted(bridges, key=lambda t: t.name))
    all_tables.extend(bridge_tables)

    return all_tables


# ---------------------------------------------------------------------------
# Main projector function
# ---------------------------------------------------------------------------

def generate_gold_artifacts(
    classes: list[dict],
    graph: Graph,
    namespace: str,
    shapes_dir: Optional[Path] = None,
    ontology_name: str = "domain",
    projection_ext_path: Optional[Path] = None,
    ontology_metadata: Optional[dict] = None,
) -> dict[str, str]:
    """Generate gold layer star-schema DDL, TMDL, DAX measures, and Mermaid ERD.

    Args:
        classes: Pre-extracted list of ``{uri, name, label, comment}`` dicts.
        graph: Loaded domain ontology graph.
        namespace: Domain namespace URI string.
        shapes_dir: Optional SHACL shapes directory.
        ontology_name: Domain name (used for filenames and default schema).
        projection_ext_path: Optional path to ``*-gold-ext.ttl`` annotation file.
        ontology_metadata: Provenance metadata from ``extract_ontology_metadata()``.

    Returns:
        ``{filename: content}`` mapping for all gold artifacts.
    """
    # Delegate table building to the shared helper
    all_tables = build_gold_tables(
        classes, graph, namespace, shapes_dir, ontology_name, projection_ext_path,
    )
    if not all_tables:
        return {}

    # Re-read schema_name from the merged graph for rendering headers
    merged = Graph()
    for triple in graph:
        merged.add(triple)
    if projection_ext_path and projection_ext_path.exists():
        ext_graph = Graph()
        ext_graph.parse(str(projection_ext_path), format="turtle")
        for triple in ext_graph:
            merged.add(triple)
    onto_uri = _detect_ontology_uri(merged, namespace)
    schema_name = _str_val(merged, onto_uri, KAIROS_EXT.goldSchema,
                           f"gold_{ontology_name}")
    gen_time_intel = _bool_val(merged, onto_uri,
                               KAIROS_EXT.generateTimeIntelligence, False)

    # ----------------------------------------------------------
    # Build provenance header
    # ----------------------------------------------------------
    meta = ontology_metadata or {}
    prov_lines = [
        f"-- Gold layer star schema: {schema_name}",
        f"-- Domain: {ontology_name}",
    ]
    if meta.get("iri"):
        prov_lines.append(f"-- Ontology IRI: {meta['iri']}")
    if meta.get("version"):
        prov_lines.append(f"-- Ontology version: {meta['version']}")
    if meta.get("toolkit_version"):
        prov_lines.append(f"-- Toolkit version: {meta['toolkit_version']}")
    if meta.get("generated_at"):
        prov_lines.append(f"-- Generated at: {meta['generated_at']}")

    # ----------------------------------------------------------
    # Render DDL
    # ----------------------------------------------------------
    ddl_lines = prov_lines + [
        "",
        f"CREATE SCHEMA IF NOT EXISTS {schema_name};",
        "",
    ]
    for tbl in all_tables:
        type_label = tbl.table_type.upper()
        ddl_lines.append(f"-- {type_label}: {tbl.full_name}")
        if tbl.source_class_label:
            ddl_lines.append(f"-- Source: {tbl.source_class_label}")
        ddl_lines.append(tbl.render_create())
        ddl_lines.append("")

    # ----------------------------------------------------------
    # Render ALTER (constraint documentation)
    # ----------------------------------------------------------
    alter_lines = [
        f"-- Gold layer constraints (documentation only): {schema_name}",
        f"-- Fabric Warehouse cannot enforce PK/FK constraints.",
        f"-- Domain: {ontology_name}",
    ]
    if meta.get("iri"):
        alter_lines.append(f"-- Ontology IRI: {meta['iri']}")
    alter_lines.append("")
    for tbl in all_tables:
        stmts = tbl.render_alter()
        if stmts:
            alter_lines.append(f"-- {tbl.full_name}")
            alter_lines.extend(stmts)
            alter_lines.append("")

    # ----------------------------------------------------------
    # Render SCD2 framing views
    # ----------------------------------------------------------
    view_lines = prov_lines + [
        "",
        "-- SCD Type 2 framing views: filter to current records only.",
        "-- Use these views in Power BI DirectLake semantic models.",
        "",
    ]
    has_views = False
    for tbl in all_tables:
        if tbl.table_type == "dimension" and tbl.scd_type == "2":
            view_name = f"v_{tbl.name}"
            view_lines.append(f"-- Current-record view for {tbl.full_name}")
            view_lines.append(
                f"CREATE OR REPLACE VIEW {tbl.schema}.{view_name} AS")
            view_lines.append(f"SELECT *")
            view_lines.append(f"FROM {tbl.full_name}")
            view_lines.append(f"WHERE is_current = 1;")
            view_lines.append("")
            has_views = True

    # ----------------------------------------------------------
    # Render Mermaid ERD (star schema)
    # ----------------------------------------------------------
    mmd_lines = [
        "erDiagram",
        f'    %% Gold Star Schema ERD: {schema_name} / {ontology_name}',
    ]
    if meta.get("toolkit_version"):
        mmd_lines.append(f"    %% Toolkit version: {meta['toolkit_version']}")
    mmd_lines.append("")

    for tbl in all_tables:
        mmd_lines.append(f"    {tbl.name.upper()} {{")
        for col in tbl.columns:
            pk_marker = " PK" if col.name == tbl.pk_column else ""
            fk_marker = ""
            for fk_col, _, _, _ in tbl.fk_constraints:
                if col.name == fk_col:
                    fk_marker = " FK"
                    break
            mmd_lines.append(
                f"        {_mmd_type(col.sql_type)} {col.name}{pk_marker}{fk_marker}")
        mmd_lines.append("    }")
        mmd_lines.append("")

    # FK relationships
    for tbl in all_tables:
        for col, ref_full, ref_col, label in tbl.fk_constraints:
            ref_tbl_name = ref_full.split(".")[-1].upper()
            if tbl.table_type == "fact":
                mmd_lines.append(
                    f"    {ref_tbl_name} ||--o{{ {tbl.name.upper()} : \"{label}\"")
            else:
                mmd_lines.append(
                    f"    {ref_tbl_name} ||--o{{ {tbl.name.upper()} : \"{label}\"")

    # ----------------------------------------------------------
    # Collect measures
    # ----------------------------------------------------------
    all_measures: list[tuple[str, GoldColumnDef]] = []
    for tbl in all_tables:
        for m in tbl.measures:
            all_measures.append((tbl.name, m))

    # ----------------------------------------------------------
    # Render TMDL
    # ----------------------------------------------------------
    tmdl_definition = _render_tmdl_definition(schema_name, ontology_name, meta)
    tmdl_tables: dict[str, str] = {}
    for tbl in all_tables:
        tmdl_tables[f"tables/{tbl.name}.tmdl"] = _render_tmdl_table(tbl, schema_name)
    tmdl_relationships = _render_tmdl_relationships(all_tables, schema_name)
    tmdl_roles = _render_tmdl_rls_roles(all_tables, schema_name)
    tmdl_perspectives = _render_tmdl_perspectives(all_tables, schema_name)
    tmdl_calc_group = (
        _render_tmdl_calculation_group(schema_name, meta) if gen_time_intel else ""
    )

    # ----------------------------------------------------------
    # Render DAX measures
    # ----------------------------------------------------------
    dax_lines = _render_dax_measures(all_measures, ontology_name, meta)

    # ----------------------------------------------------------
    # Assemble output files
    # ----------------------------------------------------------
    sm_prefix = (
        f"{ontology_name}/{_to_pascal_case(ontology_name)}.SemanticModel/definition"
    )

    result: dict[str, str] = {
        f"{ontology_name}/{ontology_name}-gold-ddl.sql": "\n".join(ddl_lines),
        f"{ontology_name}/{ontology_name}-gold-alter.sql": "\n".join(alter_lines),
        f"{ontology_name}/{ontology_name}-gold-erd.mmd": "\n".join(mmd_lines),
    }

    if has_views:
        result[f"{ontology_name}/{ontology_name}-gold-views.sql"] = "\n".join(
            view_lines)

    # TMDL files — standard Power BI layout:
    # {Domain}.SemanticModel/definition/model.tmdl
    result[f"{sm_prefix}/model.tmdl"] = tmdl_definition
    for tmdl_path, tmdl_content in tmdl_tables.items():
        result[f"{sm_prefix}/{tmdl_path}"] = tmdl_content
    result[
        f"{sm_prefix}/relationships/relationships.tmdl"
    ] = tmdl_relationships

    if tmdl_roles:
        result[
            f"{sm_prefix}/roles/rls-roles.tmdl"
        ] = tmdl_roles

    if tmdl_perspectives:
        result[
            f"{sm_prefix}/perspectives/perspectives.tmdl"
        ] = tmdl_perspectives

    if tmdl_calc_group:
        result[
            f"{sm_prefix}/calculationGroups/time-intelligence.tmdl"
        ] = tmdl_calc_group

    if dax_lines:
        result[f"{ontology_name}/measures/{ontology_name}-measures.dax"] = dax_lines

    return result


# ---------------------------------------------------------------------------
# Property helpers
# ---------------------------------------------------------------------------

def _add_gold_data_properties(
    graph: Graph, cls_uri: URIRef, tbl: GoldTableDef,
    shacl_graph: Optional[Graph], naming_conv: str,
    comment_prefix: str = "",
) -> None:
    """Add OWL DatatypeProperty columns to the gold table."""
    SH = Namespace("http://www.w3.org/ns/shacl#")
    existing = {c.name for c in tbl.columns}

    for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
        domain = graph.value(prop, RDFS.domain)
        if domain != cls_uri:
            continue

        prop_local = _local_name(str(prop))

        # Check if this is a measure (not a physical column)
        measure_expr = _str_val(graph, prop, KAIROS_EXT.measureExpression)
        if measure_expr:
            measure_format = _str_val(graph, prop, KAIROS_EXT.measureFormatString,
                                       "#,##0")
            col_name = _str_val(graph, prop, KAIROS_EXT.goldColumnName) or (
                _camel_to_snake(prop_local) if naming_conv == "camel-to-snake"
                else prop_local.lower()
            )
            label = _str_val(graph, prop, RDFS.label, col_name)
            tbl.measures.append(GoldColumnDef(
                col_name, "", "", is_measure=True,
                measure_expr=measure_expr, measure_format=measure_format,
                comment=label))
            continue

        range_uri = graph.value(prop, RDFS.range)
        sql_type = XSD_TO_GOLD_SQL.get(str(range_uri), "VARCHAR(256)") \
            if range_uri else "VARCHAR(256)"
        tmdl_type = XSD_TO_TMDL.get(str(range_uri), "String") \
            if range_uri else "String"

        # Override from gold annotation
        override_type = _str_val(graph, prop, KAIROS_EXT.goldDataType)
        if override_type:
            sql_type = override_type

        # Column name
        col_name = _str_val(graph, prop, KAIROS_EXT.goldColumnName) or (
            _camel_to_snake(prop_local) if naming_conv == "camel-to-snake"
            else prop_local.lower()
        )
        if col_name in existing:
            continue
        existing.add(col_name)

        # Nullability
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

        col = GoldColumnDef(col_name, sql_type, tmdl_type, nullable, comment)

        # Hierarchy info
        col.hierarchy_name = _str_val(graph, prop, KAIROS_EXT.hierarchyName)
        col.hierarchy_level = _int_val(graph, prop, KAIROS_EXT.hierarchyLevel, 0)

        # OLS: Object-Level Security restriction
        col.ols_restricted = _bool_val(graph, prop, KAIROS_EXT.olsRestricted, False)

        tbl.columns.append(col)


def _not_null_from_shacl(shacl_graph: Optional[Graph], prop_uri: URIRef,
                          cls_uri: URIRef) -> bool:
    """Return True if SHACL shape has sh:minCount 1 for this property."""
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


def _add_gold_fk_columns(
    graph: Graph, cls_uri: URIRef, tbl: GoldTableDef,
    class_uris: set[str], classifications: dict[str, str],
    schema_name: str, gold_table_name_fn, base_table_name_fn,
    naming_conv: str, comment_prefix: str = "",
) -> None:
    """Add FK columns from object properties to the gold table."""
    existing = {c.name for c in tbl.columns}

    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        domain = graph.value(prop, RDFS.domain)
        if domain != cls_uri:
            continue
        # Skip junction table properties
        if graph.value(prop, KAIROS_EXT.junctionTableName):
            continue
        # Check if degenerate dimension — skip FK, property was already added as column
        if _bool_val(graph, prop, KAIROS_EXT.degenerateDimension, False):
            continue
        # Determine if this is a FK-style property
        has_explicit_col = bool(_str_val(graph, prop, KAIROS_EXT.goldColumnName))
        is_functional = (prop, RDF.type, OWL.FunctionalProperty) in graph
        if not has_explicit_col and not is_functional \
                and not _has_max_cardinality_1(graph, cls_uri, prop):
            continue

        range_cls = graph.value(prop, RDFS.range)
        if range_cls is None:
            continue

        range_uri_str = str(range_cls)
        range_local = _local_name(range_uri_str)
        range_base = base_table_name_fn(range_cls, range_local)

        # G8: INT FK (matching INT SK on target)
        col_name = _str_val(graph, prop, KAIROS_EXT.goldColumnName) or \
            f"{range_base}_sk"

        # Disambiguate
        if col_name in existing:
            prop_suffix = _camel_to_snake(_local_name(str(prop)))
            col_name = f"{prop_suffix}_sk"
            if col_name in existing:
                col_name = f"{range_base}_{prop_suffix}_sk"
        existing.add(col_name)

        # Resolve target table name
        if range_uri_str in class_uris:
            range_type = classifications.get(range_uri_str, "dimension")
            range_tbl = gold_table_name_fn(range_cls, range_local, range_type)
            ref_full = f"{schema_name}.{range_tbl}"
        else:
            # Cross-domain reference — use gold naming
            range_tbl = f"dim_{range_base}"
            ns_part = range_uri_str.rstrip("#/").rsplit("/", 1)[-1] \
                if "/" in range_uri_str else range_uri_str
            ext_schema = f"gold_{ns_part}"
            ref_full = f"{ext_schema}.{range_tbl}"

        nullable = True if comment_prefix else True  # FK columns nullable by default
        prop_label = _camel_to_snake(_local_name(str(prop)))
        comment = comment_prefix or ""

        # Role-playing dimension support
        role_playing = _str_val(graph, prop, KAIROS_EXT.rolePlayingAs)

        tbl.columns.append(GoldColumnDef(
            col_name, "INT", "Int64", nullable=nullable, comment=comment))
        tbl.fk_constraints.append(
            (col_name, ref_full, f"{range_base}_sk", prop_label))


def _has_max_cardinality_1(graph: Graph, cls_uri: URIRef, prop: URIRef) -> bool:
    """Return True if owl:maxQualifiedCardinality 1 or owl:maxCardinality 1."""
    for restriction in graph.subjects(OWL.onProperty, prop):
        if graph.value(restriction, OWL.maxQualifiedCardinality) == \
                Literal(1, datatype=XSD.nonNegativeInteger):
            for parent in graph.objects(cls_uri, RDFS.subClassOf):
                if parent == restriction:
                    return True
    for restriction in graph.subjects(OWL.onProperty, prop):
        if graph.value(restriction, OWL.maxCardinality) == \
                Literal(1, datatype=XSD.nonNegativeInteger):
            for parent in graph.objects(cls_uri, RDFS.subClassOf):
                if parent == restriction:
                    return True
    return False


def _build_gold_bridge_tables(
    graph: Graph, class_uris: set[str],
    classifications: dict[str, str],
    tables: dict[str, GoldTableDef],
    schema_name: str, gold_table_name_fn, base_table_name_fn,
    naming_conv: str,
) -> list[GoldTableDef]:
    """Build bridge tables for many-to-many object properties (R13)."""
    bridges: list[GoldTableDef] = []
    seen: set[str] = set()

    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        jct_name = _str_val(graph, prop, KAIROS_EXT.junctionTableName)
        if not jct_name or jct_name in seen:
            continue
        seen.add(jct_name)

        domain_cls = graph.value(prop, RDFS.domain)
        range_cls = graph.value(prop, RDFS.range)
        if domain_cls is None or range_cls is None:
            continue
        if str(domain_cls) not in class_uris and str(range_cls) not in class_uris:
            continue

        bridge_name = f"bridge_{jct_name}" if not jct_name.startswith("bridge_") \
            else jct_name
        bridge = GoldTableDef(bridge_name, schema_name, "bridge")

        # SK
        bridge.columns.append(GoldColumnDef(
            f"{jct_name}_sk", "INT", "Int64", nullable=False,
            comment="Surrogate key (INT IDENTITY)"))
        bridge.pk_column = f"{jct_name}_sk"

        # FK to domain side
        dom_local = _local_name(str(domain_cls))
        dom_base = base_table_name_fn(domain_cls, dom_local)
        dom_type = classifications.get(str(domain_cls), "dimension")
        dom_tbl = gold_table_name_fn(domain_cls, dom_local, dom_type)
        bridge.columns.append(GoldColumnDef(
            f"{dom_base}_sk", "INT", "Int64", nullable=False))
        bridge.fk_constraints.append(
            (f"{dom_base}_sk", f"{schema_name}.{dom_tbl}",
             f"{dom_base}_sk", f"{_camel_to_snake(_local_name(str(prop)))}_domain"))

        # FK to range side
        rng_local = _local_name(str(range_cls))
        rng_base = base_table_name_fn(range_cls, rng_local)
        rng_type = classifications.get(str(range_cls), "dimension")
        rng_tbl = gold_table_name_fn(range_cls, rng_local, rng_type)
        bridge.columns.append(GoldColumnDef(
            f"{rng_base}_sk", "INT", "Int64", nullable=False))
        bridge.fk_constraints.append(
            (f"{rng_base}_sk", f"{schema_name}.{rng_tbl}",
             f"{rng_base}_sk", f"{_camel_to_snake(_local_name(str(prop)))}_range"))

        bridges.append(bridge)

    return bridges


# ---------------------------------------------------------------------------
# TMDL renderers
# ---------------------------------------------------------------------------

def _render_tmdl_definition(schema: str, domain: str, meta: dict) -> str:
    """Render TMDL model definition file."""
    lines = [
        f"/// Gold semantic model: {schema}",
        f"/// Domain: {domain}",
    ]
    if meta.get("toolkit_version"):
        lines.append(f"/// Toolkit version: {meta['toolkit_version']}")
    if meta.get("generated_at"):
        lines.append(f"/// Generated at: {meta['generated_at']}")
    lines.extend([
        "",
        "model Model",
        f"\tculture: en-US",
        f"\tdataAccessOptions",
        f"\t\tlegacyRedirects",
        f"\t\treturnErrorValuesAsNull",
        "",
        f"\tannotation __PBI_TimeIntelligenceEnabled = 0",
        "",
    ])
    return "\n".join(lines)


def _render_tmdl_table(tbl: GoldTableDef, schema: str) -> str:
    """Render TMDL table definition."""
    lines = [
        f"/// {tbl.table_type.capitalize()}: {tbl.source_class_label or tbl.name}",
        f"table {tbl.name}",
        f"\tlineageTag: {_tmdl_guid(tbl.name)}",
        "",
    ]

    # Physical columns
    for col in tbl.columns:
        if col.is_measure:
            continue
        is_key = col.name == tbl.pk_column
        lines.append(f"\tcolumn {col.name}")
        lines.append(f"\t\tdataType: {col.tmdl_type}")
        lines.append(f"\t\tformatString: 0")
        lines.append(f"\t\tlineageTag: {_tmdl_guid(f'{tbl.name}.{col.name}')}")
        if is_key:
            lines.append(f"\t\tisKey")
            lines.append(f"\t\tisHidden")
        lines.append(f"\t\tsummarizeBy: none")
        lines.append(f"\t\tsourceColumn: {col.name}")
        if col.comment:
            safe_desc = col.comment.replace('"', '\\"')
            lines.append(f'\t\tannotation PBI_Description = "{safe_desc}"')
        lines.append("")

    # Measures
    for m in tbl.measures:
        lines.append(f"\tmeasure '{m.comment or m.name}' = {m.measure_expr}")
        lines.append(f"\t\tformatString: {m.measure_format}")
        lines.append(f"\t\tlineageTag: {_tmdl_guid(f'{tbl.name}.m.{m.name}')}")
        if m.comment:
            safe_desc = m.comment.replace('"', '\\"')
            lines.append(f'\t\tdescription: "{safe_desc}"')
        lines.append("")

    # Hierarchies
    for h_name, h_cols in tbl.hierarchies.items():
        lines.append(f"\thierarchy '{h_name}'")
        lines.append(f"\t\tlineageTag: {_tmdl_guid(f'{tbl.name}.h.{h_name}')}")
        lines.append("")
        for i, (level, col_name, _) in enumerate(h_cols):
            lines.append(f"\t\tlevel {col_name}")
            lines.append(
                f"\t\t\tlineageTag: "
                f"{_tmdl_guid(f'{tbl.name}.h.{h_name}.{col_name}')}")
            lines.append(f"\t\t\tcolumn: {col_name}")
            lines.append("")

    # Partition (source query)
    lines.append(f"\tpartition {tbl.name} = m")
    lines.append(f"\t\tmode: directLake")
    lines.append(f"\t\tsource")
    lines.append(f'\t\t\tentityName: "{schema}.{tbl.name}"')
    lines.append(f'\t\t\tschemaName: "{schema}"')
    lines.append("")

    return "\n".join(lines)


def _render_tmdl_relationships(tables: list[GoldTableDef], schema: str) -> str:
    """Render TMDL relationships file."""
    lines = [
        f"/// Star schema relationships: {schema}",
        "",
    ]
    rel_idx = 0
    for tbl in tables:
        for col, ref_full, ref_col, label in tbl.fk_constraints:
            ref_tbl_name = ref_full.split(".")[-1]
            lines.append(
                f"relationship {_tmdl_guid(f'rel.{tbl.name}.{col}.{rel_idx}')}")
            lines.append(f"\tjoinOnDateBehavior: datePartOnly")
            lines.append(
                f"\tfromColumn: {tbl.name}.{col}")
            lines.append(
                f"\ttoColumn: {ref_tbl_name}.{ref_col}")
            lines.append("")
            rel_idx += 1

    return "\n".join(lines)


def _render_tmdl_rls_roles(tables: list[GoldTableDef], schema: str) -> str:
    """Render TMDL RLS roles for GDPR dimensions (G4) and OLS column restrictions."""
    lines = [
        f"/// Row-Level Security roles: {schema}",
        "",
    ]
    has_roles = False

    # RLS roles from GDPR satellites (G4)
    for tbl in tables:
        if tbl.is_gdpr and tbl.gdpr_parent_table:
            has_roles = True
            role_name = f"Restrict_{tbl.name}"
            lines.append(f"role '{role_name}'")
            lines.append(f"\tmodelPermission: read")
            lines.append("")
            lines.append(f"\ttablePermission {tbl.name}")
            lines.append(
                f'\t\tfilterExpression: [is_authorized] = TRUE()')
            lines.append("")

    # OLS roles for columns marked with olsRestricted
    ols_columns: list[tuple[str, str]] = []
    for tbl in tables:
        for col in tbl.columns:
            if col.ols_restricted:
                ols_columns.append((tbl.name, col.name))

    if ols_columns:
        has_roles = True
        lines.append(f"/// Object-Level Security roles: {schema}")
        lines.append("")
        lines.append("role 'RestrictedColumns'")
        lines.append("\tmodelPermission: read")
        lines.append("")
        for tbl_name, col_name in ols_columns:
            lines.append(f"\tcolumnPermission {tbl_name}.{col_name}")
            lines.append(f"\t\tmetadataPermission: none")
            lines.append("")

    return "\n".join(lines) if has_roles else ""


def _render_tmdl_perspectives(tables: list[GoldTableDef], schema: str) -> str:
    """Render TMDL perspective blocks from kairos-ext:perspective annotations."""
    # Collect all perspectives and their associated tables
    perspective_tables: dict[str, list[str]] = {}
    for tbl in tables:
        for p in tbl.perspectives:
            perspective_tables.setdefault(p, []).append(tbl.name)

    if not perspective_tables:
        return ""

    lines = [
        f"/// Perspectives: {schema}",
        "",
    ]
    for name, tbl_names in sorted(perspective_tables.items()):
        lines.append(f"perspective '{name}'")
        lines.append("")
        for tbl_name in sorted(tbl_names):
            lines.append(f"\tperspectiveTable {tbl_name}")
            lines.append("")
        lines.append("")

    return "\n".join(lines)


def _render_tmdl_calculation_group(schema: str, meta: dict) -> str:
    """Render a time-intelligence calculation group scaffold.

    Generated when ``kairos-ext:generateTimeIntelligence = true`` is set on
    the ontology.  Produces common time-intelligence calculation items (YTD,
    QTD, MTD, PY, YoY%) that Power BI authors can customize.
    """
    lines = [
        f"/// Time Intelligence calculation group: {schema}",
    ]
    if meta.get("toolkit_version"):
        lines.append(f"/// Toolkit version: {meta['toolkit_version']}")
    lines.extend([
        "",
        "table 'Time Intelligence'",
        f"\tlineageTag: {_tmdl_guid(f'{schema}.calcgroup.timeintel')}",
        "",
        "\tcalculationGroup",
        "",
        "\t\tcalculationItem 'Current' = SELECTEDMEASURE()",
        f"\t\t\tlineageTag: {_tmdl_guid(f'{schema}.ci.current')}",
        "",
        "\t\tcalculationItem YTD = CALCULATE(SELECTEDMEASURE(), "
        "DATESYTD('dim_date'[full_date]))",
        f"\t\t\tlineageTag: {_tmdl_guid(f'{schema}.ci.ytd')}",
        "",
        "\t\tcalculationItem QTD = CALCULATE(SELECTEDMEASURE(), "
        "DATESQTD('dim_date'[full_date]))",
        f"\t\t\tlineageTag: {_tmdl_guid(f'{schema}.ci.qtd')}",
        "",
        "\t\tcalculationItem MTD = CALCULATE(SELECTEDMEASURE(), "
        "DATESMTD('dim_date'[full_date]))",
        f"\t\t\tlineageTag: {_tmdl_guid(f'{schema}.ci.mtd')}",
        "",
        "\t\tcalculationItem PY = CALCULATE(SELECTEDMEASURE(), "
        "SAMEPERIODLASTYEAR('dim_date'[full_date]))",
        f"\t\t\tlineageTag: {_tmdl_guid(f'{schema}.ci.py')}",
        "",
        "\t\tcalculationItem 'YoY %' = ",
        "\t\t\tVAR _current = SELECTEDMEASURE()",
        "\t\t\tVAR _py = CALCULATE(SELECTEDMEASURE(), "
        "SAMEPERIODLASTYEAR('dim_date'[full_date]))",
        "\t\t\tRETURN IF(NOT ISBLANK(_py), DIVIDE(_current - _py, _py))",
        f"\t\t\tformatString: 0.0%",
        f"\t\t\tlineageTag: {_tmdl_guid(f'{schema}.ci.yoy')}",
        "",
    ])
    return "\n".join(lines)


def _tmdl_guid(seed: str) -> str:
    """Generate a deterministic GUID-like tag from a seed string."""
    import hashlib
    h = hashlib.md5(seed.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# ---------------------------------------------------------------------------
# DAX measures renderer
# ---------------------------------------------------------------------------

def _render_dax_measures(
    measures: list[tuple[str, GoldColumnDef]],
    domain: str,
    meta: dict,
) -> str:
    """Render DAX measures file."""
    if not measures:
        return ""
    lines = [
        f"// Gold layer DAX measures: {domain}",
    ]
    if meta.get("toolkit_version"):
        lines.append(f"// Toolkit version: {meta['toolkit_version']}")
    if meta.get("generated_at"):
        lines.append(f"// Generated at: {meta['generated_at']}")
    lines.append("")

    for tbl_name, m in measures:
        label = m.comment or m.name
        lines.append(f"// Table: {tbl_name}")
        lines.append(f"{label} = {m.measure_expr}")
        lines.append(f"    // Format: {m.measure_format}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Master gold ERD
# ---------------------------------------------------------------------------

def generate_master_gold_erd(
    gold_output_path: Path, hub_name: str = "master",
) -> Optional[str]:
    """Merge all per-domain gold ERD files into one cross-domain master ERD.

    Reads ``{domain}/{domain}-gold-erd.mmd`` files under *gold_output_path*,
    strips per-file headers, and re-emits under a single ``erDiagram`` block.
    """
    if not gold_output_path.exists():
        return None
    domain_erds: list[tuple[str, str]] = []
    for mmd_file in sorted(gold_output_path.rglob("*-gold-erd.mmd")):
        if mmd_file.name == "master-gold-erd.mmd":
            continue
        domain = mmd_file.parent.name
        content = mmd_file.read_text(encoding="utf-8")
        body_lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "erDiagram" or stripped.startswith(
                    "%% Gold Star Schema ERD:"):
                continue
            body_lines.append(line)
        body = "\n".join(body_lines).strip()
        if body:
            domain_erds.append((domain, body))

    if not domain_erds:
        return None

    lines = [
        "erDiagram",
        f"    %% Master Gold Star Schema ERD — {hub_name} (all domains)",
        "",
    ]
    for domain, body in domain_erds:
        lines.append(f"    %% --- Domain: {domain} ---")
        lines.append(body)
        lines.append("")

    return "\n".join(lines)
