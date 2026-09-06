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
from ..core.determinism import write_text_lf
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
@click.argument("domain", metavar="PRODUCT_OR_DOMAIN")
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
    from ..cli.compile import _hub_domains
    from ..core.compiler.emit import emit_artifacts
    from ..core.compiler.provenance import provenance_artifact
    from ..core.insights import InsightsError
    from ..core.projections.dbt.gold_connection import resolve_gold_product
    from ..core.projections.dbt.gold_specs import GoldContractError
    from ..core.projections.dbt.tmdl_validate import validate_tmdl_artifacts
    from ..core.projections.medallion_gold_projector import (
        plan_gold_from_compile_plans,
        render_gold_product,
    )

    hub_root = find_hub_root(Path.cwd(), require_model=True)
    if hub_root is None:
        raise click.ClickException(
            "Cannot locate a hub (model/ + integration/) from the current directory."
        )

    try:
        product = resolve_gold_product(hub_root, domain, hub_domains=tuple(_hub_domains(hub_root)))
    except GoldContractError as exc:
        raise click.ClickException(str(exc)) from exc

    plans = []
    for member in product.domains:
        plan = build_compile_plan(hub_root, member)
        if plan.blocked:
            for diagnostic in plan.diagnostics.ordered:
                click.echo(diagnostic.render(), err=True)
            raise click.ClickException(f"{member}: compile plan is blocked; see diagnostics above")
        contract = plan.normalized_contract
        if contract is None or contract.policy.gold.profile is None:
            raise click.ClickException(
                f"{member} has no authored Gold profile "
                "(kairos-ext:goldProductProfile) -- nothing to emit"
            )
        plans.append(plan)

    try:
        # Shaped once and reused: the coverage report below reads the same spec, and
        # shaping a product twice per emit is pure waste.
        logical, _ = plan_gold_from_compile_plans(plans, product)
        artifacts = render_gold_product(logical, plans, product)
    except GoldContractError as exc:
        raise click.ClickException(str(exc)) from exc
    except InsightsError as exc:
        # Rendering reads insights.yaml to build the brief, so a malformed file surfaces
        # here rather than in the coverage report below. Without this the operator gets a
        # Python traceback for a stray tab in their own YAML.
        raise click.ClickException(f"insights.yaml is unusable: {exc}") from exc

    # DD-218. The Gold lane emits into its own manifest-owned subtree, so it carries its
    # own sidecar rather than relying on the Silver one; `lane` keeps the two paths apart
    # when both land under the same `metadata/` prefix. One per participating domain: the
    # sidecar records a build scope, and a product has one scope per domain it compiled.
    for plan in plans:
        provenance_path, provenance_content = provenance_artifact(plan.scope, lane="gold")
        artifacts[provenance_path] = provenance_content

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
    manifest_name = _gold_manifest_name(product.name)
    label = (
        f"{product.name!r} ({', '.join(product.domains)})"
        if len(product.domains) > 1
        else f"{product.name!r}"
    )
    verb = "Would emit" if not confirm_emit else "Emitted"
    click.echo(f"✅ {verb} {len(artifacts)} Gold artifact(s) for {label} to {target}")
    _report_unresolved(artifacts, product)
    _report_insight_coverage(hub_root, logical, product)
    if not confirm_emit:
        click.echo("   (dry run -- pass --confirm-emit to write these files)")
        return

    _retire_superseded_manifests(target, product)

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


@click.command(name="harvest-gold")
@click.argument("product", metavar="PRODUCT_OR_DOMAIN")
@click.option(
    "--from",
    "source",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="The edited semantic model: a PBIP export folder, a '<Name>.SemanticModel' "
    "folder, or its 'definition/' folder. Power BI Desktop writes this with "
    "'Save as PBIP'; for a Direct Lake model, export it through Fabric git integration "
    "instead -- Direct Lake cannot be saved as a PBIP from Desktop.",
)
def harvest_gold_cmd(product: str, source: Path) -> None:
    """Diff an edited semantic model against this hub and propose the authoring.

    A BI engineer opens the generated PBIP, hides a column, adds measures -- and the next
    `emit-gold` overwrites all of it. This reads the edited model, compares it with what
    the hub would emit now, and writes two review documents under
    `model/planning/gold-harvest/`: a Markdown diff, and a Turtle snippet of the changes
    that have authoring vocabulary.

    Nothing is applied. Merging an edit straight into `model/extensions/` would make the
    hub's own authored inputs a downstream artifact of a report, which inverts the
    ownership the whole design depends on. Review the proposal, paste what you agree with
    into the owning domain's Gold extension, and re-emit.

    \b
    Examples:
      kairos-ontology harvest-gold invoicing --from ../edited/Invoicing.SemanticModel
      kairos-ontology harvest-gold party --from ../export
    """
    from ..cli.compile import _hub_domains
    from ..core.compiler.kernel import build_compile_plan
    from ..core.determinism import write_text_lf
    from ..core.insights import InsightsError
    from ..core.gold_harvest import (
        HARVEST_RELDIR,
        diff_models,
        load_edited_model,
        render_proposal,
        render_report,
    )
    from ..core.projections.dbt.gold_connection import resolve_gold_product
    from ..core.projections.dbt.gold_specs import GoldContractError
    from ..core.projections.medallion_gold_projector import generate_gold_from_compile_plans
    from ..core.tmdl_parser import parse_tmdl_content

    hub_root = find_hub_root(Path.cwd(), require_model=True)
    if hub_root is None:
        raise click.ClickException(
            "Cannot locate a hub (model/ + integration/) from the current directory."
        )
    try:
        resolved = resolve_gold_product(
            hub_root, product, hub_domains=tuple(_hub_domains(hub_root))
        )
    except GoldContractError as exc:
        raise click.ClickException(str(exc)) from exc

    plans = []
    for member in resolved.domains:
        plan = build_compile_plan(hub_root, member)
        if plan.blocked:
            raise click.ClickException(f"{member}: compile plan is blocked; run compile --check")
        plans.append(plan)
    try:
        artifacts = generate_gold_from_compile_plans(plans, resolved)
    except GoldContractError as exc:
        raise click.ClickException(str(exc)) from exc
    except InsightsError as exc:
        raise click.ClickException(f"insights.yaml is unusable: {exc}") from exc

    emitted = _model_from_artifacts(artifacts, parse_tmdl_content)
    try:
        edited = load_edited_model(source)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    result = diff_models(emitted, edited, product=resolved.name)
    domain_of_table = _table_domains(plans)

    output_dir = hub_root / HARVEST_RELDIR
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{resolved.name}.md"
    proposal_path = output_dir / f"{resolved.name}-proposal.ttl"
    write_text_lf(report_path, render_report(result))
    write_text_lf(proposal_path, render_proposal(result, domain_of_table=domain_of_table))

    counts = (
        f"{len(result.new_measures)} new measure(s), "
        f"{len(result.changed_measures)} changed, "
        f"{len(result.hidden_columns)} column(s) hidden"
    )
    click.echo(f"✅ Harvested {resolved.name!r}: {counts}")
    click.echo(f"   → {report_path}")
    click.echo(f"   → {proposal_path}")
    if result.empty:
        click.echo("   (the deployed model matches the hub; nothing to author)")
    else:
        click.echo("   Review, then merge the proposal into the owning domain's Gold extension.")


def _model_from_artifacts(artifacts: dict[str, str], parse_tmdl_content):
    """Rebuild a TmdlModel from the in-memory emit, without writing it to disk."""
    from ..core.tmdl_parser import TmdlModel

    model = TmdlModel(name="emitted")
    for path, content in sorted(artifacts.items()):
        if "/definition/tables/" not in path or not path.endswith(".tmdl"):
            continue
        for item in parse_tmdl_content(content):
            if hasattr(item, "columns"):
                model.tables.append(item)
    return model


def _table_domains(plans) -> dict[str, str]:
    """Map each emitted Gold table name to the domain that authors it.

    A multi-domain product's tables are authored across several extension files, so a
    proposal has to say which one each item belongs in.
    """
    mapping: dict[str, str] = {}
    for plan in plans:
        contract = plan.normalized_contract
        if contract is None:
            continue
        for table in contract.policy.gold.tables:
            mapping[table.table_name.value] = plan.resolution.ontology_name
    return mapping


def _report_unresolved(artifacts: dict[str, str], product) -> None:
    """Warn about a foreign key whose target table is not in this product (#744).

    Not fatal: the model is valid and useful without the join, and the fix is an authoring
    decision -- add the owning domain to the product, or accept the dead column. Before
    #744 this was silent, and a cross-domain product lost half its star with no signal.
    """
    import json

    report = next(
        (content for name, content in artifacts.items() if name.endswith("-gold-product.json")),
        None,
    )
    if report is None:
        return
    unresolved = json.loads(report).get("unresolved_relationships") or []
    if not unresolved:
        return
    click.echo(
        f"   ⚠ {len(unresolved)} relationship(s) have no target table in this product; "
        "their join columns are emitted but nothing joins them:"
    )
    for item in unresolved:
        click.echo(f"       {item['source_table']} -> {item['target_class']}")
    click.echo(
        "     Add the owning domain to this product in kairos.yaml (gold.products), "
        "or author the target as a Gold table in a participating domain."
    )


def _report_insight_coverage(hub_root: Path, logical, product) -> None:
    """Warn when a confirmed insight names something this product does not carry (#744).

    A warning, not a gate: an insight is a statement of what the business wants to know,
    and the gap between that and what the model answers is a backlog, not a build failure.
    """
    from ..core.insights import InsightsError
    from ..core.projections.medallion_gold_projector import insight_coverage_for

    try:
        coverage = insight_coverage_for(logical, product, hub_root)
    except InsightsError as exc:
        raise click.ClickException(f"insights.yaml is unusable: {exc}") from exc
    gaps = [item for item in coverage if not item.covered]
    if not coverage:
        return
    click.echo(f"   {len(coverage) - len(gaps)}/{len(coverage)} confirmed insight(s) answerable")
    for item in gaps:
        missing = ", ".join((*item.missing_measures, *item.missing_dimensions))
        click.echo(f"     ⚠ {item.insight.id}: missing {missing}")


def _retire_superseded_manifests(target: Path, product) -> None:
    """Remove the per-domain Gold trees a declared product now supersedes (#744).

    ``emit_artifacts`` only removes files its *own* manifest owns, so a domain that used
    to emit `booking/Booking.SemanticModel` and is now part of a product would leave that
    whole tree behind: the master ERD would merge its stale diagram, and fabric-cicd,
    pointed at the folder, would deploy two models where the hub declares one.

    Emitting an empty artifact set under the old manifest deletes exactly what that
    manifest owned, through the same transaction as any other emit, and nothing else.
    """
    from ..core.compiler.emit import emit_artifacts

    if not product.declared:
        return
    for member in product.domains:
        if member == product.name:
            continue
        stale = target / _gold_manifest_name(member)
        if not stale.is_file():
            continue
        emit_artifacts({}, target, manifest_name=stale.name)
        stale.unlink(missing_ok=True)
        click.echo(f"   ↺ retired the superseded per-domain emit for {member!r}")


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
    write_text_lf(gold_output / "master-gold-erd.mmd", master_mmd)


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
