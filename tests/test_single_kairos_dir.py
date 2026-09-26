# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""One ``.kairos/`` folder per repository (#1038).

Run logs went to ``ontology-hub/.kairos/logs`` while ``update`` wrote its refresh
transcript to ``<repo>/.kairos``, so a scaffolded hub had two ``.kairos`` folders and the
run logs sat in the one nobody looked in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.cli.run_log import (
    ensure_kairos_dir,
    legacy_run_log_directory,
    newest_run_log,
    run_log_directory,
)
from kairos_ontology.cli.shared import upgrade_refresh_log_path

_ENV = {"KAIROS_SKILL_CONTEXT": "1"}


@pytest.fixture
def repo(tmp_path) -> Path:
    """The scaffolded layout: the toolkit pin at the root, the hub one level down."""
    root = tmp_path / "repo"
    (root / "ontology-hub" / "model" / "ontologies").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["kairos-ontology-toolkit"]\n', encoding="utf-8"
    )
    return root.resolve()


def _log(directory: Path, name: str, command: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    record = {"timestamp": name[:16], "event": "run.summary", "kairos.command": command}
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    return path


class TestOneLocation:
    def test_run_logs_live_at_the_repository_root(self, repo):
        assert run_log_directory(repo / "ontology-hub") == repo / ".kairos" / "logs"

    def test_the_refresh_transcript_shares_it_from_any_folder(self, repo, monkeypatch):
        expected = repo / ".kairos" / "upgrade-refresh.log"
        for cwd in (repo, repo / "ontology-hub", repo / "ontology-hub" / "model"):
            monkeypatch.chdir(cwd)
            assert upgrade_refresh_log_path() == expected

    def test_a_flat_layout_hub_is_its_own_root(self, tmp_path):
        hub = tmp_path / "flat"
        (hub / "model" / "ontologies").mkdir(parents=True)
        (hub / "pyproject.toml").write_text("[tool.kairos]\n", encoding="utf-8")
        assert run_log_directory(hub) == hub.resolve() / ".kairos" / "logs"

    def test_the_folder_ignores_itself(self, repo):
        directory = ensure_kairos_dir(repo / "ontology-hub")
        assert directory == repo / ".kairos"
        assert (directory / ".gitignore").read_text(encoding="utf-8").splitlines()[-1] == "*"


class TestLogsShowFindsIt:
    def test_from_the_root_and_from_a_subfolder(self, repo, monkeypatch):
        log = _log(run_log_directory(repo / "ontology-hub"), "20260926T100000Z-compile-a.jsonl",
                   "compile")
        for cwd in (repo, repo / "ontology-hub" / "model"):
            monkeypatch.chdir(cwd)
            result = CliRunner().invoke(cli, ["logs", "show"], env=_ENV)
            assert result.exit_code == 0, result.output
            assert f"Run log: {log}" in result.output

    def test_a_log_in_the_old_hub_folder_is_still_read(self, repo, monkeypatch):
        """One transition release: logs written before #1038 stay readable."""
        old = _log(legacy_run_log_directory(repo / "ontology-hub"),
                   "20260926T090000Z-compile-old.jsonl", "compile")
        monkeypatch.chdir(repo)
        assert newest_run_log(repo) == old.resolve()

    def test_the_newest_wins_across_both_folders(self, repo):
        _log(legacy_run_log_directory(repo / "ontology-hub"),
             "20260926T090000Z-compile-old.jsonl", "compile")
        new = _log(run_log_directory(repo / "ontology-hub"),
                   "20260926T110000Z-emit-gold-new.jsonl", "emit-gold")
        assert newest_run_log(repo / "ontology-hub") == new

    def test_outside_any_hub_it_says_so(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(cli, ["logs", "show"], env=_ENV)
        assert result.exit_code == 1
        assert "Cannot locate a hub" in result.output
