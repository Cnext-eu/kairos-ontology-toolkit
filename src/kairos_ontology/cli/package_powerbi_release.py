# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Click surface for ``kairos-ontology package-powerbi-release`` (DD-206 #8/#12 item 8).

The hub release workflow ships one ``powerbi-semantic-model.zip`` beside the dbt
release artifact, containing every Gold-configured domain's validated
``*.SemanticModel`` and ``*.Report`` folders, with a recorded SHA-256 so the
dataplatform deploy workflow can verify the archive before extraction (DD-206 §8).

This mirrors ``emit-gold``'s validation gates (``pbip_validate`` always, ``tmdl_validate``
best-effort) but runs across every domain the hub declares, and packages the deployable
subtree only -- not the full ``emit-gold`` publish tree (DDL/ERD/DAX/dbt/product-report
stay hub-side; see :mod:`kairos_ontology.core.projections.dbt.gold_release_package`).
"""

from __future__ import annotations

from pathlib import Path

import click

from ..core.compiler import build_compile_plan
from ..core.hub_utils import find_hub_root


@click.command(name="package-powerbi-release")
@click.option(
    "--output",
    "output",
    type=click.Path(path_type=Path),
    default=Path("powerbi-semantic-model.zip"),
    show_default=True,
    help="Where to write the archive. A '<output>.sha256' sidecar is written beside it.",
)
@click.option(
    "--confirm-emit",
    "confirm_emit",
    is_flag=True,
    default=False,
    help="Required to actually write the archive. Without it, this validates and "
    "reports what would be packaged without touching disk.",
)
@click.option(
    "--skip-tmdl-validation",
    "skip_tmdl_validation",
    is_flag=True,
    default=False,
    help="Skip TOM SDK structural validation of the generated TMDL for every domain. "
    "Runs by default whenever dotnet is on PATH; a missing dotnet SDK is reported "
    "but never blocks packaging.",
)
def package_powerbi_release_cmd(
    output: Path, confirm_emit: bool, skip_tmdl_validation: bool
) -> None:
    """Package every Gold-configured domain's Power BI output into one release archive.

    Discovers every domain declared in this hub, compiles and projects Gold for each
    one that authors a Gold profile (``kairos-ext:goldProductProfile``), validates the
    result the same way ``emit-gold`` does, and zips the ``*.SemanticModel``/``*.Report``
    folders of every such domain into one archive with a recorded SHA-256.

    A hub with no Gold-configured domain produces no archive: this command reports
    that and exits successfully rather than emitting a dangling, empty artifact.

    \b
    Examples:
      kairos-ontology package-powerbi-release
      kairos-ontology package-powerbi-release --confirm-emit
      kairos-ontology package-powerbi-release --confirm-emit --output dist/powerbi.zip
    """
    from ..cli.compile import _hub_domains
    from ..core.projections.dbt.gold_release_package import build_powerbi_release_archive
    from ..core.projections.dbt.gold_specs import GoldContractError
    from ..core.projections.dbt.pbip_validate import validate_package_artifacts
    from ..core.projections.dbt.tmdl_validate import validate_tmdl_artifacts
    from ..core.projections.medallion_gold_projector import generate_gold_from_compile_plan

    hub_root = find_hub_root(Path.cwd(), require_model=True)
    if hub_root is None:
        raise click.ClickException(
            "Cannot locate a hub (model/ + integration/) from the current directory."
        )

    domain_artifacts: dict[str, dict[str, str]] = {}
    skipped: list[str] = []
    for domain in _hub_domains(hub_root):
        plan = build_compile_plan(hub_root, domain)
        if plan.blocked:
            for diagnostic in plan.diagnostics.ordered:
                click.echo(diagnostic.render(), err=True)
            raise click.ClickException(f"{domain}: compile plan is blocked; see diagnostics above")

        contract = plan.normalized_contract
        if contract is None or contract.policy.gold.profile is None:
            skipped.append(domain)
            continue

        try:
            artifacts = generate_gold_from_compile_plan(plan)
        except GoldContractError as exc:
            raise click.ClickException(f"{domain}: {exc}") from exc

        package_failures = [
            result for result in validate_package_artifacts(artifacts) if result.status != "pass"
        ]
        if package_failures:
            detail = "; ".join(f"{item.artifact_path}: {item.message}" for item in package_failures)
            raise click.ClickException(
                f"{domain}: Fabric package validation failed for "
                f"{len(package_failures)} file(s): {detail}"
            )

        if not skip_tmdl_validation:
            tmdl_results = validate_tmdl_artifacts(artifacts)
            failures = [result for result in tmdl_results if result.status == "fail"]
            for result in tmdl_results:
                if result.status == "unavailable":
                    click.echo(
                        f"   (TOM SDK validation unavailable for {domain} "
                        f"{result.definition_root}: {result.message})"
                    )
            if failures:
                detail = "; ".join(
                    f"{item.definition_root}: {item.message}" for item in failures
                )
                raise click.ClickException(
                    f"{domain}: TMDL structural validation failed for "
                    f"{len(failures)} model(s): {detail}"
                )

        domain_artifacts[domain] = artifacts

    if skipped:
        click.echo(f"   (skipped, no Gold profile authored: {', '.join(skipped)})")

    try:
        archive = build_powerbi_release_archive(domain_artifacts)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if archive is None:
        click.echo("No Gold-configured domain contributes a Power BI item; nothing to package.")
        return

    verb = "Would package" if not confirm_emit else "Packaged"
    click.echo(
        f"✅ {verb} {archive.file_count} file(s) across {len(archive.domains)} "
        f"domain(s) ({', '.join(archive.domains)}) into {output}"
    )
    click.echo(f"   sha256: {archive.sha256}")
    if not confirm_emit:
        click.echo("   (dry run -- pass --confirm-emit to write the archive)")
        return

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(archive.zip_bytes)
    sidecar = output.with_name(f"{output.name}.sha256")
    sidecar.write_text(f"{archive.sha256}  {output.name}\n", encoding="utf-8")
    click.echo(f"   → {output}")
    click.echo(f"   → {sidecar}")
