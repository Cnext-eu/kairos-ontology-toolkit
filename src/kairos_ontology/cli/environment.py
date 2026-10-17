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


#: The environments the managed promote workflow carries a commit through, in order.
PROMOTION_PATH = ("dev", "uat", "prod")


def _checked_hub_release_lock(project_dir: Path):
    """Read hub-release.lock and check it against the packages.yml pin (DD-256)."""
    from ..core.hub_release_lock import check_lock_matches_pin, read_hub_release_lock
    from .shared import _parse_hub_package_pin

    lock = read_hub_release_lock(project_dir)
    if lock is None:
        return None
    packages = project_dir / "packages.yml"
    pinned = None
    if packages.is_file():
        try:
            pinned = _parse_hub_package_pin(packages.read_text(encoding="utf-8")).previous_revision
        except ValueError:
            pinned = None
    check_lock_matches_pin(lock, pinned)
    return lock


def _split_github_repo(value: str, project_dir: Path) -> tuple[str, str]:
    """Return ``(host, owner/repo)`` for ``--github-repo``.

    ``HOST/OWNER/REPO`` names a GitHub Enterprise host explicitly. Plain ``OWNER/REPO``
    takes the host of the project's ``origin`` remote when that remote is the same
    repository, so a dataplatform on GitHub Enterprise needs no extra flag.
    """
    import re
    import subprocess

    parts = value.strip().strip("/").split("/")
    if len(parts) == 3:
        return parts[0], "/".join(parts[1:])
    repo = "/".join(parts)
    try:
        origin = subprocess.run(
            ["git", "-C", str(project_dir), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        origin = ""
    match = re.match(r"^(?:https?://(?:[^@/]+@)?|git@)([^/:]+)[/:](.+?)(?:\.git)?/?$", origin)
    if match and match.group(2).lower() == repo.lower():
        return match.group(1), repo
    return "github.com", repo


def _deploy_is_callable(project_dir: Path) -> bool | None:
    """Whether the repository's deploy workflow can be called by promote.yml (DD-256).

    ``None`` when there is no deploy workflow at all.
    """
    import yaml

    path = project_dir / ".github" / "workflows" / "deploy-powerbi-semantic-model.yml"
    if not path.is_file():
        return None
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return False
    # PyYAML reads the bare key `on` as the boolean True.
    triggers = (document or {}).get(True) or (document or {}).get("on") or {}
    return isinstance(triggers, dict) and "workflow_call" in triggers


def _github_environments(repo: str, host: str = "github.com") -> set[str] | None:
    """The lowercased Environment names of *repo*, or ``None`` when `gh` cannot list them."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                "--hostname",
                host,
                f"/repos/{repo}/environments",
                "--jq",
                ".environments[].name",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    # GitHub matches Environment names case-insensitively, as the deploy does.
    return {line.strip().lower() for line in result.stdout.splitlines() if line.strip()}


@click.command(name="hub-release")
@PROJECT_DIR_OPTION
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "github-output"]),
    default="text",
    show_default=True,
)
def hub_release_cmd(project_dir: Path, output_format: str):
    """Show the hub release this dataplatform deploys, from hub-release.lock (DD-256).

    Fails when the lock is malformed, or names a different hub commit than packages.yml
    pins: the dbt package and the semantic model must come from the same hub commit.
    Without a lock, prints `deploy=false` -- the promote workflow then builds dbt only.
    """
    from ..core.hub_release_lock import HUB_RELEASE_LOCK_PATH, HubReleaseLockError

    try:
        lock = _checked_hub_release_lock(project_dir)
    except HubReleaseLockError as exc:
        raise click.ClickException(str(exc)) from exc
    if output_format == "github-output":
        if lock is None:
            click.echo("deploy=false")
            return
        click.echo("deploy=true")
        click.echo(f"hub_release_tag={lock.tag}")
        click.echo(f"expected_hub_sha={lock.hub_sha}")
        click.echo(f"expected_archive_sha256={lock.archive_sha256}")
        return
    if lock is None:
        click.echo(
            f"No {HUB_RELEASE_LOCK_PATH}: a promotion builds dbt only. Run "
            "`kairos-ontology bump-hub <release tag>` to deploy the hub's Power BI models too."
        )
        return
    click.echo(f"Hub release {lock.tag}")
    click.echo(f"  hub commit:     {lock.hub_sha} (matches packages.yml)")
    click.echo(f"  archive SHA-256: {lock.archive_sha256}")


@click.command(name="check-environments")
@PROJECT_DIR_OPTION
@PROFILES_DIR_OPTION
@click.option(
    "--online",
    is_flag=True,
    help="Also resolve each environment's IDs through the Fabric REST API.",
)
@click.option(
    "--github-repo",
    default=None,
    metavar="OWNER/REPO",
    help="Also check that each environment has a GitHub Environment (needs `gh`). "
    "HOST/OWNER/REPO for GitHub Enterprise; OWNER/REPO takes the host of `origin`.",
)
def check_environments_cmd(
    project_dir: Path, profiles_dir: Path | None, online: bool, github_repo: str | None
):
    """Check that every environment can be promoted to, and say what to fix (DD-256).

    For each dbt target in profiles.yml: it resolves (offline unless --online), the
    vars.kairos entries name real targets, the promote workflow's dev -> uat -> prod path
    is covered, hub-release.lock agrees with packages.yml, and -- with --github-repo --
    a GitHub Environment of the same name exists. Read-only. Exit 1 on any problem.
    """
    from ..core.dbt_environment import list_dbt_targets, load_kairos_vars
    from ..core.projections.dbt.gold_connection import normalize_environment_key

    problems: list[str] = []
    notes: list[str] = []

    def problem(message: str) -> None:
        problems.append(message)
        click.echo(f"  ✗ {message}")

    click.echo("dbt targets (profiles.yml):")
    try:
        targets = list_dbt_targets(project_dir, profiles_dir=profiles_dir)
    except EnvironmentResolutionError as exc:
        problem(f"{exc} -- create profiles.yml with one target per environment (DD-255)")
        targets = []
    keys = [normalize_environment_key(name) for name in targets]
    for name in targets:
        try:
            resolved = resolve_environment(
                project_dir, name, profiles_dir=profiles_dir, offline=not online
            )
        except EnvironmentResolutionError as exc:
            problem(f"{name}: {exc}")
            continue
        if resolved.deferred_env:
            # The managed deploy passes dbt only the Azure credentials, never an arbitrary
            # GitHub Environment variable, so an endpoint read through env_var() is unset
            # there and both the dbt build and the resolution fail (#1114).
            problem(
                f"{resolved.environment}: the endpoint reads "
                f"{', '.join(resolved.deferred_env)}, which the deploy workflow does not "
                f"pass to dbt -- write the {resolved.environment!r} target's endpoint into "
                "profiles.yml (an endpoint and a database name are not secrets)"
            )
            continue
        detail = resolved.gold_item_id or resolved.server_hostname or "IDs resolved at deploy"
        click.echo(f"  ✓ {resolved.environment} ({resolved.target_type}): {detail}")

    try:
        for key in sorted(set(load_kairos_vars(project_dir)) - set(keys)):
            problem(
                f"vars.kairos.environments.{key} names no dbt target; add the target to "
                "profiles.yml or remove the entry"
            )
    except EnvironmentResolutionError as exc:
        problem(str(exc))

    missing = [key for key in PROMOTION_PATH if key not in keys]
    if targets and missing:
        notes.append(
            f"The promote workflow runs {' -> '.join(PROMOTION_PATH)}; profiles.yml has no "
            f"{missing} target. Set the repository variable KAIROS_PROMOTION_PATH (e.g. "
            f"{','.join(key for key in PROMOTION_PATH if key in keys)}) to skip them."
        )
    extra = [key for key in keys if key not in PROMOTION_PATH]
    if extra:
        notes.append(
            f"{extra} are not on the promote path; deploy them by dispatching "
            "deploy-powerbi-semantic-model.yml with build_dbt enabled."
        )

    from ..core.hub_release_lock import HubReleaseLockError

    click.echo("Workflows:")
    callable_deploy = _deploy_is_callable(project_dir)
    if callable_deploy is None:
        problem(
            "no .github/workflows/deploy-powerbi-semantic-model.yml: run "
            "`kairos-ontology update --refresh-workflows`"
        )
    elif not callable_deploy:
        problem(
            "deploy-powerbi-semantic-model.yml has no `workflow_call` trigger, so promote.yml "
            "cannot call it. It is an older or customized copy: if pyproject.toml lists it "
            "under [tool.kairos] customized-workflows, port your changes onto the managed "
            "template (or upstream them), remove the entry, and run "
            "`kairos-ontology update --refresh-workflows`"
        )
    else:
        click.echo("  ✓ the deploy workflow can be called by promote.yml")
    if not (project_dir / ".github" / "workflows" / "promote.yml").is_file():
        notes.append(
            "No .github/workflows/promote.yml: `kairos-ontology update --refresh-workflows` "
            "installs it."
        )

    click.echo("Hub release (hub-release.lock):")
    try:
        lock = _checked_hub_release_lock(project_dir)
    except HubReleaseLockError as exc:
        problem(str(exc))
    else:
        if lock is None:
            notes.append(
                "No hub-release.lock: a promotion builds dbt only. `kairos-ontology bump-hub "
                "<release tag>` writes it to deploy the Power BI models too."
            )
        else:
            click.echo(f"  ✓ {lock.tag}, the hub commit packages.yml pins")

    if github_repo:
        host, github_repo = _split_github_repo(github_repo, project_dir)
        click.echo(f"GitHub Environments ({host}/{github_repo}):")
        existing = _github_environments(github_repo, host)
        if existing is None:
            problem(
                f"could not list the Environments of {host}/{github_repo} (check "
                f"`gh auth status --hostname {host}`; a GitHub Enterprise repository can be "
                "named HOST/OWNER/REPO)"
            )
        else:
            for key in keys:
                if key in existing:
                    click.echo(f"  ✓ {key}")
                else:
                    problem(
                        f"no GitHub Environment {key!r}: create it (Settings -> Environments), "
                        f"add its FABRIC_*/AZURE_* secrets, required reviewers on uat/prod, and "
                        f"an Entra federated credential with subject "
                        f"repo:{github_repo}:environment:{key}"
                    )

    for note in notes:
        click.echo(f"  i {note}")
    if problems:
        raise click.ClickException(f"{len(problems)} problem(s); see above.")
    click.echo("All environments can be promoted.")
