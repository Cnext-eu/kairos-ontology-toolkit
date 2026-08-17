# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Drafting the gap-gate decisions (DD-186).

The DD-169 gate is correct and expensive: 1,286 blocking columns on the live hub.
This module does the clerical part — recording the two reason codes that were
never judgment calls, and collapsing the rest to one entry per column name (1,087
columns become 358 decisions, because the same ``OrderNo`` in nineteen tables is
one decision).

What these tests mostly pin is the refusal: a proposal is never applied on its
own. ``blueprint-gap``, ``deferred`` and ``registered-extension`` shape the model,
and a drafting tool that quietly chose them would recreate the silent-omission
failure the gate exists to prevent.
"""

import pytest
import yaml

from kairos_ontology.core.alignment_report import (
    REASON_NO_REFERENCE_PROPERTY,
    REASON_OPERATIONAL,
    REASON_VENDOR_SLOT,
    GapGroup,
    UnmappedColumn,
)
from kairos_ontology.core.gap_decisions import (
    AUTO_DISPOSITIONS,
    apply_auto_dispositions,
    apply_decision_sheet,
    build_decision_sheet,
    propose_for_group,
    write_decision_sheet,
)
from kairos_ontology.core.source_disposition import DISPOSITIONS, load_dispositions


def group(column, count=1, data_type="varchar(max)", reason=REASON_NO_REFERENCE_PROPERTY):
    return GapGroup(
        column=column,
        occurrences=[
            UnmappedColumn(
                system="qargo", table=f"t{i}", column=column,
                data_type=data_type, reason=reason,
            )
            for i in range(count)
        ],
    )


def write_alignment(analysis, domain, table, columns):
    analysis.mkdir(parents=True, exist_ok=True)
    (analysis / f"{domain}-alignment.yaml").write_text(
        yaml.safe_dump({
            "domain": domain,
            "tables": [{
                "system": "qargo", "table": table, "ref_class": "C",
                "columns": [], "custom_columns": columns,
            }],
        }),
        encoding="utf-8",
    )


class TestProposals:
    def test_recurring_identifier_proposes_a_blueprint_gap(self):
        p = propose_for_group(group("OrderNo", count=19, data_type="int"))
        assert p.proposed_disposition == "blueprint-gap"
        assert "19" in p.reasoning

    def test_free_text_proposes_not_business_data(self):
        assert propose_for_group(group("comments")).proposed_disposition == "not-business-data"

    def test_json_blob_proposes_deferred(self):
        p = propose_for_group(group("custom_fields", count=14))
        assert p.proposed_disposition == "deferred"
        assert "unpacked" in p.reasoning

    def test_a_singleton_with_no_rule_gets_no_proposal(self):
        """Silence is the honest answer when no rule applies."""
        p = propose_for_group(group("weird_local_thing"))
        assert p.proposed_disposition == ""
        assert p.confidence == "low"

    def test_every_proposal_is_a_valid_disposition_or_empty(self):
        for name, n in [("OrderNo", 19), ("notes", 2), ("payload", 3), ("x", 1), ("thing", 6)]:
            p = propose_for_group(group(name, count=n))
            assert p.proposed_disposition in DISPOSITIONS or p.proposed_disposition == ""

    def test_proposal_carries_the_evidence_a_reviewer_needs(self):
        entry = propose_for_group(group("OrderNo", count=19, data_type="int")).to_entry()
        assert entry["occurrences"] == 19
        assert entry["data_types"] == ["int"]
        assert entry["tables"], "a reviewer must see where it appears"
        assert entry["decision"] == "", "the reviewer's field starts empty"
        assert "domain" in entry, "a decision is domain-scoped"


class TestAutoDispositions:
    def _hub(self, tmp_path, reason):
        write_alignment(
            tmp_path / "integration" / "sources" / "_analysis", "party", "companies",
            [{"column": "created_at", "data_type": "datetime",
              "recommended_disposition": "", "suggested_property": None}],
        )
        return tmp_path

    def test_only_rule_decidable_reasons_are_automated(self):
        """blueprint-gap et al must never be automated — they shape the model."""
        assert set(AUTO_DISPOSITIONS) == {REASON_OPERATIONAL, REASON_VENDOR_SLOT}
        assert set(AUTO_DISPOSITIONS.values()) == {"not-business-data"}

    def test_dry_run_writes_nothing(self, tmp_path):
        hub = self._hub(tmp_path, REASON_OPERATIONAL)
        apply_auto_dispositions(hub, dry_run=True)
        assert load_dispositions(hub) == {}

    def test_existing_human_decision_is_never_overwritten(self, tmp_path):
        from kairos_ontology.core.source_disposition import record_disposition

        hub = self._hub(tmp_path, REASON_OPERATIONAL)
        record_disposition(
            hub_root=hub, system="qargo", table="companies", column="created_at",
            disposition="deferred", rationale="human said so", decided_by="user",
        )
        stats = apply_auto_dispositions(hub)
        assert stats["skipped_already_decided"] >= 1
        entry = load_dispositions(hub)[("qargo", "companies", "created_at")]
        assert entry["disposition"] == "deferred"
        assert entry["decided_by"] == "user"


class TestDecisionSheet:
    def _hub_with_gaps(self, tmp_path):
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        write_alignment(analysis, "party", "companies", [
            {"column": "OrderNo", "data_type": "int"},
            {"column": "custom_fields", "data_type": "varchar(max)"},
        ])
        return tmp_path

    def test_sheet_lists_names_with_empty_decisions(self, tmp_path):
        sheet = build_decision_sheet(self._hub_with_gaps(tmp_path))
        assert sheet["summary"]["decisions_to_make"] >= 1
        assert all(e["decision"] == "" for e in sheet["decisions"])
        assert all(f["decision"] == "" for f in sheet["families"])
        assert "draft-gap-decisions --apply" in sheet["how_to_use"]

    def test_rewriting_preserves_decisions_already_filled_in(self, tmp_path):
        """Re-drafting after new alignment output must not discard review work."""
        hub = self._hub_with_gaps(tmp_path)
        sheet = build_decision_sheet(hub)
        sheet["decisions"][0]["decision"] = "blueprint-gap"
        target = sheet["decisions"][0]["column"]
        write_decision_sheet(hub, sheet)

        rewritten = build_decision_sheet(hub)
        path = write_decision_sheet(hub, rewritten)
        saved = yaml.safe_load(path.read_text(encoding="utf-8"))
        kept = next(e for e in saved["decisions"] if e["column"] == target)
        assert kept["decision"] == "blueprint-gap"

    def test_apply_fans_one_name_out_to_every_occurrence(self, tmp_path):
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (analysis / "party-alignment.yaml").write_text(
            yaml.safe_dump({"domain": "party", "tables": [
                {"system": "qargo", "table": f"t{i}", "ref_class": "C", "columns": [],
                 "custom_columns": [{"column": "OrderNo", "data_type": "int"}]}
                for i in range(3)
            ]}),
            encoding="utf-8",
        )
        sheet = build_decision_sheet(tmp_path)
        for entry in sheet["decisions"]:
            if entry["column"] == "OrderNo":
                entry["decision"] = "blueprint-gap"
        write_decision_sheet(tmp_path, sheet)

        stats = apply_decision_sheet(tmp_path)
        assert stats["names_applied"] == 1
        assert stats["columns_written"] == 3, "one decision must cover all its occurrences"
        recorded = load_dispositions(tmp_path)
        assert all(
            recorded[("qargo", f"t{i}", "OrderNo")]["disposition"] == "blueprint-gap"
            for i in range(3)
        )

    def test_an_invalid_disposition_is_refused_before_anything_is_written(self, tmp_path):
        hub = self._hub_with_gaps(tmp_path)
        sheet = build_decision_sheet(hub)
        sheet["decisions"][0]["decision"] = "make-it-up"
        write_decision_sheet(hub, sheet)
        with pytest.raises(ValueError, match="Unknown disposition"):
            apply_decision_sheet(hub)
        assert load_dispositions(hub) == {}

    def test_blank_decisions_are_simply_skipped(self, tmp_path):
        hub = self._hub_with_gaps(tmp_path)
        write_decision_sheet(hub, build_decision_sheet(hub))
        assert apply_decision_sheet(hub) == {
            "names_applied": 0, "families_applied": 0, "columns_written": 0}

    def test_apply_without_a_sheet_is_an_explicit_error(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Draft one first"):
            apply_decision_sheet(tmp_path)


class TestFamilies:
    """Family grouping is the real reduction: 58 families covered 434 of 596
    undecided names on the live hub, and they are semantically coherent
    (pickup_*, delivery_*, origin_* — the DD-179 role structures)."""

    def _family_hub(self, tmp_path):
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        cols = [{"column": f"pickup_{s}", "data_type": "varchar(max)"}
                for s in ("city", "country", "postcode", "street")]
        cols.append({"column": "loner", "data_type": "int"})
        (analysis / "party-alignment.yaml").write_text(
            yaml.safe_dump({"domain": "party", "tables": [
                {"system": "qargo", "table": "stops", "ref_class": "C",
                 "columns": [], "custom_columns": cols}]}),
            encoding="utf-8")
        return tmp_path

    def test_a_family_becomes_one_decision(self, tmp_path):
        sheet = build_decision_sheet(self._family_hub(tmp_path))
        fam = next(f for f in sheet["families"] if f["family"] == "pickup")
        assert fam["distinct_names"] == 4
        assert fam["source_columns"] == 4
        assert "loner" not in fam["members"]

    def test_names_below_the_threshold_stay_loose(self, tmp_path):
        sheet = build_decision_sheet(self._family_hub(tmp_path))
        assert "loner" in [e["column"] for e in sheet["decisions"]]

    def test_family_decision_fans_out_to_every_member(self, tmp_path):
        hub = self._family_hub(tmp_path)
        sheet = build_decision_sheet(hub)
        next(f for f in sheet["families"] if f["family"] == "pickup")["decision"] = "deferred"
        write_decision_sheet(hub, sheet)
        stats = apply_decision_sheet(hub)
        assert stats["families_applied"] == 1
        assert stats["columns_written"] == 4
        recorded = load_dispositions(hub)
        assert recorded[("qargo", "stops", "pickup_city")]["disposition"] == "deferred"
        assert ("qargo", "stops", "loner") not in recorded

    def test_an_explicit_name_decision_overrides_its_family(self, tmp_path):
        """Rule on the family, carve out one exception, without unpicking it."""
        hub = self._family_hub(tmp_path)
        sheet = build_decision_sheet(hub)
        next(f for f in sheet["families"] if f["family"] == "pickup")["decision"] = "deferred"
        fam = next(f for f in sheet["families"] if f["family"] == "pickup")
        sheet["decisions"].append(
            {"column": "pickup_city", "domain": fam["domain"],
             "decision": "not-business-data"}
        )
        write_decision_sheet(hub, sheet)
        apply_decision_sheet(hub)
        recorded = load_dispositions(hub)
        assert recorded[("qargo", "stops", "pickup_city")]["disposition"] == "not-business-data"
        assert recorded[("qargo", "stops", "pickup_country")]["disposition"] == "deferred"

    def test_family_decisions_survive_a_redraft(self, tmp_path):
        hub = self._family_hub(tmp_path)
        sheet = build_decision_sheet(hub)
        next(f for f in sheet["families"] if f["family"] == "pickup")["decision"] = "deferred"
        write_decision_sheet(hub, sheet)
        path = write_decision_sheet(hub, build_decision_sheet(hub))
        saved = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert next(f for f in saved["families"] if f["family"] == "pickup")["decision"] == "deferred"

    def test_family_of_handles_camel_and_snake(self):
        from kairos_ontology.core.gap_decisions import family_of

        assert family_of("pickup_location_city") == "pickup"
        assert family_of("PickupLocationCity") == "pickup"
        assert family_of("") == ""
