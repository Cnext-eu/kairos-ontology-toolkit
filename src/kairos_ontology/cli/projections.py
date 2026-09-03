# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused projections CLI commands."""

import click

from ..core.adapters import ADAPTER_CHOICES, FABRIC_WAREHOUSE
from pathlib import Path


from ..core.projector import (
    COMPILE_PLAN_ONLY_TARGETS,
    ProjectionRunError,
    RETIRED_COMPILER_TARGETS,
    projection_target_choices,
    run_projections,
)

# Importing the design-time MDM package registers the additive ``mdm-profile``
# projection target with the core projector (registry pattern, MDM-DD-002).
# The CLI is the layer that legitimately depends on both core and mdm.
from .. import mdm as _mdm  # noqa: F401  (import for side-effect: target registration)

from .shared import (
    _resolve_projection_cli_scope,
)


@click.command()
@click.option(
    "--ontologies",
    type=click.Path(exists=True),
    default=None,
    help="Path to ontologies directory (default: auto-detect from hub).",
)
@click.option(
    "--ontology",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to a single ontology file to project.",
)
@click.option(
    "--catalog",
    type=click.Path(exists=True),
    default=None,
    help="Path to catalog file for resolving imports "
    "(default: <hub>/catalog-v001.xml, "
    "overlaid with the installed reference-models package catalog)",
)
@click.option(
    "--ref-models",
    type=click.Path(),
    default=None,
    help="Reference-model repository containing accelerator module profiles.",
)
@click.option(
    "--accelerator",
    default=None,
    help="Accelerator pack used for managed-import projection preflight.",
)
@click.option(
    "--output",
    type=click.Path(),
    default=None,
    help="Output directory for projections (default: <repo>/ontology-hub-publish).",
)
@click.option(
    "--target",
    type=click.Choice(("all", *RETIRED_COMPILER_TARGETS, "gold", *projection_target_choices())),
    default="all",
    help="Projection target",
)
@click.option(
    "--platform",
    "--adapter",
    type=click.Choice(ADAPTER_CHOICES),
    default=FABRIC_WAREHOUSE,
    show_default=True,
    help="SQL platform for dbt projection.",
)
@click.option(
    "--namespace",
    type=str,
    default=None,
    help="Base namespace to project (e.g., http://example.org/ont/). Auto-detects if not provided.",
)
@click.option(
    "--degraded",
    is_flag=True,
    default=False,
    help="Explicitly allow projection from an incomplete import closure.",
)
def project(
    ontologies,
    ontology,
    catalog,
    ref_models,
    accelerator,
    output,
    target,
    platform,
    namespace,
    degraded,
):
    """Generate projections from ontologies."""
    if target in RETIRED_COMPILER_TARGETS:
        raise click.ClickException(
            f"`project --target {target}` is retired; use `kairos-ontology compile <domain> --emit`"
        )
    if target in {"powerbi", "gold"}:
        raise click.ClickException(
            f"`project --target {target}` is disabled because it bypasses the immutable "
            "CompilePlan; use `kairos-ontology compile <domain> --check|--explain` to "
            "validate the plan first, then `kairos-ontology emit-gold <domain> "
            "--confirm-emit` to project and write Gold/PowerBI artifacts."
        )
    if target in COMPILE_PLAN_ONLY_TARGETS:
        raise click.ClickException(
            f"`project --target {target}` is disabled because it bypasses the immutable "
            "CompilePlan; use `kairos-ontology compile <domain> --check|--explain|--emit`. "
            "It must consume the compiler-produced plan through the typed downstream "
            "registry (Python API only today: "
            "kairos_ontology.mdm.profile_projector.generate_mdm_profile_from_compile_plan)."
        )
    cwd = Path.cwd()
    if platform != FABRIC_WAREHOUSE and target not in {"dbt", "all"}:
        raise click.UsageError("--platform applies only to --target dbt or --target all")
    (
        ontologies_path,
        catalog_path,
        ref_models_path,
        hub_root,
        accelerator,
    ) = _resolve_projection_cli_scope(ontologies, ontology, catalog, ref_models, accelerator)

    if output is not None:
        output_path = Path(output)
    else:
        from ..core.hub_utils import publish_root

        if hub_root is not None:
            output_path = publish_root(hub_root)
        else:
            output_path = publish_root(cwd / "ontology-hub")

    try:
        run_projections(
            ontologies_path=ontologies_path,
            catalog_path=catalog_path,
            output_path=output_path,
            target=target,
            namespace=namespace,
            platform=platform,
            degraded=degraded,
            ref_models_dir=ref_models_path,
            accelerator=accelerator,
        )
    except ProjectionRunError as exc:
        raise click.ClickException(str(exc)) from exc


@click.command(name="scaffold-mapping")
@click.option("--domain", required=True)
@click.option("--source-table", required=True, help="Absolute SourceTable IRI.")
@click.option("--target-class", required=True, help="Absolute target owl:Class IRI.")
@click.option(
    "--existing-mapping",
    "existing_mappings",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Existing mapping evidence used only for denormalized-ownership advisories.",
)
@click.option("--catalog", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--overwrite", is_flag=True, help="Explicitly replace an existing output file.")
def scaffold_mapping_cmd(
    domain,
    source_table,
    target_class,
    existing_mappings,
    catalog,
    output,
    overwrite,
):
    """Preview or write evidence-grounded named v2 mapping proposals."""
    from ..core.authoring_scaffolds import (
        AuthoringScaffoldError,
        build_mapping_scaffold,
        write_text,
    )
    from ..core.hub_utils import find_hub_root

    hub = find_hub_root(Path.cwd(), require_model=True)
    if hub is None:
        raise click.ClickException("Cannot locate an ontology hub.")
    try:
        scaffold = build_mapping_scaffold(
            source_root=hub / "integration" / "sources",
            ontology_path=hub / "model" / "ontologies" / f"{domain}.ttl",
            source_table_uri=source_table,
            target_class_uri=target_class,
            catalog_path=catalog,
            existing_mapping_paths=existing_mappings,
        )
        content = scaffold.serialize()
        if output is None:
            click.echo(content)
        else:
            destination = output if output.is_absolute() else hub / output
            write_text(destination, content, overwrite=overwrite)
            click.echo(f"✓ Wrote mapping proposal scaffold: {destination}")
    except (AuthoringScaffoldError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Review required: {scaffold.proposals} proposals, {scaffold.review_items} "
        f"out-of-scope items, {scaffold.advisories} ownership advisories."
    )


@click.command(name="scaffold-silver-ext")
@click.option("--domain", required=True)
@click.option(
    "--mapping",
    "mappings",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--catalog", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--overwrite", is_flag=True, help="Explicitly replace an existing output file.")
def scaffold_silver_ext_cmd(domain, mappings, catalog, output, overwrite):
    """Preview or write a legacy, non-authoritative Silver skeleton.

    V5 execution policy belongs in closed EntityBinding YAML. This retained
    layout utility does not create v5 execution authority.
    """
    from ..core.authoring_scaffolds import (
        AuthoringScaffoldError,
        build_silver_scaffold,
        write_text,
    )
    from ..core.design_validation import resolve_silver_ext_shapes
    from ..core.hub_utils import find_hub_root

    hub = find_hub_root(Path.cwd(), require_model=True)
    if hub is None:
        raise click.ClickException("Cannot locate an ontology hub.")
    selected = tuple(mappings) or tuple(
        sorted((hub / "model" / "mappings").glob(f"*{domain}*.ttl"))
    )
    if not selected:
        raise click.ClickException(f"No scoped mapping evidence found for domain {domain!r}.")
    shapes_path, shape_source = resolve_silver_ext_shapes(hub)
    if shapes_path is None:
        raise click.ClickException(
            "No Silver-ext SHACL shape found: hub-local "
            "model/shapes/kairos-ext-shapes.shacl.ttl is absent and no packaged "
            "canonical shape is available. Run 'kairos-ontology update'."
        )
    click.echo(
        f"Using Silver-ext shapes: {shapes_path} (source: {shape_source})",
        err=True,
    )
    try:
        scaffold = build_silver_scaffold(
            source_root=hub / "integration" / "sources",
            ontology_path=hub / "model" / "ontologies" / f"{domain}.ttl",
            mapping_paths=selected,
            shapes_path=shapes_path,
            catalog_path=catalog,
        )
        content = scaffold.serialize()
        if output is None:
            click.echo(content)
        else:
            destination = output if output.is_absolute() else hub / output
            write_text(destination, content, overwrite=overwrite)
            click.echo(f"✓ Wrote Silver extension scaffold: {destination}")
    except (AuthoringScaffoldError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Review required: {scaffold.proposals} evidenced annotations and "
        f"{scaffold.review_items} governance choices."
    )
