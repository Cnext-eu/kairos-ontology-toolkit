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


class TestAcceptProposals:
    """The explicit override: proposals become decisions, attributed honestly."""

    def _sheet(self):
        return {
            "families": [
                {"family": "pickup", "domain": "consignment", "decision": "",
                 "proposed_disposition": "deferred", "members": ["pickup_city"]},
                {"family": "notes", "domain": "party", "decision": "already-set",
                 "proposed_disposition": "deferred", "members": ["notes_text"]},
            ],
            "decisions": [
                {"column": "OrderNo", "domain": "booking", "decision": "",
                 "proposed_disposition": "blueprint-gap"},
                {"column": "mystery", "domain": "booking", "decision": "",
                 "proposed_disposition": ""},
            ],
        }

    def test_proposals_become_decisions(self):
        from kairos_ontology.core.gap_decisions import accept_proposals

        sheet = self._sheet()
        accept_proposals(sheet)
        assert sheet["families"][0]["decision"] == "deferred"
        assert sheet["decisions"][0]["decision"] == "blueprint-gap"

    def test_entries_without_a_proposal_default_to_deferred(self):
        """The only defensible blanket answer: visible, reversible, non-dismissive."""
        from kairos_ontology.core.gap_decisions import accept_proposals

        sheet = self._sheet()
        accept_proposals(sheet)
        assert sheet["decisions"][1]["decision"] == "deferred"

    def test_a_human_decision_is_never_overwritten(self):
        from kairos_ontology.core.gap_decisions import accept_proposals

        sheet = self._sheet()
        accept_proposals(sheet)
        assert sheet["families"][1]["decision"] == "already-set"
        assert "decided_by" not in sheet["families"][1]

    def test_accepted_entries_are_attributed_to_autopilot(self):
        from kairos_ontology.core.gap_decisions import accept_proposals

        sheet = self._sheet()
        accept_proposals(sheet)
        assert sheet["families"][0]["decided_by"] == "autopilot"

    def test_apply_records_the_given_attribution(self, tmp_path):
        """An agent accepting drafts must not be recorded as a human decision."""
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        write_alignment(analysis, "party", "companies",
                        [{"column": "OrderNo", "data_type": "int"}])
        sheet = build_decision_sheet(tmp_path)
        for entry in sheet["decisions"]:
            entry["decision"] = "deferred"
        write_decision_sheet(tmp_path, sheet)
        apply_decision_sheet(tmp_path, decided_by="autopilot")
        recorded = load_dispositions(tmp_path)
        assert all(e["decided_by"] == "autopilot" for e in recorded.values())


class TestBlueprintGapIsFramedAsPotential:
    """blueprint-gap means 'a reference-model defect to file upstream'. Recorded
    from a drafted proposal it is weaker: nobody has confirmed the model ought to
    have had the concept. The entry must say so."""

    def test_the_proposal_says_potential(self):
        p = propose_for_group(group("OrderNo", count=19, data_type="int"))
        assert p.proposed_disposition == "blueprint-gap"
        assert "POTENTIAL" in p.reasoning
        assert "not mapped yet" in p.reasoning or "no reference-model property" in p.reasoning

    def test_the_recorded_rationale_says_potential_and_not_confirmed(self, tmp_path):
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (analysis / "booking-alignment.yaml").write_text(
            yaml.safe_dump({"domain": "booking", "tables": [
                {"system": "qargo", "table": f"t{i}", "ref_class": "C", "columns": [],
                 "custom_columns": [{"column": "OrderNo", "data_type": "int"}]}
                for i in range(3)]}),
            encoding="utf-8")
        sheet = build_decision_sheet(tmp_path)
        for entry in sheet["decisions"]:
            entry["decision"] = "blueprint-gap"
        write_decision_sheet(tmp_path, sheet)
        apply_decision_sheet(tmp_path, decided_by="autopilot")

        rationale = load_dispositions(tmp_path)[("qargo", "t0", "OrderNo")]["rationale"]
        assert "POTENTIAL blueprint gap" in rationale
        assert "not as a confirmed reference-model defect" in rationale

    def test_deferred_records_that_the_data_is_real_and_unmapped(self, tmp_path):
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        write_alignment(analysis, "party", "companies",
                        [{"column": "some_field", "data_type": "varchar(max)"}])
        sheet = build_decision_sheet(tmp_path)
        for entry in sheet["decisions"]:
            entry["decision"] = "deferred"
        write_decision_sheet(tmp_path, sheet)
        apply_decision_sheet(tmp_path, decided_by="autopilot")
        rationale = load_dispositions(tmp_path)[("qargo", "companies", "some_field")]["rationale"]
        assert "not mapped yet" in rationale
        assert "known gap" in rationale


class TestAutoDispositionConflicts:
    """Issue #521. ``not-business-data`` is the one disposition that removes a
    column from the DD-169 gate instead of deferring it, so a false positive
    disappears rather than queueing. On the live hub the name rule silenced
    ``qargo.packaging_transactions.transaction_timestamp`` — the occurrence
    timestamp of a packaging movement — as 'created/updated/guid/hash/ingest
    metadata', while the alignment pass had independently mapped it at 0.90.
    The auto-disposition won because it ran first."""

    def _packaging_hub(self, tmp_path):
        """One domain maps the ledger's occurrence timestamp; another does not."""
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (analysis / "commercial-alignment.yaml").write_text(
            yaml.safe_dump({"domain": "commercial", "tables": [{
                "system": "qargo", "table": "packaging_transactions",
                "ref_class": "CommercialTransaction",
                "columns": [{
                    "column": "transaction_timestamp", "data_type": "datetime",
                    "alignment": "semantic", "confidence": 0.9,
                    "ref_property": "eventDateTime",
                }],
                "custom_columns": [],
            }]}),
            encoding="utf-8")
        (analysis / "customs-alignment.yaml").write_text(
            yaml.safe_dump({"domain": "customs", "tables": [{
                "system": "qargo", "table": "packaging_transactions", "ref_class": "C",
                "columns": [],
                "custom_columns": [
                    {"column": "transaction_timestamp", "data_type": "datetime",
                     "recommended_disposition": "skip"},
                    {"column": "last_ingest_date", "data_type": "varchar(max)",
                     "recommended_disposition": "skip"},
                ],
            }]}),
            encoding="utf-8")
        return tmp_path

    def test_an_occurrence_timestamp_is_withheld_not_silenced(self, tmp_path):
        hub = self._packaging_hub(tmp_path)
        stats = apply_auto_dispositions(hub)
        recorded = load_dispositions(hub)
        assert ("qargo", "packaging_transactions", "transaction_timestamp") not in recorded
        assert stats["withheld_conflicting"] == 1
        assert stats["written"] == 1, "the audit column is still decided by rule"

    def test_a_genuine_audit_column_is_still_recorded(self, tmp_path):
        """The narrowing must not disarm the rule: ingest metadata stays automatic."""
        hub = self._packaging_hub(tmp_path)
        apply_auto_dispositions(hub)
        entry = load_dispositions(hub)[("qargo", "packaging_transactions", "last_ingest_date")]
        assert entry["disposition"] == "not-business-data"
        assert entry["decided_by"] == "autopilot"

    def test_the_conflict_names_the_score_that_contradicts_it(self, tmp_path):
        from kairos_ontology.core.gap_decisions import find_disposition_conflicts

        conflicts = find_disposition_conflicts(self._packaging_hub(tmp_path))
        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.column == "transaction_timestamp"
        assert "0.90" in conflict.conflict and "eventDateTime" in conflict.conflict
        assert "packaging_transactions" in conflict.conflict, "the grain is the argument"
        assert conflict.would_record == "not-business-data"

    def test_a_confident_mapping_outranks_even_an_audit_name(self, tmp_path):
        """Whatever the column is called, two stages disagreeing is worth a reader."""
        from kairos_ontology.core.gap_decisions import find_disposition_conflicts

        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (analysis / "party-alignment.yaml").write_text(
            yaml.safe_dump({"domain": "party", "tables": [{
                "system": "qargo", "table": "companies", "ref_class": "TradeParty",
                "columns": [{"column": "created_at", "data_type": "datetime",
                             "confidence": 0.91, "ref_property": "registeredOn"}],
                "custom_columns": [{"column": "created_at", "data_type": "datetime"}],
            }]}),
            encoding="utf-8")
        assert [c.column for c in find_disposition_conflicts(tmp_path)] == ["created_at"]

    def test_a_mapping_below_the_floor_does_not_block_the_rule(self, tmp_path):
        """Under review itself, so it cannot outrank a disposition."""
        from kairos_ontology.core.gap_decisions import (
            MAPPED_CONFIDENCE_FLOOR,
            find_disposition_conflicts,
        )

        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (analysis / "party-alignment.yaml").write_text(
            yaml.safe_dump({"domain": "party", "tables": [{
                "system": "qargo", "table": "companies", "ref_class": "TradeParty",
                "columns": [{"column": "created_at", "data_type": "datetime",
                             "confidence": MAPPED_CONFIDENCE_FLOOR - 0.1,
                             "ref_property": "registeredOn"}],
                "custom_columns": [{"column": "created_at", "data_type": "datetime"}],
            }]}),
            encoding="utf-8")
        assert find_disposition_conflicts(tmp_path) == []
        apply_auto_dispositions(tmp_path)
        assert ("qargo", "companies", "created_at") in load_dispositions(tmp_path)

    def test_a_proposed_local_property_contradicts_no_business_meaning(self, tmp_path):
        """The aligner asking for a property is a claim that the data is real."""
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        write_alignment(analysis, "financial", "revenue_and_costs", [
            {"column": "owned_by_subco", "data_type": "bit",
             "proposed_local_property": {"name": "ownedBySubcontractor",
                                         "on_class": "ResourceAllocation"}},
            {"column": "created_by", "data_type": "varchar(max)"},
        ])
        stats = apply_auto_dispositions(tmp_path)
        recorded = load_dispositions(tmp_path)
        assert ("qargo", "revenue_and_costs", "owned_by_subco") not in recorded
        assert ("qargo", "revenue_and_costs", "created_by") in recorded
        assert stats["withheld_conflicting"] == 1

    def test_the_conflict_is_surfaced_in_the_decision_sheet(self, tmp_path):
        """Surfaced, not resolved in favour of whichever stage ran first."""
        sheet = build_decision_sheet(self._packaging_hub(tmp_path))
        assert sheet["summary"]["auto_disposition_conflicts"] == 1
        entry = sheet["conflicts"][0]
        assert entry["column"] == "transaction_timestamp"
        assert entry["withheld_disposition"] == "not-business-data"
        assert "source-disposition set" in entry["remediation"]
        assert "decision" not in entry, "a conflict is evidence, never a draft answer"

    def test_a_conflict_already_on_disk_is_flagged_for_re_reading(self, tmp_path):
        """224 entries were written before this check existed; they must be findable."""
        from kairos_ontology.core.source_disposition import record_disposition

        hub = self._packaging_hub(tmp_path)
        record_disposition(
            hub_root=hub, system="qargo", table="packaging_transactions",
            column="transaction_timestamp", disposition="not-business-data",
            rationale="created/updated/guid/hash/ingest metadata", decided_by="autopilot",
        )
        sheet = build_decision_sheet(hub)
        assert sheet["summary"]["conflicts_already_recorded"] == 1
        assert sheet["conflicts"][0]["already_recorded_as"] == "not-business-data"

    def test_conflicts_are_never_turned_into_decisions(self, tmp_path):
        """--accept-proposals fills drafts. A conflict is not a draft."""
        from kairos_ontology.core.gap_decisions import accept_proposals

        sheet = build_decision_sheet(self._packaging_hub(tmp_path))
        accept_proposals(sheet)
        assert all("decision" not in c for c in sheet["conflicts"])

    def test_audit_names_are_separated_from_occurrence_names(self):
        from kairos_ontology.core.gap_decisions import is_audit_named

        for audit in ("created_at", "updated_at", "last_ingest_date", "data_loaded_ts",
                      "row_version", "tenant_id", "record_hash", "created_by"):
            assert is_audit_named(audit), audit
        for business in ("transaction_timestamp", "settled_timestamp",
                         "pickup_start_timestamp", "owned_by_subco", "origin_timestamp"):
            assert not is_audit_named(business), business
