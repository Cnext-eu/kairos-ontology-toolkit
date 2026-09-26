# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``kairos-ontology logs``: read a run log back in human form (#1011, DD-242).

A writing command keeps a JSON-lines run log under ``<repo>/.kairos/logs/`` (#1038), and any
command writes one with ``--log-file <path> --log-format json``. This reads one back as
the span tree of the run (command, domain or product, gate, stage, with durations) and
its diagnostics grouped by task, code or severity. It reads only: nothing is written.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import click

from ..core.observability.events import DIAGNOSTIC_REPORTED, RUN_SUMMARY
from ..core.observability.spans import SPAN_COMPLETED

_SEVERITIES = ("error", "warning", "info")


@click.group(name="logs")
def logs_group() -> None:
    """Read the run logs that writing commands keep in <repo>/.kairos/logs/."""


def _latest_log() -> Path:
    from .run_log import ENV_RUN_LOG, newest_run_log, run_log_directories

    directories = run_log_directories(Path.cwd())
    if not directories:
        raise click.ClickException(
            "Cannot locate a hub from the current directory; pass the run log's PATH."
        )
    latest = newest_run_log(Path.cwd())
    if latest is None:
        raise click.ClickException(
            f"No run logs in {directories[0]}. A run log is kept by compile --emit, "
            "emit-gold, package-powerbi-release and project (unless "
            f"{ENV_RUN_LOG}=0); any command writes one with --log-file <path> "
            "--log-format json."
        )
    return latest


def _read(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    if not records:
        raise click.ClickException(
            f"{path} holds no JSON log records; write it with --log-format json."
        )
    return records


def _diagnostic(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": record.get("kairos.task", ""),
        "gate": record.get("kairos.gate", ""),
        "span_id": record.get("kairos.span.id", ""),
        "code": record.get("diagnostic.code", ""),
        "severity": record.get("diagnostic.severity", ""),
        "rule_id": record.get("diagnostic.rule_id", ""),
        "location": record.get("diagnostic.location", ""),
        "message": record.get("diagnostic.message", ""),
    }


def _span(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("span.id", ""),
        "parent_id": record.get("span.parent_id", ""),
        "kind": record.get("span.kind", ""),
        "name": record.get("span.name", ""),
        "status": record.get("span.status", ""),
        "duration_ms": record.get("duration_ms", 0),
        "diagnostics": record.get("span.diagnostics", {}) or {},
    }


def _load(path: Path) -> dict[str, Any]:
    records = _read(path)
    summary = next((r for r in reversed(records) if r.get("event") == RUN_SUMMARY), {})
    return {
        "path": str(path),
        "command": summary.get("kairos.command", ""),
        "outcome": summary.get("kairos.outcome", ""),
        "exit_code": summary.get("kairos.exit_code"),
        "operation_id": next(
            (r["kairos.operation.id"] for r in records if r.get("kairos.operation.id")), ""
        ),
        "started": records[0].get("timestamp", ""),
        "finished": records[-1].get("timestamp", ""),
        "spans": [_span(r) for r in records if r.get("event") == SPAN_COMPLETED],
        "diagnostics": [_diagnostic(r) for r in records if r.get("event") == DIAGNOSTIC_REPORTED],
    }


def _counts(diagnostics: list[dict[str, Any]]) -> str:
    tally = Counter(item["severity"] for item in diagnostics)
    parts = [f"{tally[name]} {name}" for name in _SEVERITIES if tally.get(name)]
    parts += [f"{count} {name}" for name, count in sorted(tally.items()) if name not in _SEVERITIES]
    return ", ".join(parts) or "no diagnostics"


def _line(item: dict[str, Any]) -> str:
    location = f" ({item['location']})" if item["location"] else ""
    return f"[{item['severity']}] {item['code']}: {item['message']}{location}"


def _groups(run: dict[str, Any], group_by: str) -> dict[str, list[dict[str, Any]]]:
    key = {"task": "task", "code": "code", "severity": "severity"}[group_by]
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in run["diagnostics"]:
        groups.setdefault(item[key] or "(none)", []).append(item)
    if group_by == "severity":
        order = {name: index for index, name in enumerate(_SEVERITIES)}
        return dict(sorted(groups.items(), key=lambda entry: order.get(entry[0], len(order))))
    if group_by == "code":
        return dict(sorted(groups.items(), key=lambda entry: (-len(entry[1]), entry[0])))
    return dict(sorted(groups.items()))


def _render_tree(run: dict[str, Any]) -> list[str]:
    """The span tree, each span followed by the diagnostics logged directly in it."""
    spans = run["spans"]
    known = {span["id"] for span in spans}
    children: dict[str, list[dict[str, Any]]] = {}
    for span in spans:
        # Children finish before their parent, so file order is start order per level.
        parent = span["parent_id"] if span["parent_id"] in known else ""
        children.setdefault(parent, []).append(span)
    own: dict[str, list[dict[str, Any]]] = {}
    for item in run["diagnostics"]:
        own.setdefault(item["span_id"] if item["span_id"] in known else "", []).append(item)
    lines: list[str] = []

    def walk(parent: str, depth: int) -> None:
        for span in children.get(parent, []):
            counts = ", ".join(
                f"{count} {name}" for name, count in sorted(span["diagnostics"].items())
            )
            lines.append(
                f"{'  ' * depth}{span['kind']} {span['name']}: {span['status']}, "
                f"{span['duration_ms']} ms" + (f" ({counts})" if counts else "")
            )
            for item in own.get(span["id"], []):
                lines.append(f"{'  ' * (depth + 1)}{_line(item)}")
            walk(span["id"], depth + 1)

    walk("", 1)
    stray = own.get("", [])
    if stray:
        # A log written before spans existed, or a record logged outside every span.
        lines.append("  (not in a span)")
        for item in stray:
            lines.append(f"    {item['task']}/{item['gate']} {_line(item)}")
    return lines


@logs_group.command(name="show")
@click.argument(
    "path", required=False, type=click.Path(path_type=Path, dir_okay=False, exists=True)
)
@click.option(
    "--last",
    is_flag=True,
    default=False,
    help="Show the newest run log of this hub (the default when no PATH is given).",
)
@click.option(
    "--group-by",
    "group_by",
    type=click.Choice(["task", "code", "severity"], case_sensitive=False),
    default="task",
    show_default=True,
    help="task: the span tree with each diagnostic under the task that reported it. "
    "code / severity: diagnostics grouped by that field, with counts.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
)
def logs_show_cmd(path: Path | None, last: bool, group_by: str, output_format: str) -> None:
    """Show one run log: how the run ended, its tasks and durations, and its diagnostics.

    Reads PATH, or with no PATH (or --last) the newest log in <repo>/.kairos/logs/, or in
    <hub>/.kairos/logs/ where older toolkits kept them. Works on any JSON-lines log,
    including one written with --log-file and --log-format json.

    \b
    Examples:
      kairos-ontology logs show
      kairos-ontology logs show --group-by code
      kairos-ontology logs show run.jsonl --format json
    """
    if path is not None and last:
        raise click.UsageError("Pass a PATH or --last, not both.")
    run = _load(path if path is not None else _latest_log())
    group_by = group_by.lower()
    groups = _groups(run, group_by)
    if output_format.lower() == "json":
        click.echo(json.dumps({**run, "group_by": group_by, "groups": groups}, indent=2))
        return

    exit_code = run["exit_code"]
    outcome = run["outcome"] or "unknown (no run summary; the run may not have finished)"
    click.echo(f"Run log: {run['path']}")
    click.echo(
        f"  {run['command'] or '?'}: {outcome}"
        + (f" (exit {exit_code})" if exit_code is not None else "")
    )
    click.echo(f"  operation: {run['operation_id'] or '?'}")
    click.echo(f"  {run['started']} .. {run['finished']}")
    click.echo(f"  diagnostics: {len(run['diagnostics'])} ({_counts(run['diagnostics'])})")
    if group_by == "task":
        click.echo("Tasks:")
        if run["spans"]:
            for line in _render_tree(run):
                click.echo(line)
            return
        # A log from before spans existed: fall back to the task field.
        for task, items in groups.items():
            click.echo(f"  {task}: {_counts(items)}")
            for item in items:
                click.echo(f"    {item['gate']} {_line(item)}")
        return
    click.echo(f"By {group_by}:")
    for key, items in groups.items():
        click.echo(f"  {key}: {len(items)}")
        for item in items:
            where = f"{item['task']}/{item['gate']}" if item["gate"] else item["task"]
            click.echo(f"    {where} {_line(item)}")
