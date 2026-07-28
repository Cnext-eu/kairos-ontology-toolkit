# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Regression tests for the validate --format alias."""

from click.testing import CliRunner

from kairos_ontology.cli import validation as validation_commands
from kairos_ontology.cli.validation import validate
from kairos_ontology.core import reference_modules
from kairos_ontology.core.reference_modules import AcceleratorResolution


def _prepare_hub(tmp_path):
    hub = tmp_path / "hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "model" / "shapes").mkdir(parents=True)
    (hub / "model" / "ontologies" / "sales.ttl").write_text("", encoding="utf-8")
    return hub


def test_validate_format_alias_matches_report_format(tmp_path, monkeypatch):
    hub = _prepare_hub(tmp_path)
    calls = []
    monkeypatch.chdir(hub)
    monkeypatch.setattr(validation_commands, "run_gdpr_validation", lambda **kw: None)
    monkeypatch.setattr(validation_commands, "run_validation", lambda **kw: calls.append(kw))
    monkeypatch.setattr(
        reference_modules,
        "resolve_hub_accelerator_detailed",
        lambda **kw: AcceleratorResolution(None, "none", None),
    )

    alias_result = CliRunner().invoke(validate, ["--syntax", "--format", "json"])
    report_result = CliRunner().invoke(validate, ["--syntax", "--report-format", "json"])
    both_result = CliRunner().invoke(
        validate,
        ["--syntax", "--format", "markdown", "--report-format", "json"],
    )

    assert alias_result.exit_code == 0, alias_result.output
    assert report_result.exit_code == 0, report_result.output
    assert both_result.exit_code == 0, both_result.output
    assert len(calls) == 3
    assert calls[0]["report_path"] == calls[1]["report_path"]
    assert calls[0]["report_path"] == calls[2]["report_path"]
    assert calls[0]["markdown_report_path"] == calls[1]["markdown_report_path"] is None
    assert calls[2]["markdown_report_path"] is None


def test_validate_report_format_both_still_rejects_report_path(tmp_path, monkeypatch):
    hub = _prepare_hub(tmp_path)
    monkeypatch.chdir(hub)
    monkeypatch.setattr(validation_commands, "run_gdpr_validation", lambda **kw: None)
    monkeypatch.setattr(validation_commands, "run_validation", lambda **kw: None)
    monkeypatch.setattr(
        reference_modules,
        "resolve_hub_accelerator_detailed",
        lambda **kw: AcceleratorResolution(None, "none", None),
    )

    result = CliRunner().invoke(
        validate,
        ["--syntax", "--report-format", "both", "--report-path", str(hub / "report.json")],
    )

    assert result.exit_code != 0
    assert "--report-path requires --report-format json or markdown" in result.output
