# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for enrich_vocabulary module — enum, format, and FK inference."""

from __future__ import annotations

from kairos_ontology.enrich_vocabulary import (
    detect_enums,
    detect_formats,
    infer_foreign_keys,
    enrich_source_schema,
)


class TestEnumDetection:
    """Tests for enum detection heuristic."""

    def test_low_cardinality_detected(self):
        columns = [
            {"name": "status", "data_type": "varchar(20)", "distinct_count": 5,
             "samples": ["active", "inactive", "pending", "closed", "draft"]},
        ]
        result = detect_enums("orders", columns, row_count=10000)
        assert len(result) == 1
        assert result[0].column == "status"
        assert result[0].distinct_count == 5
        assert "active" in result[0].values

    def test_high_cardinality_not_detected(self):
        columns = [
            {"name": "email", "data_type": "varchar(200)", "distinct_count": 9500,
             "samples": ["a@b.com"]},
        ]
        result = detect_enums("users", columns, row_count=10000)
        assert len(result) == 0

    def test_too_few_rows_skipped(self):
        columns = [
            {"name": "type", "data_type": "varchar(10)", "distinct_count": 3,
             "samples": ["A", "B", "C"]},
        ]
        result = detect_enums("small_table", columns, row_count=50)
        assert len(result) == 0

    def test_single_distinct_skipped(self):
        columns = [
            {"name": "constant", "data_type": "int", "distinct_count": 1,
             "samples": ["0"]},
        ]
        result = detect_enums("t", columns, row_count=1000)
        assert len(result) == 0

    def test_no_distinct_count_skipped(self):
        columns = [
            {"name": "col", "data_type": "varchar(50)", "samples": ["x"]},
        ]
        result = detect_enums("t", columns, row_count=1000)
        assert len(result) == 0

    def test_custom_threshold(self):
        columns = [
            {"name": "country", "data_type": "varchar(50)", "distinct_count": 15,
             "samples": ["BE", "NL", "FR"]},
        ]
        # With threshold 10, should NOT detect
        result = detect_enums("t", columns, row_count=5000, enum_threshold=10)
        assert len(result) == 0

        # With threshold 20, SHOULD detect
        result = detect_enums("t", columns, row_count=5000, enum_threshold=20)
        assert len(result) == 1


class TestFormatDetection:
    """Tests for format pattern detection."""

    def test_uuid_detected(self):
        columns = [
            {"name": "id", "data_type": "varchar(36)",
             "samples": ["550e8400-e29b-41d4-a716-446655440000",
                         "6ba7b810-9dad-11d1-80b4-00c04fd430c8"]},
        ]
        result = detect_formats("t", columns)
        assert len(result) == 1
        assert result[0].format_hint == "uuid"

    def test_email_detected(self):
        columns = [
            {"name": "email", "data_type": "varchar(200)",
             "samples": ["user@example.com", "admin@company.org", "test@test.be"]},
        ]
        result = detect_formats("t", columns)
        assert len(result) == 1
        assert result[0].format_hint == "email"

    def test_date_detected(self):
        columns = [
            {"name": "created_at", "data_type": "varchar(30)",
             "samples": ["2026-01-15T10:30:00Z", "2026-06-02"]},
        ]
        result = detect_formats("t", columns)
        assert len(result) == 1
        assert result[0].format_hint == "date"

    def test_url_detected(self):
        columns = [
            {"name": "website", "data_type": "varchar(500)",
             "samples": ["https://example.com", "https://github.com/org/repo"]},
        ]
        result = detect_formats("t", columns)
        assert len(result) == 1
        assert result[0].format_hint == "url"

    def test_phone_detected(self):
        columns = [
            {"name": "phone", "data_type": "varchar(20)",
             "samples": ["+32 2 123 45 67", "+1 (555) 123-4567"]},
        ]
        result = detect_formats("t", columns)
        assert len(result) == 1
        assert result[0].format_hint == "phone"

    def test_numeric_code_detected(self):
        columns = [
            {"name": "zip", "data_type": "varchar(10)",
             "samples": ["1000", "9000", "2600"]},
        ]
        result = detect_formats("t", columns)
        assert len(result) == 1
        assert result[0].format_hint == "numeric_code"

    def test_integer_column_skipped(self):
        columns = [
            {"name": "count", "data_type": "int",
             "samples": ["100", "200"]},
        ]
        result = detect_formats("t", columns)
        assert len(result) == 0

    def test_mixed_formats_no_match(self):
        columns = [
            {"name": "notes", "data_type": "varchar(max)",
             "samples": ["hello world", "12345", "user@test.com"]},
        ]
        result = detect_formats("t", columns)
        assert len(result) == 0

    def test_empty_samples_skipped(self):
        columns = [
            {"name": "col", "data_type": "varchar(50)", "samples": []},
        ]
        result = detect_formats("t", columns)
        assert len(result) == 0


class TestFKInference:
    """Tests for foreign key inference."""

    def test_name_based_exact_match(self):
        tables = [
            {"name": "orders", "row_count": 1000, "columns": [
                {"name": "id", "data_type": "int", "distinct_count": 1000},
                {"name": "customer_id", "data_type": "int", "distinct_count": 200},
            ]},
            {"name": "customers", "row_count": 200, "columns": [
                {"name": "id", "data_type": "int", "distinct_count": 200},
            ]},
        ]
        result = infer_foreign_keys(tables)
        assert len(result) == 1
        assert result[0].table == "orders"
        assert result[0].column == "customer_id"
        assert result[0].target_table == "customers"
        assert result[0].confidence == "high"

    def test_name_based_tbl_prefix(self):
        tables = [
            {"name": "tblInvoice", "row_count": 500, "columns": [
                {"name": "ClientId", "data_type": "int", "distinct_count": 100},
            ]},
            {"name": "tblClient", "row_count": 100, "columns": [
                {"name": "id", "data_type": "int", "distinct_count": 100},
            ]},
        ]
        result = infer_foreign_keys(tables)
        # Should find tblClient via "tblclient" match
        fk = [r for r in result if r.column == "ClientId"]
        assert len(fk) == 1
        assert fk[0].target_table == "tblClient"

    def test_no_match_no_suggestion(self):
        tables = [
            {"name": "orders", "row_count": 1000, "columns": [
                {"name": "amount", "data_type": "decimal", "distinct_count": 500},
            ]},
        ]
        result = infer_foreign_keys(tables)
        assert len(result) == 0

    def test_self_reference_excluded(self):
        tables = [
            {"name": "orders", "row_count": 1000, "columns": [
                {"name": "order_id", "data_type": "int", "distinct_count": 1000},
            ]},
        ]
        result = infer_foreign_keys(tables)
        # Should not suggest FK to itself
        assert all(r.target_table != r.table for r in result)


class TestEnrichSourceSchema:
    """Integration tests for the full enrichment pipeline."""

    def test_enriches_all_passes(self):
        data = {
            "version": "1.1",
            "system": "testapp",
            "tables": [
                {
                    "name": "orders",
                    "row_count": 5000,
                    "columns": [
                        {"name": "id", "data_type": "int", "distinct_count": 5000,
                         "samples": ["1", "2", "3"]},
                        {"name": "status", "data_type": "varchar(20)", "distinct_count": 4,
                         "samples": ["open", "closed", "pending", "cancelled"]},
                        {"name": "email", "data_type": "varchar(200)", "distinct_count": 4800,
                         "samples": ["a@b.com", "c@d.org", "test@example.com"]},
                        {"name": "customer_id", "data_type": "int", "distinct_count": 500,
                         "samples": ["101", "202", "303"]},
                    ],
                },
                {
                    "name": "customers",
                    "row_count": 500,
                    "columns": [
                        {"name": "id", "data_type": "int", "distinct_count": 500,
                         "samples": ["101", "202"]},
                    ],
                },
            ],
        }

        result = enrich_source_schema(data)

        # Enum: status should be detected
        status_col = result["tables"][0]["columns"][1]
        assert status_col["suggested_enum"] is True
        assert "open" in status_col["enum_values"]

        # Format: email should be detected
        email_col = result["tables"][0]["columns"][2]
        assert email_col["format_hint"] == "email"

        # FK: customer_id → customers
        cust_col = result["tables"][0]["columns"][3]
        assert cust_col["suggested_fk"] == "customers"
        assert cust_col["fk_confidence"] == "high"

    def test_no_enrichment_for_v10_like_data(self):
        """Data without samples/distinct_count gets no annotations."""
        data = {
            "version": "1.0",
            "system": "basic",
            "tables": [
                {
                    "name": "t1",
                    "columns": [
                        {"name": "col1", "data_type": "int"},
                    ],
                },
            ],
        }
        result = enrich_source_schema(data)
        col = result["tables"][0]["columns"][0]
        assert "suggested_enum" not in col
        assert "format_hint" not in col
        assert "suggested_fk" not in col

    def test_returns_same_dict(self):
        """enrich_source_schema mutates and returns the same dict."""
        data = {"version": "1.1", "system": "x", "tables": []}
        result = enrich_source_schema(data)
        assert result is data
