"""Silver Layer Projector — generate MS Fabric / Delta Lake silver DDL, FK scripts,
and Mermaid ERD from OWL ontologies annotated with kairos-ext: projection extensions.

Rules R1–R15 are implemented here.  Projection annotations live in a separate
``*-silver-ext.ttl`` file that is merged with the domain ontology at generation time.

Namespace:  kairos-ext:  https://kairos.cnext.eu/ext#
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace, URIRef, Literal, XSD
from rdflib.namespace import OWL, RDF, RDFS

# ---------------------------------------------------------------------------
# kairos-ext namespace
# ---------------------------------------------------------------------------
KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")

# ---------------------------------------------------------------------------
# XSD → SQL type mapping (MS Fabric / T-SQL / Delta Lake compatible)
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
    str(XSD.float): "FLOAT",
    str(XSD.double): "FLOAT",
    str(XSD.boolean): "BIT",
    str(XSD.date): "DATE",
    str(XSD.dateTime): "DATETIME2",
    str(XSD.time): "TIME",
    str(XSD.gYear): "INT",
    str(XSD.anyURI): "NVARCHAR(2048)",
}

# Default audit envelope columns (R9)
_DEFAULT_AUDIT = (
    "_created_at DATETIME2, _updated_at DATETIME2, "
    "_source_system NVARCHAR(128), _load_date DATE, _batch_id NVARCHAR(64)"
)


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase or camelCase to snake_case (R4)."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _mmd_type(sql_type: str) -> str:
    """Sanitize a SQL type for use in a Mermaid erDiagram attribute.

    Mermaid ATTRIBUTE_WORD only allows ``[A-Za-z0-9_]``.
    Examples:
      DECIMAL(18,4)   → DECIMAL_18_4
      NVARCHAR(MAX)   → NVARCHAR_MAX
      NVARCHAR(2048)  → NVARCHAR_2048
      DATETIME2       → DATETIME2   (unchanged)
    """
    return re.sub(r"[^A-Za-z0-9_]", "_", sql_type).strip("_")


def _local_name(uri: str) -> str:
    """Extract local name from a URI."""
    if "#" in uri:
        return uri.rsplit("#", 1)[1]
    return uri.rsplit("/", 1)[1]


def _str_val(graph: Graph, subject: URIRef, predicate: URIRef, default: str = "") -> str:
    val = graph.value(subject, predicate)
    return str(val) if val is not None else default


def _bool_val(graph: Graph, subject: URIRef, predicate: URIRef, default: bool = False) -> bool:
    val = graph.value(subject, predicate)
    if val is None:
        return default
    return str(val).lower() in ("true", "1", "yes")


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
        lines = [f"CREATE TABLE {self.full_name} ("]
        col_lines = [c.ddl_fragment() for c in self.columns]
        # Primary key constraint
        if self.pk_column:
            col_lines.append(f"    CONSTRAINT pk_{self.name} PRIMARY KEY ({self.pk_column})")
        lines.append(",\n".join(col_lines))
        lines.append(")")
        # Partitioning / clustering
        if self.partition_by:
            lines.append(f"PARTITIONED BY ({self.partition_by})")
        if self.cluster_by:
            lines.append(f"CLUSTER BY ({self.cluster_by})")
        return "\n".join(lines) + ";"

    def render_alter(self) -> list[str]:
        stmts = []
        for col in self.unique_columns:
            stmts.append(
                f"ALTER TABLE {self.full_name}\n"
                f"    ADD CONSTRAINT u_{self.name}_{col} UNIQUE ({col});"
            )
        for col, ref_table, ref_col, *_label in self.fk_constraints:
            stmts.append(
                f"ALTER TABLE {self.full_name}\n"
                f"    ADD CONSTRAINT fk_{self.name}_{col}"
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
) -> dict[str, str]:
    """Generate silver layer DDL, ALTER script, and Mermaid ERD.

    Args:
        classes: Pre-extracted list of ``{uri, name, label, comment}`` dicts.
        graph: Loaded domain ontology graph.
        namespace: Domain namespace URI string.
        shapes_dir: Optional SHACL shapes directory (for NOT NULL inference, R11).
        ontology_name: Domain name (used for filenames and default schema).
        projection_ext_path: Optional path to ``*-silver-ext.ttl`` annotation file.

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
            return _camel_to_snake(local)
        return local.lower()

    # Build class map: uri → TableDef
    tables: dict[str, TableDef] = {}
    class_uris = {c["uri"] for c in classes}

    for cls_info in classes:
        cls_uri = URIRef(cls_info["uri"])
        local = cls_info["name"]
        tbl_name = table_name_for(cls_uri, local)

        # Detect table type flags
        is_ref = _bool_val(merged, cls_uri, KAIROS_EXT.isReferenceData, False)
        gdpr_parent = merged.value(cls_uri, KAIROS_EXT.gdprSatelliteOf)
        is_gdpr = gdpr_parent is not None
        scd = _str_val(merged, cls_uri, KAIROS_EXT.scdType, "1" if is_ref else "2")

        # Reference data → prefix with ref_
        if is_ref:
            tbl_name = f"ref_{tbl_name}" if not tbl_name.startswith("ref_") else tbl_name

        tbl = TableDef(tbl_name, schema_name)
        tbl.is_reference = is_ref
        tbl.partition_by = _str_val(merged, cls_uri, KAIROS_EXT.partitionBy) or None
        tbl.cluster_by = _str_val(merged, cls_uri, KAIROS_EXT.clusterBy) or None

        # ----------------------------------------------------------------
        # Determine inheritance: is this a subtype?
        # ----------------------------------------------------------------
        supertype_uri = None
        for parent in merged.objects(cls_uri, RDFS.subClassOf):
            if isinstance(parent, URIRef) and str(parent) in class_uris:
                supertype_uri = parent
                break
        is_subtype = supertype_uri is not None

        # ----------------------------------------------------------------
        # Column ordering: SK → IRI → FK → discriminator → data → SCD → audit
        # ----------------------------------------------------------------

        # 1. Surrogate key (R2) — skip for GDPR satellites and subtypes (class-per-table)
        if not is_gdpr and not is_subtype:
            sk_col = ColumnDef(f"{tbl_name}_sk", "NVARCHAR(36)", nullable=False,
                               comment="Surrogate key (UUID)")
            tbl.columns.append(sk_col)
            tbl.pk_column = f"{tbl_name}_sk"
        elif is_subtype:
            # Subtype: FK to supertype table acts as PK (R6 class-per-table)
            parent_local = _local_name(str(supertype_uri))
            parent_tbl = table_name_for(supertype_uri, parent_local)
            sk_col = ColumnDef(f"{parent_tbl}_sk", "NVARCHAR(36)", nullable=False,
                               comment=f"PK/FK → {parent_tbl} (joined-table inheritance)")
            tbl.columns.append(sk_col)
            tbl.pk_column = f"{parent_tbl}_sk"
            tbl.fk_constraints.append(
                (f"{parent_tbl}_sk", f"{schema_name}.{parent_tbl}",
                 f"{parent_tbl}_sk", "inherits")
            )
            tbl.table_type = "subtype"
        elif is_gdpr:
            # GDPR satellite: PK = FK to parent (R7)
            parent_local = _local_name(str(gdpr_parent))
            parent_tbl = table_name_for(gdpr_parent, parent_local)
            sk_col = ColumnDef(f"{parent_tbl}_sk", "NVARCHAR(36)", nullable=False,
                               comment=f"PK/FK → {parent_tbl} (GDPR satellite)")
            tbl.columns.append(sk_col)
            tbl.pk_column = f"{parent_tbl}_sk"
            tbl.fk_constraints.append(
                (f"{parent_tbl}_sk", f"{schema_name}.{parent_tbl}",
                 f"{parent_tbl}_sk", "gdpr_satellite_of")
            )
            tbl.table_type = "satellite"

        # 2. IRI lineage column (R3) — skip for subtypes, ref, and GDPR satellites
        if include_iri and not is_subtype and not is_gdpr and not is_ref:
            iri_col = ColumnDef(f"{tbl_name}_iri", "NVARCHAR(2048)", nullable=False,
                                comment="OWL IRI lineage")
            tbl.columns.append(iri_col)
            tbl.unique_columns.append(f"{tbl_name}_iri")

        # 3. FK columns from max-cardinality-1 object properties (R12)
        _add_object_property_fk_cols(merged, cls_uri, tbl, table_name_for, schema_name,
                                     class_uris, naming_conv)

        # 4. Discriminator column (R6 — discriminator strategy)
        disc_col = _str_val(merged, cls_uri, KAIROS_EXT.discriminatorColumn)
        if disc_col:
            tbl.columns.append(ColumnDef(disc_col, "NVARCHAR(64)", nullable=False,
                                         comment="Type discriminator"))

        # 5. Data properties (business columns)
        _add_data_properties(merged, cls_uri, tbl, shacl_graph, naming_conv)

        # 6. SCD Type 2 columns (R5)
        if scd == "2":
            tbl.columns.append(ColumnDef("valid_from", "DATE", nullable=False))
            tbl.columns.append(ColumnDef("valid_to", "DATE", nullable=True,
                                         comment="NULL = current record"))
            tbl.columns.append(ColumnDef("is_current", "BIT", nullable=False,
                                         comment="DEFAULT 1"))

        # 7. Audit envelope (R9) — skip for reference tables
        if not is_ref:
            tbl.columns.extend(audit_cols)

        if is_ref:
            tbl.table_type = "reference"

        tables[cls_info["uri"]] = tbl

    # ----------------------------------------------------------------
    # Junction tables from many-to-many object properties (R13)
    # ----------------------------------------------------------------
    junction_tables = _build_junction_tables(merged, class_uris, tables, schema_name,
                                             table_name_for, audit_cols)

    # ----------------------------------------------------------------
    # Sort tables per ordering convention
    # ----------------------------------------------------------------
    all_tables = _sort_tables(list(tables.values()) + junction_tables)

    # ----------------------------------------------------------------
    # Render DDL
    # ----------------------------------------------------------------
    ddl_lines = [
        f"-- Silver layer DDL: {schema_name}",
        f"-- Domain: {ontology_name}",
        f"-- Generated by kairos-ontology-toolkit (silver projector)",
        "",
        f"-- Schema",
        f"CREATE SCHEMA IF NOT EXISTS {schema_name};",
        "",
    ]
    for tbl in all_tables:
        ddl_lines.append(f"-- {tbl.table_type.upper()}: {tbl.full_name}")
        ddl_lines.append(tbl.render_create())
        ddl_lines.append("")

    # ----------------------------------------------------------------
    # Render ALTER TABLE script
    # ----------------------------------------------------------------
    alter_lines = [
        f"-- Silver layer constraints: {schema_name}",
        f"-- Domain: {ontology_name}",
        "",
    ]
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
        "",
    ]
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

    domain_dir = f"{ontology_name}/"
    return {
        f"{domain_dir}{ontology_name}-ddl.sql": "\n".join(ddl_lines),
        f"{domain_dir}{ontology_name}-alter.sql": "\n".join(alter_lines),
        f"{domain_dir}{ontology_name}-erd.mmd": "\n".join(mmd_lines),
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


def _parse_audit_envelope(audit_str: str) -> list[ColumnDef]:
    """Parse comma-separated ``name TYPE`` audit column definitions.

    Commas inside parentheses (e.g. ``DECIMAL(18, 4)``) are preserved.
    """
    import re
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
                if min_count is not None and int(str(min_count)) >= 1:
                    return True
    return False


def _add_data_properties(graph: Graph, cls_uri: URIRef, tbl: TableDef,
                          shacl_graph: Optional[Graph], naming_conv: str) -> None:
    """Add OWL DatatypeProperty columns to the table (business columns, R4, R11)."""
    existing_col_names = {c.name for c in tbl.columns}
    for prop in graph.subjects(RDF.type, OWL.DatatypeProperty):
        domain = graph.value(prop, RDFS.domain)
        if domain != cls_uri:
            continue
        range_uri = graph.value(prop, RDFS.range)
        sql_type = XSD_TO_SQL.get(str(range_uri), "NVARCHAR(MAX)") if range_uri else "NVARCHAR(MAX)"
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
            continue
        existing_col_names.add(col_name)
        # Nullability: explicit annotation wins, then SHACL, then nullable (R11)
        nullable_ann = graph.value(prop, KAIROS_EXT.nullable)
        if nullable_ann is not None:
            nullable = str(nullable_ann).lower() not in ("false", "0")
        else:
            nullable = not _not_null_from_shacl(shacl_graph, prop, cls_uri)
        label = _str_val(graph, prop, RDFS.label, "")
        tbl.columns.append(ColumnDef(col_name, sql_type, nullable=nullable, comment=label))


def _add_object_property_fk_cols(
    graph: Graph, cls_uri: URIRef, tbl: TableDef,
    table_name_for, schema_name: str, class_uris: set[str], naming_conv: str,
) -> None:
    """Add FK columns from max-cardinality-1 object properties (R12).

    A property qualifies as a FK column when ANY of:
      - it has an explicit ``kairos-ext:silverColumnName`` annotation,
      - it is declared ``owl:FunctionalProperty``,
      - the domain class has an ``owl:maxQualifiedCardinality 1`` or
        ``owl:maxCardinality 1`` restriction on the property.

    Junction-table properties (R13) are always skipped.
    """
    for prop in graph.subjects(RDF.type, OWL.ObjectProperty):
        domain = graph.value(prop, RDFS.domain)
        if domain != cls_uri:
            continue
        # Skip if this property has a junctionTableName (R13)
        if graph.value(prop, KAIROS_EXT.junctionTableName):
            continue
        # Determine if this is a many-to-one FK column
        has_explicit_col = _str_val(graph, prop, KAIROS_EXT.silverColumnName) is not None
        is_functional = (prop, RDF.type, OWL.FunctionalProperty) in graph
        if not has_explicit_col and not is_functional \
                and not _has_max_cardinality_1(graph, cls_uri, prop):
            continue
        range_cls = graph.value(prop, RDFS.range)
        if range_cls is None or str(range_cls) not in class_uris:
            continue
        range_local = _local_name(str(range_cls))
        range_tbl = table_name_for(range_cls, range_local)
        col_name_override = _str_val(graph, prop, KAIROS_EXT.silverColumnName)
        col_name = col_name_override or f"{range_tbl}_sk"
        # Conditional nullable (R14)
        cond_on = _str_val(graph, prop, KAIROS_EXT.conditionalOnType)
        comment = f"nullable: active when type IN ({cond_on})" if cond_on else ""
        prop_label = _camel_to_snake(_local_name(str(prop)))
        tbl.columns.append(ColumnDef(col_name, "NVARCHAR(36)", nullable=True, comment=comment))
        tbl.fk_constraints.append(
            (col_name, f"{schema_name}.{range_tbl}", f"{range_tbl}_sk", prop_label)
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
        if str(domain_cls) not in class_uris or str(range_cls) not in class_uris:
            continue

        dom_local = _local_name(str(domain_cls))
        rng_local = _local_name(str(range_cls))
        dom_tbl = table_name_for(domain_cls, dom_local)
        rng_tbl = table_name_for(range_cls, rng_local)

        jct = TableDef(jct_name, schema_name)
        jct.table_type = "satellite"
        # SK
        jct.columns.append(ColumnDef(f"{jct_name}_sk", "NVARCHAR(36)", nullable=False,
                                      comment="Surrogate key (UUID)"))
        jct.pk_column = f"{jct_name}_sk"
        prop_label = _camel_to_snake(_local_name(str(prop)))
        # FK to domain
        jct.columns.append(ColumnDef(f"{dom_tbl}_sk", "NVARCHAR(36)", nullable=False))
        jct.fk_constraints.append(
            (f"{dom_tbl}_sk", f"{schema_name}.{dom_tbl}", f"{dom_tbl}_sk",
             f"{prop_label}_domain")
        )
        # FK to range
        jct.columns.append(ColumnDef(f"{rng_tbl}_sk", "NVARCHAR(36)", nullable=False))
        jct.fk_constraints.append(
            (f"{rng_tbl}_sk", f"{schema_name}.{rng_tbl}", f"{rng_tbl}_sk",
             f"{prop_label}_range")
        )
        # SCD 2
        jct.columns.extend([
            ColumnDef("valid_from", "DATE", nullable=False),
            ColumnDef("valid_to", "DATE", nullable=True, comment="NULL = current"),
            ColumnDef("is_current", "BIT", nullable=False, comment="DEFAULT 1"),
        ])
        # Audit
        jct.columns.extend(audit_cols)
        junctions.append(jct)

    return junctions


def _sort_tables(tables: list[TableDef]) -> list[TableDef]:
    """Sort tables per ordering convention: root → subtype → satellite → reference."""
    order = {"root": 0, "subtype": 1, "satellite": 2, "reference": 3}
    return sorted(tables, key=lambda t: order.get(t.table_type, 0))


def generate_master_erd(silver_output_path: Path, hub_name: str = "master") -> Optional[str]:
    """Merge all per-domain ``*-erd.mmd`` files into one cross-domain master ERD.

    Reads every ``<domain>/<domain>-erd.mmd`` file under *silver_output_path*,
    strips the per-file ``erDiagram`` header and domain comment, then re-emits
    them under a single ``erDiagram`` block with a section comment per domain.

    Args:
        silver_output_path: Path to the ``output/silver/`` directory.
        hub_name: Label used in the master ERD header comment.

    Returns:
        Mermaid ERD string, or ``None`` if no domain ERDs were found.
    """
    domain_erds: list[tuple[str, str]] = []
    for mmd_file in sorted(silver_output_path.rglob("*-erd.mmd")):
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

