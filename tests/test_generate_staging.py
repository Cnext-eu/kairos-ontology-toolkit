# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for generate_staging module — bronze_expanded dbt model generation."""

from __future__ import annotations

import yaml
import pytest

from kairos_ontology.core.generate_staging import (
    generate_staging_models,
    _generate_flat_expansion,
    _generate_array_expansion,
    _json_type_to_sql_cast,
)


@pytest.fixture
def schema_dir(tmp_path):
    """Create a sample extracted/<system>/ directory for testing."""
    d = tmp_path / "extracted" / "myapp"
    d.mkdir(parents=True)

    manifest = {
        "version": "1.1",
        "system": "myapp",
        "platform": "fabric-warehouse",
        "extracted_at": "2026-06-01T12:00:00Z",
        "tables": ["orders", "customers"],
    }
    (d / "_manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")

    orders = {
        "name": "orders",
        "row_count": 500,
        "columns": [
            {"name": "id", "data_type": "int", "nullable": False},
            {"name": "status", "data_type": "varchar(50)", "nullable": False},
            {
                "name": "metadata",
                "data_type": "varchar(max)",
                "nullable": True,
                "json_detected": True,
                "json_classification": "flat",
                "json_structure": [
                    {"key": "priority", "type": "integer", "sample": 3},
                    {"key": "note", "type": "string", "sample": "urgent"},
                ],
            },
            {
                "name": "line_items",
                "data_type": "varchar(max)",
                "nullable": True,
                "json_detected": True,
                "json_classification": "array_object",
                "json_structure": [
                    {"key": "product_id", "type": "integer"},
                    {"key": "quantity", "type": "integer"},
                    {"key": "price", "type": "number"},
                ],
            },
        ],
    }
    (d / "orders.yaml").write_text(yaml.dump(orders), encoding="utf-8")

    customers = {
        "name": "customers",
        "row_count": 100,
        "columns": [
            {"name": "id", "data_type": "int", "nullable": False},
            {"name": "name", "data_type": "varchar(200)", "nullable": False},
        ],
    }
    (d / "customers.yaml").write_text(yaml.dump(customers), encoding="utf-8")

    return d


class TestGenerateStagingModels:
    """Integration tests for generate_staging_models."""

    def test_generates_models_for_json_columns(self, schema_dir, tmp_path):
        out = tmp_path / "models" / "staging"
        result = generate_staging_models(schema_dir, out)

        assert len(result) == 2
        names = [p.name for p in result]
        assert "stg_myapp_orders_metadata.sql" in names
        assert "stg_myapp_orders_line_items.sql" in names

    def test_flat_model_uses_json_value(self, schema_dir, tmp_path):
        out = tmp_path / "models" / "staging"
        generate_staging_models(schema_dir, out)

        flat_model = (out / "stg_myapp_orders_metadata.sql").read_text()
        assert "JSON_VALUE" in flat_model
        assert "$.priority" in flat_model
        assert "$.note" in flat_model
        assert "materialized='view'" in flat_model
        assert "source('myapp', 'orders')" in flat_model

    def test_array_model_uses_cross_apply(self, schema_dir, tmp_path):
        out = tmp_path / "models" / "staging"
        generate_staging_models(schema_dir, out)

        array_model = (out / "stg_myapp_orders_line_items.sql").read_text()
        assert "CROSS APPLY OPENJSON" in array_model
        assert "$.product_id" in array_model
        assert "$.quantity" in array_model
        assert "materialized='table'" in array_model

    def test_no_models_for_table_without_json(self, schema_dir, tmp_path):
        out = tmp_path / "models" / "staging"
        generate_staging_models(schema_dir, out)

        # No model for customers (no JSON columns)
        files = list(out.iterdir())
        assert not any("customers" in f.name for f in files)

    def test_missing_manifest_raises(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with pytest.raises(FileNotFoundError, match="_manifest.yaml"):
            generate_staging_models(empty_dir, tmp_path / "out")

    def test_custom_source_name(self, schema_dir, tmp_path):
        out = tmp_path / "models" / "staging"
        result = generate_staging_models(schema_dir, out, source_name="custom_src")

        names = [p.name for p in result]
        assert "stg_custom_src_orders_metadata.sql" in names

    def test_creates_output_dir(self, schema_dir, tmp_path):
        out = tmp_path / "deeply" / "nested" / "dir"
        assert not out.exists()
        generate_staging_models(schema_dir, out)
        assert out.exists()


class TestFlatExpansion:
    """Unit tests for _generate_flat_expansion."""

    def test_basic_flat(self):
        result = _generate_flat_expansion(
            "orders", "meta",
            [{"key": "email", "type": "string"}, {"key": "age", "type": "integer"}],
            "src"
        )
        assert result is not None
        name, sql = result
        assert name == "stg_src_orders_meta"
        assert "JSON_VALUE([meta], '$.email')" in sql
        assert "CAST(JSON_VALUE([meta], '$.age') AS INT)" in sql

    def test_empty_structure_returns_none(self):
        assert _generate_flat_expansion("t", "c", [], "s") is None

    def test_empty_key_skipped(self):
        result = _generate_flat_expansion(
            "t", "c", [{"key": "", "type": "string"}], "s"
        )
        assert result is None


class TestArrayExpansion:
    """Unit tests for _generate_array_expansion."""

    def test_basic_array(self):
        result = _generate_array_expansion(
            "orders", "items",
            [{"key": "name", "type": "string"}, {"key": "qty", "type": "integer"}],
            "src"
        )
        assert result is not None
        name, sql = result
        assert name == "stg_src_orders_items"
        assert "CROSS APPLY OPENJSON" in sql
        assert "JSON_VALUE(j.value, '$.name')" in sql
        assert "CAST(JSON_VALUE(j.value, '$.qty') AS INT)" in sql


class TestJsonTypeCast:
    """Unit tests for _json_type_to_sql_cast."""

    def test_integer(self):
        assert _json_type_to_sql_cast("integer") == "INT"

    def test_number(self):
        assert _json_type_to_sql_cast("number") == "DECIMAL(18,4)"

    def test_boolean(self):
        assert _json_type_to_sql_cast("boolean") == "BIT"

    def test_string_returns_none(self):
        assert _json_type_to_sql_cast("string") is None

    def test_unknown_returns_none(self):
        assert _json_type_to_sql_cast("object") is None
