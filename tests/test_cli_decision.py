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


def test_decision_new_accepted_without_materiality_fails_fast(tmp_path, monkeypatch):
    _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli, ["decision", "new", "--title", "T", "--decision-state", "Accepted"]
    )

    assert result.exit_code != 0
    assert "--materiality" in result.output
    # The error should name the valid choices so the fix is actionable.
    assert "evidence-conflict" in result.output
    # No half-written record should have been left behind.
    assert not (tmp_path / "ontology-hub" / "decisions").exists()


def test_decision_new_accepted_with_materiality_succeeds(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        [
            "decision",
            "new",
            "--title",
            "T",
            "--decision-state",
            "Accepted",
            "--materiality",
            "evidence-conflict",
        ],
    )

    assert result.exit_code == 0, result.output
    decisions_path = hub / "decisions"
    records = _decision_records(decisions_path)
    assert len(records) == 1
    frontmatter_text = records[0].read_text(encoding="utf-8")
    assert "materiality:" in frontmatter_text
    assert "evidence-conflict" in frontmatter_text
    record = validate_decision_bundle(decisions_path).records[0]
    assert record.materiality == ("evidence-conflict",)


def test_decision_new_accepted_with_multiple_materiality(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        [
            "decision",
            "new",
            "--title",
            "T",
            "--decision-state",
            "Accepted",
            "--materiality",
            "evidence-conflict",
            "--materiality",
            "persistent-consequence",
        ],
    )

    assert result.exit_code == 0, result.output
    decisions_path = hub / "decisions"
    record = validate_decision_bundle(decisions_path).records[0]
    assert set(record.materiality) == {"evidence-conflict", "persistent-consequence"}


def test_decision_new_proposed_without_materiality_still_allowed(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["decision", "new", "--title", "T"])

    assert result.exit_code == 0, result.output
    decisions_path = hub / "decisions"
    assert len(_decision_records(decisions_path)) == 1


def test_decision_sync_index_refreshes_stale_state(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    created = runner.invoke(
        cli, ["decision", "new", "--id", "HUB-DD-20260101-stale", "--title", "T"]
    )
    assert created.exit_code == 0, created.output

    decisions_path = hub / "decisions"
    record_path = decisions_path / "HUB-DD-20260101-stale.md"
    frontmatter_text = record_path.read_text(encoding="utf-8")
    assert "decision_state: Proposed" in frontmatter_text

    index_path = decisions_path / "index.md"
    assert "Proposed" in index_path.read_text(encoding="utf-8")

    # Hand-edit the record's frontmatter directly on disk (bypassing the CLI),
    # simulating the real-world scenario where a record is accepted after the
    # fact but nothing regenerates the index.
    record_path.write_text(
        frontmatter_text.replace("decision_state: Proposed", "decision_state: Accepted"),
        encoding="utf-8",
    )

    # index.md is now stale: it still reports the pre-edit state.
    stale_index_text = index_path.read_text(encoding="utf-8")
    assert "Proposed" in stale_index_text
    assert "Accepted" not in stale_index_text

    result = runner.invoke(cli, ["decision", "sync-index"])

    assert result.exit_code == 0, result.output
    assert str(index_path) in result.output
    refreshed_index_text = index_path.read_text(encoding="utf-8")
    assert "Accepted" in refreshed_index_text
    assert "HUB-DD-20260101-stale" in refreshed_index_text

    # D4/#416c: the hand-edit above flipped decision_state to Accepted but left
    # the body untouched -- still the unedited scaffold TEMPLATE_BODY. That is
    # unambiguously wrong for an Accepted record (D1), so it must now surface
    # as an error (previously nothing caught this: _has_rejected_alternative is
    # fooled by the template's own placeholder row).
    after = validate_decision_bundle(decisions_path)
    assert any(e.code == "unedited_template_body" for e in after.errors)
    # sync-index itself only renders the index from records, so a validator
    # error does not fail the command -- but the diagnostic is now surfaced,
    # not silently discarded (D5).
    assert "unedited scaffold template" in result.output


def test_decision_sync_index_on_empty_hub_does_not_error(tmp_path, monkeypatch):
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["decision", "sync-index"])

    assert result.exit_code == 0, result.output
    index_path = hub / "decisions" / "index.md"
    assert index_path.exists()
    index_text = index_path.read_text(encoding="utf-8")
    assert "# Decision Log" in index_text


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


# ---------------------------------------------------------------------------
# Issue #466 — citation path resolution: hub-dir-prefixed repo-root-relative
# citations must resolve, and unresolved citations must include the base in the
# warning message.
# ---------------------------------------------------------------------------


def _make_managed_repo(root: Path) -> Path:
    """Create a hub inside a repo root with a managed marker so
    ``resolve_repo_root`` returns the repo root, not the hub itself."""
    (root / ".github").mkdir(parents=True)
    (root / ".github" / "copilot-instructions.md").write_text(
        "<!-- kairos-ontology-toolkit:managed -->", encoding="utf-8"
    )
    return _make_hub(root)


def test_decision_citation_hub_dir_prefixed_resolves_from_repo_root(tmp_path, monkeypatch):
    """A source citation like 'ontology-hub/integration/sources/x.pdf' must resolve
    when the file exists at hub_root/integration/sources/x.pdf (#466)."""
    hub = _make_managed_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    # Create a source file inside the hub.
    source_file = hub / "integration" / "sources" / "x.pdf"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("dummy", encoding="utf-8")

    runner = CliRunner()
    runner.invoke(
        cli,
        [
            "decision", "new",
            "--id", "HUB-DD-20260101-cite",
            "--title", "Cite",
            "--source", "ontology-hub/integration/sources/x.pdf",
        ],
    )
    decisions_path = hub / "decisions"
    records = _decision_records(decisions_path)
    assert len(records) == 1

    bundle = validate_decision_bundle(decisions_path)
    # No unresolved_source warning for the hub-dir-prefixed citation.
    assert not any(d.code == "unresolved_source" for d in bundle.diagnostics)


def test_decision_unresolved_citation_warning_includes_base(tmp_path, monkeypatch):
    """When a local citation does not resolve, the warning must include the base
    path so the user can diagnose the issue (#466)."""
    hub = _make_managed_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    runner.invoke(
        cli,
        [
            "decision", "new",
            "--id", "HUB-DD-20260101-bad",
            "--title", "Bad Cite",
            "--source", "integration/sources/nonexistent.pdf",
        ],
    )
    decisions_path = hub / "decisions"
    records = _decision_records(decisions_path)
    assert len(records) == 1

    bundle = validate_decision_bundle(decisions_path)
    unresolved = [d for d in bundle.diagnostics if d.code == "unresolved_source"]
    assert len(unresolved) == 1
    # The warning must include the base path.
    assert "base:" in unresolved[0].message
    assert "ontology-hub" in unresolved[0].message
