# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the strict alignment response schema (DD-177).

The schema exists to fix a measured failure, not to validate syntax. Three
identical runs of the party domain mapped 24, 22 and 23 columns with *zero*
disagreement about what the shared columns meant — the model omitted a
different handful each time. Keying verdicts by column name and requiring
every key makes that omission a schema violation.

Provider limits pinned here were measured against the live endpoint by
bisection: 1,000 enum values in total per schema, and ``$defs``/``$ref`` is
required because inlining the verdict per column exceeds a separate
total-size limit at realistic table widths.
"""

import pytest

from kairos_ontology.core.propose_alignment import (
    ALIGNMENT_KINDS,
    TOTAL_SCHEMA_ENUM_BUDGET,
    build_alignment_response_schema,
    normalize_schema_response,
)


def _schema(fmt):
    return fmt["json_schema"]["schema"]


class TestOmissionIsImpossible:
    """The whole point: the model cannot stay silent about a column."""

    def test_every_column_is_required(self):
        fmt, _ = build_alignment_response_schema(
            ["shipper_code", "consignee_code", "origin"], ["Shipment"], ["hasShipper"]
        )
        alignments = _schema(fmt)["properties"]["column_alignments"]
        assert alignments["required"] == ["shipper_code", "consignee_code", "origin"]
        assert set(alignments["properties"]) == {
            "shipper_code",
            "consignee_code",
            "origin",
        }

    def test_invented_columns_are_rejected(self):
        fmt, _ = build_alignment_response_schema(["a"], ["C"], ["p"])
        assert _schema(fmt)["properties"]["column_alignments"]["additionalProperties"] is False

    def test_duplicate_column_names_collapse(self):
        """A repeated name must not produce a duplicate required key."""
        fmt, _ = build_alignment_response_schema(["a", "a", "b"], ["C"], ["p"])
        assert _schema(fmt)["properties"]["column_alignments"]["required"] == ["a", "b"]

    def test_column_order_is_preserved(self):
        """Order follows the (already deterministic) source column order, DD-175."""
        fmt, _ = build_alignment_response_schema(["z", "m", "a"], ["C"], ["p"])
        assert _schema(fmt)["properties"]["column_alignments"]["required"] == ["z", "m", "a"]


class TestVocabularyConstraints:
    def test_properties_and_classes_are_enum_constrained(self):
        fmt, notes = build_alignment_response_schema(
            ["c"], ["Shipment", "Organization"], ["hasShipper", "hasConsignee"]
        )
        verdict = _schema(fmt)["$defs"]["ColumnVerdict"]["properties"]
        assert verdict["ref_property"]["enum"] == ["hasConsignee", "hasShipper", None]
        assert verdict["ref_class"]["enum"] == ["Organization", "Shipment", None]
        assert notes == []

    def test_alignment_kind_is_closed(self):
        fmt, _ = build_alignment_response_schema(["c"], ["C"], ["p"])
        verdict = _schema(fmt)["$defs"]["ColumnVerdict"]["properties"]
        assert verdict["alignment"]["enum"] == list(ALIGNMENT_KINDS)

    def test_null_is_allowed_so_no_match_is_expressible(self):
        """Forcing a verdict must not force a *mapping* — that would be worse."""
        fmt, _ = build_alignment_response_schema(["c"], ["C"], ["p"])
        verdict = _schema(fmt)["$defs"]["ColumnVerdict"]["properties"]
        assert None in verdict["ref_property"]["enum"]
        assert "null" in verdict["ref_property"]["type"]

    def test_oversized_enum_is_dropped_and_reported(self):
        """No silent cap: a dropped constraint is stated, not hidden."""
        props = [f"prop{i}" for i in range(TOTAL_SCHEMA_ENUM_BUDGET + 1)]
        fmt, notes = build_alignment_response_schema(["c"], ["C"], props)
        verdict = _schema(fmt)["$defs"]["ColumnVerdict"]["properties"]
        assert "enum" not in verdict["ref_property"]
        assert verdict["ref_property"]["type"] == ["string", "null"]
        assert any("ref_property enum dropped" in n for n in notes)

    def test_enum_budget_stays_within_the_provider_limit(self):
        """Total enum values across the schema must stay under the measured 1,000."""
        props = [f"prop{i}" for i in range(TOTAL_SCHEMA_ENUM_BUDGET)]
        classes = [f"Class{i}" for i in range(50)]
        fmt, _ = build_alignment_response_schema(["c"], classes, props)

        def count(node):
            if isinstance(node, dict):
                return len(node.get("enum", [])) + sum(count(v) for v in node.values())
            if isinstance(node, list):
                return sum(count(v) for v in node)
            return 0

        assert count(_schema(fmt)) <= 1000

    def test_empty_vocabulary_degrades_to_free_string(self):
        fmt, notes = build_alignment_response_schema(["c"], [], [])
        verdict = _schema(fmt)["$defs"]["ColumnVerdict"]["properties"]
        assert "enum" not in verdict["ref_property"]
        assert notes == []


class TestStrictModeContract:
    def test_uses_defs_ref_not_inline_verdicts(self):
        """Inlining per column exceeds the provider's total-schema-size limit."""
        fmt, _ = build_alignment_response_schema(["a", "b"], ["C"], ["p"])
        schema = _schema(fmt)
        assert "ColumnVerdict" in schema["$defs"]
        for col in ("a", "b"):
            assert schema["properties"]["column_alignments"]["properties"][col] == {
                "$ref": "#/$defs/ColumnVerdict"
            }

    def test_strict_flag_and_closed_objects(self):
        fmt, _ = build_alignment_response_schema(["a"], ["C"], ["p"])
        assert fmt["json_schema"]["strict"] is True
        schema = _schema(fmt)
        assert schema["additionalProperties"] is False
        assert schema["$defs"]["ColumnVerdict"]["additionalProperties"] is False

    def test_every_verdict_field_is_required(self):
        """Strict mode expresses optional as nullable, never as an absent key."""
        fmt, _ = build_alignment_response_schema(["a"], ["C"], ["p"])
        verdict = _schema(fmt)["$defs"]["ColumnVerdict"]
        assert set(verdict["required"]) == set(verdict["properties"])


class TestNormalizeSchemaResponse:
    def test_object_keyed_response_becomes_the_historical_list(self):
        result = normalize_schema_response(
            {
                "ref_class": "Shipment",
                "column_alignments": {
                    "shipper_code": {"ref_property": "hasShipper", "confidence": 0.9},
                    "origin": {"ref_property": None, "confidence": 0.0},
                },
            }
        )
        assert result["column_alignments"] == [
            {"column": "shipper_code", "ref_property": "hasShipper", "confidence": 0.9},
            {"column": "origin", "ref_property": None, "confidence": 0.0},
        ]
        assert result["ref_class"] == "Shipment"

    def test_list_response_passes_through_untouched(self):
        """This is the JSON-mode fallback path, when the schema was rejected."""
        original = {"column_alignments": [{"column": "a", "ref_property": "p"}]}
        assert normalize_schema_response(original) == original

    @pytest.mark.parametrize("value", [None, "", 42, []])
    def test_non_dict_alignments_pass_through(self, value):
        assert normalize_schema_response({"column_alignments": value})[
            "column_alignments"
        ] == value

    def test_missing_key_is_left_alone(self):
        assert normalize_schema_response({"ref_class": "C"}) == {"ref_class": "C"}

    def test_non_dict_verdicts_are_skipped(self):
        result = normalize_schema_response(
            {"column_alignments": {"a": {"ref_property": "p"}, "b": "junk"}}
        )
        assert result["column_alignments"] == [{"column": "a", "ref_property": "p"}]
