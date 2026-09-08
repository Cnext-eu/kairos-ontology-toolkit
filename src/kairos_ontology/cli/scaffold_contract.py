# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Click surface for ``kairos-ontology scaffold-contract`` (DD-213)."""

from __future__ import annotations

import re
from pathlib import Path

import click

from ..core.compiler.contract_scaffold import (
    ContractScaffoldError,
    build_contract_document,
    render_contract_yaml,
)
from ..core.compiler.kernel import build_compile_plan
from ..core.compiler.plan import CompilePlan
from ..core.compiler.result import CompileError, DiagnosticSeverity
from ..core.hub_utils import find_hub_root

#: The one Gate A error the scaffolder may proceed through (#750). It says "this class has
#: no contract entry yet", and the contract entry is precisely what this command produces;
#: refusing on it locked authors out of the tool built to unblock them. The shaped project
#: is intact behind it -- the kernel runs Gate A *after* shaping -- so the emitted block
#: still records what the compiler would emit.
_CLASS_NOT_DECLARED = "contract.class-not-declared"
_CLASS_TOKEN = re.compile(r"class '([^']+)' is not declared")


def _undeclared_classes(plan: CompilePlan) -> list[str] | None:
    """Return the undeclared class tokens when that is the *only* blocking error.

    ``None`` means the plan is blocked by something else as well (or has no shaped
    project), and the caller must keep refusing.
    """
    error_codes = {
        item.code
        for item in plan.diagnostics.items
        if item.severity is DiagnosticSeverity.ERROR
    }
    if error_codes != {_CLASS_NOT_DECLARED} or plan.shaped_project is None:
        return None
    tokens: set[str] = set()
    for item in plan.diagnostics.items:
        if item.code != _CLASS_NOT_DECLARED:
            continue
        match = _CLASS_TOKEN.search(item.message)
        if match:
            tokens.add(match.group(1))
    return sorted(tokens)


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
@click.option(
    "--entity",
    "entities",
    multiple=True,
    metavar="CLASS",
    help="Only scaffold this target class (authored token such as party:Customer, or the "
    "resolved IRI). Repeatable. With --dry-run this prints just the block(s) to paste "
    "into an existing contract.",
)
def scaffold_contract_cmd(
    domain: str,
    out_path: Path | None,
    force: bool,
    dry_run: bool,
    entities: tuple[str, ...],
) -> None:
    """Generate a declared Silver contract from the current compile plan.

    The generated document records what the compiler emits today, so adopting it is a
    no-op: the parity manifest must be unchanged. Edit it afterwards to record what Silver
    *promises* rather than what it currently contains.

    A compile blocked *only* by ``contract.class-not-declared`` does not refuse: that
    diagnostic means the contract lacks an entry for a class, and this command is how that
    entry is produced. Pair it with ``--entity <class> --dry-run`` to get the block to add.
    """
    hub = find_hub_root(Path.cwd(), require_model=True) or Path.cwd()
    try:
        plan = build_compile_plan(hub, domain)
    except CompileError as exc:
        for diagnostic in exc.diagnostics:
            click.echo(f"{diagnostic.code}: {diagnostic.message}", err=True)
        raise SystemExit(1) from exc

    if plan.blocked:
        undeclared = _undeclared_classes(plan)
        if undeclared is None:
            click.echo(
                "compile is blocked for this domain; a contract must be scaffolded from a "
                "plan that compiles, or it would record a shape the compiler cannot emit",
                err=True,
            )
            raise SystemExit(1)
        click.echo(
            f"compile is blocked only by {_CLASS_NOT_DECLARED} for: "
            f"{', '.join(undeclared) or '(unknown)'}; scaffolding the contract from the "
            "shaped plan so those classes can be declared",
            err=True,
        )

    try:
        document = build_contract_document(plan, only_classes=entities or None)
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
