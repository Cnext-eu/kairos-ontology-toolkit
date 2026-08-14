# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Decision Log CLI commands."""

from __future__ import annotations

import os
import secrets
from datetime import date
from pathlib import Path

import click

from .. import __version__ as _toolkit_version
from ..core.decision_records import (
    VALID_DECISION_STATES,
    VALID_MATERIALITY,
    DecisionDiagnostic,
    DecisionValidationResult,
    build_index_markdown,
    generate_decision_id,
    render_new_record,
    validate_decision_bundle,
)
from ..core.hub_utils import find_hub_root

_MAX_ID_ATTEMPTS = 8


def _decisions_dir(cwd: Path | None = None) -> Path:
    """Resolve and create the current hub's decision bundle directory."""
    if cwd is None:
        cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)
    if hub_root is None:
        hub_root = cwd / "ontology-hub"
    decisions_path = hub_root / "decisions"
    decisions_path.mkdir(parents=True, exist_ok=True)
    return decisions_path


def _write_index(decisions_path: Path) -> DecisionValidationResult:
    """Atomically regenerate ``index.md`` for *decisions_path*.

    Returns the full validation result (not just the ``records`` used to
    render the index) so callers can surface the diagnostics that
    ``validate_decision_bundle`` already computes instead of discarding them
    (D5, #416c) -- e.g. ``no_sources``, ``missing_materiality``.
    """
    result = validate_decision_bundle(decisions_path)
    index_text = build_index_markdown(result.records)
    temp_path = decisions_path / f".index.{secrets.token_hex(6)}.tmp"
    try:
        temp_path.write_text(index_text, encoding="utf-8")
        os.replace(temp_path, decisions_path / "index.md")
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return result


def _echo_diagnostics(
    diagnostics: list[DecisionDiagnostic],
    *,
    only_file: str | None = None,
) -> None:
    """Print validator diagnostics that were previously silently discarded (D5, #416c)."""
    for diag in diagnostics:
        if only_file is not None and diag.file != only_file:
            continue
        marker = "✗" if diag.level == "error" else "⚠"
        click.echo(f"   {marker} {diag.file}: {diag.message}")


def _new_record_id(explicit_id: str | None) -> str:
    token = explicit_id if explicit_id is not None else secrets.token_hex(3)
    return token if explicit_id is not None else generate_decision_id(date.today(), token)


@click.group()
def decision() -> None:
    """Create and inspect hub OKF Decision Log records."""


@decision.command(name="new")
@click.option("--title", required=True, help="Decision record title.")
@click.option("--domain", help="Optional canonical domain for the decision.")
@click.option(
    "--decision-state",
    type=click.Choice(sorted(VALID_DECISION_STATES)),
    default="Proposed",
    show_default=True,
    help="Initial decision workflow state.",
)
@click.option("--source", multiple=True, help="Evidence resource string; may be repeated.")
@click.option(
    "--materiality",
    "materiality",
    multiple=True,
    type=click.Choice(sorted(VALID_MATERIALITY)),
    help=(
        "Structured materiality reason; may be repeated. Required when "
        "--decision-state is Accepted."
    ),
)
@click.option("--id", "record_id", help="Explicit decision record id.")
def new_decision(
    title: str,
    domain: str | None,
    decision_state: str,
    source: tuple[str, ...],
    materiality: tuple[str, ...],
    record_id: str | None,
) -> None:
    """Create a new Decision Log record and refresh the index."""
    if decision_state == "Accepted" and not materiality:
        raise click.ClickException(
            "--decision-state Accepted requires >=1 --materiality reason (the hub's "
            "decision-log validator rejects an Accepted record with none). Pass one or "
            "more of: " + ", ".join(sorted(VALID_MATERIALITY)) + ". If the materiality "
            "is not yet known, create the record with --decision-state Proposed instead "
            "and accept it once a reason is decided."
        )

    decisions_path = _decisions_dir()
    attempts = 1 if record_id is not None else _MAX_ID_ATTEMPTS

    for _ in range(attempts):
        candidate_id = _new_record_id(record_id)
        target = decisions_path / f"{candidate_id}.md"
        try:
            with target.open("x", encoding="utf-8") as handle:
                handle.write(
                    render_new_record(
                        record_id=candidate_id,
                        title=title,
                        version=_toolkit_version,
                        domain=domain,
                        decision_state=decision_state,
                        materiality=list(materiality),
                        sources=list(source),
                    )
                )
        except FileExistsError:
            if record_id is not None:
                raise click.ClickException(f"Decision record already exists: {target}") from None
            continue

        result = _write_index(decisions_path)
        click.echo(str(target))
        _echo_diagnostics(result.diagnostics, only_file=target.name)
        return

    raise click.ClickException(f"Could not allocate a unique decision id after {attempts} attempts")


@decision.command(name="sync-index")
def sync_index() -> None:
    """Regenerate ``index.md`` from the records currently on disk.

    Use this after hand-editing a decision record's frontmatter (e.g. flipping
    ``decision_state`` from ``Proposed`` to ``Accepted``) so the static index
    stops disagreeing with the live records.
    """
    decisions_path = _decisions_dir()
    result = _write_index(decisions_path)
    click.echo(str(decisions_path / "index.md"))
    _echo_diagnostics(result.diagnostics)


@decision.command(name="list")
def list_decisions() -> None:
    """List Decision Log records."""
    decisions_path = _decisions_dir()
    result = validate_decision_bundle(decisions_path)
    for record in result.records:
        click.echo(
            f"{record.id or record.path.stem}\t{record.decision_state or ''}\t{record.title or ''}"
        )
        _echo_diagnostics(result.diagnostics, only_file=record.path.name)
