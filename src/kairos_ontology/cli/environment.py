# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Resolve a deploy environment from the dataplatform's dbt target (DD-255, #1114)."""

from __future__ import annotations

import json
from pathlib import Path

import click

from ..core.dbt_environment import EnvironmentResolutionError, resolve_environment

#: Shared by `resolve-environment` and `apply-gold-connection --from-dbt-target`.
PROJECT_DIR_OPTION = click.option(
    "--project-dir",
    default=".",
    show_default=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="dbt project directory (holds dbt_project.yml).",
)
PROFILES_DIR_OPTION = click.option(
    "--profiles-dir",
    default=None,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory holding profiles.yml (default: as dbt -- DBT_PROFILES_DIR, the project "
    "directory, then ~/.dbt).",
)


@click.command(name="resolve-environment")
@click.option("--target", required=True, help="dbt target naming the environment.")
@PROJECT_DIR_OPTION
@PROFILES_DIR_OPTION
@click.option(
    "--offline",
    is_flag=True,
    help="Check the target and vars.kairos without calling Fabric; IDs that need the API "
    "are left unresolved.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json", "github-output"]),
    default="text",
    show_default=True,
    help="`github-output` prints key=value lines to append to $GITHUB_OUTPUT.",
)
def resolve_environment_cmd(
    target: str,
    project_dir: Path,
    profiles_dir: Path | None,
    offline: bool,
    output_format: str,
):
    """Resolve one environment's deploy IDs from its dbt target.

    The dbt target is the environment authority (DD-255): its name is the environment key
    (lowercased), its endpoint identifies the Gold connection, and
    `vars.kairos.environments.<env>` in dbt_project.yml names what dbt does not know --
    the models and reports workspaces, by name or GUID.

    For a Fabric target, the Gold Warehouse is the one whose SQL endpoint and name are the
    target's `server` and `database`, found through the Fabric REST API. A Databricks
    target's `host` and `http_path` are the connection itself. FABRIC_ITEM_ID,
    FABRIC_GOLD_WORKSPACE_ID, FABRIC_WORKSPACE_ID and FABRIC_REPORTS_WORKSPACE_ID, when
    set, take precedence. Each value is printed with its source. Exit 1 when the
    environment cannot be resolved.
    """
    try:
        resolved = resolve_environment(
            project_dir, target, profiles_dir=profiles_dir, offline=offline
        )
    except EnvironmentResolutionError as exc:
        raise click.ClickException(str(exc)) from exc
    values = resolved.as_dict()
    sources = values.pop("sources")
    if output_format == "json":
        click.echo(json.dumps({**values, "sources": sources}, indent=2))
        return
    if output_format == "github-output":
        for key, value in values.items():
            click.echo(f"{key}={value or ''}")
        return
    click.echo(f"Environment {resolved.environment!r} (dbt target {resolved.target!r}, "
               f"{resolved.target_type})")
    for key, value in values.items():
        if key in {"environment", "target", "target_type"} or (
            value is None and key not in sources
        ):
            continue
        click.echo(f"  {key}: {value or '(unresolved)'}  <- {sources.get(key, '')}")
