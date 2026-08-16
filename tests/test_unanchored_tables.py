# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unanchored-table detection and the anchor gate (DD-180).

An unanchored table is one alignment could not attach to any reference class.
The anchor is the frame: step 1 decides what the table *is*, step 2 maps its
columns to that class's properties. With no anchor, step 2 draws from the whole
pool with nothing to constrain it — measured on the live corpus, anchored tables
held 60-67% run-to-run stability and unanchored ones 30-44%, swinging between 26
and 8 mapped columns for identical input.

Nothing reported this. Two tables and 237 columns produced low-value output that
was indistinguishable from ordinary output downstream.
"""

import textwrap

import pytest
import yaml

from kairos_ontology.core.alignment_report import (
    UNANCHORED_STATUSES,
    build_alignment_report,
    domain_imports,
    find_anchor_candidates,
    render_unanchored_guidance,
    undecided_unanchored_tables,
)


def write_alignment(directory, domain, tables):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{domain}-alignment.yaml").write_text(
        yaml.safe_dump({"domain": domain, "tables": tables}), encoding="utf-8"
    )


def table(name, *, ref_class="", status="", columns=0, likely=""):
    entry = {
        "system": "src",
        "table": name,
        "ref_class": ref_class,
        "source_column_count": columns,
        "columns": [],
        "custom_columns": [],
    }
    if status:
        entry["ref_class_status"] = status
    if likely:
        entry["likely_entity"] = likely
    return entry


class TestDetection:
    def test_a_table_with_no_ref_class_is_unanchored(self, tmp_path):
        write_alignment(
            tmp_path,
            "consignment",
            [table("stops", status="unmatched", columns=120)],
        )
        report = build_alignment_report(tmp_path)
        assert len(report.unanchored) == 1
        assert report.unanchored[0].table == "stops"
        assert report.unanchored[0].columns == 120
        assert report.unanchored_columns == 120

    def test_an_anchored_table_is_not_reported(self, tmp_path):
        write_alignment(
            tmp_path, "consignment", [table("consignments", ref_class="Consignment", columns=122)]
        )
        assert build_alignment_report(tmp_path).unanchored == []

    @pytest.mark.parametrize("status", sorted(UNANCHORED_STATUSES))
    def test_both_failure_statuses_count(self, tmp_path, status):
        write_alignment(tmp_path, "d", [table("t", status=status, columns=5)])
        assert len(build_alignment_report(tmp_path).unanchored) == 1

    def test_widest_table_is_reported_first(self, tmp_path):
        write_alignment(
            tmp_path,
            "d",
            [
                table("narrow", status="unmatched", columns=4),
                table("wide", status="unmatched", columns=120),
            ],
        )
        assert [t.table for t in build_alignment_report(tmp_path).unanchored] == [
            "wide",
            "narrow",
        ]

    def test_column_count_falls_back_when_not_recorded(self, tmp_path):
        entry = table("t", status="unmatched")
        entry["columns"] = [{"column": "a"}, {"column": "b"}]
        entry["custom_columns"] = [{"column": "c"}]
        write_alignment(tmp_path, "d", [entry])
        assert build_alignment_report(tmp_path).unanchored[0].columns == 3


class TestAnchorCandidates:
    REF = {
        "TransportCall": "https://ex.org/dcsa/transport-call#",
        "Consignment": "https://ex.org/mmt/consignment#",
        "ConversionFactorBetweenUnits": "https://ex.org/omg/units/",
    }
    IMPORTS = {
        "consignment": {"https://ex.org/mmt/consignment#"},
        "route-schedule": {"https://ex.org/dcsa/transport-call#"},
    }

    def test_names_the_class_and_the_domain_that_has_it(self):
        found = find_anchor_candidates(
            "stops",
            "TransportCall",
            reference_classes=self.REF,
            imports_by_domain=self.IMPORTS,
            own_domain="consignment",
        )
        assert found[0] == (
            "TransportCall",
            "https://ex.org/dcsa/transport-call#",
            "route-schedule",
        )

    def test_a_class_the_domain_already_imports_is_not_the_explanation(self):
        """The model saw it and declined it — suggesting it back is noise."""
        found = find_anchor_candidates(
            "consignments",
            "Consignment",
            reference_classes=self.REF,
            imports_by_domain=self.IMPORTS,
            own_domain="consignment",
        )
        assert all(name != "Consignment" for name, _, _ in found)

    def test_plural_table_matches_singular_class(self):
        found = find_anchor_candidates(
            "stops",
            "",
            reference_classes={"Stop": "https://ex.org/m#"},
            imports_by_domain={},
            own_domain="d",
        )
        assert found and found[0][0] == "Stop"

    def test_a_module_some_domain_imports_ranks_above_an_orphan(self):
        """A boundary mismatch is likelier — and cheaper to fix — than vocabulary noise."""
        found = find_anchor_candidates(
            "empty units",
            "",
            reference_classes={
                "UnitsOfMeasure": "https://ex.org/orphan/",
                "TransportUnit": "https://ex.org/used#",
            },
            imports_by_domain={"other": {"https://ex.org/used#"}},
            own_domain="d",
        )
        assert found[0][0] == "TransportUnit"
        assert found[0][2] == "other"

    def test_no_shared_token_yields_nothing(self):
        assert (
            find_anchor_candidates(
                "widgets",
                "",
                reference_classes={"TransportCall": "https://ex.org/m#"},
                imports_by_domain={},
                own_domain="d",
            )
            == ()
        )

    def test_short_tokens_do_not_match(self):
        """Two-letter fragments would match almost anything."""
        assert (
            find_anchor_candidates(
                "t_x",
                "",
                reference_classes={"Tx": "https://ex.org/m#"},
                imports_by_domain={},
                own_domain="d",
            )
            == ()
        )


class TestDomainImports:
    def test_reads_real_imports_and_skips_commented_examples(self, tmp_path):
        ontologies = tmp_path / "ontology-hub" / "model" / "ontologies"
        ontologies.mkdir(parents=True)
        (ontologies / "consignment.ttl").write_text(
            textwrap.dedent(
                """\
                <https://h/ont/consignment> a owl:Ontology .
                <https://h/ont/consignment> owl:imports <https://ex.org/mmt/consignment#> .
                ##   owl:imports <https://h/ont/_foundation> ;
                """
            ),
            encoding="utf-8",
        )
        found = domain_imports(tmp_path)
        assert found == {"consignment": {"https://ex.org/mmt/consignment#"}}

    def test_missing_directory_is_not_an_error(self, tmp_path):
        assert domain_imports(tmp_path) == {}


class TestGuidanceRendering:
    def test_names_the_fix_not_just_the_problem(self):
        from kairos_ontology.core.alignment_report import UnanchoredTable

        text = render_unanchored_guidance(
            [
                UnanchoredTable(
                    domain="consignment",
                    system="src",
                    table="stops",
                    columns=120,
                    status="unmatched",
                    candidates=(("TransportCall", "https://ex.org/tc#", "route-schedule"),),
                )
            ]
        )
        assert "TransportCall" in text
        assert "route-schedule" in text
        assert "owl:imports" in text

    def test_a_genuine_gap_says_so(self):
        from kairos_ontology.core.alignment_report import UnanchoredTable

        text = render_unanchored_guidance(
            [UnanchoredTable("d", "src", "t", 10, "unmatched", candidates=())]
        )
        assert "blueprint gap" in text
        assert "out of scope" in text

    def test_empty_input_renders_nothing(self):
        assert render_unanchored_guidance([]) == ""


class TestGate:
    def _hub(self, tmp_path, status="unmatched"):
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        write_alignment(analysis, "consignment", [table("stops", status=status, columns=120)])
        return tmp_path

    def test_an_unanchored_table_blocks(self, tmp_path):
        assert len(undecided_unanchored_tables(self._hub(tmp_path))) == 1

    def test_a_recorded_disposition_clears_it(self, tmp_path):
        hub = self._hub(tmp_path)
        from kairos_ontology.core.source_disposition import record_disposition

        record_disposition(
            hub_root=hub,
            system="src",
            table="stops",
            disposition="not-business-data",
            rationale="staging artefact",
        )
        assert undecided_unanchored_tables(hub) == []

    def test_domain_scope_is_respected(self, tmp_path):
        hub = self._hub(tmp_path)
        assert undecided_unanchored_tables(hub, domains=["consignment"])
        assert undecided_unanchored_tables(hub, domains=["party"]) == []


class TestCandidateRanking:
    def test_unqualified_class_beats_a_modal_specialisation(self):
        """TransportCall is the suggestion; BargeTransportCall is a later refinement."""
        found = find_anchor_candidates(
            "stops",
            "TransportCall",
            reference_classes={
                "BargeTransportCall": "https://ex.org/tc#",
                "RailTransportCall": "https://ex.org/tc#",
                "TransportCall": "https://ex.org/tc#",
            },
            imports_by_domain={"route-schedule": {"https://ex.org/tc#"}},
            own_domain="consignment",
        )
        assert found[0][0] == "TransportCall"

    def test_more_overlap_still_wins_over_fewer_surplus_tokens(self):
        found = find_anchor_candidates(
            "transport call event",
            "",
            reference_classes={
                "Call": "https://ex.org/m#",
                "TransportCallEvent": "https://ex.org/m#",
            },
            imports_by_domain={"other": {"https://ex.org/m#"}},
            own_domain="d",
        )
        assert found[0][0] == "TransportCallEvent"
