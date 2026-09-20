# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``kairos-ontology class-disposition`` -- the class-level disposition ledger (DD-231)."""

from __future__ import annotations

import json
from pathlib import Path

import click
import yaml


def _hub_root() -> Path:
    from ..core.hub_utils import find_hub_root

    hub_root = find_hub_root(Path.cwd(), require_model=False)
    if hub_root is None:
        raise click.ClickException(
            "Cannot locate an ontology hub. Run from the hub root (or inside ontology-hub/)."
        )
    return hub_root


def _disposition_choices() -> tuple[str, ...]:
    from ..core.class_disposition import DISPOSITIONS

    return tuple(sorted(DISPOSITIONS))


def _decider_choices() -> tuple[str, ...]:
    from ..core.class_disposition import DECIDED_BY

    return tuple(sorted(DECIDED_BY))


def _emit(payload: dict, output_format: str) -> None:
    if output_format == "json":
        click.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        click.echo(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))


@click.group(name="class-disposition")
def class_disposition_group() -> None:
    """Record why a hub class is deliberately not bound to Silver (DD-231).

    The ontology may run ahead of the sources: a class no EntityBinding targets never enters
    the CompilePlan, and that is correct. What was missing is somewhere to say "not bound
    yet, deliberately, because X" -- so a context engineer's logical model can live in the
    ontology as a superset of Silver without every unbound class looking forgotten.

    Until the hub creates the ledger, `validate` reports undecided classes as warnings.
    `init` (or the first `set`) creates it; from then on an undecided class is an error,
    degradable with `validate --degraded`.
    """


@class_disposition_group.command(name="init")
def class_disposition_init_cmd() -> None:
    """Create the ledger, turning undecided classes from warnings into errors."""
    from ..core.class_disposition import audit_class_dispositions, init_ledger

    hub_root = _hub_root()
    path, created = init_ledger(hub_root)
    click.echo(("✓ created " if created else "ℹ already present: ") + str(path))
    report = audit_class_dispositions(hub_root=hub_root)
    if report.undecided:
        click.echo(f"  {len(report.undecided)} class(es) now need a decision:")
        for item in report.undecided:
            click.echo(f"   ✗ {item.domain}: {item.local_name}  ({item.iri})")
    else:
        click.echo("  every hub class is bound or explicitly disposed")


@class_disposition_group.command(name="set")
@click.option(
    "--class",
    "class_iri",
    required=True,
    help="Class IRI or prefix:Local token, resolved against the hub's domain files.",
)
@click.option(
    "--disposition",
    required=True,
    type=click.Choice(_disposition_choices()),
    help="What the hub decided about this class.",
)
@click.option("--rationale", default="", help="Why. Required for deferred and architecture-only.")
@click.option(
    "--decided-by",
    type=click.Choice(_decider_choices()),
    default="user",
    show_default=True,
    help="Who made this call, so a reviewer can weight it.",
)
@click.option(
    "--evidence",
    multiple=True,
    help="Supporting evidence locator (a decision record, a design note, an issue). Repeatable.",
)
def class_disposition_set_cmd(
    class_iri: str,
    disposition: str,
    rationale: str,
    decided_by: str,
    evidence: tuple[str, ...],
) -> None:
    """Record one class's disposition in the hub ledger.

    \b
    Example:
      kairos-ontology class-disposition set --class party:PostalAddress \\
        --disposition architecture-only \\
        --rationale "Address is its own bounded context; physically it stays in party."
    """
    from ..core.class_disposition import ClassDispositionError, record_class_disposition

    hub_root = _hub_root()
    try:
        path = record_class_disposition(
            hub_root=hub_root,
            class_iri=class_iri,
            disposition=disposition,
            rationale=rationale,
            decided_by=decided_by,
            evidence=evidence,
        )
    except ClassDispositionError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✓ {class_iri} recorded as '{disposition}'")
    click.echo(f"  written to {path}")


@class_disposition_group.command(name="list")
@click.option(
    "--undecided",
    is_flag=True,
    default=False,
    help="Show only the classes that still need a decision.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json", "yaml"]),
    default="text",
    show_default=True,
    help="Text is the default: this surface exists for a human deciding what to do.",
)
def class_disposition_list_cmd(undecided: bool, output_format: str) -> None:
    """Show every hub class's decision state, and what is still undecided."""
    from ..core.class_disposition import ClassDispositionError, audit_class_dispositions

    hub_root = _hub_root()
    try:
        report = audit_class_dispositions(hub_root=hub_root)
    except ClassDispositionError as exc:
        raise click.ClickException(str(exc)) from exc
    if output_format in {"json", "yaml"}:
        payload = report.to_dict()
        if undecided:
            payload = {"undecided": payload["undecided"], "totals": payload["totals"]}
        _emit(payload, output_format)
        return
    if undecided:
        if not report.undecided:
            click.echo("✓ every hub class is bound or explicitly disposed")
            return
        click.echo(f"{len(report.undecided)} undecided class(es):")
        for item in report.undecided:
            click.echo(f"   ✗ {item.domain}: {item.local_name}  ({item.iri})")
        return
    ledger = "ledger present" if report.ledger_present else "no ledger yet (warnings only)"
    click.echo(
        f"🧾 Class dispositions — {report.coverage():.0%} decided "
        f"({report.classes_bound} bound, {report.classes_disposed} disposed, "
        f"{report.classes_undecided} undecided of {report.classes_total}); {ledger}"
    )
    for iri, status in sorted(report.statuses.items()):
        click.echo(f"   {status:<20} {iri}")
    for item in report.diagnostics:
        marker = "✗" if item.level == "error" else "⚠"
        click.echo(f"   {marker} {item.message}")
    for notice in report.notices:
        click.echo(f"   ℹ {notice}")


@class_disposition_group.command(name="clear")
@click.option(
    "--class",
    "classes",
    multiple=True,
    help="Class IRI or prefix:Local token to withdraw. Repeatable; omit to filter by other options.",
)
@click.option("--disposition", default=None, help="Withdraw only entries with this disposition.")
@click.option(
    "--decided-by",
    default=None,
    help="Withdraw only entries recorded by this decider (e.g. every 'ai' blanket answer).",
)
@click.option("--dry-run", is_flag=True, default=False, help="Report what would be removed.")
def class_disposition_clear_cmd(
    classes: tuple[str, ...],
    disposition: str | None,
    decided_by: str | None,
    dry_run: bool,
) -> None:
    """Withdraw recorded dispositions -- as auditable as recording them."""
    from ..core.class_disposition import ClassDispositionError, clear_class_dispositions

    if not classes and disposition is None and decided_by is None:
        raise click.ClickException("Give at least one of --class, --disposition, --decided-by.")
    hub_root = _hub_root()
    try:
        outcome = clear_class_dispositions(
            hub_root,
            classes=set(classes) or None,
            disposition=disposition,
            decided_by=decided_by,
            dry_run=dry_run,
        )
    except ClassDispositionError as exc:
        raise click.ClickException(str(exc)) from exc
    verb = "would remove" if dry_run else "removed"
    click.echo(f"✓ {verb} {outcome['removed']} entr(y/ies), {outcome['kept']} kept")
    for iri in outcome["classes"]:
        click.echo(f"   - {iri}")
