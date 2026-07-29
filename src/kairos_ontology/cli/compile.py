# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Click surface for the stateless Kairos v5 compiler."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, replace
from pathlib import Path

import click

from ..core.compiler import CompileMode, compile_domain
from ..core.hub_utils import find_hub_root, publish_root

#: dbt project sub-path under the publish root (``<publish_root>/medallion/dbt``).
_DBT_EMIT_SUBPATH = Path("medallion") / "dbt"
_SHARED_MANIFEST_NAME = ".kairos-compile-manifest.shared.json"
_PACKAGE_ARTIFACTS = frozenset({"README.md", "dbt_project.yml", "packages.yml"})


def _payload(result) -> dict:
    return {
        "domain": result.domain,
        "mode": result.mode,
        "succeeded": result.succeeded,
        "provenance_hash": result.provenance_hash,
        "diagnostics": [asdict(item) for item in result.diagnostics.ordered],
        "explain": asdict(result.explain) if result.explain is not None else None,
        "artifacts": [path for path, _ in result.artifacts],
    }


def _domain_manifest_name(domain: str) -> str:
    safe_domain = re.sub(r"[^A-Za-z0-9_.-]", "_", domain)
    if not safe_domain:
        safe_domain = "domain"
    return f".kairos-compile-manifest.{safe_domain}.json"


def _is_source_catalog_artifact(path: str) -> bool:
    return path.startswith("models/silver/") and path.endswith("__sources.yml")


def _is_shared_artifact(path: str) -> bool:
    return (
        path in _PACKAGE_ARTIFACTS
        or path.startswith("macros/")
        or _is_source_catalog_artifact(path)
    )


def _existing_domains(target: Path, current_domain: str) -> tuple[str, ...]:
    domains = {current_domain}
    silver = target / "models" / "silver"
    if silver.is_dir():
        domains.update(path.name for path in silver.iterdir() if path.is_dir())
    return tuple(sorted(domains))


def _existing_gold_domains(target: Path, current_domains: tuple[str, ...]) -> tuple[str, ...]:
    gold = target / "models" / "gold"
    domains = set()
    if gold.is_dir():
        domains.update(
            path.name for path in gold.iterdir() if path.is_dir() and path.name != "shared"
        )
    domains.intersection_update(current_domains)
    return tuple(sorted(domains))


def _reconciled_shared_artifacts(result, target: Path) -> dict[str, str]:
    shared = {
        path: content
        for path, content in result.artifact_dict().items()
        if _is_shared_artifact(path)
    }
    current_source_paths = {path for path in shared if _is_source_catalog_artifact(path)}
    plan = result.plan.materialization_plan if result.plan is not None else None
    if plan is not None and plan.project.emit:
        from ..core.projections.dbt.render import render_project_config

        domains = _existing_domains(target, result.domain)
        project = replace(
            plan.project,
            project_name="kairos_medallion_project",
            domains=domains,
            gold_domains=_existing_gold_domains(target, domains),
        )
        shared.update(render_project_config(replace(plan, project=project)))

    if target.is_dir():
        for existing in target.rglob("*"):
            if not existing.is_file():
                continue
            relative = existing.relative_to(target).as_posix()
            if _is_shared_artifact(relative) and relative not in shared:
                shared[relative] = existing.read_text(encoding="utf-8")

    for path, content in tuple(shared.items()):
        if path not in current_source_paths:
            continue
        existing = target.joinpath(*path.split("/"))
        if existing.is_file():
            from ..core.projector import _union_sources_yaml

            shared[path] = _union_sources_yaml(existing.read_text(encoding="utf-8"), content)
    return shared


def _emit_compile_artifacts(result, emit_dir: Path) -> Path:
    from ..core.compiler.emit import emit_artifacts

    target = emit_dir.resolve(strict=False)
    artifacts = result.artifact_dict()
    domain_artifacts = {
        path: content for path, content in artifacts.items() if not _is_shared_artifact(path)
    }
    emit_artifacts(
        domain_artifacts,
        target,
        manifest_name=_domain_manifest_name(result.domain),
    )
    shared_artifacts = _reconciled_shared_artifacts(result, target)
    emit_artifacts(
        shared_artifacts,
        target,
        manifest_name=_SHARED_MANIFEST_NAME,
        replace_unowned_paths=tuple(shared_artifacts),
    )
    return target


@click.command(name="compile")
@click.argument("domain")
@click.option("--check", "check_mode", is_flag=True, help="Validate without writing files.")
@click.option("--explain", "explain_mode", is_flag=True, help="Explain the normalized plan.")
@click.option(
    "--emit",
    "emit_mode",
    is_flag=True,
    help="Atomically emit generated dbt artifacts to the fixed canonical location "
    "<repo>/ontology-hub-publish/medallion/dbt (sibling of the hub). The target is "
    "not configurable.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(("text", "json")),
    default="text",
    show_default=True,
)
def compile_cmd(
    domain: str,
    check_mode: bool,
    explain_mode: bool,
    emit_mode: bool,
    output_format: str,
) -> None:
    """Check, explain, or emit one v5 DOMAIN from the current hub."""
    selected = int(check_mode) + int(explain_mode) + int(emit_mode)
    if selected != 1:
        raise click.UsageError("exactly one of --check, --explain, or --emit is required")
    mode = (
        CompileMode.CHECK
        if check_mode
        else CompileMode.EXPLAIN if explain_mode else CompileMode.EMIT
    )
    hub = find_hub_root(Path.cwd(), require_model=True) or Path.cwd()
    result = compile_domain(hub, domain, mode)
    emit_target = None
    if emit_mode and result.can_emit:
        # The emit location is fixed and not configurable: derived dbt artifacts
        # always land in the sibling publish root, never inside the hub.
        requested_target = publish_root(hub) / _DBT_EMIT_SUBPATH
        emit_target = _emit_compile_artifacts(result, requested_target)
    if output_format == "json":
        click.echo(json.dumps(_payload(result), indent=2, sort_keys=True))
    else:
        for diagnostic in result.diagnostics.ordered:
            click.echo(diagnostic.render(), err=not result.succeeded)
        if result.succeeded:
            if mode is CompileMode.CHECK:
                click.echo(f"✓ {domain}: compile check passed")
            elif mode is CompileMode.EXPLAIN:
                report = result.explain
                click.echo(f"✓ {domain}: {len(report.entities)} entity binding(s)")
                for entity in report.entities:
                    click.echo(
                        f"  {entity.name}: {entity.source} → {entity.target_class} "
                        f"[grain: {', '.join(entity.grain)}]"
                    )
                for path in report.artifact_paths:
                    click.echo(f"  {path}")
            else:
                click.echo(
                    f"✓ {domain}: emitted {len(result.artifacts)} artifact(s) to {emit_target}"
                )
    if not result.succeeded:
        raise click.exceptions.Exit(1)
