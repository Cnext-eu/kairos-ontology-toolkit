# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI tests for OKF Decision Log commands."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.decision_records import RECORD_GLOB, validate_decision_bundle


def _make_hub(root: Path) -> Path:
    hub = root / "ontology-hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    return hub


def _decision_records(decisions_path: Path) -> list[Path]:
    return sorted(decisions_path.glob(RECORD_GLOB))


def test_decision_new_creates_valid_record_and_index_from_repo_root(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["decision", "new", "--title", "T", "--domain", "d"])

    assert result.exit_code == 0, result.output
    decisions_path = hub / "decisions"
    records = _decision_records(decisions_path)
    assert len(records) == 1
    record = validate_decision_bundle(decisions_path).records[0]
    assert record.id == records[0].stem
    assert record.title == "T"
    assert record.domain == "d"
    index = decisions_path / "index.md"
    assert index.exists()
    assert record.id in index.read_text(encoding="utf-8")
    assert validate_decision_bundle(decisions_path).errors == []


def test_decision_new_accepts_explicit_id(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["decision", "new", "--id", "HUB-DD-20260101-fixed", "--title", "X"],
    )

    assert result.exit_code == 0, result.output
    assert (hub / "decisions" / "HUB-DD-20260101-fixed.md").exists()


def test_decision_new_generates_distinct_ids_and_index_lists_both(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    first = runner.invoke(cli, ["decision", "new", "--title", "A"])
    second = runner.invoke(cli, ["decision", "new", "--title", "B"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    decisions_path = hub / "decisions"
    records = _decision_records(decisions_path)
    assert len(records) == 2
    assert records[0].stem != records[1].stem
    index_text = (decisions_path / "index.md").read_text(encoding="utf-8")
    assert records[0].stem in index_text
    assert records[1].stem in index_text


def test_decision_commands_resolve_from_inside_hub(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(hub)
    runner = CliRunner()

    result = runner.invoke(cli, ["decision", "new", "--title", "Inside"])

    assert result.exit_code == 0, result.output
    decisions_path = hub / "decisions"
    records = _decision_records(decisions_path)
    assert len(records) == 1
    assert (hub / "ontology-hub" / "decisions").exists() is False
    assert records[0].stem in (decisions_path / "index.md").read_text(encoding="utf-8")

    listed = runner.invoke(cli, ["decision", "list"])
    assert listed.exit_code == 0, listed.output
    assert records[0].stem in listed.output


def test_decision_list_prints_created_ids(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["decision", "new", "--id", "HUB-DD-20260101-one", "--title", "One"])
    runner.invoke(cli, ["decision", "new", "--id", "HUB-DD-20260101-two", "--title", "Two"])

    result = runner.invoke(cli, ["decision", "list"])

    assert result.exit_code == 0, result.output
    assert "HUB-DD-20260101-one" in result.output
    assert "HUB-DD-20260101-two" in result.output
    assert validate_decision_bundle(hub / "decisions").errors == []
