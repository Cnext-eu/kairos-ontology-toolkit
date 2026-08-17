# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""#525: what the pipeline withheld has to reach the terminal, not just a YAML file.

Two stages produce information no command printed. ``apply_auto_dispositions``
withholds a disposition whenever the alignment pass contradicts the rule — 114 of
them on the live hub — and the handler printed only ``written``, so the user saw a
smaller number with no explanation. ``anchor-tables`` can drop a source table out
of the pipeline entirely and its ``--help`` did not say so.

A withheld conflict is a column the pipeline was about to silence permanently and
did not. Silence is the one way it must not be reported.
"""

from click.testing import CliRunner

from kairos_ontology.cli.main import cli

CONFLICT = {
    "system": "qargo",
    "table": "packaging_transactions",
    "column": "transaction_timestamp",
    "domain": "customs",
    "reason": "operational",
    "withheld_disposition": "not-business-data",
    "conflict": "alignment maps it at 0.90 to eventDateTime",
    "evidence": ["mapped-elsewhere:eventDateTime@0.90"],
    "already_recorded_as": "not-business-data",
    "remediation": "Decide it explicitly: 'kairos-ontology source-disposition set ...'.",
}


def _run(monkeypatch, tmp_path, args, *, stats=None, sheet=None):
    from kairos_ontology.core import gap_decisions, hub_utils

    monkeypatch.setattr(hub_utils, "find_hub_root", lambda *a, **k: tmp_path)
    if stats is not None:
        monkeypatch.setattr(gap_decisions, "apply_auto_dispositions", lambda *a, **k: stats)
    if sheet is not None:
        monkeypatch.setattr(gap_decisions, "build_decision_sheet", lambda *a, **k: sheet)
    return CliRunner().invoke(cli, args)


def _stats(withheld, *, conflicts=None):
    return {
        "written": 12,
        "skipped_already_decided": 3,
        "by_reason": {"operational": 12},
        "withheld_conflicting": withheld,
        "conflicts": conflicts if conflicts is not None else [CONFLICT] * withheld,
    }


def _sheet(**summary):
    base = {
        "source_columns_covered": 1166,
        "column_names": 830,
        "decisions_to_make": 458,
        "families": 56,
        "loose_names": 402,
        "with_a_proposal": 16,
        "auto_disposition_conflicts": 0,
        "conflicts_already_recorded": 0,
        "schema_catalogue_tables_excluded": 0,
        "gap_columns_in_excluded_tables": 0,
    }
    base.update(summary)
    return {"summary": base, "families": [], "decisions": [], "conflicts": []}


class TestWithheldConflictsAreSurfaced:
    def test_auto_reports_what_it_withheld_and_how_to_settle_it(self, monkeypatch, tmp_path):
        result = _run(
            monkeypatch, tmp_path, ["draft-gap-decisions", "--auto", "--dry-run"],
            stats=_stats(114),
        )
        assert result.exit_code == 0, result.output
        assert "114" in result.output
        assert "WITHHELD" in result.output
        assert "conflicts:" in result.output, "name the block the user must open"
        assert "gap-decisions.yaml" in result.output
        assert "source-disposition set" in result.output, "the remediation, not just the count"

    def test_entries_written_before_the_cross_check_are_called_out(self, monkeypatch, tmp_path):
        """224 were written by an earlier run; those need re-reading, not deciding."""
        result = _run(
            monkeypatch, tmp_path, ["draft-gap-decisions", "--auto"],
            stats=_stats(2, conflicts=[CONFLICT, {**CONFLICT, "already_recorded_as": ""}]),
        )
        assert "1 further contradicted column(s) were already written" in result.output
        assert "NOT withheld" in result.output, (
            "must not read as though the earlier entries were blocked too"
        )
        assert "source-disposition clear" in result.output, (
            "re-reading is not the remediation; withdrawing the entry is"
        )

    def test_nothing_withheld_prints_no_warning(self, monkeypatch, tmp_path):
        result = _run(
            monkeypatch, tmp_path, ["draft-gap-decisions", "--auto"], stats=_stats(0)
        )
        assert result.exit_code == 0, result.output
        assert "WITHHELD" not in result.output

    def test_the_sheet_run_reports_the_conflicts_block(self, monkeypatch, tmp_path):
        result = _run(
            monkeypatch, tmp_path, ["draft-gap-decisions", "--dry-run"],
            sheet=_sheet(auto_disposition_conflicts=83, conflicts_already_recorded=70),
        )
        assert result.exit_code == 0, result.output
        assert "83 auto-disposition conflict(s)" in result.output
        assert "70 already" in result.output

    def test_the_sheet_run_accounts_for_screened_out_tables(self, monkeypatch, tmp_path):
        """#528's counterpart: honoured visibly, so a false positive is questionable."""
        result = _run(
            monkeypatch, tmp_path, ["draft-gap-decisions", "--dry-run"],
            sheet=_sheet(schema_catalogue_tables_excluded=4, gap_columns_in_excluded_tables=177),
        )
        assert "177" in result.output and "4 table(s)" in result.output
        assert "table-anchors.yaml" in result.output

    def test_a_clean_sheet_stays_quiet(self, monkeypatch, tmp_path):
        result = _run(monkeypatch, tmp_path, ["draft-gap-decisions", "--dry-run"], sheet=_sheet())
        assert "conflict(s)" not in result.output
        assert "table-anchors.yaml" not in result.output


class TestHelpTextDocumentsWhatTheCommandsDo:
    def test_anchor_tables_help_declares_that_it_can_drop_a_table(self):
        """A command that removes a source table from the pipeline must say so."""
        out = CliRunner().invoke(cli, ["anchor-tables", "--help"]).output
        assert "schema" in out and "excluded" in out
        assert "not-business-data" in out
        assert "--no-schema-catalogue-screen" in out, "and how to overrule it"
        assert "anchor_properties" in out and "anchor_column_overlap" in out
        assert "warning" in out

    def test_draft_gap_decisions_help_declares_the_withholding(self):
        out = CliRunner().invoke(cli, ["draft-gap-decisions", "--help"]).output
        assert "WITHHELD" in out
        assert "conflicts:" in out
        assert "DD-169" in out

class TestProposeAlignmentEscapeHatch:
    """#528 follow-up: the escape hatch is only real if the flag reaches the core.

    ``run_propose_alignment`` takes ``**kwargs``, so a misspelled or unforwarded
    parameter fails at run time, not import time, and a --help assertion would
    still pass. These pin the wiring itself.
    """

    def _forwarded(self, monkeypatch, argv):
        seen = {}

        def _fake(analysis_dir, sources_dir, catalog_path, output_dir, **kwargs):
            seen.update(kwargs)
            return []

        monkeypatch.setattr(
            "kairos_ontology.core.propose_alignment.run_propose_alignment", _fake
        )
        monkeypatch.setattr(
            "kairos_ontology.cli.sources.run_propose_alignment", _fake, raising=False
        )
        CliRunner().invoke(cli, argv)
        return seen

    def test_the_flag_is_forwarded_as_honour_table_exclusions(self, monkeypatch, tmp_path):
        seen = self._forwarded(
            monkeypatch,
            ["propose-alignment", "--no-schema-catalogue-screen",
             "--analysis", str(tmp_path), "--sources", str(tmp_path)],
        )
        assert seen, "monkeypatch never intercepted"
        assert seen.get("honour_table_exclusions") is False

    def test_honouring_the_screen_is_the_default(self, monkeypatch, tmp_path):
        seen = self._forwarded(
            monkeypatch,
            ["propose-alignment", "--analysis", str(tmp_path), "--sources", str(tmp_path)],
        )
        assert seen, "monkeypatch never intercepted"
        assert seen.get("honour_table_exclusions") is True

    def test_the_flag_is_documented(self):
        result = CliRunner().invoke(cli, ["propose-alignment", "--help"])
        assert result.exit_code == 0
        assert "--no-schema-catalogue-screen" in result.output
        assert "excluded_tables" in result.output, "say where the record lands"
