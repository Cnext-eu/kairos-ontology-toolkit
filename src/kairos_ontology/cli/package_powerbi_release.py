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

from .gates import escape_option

from ..core.compiler import build_compile_plan
from ..core.observability import events, spans
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
@escape_option(
    "gold.tmdl-structural-validation",
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

    Rendering runs the same Best Practice Analyzer assertions as ``emit-gold`` (DD-238),
    so no archive is built for a model that breaks one; see ``emit-gold`` for the codes.

    A hub with no Gold-configured domain produces no archive: this command reports
    that and exits successfully rather than emitting a dangling, empty artifact.

    \b
    Examples:
      kairos-ontology package-powerbi-release
      kairos-ontology package-powerbi-release --confirm-emit
      kairos-ontology package-powerbi-release --confirm-emit --output dist/powerbi.zip
    """
    from ..cli.compile import _hub_domains
    from ..core.projections.dbt.gold_connection import GoldProductConfig, load_gold_products
    from ..core.projections.dbt.gold_release_package import build_powerbi_release_archive

    hub_root = find_hub_root(Path.cwd(), require_model=True)
    if hub_root is None:
        raise click.ClickException(
            "Cannot locate a hub (model/ + integration/) from the current directory."
        )
    from .run_log import start_run_log

    start_run_log(hub_root, "package-powerbi-release")

    # Declared products first, then every Gold-configured domain no product claims as its
    # own implicit product (#744). A hub that declares nothing packages exactly what it
    # packaged before: one item per Gold-configured domain, under its own name.
    declared = load_gold_products(hub_root)
    claimed = {domain for product in declared for domain in product.domains}
    hub_domains = list(_hub_domains(hub_root))
    unknown = sorted(
        domain for product in declared for domain in product.domains if domain not in hub_domains
    )
    if unknown:
        raise click.ClickException(
            f"gold.products names domain(s) not in this hub: {', '.join(unknown)}"
        )
    products = [
        *declared,
        *(
            GoldProductConfig(name=domain, domains=(domain,), declared=False)
            for domain in hub_domains
            if domain not in claimed
        ),
    ]

    domain_artifacts: dict[str, dict[str, str]] = {}
    skipped: list[str] = []
    for product in products:
        # One product span, so its gates group under it in the run log (#1011).
        with spans.task_span(
            "product", f"gold:{product.name}", **{"kairos.product": product.name}
        ):
            artifacts = _package_product(
                hub_root, product, skipped, skip_tmdl_validation=skip_tmdl_validation
            )
        if artifacts is not None:
            domain_artifacts[product.name] = artifacts

    if skipped:
        click.echo(f"   (skipped, no Gold profile authored: {', '.join(sorted(skipped))})")

    try:
        with spans.task_span("stage", "archive"):
            archive = build_powerbi_release_archive(domain_artifacts)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if archive is None:
        click.echo("No Gold-configured product contributes a Power BI item; nothing to package.")
        return

    verb = "Would package" if not confirm_emit else "Packaged"
    click.echo(
        f"✅ {verb} {archive.file_count} file(s) across {len(archive.domains)} "
        f"product(s) ({', '.join(archive.domains)}) into {output}"
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


def _package_product(
    hub_root: Path, product, skipped: list[str], *, skip_tmdl_validation: bool
) -> dict[str, str] | None:
    """Compile, render and validate one product; None when it has nothing to package."""
    from ..core.projections.dbt.gold_specs import GoldContractError
    from ..core.projections.medallion_gold_projector import generate_gold_from_compile_plans
    from .emit_gold import _check_package, _check_tmdl, _refuse

    command = "package-powerbi-release"
    plans = []
    with spans.task_span("gate", "compile"):
        for member in product.domains:
            plan = build_compile_plan(hub_root, member)
            if plan.blocked:
                for diagnostic in plan.diagnostics.ordered:
                    events.log_diagnostic(
                        diagnostic, command=command, domain=member, gate="compile"
                    )
                    click.echo(diagnostic.render(), err=True)
                spans.mark_refused()
                raise click.ClickException(
                    f"{member}: compile plan is blocked; see diagnostics above"
                )
            contract = plan.normalized_contract
            if contract is None or contract.policy.gold.profile is None:
                # An implicit product is just a domain, and a domain without a Gold
                # profile has always been skipped. A *declared* product naming such a
                # domain is an authoring error, and is reported as one by the projector.
                if not product.declared:
                    skipped.append(member)
                    return None
            plans.append(plan)

    with spans.task_span("gate", "gold-shape"):
        try:
            artifacts = generate_gold_from_compile_plans(plans, product)
        except GoldContractError as exc:
            _refuse(exc, product=product.name, gate="gold-shape", command=command)
            raise click.ClickException(f"{product.name}: {exc}") from exc

    _check_package(artifacts, product, command=command, label=product.name)
    if not skip_tmdl_validation:
        _check_tmdl(artifacts, product, command=command, label=product.name)
    return artifacts
