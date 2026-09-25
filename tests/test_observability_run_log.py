# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Every diagnostic of a run lands in a structured log, grouped per task (#1011).

Diagnostics reached only the console, interleaved across domains; the ``--log-file``
was empty at the default level even when a run had warnings. Now each diagnostic is a
``kairos.diagnostic.reported`` record and the run ends with a ``kairos.run.summary``. A
command that writes also keeps a default run log under ``<hub>/.kairos/logs/``;
``--check`` stays write-free (DD-133/140).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.cli.run_log import RUN_LOGS_KEPT, run_log_directory

_PRODUCT_HUB = Path(__file__).parent / "scenarios" / "v5-product-hub"
#: `billing` reports one info diagnostic on this fixture; `party` reports none.
_BILLING_CODE = "relationship.external-reference-key-unverified"


@pytest.fixture
def hub(tmp_path, monkeypatch):
    root = tmp_path / "hub"
    shutil.copytree(_PRODUCT_HUB, root)
    monkeypatch.chdir(root)
    monkeypatch.delenv("KAIROS_RUN_LOG", raising=False)
    return root


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _run_logs(hub: Path) -> list[Path]:
    return sorted(run_log_directory(hub).glob("*.jsonl"))


class TestLogFile:
    def test_a_check_run_logs_every_diagnostic_at_the_default_level(self, hub, tmp_path):
        log = tmp_path / "run.jsonl"
        result = CliRunner().invoke(
            cli,
            ["--log-file", str(log), "--log-format", "json", "compile", "billing", "--check"],
        )
        assert result.exit_code == 0, result.output
        records = _records(log)
        (diagnostic,) = [r for r in records if r.get("event") == "kairos.diagnostic.reported"]
        assert diagnostic["diagnostic.code"] == _BILLING_CODE
        assert diagnostic["kairos.task"] == "billing"
        assert diagnostic["kairos.gate"] == "compile"
        assert diagnostic["kairos.operation.id"]
        (summary,) = [r for r in records if r.get("event") == "kairos.run.summary"]
        assert summary["kairos.summary"]["billing"]["code"] == {_BILLING_CODE: 1}

    def test_the_console_does_not_print_a_diagnostic_twice(self, hub, tmp_path):
        log = tmp_path / "run.jsonl"
        result = CliRunner().invoke(cli, ["--log-file", str(log), "compile", "billing", "--check"])
        assert result.output.count(_BILLING_CODE) == 1, result.output

    def test_check_keeps_no_default_run_log(self, hub):
        """DD-133/140: --check and --explain write nothing into the hub."""
        result = CliRunner().invoke(cli, ["compile", "billing", "--check"])
        assert result.exit_code == 0, result.output
        assert not (hub / ".kairos").exists()


class TestDefaultRunLog:
    def _emit(self, *args: str):
        return CliRunner().invoke(
            cli, [*args, "compile", "--all", "--emit", "--confirm-emit"],
            env={"KAIROS_SKILL_CONTEXT": "1"},
        )

    def test_an_emit_writes_one_run_log_with_its_diagnostics(self, hub):
        result = self._emit()
        assert result.exit_code == 0, result.output
        (log,) = _run_logs(hub)
        assert "-compile-" in log.name
        codes = [
            r["diagnostic.code"]
            for r in _records(log)
            if r.get("event") == "kairos.diagnostic.reported"
        ]
        assert _BILLING_CODE in codes

    def test_the_log_directory_ignores_itself_in_git(self, hub):
        self._emit()
        assert (run_log_directory(hub) / ".gitignore").read_text(encoding="utf-8").endswith("*\n")

    def test_a_multi_domain_run_prints_one_summary_table(self, hub):
        result = self._emit()
        assert "Diagnostics by task:" in result.output
        assert f"billing: 1 info  ({_BILLING_CODE} x1)" in result.output

    def test_it_can_be_turned_off(self, hub, monkeypatch):
        monkeypatch.setenv("KAIROS_RUN_LOG", "0")
        assert self._emit().exit_code == 0
        assert _run_logs(hub) == []

    def test_an_explicit_log_file_replaces_it(self, hub, tmp_path):
        assert self._emit("--log-file", str(tmp_path / "mine.log")).exit_code == 0
        assert _run_logs(hub) == []
        assert _BILLING_CODE in (tmp_path / "mine.log").read_text(encoding="utf-8")

    def test_old_logs_are_rotated(self, hub):
        directory = run_log_directory(hub)
        directory.mkdir(parents=True)
        for index in range(RUN_LOGS_KEPT + 5):
            (directory / f"20200101T0000{index:02d}Z-compile-old.jsonl").write_text("")
        self._emit()
        logs = _run_logs(hub)
        assert len(logs) == RUN_LOGS_KEPT
        assert "-old" not in logs[-1].name, "the new log is the newest"

    def test_the_log_is_not_inside_the_emission_target(self, hub):
        self._emit()
        (log,) = _run_logs(hub)
        target = hub.parent / "ontology-hub-publish"
        assert target not in log.parents
