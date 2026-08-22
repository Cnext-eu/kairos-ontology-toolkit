# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Modeling-feedback CLI commands (OKF-style, lighter-weight sibling of the Decision Log)."""

from __future__ import annotations

import os
import secrets
from datetime import date
from pathlib import Path

import click

from .. import __version__ as _toolkit_version
from ..core.decision_records import rfc3339_now
from ..core.feedback_records import (
    VALID_STATUS,
    FeedbackDiagnostic,
    FeedbackValidationResult,
    build_index_markdown,
    generate_feedback_id,
    render_new_record,
    resolve_record,
    validate_feedback_bundle,
)
from ..core.hub_utils import find_hub_root
from .shared import _resolve_import_dir

_MAX_ID_ATTEMPTS = 8


def _feedback_dir(cwd: Path | None = None) -> tuple[Path, Path | None]:
    """Resolve and create the current hub's modeling-feedback bundle directory.

    Returns ``(feedback_path, hub_root)``. Feedback records live under
    ``.import/businessdiscovery/insights/`` -- a repo-root sibling of
    ``ontology-hub/``, not inside it -- so *hub_root* (used only for resolving
    local ``sources[].resource`` citations) is returned separately rather than
    derived from *feedback_path* itself; it may be ``None`` for a bare
    ``.import/`` tree with no ``ontology-hub/`` sibling yet.
    """
    if cwd is None:
        cwd = Path.cwd()
    hub_root = find_hub_root(cwd, require_model=False)
    import_dir = _resolve_import_dir(cwd, hub_root)
    feedback_path = import_dir / "insights"
    feedback_path.mkdir(parents=True, exist_ok=True)
    return feedback_path, hub_root


def _write_index(feedback_path: Path, hub_root: Path | None) -> FeedbackValidationResult:
    """Atomically regenerate ``index.md`` for *feedback_path*."""
    result = validate_feedback_bundle(feedback_path, hub_root=hub_root)
    index_text = build_index_markdown(result.records)
    temp_path = feedback_path / f".index.{secrets.token_hex(6)}.tmp"
    try:
        temp_path.write_text(index_text, encoding="utf-8")
        os.replace(temp_path, feedback_path / "index.md")
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return result


def _echo_diagnostics(
    diagnostics: list[FeedbackDiagnostic],
    *,
    only_file: str | None = None,
) -> None:
    for diag in diagnostics:
        if only_file is not None and diag.file != only_file:
            continue
        marker = "✗" if diag.level == "error" else "⚠"
        click.echo(f"   {marker} {diag.file}: {diag.message}")


def _new_record_id(explicit_id: str | None) -> str:
    if explicit_id is not None:
        return explicit_id
    return generate_feedback_id(date.today(), secrets.token_hex(3))


@click.group()
def feedback() -> None:
    """Create and inspect hub modeling-feedback knowledge-snippet records."""


@feedback.command(name="new")
@click.option("--title", required=True, help="Feedback record title.")
@click.option("--area", help="Free-text modeling area (e.g. 'party').")
@click.option("--observation", required=True, help="What was observed.")
@click.option("--implication", help="Optional design implication.")
@click.option(
    "--source",
    multiple=True,
    help=(
        "Evidence resource string; may be repeated. Local paths resolve from the "
        "hub root; on nested hubs, .import/... evidence also resolves from the "
        "repo root."
    ),
)
@click.option("--id", "record_id", help="Explicit feedback record id.")
def new_feedback(
    title: str,
    area: str | None,
    observation: str,
    implication: str | None,
    source: tuple[str, ...],
    record_id: str | None,
) -> None:
    """Create a new modeling-feedback record and refresh the index."""
    feedback_path, hub_root = _feedback_dir()
    attempts = 1 if record_id is not None else _MAX_ID_ATTEMPTS

    for _ in range(attempts):
        candidate_id = _new_record_id(record_id)
        target = feedback_path / f"{candidate_id}.md"
        try:
            with target.open("x", encoding="utf-8") as handle:
                handle.write(
                    render_new_record(
                        record_id=candidate_id,
                        title=title,
                        version=_toolkit_version,
                        area=area,
                        observation=observation,
                        implication=implication,
                        sources=list(source),
                    )
                )
        except FileExistsError:
            if record_id is not None:
                raise click.ClickException(f"Feedback record already exists: {target}") from None
            continue

        result = _write_index(feedback_path, hub_root)
        click.echo(str(target))
        _echo_diagnostics(result.diagnostics, only_file=target.name)
        return

    raise click.ClickException(f"Could not allocate a unique feedback id after {attempts} attempts")


@feedback.command(name="resolve")
@click.argument("record_id")
@click.option("--note", required=True, help="Resolution note.")
def resolve_feedback(record_id: str, note: str) -> None:
    """Mark a modeling-feedback record resolved and record the resolution note."""
    feedback_path, hub_root = _feedback_dir()
    target = feedback_path / f"{record_id}.md"
    if not target.is_file():
        raise click.ClickException(f"No feedback record found: {target}")

    text = target.read_text(encoding="utf-8")
    try:
        updated = resolve_record(text, note=note, resolved_at=rfc3339_now())
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    temp_path = feedback_path / f".{record_id}.{secrets.token_hex(6)}.tmp"
    try:
        temp_path.write_text(updated, encoding="utf-8")
        os.replace(temp_path, target)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    result = _write_index(feedback_path, hub_root)
    click.echo(str(target))
    _echo_diagnostics(result.diagnostics, only_file=target.name)


@feedback.command(name="sync-index")
def sync_index() -> None:
    """Regenerate ``index.md`` from the records currently on disk.

    Use this after hand-editing a feedback record's frontmatter so the static
    index stops disagreeing with the live records.
    """
    feedback_path, hub_root = _feedback_dir()
    result = _write_index(feedback_path, hub_root)
    click.echo(str(feedback_path / "index.md"))
    _echo_diagnostics(result.diagnostics)


@feedback.command(name="list")
@click.option("--status", type=click.Choice(sorted(VALID_STATUS)), help="Filter by status.")
def list_feedback(status: str | None) -> None:
    """List modeling-feedback records."""
    feedback_path, hub_root = _feedback_dir()
    result = validate_feedback_bundle(feedback_path, hub_root=hub_root)
    for record in result.records:
        if status is not None and record.status != status:
            continue
        click.echo(f"{record.id or record.path.stem}\t{record.status or ''}\t{record.title or ''}")
        _echo_diagnostics(result.diagnostics, only_file=record.path.name)
