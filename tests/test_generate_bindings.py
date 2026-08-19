# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-191 binding generation from the design sheet.

Pins the kernel-verified rules: reuse-first target class from the sheet's
anchor URI; module-scoped property resolution (unresolvable → reported gap,
never a guess); object-property mappings routed to technicalFields, never
fields; duplicate property claims deduped by confidence; grain/identity
materialized with profile types; profile-proven quality only; contract
validation BEFORE writing; existing bindings never overwritten without force.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kairos_ontology.core import generate_bindings as gb
from kairos_ontology.core.compiler.bindings import load_entity_binding

CLASS_URI = "https://ref.test/ont/consignment#Consignment"

SHEET_ENTRY = {
    "system": "src", "table": "goods", "anchor": "Consignment",
    "anchor_uri": CLASS_URI, "domain": "consignment",
    "grain_columns": ["good_id"], "natural_key": ["good_id"],
    "status": "proposed", "schema_hash": "abc",
    "relationships": [
        {"to_table": "src.orders", "local_column": "order_id", "evidence": "fk-inclusion"}
    ],
    "secondary_entities": [
        {"class": "TradeParty", "grain_columns": ["customer_id"], "columns": ["customer_id"]}
    ],
    "flags": [],
}

ALIGNMENT_TABLE = {
    "system": "src", "table": "goods", "ref_class": "Consignment",
    "columns": [
        {"column": "descr", "data_type": "varchar(max)",
         "ref_property": "goodsDescription", "confidence": 0.9},
        {"column": "descr_alt", "data_type": "varchar(max)",
         "ref_property": "goodsDescription", "confidence": 0.4},   # duplicate claim
        {"column": "consignee", "data_type": "varchar(max)",
         "ref_property": "hasConsignee", "confidence": 0.8},       # object property
        {"column": "mystery", "data_type": "varchar(max)",
         "ref_property": "notInModule", "confidence": 0.7},        # unresolvable
        {"column": "plain", "data_type": "varchar(max)",
         "ref_property": "", "confidence": 0.0},                   # unmapped
    ],
    "custom_columns": [],
}

PROFILE = {
    "schema_version": 1, "system": "src", "basis": "import-extract(full)",
    "data_maturity": "production",
    "tables": {"goods": {"rows": 10, "table_tags": [], "columns": {
        "good_id": {"type": "int64", "null_ratio": 0.0, "distinct": 10,
                    "distinct_ratio": 1.0, "tags": ["unique", "id-like"]},
        "order_id": {"type": "int64", "null_ratio": 0.1, "distinct": 4,
                     "distinct_ratio": 0.44, "tags": ["id-like"]},
    }}},
}


def _pools(_catalog_path, class_uri):
    assert class_uri == CLASS_URI
    return (
        {"goodsDescription": "https://ref.test/ont/consignment#goodsDescription"},
        {"hasConsignee"},
    )


@pytest.fixture()
def hub(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(gb, "_class_pools", _pools)
    hub = tmp_path / "hub"
    analysis = hub / "integration" / "sources" / "_analysis"
    analysis.mkdir(parents=True)
    (hub / "catalog-v001.xml").write_text("<catalog/>", encoding="utf-8")
    (analysis / "table-anchors.yaml").write_text(
        yaml.safe_dump({"schema_version": 2, "tables": [SHEET_ENTRY]}),
        encoding="utf-8",
    )
    (analysis / "consignment-alignment.yaml").write_text(
        yaml.safe_dump({"domain": "consignment", "tables": [ALIGNMENT_TABLE]}),
        encoding="utf-8",
    )
    srcdir = hub / "integration" / "sources" / "src"
    srcdir.mkdir(parents=True)
    (srcdir / "src.profile.yaml").write_text(yaml.safe_dump(PROFILE), encoding="utf-8")
    return hub


def _run(hub, **kwargs):
    return gb.run_generate_bindings(hub, **kwargs)


class TestGeneration:
    def test_draft_is_written_and_loads_through_the_compiler_contract(self, hub):
        report = _run(hub)
        [g] = [g for g in report.generated if g.outcome == "written"]
        assert g.binding_name == "src-goods-to-consignment"
        text = g.path.read_text(encoding="utf-8")
        binding = load_entity_binding(text, path=str(g.path))
        assert binding.target_class == CLASS_URI, "reuse-first: reference IRI directly"

    def test_field_routing_rules(self, hub):
        report = _run(hub)
        doc = yaml.safe_load(report.generated[0].path.read_text(encoding="utf-8"))
        fields = {f["expression"]: f["property"] for f in doc["fields"]}
        # best-confidence column kept for the duplicated property
        assert fields == {"descr": "https://ref.test/ont/consignment#goodsDescription"}
        assert {"system": "src", "table": "goods", "property": "goodsDescription",
                "kept": "descr", "dropped": "descr_alt"} in report.duplicate_property_claims
        # unresolvable property reported, never guessed
        assert any(u["property"] == "notInModule" for u in report.unresolved_properties)
        technical = {t["name"]: t for t in doc["technicalFields"]}
        # object-property mapping → FK carrier, not a field
        assert technical["consignee"]["purpose"] == "relationship"
        # sheet relationship column → FK carrier with profile type/nullability
        assert technical["order_id"]["purpose"] == "relationship"
        assert technical["order_id"]["type"] == "int64"
        assert technical["order_id"]["nullable"] is True
        # grain column materialized for identity with profile type
        assert technical["good_id"]["purpose"] == "identity"
        assert technical["good_id"]["type"] == "int64"

    def test_profile_proven_quality_only(self, hub):
        report = _run(hub)
        doc = yaml.safe_load(report.generated[0].path.read_text(encoding="utf-8"))
        kinds = {q["kind"] for q in doc["quality"]}
        assert kinds == {"not-null", "unique"}, "grain measured non-null and unique"

    def test_secondary_entities_become_worklist_not_bindings(self, hub):
        report = _run(hub)
        assert report.secondary_entity_worklist == [
            {"system": "src", "table": "goods", "class": "TradeParty",
             "grain_columns": ["customer_id"], "columns": ["customer_id"]}
        ]
        assert len([g for g in report.generated if g.outcome == "written"]) == 1


class TestGuards:
    def test_existing_binding_is_never_overwritten_without_force(self, hub):
        first = _run(hub)
        path = first.generated[0].path
        path.write_text("# hand-edited\n" + path.read_text(encoding="utf-8"),
                        encoding="utf-8")
        second = _run(hub)
        assert second.generated[0].outcome == "exists"
        assert path.read_text(encoding="utf-8").startswith("# hand-edited")
        forced = _run(hub, force=True)
        assert forced.generated[0].outcome == "written"
        assert not path.read_text(encoding="utf-8").startswith("# hand-edited")

    def test_dry_run_validates_but_writes_nothing(self, hub):
        report = _run(hub, dry_run=True)
        assert report.generated[0].outcome == "would-write"
        assert not report.generated[0].path.exists()

    def test_rejected_sheet_rows_are_not_generated(self, hub):
        analysis = hub / "integration" / "sources" / "_analysis"
        doc = yaml.safe_load((analysis / "table-anchors.yaml").read_text("utf-8"))
        doc["tables"][0]["status"] = "rejected"
        (analysis / "table-anchors.yaml").write_text(yaml.safe_dump(doc), "utf-8")
        report = _run(hub)
        assert report.generated == []

    def test_missing_alignment_is_a_reported_skip(self, hub):
        analysis = hub / "integration" / "sources" / "_analysis"
        (analysis / "consignment-alignment.yaml").unlink()
        report = _run(hub)
        assert report.generated[0].outcome == "skipped"
        assert "propose-alignment" in report.generated[0].note

    def test_empty_grain_is_skipped_not_reported_invalid(self, hub):
        """#565: an empty grain is a property of the row (nothing to identify a
        record by), not a defect in the draft -- must never reach the validator
        and come back as 'invalid'."""
        analysis = hub / "integration" / "sources" / "_analysis"
        doc = yaml.safe_load((analysis / "table-anchors.yaml").read_text("utf-8"))
        doc["tables"][0]["grain_columns"] = []      # would violate the closed contract
        doc["tables"][0]["natural_key"] = []
        (analysis / "table-anchors.yaml").write_text(yaml.safe_dump(doc), "utf-8")
        report = _run(hub)
        assert report.generated[0].outcome == "skipped"
        assert "no grain identified" in report.generated[0].note

    def test_zero_scalar_fields_with_fk_carrier_is_skipped(self, hub):
        """#565: this generator never emits relationships:, so a table with zero
        scalar field mappings is unconditionally unwritable -- must be skipped,
        never sent to the validator to fail with a generic schema error. An FK
        carrier's presence only changes the reason text, never the outcome."""
        analysis = hub / "integration" / "sources" / "_analysis"
        alignment_path = analysis / "consignment-alignment.yaml"
        doc = yaml.safe_load(alignment_path.read_text("utf-8"))
        for table_dict in doc.get("tables", []):
            table_dict["columns"] = []
        alignment_path.write_text(yaml.safe_dump(doc), "utf-8")
        report = _run(hub)
        assert report.generated[0].outcome == "skipped"
        assert "no scalar fields mapped" in report.generated[0].note
        assert "deferred to propose-relationships" in report.generated[0].note

    def test_zero_scalar_fields_with_no_fk_carrier_at_all_is_skipped(self, hub):
        """Same outcome with no FK carrier evidence anywhere -- just a plainer
        reason, since there's no relationship wiring to defer to begin with."""
        analysis = hub / "integration" / "sources" / "_analysis"
        alignment_path = analysis / "consignment-alignment.yaml"
        align_doc = yaml.safe_load(alignment_path.read_text("utf-8"))
        for table_dict in align_doc.get("tables", []):
            table_dict["columns"] = []
        alignment_path.write_text(yaml.safe_dump(align_doc), "utf-8")

        anchors_path = analysis / "table-anchors.yaml"
        anchors_doc = yaml.safe_load(anchors_path.read_text("utf-8"))
        anchors_doc["tables"][0]["relationships"] = []
        anchors_path.write_text(yaml.safe_dump(anchors_doc), "utf-8")

        report = _run(hub)
        assert report.generated[0].outcome == "skipped"
        assert report.generated[0].note == "no scalar fields mapped for this table"
        assert not (hub / "integration" / "bindings").exists()

    def test_missing_sheet_is_a_hard_error_naming_the_fix(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="anchor-tables"):
            _run(tmp_path / "hub")