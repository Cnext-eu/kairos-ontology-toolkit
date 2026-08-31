# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Click surface for ``kairos-ontology emit-gold`` (issue #619 Bug 2).

Gold/PowerBI artifacts (TMDL, PBIP, DAX, ERD) are not dbt project files -- they are a
Fabric/Power BI workspace project structure, so they were never wired into
``compile --emit``'s fixed dbt publish target (mixing them into a dbt project directory
would confuse dbt tooling). Before this command, the only way to produce them was the
Python API (``project_downstream_compile_plan('powerbi', plan)``), which every #619
reporter had to reach for directly. This gives that path a real CLI entry point, atomic
emit, and its own fixed publish location, mirroring ``compile --emit``'s safety
conventions (manifest-owned target, ``--confirm-emit`` gate) without writing into the
dbt publish tree.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import click

from ..core.compiler import build_compile_plan
from ..core.hub_utils import find_hub_root, publish_root
from ..core.projections.dbt.gold_connection import GOLD_CONNECTION_OVERRIDE_PATH
from ..core.projections.dbt.gold_render import PARAMETER_ARTIFACT_PATH
from ..core.projections.dbt.pbip_validate import validate_package_artifacts

#: Power BI/Gold publish sub-path under the publish root (``<publish_root>/powerbi``),
#: a sibling of the dbt publish sub-path (``<publish_root>/medallion/dbt``) -- never
#: inside it, since TMDL/PBIP files are not dbt project files.
_POWERBI_EMIT_SUBPATH = Path("powerbi")


def _gold_manifest_name(domain: str) -> str:
    # Manifest names are validated elsewhere to start with ".kairos-compile-manifest"
    # and end with ".json" (core.compiler.emit._manifest_file_name) -- that prefix is
    # reserved for Kairos regardless of which emit target it lives in, so this reuses
    # it rather than inventing a second reserved namespace.
    safe_domain = re.sub(r"[^A-Za-z0-9_.-]", "_", domain) or "domain"
    return f".kairos-compile-manifest.gold-{safe_domain}.json"


@click.command(name="emit-gold")
@click.argument("domain")
@click.option(
    "--confirm-emit",
    "confirm_emit",
    is_flag=True,
    default=False,
    help="Required to actually write files. Without it, this validates and reports "
    "what would be emitted without touching disk.",
)
@click.option(
    "--skip-tmdl-validation",
    "skip_tmdl_validation",
    is_flag=True,
    default=False,
    help="Skip TOM SDK structural validation of the generated TMDL. Runs by default "
    "(dry run or --confirm-emit) whenever dotnet is on PATH; a missing dotnet SDK is "
    "reported but never blocks the emit.",
)
def emit_gold_cmd(domain: str, confirm_emit: bool, skip_tmdl_validation: bool) -> None:
    """Emit Gold/PowerBI artifacts (TMDL, PBIP, DAX, ERD) for one compiled DOMAIN.

    Builds the same typed ``CompilePlan`` ``compile`` uses, then projects its Gold
    product the same way ``project_downstream_compile_plan('powerbi', plan)`` does.
    Requires the domain to have an authored Gold profile (``kairos-ext:goldProductProfile``)
    and, for a Direct Lake or Databricks-backed product, the matching connection block
    in ``kairos.yaml`` (``gold.direct_lake_connection`` / ``gold.databricks_connection``).

    Before writing anything, two independent gates run.

    ``validate_package_artifacts()`` validates every Fabric package file (``.pbip``,
    ``definition.pbir``, ``definition.pbism``, ``.platform``, and the PBIR report JSON)
    against the JSON Schema each one declares, using vendored copies of Microsoft's
    published schemas. It always runs and never touches the network.

    ``validate_tmdl_artifacts()`` then runs the generated TMDL through the Microsoft
    TOM SDK. This is **TMDL structural/deserialization validation only**
    (``TmdlSerializer.DeserializeDatabaseFromFolder``) -- it is not proof that Desktop
    or Fabric can open the project. It does not evaluate the package JSON above, the
    ``sourceColumn`` requirements Desktop enforces on calculated tables, relationship
    endpoint validity, or anything else checked when a local Analysis Services
    database is created (#623). Pass ``--skip-tmdl-validation`` to skip it (for
    example in an environment without the .NET SDK where you'd rather not pay the
    build cost on every emit).

    The emit location is fixed and not configurable:
    ``<repo>/ontology-hub-publish/powerbi`` (sibling of the hub, and of the dbt publish
    target `<repo>/ontology-hub-publish/medallion/dbt` -- never inside it).

    \b
    Examples:
      kairos-ontology emit-gold party
      kairos-ontology emit-gold party --confirm-emit
    """
    from ..core.compiler.emit import emit_artifacts
    from ..core.projections.dbt.gold_specs import GoldContractError
    from ..core.projections.dbt.tmdl_validate import validate_tmdl_artifacts
    from ..core.projections.medallion_gold_projector import generate_gold_from_compile_plan

    hub_root = find_hub_root(Path.cwd(), require_model=True)
    if hub_root is None:
        raise click.ClickException(
            "Cannot locate a hub (model/ + integration/) from the current directory."
        )

    plan = build_compile_plan(hub_root, domain)
    if plan.blocked:
        for diagnostic in plan.diagnostics.ordered:
            click.echo(diagnostic.render(), err=True)
        raise click.ClickException(f"{domain}: compile plan is blocked; see diagnostics above")

    contract = plan.normalized_contract
    if contract is None or contract.policy.gold.profile is None:
        raise click.ClickException(
            f"{domain} has no authored Gold profile "
            "(kairos-ext:goldProductProfile) -- nothing to emit"
        )

    try:
        artifacts = generate_gold_from_compile_plan(plan)
    except GoldContractError as exc:
        raise click.ClickException(str(exc)) from exc

    # Always on, unlike the TMDL gate: this is pure Python against vendored schemas,
    # so there is no .NET SDK to be missing and no build cost to opt out of. It is also
    # the gate that covers everything Desktop and Fabric read *before* the model, which
    # is where #623's blocker lived -- a `.pbip` whose $schema URI 404s.
    package_failures = [
        result for result in validate_package_artifacts(artifacts) if result.status != "pass"
    ]
    if package_failures:
        detail = "; ".join(f"{item.artifact_path}: {item.message}" for item in package_failures)
        raise click.ClickException(
            f"Fabric package validation failed for {len(package_failures)} file(s): {detail}"
        )

    if not skip_tmdl_validation:
        tmdl_results = validate_tmdl_artifacts(artifacts)
        failures = [result for result in tmdl_results if result.status == "fail"]
        for result in tmdl_results:
            if result.status == "unavailable":
                click.echo(
                    f"   (TOM SDK validation unavailable for {result.definition_root}: "
                    f"{result.message})"
                )
        if failures:
            detail = "; ".join(f"{item.definition_root}: {item.message}" for item in failures)
            raise click.ClickException(
                f"TMDL structural validation failed for {len(failures)} model(s): {detail}"
            )

    target = (publish_root(hub_root) / _POWERBI_EMIT_SUBPATH).resolve(strict=False)
    manifest_name = _gold_manifest_name(domain)
    verb = "Would emit" if not confirm_emit else "Emitted"
    click.echo(f"✅ {verb} {len(artifacts)} Gold artifact(s) for {domain!r} to {target}")
    if not confirm_emit:
        click.echo("   (dry run -- pass --confirm-emit to write these files)")
        return

    # `parameter.yml` is the one hub-wide root artifact every domain's Gold emit writes
    # into this shared directory -- correctly so, since fabric-cicd reads exactly one
    # per `repository_directory` and it must cover every domain. Each domain owns only
    # its own manifest, so without declaring it mergeable the second domain's emit sees
    # an unowned file already on disk and fails closed (issue #664). Mirrors how
    # `cli/compile.py` declares the Silver side's shared artifacts.
    emit_artifacts(
        artifacts,
        target,
        manifest_name=manifest_name,
        replace_unowned_paths=(PARAMETER_ARTIFACT_PATH,),
    )
    click.echo(f"   → {target}")

    _regenerate_master_gold_erd(target, hub_name=hub_root.name)


def _regenerate_master_gold_erd(gold_output: Path, *, hub_name: str) -> None:
    """Recompute the hub-wide bound Gold ERD from whatever domains are on disk.

    ``generate_master_gold_erd`` is a pure disk-scan-and-merge over every
    ``**/*-gold-erd.mmd`` already emitted under the shared Gold/PowerBI publish root, so
    this accumulates correctly across separate single-domain ``emit-gold`` invocations.
    Ported from the legacy ``run_projections`` orchestrator (DD-011), whose ``powerbi``
    target is compile-plan-only and unreachable there; that call site is now commented
    out.
    """
    from ..core.projections.medallion_gold_projector import generate_master_gold_erd

    master_mmd = generate_master_gold_erd(gold_output, hub_name=hub_name)
    if master_mmd is None:
        return
    (gold_output / "master-gold-erd.mmd").write_text(master_mmd, encoding="utf-8")


@click.command(name="apply-gold-connection")
@click.option(
    "--package-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory the verified semantic-model archive was extracted into.",
)
@click.option(
    "--environment",
    required=True,
    help="Target environment key, matching the one passed to fabric-cicd.",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(path_type=Path),
    help=f"Override file (default: {GOLD_CONNECTION_OVERRIDE_PATH}).",
)
def apply_gold_connection_cmd(package_dir: Path, environment: str, config_path: Path | None):
    """Point one environment's Direct Lake target at dataplatform-owned infrastructure.

    The hub authors `gold.direct_lake_connection` in its own `kairos.yaml`, so the
    `parameter.yml` it ships can only rewrite between environments the hub itself
    declares. That forced every Fabric workspace a hub might ever deploy to have its real
    GUIDs committed to the hub repo, which otherwise stays infrastructure-agnostic
    (issue #662). This is the seam from the other side.

    Only `replace_value[ENVIRONMENT]` is rewritten. `find_value` is left exactly as the
    hub emitted it: fabric-cicd matches it as a literal substring against the URL baked
    into the TMDL, so a dataplatform-supplied value would silently fail to match and
    leave the model pointed at the hub's default workspace.

    A missing config file, or one that does not declare ENVIRONMENT, is a clean no-op --
    the hub's own values stand. The archive and its verified checksum are never touched;
    only the already-extracted `parameter.yml` is rewritten, after verification.
    """
    import yaml

    from ..core.projections.dbt.gold_connection import (
        GoldConnectionOverrideError,
        apply_gold_connection_override,
        parse_gold_connection_overrides,
    )

    resolved_config = config_path or Path(GOLD_CONNECTION_OVERRIDE_PATH)
    if not resolved_config.is_file():
        click.echo(f"No {resolved_config} -- using the hub's own Direct Lake connection.")
        return

    parameter_path = package_dir / PARAMETER_ARTIFACT_PATH
    if not parameter_path.is_file():
        click.echo(
            f"No {PARAMETER_ARTIFACT_PATH} in {package_dir} -- nothing to parameterise. "
            "The hub emits one only for a connection-bound semantic model."
        )
        return

    try:
        overrides = parse_gold_connection_overrides(
            yaml.safe_load(resolved_config.read_text(encoding="utf-8")),
            os.environ,
        )
    except GoldConnectionOverrideError as exc:
        raise click.ClickException(str(exc)) from exc

    override = overrides.get(environment)
    if override is None:
        click.echo(
            f"{resolved_config} declares no {environment!r} environment "
            f"(declared: {sorted(overrides)}) -- using the hub's own connection."
        )
        return

    try:
        rewritten, previous, new_url = apply_gold_connection_override(
            parameter_path.read_text(encoding="utf-8"),
            environment,
            override,
        )
    except GoldConnectionOverrideError as exc:
        raise click.ClickException(str(exc)) from exc

    parameter_path.write_text(rewritten, encoding="utf-8")
    click.echo(f"Applied {resolved_config} override for {environment!r}:")
    click.echo(f"  before: {previous or '(not declared by the hub)'}")
    click.echo(f"  after:  {new_url}")
