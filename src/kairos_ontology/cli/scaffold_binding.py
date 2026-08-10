# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Click surface for ``kairos-ontology scaffold-binding``."""

from __future__ import annotations

from pathlib import Path

import click

from .shared import _autodetect_analysis_dir, _resolve_ref_models_dir


@click.command(name="scaffold-binding")
@click.option("--system", default=None, help="Source system id (integration/sources/<system>/).")
@click.option("--table", default=None, help="Bronze table name within --system.")
@click.option(
    "--archetype",
    "archetype_id",
    default=None,
    type=click.Choice(
        ["passthrough", "single-source-master", "merged-master", "event-stream", "line-item-child"]
    ),
    help="Binding shape to scaffold (see --list-archetypes).",
)
@click.option(
    "--target-class",
    default=None,
    help="Full class IRI or 'prefix:Local' qname to bind to (accelerator-direct by default; "
    "no local subclass is minted). Required unless --from-binding supplies one.",
)
@click.option(
    "--domain",
    default=None,
    help="Hub domain (default: inferred from an existing analyse-sources affinity report).",
)
@click.option(
    "--from-binding",
    "from_binding",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Seed a merged-master skeleton's fields: from an existing passthrough binding "
    "(promotion path).",
)
@click.option(
    "--out",
    "out_path",
    type=click.Path(),
    default=None,
    help="Output path (default: integration/bindings/<system>-<table>-to-<domain>.binding.yaml).",
)
@click.option("--force", is_flag=True, default=False, help="Overwrite an existing output path.")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Compute and report what would be scaffolded without writing any file.",
)
@click.option(
    "--accelerator", default=None, help="Accelerator pack (default: resolved from hub config)."
)
@click.option(
    "--ref-models",
    "ref_models_dir_opt",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Reference-models checkout (default: auto-detect).",
)
@click.option("--catalog", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option(
    "--list-unscaffolded",
    is_flag=True,
    default=False,
    help="List tables under integration/sources/<system>/ with no EntityBinding yet (read-only; "
    "requires --system only).",
)
@click.option(
    "--list-archetypes",
    is_flag=True,
    default=False,
    help="Print the scaffold-binding archetype catalog and exit.",
)
def scaffold_binding_cmd(
    system,
    table,
    archetype_id,
    target_class,
    domain,
    from_binding,
    out_path,
    force,
    dry_run,
    accelerator,
    ref_models_dir_opt,
    catalog,
    list_unscaffolded,
    list_archetypes,
):
    """Scaffold a first-draft v5 EntityBinding YAML for one Bronze source table.

    Authoring an EntityBinding is otherwise 100% manual. ``passthrough`` writes a
    ready-to-compile binding (plus a dbt staging model); the other archetypes write a
    canonical-tier skeleton with sentinel placeholders for the fields that carry irreducible
    modeling judgement (grain, identity, and -- for merged-master -- survivorship), which
    ``compile --check`` rejects until a human confirms them.

    \b
    Examples:
      kairos-ontology scaffold-binding --list-archetypes
      kairos-ontology scaffold-binding --list-unscaffolded --system crm
      kairos-ontology scaffold-binding --system crm --table organisations \\
          --archetype passthrough --target-class acc:TradeParty
      kairos-ontology scaffold-binding --system crm --table organisations \\
          --archetype merged-master --from-binding integration/bindings/crm-organisations-to-party.binding.yaml
    """
    from ..core.binding_archetypes import BindingArchetypeError, list_binding_archetypes
    from ..core.hub_utils import find_hub_root
    from ..core.scaffold_binding import (
        ScaffoldBindingError,
        list_unscaffolded_tables,
        run_scaffold_binding,
    )

    if list_archetypes:
        for archetype in list_binding_archetypes():
            click.echo(f"{archetype.id:<22} [{archetype.tier:<11}] {archetype.label}")
            click.echo(f"    {archetype.description}")
        return

    hub_root = find_hub_root(Path.cwd(), require_model=True)
    if hub_root is None:
        raise click.ClickException(
            "Cannot locate a hub (model/ + integration/) from the current directory."
        )

    if list_unscaffolded:
        if not system:
            raise click.UsageError("--list-unscaffolded requires --system.")
        tables = list_unscaffolded_tables(hub_root, system)
        if not tables:
            click.echo(
                f"✅ Every table under integration/sources/{system}/ already has an EntityBinding."
            )
            return
        click.echo(
            f"Tables under integration/sources/{system}/ with no EntityBinding yet ({len(tables)}):"
        )
        for name in tables:
            click.echo(f"  - {name}")
        return

    missing = [
        flag
        for flag, value in (("--system", system), ("--table", table), ("--archetype", archetype_id))
        if not value
    ]
    if missing:
        raise click.UsageError(
            f"{', '.join(missing)} required (or use --list-unscaffolded/--list-archetypes)."
        )

    cwd = Path.cwd()
    ref_models_dir = (
        Path(ref_models_dir_opt) if ref_models_dir_opt else _resolve_ref_models_dir(cwd, hub_root)
    )
    catalog_path = Path(catalog) if catalog else None
    if catalog_path is None:
        candidate = hub_root / "catalog-v001.xml"
        catalog_path = candidate if candidate.is_file() else None
    analysis_dir = _autodetect_analysis_dir(cwd, hub_root)

    try:
        result = run_scaffold_binding(
            hub_root,
            system=system,
            table=table,
            archetype_id=archetype_id,
            target_class=target_class,
            domain=domain,
            from_binding=Path(from_binding) if from_binding else None,
            out_path=Path(out_path) if out_path else None,
            force=force,
            ref_models_dir=ref_models_dir,
            catalog_path=catalog_path,
            accelerator=accelerator,
            analysis_dir=analysis_dir,
            dry_run=dry_run,
        )
    except (ScaffoldBindingError, BindingArchetypeError) as exc:
        raise click.ClickException(str(exc)) from exc

    verb = "Would scaffold" if dry_run else "Scaffolded"
    click.echo(f"✅ {verb} {result.archetype.label} binding: {result.binding_path}")
    click.echo(f"   Domain: {result.domain}   Target class: {result.target_class}")
    if result.mapped_columns:
        click.echo(
            f"   Mapped columns ({len(result.mapped_columns)}): {', '.join(result.mapped_columns)}"
        )
    if result.technical_field_columns:
        click.echo(
            f"   Technical fields, DD-139, not ontology properties "
            f"({len(result.technical_field_columns)}): {', '.join(result.technical_field_columns)}"
        )
    if result.orphan_columns:
        click.echo(
            f"   ⚠ Orphan columns -- no property match ({len(result.orphan_columns)}): "
            f"{', '.join(result.orphan_columns)}"
        )
    stub = result.ontology_stub
    if stub is not None:
        prefix = "Would create" if stub.dry_run else "Created"
        prefix_import = "Would add" if stub.dry_run else "Added"
        if stub.created:
            click.echo(f"   {prefix} machine-managed ontology stub: {stub.path}")
        elif stub.import_added:
            click.echo(f"   {prefix_import} owl:imports to: {stub.path}")
    if result.dbt_model_written:
        click.echo(f"   dbt staging model: {result.dbt_model_path}")
    elif dry_run and result.dbt_model_path is not None:
        click.echo(f"   Would write dbt staging model: {result.dbt_model_path}")
    if result.archetype.tier == "canonical":
        extra = ", and conformance" if result.archetype.scaffold_conformance else ""
        click.echo(f"   ⚠ This is a SKELETON: confirm grain, identity{extra} before compiling.")
    for note in result.notes:
        click.echo(f"   NOTE: {note}")
