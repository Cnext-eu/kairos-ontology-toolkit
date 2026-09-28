# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Authored Power BI reports in a dataplatform (DD-253, #1102)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.authored_reports import (
    AuthoredReportsError,
    apply_report_theme,
    check_authored_reports,
    live_connection,
    parse_manifest,
    stage_authored_reports,
)

FOLDER = "SalesInsight.Margin.Report"
MODEL = "Sales Insight"
DEV_ID = "00000000-0000-0000-0000-00000000d001"
PRD_ID = "00000000-0000-0000-0000-00000000f001"
THEME = {"name": "Brand", "dataColors": ["#112233", "#445566"]}


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _report(reports: Path, folder: str = FOLDER, display: str = "Margin by Job") -> Path:
    """A report as Power BI Desktop saves one live-connected to a model in the service."""
    root = reports / folder
    _write_json(
        root / ".platform",
        {"metadata": {"type": "Report", "displayName": display}, "config": {"version": "2.0"}},
    )
    _write_json(
        root / "definition.pbir",
        {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/"
            "definitionProperties/1.0.0/schema.json",
            "version": "4.0",
            "datasetReference": {"byConnection": live_connection(DEV_ID)},
        },
    )
    _write_json(
        root / "definition" / "report.json",
        {
            "themeCollection": {
                "baseTheme": {
                    "name": "CY24SU10",
                    "reportVersionAtImport": "5.55",
                    "type": "SharedResources",
                }
            },
            "resourcePackages": [
                {
                    "name": "RegisteredResources",
                    "type": "RegisteredResources",
                    "items": [{"name": "logo.jpg", "path": "logo.jpg", "type": "Image"}],
                }
            ],
        },
    )
    logo = root / "StaticResources" / "RegisteredResources" / "logo.jpg"
    logo.parent.mkdir(parents=True, exist_ok=True)
    logo.write_bytes(b"\xff\xd8logo")
    return root


def _manifest(reports: Path, body: str) -> None:
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "reports.yml").write_text(body, encoding="utf-8")


def _themed(reports: Path) -> None:
    _write_json(reports / "theme" / "brand.json", THEME)
    _manifest(
        reports,
        f"theme: theme/brand.json\nreports:\n  - folder: {FOLDER}\n    model: {MODEL}\n",
    )


@pytest.fixture
def reports(tmp_path: Path) -> Path:
    root = tmp_path / "powerbi" / "reports"
    _report(root)
    _manifest(
        root,
        f'schema_version: "1"\nreports:\n  - folder: {FOLDER}\n    model: {MODEL}\n'
        "    product: sales-insight\n    insights: [ins-001, ins-002]\n",
    )
    return root


# --- manifest ---------------------------------------------------------------------------


def test_manifest_parses_every_field():
    manifest = parse_manifest(
        "theme: theme/brand.json\nreports:\n"
        f"  - folder: {FOLDER}\n    model: {MODEL}\n    product: sales-insight\n"
        "    insights: [ins-001]\n    theme: false\n"
    )
    assert manifest.theme == "theme/brand.json"
    (report,) = manifest.reports
    assert (report.folder, report.model, report.product) == (FOLDER, MODEL, "sales-insight")
    assert report.insights == ("ins-001",)
    assert report.themed is False


def test_an_empty_manifest_lists_no_reports():
    assert parse_manifest("reports: []\n").reports == ()
    assert parse_manifest("").reports == ()


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("reports:\n  - model: X\n", "folder must be a non-empty string"),
        (f"reports:\n  - folder: {FOLDER}\n", "model must be a non-empty string"),
        ("reports:\n  - folder: Margin\n    model: X\n", "`<Name>.Report`"),
        ("reports:\n  - folder: a/B.Report\n    model: X\n", "`<Name>.Report`"),
        (
            f"reports:\n  - folder: {FOLDER}\n    model: X\n  - folder: {FOLDER}\n    model: Y\n",
            "listed twice",
        ),
        (f"reports:\n  - folder: {FOLDER}\n    model: X\n    insights: ins-1\n", "insight ids"),
        (
            f"reports:\n  - folder: {FOLDER}\n    model: X\n    insights: [a, a]\n",
            "insight id twice",
        ),
        (f"reports:\n  - folder: {FOLDER}\n    model: X\n    theme: other.json\n", "`false`"),
        (f"reports:\n  - folder: {FOLDER}\n    model: X\n    page: 1\n", "unknown key"),
        ("report: []\n", "unknown key"),
        ("theme: ../brand.json\n", "inside the reports directory"),
        ("reports: {}\n", "must be a list"),
        ("- a\n", "must be a mapping"),
        ("reports: [\n", "not valid YAML"),
    ],
)
def test_an_unusable_manifest_is_rejected(body, message):
    with pytest.raises(AuthoredReportsError, match=message):
        parse_manifest(body)


# --- check ------------------------------------------------------------------------------


def test_a_listed_bound_report_passes(reports):
    assert check_authored_reports(reports) == []


def test_no_reports_and_no_manifest_is_nothing_to_check(tmp_path):
    assert check_authored_reports(tmp_path / "powerbi" / "reports") == []


def test_a_report_folder_without_a_manifest_is_reported(tmp_path):
    root = tmp_path / "reports"
    _report(root)

    (finding,) = check_authored_reports(root)

    assert finding.code == "reports.unlisted"
    assert f"- folder: {FOLDER}" in finding.message


def test_unlisted_and_missing_folders_are_both_reported(reports):
    _report(reports, "Other.Report")
    _manifest(
        reports,
        f"reports:\n  - folder: {FOLDER}\n    model: {MODEL}\n"
        f"  - folder: Gone.Report\n    model: {MODEL}\n",
    )

    codes = sorted(d.code for d in check_authored_reports(reports))

    assert codes == ["reports.folder-missing", "reports.unlisted"]


def test_a_report_named_like_a_model_collides_with_the_hub_stub(tmp_path):
    root = tmp_path / "reports"
    _report(root, display=MODEL)
    _manifest(root, f"reports:\n  - folder: {FOLDER}\n    model: {MODEL}\n")

    (finding,) = check_authored_reports(root)

    assert finding.code == "reports.name-collision"
    assert "DD-236" in finding.message


def test_a_report_with_no_binding_is_reported(reports):
    _write_json(reports / FOLDER / "definition.pbir", {"version": "4.0"})

    assert [d.code for d in check_authored_reports(reports)] == ["reports.pbir-unbound"]


def test_a_report_without_definition_pbir_is_reported(reports):
    (reports / FOLDER / "definition.pbir").unlink()

    assert [d.code for d in check_authored_reports(reports)] == ["reports.pbir-missing"]


def test_an_invalid_manifest_is_one_finding(reports):
    _manifest(reports, "reports: {}\n")

    assert [d.code for d in check_authored_reports(reports)] == ["reports.manifest-invalid"]


def test_a_declared_theme_that_does_not_exist_is_reported(reports):
    _manifest(reports, f"theme: theme/none.json\nreports:\n  - folder: {FOLDER}\n    model: X\n")

    assert [d.code for d in check_authored_reports(reports)] == ["reports.theme-missing"]


# --- stage ------------------------------------------------------------------------------


def test_staging_binds_each_report_to_the_target_workspace_model(reports, tmp_path):
    committed = (reports / FOLDER / "definition.pbir").read_bytes()
    out = tmp_path / "staged"

    staged = stage_authored_reports(reports, out, {MODEL: PRD_ID, "Other": "x"})

    assert staged == [(FOLDER, MODEL, PRD_ID)]
    pbir = json.loads((out / FOLDER / "definition.pbir").read_text(encoding="utf-8"))
    # Exactly the shape Power BI Desktop writes and Fabric's REST import accepts.
    assert pbir["datasetReference"] == {
        "byConnection": {
            "connectionString": None,
            "pbiServiceModelId": None,
            "pbiModelVirtualServerName": "sobe_wowvirtualserver",
            "pbiModelDatabaseName": PRD_ID,
            "name": "EntityDataSource",
            "connectionType": "pbiServiceXmlaStyleLive",
        }
    }
    assert pbir["version"] == "4.0" and "$schema" in pbir
    assert b"\r\n" not in (out / FOLDER / "definition.pbir").read_bytes()
    assert (reports / FOLDER / "definition.pbir").read_bytes() == committed
    assert (out / FOLDER / "StaticResources" / "RegisteredResources" / "logo.jpg").is_file()


def test_staging_rebinds_a_report_saved_by_path(reports, tmp_path):
    _write_json(
        reports / FOLDER / "definition.pbir",
        {"version": "4.0", "datasetReference": {"byPath": {"path": "../Sales.SemanticModel"}}},
    )

    stage_authored_reports(reports, tmp_path / "staged", {MODEL: PRD_ID})

    pbir = json.loads((tmp_path / "staged" / FOLDER / "definition.pbir").read_text("utf-8"))
    assert list(pbir["datasetReference"]) == ["byConnection"]


def test_staging_keeps_a_hand_authored_parameter_file(reports, tmp_path):
    (reports / "parameter.yml").write_text("find_replace: []\n", encoding="utf-8")

    stage_authored_reports(reports, tmp_path / "staged", {MODEL: PRD_ID})

    assert (tmp_path / "staged" / "parameter.yml").read_text("utf-8") == "find_replace: []\n"


def test_staging_replaces_a_previous_staging_directory(reports, tmp_path):
    out = tmp_path / "staged"
    (out / "Leftover.Report").mkdir(parents=True)

    stage_authored_reports(reports, out, {MODEL: PRD_ID})

    assert not (out / "Leftover.Report").exists()


def test_staging_fails_closed_on_a_model_the_workspace_lacks(reports, tmp_path):
    with pytest.raises(AuthoredReportsError, match=r"Sales Insight.*it has: Finance"):
        stage_authored_reports(reports, tmp_path / "staged", {"Finance": "id"})
    assert not (tmp_path / "staged").exists()


def test_staging_fails_closed_on_an_unlisted_report(reports, tmp_path):
    _report(reports, "Other.Report")

    with pytest.raises(AuthoredReportsError, match="reports.unlisted"):
        stage_authored_reports(reports, tmp_path / "staged", {MODEL: PRD_ID})


def test_theme_drift_does_not_block_a_deploy(reports, tmp_path):
    _themed(reports)

    assert [d.code for d in check_authored_reports(reports)] == ["reports.theme-drift"]
    assert stage_authored_reports(reports, tmp_path / "staged", {MODEL: PRD_ID})


# --- theme ------------------------------------------------------------------------------


def test_applying_the_theme_matches_what_desktop_writes(reports):
    _themed(reports)

    assert apply_report_theme(reports) == [FOLDER]

    report = json.loads((reports / FOLDER / "definition" / "report.json").read_text("utf-8"))
    assert report["themeCollection"]["customTheme"] == {
        "name": "brand.json",
        "reportVersionAtImport": "5.55",
        "type": "RegisteredResources",
    }
    assert report["resourcePackages"][0]["items"] == [
        {"name": "logo.jpg", "path": "logo.jpg", "type": "Image"},
        {"name": "brand.json", "path": "brand.json", "type": "CustomTheme"},
    ]
    installed = reports / FOLDER / "StaticResources" / "RegisteredResources" / "brand.json"
    assert installed.read_bytes() == (reports / "theme" / "brand.json").read_bytes()
    assert check_authored_reports(reports) == []


def test_applying_the_theme_twice_changes_nothing(reports):
    _themed(reports)
    apply_report_theme(reports)
    before = (reports / FOLDER / "definition" / "report.json").read_bytes()

    assert apply_report_theme(reports) == []
    assert (reports / FOLDER / "definition" / "report.json").read_bytes() == before


def test_a_changed_theme_is_reported_then_reapplied(reports):
    _themed(reports)
    apply_report_theme(reports)
    _write_json(reports / "theme" / "brand.json", {**THEME, "dataColors": ["#000000"]})

    assert [d.code for d in check_authored_reports(reports)] == ["reports.theme-drift"]
    assert apply_report_theme(reports) == [FOLDER]
    assert check_authored_reports(reports) == []


def test_an_earlier_theme_is_replaced_where_it_stood(reports):
    _themed(reports)
    report_json = reports / FOLDER / "definition" / "report.json"
    content = json.loads(report_json.read_text("utf-8"))
    content["resourcePackages"][0]["items"].insert(
        0, {"name": "old.json", "path": "old.json", "type": "CustomTheme"}
    )
    _write_json(report_json, content)

    apply_report_theme(reports)

    items = json.loads(report_json.read_text("utf-8"))["resourcePackages"][0]["items"]
    assert [item["name"] for item in items] == ["brand.json", "logo.jpg"]


def test_a_report_that_opts_out_keeps_its_own_theme(reports):
    _write_json(reports / "theme" / "brand.json", THEME)
    _manifest(
        reports,
        f"theme: theme/brand.json\nreports:\n  - folder: {FOLDER}\n    model: {MODEL}\n"
        "    theme: false\n",
    )

    assert apply_report_theme(reports) == []
    assert check_authored_reports(reports) == []


def test_applying_without_a_declared_theme_is_an_error(reports):
    with pytest.raises(AuthoredReportsError, match="declares no `theme:`"):
        apply_report_theme(reports)


# --- CLI --------------------------------------------------------------------------------


def test_check_command_exits_one_with_json_findings(reports):
    _report(reports, "Other.Report")

    result = CliRunner().invoke(
        cli, ["check-authored-reports", "--reports-dir", str(reports), "--format", "json"]
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["diagnostics"][0]["code"] == "reports.unlisted"


def test_check_command_passes_a_ready_folder(reports):
    result = CliRunner().invoke(cli, ["check-authored-reports", "--reports-dir", str(reports)])

    assert result.exit_code == 0, result.output
    assert "ready to deploy" in result.output


def test_stage_command_binds_and_reports_each_report(reports, tmp_path):
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps({MODEL: PRD_ID}), encoding="utf-8")
    out = tmp_path / "staged"

    result = CliRunner().invoke(
        cli,
        [
            "stage-authored-reports",
            "--reports-dir",
            str(reports),
            "--model-ids",
            str(ids),
            "--out",
            str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    assert PRD_ID in result.output
    assert PRD_ID in (out / FOLDER / "definition.pbir").read_text("utf-8")


@pytest.mark.parametrize("ids_text", ["[1, 2]", "{not json", '{"Sales Insight": 3}'])
def test_stage_command_rejects_a_malformed_model_list(reports, tmp_path, ids_text):
    ids = tmp_path / "ids.json"
    ids.write_text(ids_text, encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "stage-authored-reports",
            "--reports-dir",
            str(reports),
            "--model-ids",
            str(ids),
            "--out",
            str(tmp_path / "staged"),
        ],
    )

    assert result.exit_code == 1
    assert "ids.json" in result.output


def test_stage_command_fails_on_a_missing_model(reports, tmp_path):
    ids = tmp_path / "ids.json"
    ids.write_text("{}", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "stage-authored-reports",
            "--reports-dir",
            str(reports),
            "--model-ids",
            str(ids),
            "--out",
            str(tmp_path / "staged"),
        ],
    )

    assert result.exit_code == 1
    assert "not in the target workspace" in result.output


def test_theme_command_themes_and_reports(reports):
    _themed(reports)

    result = CliRunner().invoke(cli, ["apply-report-theme", "--reports-dir", str(reports)])

    assert result.exit_code == 0, result.output
    assert FOLDER in result.output
