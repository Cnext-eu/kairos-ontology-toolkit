# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Click surface for ``kairos-ontology scaffold-staging`` (issue #399)."""

from __future__ import annotations

from pathlib import Path

import click


@click.command(name="scaffold-staging")
@click.option("--entity", required=True, help="Entity name, e.g. 'party' (models are named "
    "stg_<system>__<entity> and int_merged__<entity>).")
@click.option("--domain", required=True, help="Hub domain owning the merged model.")
@click.option(
    "--source",
    "sources",
    multiple=True,
    required=True,
    help="'<system>.<table>' contributing to the merged entity. Repeatable; a single source "
    "scaffolds a trivial passthrough int_merged__<entity> (issue #616's day-one pattern), "
    "two or more scaffold a real survivorship model.",
)
@click.option("--force", is_flag=True, default=False, help="Overwrite existing output files.")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Compute and report what would be scaffolded without writing any file.",
)
def scaffold_staging_cmd(entity, domain, sources, force, dry_run):
    """Scaffold first-class stg_<source>__<entity> + int_merged__<entity> staging (issue #399, #616).

    kairos-develop-dbt-transformation/SKILL.md already documents this layering -- one
    stg_<source>__<entity> model per contributing source, feeding one merged survivorship
    model -- as a convention with no tooling behind it. This writes the starter SQL +
    properties YAML for each stage (reusing the same per-table staging SELECT
    scaffold-binding's passthrough archetype already generates) plus the merged model.

    With two or more --source entries, the merged model is a survivorship skeleton with
    sentinel placeholders for the judgment a human must confirm (natural key, priority
    order, target class, virtual source identity) -- compile --check rejects the merged
    model's contract until those are filled in. With a single --source entry (the
    kairos-design-mapping/SKILL.md day-one pattern for master/business-entity accelerator
    classes), the merged model is a trivial passthrough of its one stage -- no
    natural-key/priority sentinels, since there is nothing yet to reconcile.

    \b
    Examples:
      kairos-ontology scaffold-staging --entity party --domain party \\
          --source cargowise.OrgCompanyData
      kairos-ontology scaffold-staging --entity party --domain party \\
          --source crm.customers --source erp.parties
    """
    from ..core.hub_utils import find_hub_root
    from ..core.scaffold_binding import ScaffoldBindingError
    from ..core.scaffold_staging import ScaffoldStagingError, run_scaffold_staging

    hub_root = find_hub_root(Path.cwd(), require_model=True)
    if hub_root is None:
        raise click.ClickException(
            "Cannot locate a hub (model/ + integration/) from the current directory."
        )

    parsed_sources: list[tuple[str, str]] = []
    for token in sources:
        if "." not in token:
            raise click.UsageError(f"--source must be '<system>.<table>', got {token!r}")
        system, table = token.split(".", 1)
        parsed_sources.append((system, table))

    try:
        result = run_scaffold_staging(
            hub_root,
            entity=entity,
            domain=domain,
            sources=tuple(parsed_sources),
            force=force,
            dry_run=dry_run,
        )
    except (ScaffoldStagingError, ScaffoldBindingError) as exc:
        raise click.ClickException(str(exc)) from exc

    verb = "Would scaffold" if dry_run else "Scaffolded"
    click.echo(f"✅ {verb} {len(result.stages)} stage(s) + 1 merged model for '{entity}':")
    for stage in result.stages:
        click.echo(f"   - {stage.model_name}: {stage.sql_path}")
    click.echo(f"   - {result.merged_model_name}: {result.merged_sql_path}")
    click.echo(
        f"   Common columns across every stage ({len(result.common_columns)}): "
        f"{', '.join(result.common_columns) or '(none)'}"
    )
    if len(result.stages) == 1:
        click.echo(
            "   ⚠ The merged model is a single-source passthrough SKELETON: confirm the "
            "target class and virtual source IRI (search for <CONFIRM_...>) before compiling."
        )
    else:
        click.echo(
            "   ⚠ The merged model is a SKELETON: confirm the natural key, priority order, "
            "target class, and virtual source IRI (search for <CONFIRM_...>) before compiling."
        )
    for note in result.notes:
        click.echo(f"   NOTE: {note}")
