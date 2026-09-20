# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Alignment evidence is a requirement, not a condition (DD-234 §2.1).

Reproduces the three states measured on a real hub, where only the *readability* of the
gate's input varied::

    healthy                      661 undecided columns   -> blocked, correctly
    one *-alignment.yaml broken  405 undecided columns   -> blocked, 256 columns unseen
    _analysis/ deleted             0 undecided columns   -> PASSED CLEAN

No exception was raised in any of them. ``build_alignment_report`` degrades gracefully
by design -- right for a report, a category error underneath a gate -- so "no findings"
and "nothing was read" reached the caller indistinguishable, and the cheapest way past
the strongest gate in the toolkit was to not generate its evidence.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from kairos_ontology.core.alignment_report import (
    alignment_evidence_gaps,
    build_alignment_report,
    sources_imported,
)

_ALIGNMENT = textwrap.dedent(
    """\
    schema_version: 1
    domain: roro
    tables:
      - system: src
        table: cargo
        ref_class: CargoItem
        columns:
          - column: GOODDESCRIPTION
            data_type: varchar(50)
            ref_class: CargoItem
            ref_property: cargoDescription
            alignment: matched
            confidence: 0.9
    """
)

_SOURCE_VOCABULARY = textwrap.dedent(
    """\
    system: src
    tables:
      - name: cargo
    """
)


def _hub(tmp_path: Path, *, with_sources: bool = True, with_analysis: bool = True) -> Path:
    sources = tmp_path / "integration" / "sources"
    if with_sources:
        system = sources / "src"
        system.mkdir(parents=True)
        (system / "src.yaml").write_text(_SOURCE_VOCABULARY, encoding="utf-8")
    if with_analysis:
        analysis = sources / "_analysis"
        analysis.mkdir(parents=True, exist_ok=True)
        (analysis / "roro-alignment.yaml").write_text(_ALIGNMENT, encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def _no_report_memo():
    """The report is memoized per (analysis_dir, hub_root); tmp_path makes each unique."""
    yield


class TestSourcesImported:
    """The scope test. A gate that fires where it cannot be cleared gets switched off."""

    def test_a_hub_with_an_imported_system_is_in_scope(self, tmp_path):
        assert sources_imported(_hub(tmp_path))

    def test_a_hub_with_no_sources_at_all_is_not(self, tmp_path):
        assert not sources_imported(_hub(tmp_path, with_sources=False))

    def test_the_analysis_output_is_not_mistaken_for_an_imported_system(self, tmp_path):
        """Otherwise the gate's own output would satisfy the gate."""
        hub = _hub(tmp_path, with_sources=False)
        assert not sources_imported(hub)

    def test_the_scaffolded_template_is_not_an_imported_system(self, tmp_path):
        """`init` writes it as an example; treating it as evidence would block a new hub."""
        template = tmp_path / "integration" / "sources" / "source-system-template"
        template.mkdir(parents=True)
        (template / "example.yaml").write_text("system: example\n", encoding="utf-8")
        assert not sources_imported(tmp_path)


class TestTheThreeMeasuredStates:
    def test_healthy_evidence_reports_no_gap(self, tmp_path):
        assert alignment_evidence_gaps(_hub(tmp_path)) == []

    def test_a_deleted_analysis_directory_is_an_error_not_a_clean_pass(self, tmp_path):
        """The row that mattered: the gate used to report zero findings and pass."""
        hub = _hub(tmp_path, with_analysis=False)

        gaps = alignment_evidence_gaps(hub)

        assert [gap.kind for gap in gaps] == ["missing-directory"]
        assert "propose-alignment" in gaps[0].remediation

    def test_an_unreadable_alignment_file_is_named(self, tmp_path):
        """405 of 661 columns went missing this way, with nothing said about it."""
        hub = _hub(tmp_path)
        (hub / "integration" / "sources" / "_analysis" / "roro-alignment.yaml").write_text(
            "domain: roro\n  bad: [indentation\n", encoding="utf-8"
        )

        gaps = alignment_evidence_gaps(hub)

        assert [gap.kind for gap in gaps] == ["unreadable-file"]
        assert "roro-alignment.yaml" in gaps[0].detail

    def test_an_empty_analysis_directory_is_an_error(self, tmp_path):
        hub = _hub(tmp_path, with_analysis=False)
        (hub / "integration" / "sources" / "_analysis").mkdir(parents=True)

        assert [gap.kind for gap in alignment_evidence_gaps(hub)] == ["no-alignment-files"]

    def test_a_hub_with_no_imported_sources_is_left_alone(self, tmp_path):
        """Nothing to align, so demanding alignment evidence would be a false stop."""
        assert alignment_evidence_gaps(_hub(tmp_path, with_sources=False, with_analysis=False)) == []


class TestTheReportRecordsWhatItCouldNotRead:
    """The gate can only ask because the report now answers in a structured way."""

    def test_an_unreadable_file_is_listed_not_only_narrated(self, tmp_path):
        hub = _hub(tmp_path)
        analysis = hub / "integration" / "sources" / "_analysis"
        (analysis / "broken-alignment.yaml").write_text("a: [unclosed\n", encoding="utf-8")

        report = build_alignment_report(analysis, hub_root=hub)

        assert report.unreadable == ["broken-alignment.yaml"]
        # The prose notice is kept: it is what a human reading the report sees.
        assert any("broken-alignment.yaml" in notice for notice in report.notices)

    def test_a_present_directory_says_so(self, tmp_path):
        hub = _hub(tmp_path)
        report = build_alignment_report(hub / "integration" / "sources" / "_analysis", hub_root=hub)
        assert report.analysis_dir_present is True

    def test_an_absent_directory_says_so(self, tmp_path):
        hub = _hub(tmp_path, with_analysis=False)
        report = build_alignment_report(hub / "integration" / "sources" / "_analysis", hub_root=hub)
        assert report.analysis_dir_present is False

    def test_one_broken_file_still_does_not_sink_the_rest_of_the_report(self, tmp_path):
        """The report keeps degrading gracefully; only the gate above it got stricter."""
        hub = _hub(tmp_path)
        analysis = hub / "integration" / "sources" / "_analysis"
        (analysis / "broken-alignment.yaml").write_text("a: [unclosed\n", encoding="utf-8")

        report = build_alignment_report(analysis, hub_root=hub)

        assert [domain.domain for domain in report.domains] == ["roro"]
