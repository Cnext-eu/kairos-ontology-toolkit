# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The gap gate sees the BI demand (#942).

On one hub a weekly-volume report, the reason the hub existed, was grained on a sailing
date the gap gate auto-deferred like any other timestamp. The imported Power BI model
that could not be built without it sat in the same repository. These pin that a column
a BI model uses carries that fact onto its decision row, is never drafted as deferred or
not-business-data, and is left for a human by the blanket accept.
"""

from __future__ import annotations

import yaml

from kairos_ontology.core.alignment_report import GapGroup, UnmappedColumn
from kairos_ontology.core.bi_demand import (
    KIND_MEASURE,
    KIND_RELATIONSHIP,
    load_bi_demand,
    normalise,
)
from kairos_ontology.core.gap_decisions import (
    accept_proposals,
    build_decision_sheet,
    propose_for_group,
)


def _concept_mapping(hub):
    bi = hub / "integration" / "discovery" / "bi"
    bi.mkdir(parents=True, exist_ok=True)
    (bi / "Volumes-concept-mapping.yaml").write_text(
        yaml.safe_dump({
            "schema_version": "1",
            "model_name": "Volumes",
            "tables": [
                {"tmdl_name": "f_Volume", "columns": ["Route", "Week"],
                 "measures": [{"name": "Teu", "expression": "SUM(f_Volume[Teu_Count])"}]},
                {"tmdl_name": "d_Sailing", "columns": ["SailingDate", "Vessel"], "measures": []},
            ],
            "relationships": [
                {"from": "f_Volume.SAILING_DATE", "to": "d_Sailing.SailingDate",
                 "cardinality": "many-to-one"},
            ],
        }),
        encoding="utf-8",
    )


def _alignment(hub, columns):
    analysis = hub / "integration" / "sources" / "_analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    (analysis / "dom-voyage.alignment.yaml").write_text(
        yaml.safe_dump({"domain": "voyage", "tables": [{
            "system": "tms", "table": "legs", "ref_class": "Leg", "columns": [],
            "custom_columns": [{"column": c, "data_type": "varchar"} for c in columns],
        }]}),
        encoding="utf-8",
    )


class TestTheIndex:
    def test_names_match_across_case_and_separators(self):
        assert normalise("SAILING_DATE") == normalise("SailingDate") == "sailingdate"

    def test_relationship_keys_and_measure_inputs_are_indexed(self, tmp_path):
        _concept_mapping(tmp_path)
        demand = load_bi_demand(tmp_path)

        kinds = {ref.kind for ref in demand.references_for("sailing_date")}
        assert KIND_RELATIONSHIP in kinds
        (teu,) = demand.references_for("TEU_COUNT")
        assert teu.kind == KIND_MEASURE and teu.measure == "Teu"
        assert demand.references_for("unrelated_column") == []

    def test_a_hub_without_bi_evidence_has_no_demand(self, tmp_path):
        assert not load_bi_demand(tmp_path)


class TestTheSheet:
    def test_a_name_rule_never_defers_a_column_a_report_uses(self):
        group = GapGroup(column="booking_notes", occurrences=[
            UnmappedColumn(system="tms", table="t", column="booking_notes",
                           data_type="varchar", reason="no-reference-property"),
        ])
        plain = propose_for_group(group)
        assert plain.proposed_disposition == "not-business-data"

        demanded = propose_for_group(group, bi_demand=["Volumes: f[Booking Notes] (model column)"])
        assert demanded.proposed_disposition == ""
        assert "Power BI model depends on this column" in demanded.reasoning
        assert "not-business-data" in demanded.reasoning, "the rule's reading stays visible"
        assert demanded.to_entry()["bi_demand"]

    def test_the_sheet_carries_the_evidence_and_the_count(self, tmp_path):
        _concept_mapping(tmp_path)
        _alignment(tmp_path, ["SAILING_DATE", "internal_flag"])

        sheet = build_decision_sheet(tmp_path)

        entries = {e["column"]: e for e in sheet["decisions"]}
        assert "relationship key" in entries["SAILING_DATE"]["bi_demand"][0]
        assert "bi_demand" not in entries["internal_flag"]
        assert sheet["summary"]["with_bi_demand"] == 1

    def test_accept_proposals_leaves_bi_demand_to_a_human(self, tmp_path):
        _concept_mapping(tmp_path)
        _alignment(tmp_path, ["SAILING_DATE", "internal_flag"])
        sheet = build_decision_sheet(tmp_path)

        counts = accept_proposals(sheet)

        entries = {e["column"]: e for e in sheet["decisions"]}
        assert entries["SAILING_DATE"]["decision"] == ""
        assert entries["internal_flag"]["decision"] == "deferred"
        assert counts["held-for-bi-demand"] == 1


class TestTheAutoRule:
    def test_a_bi_column_is_withheld_from_auto_silencing(self, tmp_path):
        """--auto records not-business-data for audit-shaped names; not one a report uses."""
        from kairos_ontology.core.gap_decisions import apply_auto_dispositions
        from kairos_ontology.core.source_disposition import load_dispositions

        _concept_mapping(tmp_path)
        bi = tmp_path / "integration" / "discovery" / "bi" / "Volumes-concept-mapping.yaml"
        document = yaml.safe_load(bi.read_text(encoding="utf-8"))
        document["tables"][0]["columns"].append("Created_At")
        bi.write_text(yaml.safe_dump(document), encoding="utf-8")
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True, exist_ok=True)
        (analysis / "dom-voyage.alignment.yaml").write_text(
            yaml.safe_dump({"domain": "voyage", "tables": [{
                "system": "tms", "table": "legs", "ref_class": "Leg", "columns": [],
                "custom_columns": [
                    {"column": "created_at", "data_type": "datetime",
                     "recommended_disposition": "", "suggested_property": None},
                    {"column": "updated_at", "data_type": "datetime",
                     "recommended_disposition": "", "suggested_property": None},
                ],
            }]}),
            encoding="utf-8",
        )

        stats = apply_auto_dispositions(tmp_path)

        recorded = load_dispositions(tmp_path)
        assert ("tms", "legs", "created_at") not in recorded, "a report uses it"
        assert ("tms", "legs", "updated_at") in recorded, "the rule still works elsewhere"
        assert any(
            "Power BI model depends on it" in c["conflict"] for c in stats["conflicts"]
        )
