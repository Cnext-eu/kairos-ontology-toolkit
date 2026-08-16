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
from ..core.conformance_artifact import check_discovery_gate
from ..core.hub_utils import find_hub_root, publish_root
from ..core.observability import current_operation_id

#: dbt project sub-path under the publish root (``<publish_root>/medallion/dbt``).
_DBT_EMIT_SUBPATH = Path("medallion") / "dbt"
_SHARED_MANIFEST_NAME = ".kairos-compile-manifest.shared.json"
_PACKAGE_ARTIFACTS = frozenset({"README.md", "dbt_project.yml", "packages.yml"})


def _domain_integrity_failures(hub: Path, domain: str) -> list:
    """Return this domain's non-degradable integrity errors, or ``[]``.

    Best-effort by design: a hub with no resolvable accelerator, or an ontology
    directory that cannot be read, yields no findings rather than blocking a compile on
    an infrastructure problem. The blueprint-boundary check needs the accelerator and is
    degradable anyway, so it is deliberately not consulted here — only the two
    correctness codes, which need nothing but the hub's own files.
    """
    try:
        from ..core.ontology_integrity import NON_DEGRADABLE_CODES, audit_ontology_integrity

        report = audit_ontology_integrity(
            ontologies_dir=hub / "model" / "ontologies",
            data_domains={},
            domains=[domain],
        )
    except Exception:  # noqa: BLE001 - never fail a compile on the guard itself
        return []
    return [item for item in report.errors if item.code in NON_DEGRADABLE_CODES]


def _payload(result) -> dict:
    return {
        "domain": result.domain,
        "mode": result.mode,
        "succeeded": result.succeeded,
        "provenance_hash": result.provenance_hash,
        "operation_id": current_operation_id(),
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
    "not configurable. Requires --confirm-emit.",
)
@click.option(
    "--confirm-emit",
    "confirm_emit",
    is_flag=True,
    help="Required alongside --emit. Confirms this is an explicit, execution-phase "
    "invocation (owned by kairos-execute-project) — prevents design-time skills "
    "from accidentally emitting compiled artifacts.",
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
    confirm_emit: bool,
    output_format: str,
) -> None:
    """Check, explain, or emit one v5 DOMAIN from the current hub.

    ``--check`` and ``--explain`` may be combined in a single invocation to get both
    the diagnostic stream and the structured explain report together. ``--emit`` is
    the only side-effecting mode and remains mutually exclusive with the other two.
    """
    if emit_mode and (check_mode or explain_mode):
        raise click.UsageError("--emit cannot be combined with --check or --explain")
    if not emit_mode and not check_mode and not explain_mode:
        raise click.UsageError(
            "exactly one of --emit, or at least one of --check/--explain, is required"
        )
    if emit_mode and not confirm_emit:
        raise click.UsageError(
            "--emit requires --confirm-emit. Emitting is an execution-phase action "
            "owned by kairos-execute-project — design skills (kairos-design-mapping, "
            "kairos-design-domain) must never pass --emit. If you are "
            "kairos-execute-project running after a successful check and explicit "
            "output-path confirmation, pass --confirm-emit."
        )
    mode = (
        CompileMode.EMIT if emit_mode else CompileMode.CHECK if check_mode else CompileMode.EXPLAIN
    )
    hub = find_hub_root(Path.cwd(), require_model=True) or Path.cwd()
    # Domain-scoped (issue #389/#390): compile is inherently single-domain (domain is a
    # required positional argument here), so an unresolved DD-148 judgment tagged to a
    # different domain no longer blocks this domain's compile; cross-cutting or
    # matching-domain judgments still do.
    discovery_errors = check_discovery_gate(hub, domains=[domain])
    if discovery_errors:
        for error in discovery_errors:
            click.echo(f"✗ {error}", err=True)
        raise click.exceptions.Exit(1)

    # Ontology integrity, at the stage the damage is done (DD-163). Binding authoring is
    # where an agent is under pressure to make `binding.unknown-property` go away, and
    # minting the missing term locally is the fastest way to do it. validate would catch
    # the result, but not until a later stage -- the previous run's cross-domain
    # duplicates reached a dbt build failure before anything objected.
    #
    # Scoped to this domain and to the non-degradable subset only: a compile must not be
    # blocked by another domain's boundary divergence, and these two codes are
    # correctness failures a hub can always fix itself.
    # DD-169: the last point before a binding makes an omission permanent. Compile is
    # what a binding author runs, so gating it here is what "close the gap before entity
    # binding" actually means in practice.
    try:
        from ..core.alignment_report import GAP_RESOLUTIONS, undecided_gap_columns

        undecided = undecided_gap_columns(hub, domains=[domain])
    except Exception:  # noqa: BLE001 - never fail a compile on the guard itself
        undecided = []
    if undecided:
        click.echo(
            f"✗ {len(undecided)} source column(s) in '{domain}' carry real business data "
            "with no canonical home and no recorded decision:",
            err=True,
        )
        for column in undecided[:10]:
            click.echo(
                f"    {column.system}.{column.table}.{column.column} "
                f"({column.data_type}) [{column.reason}]",
                err=True,
            )
        if len(undecided) > 10:
            click.echo(f"    … and {len(undecided) - 10} more", err=True)
        click.echo("  Resolve each by one of:", err=True)
        for resolution in GAP_RESOLUTIONS:
            click.echo(f"    - {resolution}", err=True)
        raise click.exceptions.Exit(1)

    integrity_failures = _domain_integrity_failures(hub, domain)
    if integrity_failures:
        for finding in integrity_failures:
            click.echo(f"✗ {finding.message}", err=True)
            click.echo(f"  ↪ {finding.remediation}", err=True)
        click.echo(
            "✗ ontology integrity must pass before a binding compiles; "
            "run 'kairos-ontology validate --all' for the full picture",
            err=True,
        )
        raise click.exceptions.Exit(1)

    result = compile_domain(hub, domain, mode)
    if check_mode and explain_mode:
        # Both diagnostics and the explain report are already computed as part of the
        # same plan (CompileResult always carries both), so this is a free relabel —
        # not a second compile.
        result = replace(result, mode="check+explain")
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
            if check_mode:
                click.echo(f"✓ {domain}: compile check passed")
            if explain_mode:
                report = result.explain
                click.echo(f"✓ {domain}: {len(report.entities)} entity binding(s)")
                for entity in report.entities:
                    click.echo(
                        f"  {entity.name}: {entity.source} → {entity.target_class} "
                        f"[grain: {', '.join(entity.grain)}]"
                    )
                    for gm in entity.grain_mechanisms:
                        click.echo(
                            f"    grain: {gm.column} via {gm.mechanism}"
                            + (f" → {gm.output}" if gm.output else "")
                        )
                    for rel in entity.relationship_shapes:
                        joins = f" on ({', '.join(rel.join)})" if rel.join else ""
                        temporal = " temporal" if rel.temporal else ""
                        click.echo(
                            f"    rel: {rel.property} → {rel.target} "
                            f"[{rel.cardinality}, {rel.mode}{temporal}]{joins}"
                        )
                    for check in entity.quality:
                        emitted = f" → {check.emitted_test}" if check.emitted_test else ""
                        columns = f"({', '.join(check.columns)})" if check.columns else ""
                        click.echo(f"    dq: {check.kind}{columns}{emitted}")
                    for rule in entity.data_quality:
                        quarantine = f" quarantine={rule.quarantine}" if rule.quarantine else ""
                        click.echo(
                            f"    dq-rule: {rule.rule_id} [{rule.kind}] "
                            f"scope={rule.scope} action={rule.action} "
                            f"severity={rule.severity}{quarantine}"
                        )
                        click.echo(f"      → {rule.result_model}")
                        click.echo(f"      → {rule.result_test}")
                for path in report.artifact_paths:
                    click.echo(f"  {path}")
            if emit_mode:
                click.echo(
                    f"✓ {domain}: emitted {len(result.artifacts)} artifact(s) to {emit_target}"
                )
    if not result.succeeded:
        raise click.exceptions.Exit(1)
