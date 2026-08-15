# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Click surface for ``kairos-ontology scaffold-system``."""

from __future__ import annotations

import json
from pathlib import Path

import click

from .shared import _autodetect_analysis_dir, resolve_refmodels_dir


def _render_scaffold_system_text(result, *, limit: int) -> None:
    verb = "Would scaffold" if result.dry_run else "Scaffolded"
    suffix = " (dry-run -- nothing was written)" if result.dry_run else ""
    click.echo(f"kairos-ontology scaffold-system — {result.system}{suffix}")
    click.echo(
        f"{verb} {len(result.scaffolded)} table(s); declined {len(result.declined)} table(s)."
    )

    if result.scaffolded:
        click.echo("")
        click.echo(f"{verb}:")
        for item in result.scaffolded:
            click.echo(f"  - {item.table} -> {item.domain}   target: {item.target_class}")
            click.echo(f"      binding: {item.binding_path}")
            if item.orphan_columns:
                click.echo(
                    f"      ⚠ orphan columns ({len(item.orphan_columns)}): "
                    f"{', '.join(item.orphan_columns)}"
                )
            for diag in item.compile_diagnostics:
                click.echo(
                    f"      ⚠ [{diag.severity}] {diag.code}: {diag.message} ({diag.pointer})"
                )

    if result.declined:
        click.echo("")
        click.echo("Declined:")
        by_reason: dict[str, list] = {}
        for item in result.declined:
            by_reason.setdefault(item.reason, []).append(item)
        for reason in sorted(by_reason):
            items = by_reason[reason]
            click.echo(f"  {reason} ({len(items)}):")
            shown = items if limit <= 0 else items[:limit]
            for item in shown:
                click.echo(f"    - {item.table}: {item.detail}")
            omitted = len(items) - len(shown)
            if omitted > 0:
                click.echo(
                    f"    ... {omitted} more {reason} table(s) omitted for readability "
                    "(pass --format json for the full list, or raise --limit)."
                )

    if result.domains_compiled:
        click.echo("")
        click.echo(f"Compiled domain(s): {', '.join(result.domains_compiled)}")

    for note in result.notes:
        click.echo(f"NOTE: {note}")


@click.command(name="scaffold-system")
@click.option("--system", required=True, help="Source system id (integration/sources/<system>/).")
@click.option(
    "--accelerator", default=None, help="Accelerator pack (default: resolved from hub config)."
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Compute and report what would be scaffolded across the whole system without writing "
    "any file.",
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
    "--format",
    "out_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (default: text).",
)
@click.option(
    "--limit",
    default=20,
    show_default=True,
    help="Max declined-table rows printed per reason in text mode (0 = unlimited; --format json "
    "is always complete).",
)
def scaffold_system_cmd(
    system, accelerator, dry_run, ref_models_dir_opt, catalog, out_format, limit
):
    """Scaffold every good ``passthrough`` candidate under one source system in one pass.

    Composes ``list-unscaffolded`` table discovery, ``propose-alignment`` evidence (its
    ``ref_class``, re-resolved to a full accelerator class URI), the ``passthrough``
    ``scaffold-binding`` archetype, and ``compile --check`` into one review report: which
    tables were scaffolded, which were declined and why (already covered, no alignment
    evidence, an ambiguous/unresolvable class, or judged non-mechanical), and any compile
    diagnostics for each scaffolded binding. Never invents a ``--target-class`` guess -- a
    table with no usable ``propose-alignment`` evidence is declined, not scaffolded.

    \b
    Examples:
      kairos-ontology scaffold-system --system crm
      kairos-ontology scaffold-system --system crm --dry-run
      kairos-ontology scaffold-system --system crm --format json
    """
    from ..core.hub_utils import find_hub_root
    from ..core.scaffold_system import ScaffoldSystemError, run_scaffold_system

    hub_root = find_hub_root(Path.cwd(), require_model=True)
    if hub_root is None:
        raise click.ClickException(
            "Cannot locate a hub (model/ + integration/) from the current directory."
        )

    cwd = Path.cwd()
    ref_models_dir = (
        Path(ref_models_dir_opt) if ref_models_dir_opt else resolve_refmodels_dir(cwd, hub_root)
    )
    catalog_path = Path(catalog) if catalog else None
    if catalog_path is None:
        candidate = hub_root / "catalog-v001.xml"
        catalog_path = candidate if candidate.is_file() else None
    analysis_dir = _autodetect_analysis_dir(cwd, hub_root)

    try:
        result = run_scaffold_system(
            hub_root,
            system=system,
            accelerator=accelerator,
            ref_models_dir=ref_models_dir,
            catalog_path=catalog_path,
            analysis_dir=analysis_dir,
            dry_run=dry_run,
        )
    except ScaffoldSystemError as exc:
        raise click.ClickException(str(exc)) from exc

    if out_format == "json":
        click.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True))
        return
    _render_scaffold_system_text(result, limit=limit)
