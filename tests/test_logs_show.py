# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``kairos-ontology logs show`` reads a run log back in human form (#1011 item 5)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.cli.run_log import run_log_directory

_PRODUCT_HUB = Path(__file__).parent / "scenarios" / "v5-product-hub"
_BILLING_CODE = "relationship.external-reference-key-unverified"
_ENV = {"KAIROS_SKILL_CONTEXT": "1"}


@pytest.fixture
def hub(tmp_path, monkeypatch):
    root = tmp_path / "hub"
    shutil.copytree(_PRODUCT_HUB, root)
    monkeypatch.chdir(root)
    monkeypatch.delenv("KAIROS_RUN_LOG", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    return root


@pytest.fixture
def emitted(hub):
    result = CliRunner().invoke(cli, ["compile", "--all", "--emit", "--confirm-emit"], env=_ENV)
    assert result.exit_code == 0, result.output
    return hub


def _show(*args: str):
    return CliRunner().invoke(cli, ["logs", "show", *args], env=_ENV)


def _tree(hub: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in hub.rglob("*") if path.is_file()}


class TestShow:
    def test_the_newest_log_as_a_span_tree(self, emitted):
        result = _show()
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert "  compile: ok (exit 0)" in lines
        assert "  diagnostics: 1 (1 info)" in lines
        assert any(line.startswith("  run compile: ok") for line in lines)
        assert any(line.startswith("    domain billing: ok") for line in lines)
        gate = next(i for i, line in enumerate(lines) if line.startswith("      gate compile: ok"))
        assert lines[gate + 1].lstrip().startswith(f"[info] {_BILLING_CODE}:")
        assert any(line.startswith("      stage emit: ok") for line in lines)

    def test_last_and_no_path_are_the_same(self, emitted):
        assert _show("--last").output == _show().output

    def test_group_by_code(self, emitted):
        result = _show("--group-by", "code")
        assert result.exit_code == 0, result.output
        assert f"  {_BILLING_CODE}: 1" in result.output.splitlines()
        assert f"billing/compile [info] {_BILLING_CODE}:" in result.output

    def test_group_by_severity(self, emitted):
        result = _show("--group-by", "severity")
        assert result.exit_code == 0, result.output
        assert "  info: 1" in result.output.splitlines()

    def test_json_output(self, emitted):
        result = _show("--format", "json", "--group-by", "severity")
        assert result.exit_code == 0, result.output
        document = json.loads(result.output)
        assert document["command"] == "compile"
        assert document["exit_code"] == 0
        assert document["group_by"] == "severity"
        assert [item["code"] for item in document["groups"]["info"]] == [_BILLING_CODE]
        assert {span["kind"] for span in document["spans"]} >= {"run", "domain", "gate", "stage"}

    def test_an_explicit_path(self, hub, tmp_path):
        log = tmp_path / "check.jsonl"
        CliRunner().invoke(
            cli,
            ["--log-file", str(log), "--log-format", "json", "compile", "nosuchdomain", "--check"],
            env=_ENV,
        )
        result = _show(str(log))
        assert result.exit_code == 0, result.output
        assert "  compile: failed (exit 1)" in result.output.splitlines()

    def test_it_writes_nothing(self, emitted):
        before = _tree(emitted)
        assert _show().exit_code == 0
        assert _tree(emitted) == before
        assert len(list(run_log_directory(emitted).glob("*.jsonl"))) == 1


class TestErrors:
    def test_no_logs_explains_how_to_get_one(self, hub):
        result = _show()
        assert result.exit_code == 1
        assert "No run logs" in result.output
        assert "--log-file" in result.output
        assert "KAIROS_RUN_LOG" in result.output

    def test_a_text_log_is_not_readable(self, hub, tmp_path):
        log = tmp_path / "run.log"
        log.write_text("2026-09-26 INFO kairos_ontology: a text line\n", encoding="utf-8")
        result = _show(str(log))
        assert result.exit_code == 1
        assert "--log-format json" in result.output

    def test_path_and_last_together_is_a_usage_error(self, hub, tmp_path):
        log = tmp_path / "run.jsonl"
        log.write_text("{}\n", encoding="utf-8")
        assert _show(str(log), "--last").exit_code == 2

    def test_a_log_from_before_spans_falls_back_to_tasks(self, hub, tmp_path):
        log = tmp_path / "old.jsonl"
        log.write_text(
            json.dumps(
                {
                    "event": "kairos.diagnostic.reported",
                    "kairos.task": "billing",
                    "kairos.gate": "compile",
                    "diagnostic.code": _BILLING_CODE,
                    "diagnostic.severity": "info",
                    "diagnostic.message": "m",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        result = _show(str(log))
        assert result.exit_code == 0, result.output
        assert "  billing: 1 info" in result.output.splitlines()
