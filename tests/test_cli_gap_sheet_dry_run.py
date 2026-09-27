# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``draft-gap-decisions`` flag combinations that used to lose work silently (#1056).

``--accept-proposals --dry-run`` wrote the sheet before accepting, and counted only the
decisions already on disk, so a dry run changed the file and under-reported what it would
apply. ``--suggest`` next to ``--auto`` or ``--accept-proposals`` was dropped without a
word, and ``--suggest --dry-run`` paid for model calls and printed nothing of them.
"""

import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.source_disposition import load_dispositions


def _hub(tmp_path):
    analysis = tmp_path / "integration" / "sources" / "_analysis"
    analysis.mkdir(parents=True)
    (analysis / "party-alignment.yaml").write_text(
        yaml.safe_dump({"domain": "party", "tables": [
            {"system": "qargo", "table": f"t{i}", "ref_class": "C", "columns": [],
             "custom_columns": [{"column": "OrderNo", "data_type": "int"}]
             + ([{"column": "mystery", "data_type": "varchar"}] if i == 0 else [])}
            for i in range(3)
        ]}),
        encoding="utf-8",
    )
    return tmp_path


def _run(monkeypatch, hub, args):
    from kairos_ontology.core import hub_utils

    monkeypatch.setattr(hub_utils, "find_hub_root", lambda *a, **k: hub)
    return CliRunner().invoke(cli, ["draft-gap-decisions", *args])


def _sheet_path(hub):
    return hub / "integration" / "sources" / "_analysis" / "hub.gap-decisions.yaml"


class TestAcceptProposalsDryRun:
    def test_the_sheet_on_disk_is_untouched(self, monkeypatch, tmp_path):
        hub = _hub(tmp_path)
        assert _run(monkeypatch, hub, []).exit_code == 0
        # A comment no rewrite keeps: any write through safe_dump would drop it.
        before = b"# reviewer notes\n" + _sheet_path(hub).read_bytes()
        _sheet_path(hub).write_bytes(before)

        result = _run(monkeypatch, hub, ["--accept-proposals", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert _sheet_path(hub).read_bytes() == before
        assert load_dispositions(hub) == {}

    def test_it_counts_what_accepting_would_apply(self, monkeypatch, tmp_path):
        """Both names are accepted in memory, so all four columns would be written."""
        hub = _hub(tmp_path)
        assert _run(monkeypatch, hub, []).exit_code == 0

        result = _run(monkeypatch, hub, ["--accept-proposals", "--dry-run"])

        assert "would accept" in result.output
        assert "would apply 0 family + 2 name-level decision(s) to 4 source column(s)" in (
            result.output
        )

    def test_no_sheet_is_created_by_a_dry_run(self, monkeypatch, tmp_path):
        hub = _hub(tmp_path)

        result = _run(monkeypatch, hub, ["--accept-proposals", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert not _sheet_path(hub).exists()

    def test_without_dry_run_it_writes_and_applies(self, monkeypatch, tmp_path):
        hub = _hub(tmp_path)

        result = _run(monkeypatch, hub, ["--accept-proposals"])

        assert result.exit_code == 0, result.output
        assert "applied 0 family + 2 name-level decision(s) to 4 source column(s)" in (
            result.output
        )
        saved = yaml.safe_load(_sheet_path(hub).read_text(encoding="utf-8"))
        assert all(e["decided_by"] == "autopilot" for e in saved["decisions"])
        assert len(load_dispositions(hub)) == 4


class TestSuggestIsNotCombinable:
    def test_with_accept_proposals(self, monkeypatch, tmp_path):
        result = _run(monkeypatch, _hub(tmp_path), ["--suggest", "--accept-proposals"])

        assert result.exit_code == 2
        assert "--suggest" in result.output and "then run" in result.output

    def test_with_auto(self, monkeypatch, tmp_path):
        hub = _hub(tmp_path)

        result = _run(monkeypatch, hub, ["--suggest", "--auto"])

        assert result.exit_code == 2
        assert "--auto" in result.output
        assert not _sheet_path(hub).exists()


class TestSuggestDryRunShowsTheAnswers:
    def test_the_model_proposals_are_printed_not_written(self, monkeypatch, tmp_path):
        from kairos_ontology.core import ai_preflight, ai_provider, gap_decisions

        def fake_loose(sheet, **_kwargs):
            for entry in sheet["decisions"]:
                entry.update(proposed_disposition="deferred", reasoning="a  shipment\nkey")
                gap_decisions._stamp_model(entry, "abc")
            return {"names_described": len(sheet["decisions"]), "batches": 1}

        monkeypatch.setattr(ai_preflight, "require_ai_provider", lambda *a, **k: None)
        monkeypatch.setattr(ai_provider, "get_ai_client", lambda *a, **k: None)
        monkeypatch.setattr(ai_provider, "resolve_role_model", lambda *a, **k: "m")
        monkeypatch.setattr(
            gap_decisions, "suggest_family_dispositions",
            lambda *a, **k: {"families_described": 0, "flagged_incoherent": 0},
        )
        monkeypatch.setattr(gap_decisions, "suggest_loose_dispositions", fake_loose)
        hub = _hub(tmp_path)

        result = _run(monkeypatch, hub, ["--suggest", "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "2 model proposal(s), not written (--dry-run)" in result.output
        assert "party :: mystery -> deferred — a shipment key" in result.output
        assert not _sheet_path(hub).exists()
