# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Commands for the Power BI reports a dataplatform authors itself (DD-253, #1102)."""

from __future__ import annotations

import json
from pathlib import Path

import click

from ..core.authored_reports import (
    DEFAULT_REPORTS_DIR,
    MANIFEST_NAME,
    AuthoredReportsError,
    apply_report_theme,
    check_authored_reports,
    stage_authored_reports,
)

_REPORTS_DIR_OPTION = click.option(
    "--reports-dir",
    default=DEFAULT_REPORTS_DIR.as_posix(),
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help=f"Directory holding the `<Name>.Report` folders and {MANIFEST_NAME}.",
)


@click.command(name="check-authored-reports")
@_REPORTS_DIR_OPTION
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def check_authored_reports_cmd(reports_dir: Path, output_format: str):
    """Check the authored reports before they reach a deploy.

    Every `<Name>.Report` folder needs an entry in reports.yml naming the semantic model it
    reads, a definition.pbir bound to a model, and a name no semantic model uses -- the hub
    republishes a stub report under each model's name (DD-236). When reports.yml declares a
    shared `theme:`, each report must carry the current copy of it. Exit 1 on any finding.
    """
    diagnostics = check_authored_reports(reports_dir)
    if output_format == "json":
        click.echo(
            json.dumps(
                {"ok": not diagnostics, "diagnostics": [d.as_dict() for d in diagnostics]},
                indent=2,
            )
        )
    elif diagnostics:
        for item in diagnostics:
            click.echo(f"✗ {item.code}  {item.path}\n  {item.message}")
    else:
        click.echo(f"✅ Authored reports in {reports_dir.as_posix()} are ready to deploy.")
    if diagnostics:
        raise SystemExit(1)


@click.command(name="stage-authored-reports")
@_REPORTS_DIR_OPTION
@click.option(
    "--model-ids",
    "model_ids_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="JSON object mapping each semantic model's display name to its ID in the target "
    "workspace.",
)
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory to stage the bound reports in; replaced if it exists.",
)
def stage_authored_reports_cmd(reports_dir: Path, model_ids_path: Path, out_dir: Path):
    """Copy the authored reports, each bound to its model's ID in the target workspace.

    A report binds to a semantic model by ID, and every workspace's copy of the model has its
    own, so the ID cannot be committed. The deploy lists the target workspace's models and
    passes them in; this writes each report's definition.pbir as the long `byConnection`
    form Fabric's import accepts. The committed reports are never modified. Fails when a
    model reports.yml names is not in the workspace.
    """
    try:
        model_ids = json.loads(model_ids_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"{model_ids_path} is not valid JSON: {exc}") from exc
    if not isinstance(model_ids, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in model_ids.items()
    ):
        raise click.ClickException(
            f"{model_ids_path} must be a JSON object of display name to model ID."
        )
    try:
        staged = stage_authored_reports(reports_dir, out_dir, model_ids)
    except AuthoredReportsError as exc:
        raise click.ClickException(str(exc)) from exc
    for folder, model, model_id in staged:
        click.echo(f"  ✓ {folder} → {model} ({model_id})")
    click.echo(f"Staged {len(staged)} authored report(s) in {out_dir.as_posix()}")


@click.command(name="apply-report-theme")
@_REPORTS_DIR_OPTION
def apply_report_theme_cmd(reports_dir: Path):
    """Install the shared theme reports.yml declares into every authored report.

    Copies the theme into each report's StaticResources/RegisteredResources and makes it the
    report's custom theme, as importing it in Power BI Desktop would. Commit the result:
    the deploy never changes report content. A report with `theme: false` is skipped.
    """
    try:
        changed = apply_report_theme(reports_dir)
    except AuthoredReportsError as exc:
        raise click.ClickException(str(exc)) from exc
    for folder in changed:
        click.echo(f"  ✓ {folder}")
    click.echo(f"Themed {len(changed)} report(s); the others were already current.")
