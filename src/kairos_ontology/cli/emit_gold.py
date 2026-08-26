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

import re
from pathlib import Path

import click

from ..core.compiler import build_compile_plan
from ..core.hub_utils import find_hub_root, publish_root

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
def emit_gold_cmd(domain: str, confirm_emit: bool) -> None:
    """Emit Gold/PowerBI artifacts (TMDL, PBIP, DAX, ERD) for one compiled DOMAIN.

    Builds the same typed ``CompilePlan`` ``compile`` uses, then projects its Gold
    product the same way ``project_downstream_compile_plan('powerbi', plan)`` does.
    Requires the domain to have an authored Gold profile (``kairos-ext:goldProductProfile``)
    and, for a Direct Lake or Databricks-backed product, the matching connection block
    in ``kairos.yaml`` (``gold.direct_lake_connection`` / ``gold.databricks_connection``).

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

    target = (publish_root(hub_root) / _POWERBI_EMIT_SUBPATH).resolve(strict=False)
    manifest_name = _gold_manifest_name(domain)
    verb = "Would emit" if not confirm_emit else "Emitted"
    click.echo(f"✅ {verb} {len(artifacts)} Gold artifact(s) for {domain!r} to {target}")
    if not confirm_emit:
        click.echo("   (dry run -- pass --confirm-emit to write these files)")
        return

    emit_artifacts(artifacts, target, manifest_name=manifest_name)
    click.echo(f"   → {target}")
