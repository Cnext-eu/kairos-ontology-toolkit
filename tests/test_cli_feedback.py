# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI tests for modeling-feedback commands (issue #588)."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.feedback_records import RECORD_GLOB, validate_feedback_bundle


def _make_hub(root: Path) -> Path:
    hub = root / "ontology-hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    return hub


def _insights_dir(repo_root: Path) -> Path:
    return repo_root / ".import" / "modeling" / "feedback"


def _feedback_records(insights_path: Path) -> list[Path]:
    return sorted(insights_path.glob(RECORD_GLOB))


def test_feedback_new_creates_valid_record_and_index_from_repo_root(tmp_path, monkeypatch):
    _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["feedback", "new", "--title", "T", "--area", "party", "--observation", "Obs."],
    )

    assert result.exit_code == 0, result.output
    insights_path = _insights_dir(tmp_path)
    records = _feedback_records(insights_path)
    assert len(records) == 1
    record = validate_feedback_bundle(insights_path).records[0]
    assert record.id == records[0].stem
    assert record.title == "T"
    assert record.area == "party"
    assert record.status == "open"
    index = insights_path / "index.md"
    assert index.exists()
    assert record.id in index.read_text(encoding="utf-8")
    assert validate_feedback_bundle(insights_path).errors == []


def test_feedback_new_accepts_explicit_id(tmp_path, monkeypatch):
    _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        [
            "feedback",
            "new",
            "--id",
            "HUB-FB-20260101-fixed",
            "--title",
            "X",
            "--observation",
            "Obs.",
        ],
    )

    assert result.exit_code == 0, result.output
    assert (_insights_dir(tmp_path) / "HUB-FB-20260101-fixed.md").exists()


def test_feedback_new_generates_distinct_ids_and_index_lists_both(tmp_path, monkeypatch):
    _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    first = runner.invoke(cli, ["feedback", "new", "--title", "A", "--observation", "Obs A"])
    second = runner.invoke(cli, ["feedback", "new", "--title", "B", "--observation", "Obs B"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    insights_path = _insights_dir(tmp_path)
    records = _feedback_records(insights_path)
    assert len(records) == 2
    assert records[0].stem != records[1].stem
    index_text = (insights_path / "index.md").read_text(encoding="utf-8")
    assert records[0].stem in index_text
    assert records[1].stem in index_text


def test_feedback_new_duplicate_explicit_id_fails(tmp_path, monkeypatch):
    _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(
        cli,
        ["feedback", "new", "--id", "HUB-FB-dup", "--title", "A", "--observation", "Obs A"],
    )

    result = runner.invoke(
        cli,
        ["feedback", "new", "--id", "HUB-FB-dup", "--title", "B", "--observation", "Obs B"],
    )

    assert result.exit_code != 0
    assert "already exists" in result.output


def test_feedback_commands_resolve_from_inside_hub(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    # _resolve_import_dir prefers an already-existing .import/businessdiscovery/
    # candidate; with none yet, it falls back to cwd. A hub scaffolded via
    # init/new-repo already has this directory at the repo root by the time a
    # user runs `feedback new`, so pre-create it here to match that real
    # precondition rather than an unscaffolded, artificial hub state.
    _insights_dir(tmp_path).mkdir(parents=True)
    monkeypatch.chdir(hub)
    runner = CliRunner()

    result = runner.invoke(cli, ["feedback", "new", "--title", "Inside", "--observation", "Obs."])

    assert result.exit_code == 0, result.output
    insights_path = _insights_dir(tmp_path)
    records = _feedback_records(insights_path)
    assert len(records) == 1
    assert records[0].stem in (insights_path / "index.md").read_text(encoding="utf-8")

    listed = runner.invoke(cli, ["feedback", "list"])
    assert listed.exit_code == 0, listed.output
    assert records[0].stem in listed.output


def test_feedback_resolve_sets_status_and_note(tmp_path, monkeypatch):
    _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    new_result = runner.invoke(
        cli, ["feedback", "new", "--title", "T", "--observation", "Obs."]
    )
    insights_path = _insights_dir(tmp_path)
    record_id = _feedback_records(insights_path)[0].stem

    result = runner.invoke(
        cli, ["feedback", "resolve", record_id, "--note", "Confirmed with business."]
    )

    assert result.exit_code == 0, result.output
    record = validate_feedback_bundle(insights_path).records[0]
    assert record.status == "resolved"
    assert "Confirmed with business." in record.body
    index_text = (insights_path / "index.md").read_text(encoding="utf-8")
    assert "resolved" in index_text
    assert new_result.exit_code == 0, new_result.output


def test_feedback_resolve_twice_fails_without_overwriting_first_note(tmp_path, monkeypatch):
    _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["feedback", "new", "--title", "T", "--observation", "Obs."])
    insights_path = _insights_dir(tmp_path)
    record_id = _feedback_records(insights_path)[0].stem
    runner.invoke(cli, ["feedback", "resolve", record_id, "--note", "First note."])

    second = runner.invoke(cli, ["feedback", "resolve", record_id, "--note", "Second note."])

    assert second.exit_code != 0
    assert "already resolved" in second.output
    record = validate_feedback_bundle(insights_path).records[0]
    assert "First note." in record.body
    assert "Second note." not in record.body


def test_feedback_resolve_missing_record_fails(tmp_path, monkeypatch):
    _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli, ["feedback", "resolve", "HUB-FB-does-not-exist", "--note", "N/A"]
    )

    assert result.exit_code != 0
    assert "No feedback record found" in result.output


def test_feedback_list_filters_by_status(tmp_path, monkeypatch):
    _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["feedback", "new", "--title", "Open one", "--observation", "Obs."])
    runner.invoke(cli, ["feedback", "new", "--title", "To resolve", "--observation", "Obs."])
    insights_path = _insights_dir(tmp_path)
    target = next(
        r for r in validate_feedback_bundle(insights_path).records if r.title == "To resolve"
    )
    runner.invoke(cli, ["feedback", "resolve", target.id, "--note", "Done."])

    open_listing = runner.invoke(cli, ["feedback", "list", "--status", "open"])
    resolved_listing = runner.invoke(cli, ["feedback", "list", "--status", "resolved"])

    assert open_listing.exit_code == 0, open_listing.output
    assert "Open one" in open_listing.output
    assert "To resolve" not in open_listing.output
    assert resolved_listing.exit_code == 0, resolved_listing.output
    assert "To resolve" in resolved_listing.output
    assert "Open one" not in resolved_listing.output


def test_feedback_sync_index_picks_up_hand_edited_status(tmp_path, monkeypatch):
    _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["feedback", "new", "--title", "T", "--observation", "Obs."])
    insights_path = _insights_dir(tmp_path)
    record_path = _feedback_records(insights_path)[0]
    text = record_path.read_text(encoding="utf-8")
    record_path.write_text(text.replace("status: open", "status: resolved"), encoding="utf-8")

    result = runner.invoke(cli, ["feedback", "sync-index"])

    assert result.exit_code == 0, result.output
    index_text = (insights_path / "index.md").read_text(encoding="utf-8")
    assert "resolved" in index_text


def test_feedback_records_are_not_business_discovery_documents(tmp_path, monkeypatch):
    """#591: feedback records live under .import/modeling/feedback/, not
    .import/businessdiscovery/ -- they are toolkit-managed OKF-style records, not raw
    client evidence, and must not surface as "unprocessed" business-discovery input
    (they have no matching extraction.yaml and never will, since they're never
    extracted -- they're already structured)."""
    from kairos_ontology.core.discovery_extraction import iter_discovery_documents

    _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)
    CliRunner().invoke(cli, ["feedback", "new", "--title", "T", "--observation", "Obs."])

    documents = iter_discovery_documents(tmp_path / ".import" / "businessdiscovery")
    names = {doc.name for doc in documents}
    assert not any(name.startswith("HUB-FB-") for name in names), names
