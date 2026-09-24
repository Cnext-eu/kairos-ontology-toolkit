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

import json

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
    MAX_LOOSE_PER_CALL,
    AUTO_DISPOSITIONS,
    apply_auto_dispositions,
    apply_decision_sheet,
    build_decision_sheet,
    propose_for_group,
    suggest_family_dispositions,
    suggest_loose_dispositions,
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

    def test_table_grain_deferred_does_not_empty_the_sheet(self, tmp_path):
        """#948: the gate blocks on these columns, so the sheet must list them."""
        from kairos_ontology.core.alignment_report import undecided_gap_columns
        from kairos_ontology.core.source_disposition import record_disposition

        hub = self._hub_with_gaps(tmp_path)
        record_disposition(hub_root=hub, system="qargo", table="companies",
                           disposition="deferred", rationale="later", decided_by="user")

        sheet = build_decision_sheet(hub)

        gate = undecided_gap_columns(hub)
        assert gate, "a table-grain deferred must not satisfy the gate (#881)"
        assert sheet["summary"]["source_columns_covered"] == len(gate)

    @pytest.mark.parametrize("table_disposition", sorted(DISPOSITIONS))
    def test_sheet_and_gate_agree_for_every_table_disposition(self, tmp_path, table_disposition):
        """One rule decides a column, so the sheet can never drift from the gate again."""
        from kairos_ontology.core.alignment_report import undecided_gap_columns
        from kairos_ontology.core.source_disposition import record_disposition

        from kairos_ontology.core.source_disposition import DISPOSITIONS_RELPATH

        hub = self._hub_with_gaps(tmp_path)
        # Written directly: a hub upgraded from before #881 holds table-grain values,
        # `bound` among them, that record_disposition no longer accepts.
        (hub / DISPOSITIONS_RELPATH).write_text(yaml.safe_dump({"schema_version": 1, "tables": [
            {"system": "qargo", "table": "companies", "disposition": table_disposition},
        ]}), encoding="utf-8")
        record_disposition(hub_root=hub, system="qargo", table="companies",
                           column="OrderNo", disposition="blueprint-gap", rationale="r")

        covered = build_decision_sheet(hub)["summary"]["source_columns_covered"]
        assert covered == len(undecided_gap_columns(hub))

    def test_apply_leaves_an_already_decided_occurrence_alone(self, tmp_path):
        from kairos_ontology.core.source_disposition import record_disposition

        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (analysis / "party-alignment.yaml").write_text(
            yaml.safe_dump({"domain": "party", "tables": [
                {"system": "qargo", "table": f"t{i}", "ref_class": "C", "columns": [],
                 "custom_columns": [{"column": "OrderNo", "data_type": "int"}]}
                for i in range(2)
            ]}),
            encoding="utf-8",
        )
        sheet = build_decision_sheet(tmp_path)
        for entry in sheet["decisions"]:
            entry["decision"] = "blueprint-gap"
        write_decision_sheet(tmp_path, sheet)
        record_disposition(hub_root=tmp_path, system="qargo", table="t0", column="OrderNo",
                           disposition="deferred", rationale="human", decided_by="user")

        stats = apply_decision_sheet(tmp_path)

        assert stats["columns_written"] == 1
        assert stats["skipped_already_decided"] == 1
        recorded = load_dispositions(tmp_path)
        assert recorded[("qargo", "t0", "OrderNo")]["decided_by"] == "user"
        assert recorded[("qargo", "t1", "OrderNo")]["disposition"] == "blueprint-gap"

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
            "names_applied": 0, "families_applied": 0, "columns_written": 0,
            "skipped_already_decided": 0}

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
        """The aligner asking for a property is a claim that the data is real.

        The example must be a column the *operational* rule catches but `is_audit_named`
        does not, because an audit-named column is deliberately not rescued by a proposal
        (an audit column stays audit whatever the aligner says). `source_id` is exactly
        that: a pipeline identifier by name, so a proposed business property for it is a
        real disagreement worth surfacing.

        `owned_by_subco` used to serve here. #522 stopped the name predicate
        misclassifying it at all, so it never becomes a candidate and there is no conflict
        left to withhold -- covered below as its own case. This cross-check is the safety
        net, and fixing the root cause means the net legitimately catches less.
        """
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        write_alignment(analysis, "financial", "revenue_and_costs", [
            {"column": "source_id", "data_type": "varchar(max)",
             "proposed_local_property": {"name": "originatingSource",
                                         "on_class": "ResourceAllocation"}},
            {"column": "row_version", "data_type": "varchar(max)"},
        ])
        stats = apply_auto_dispositions(tmp_path)
        recorded = load_dispositions(tmp_path)
        assert ("qargo", "revenue_and_costs", "source_id") not in recorded
        assert ("qargo", "revenue_and_costs", "row_version") in recorded
        assert stats["withheld_conflicting"] == 1

    def test_a_business_relationship_is_no_longer_a_candidate_at_all(self, tmp_path):
        """#522: `owned_by_subco` is not audit-named, so it never reaches the cross-check.

        Before, a bare `_by` substring match made it a candidate and #521's cross-check had
        to rescue it. Not being classified in the first place is the stronger outcome --
        the cross-check only fires when the aligner happens to have said something.
        """
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        write_alignment(analysis, "financial", "revenue_and_costs", [
            {"column": "owned_by_subco", "data_type": "bit"},
        ])
        stats = apply_auto_dispositions(tmp_path)

        assert ("qargo", "revenue_and_costs", "owned_by_subco") not in load_dispositions(tmp_path)
        assert stats["withheld_conflicting"] == 0

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


class TestSchemaCatalogueTablesAreHonoured:
    """#528: the anchoring screen's exclusions are a pipeline-level fact.

    A table that lists another table's columns is not business data, so a column
    of it cannot be a real disagreement between the rule and the alignment pass.
    On the live hub 26 of 109 reported conflicts were rows of two sheets of a
    "Qargo Tables Columns Info" workbook, and both sat at the top of the list.
    """

    CATALOGUE = "Qargo Tables Columns Info__orders_table"

    def _hub(self, tmp_path, *, excluded=True):
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (analysis / "booking-alignment.yaml").write_text(
            yaml.safe_dump({"domain": "booking", "tables": [
                {
                    "system": "qargo", "table": table, "ref_class": "Order",
                    # A confident mapping of an audit-named column is a conflict.
                    "columns": [{"column": "created_at", "data_type": "datetime",
                                 "confidence": 0.91, "ref_property": "placedOn"}],
                    "custom_columns": [
                        {"column": "created_at", "data_type": "datetime"},
                        {"column": "destination_reference", "data_type": "varchar(max)"},
                    ],
                }
                for table in ("orders", self.CATALOGUE)
            ]}),
            encoding="utf-8",
        )
        if excluded:
            (analysis / "table-anchors.yaml").write_text(
                yaml.safe_dump({
                    "schema_version": 1, "tables": [], "unanchored": [],
                    "excluded": [{
                        "system": "qargo", "table": self.CATALOGUE, "columns": 121,
                        "disposition": "not-business-data",
                        "reason": "sheet of 'Qargo Tables Columns Info', shown to be a "
                                  "schema catalogue by sibling sheet",
                    }],
                }),
                encoding="utf-8",
            )
        return tmp_path

    def test_a_conflict_inside_an_excluded_table_is_not_reported(self, tmp_path):
        from kairos_ontology.core.gap_decisions import find_disposition_conflicts

        unscreened = find_disposition_conflicts(self._hub(tmp_path, excluded=False))
        assert {c.table for c in unscreened} == {"orders", self.CATALOGUE}

        conflicts = find_disposition_conflicts(self._hub(tmp_path / "screened"))
        assert [c.table for c in conflicts] == ["orders"], (
            "a row of a table that lists another table's columns is not a column "
            "of a business entity, so the two stages cannot disagree about it"
        )

    def test_the_unscreened_set_stays_reachable(self, tmp_path):
        """An empty mapping is the explicit 'show me everything' escape hatch."""
        from kairos_ontology.core.gap_decisions import find_disposition_conflicts

        hub = self._hub(tmp_path)
        assert len(find_disposition_conflicts(hub, excluded_tables={})) == 2

    def test_the_screen_does_not_reach_past_the_tables_it_named(self, tmp_path):
        """Only the recorded (system, table) pairs are skipped, not a name prefix."""
        from kairos_ontology.core.gap_decisions import find_disposition_conflicts

        conflicts = find_disposition_conflicts(
            self._hub(tmp_path), excluded_tables={("qlik", self.CATALOGUE): "other system"}
        )
        assert {c.table for c in conflicts} == {"orders", self.CATALOGUE}

    def test_the_withheld_count_drops_with_the_noise(self, tmp_path):
        """The conflicts feed the withholding, so the noise inflated that too."""
        hub = self._hub(tmp_path)
        stats = apply_auto_dispositions(hub, dry_run=True)
        assert stats["withheld_conflicting"] == 1
        assert len(stats["conflicts"]) == 1

    def test_the_sheet_counts_excluded_table_columns_rather_than_hiding_them(self, tmp_path):
        """Honoured visibly. The DD-169 gate still counts these columns undecided,
        so dropping them from the sheet would strand them with no bulk route to a
        decision — and would hide a false positive in the screen itself."""
        sheet = build_decision_sheet(self._hub(tmp_path))
        summary = sheet["summary"]
        assert summary["auto_disposition_conflicts"] == 1
        assert summary["schema_catalogue_tables_excluded"] == 1
        assert summary["gap_columns_in_excluded_tables"] == 1
        tables = {t for entry in sheet["decisions"] for t in entry["tables"]}
        assert any(self.CATALOGUE in t for t in tables), "counted, not vanished"
        assert "excluded" in sheet["how_to_use"] and "--table" in sheet["how_to_use"]

    def test_a_hub_without_an_anchors_artifact_is_unaffected(self, tmp_path):
        summary = build_decision_sheet(self._hub(tmp_path, excluded=False))["summary"]
        assert summary["schema_catalogue_tables_excluded"] == 0
        assert summary["gap_columns_in_excluded_tables"] == 0


# ---------------------------------------------------------------------------
# Drafted extension properties reach the sheet (issue #880)
# ---------------------------------------------------------------------------


def _unmapped(column: str, table: str, proposal: dict | None = None) -> UnmappedColumn:
    return UnmappedColumn(
        system="src",
        table=table,
        column=column,
        domain="roro",
        data_type="string",
        reason="no reference property",
        suggestion="",
        recommended_disposition="",
        proposal=proposal or {},
    )


def _group(column: str, *occurrences: UnmappedColumn) -> GapGroup:
    group = GapGroup(column=column)
    group.occurrences.extend(occurrences)
    return group


class TestDraftedPropertyReachesTheSheet:
    """propose-alignment's proposed_local_property must not stop at the gap sheet."""

    def test_drafted_property_is_carried_into_the_entry(self):
        proposal = {
            "name": "vesselClass",
            "range": "xsd:string",
            "on_class": "Vessel",
            "why": "Hull class not represented in the reference model.",
        }
        group = _group("VESSELCLASS", _unmapped("VESSELCLASS", "ships", proposal))

        drafted = propose_for_group(group, "vessel-maritime")

        assert drafted.suggested_properties == [proposal]
        assert drafted.to_entry()["suggested_properties"] == [proposal]

    def test_a_drafted_property_proposes_registered_extension(self):
        group = _group(
            "VESSELCLASS",
            _unmapped("VESSELCLASS", "ships", {"name": "vesselClass", "range": "xsd:string",
                                               "on_class": "Vessel", "why": "..."}),
        )

        drafted = propose_for_group(group, "vessel-maritime")

        assert drafted.proposed_disposition == "registered-extension"
        assert "vesselClass" in drafted.reasoning
        assert "Vessel" in drafted.reasoning
        # A proposal is never a decision.
        assert drafted.to_entry()["decision"] == ""

    def test_divergent_proposals_are_shown_not_averaged(self):
        group = _group(
            "FLAG",
            _unmapped("FLAG", "a", {"name": "animalProductIndicator", "range": "xsd:boolean",
                                    "on_class": "CargoItem", "why": "..."}),
            _unmapped("FLAG", "b", {"name": "containsAnimalProducts", "range": "xsd:boolean",
                                    "on_class": "CargoItem", "why": "..."}),
        )

        drafted = propose_for_group(group, "roro")

        assert len(drafted.suggested_properties) == 2
        assert "animalProductIndicator" in drafted.reasoning
        assert "containsAnimalProducts" in drafted.reasoning
        assert "more than one reading" in drafted.reasoning

    def test_no_drafted_property_still_leaves_the_decision_open(self):
        group = _group("MYSTERY", _unmapped("MYSTERY", "a"))

        drafted = propose_for_group(group, "roro")

        assert drafted.proposed_disposition == ""
        assert drafted.suggested_properties == []

    def test_rule_branches_still_win_over_the_extension_proposal(self):
        """A free-text column keeps its rule disposition even with a drafted property."""
        group = _group(
            "CARGO_REMARK",
            _unmapped("CARGO_REMARK", "a", {"name": "remarkText", "range": "xsd:string",
                                       "on_class": "CargoItem", "why": "..."}),
        )

        drafted = propose_for_group(group, "roro")

        assert drafted.proposed_disposition == "not-business-data"
        # ...and still shows the reviewer what was drafted.
        assert drafted.suggested_properties[0]["name"] == "remarkText"


# ---------------------------------------------------------------------------
# Unseparated numbered repeating groups (issue #882)
# ---------------------------------------------------------------------------


from kairos_ontology.core.gap_decisions import family_of, group_into_families


class TestNumberedRepeatingGroups:
    """`ADDRESS_1` grouped and `ADDRESS1` did not, for one concept either way."""

    def test_a_trailing_index_is_not_part_of_the_stem(self):
        assert family_of("EQUIPMENTTYPE1") == "equipmenttype"
        assert family_of("EQUIPMENTTYPE14") == "equipmenttype"
        assert family_of("ADDRESS2") == "address"

    def test_it_agrees_with_the_separated_spelling(self):
        assert family_of("EQUIPMENTTYPE1") == family_of("EQUIPMENTTYPE_1")

    def test_an_unseparated_group_now_forms_one_decision(self):
        members = [
            propose_for_group(group(f"EQUIPMENTTYPE{n}"), "reference-data")
            for n in range(1, 15)
        ]

        families, loose = group_into_families(members)

        assert [f["family"] for f in families] == ["equipmenttype"]
        assert families[0]["distinct_names"] == 14
        assert loose == []

    def test_a_standards_number_is_not_a_stem(self):
        """ISO6346, UN1234: too few letters before the digits to be a repeating group."""
        assert family_of("ISO6346") == "iso6346"
        assert family_of("UN1234") == "un1234"
        assert family_of("A1") == "a1"

    def test_digits_inside_a_name_are_left_alone(self):
        assert "co2" in family_of("CO2EMISSIONS")

    def test_three_standards_numbers_do_not_become_a_family(self):
        members = [
            propose_for_group(group(name), "dangerous-goods")
            for name in ("ISO6346", "ISO668", "ISO1496")
        ]

        families, loose = group_into_families(members)

        assert families == []
        assert len(loose) == 3


# ---------------------------------------------------------------------------
# The business vocabulary reaches disposition evaluation (issue #885)
# ---------------------------------------------------------------------------


GLOSSARY_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix glossary: <https://example.com/glossary#> .

glossary:Allocation a skos:Concept ;
    skos:prefLabel "Allocation"@en ;
    skos:definition "A verbal agreement giving a customer a set number of places on a ship."@en .

glossary:Berth a skos:Concept ;
    skos:prefLabel "Berth"@en ;
    skos:definition "A designated location in a port used for mooring vessels."@en .
"""


class TestGlossaryReachesDispositionEvaluation:
    """Naming a concept the client has already named needs their vocabulary."""

    def _sheet(self):
        return {
            "families": [
                {
                    "family": "alloc",
                    "domain": "booking",
                    "distinct_names": 3,
                    "source_columns": 6,
                    "members": ["ALLOC_QTY", "ALLOC_REF", "ALLOC_STATUS"],
                    "decision": "",
                }
            ],
            "decisions": [],
        }

    def _captured_prompt(self, tmp_path, *, with_glossary):
        if with_glossary:
            bd = tmp_path / "businessdiscovery"
            bd.mkdir(parents=True)
            (bd / "acme-glossary.ttl").write_text(GLOSSARY_TTL, encoding="utf-8")

        captured = {}

        class _Client:
            class chat:  # noqa: N801 - mirrors the OpenAI client shape
                class completions:
                    @staticmethod
                    def create(**kwargs):
                        captured["prompt"] = kwargs["messages"][0]["content"]
                        raise RuntimeError("stop after capture")

        try:
            suggest_family_dispositions(
                self._sheet(),
                client=_Client(),
                model="test-model",
                hub_root=tmp_path if with_glossary else None,
            )
        except Exception:  # noqa: BLE001 - the capture raises on purpose
            pass
        return captured.get("prompt", "")

    def test_terms_and_definitions_are_in_the_prompt(self, tmp_path):
        prompt = self._captured_prompt(tmp_path, with_glossary=True)

        assert "BUSINESS'S OWN VOCABULARY" in prompt
        assert "Allocation" in prompt
        assert "set number of places on a ship" in prompt

    def test_a_hub_without_a_glossary_gets_no_block(self, tmp_path):
        prompt = self._captured_prompt(tmp_path, with_glossary=False)

        assert prompt
        assert "BUSINESS'S OWN VOCABULARY" not in prompt


class TestSuggestOnAFullyDecidedHub:
    """An empty sheet is success, not an error state (issue #889)."""

    def test_the_stats_shape_is_complete_when_there_is_nothing_to_describe(self):
        stats = suggest_family_dispositions(
            {"families": [], "decisions": []}, client=None, model="unused"
        )

        assert stats["families_described"] == 0
        assert stats["flagged_incoherent"] == 0


# ---------------------------------------------------------------------------
# The singletons get characterised too (issue #880)
# ---------------------------------------------------------------------------


class _CapturingClient:
    """Captures the prompt and replays a canned answer for every requested key."""

    def __init__(self, answer=None):
        self.prompts: list[str] = []
        self.schemas: list[dict] = []
        self._answer = answer or {"proposed_disposition": "registered-extension",
                                  "reasoning": "a real business fact"}
        outer = self

        class _Completions:
            @staticmethod
            def create(**kwargs):
                outer.prompts.append(kwargs["messages"][0]["content"])
                schema = kwargs["response_format"]["json_schema"]["schema"]
                outer.schemas.append(schema)
                keys = schema["properties"]["columns"]["required"]
                payload = {"columns": {key: dict(outer._answer) for key in keys}}

                class _Message:
                    content = json.dumps(payload)

                class _Choice:
                    message = _Message()

                class _Response:
                    choices = [_Choice()]

                return _Response()

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _loose_sheet(count=3, **overrides):
    decisions = []
    for index in range(count):
        entry = {
            "column": f"MYSTERY_{index}",
            "domain": "roro",
            "decision": "",
            "proposed_disposition": "",
            "reasoning": "No rule applies.",
            "occurrences": 1,
            "tables": ["src.cargo"],
            "data_types": ["string"],
        }
        entry.update(overrides)
        decisions.append(entry)
    return {"families": [], "decisions": decisions}


class TestSuggestLooseDispositions:
    def test_a_name_with_no_proposal_is_characterised(self):
        sheet = _loose_sheet(2)
        client = _CapturingClient()

        stats = suggest_loose_dispositions(sheet, client=client, model="m")

        assert stats["names_described"] == 2
        assert all(e["proposed_disposition"] == "registered-extension" for e in sheet["decisions"])
        assert all(e["reasoning"] == "a real business fact" for e in sheet["decisions"])

    def test_it_never_fills_the_decision(self):
        """The same contract the families call honours: propose, never decide."""
        sheet = _loose_sheet(2)

        suggest_loose_dispositions(sheet, client=_CapturingClient(), model="m")

        assert all(e["decision"] == "" for e in sheet["decisions"])

    def test_a_name_a_rule_already_decided_is_not_re_asked(self):
        """Re-asking would spend a call to second-guess a deterministic answer."""
        sheet = _loose_sheet(2, proposed_disposition="not-business-data")
        client = _CapturingClient()

        stats = suggest_loose_dispositions(sheet, client=client, model="m")

        assert stats["names_described"] == 0
        assert client.prompts == []

    def test_an_already_decided_name_is_not_re_asked(self):
        sheet = _loose_sheet(2, decision="deferred")

        stats = suggest_loose_dispositions(sheet, client=_CapturingClient(), model="m")

        assert stats["names_described"] == 0

    def test_an_empty_sheet_makes_no_call(self):
        client = _CapturingClient()

        stats = suggest_loose_dispositions(
            {"families": [], "decisions": []}, client=client, model="m"
        )

        assert stats == {"names_described": 0, "batches": 0}
        assert client.prompts == []

    def test_large_lists_are_batched_not_truncated(self):
        """A strict response_format names every key in `required`, so an unbounded list
        would build a schema no provider accepts — and a name the reviewer never sees is
        the failure this gate exists to prevent."""
        sheet = _loose_sheet(MAX_LOOSE_PER_CALL + 5)
        client = _CapturingClient()

        stats = suggest_loose_dispositions(sheet, client=client, model="m")

        assert stats["batches"] == 2
        assert stats["names_described"] == MAX_LOOSE_PER_CALL + 5
        assert len(client.prompts) == 2

    def test_the_drafted_property_is_offered_as_evidence(self):
        sheet = _loose_sheet(1)
        sheet["decisions"][0]["suggested_properties"] = [
            {"name": "vesselClass", "range": "xsd:string", "on_class": "Vessel"}
        ]
        client = _CapturingClient()

        suggest_loose_dispositions(sheet, client=client, model="m")

        assert "aligner drafted property: vesselClass" in client.prompts[0]

    def test_an_empty_disposition_is_accepted_as_an_answer(self):
        """"I cannot read this abbreviation" is a better answer than a guess."""
        sheet = _loose_sheet(1)
        client = _CapturingClient(
            answer={"proposed_disposition": None, "reasoning": "an opaque legacy code"}
        )

        suggest_loose_dispositions(sheet, client=client, model="m")

        assert sheet["decisions"][0]["proposed_disposition"] == ""
        assert sheet["decisions"][0]["reasoning"] == "an opaque legacy code"
