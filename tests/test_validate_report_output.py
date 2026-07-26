# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Regression tests for validation report destination (PR2).

`kairos-ontology validate` must write its JSON report under
``<hub>/output/validation-report.json``, never into the process's current
working directory, regardless of whether it is invoked from the repo root or
from inside ``ontology-hub/``. ``status`` must recognize that report without
any changes to ``status.py`` — it already scans for
``<hub>/output/validation-report.json`` (see ``_scan_validate``).
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.status import STATE_DONE, scan_hub_status

VALID_TTL = """\
@prefix : <https://acme.com/ont/client#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<https://acme.com/ont/client> a owl:Ontology ;
    rdfs:label "Client"@en ;
    owl:versionInfo "0.1.0" .

:Client a owl:Class ;
    rdfs:label "Client"@en ;
    rdfs:comment "A client."@en .
"""


def _make_hub(root: Path) -> Path:
    """Create a minimal hub at ``root/ontology-hub`` and return the hub root."""
    hub = root / "ontology-hub"
    ont = hub / "model" / "ontologies"
    ont.mkdir(parents=True)
    (ont / "client.ttl").write_text(VALID_TTL, encoding="utf-8")
    return hub


def test_validate_report_under_hub_output_from_repo_root(tmp_path, monkeypatch):
    """Invoking from the repo root must land the report under <hub>/output/."""
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["validate", "--syntax"])
    assert result.exit_code == 0, result.output

    assert (hub / "output" / "validation-report.json").exists()
    assert not (tmp_path / "validation-report.json").exists()


def test_validate_report_under_hub_output_from_inside_hub(tmp_path, monkeypatch):
    """Invoking from inside ontology-hub/ must not drop the report at cwd."""
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["validate", "--syntax"])
    assert result.exit_code == 0, result.output

    assert (hub / "output" / "validation-report.json").exists()
    assert not (hub / "validation-report.json").exists()


def test_status_recognizes_cli_written_report(tmp_path, monkeypatch):
    """`status` must recognize the CLI-produced report without editing status.py."""
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["validate", "--syntax"])
    assert result.exit_code == 0, result.output

    status = scan_hub_status(hub)
    validate_phase = status.phase("validate")
    assert validate_phase is not None
    assert validate_phase.state == STATE_DONE


# ---------------------------------------------------------------------------
# Additive JSON/Markdown report-format selection (validation-operations)
# ---------------------------------------------------------------------------


def test_report_format_defaults_preserve_json_only_contract(tmp_path, monkeypatch):
    """Omitting --report-format/--report-path keeps the exact pre-existing
    JSON-only contract: only validation-report.json is written."""
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["validate", "--syntax"])
    assert result.exit_code == 0, result.output

    assert (hub / "output" / "validation-report.json").exists()
    assert not (hub / "output" / "validation-report.md").exists()


def test_report_format_markdown_writes_only_markdown_by_default_path(tmp_path, monkeypatch):
    """--report-format markdown writes only the default Markdown path, no JSON."""
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["validate", "--syntax", "--report-format", "markdown"])
    assert result.exit_code == 0, result.output

    assert (hub / "output" / "validation-report.md").exists()
    assert not (hub / "output" / "validation-report.json").exists()


def test_report_format_both_writes_json_and_markdown(tmp_path, monkeypatch):
    """--report-format both writes both default report paths."""
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["validate", "--syntax", "--report-format", "both"])
    assert result.exit_code == 0, result.output

    assert (hub / "output" / "validation-report.json").exists()
    assert (hub / "output" / "validation-report.md").exists()


def test_report_path_overrides_markdown_destination(tmp_path, monkeypatch):
    """--report-path with --report-format markdown honors the explicit path."""
    hub = _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)
    explicit_path = tmp_path / "custom" / "report.md"

    result = CliRunner().invoke(
        cli,
        [
            "validate",
            "--syntax",
            "--report-format",
            "markdown",
            "--report-path",
            str(explicit_path),
        ],
    )
    assert result.exit_code == 0, result.output

    assert explicit_path.exists()
    assert not (hub / "output" / "validation-report.md").exists()
    assert not (hub / "output" / "validation-report.json").exists()


def test_report_path_with_both_format_rejected(tmp_path, monkeypatch):
    """--report-path combined with --report-format both is an explicit, clear error
    (ambiguous single path for two report files) rather than silently guessing."""
    _make_hub(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        cli,
        [
            "validate",
            "--syntax",
            "--report-format",
            "both",
            "--report-path",
            str(tmp_path / "report.out"),
        ],
    )
    assert result.exit_code != 0
    assert "both" in result.output
