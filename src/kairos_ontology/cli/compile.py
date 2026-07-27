# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Click surface for the stateless Kairos v5 compiler."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import click

from ..core.compiler import CompileMode, compile_domain


def _payload(result) -> dict:
    return {
        "domain": result.domain,
        "mode": result.mode,
        "succeeded": result.succeeded,
        "provenance_hash": result.provenance_hash,
        "diagnostics": [asdict(item) for item in result.diagnostics.ordered],
        "explain": asdict(result.explain) if result.explain is not None else None,
        "artifacts": [path for path, _ in result.artifacts],
    }


@click.command(name="compile")
@click.argument("domain")
@click.option("--check", "check_mode", is_flag=True, help="Validate without writing files.")
@click.option("--explain", "explain_mode", is_flag=True, help="Explain the normalized plan.")
@click.option(
    "--emit",
    "emit_dir",
    type=click.Path(path_type=Path, file_okay=False),
    help="Atomically emit generated artifacts below DIRECTORY.",
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
    emit_dir: Path | None,
    output_format: str,
) -> None:
    """Check, explain, or emit one v5 DOMAIN from the current hub."""
    selected = int(check_mode) + int(explain_mode) + int(emit_dir is not None)
    if selected != 1:
        raise click.UsageError("exactly one of --check, --explain, or --emit is required")
    mode = (
        CompileMode.CHECK
        if check_mode
        else CompileMode.EXPLAIN if explain_mode else CompileMode.EMIT
    )
    result = compile_domain(Path.cwd(), domain, mode)
    if emit_dir is not None and result.can_emit:
        from ..core.compiler.emit import emit_artifacts

        emit_artifacts(result.artifact_dict(), emit_dir, owned_subtree=domain)
    if output_format == "json":
        click.echo(json.dumps(_payload(result), indent=2, sort_keys=True))
    else:
        for diagnostic in result.diagnostics.ordered:
            click.echo(diagnostic.render(), err=not result.succeeded)
        if result.succeeded:
            if mode is CompileMode.CHECK:
                click.echo(f"✓ {domain}: compile check passed")
            elif mode is CompileMode.EXPLAIN:
                report = result.explain
                click.echo(f"✓ {domain}: {len(report.entities)} entity binding(s)")
                for entity in report.entities:
                    click.echo(
                        f"  {entity.name}: {entity.source} → {entity.target_class} "
                        f"[grain: {', '.join(entity.grain)}]"
                    )
                for path in report.artifact_paths:
                    click.echo(f"  {path}")
            else:
                click.echo(f"✓ {domain}: emitted {len(result.artifacts)} artifact(s) to {emit_dir}")
    if not result.succeeded:
        raise click.exceptions.Exit(1)
