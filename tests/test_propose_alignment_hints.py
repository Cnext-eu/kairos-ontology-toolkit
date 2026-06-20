# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for DD-045 deterministic mapping-hint generation."""

from __future__ import annotations

from kairos_ontology.propose_alignment import (
    ColumnAlignment,
    DomainAlignment,
    TableAlignment,
    _build_property_range_index,
    _detect_structural_hints,
    _is_discriminator,
    _lookup_property_range,
    _normalize_logical_type,
    _transform_hint,
    alignment_to_dict,
)

# ---------------------------------------------------------------------------
# _normalize_logical_type
# ---------------------------------------------------------------------------


class TestNormalizeLogicalType:
    def test_sql_string_types(self):
        for t in ("varchar", "NVARCHAR(50)", "char", "text"):
            assert _normalize_logical_type(t) == "string"

    def test_sql_int_types(self):
        for t in ("int", "BIGINT", "smallint", "tinyint"):
            assert _normalize_logical_type(t) == "int"

    def test_bit_is_bool(self):
        assert _normalize_logical_type("bit") == "bool"

    def test_decimal_precision_stripped(self):
        assert _normalize_logical_type("decimal(10,2)") == "decimal"

    def test_xsd_uri_range(self):
        assert _normalize_logical_type("http://www.w3.org/2001/XMLSchema#string") == "string"
        assert _normalize_logical_type("xsd:boolean") == "bool"
        assert _normalize_logical_type("xsd:dateTime") == "datetime"

    def test_unknown(self):
        assert _normalize_logical_type("") == "unknown"
        assert _normalize_logical_type(None) == "unknown"
        assert _normalize_logical_type("geography") == "unknown"


# ---------------------------------------------------------------------------
# _transform_hint
# ---------------------------------------------------------------------------


class TestTransformHint:
    def test_passthrough_same_type_and_name_no_confirmation(self):
        col = {"name": "isActive", "data_type": "bit"}
        h = _transform_hint(col, "isActive", "xsd:boolean")
        assert h["transform_hint"] == "source.isActive"
        assert h["requires_human_confirmation"] is False
        assert h["transform_confidence"] >= 0.9

    def test_same_type_name_differs_requires_confirmation(self):
        col = {"name": "IsActive", "data_type": "bit"}
        h = _transform_hint(col, "active", "xsd:boolean")
        assert h["transform_hint"] == "source.IsActive"
        assert h["requires_human_confirmation"] is True

    def test_name_match_is_case_insensitive(self):
        col = {"name": "IsActive", "data_type": "bit"}
        h = _transform_hint(col, "isactive", "xsd:boolean")
        assert h["requires_human_confirmation"] is False

    def test_type_differs_emits_cast_and_requires_confirmation(self):
        col = {"name": "IsActive", "data_type": "int"}
        h = _transform_hint(col, "isActive", "xsd:boolean")
        assert h["transform_hint"] == "CAST(source.IsActive AS BOOLEAN)"
        assert h["requires_human_confirmation"] is True

    def test_unknown_type_flags_for_human(self):
        col = {"name": "Geo", "data_type": "geography"}
        h = _transform_hint(col, "geo", "xsd:string")
        assert h["transform_hint"] == "source.Geo"
        assert h["requires_human_confirmation"] is True
        assert h["transform_confidence"] <= 0.3


# ---------------------------------------------------------------------------
# _is_discriminator
# ---------------------------------------------------------------------------


class TestIsDiscriminator:
    def test_name_type(self):
        assert _is_discriminator({"name": "Type", "data_type": "int"})

    def test_name_suffix_type(self):
        assert _is_discriminator({"name": "ClientType", "data_type": "int"})

    def test_low_cardinality_samples(self):
        assert _is_discriminator(
            {"name": "Flag", "data_type": "int", "samples": ["0", "1", "2"]}
        )

    def test_high_cardinality_not_discriminator(self):
        assert not _is_discriminator(
            {"name": "ClientID", "data_type": "int", "samples": ["1", "2", "3", "4", "5", "6"]}
        )

    def test_no_samples_plain_name_not_discriminator(self):
        assert not _is_discriminator({"name": "Email", "data_type": "varchar"})


# ---------------------------------------------------------------------------
# _detect_structural_hints
# ---------------------------------------------------------------------------


def _party_ref_classes():
    return [
        {
            "name": "Party",
            "properties": [
                {"name": "partyId", "range": "xsd:string"},
                {"name": "name", "range": "xsd:string"},
            ],
            "specializations": [
                {"class": "CorporateClient", "properties": []},
                {"class": "IndividualClient", "properties": []},
                {"class": "SoleProprietorClient", "properties": []},
            ],
        },
        {
            "name": "Address",
            "properties": [{"name": "name", "range": "xsd:string"}],
        },
    ]


class TestDetectStructuralHints:
    def test_split_candidate_detected(self):
        cols = [
            {"name": "ClientID", "data_type": "int"},
            {"name": "Type", "data_type": "int", "samples": ["0", "1", "2"]},
        ]
        hints = _detect_structural_hints("tblClient", cols, _party_ref_classes())
        split = [h for h in hints if h["type"] == "split_candidate"]
        assert len(split) == 1
        assert split[0]["discriminator_column"] == "Type"
        assert split[0]["sampled_values"] == ["0", "1", "2"]
        assert len(split[0]["target_class_candidates"]) == 3
        assert split[0]["requires_human_confirmation"] is True

    def test_no_split_when_no_siblings(self):
        ref = [{"name": "Party", "properties": [], "specializations": []}]
        cols = [{"name": "Type", "data_type": "int", "samples": ["0", "1"]}]
        hints = _detect_structural_hints("tblClient", cols, ref)
        assert not [h for h in hints if h["type"] == "split_candidate"]

    def test_dedup_candidate_detected(self):
        cols = [
            {"name": "ClientID", "data_type": "int"},
            {"name": "ModifiedDate", "data_type": "datetime"},
        ]
        hints = _detect_structural_hints("tblRelation", cols, _party_ref_classes())
        dedup = [h for h in hints if h["type"] == "dedup_candidate"]
        assert len(dedup) == 1
        assert dedup[0]["natural_key_column"] == "ClientID"
        assert "ModifiedDate" in dedup[0]["ordering_column_candidates"]

    def test_no_dedup_without_ordering_column(self):
        cols = [{"name": "ClientID", "data_type": "int"}]
        hints = _detect_structural_hints("tblClient", cols, _party_ref_classes())
        assert not [h for h in hints if h["type"] == "dedup_candidate"]

    def test_multi_target_candidate_detected(self):
        cols = [{"name": "name", "data_type": "varchar"}]
        hints = _detect_structural_hints("tblThing", cols, _party_ref_classes())
        multi = [h for h in hints if h["type"] == "multi_target_candidate"]
        assert len(multi) == 1
        assert set(multi[0]["target_class_candidates"]) == {"Party", "Address"}

    def test_clean_table_has_no_hints(self):
        ref = [{"name": "Party", "properties": [{"name": "partyId", "range": "xsd:string"}]}]
        cols = [{"name": "partyId", "data_type": "varchar"}]
        assert _detect_structural_hints("tblParty", cols, ref) == []


# ---------------------------------------------------------------------------
# property range index
# ---------------------------------------------------------------------------


class TestPropertyRangeIndex:
    def test_lookup_by_class_and_name(self):
        idx = _build_property_range_index(_party_ref_classes())
        assert _lookup_property_range(idx, "Party", "partyId") == "xsd:string"

    def test_lookup_falls_back_to_name(self):
        idx = _build_property_range_index(_party_ref_classes())
        assert _lookup_property_range(idx, "UnknownClass", "partyId") == "xsd:string"

    def test_missing_property_returns_empty(self):
        idx = _build_property_range_index(_party_ref_classes())
        assert _lookup_property_range(idx, "Party", "nope") == ""


# ---------------------------------------------------------------------------
# alignment_to_dict — hint serialization (Phase 2 regression guard)
# ---------------------------------------------------------------------------


def _domain_with_column(**hint_fields):
    col = ColumnAlignment(
        column="IsActive",
        data_type="bit",
        ref_class="Client",
        ref_property="isActive",
        alignment="exact",
        confidence=0.9,
        rationale="",
        **hint_fields,
    )
    table = TableAlignment(
        system="adminpulse", table="tblClient", ref_class="Client",
        ref_class_confidence=0.9, columns=[col],
    )
    return DomainAlignment(
        domain="client", domain_uris=["http://ex/client#"],
        generated_at="2026-06-13T00:00:00Z", model_used="test",
        tables=[table],
    )


class TestHintSerialization:
    def test_default_output_has_no_hint_keys(self, tmp_path):
        """Regression guard: without hints, output is unchanged (design-domain)."""
        data = alignment_to_dict(_domain_with_column())
        col = data["tables"][0]["columns"][0]
        for key in (
            "transform_hint", "transform_confidence",
            "requires_human_confirmation", "transform_rationale",
        ):
            assert key not in col
        assert "structural_hints" not in data["tables"][0]

    def test_hint_keys_emitted_when_populated(self, tmp_path):
        dom = _domain_with_column(
            transform_hint="source.IsActive",
            transform_confidence=0.9,
            requires_human_confirmation=False,
            transform_rationale="passthrough",
        )
        dom.tables[0].structural_hints = [
            {"type": "split_candidate", "source_table": "tblClient"}
        ]
        data = alignment_to_dict(dom)
        col = data["tables"][0]["columns"][0]
        assert col["transform_hint"] == "source.IsActive"
        assert col["requires_human_confirmation"] is False
        assert data["tables"][0]["structural_hints"][0]["type"] == "split_candidate"
