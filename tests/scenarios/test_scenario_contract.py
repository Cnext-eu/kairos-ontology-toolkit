# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Contract/round-trip QA tests for dbt projection completeness.

These tests parse the acme-hub SKOS mappings as ground truth, project dbt
artifacts, and validate that the generated SQL/YAML is complete and consistent
with the mapping configuration.

Run with: py -m pytest -m slow
(Excluded from default test runs by pyproject.toml addopts.)
"""

import re

import pytest
import yaml
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, OWL

from .conftest import MAPPINGS_DIR, HUB_ROOT

SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
KAIROS_MAP = Namespace("https://kairos.cnext.eu/mapping#")
KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")

# System-generated columns that don't come from SKOS mappings
SYSTEM_COLUMNS = {
    "_sk", "_iri", "_type", "_source_system", "_source_record_id", "_loaded_at",
    "_row_hash", "valid_from", "valid_to", "is_current",
}


def _is_system_column(col_name: str) -> bool:
    """Check if a column name is a system-generated column (SK, IRI, discriminator, etc.)."""
    if any(col_name.endswith(suffix) for suffix in ("_sk", "_iri", "_fk", "_ref")):
        return True
    if col_name in SYSTEM_COLUMNS:
        return True
    # Discriminator columns end with _type
    if col_name.endswith("_type") and not col_name.startswith("type_"):
        return True
    return False


def _load_mappings_graph() -> Graph:
    """Load all SKOS mapping files into a single graph."""
    g = Graph()
    for ttl_file in MAPPINGS_DIR.glob("*.ttl"):
        g.parse(ttl_file, format="turtle")
    return g


def _extract_column_maps(g: Graph, domain_ns: str) -> dict[str, set[str]]:
    """Extract column-level mappings grouped by target class.

    Returns: {class_local_name: {property_local_name, ...}}
    Excludes properties that are owl:ObjectProperty (FK columns get different names).
    """
    # Load full ontology graph to check property types
    ontology_g = Graph()
    ont_dir = HUB_ROOT / "model" / "ontologies"
    for ttl_file in ont_dir.rglob("*.ttl"):
        ontology_g.parse(ttl_file, format="turtle")
    ref_dir = HUB_ROOT / "model" / "reference-models"
    if ref_dir.exists():
        for ttl_file in ref_dir.rglob("*.ttl"):
            ontology_g.parse(ttl_file, format="turtle")

    # Identify object properties (FK relations)
    object_props = {
        str(s) for s, _, _ in ontology_g.triples((None, RDF.type, OWL.ObjectProperty))
    }

    class_columns: dict[str, set[str]] = {}

    # Find all column-level mappings (source_col → domain_property)
    for match_pred in (SKOS.exactMatch, SKOS.closeMatch, SKOS.narrowMatch):
        for source_col, _, target_prop in g.triples((None, match_pred, None)):
            target_str = str(target_prop)
            if not target_str.startswith(domain_ns):
                continue

            # Table-level mappings have mappingType; skip those
            mapping_type = g.value(source_col, KAIROS_MAP.mappingType)
            if mapping_type:
                continue

            # Skip object properties — they become FK columns with different names
            if target_str in object_props:
                continue

            # This is a data property column-level mapping
            prop_local = target_str.replace(domain_ns, "")
            class_columns.setdefault("_all_", set()).add(prop_local)

    return class_columns


def _extract_table_maps(g: Graph, domain_ns: str) -> dict[str, list[str]]:
    """Extract table-level mappings: {class_local_name: [source_table_names]}."""
    class_tables: dict[str, list[str]] = {}

    for match_pred in (SKOS.exactMatch, SKOS.closeMatch, SKOS.narrowMatch):
        for source_tbl, _, target_cls in g.triples((None, match_pred, None)):
            target_str = str(target_cls)
            if not target_str.startswith(domain_ns):
                continue

            mapping_type = g.value(source_tbl, KAIROS_MAP.mappingType)
            if not mapping_type:
                continue  # Not a table-level mapping

            cls_local = target_str.replace(domain_ns, "")
            class_tables.setdefault(cls_local, []).append(str(source_tbl))

    return class_tables


def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case."""
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


def _load_silver_column_overrides(domain: str) -> dict[str, str]:
    """Load silverColumnName overrides: {property_local_name: override_name}.

    Reads the silver-ext file for the given domain and returns a mapping from
    property local names to their declared silverColumnName values.
    """
    ext_path = HUB_ROOT / "model" / "extensions" / f"{domain}-silver-ext.ttl"
    if not ext_path.exists():
        return {}
    g = Graph()
    g.parse(ext_path, format="turtle")
    overrides: dict[str, str] = {}
    for subj, _, col_name in g.triples((None, KAIROS_EXT.silverColumnName, None)):
        prop_local = str(subj).split("#")[-1].split("/")[-1]
        overrides[prop_local] = str(col_name)
    return overrides


def _resolve_expected_col_name(prop_local: str, overrides: dict[str, str]) -> str:
    """Resolve expected column name using silverColumnName override or snake_case."""
    return overrides.get(prop_local, _camel_to_snake(prop_local))


def _find_artifact(artifacts: dict, suffix: str) -> str | None:
    """Find artifact key ending with suffix."""
    return next((k for k in artifacts if k.endswith(suffix)), None)


def _get_sql_columns(sql: str) -> set[str]:
    """Extract target column names from SQL 'expression as column_name' patterns.

    Only matches column aliases at the SELECT level (followed by comma, newline,
    or end-of-line comment), not type names inside CAST(...AS TYPE).
    """
    # Match "as column_name" that is NOT inside a CAST (preceded by closing paren
    # or quote, or at line-level indentation). Use the pattern:
    # "as col_name" followed by comma, whitespace, comment, or end-of-line.
    pattern = r"^\s+.*?\bas\s+([a-z_][a-z0-9_]*)\s*[,\n]"
    # Only inspect SELECT-list lines; FROM/JOIN aliases are not output columns.
    select_lines = []
    in_select = False
    for line in sql.lower().splitlines():
        if re.match(r"^\s*select\b", line):
            in_select = True
            continue
        if in_select and re.match(r"^\s*from\b", line):
            in_select = False
            continue
        if in_select:
            select_lines.append(line)
    select_sql = "\n".join(select_lines)
    matches = re.findall(pattern, select_sql, re.MULTILINE)

    # Also catch last column in a SELECT list (no trailing comma).
    pattern2 = r"^\s+.*?\bas\s+([a-z_][a-z0-9_]*)\s*(?:--|$)"
    matches2 = re.findall(pattern2, select_sql, re.MULTILINE)

    # Filter out SQL type keywords that get false-matched
    sql_types = {
        "string", "boolean", "varchar", "int", "integer", "bigint",
        "smallint", "float", "double", "decimal", "date", "timestamp",
        "bit", "text", "binary", "number",
    }
    result = set(matches + matches2) - sql_types
    return result


# ===========================================================================
# Tests
# ===========================================================================


class TestMappingToSqlCompleteness:
    """Every SKOS-mapped column should appear in the generated dbt SQL."""

    def test_client_mapped_columns_present(self, client_dbt_artifacts):
        """All client domain mapped properties should appear in SQL models."""
        g = _load_mappings_graph()
        domain_ns = "https://acme.example/ontology/client#"
        col_maps = _extract_column_maps(g, domain_ns)
        all_props = col_maps.get("_all_", set())
        overrides = _load_silver_column_overrides("client")

        # Collect all column names across all SQL artifacts
        all_sql_columns: set[str] = set()
        for key, content in client_dbt_artifacts.items():
            if key.endswith(".sql"):
                all_sql_columns.update(_get_sql_columns(content))

        # Also collect full SQL text for substring matching
        all_sql_text = "\n".join(
            c for k, c in client_dbt_artifacts.items() if k.endswith(".sql")
        ).lower()

        # Each mapped property should appear using silverColumnName or snake_case
        missing = []
        for prop in all_props:
            col_name = _resolve_expected_col_name(prop, overrides)
            # Accept exact match, or FK-style variants (_sk, _fk suffix)
            if (col_name not in all_sql_columns
                    and f"{col_name}_sk" not in all_sql_columns
                    and f"{col_name}_fk" not in all_sql_columns
                    and col_name not in all_sql_text):
                missing.append(f"{prop} (expected: {col_name})")

        assert not missing, (
            "Mapped properties missing from dbt SQL:\n"
            + "\n".join(f"  - {m}" for m in sorted(missing))
        )

    def test_invoice_mapped_columns_present(self, invoice_dbt_artifacts):
        """All invoice domain mapped properties should appear in SQL models."""
        g = _load_mappings_graph()
        domain_ns = "https://acme.example/ontology/invoice#"
        col_maps = _extract_column_maps(g, domain_ns)
        all_props = col_maps.get("_all_", set())

        all_sql_columns: set[str] = set()
        for key, content in invoice_dbt_artifacts.items():
            if key.endswith(".sql"):
                all_sql_columns.update(_get_sql_columns(content))

        # Also collect full SQL text for substring matching (FK columns
        # may have _sk or _fk suffixes)
        all_sql_text = "\n".join(
            c for k, c in invoice_dbt_artifacts.items() if k.endswith(".sql")
        ).lower()

        missing = []
        for prop in all_props:
            snake_name = _camel_to_snake(prop)
            # Accept exact match, or FK-style variants (_sk, _fk suffix)
            if (snake_name not in all_sql_columns
                    and f"{snake_name}_sk" not in all_sql_columns
                    and f"{snake_name}_fk" not in all_sql_columns
                    and snake_name not in all_sql_text):
                missing.append(f"{prop} (expected: {snake_name})")

        assert not missing, (
            "Mapped properties missing from dbt SQL:\n"
            + "\n".join(f"  - {m}" for m in sorted(missing))
        )


class TestSchemaYamlCompleteness:
    """Schema YAML should list all columns present in SQL models."""

    def test_client_yaml_covers_sql_columns(self, client_dbt_artifacts):
        """Every column in the SQL model should have a schema YAML entry."""
        yaml_key = _find_artifact(client_dbt_artifacts, "_models.yml")
        assert yaml_key is not None, "No schema YAML found"
        parsed = yaml.safe_load(client_dbt_artifacts[yaml_key])

        # Build set of all YAML-declared column names per model
        yaml_columns: set[str] = set()
        for model in parsed.get("models", []):
            for col in model.get("columns", []):
                yaml_columns.add(col["name"].lower())

        # Get SQL columns from the union/final models (not per-source views,
        # not dim_date which is internally generated)
        sql_columns: set[str] = set()
        for key, content in client_dbt_artifacts.items():
            if (key.endswith(".sql")
                    and "__from_" not in key
                    and "dim_date" not in key
                    and "macros/" not in key):
                sql_columns.update(_get_sql_columns(content))

        # Filter out system columns
        meaningful_sql_cols = {
            c for c in sql_columns
            if not _is_system_column(c) and not c.startswith("_")
        }

        missing_from_yaml = meaningful_sql_cols - yaml_columns

        assert not missing_from_yaml, (
            "SQL columns missing from schema YAML:\n"
            + "\n".join(f"  - {c}" for c in sorted(missing_from_yaml))
        )


class TestFilterConditionsApplied:
    """Split pattern filter conditions should appear in per-source SQL."""

    def test_client_split_filters_present(self, client_dbt_artifacts):
        """AdminPulse split pattern filters (Type = 0, 1, 2) in per-source SQL."""
        g = _load_mappings_graph()
        domain_ns = "https://acme.example/ontology/client#"

        # Find all filter conditions from mappings
        filters: list[str] = []
        for match_pred in (SKOS.exactMatch, SKOS.closeMatch, SKOS.narrowMatch):
            for source_tbl, _, target_cls in g.triples((None, match_pred, None)):
                if not str(target_cls).startswith(domain_ns):
                    continue
                filter_cond = g.value(source_tbl, KAIROS_MAP.filterCondition)
                if filter_cond:
                    filters.append(str(filter_cond))

        assert len(filters) > 0, "No filter conditions found in mappings"

        # Collect all SQL from per-source models
        all_per_source_sql = ""
        for key, content in client_dbt_artifacts.items():
            if key.endswith(".sql") and "__from_" in key:
                all_per_source_sql += content + "\n"

        # Each filter should appear (with 'source.' prefix stripped)
        missing_filters = []
        for filt in filters:
            # Filter in mapping: "source.Type = 0" → in SQL: "Type = 0"
            clean_filter = filt.replace("source.", "")
            if clean_filter not in all_per_source_sql:
                missing_filters.append(filt)

        assert not missing_filters, (
            "Filter conditions from mappings not found in per-source SQL:\n"
            + "\n".join(f"  - {f}" for f in missing_filters)
        )


class TestNoPhantomColumns:
    """SQL models should not contain columns without a mapping or system origin."""

    def test_client_no_unexplained_columns(self, client_dbt_artifacts):
        """All columns in client SQL models should trace to a mapping or system col."""
        g = _load_mappings_graph()
        domain_ns = "https://acme.example/ontology/client#"
        col_maps = _extract_column_maps(g, domain_ns)
        all_props = col_maps.get("_all_", set())
        overrides = _load_silver_column_overrides("client")

        # Expected column names from mappings (silverColumnName override or snake_case)
        expected_from_mapping = {
            _resolve_expected_col_name(p, overrides) for p in all_props
        }

        # Get all columns from per-source SQL models
        per_source_columns: set[str] = set()
        for key, content in client_dbt_artifacts.items():
            if key.endswith(".sql") and "__from_" in key:
                per_source_columns.update(_get_sql_columns(content))

        # Unexplained = not in mapping AND not a system column
        unexplained = {
            c for c in per_source_columns
            if c not in expected_from_mapping and not _is_system_column(c)
        }

        # Allow FK columns (end with _fk or _sk referencing another entity)
        unexplained = {
            c for c in unexplained
            if not c.endswith("_fk") and not c.endswith("_sk")
            and not c.startswith("_")
        }

        # NOTE: This is an advisory check. Some columns may come from FK
        # inference or derived formulas. We assert but with informative message.
        assert not unexplained, (
            "Columns in SQL with no SKOS mapping or system origin:\n"
            + "\n".join(f"  - {c}" for c in sorted(unexplained))
            + "\n\nThese may be FK columns, derived formulas, or enum labels. "
            "If legitimate, add them to the allowlist in this test."
        )


class TestSilverExtTypesMatchCasts:
    """Silver extension silverDataType annotations should be consistent with SQL output."""

    def test_client_data_types_consistent(self, client_dbt_artifacts):
        """When a CAST is present for an annotated column, it must match silverDataType.

        Not every column gets a CAST — transforms may pass through source values
        directly.  This test verifies:
        1. Every annotated column appears in the SQL output.
        2. Where a CAST/TRY_CAST exists for that column, it uses the declared type.
        """
        # Load silver extension to get type annotations
        ext_path = HUB_ROOT / "model" / "extensions" / "client-silver-ext.ttl"
        if not ext_path.exists():
            pytest.skip("No client silver extension file")

        g = Graph()
        g.parse(ext_path, format="turtle")

        # Collect silverDataType annotations: {property_local_name: type}
        type_annotations: dict[str, str] = {}
        for subj, _, dtype in g.triples((None, KAIROS_EXT.silverDataType, None)):
            prop_name = str(subj).split("#")[-1].split("/")[-1]
            type_annotations[prop_name] = str(dtype)

        if not type_annotations:
            pytest.skip("No silverDataType annotations found")

        overrides = _load_silver_column_overrides("client")

        # Get all SQL content (exclude macros)
        all_sql = ""
        for key, content in client_dbt_artifacts.items():
            if key.endswith(".sql") and "macros/" not in key:
                all_sql += content + "\n"

        # Check 1: Every annotated column should appear as an alias in SQL
        missing_columns = []
        for prop in type_annotations:
            col_name = _resolve_expected_col_name(prop, overrides)
            # Column should appear as "as <col_name>" somewhere in the SQL
            if not re.search(rf"\bas\s+{re.escape(col_name)}\b", all_sql, re.IGNORECASE):
                missing_columns.append(f"{prop} (expected column '{col_name}')")

        assert not missing_columns, (
            "silverDataType-annotated columns missing from SQL output:\n"
            + "\n".join(f"  - {c}" for c in sorted(missing_columns))
        )

        # Check 2: Where CAST exists for a column, verify it uses the correct type
        type_mismatches = []
        for prop, expected_type in type_annotations.items():
            col_name = _resolve_expected_col_name(prop, overrides)
            # Find any CAST(...AS <TYPE>) ... as <col_name> pattern
            cast_pattern = (
                rf"(?i)(?:cast|try_cast)\s*\(.*?\bas\s+(\w+)\s*\)"
                rf".*?\bas\s+{re.escape(col_name)}\b"
            )
            match = re.search(cast_pattern, all_sql)
            if match:
                actual_type = match.group(1).upper()
                if actual_type != expected_type.upper():
                    type_mismatches.append(
                        f"{prop}: silverDataType={expected_type}, "
                        f"SQL CAST uses {actual_type}"
                    )

        assert not type_mismatches, (
            "silverDataType annotations inconsistent with SQL CASTs:\n"
            + "\n".join(f"  - {m}" for m in sorted(type_mismatches))
        )
