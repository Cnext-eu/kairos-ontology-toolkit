# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Click surface for ``kairos-ontology scaffold-contract`` (DD-213)."""

from __future__ import annotations

from pathlib import Path

import click

from ..core.compiler.contract_scaffold import (
    ContractScaffoldError,
    build_contract_document,
    render_contract_yaml,
)
from ..core.compiler.kernel import build_compile_plan
from ..core.compiler.result import CompileError
from ..core.hub_utils import find_hub_root


@click.command(name="scaffold-contract")
@click.argument("domain")
@click.option(
    "--out",
    "out_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Destination file (default: model/contracts/<domain>.contract.yaml).",
)
@click.option("--force", is_flag=True, help="Overwrite an existing contract file.")
@click.option("--dry-run", is_flag=True, help="Print the contract instead of writing it.")
def scaffold_contract_cmd(domain: str, out_path: Path | None, force: bool, dry_run: bool) -> None:
    """Generate a declared Silver contract from the current compile plan.

    The generated document records what the compiler emits today, so adopting it is a
    no-op: the parity manifest must be unchanged. Edit it afterwards to record what Silver
    *promises* rather than what it currently contains.
    """
    hub = find_hub_root(Path.cwd(), require_model=True) or Path.cwd()
    try:
        plan = build_compile_plan(hub, domain)
    except CompileError as exc:
        for diagnostic in exc.diagnostics:
            click.echo(f"{diagnostic.code}: {diagnostic.message}", err=True)
        raise SystemExit(1) from exc

    if plan.blocked:
        click.echo(
            "compile is blocked for this domain; a contract must be scaffolded from a plan "
            "that compiles, or it would record a shape the compiler cannot emit",
            err=True,
        )
        raise SystemExit(1)

    try:
        document = build_contract_document(plan)
    except ContractScaffoldError as exc:
        click.echo(f"contract.scaffold: {exc}", err=True)
        raise SystemExit(1) from exc

    text = render_contract_yaml(document)
    if dry_run:
        click.echo(text)
        return

    destination = out_path or (hub / "model" / "contracts" / f"{domain}.contract.yaml")
    if out_path is None:
        # `domain` is user input and reaches a filesystem path here. `build_compile_plan`
        # above would already have failed on a traversing value (no matching ontology
        # resolves), but a write is worth containing explicitly rather than relying on an
        # upstream check staying in place.
        resolved = destination.resolve()
        contracts_root = (hub / "model" / "contracts").resolve()
        if not resolved.is_relative_to(contracts_root):
            click.echo(
                f"refusing to write outside {contracts_root}: domain '{domain}' resolves to "
                f"{resolved}",
                err=True,
            )
            raise SystemExit(1)
    if destination.exists() and not force:
        click.echo(f"{destination} already exists; pass --force to overwrite", err=True)
        raise SystemExit(1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
    entity_count = len(document["entities"])
    click.echo(f"Wrote {destination} ({entity_count} entities).")
