# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the `guard-scope` deterministic workspace-scope guard."""

from __future__ import annotations

import subprocess
from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import cli


def _init_repo(repo_dir):
    subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, check=True)
    (repo_dir / "model").mkdir()
    (repo_dir / "model" / "ontologies").mkdir()
    tracked = repo_dir / "model" / "ontologies" / "booking.ttl"
    tracked.write_text("initial", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo_dir, check=True)
    return tracked


def test_snapshot_writes_token_path(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["guard-scope", "--snapshot"])

    assert result.exit_code == 0
    token_path = Path(result.output.strip())
    assert token_path.is_absolute()
    assert token_path.exists()
    assert tmp_path not in token_path.parents  # token lives outside the repo, in OS temp


def test_check_passes_with_only_allowed_change(tmp_path, monkeypatch):
    tracked = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    snapshot = CliRunner().invoke(cli, ["guard-scope", "--snapshot"])
    token = snapshot.output.strip()

    tracked.write_text("changed", encoding="utf-8")

    check = CliRunner().invoke(
        cli,
        ["guard-scope", "--check-since", token, "--allow", "model/ontologies/booking.ttl"],
    )

    assert check.exit_code == 0
    assert "passed" in check.output
    assert not Path(token).exists()  # token cleaned up on success


def test_check_fails_on_extra_untracked_file_outside_allowlist(tmp_path, monkeypatch):
    tracked = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    snapshot = CliRunner().invoke(cli, ["guard-scope", "--snapshot"])
    token = snapshot.output.strip()

    tracked.write_text("changed", encoding="utf-8")
    (tmp_path / "unexpected.txt").write_text("surprise", encoding="utf-8")

    check = CliRunner().invoke(
        cli,
        ["guard-scope", "--check-since", token, "--allow", "model/ontologies/booking.ttl"],
    )

    assert check.exit_code != 0
    assert "unexpected.txt" in check.output


def test_check_fails_on_extra_modified_tracked_file_outside_allowlist(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    other_file = tmp_path / "other.txt"
    other_file.write_text("original", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add other"], cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)

    snapshot = CliRunner().invoke(cli, ["guard-scope", "--snapshot"])
    token = snapshot.output.strip()

    other_file.write_text("unexpectedly modified", encoding="utf-8")

    check = CliRunner().invoke(
        cli,
        ["guard-scope", "--check-since", token, "--allow", "model/ontologies/booking.ttl"],
    )

    assert check.exit_code != 0
    assert "other.txt" in check.output


def test_check_passes_with_no_changes_and_no_allow(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    snapshot = CliRunner().invoke(cli, ["guard-scope", "--snapshot"])
    token = snapshot.output.strip()

    check = CliRunner().invoke(cli, ["guard-scope", "--check-since", token])

    assert check.exit_code == 0


def test_requires_exactly_one_mode(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    neither = CliRunner().invoke(cli, ["guard-scope"])
    assert neither.exit_code == 2
    assert "exactly one" in neither.output


def test_allow_without_check_since_rejected(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["guard-scope", "--snapshot", "--allow", "*.ttl"])
    assert result.exit_code == 2
    assert "only valid with --check-since" in result.output
