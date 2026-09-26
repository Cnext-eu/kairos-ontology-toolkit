# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Stable structured log event helpers for the Kairos toolkit.

Centralizing event-name constants and the emit helper here keeps the event
catalogue drift-detectable in the same spirit as the compiler diagnostic code
catalogue: a single place to read what events the toolkit emits, and one shape
for every instrumented call site.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from time import perf_counter
from typing import Final, Iterator

from . import spans
from .context import CONSOLE_ATTR

logger = logging.getLogger("kairos_ontology.dbt")

#: The stable event-name catalogue for offline dbt validation (DD-151).
DBT_VALIDATION_STARTED: Final[str] = "kairos.dbt.validation.started"
DBT_PHASE_STARTED: Final[str] = "kairos.dbt.phase.started"
DBT_PHASE_COMPLETED: Final[str] = "kairos.dbt.phase.completed"
DBT_PHASE_FAILED: Final[str] = "kairos.dbt.phase.failed"
DBT_ENVIRONMENT_BLOCKED: Final[str] = "kairos.dbt.environment_blocked"

#: Stable event-name catalogue for optional projection integration calls (DD-151).
#: Mermaid CLI rendering is non-fatal by design — absence of the binary or a
#: render failure returns ``None`` and is logged, never raised. These events
#: let skills/operators observe whether a projection step actually rendered
#: an SVG or silently degraded to Markdown-only output.
PROJECTION_STEP_STARTED: Final[str] = "kairos.projection.step.started"
PROJECTION_STEP_COMPLETED: Final[str] = "kairos.projection.step.completed"
PROJECTION_STEP_SKIPPED: Final[str] = "kairos.projection.step.skipped"
PROJECTION_STEP_FAILED: Final[str] = "kairos.projection.step.failed"


#: Per-domain compile progress. A multi-domain `compile --all` reports each domain only
#: once it finishes, which on a large hub is minutes of apparent silence; these say which
#: domain is in flight and how long the last one took.
COMPILE_DOMAIN_STARTED: Final[str] = "kairos.compile.domain.started"
COMPILE_DOMAIN_COMPLETED: Final[str] = "kairos.compile.domain.completed"

#: One record per diagnostic a command reports, and one summary per run (#1011). Printed
#: diagnostics reached only the console, so once the terminal scrolled a run's findings
#: were gone; these put every one in the run log, attributed to its task and gate.
DIAGNOSTIC_REPORTED: Final[str] = "kairos.diagnostic.reported"
RUN_SUMMARY: Final[str] = "kairos.run.summary"

_diagnostic_logger = logging.getLogger("kairos_ontology.diagnostics")
_SEVERITY_LEVELS: Final[dict[str, int]] = {
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
}
#: ``(task, gate, severity, code)`` for every diagnostic logged in this invocation.
_run_diagnostics: list[tuple[str, str, str, str]] = []


def reset_run_diagnostics() -> None:
    """Forget the previous invocation's diagnostics; one process may run several."""
    _run_diagnostics.clear()


def log_diagnostic(
    diagnostic: object,
    *,
    command: str,
    domain: str | None = None,
    product: str | None = None,
    gate: str = "",
) -> None:
    """Record one diagnostic in the run log, whatever the console verbosity (#1011).

    *diagnostic* is anything with ``code``, ``message`` and ``severity`` (a
    ``CompileDiagnostic``, or a projection ``Diagnostic``); ``location`` and
    ``rule_id`` are carried when present. The task is the domain, or ``gold:<product>``.
    """
    severity = getattr(diagnostic, "severity", "error")
    severity = str(getattr(severity, "value", severity)).lower()
    location = getattr(diagnostic, "location", None)
    rendered = location.render() if hasattr(location, "render") else str(location or "")
    task = f"gold:{product}" if product else (domain or command)
    code = str(getattr(diagnostic, "code", ""))
    _run_diagnostics.append((task, gate, severity, code))
    rule_id = str(getattr(diagnostic, "rule_id", "") or "")
    span = spans.current_span()
    spans.count_diagnostic(severity)
    fields: dict[str, object] = {
        "event": DIAGNOSTIC_REPORTED,
        CONSOLE_ATTR: False,
        "kairos.command": command,
        "kairos.task": task,
        "kairos.gate": gate,
        "diagnostic.code": code,
        "diagnostic.severity": severity,
        "diagnostic.rule_id": rule_id,
        "diagnostic.location": rendered,
    }
    if span is not None:
        # Groups the record under its task: `logs show` and a trace backend both nest it.
        fields["kairos.span.id"] = span.span_id
    if domain:
        fields["kairos.domain"] = domain
    if product:
        fields["kairos.product"] = product
    # The message is the diagnostic's own one-line rendering, so a text-format log reads
    # like the console; the JSON form also carries each part as its own field.
    render = getattr(diagnostic, "render", None)
    message = (
        render()
        if callable(render)
        else f"[{severity}] {code}: {getattr(diagnostic, 'message', '')}"
    )
    fields["diagnostic.message"] = str(getattr(diagnostic, "message", ""))
    if span is not None and span.otel_span is not None:
        try:
            span.otel_span.add_event(
                "kairos.diagnostic",
                attributes={
                    "diagnostic.code": code,
                    "diagnostic.severity": severity,
                    "diagnostic.rule_id": rule_id,
                    "diagnostic.location": rendered,
                    "diagnostic.message": fields["diagnostic.message"],
                },
            )
        except Exception:  # pragma: no cover - telemetry must not break a run
            pass
    _diagnostic_logger.log(_SEVERITY_LEVELS.get(severity, logging.WARNING), message, extra=fields)


def run_summary() -> dict[str, dict[str, object]]:
    """Per task: diagnostic counts by severity and by code, in task order."""
    summary: dict[str, dict[str, object]] = {}
    for task, _gate, severity, code in _run_diagnostics:
        entry = summary.setdefault(task, {"severity": {}, "code": {}})
        entry["severity"][severity] = entry["severity"].get(severity, 0) + 1
        entry["code"][code] = entry["code"].get(code, 0) + 1
    return dict(sorted(summary.items()))


def log_run_summary(command: str, *, exit_code: int = 0) -> None:
    """Write the run's outcome and diagnostic summary to the run log.

    Written for every run, a clean one included: a refusal that carries no diagnostic
    (a Gold contract error, say) still has to say how the run ended (DD-242).
    """
    summary = run_summary()
    total = sum(sum(entry["severity"].values()) for entry in summary.values())
    outcome = "ok" if exit_code == 0 else "failed"
    _diagnostic_logger.info(
        f"{command} {outcome} (exit {exit_code}): "
        f"{total} diagnostic(s) across {len(summary)} task(s)",
        extra={
            "event": RUN_SUMMARY,
            CONSOLE_ATTR: False,
            "kairos.command": command,
            "kairos.outcome": outcome,
            "kairos.exit_code": exit_code,
            "kairos.summary": summary,
        },
    )


def render_run_summary() -> list[str]:
    """The summary as console lines, one per task, for a multi-task run."""
    lines = []
    for task, entry in run_summary().items():
        counts = ", ".join(
            f"{entry['severity'][name]} {name}"
            for name in ("error", "warning", "info")
            if entry["severity"].get(name)
        )
        top = sorted(entry["code"].items(), key=lambda item: (-item[1], item[0]))[:3]
        codes = ", ".join(f"{code} x{count}" for code, count in top)
        lines.append(f"  {task}: {counts}  ({codes})")
    return lines


def emit(event: str, level: int, message: str, **fields: object) -> None:
    """Emit one structured log record carrying a stable ``event`` name.

    ``fields`` become structured ``extra`` attributes on the ``LogRecord`` and
    are subject to redaction by :class:`RedactionFilter`.
    """
    logger.log(level, message, extra={"event": event, **fields})


@contextmanager
def timed_phase(
    phase: str,
    *,
    platform: str | None = None,
    project_dir: str | None = None,
) -> Iterator[logging.Logger]:
    """Time a dbt validation phase and emit started/completed/failed events.

    Yields the logger so the caller can log phase-specific debug detail. On a
    non-error return emits ``DBT_PHASE_COMPLETED``; on exception re-raises after
    emitting ``DBT_PHASE_FAILED`` with ``kairos.retryable`` derived from the
    failure classification.
    """
    fields: dict[str, object] = {"kairos.dbt.phase": phase}
    if platform is not None:
        fields["kairos.dbt.platform"] = platform
    if project_dir is not None:
        fields["kairos.dbt.project_dir"] = project_dir
    started = DBT_VALIDATION_STARTED if phase == "validation" else DBT_PHASE_STARTED
    emit(started, logging.INFO, f"dbt {phase} started", **fields)
    start = perf_counter()
    with spans.task_span("stage", f"dbt.{phase}"):
        yield from _timed_phase_body(phase, start, fields)


def _timed_phase_body(
    phase: str, start: float, fields: dict[str, object]
) -> Iterator[logging.Logger]:
    try:
        yield logger
    except Exception as exc:
        duration_ms = int((perf_counter() - start) * 1000)
        retryable = _is_retryable(exc)
        emit(
            DBT_PHASE_FAILED,
            logging.ERROR,
            f"dbt {phase} failed: {exc}",
            duration_ms=duration_ms,
            kairos_retryable=retryable,
            error_type=type(exc).__name__,
            **fields,
        )
        raise
    duration_ms = int((perf_counter() - start) * 1000)
    emit(
        DBT_PHASE_COMPLETED,
        logging.INFO,
        f"dbt {phase} completed",
        duration_ms=duration_ms,
        **fields,
    )


_RETRYABLE_PHASES: frozenset[str] = frozenset({"deps", "parse", "compile"})


def _is_retryable(exc: BaseException) -> bool:
    """Classify whether a dbt-validation failure is safe to retry.

    Only the transient/environmental failure classes (timeout) are retryable;
    genuine artifact failures (``DbtValidationError`` from a parse/manifest/
    contract problem) are not, because retrying produces identical output.
    """
    name = type(exc).__name__
    if name == "TimeoutExpired":
        return True
    # Environment-blocked outcomes surface as DbtValidationError("compile", ...)
    # carried in DbtValidationResult, not raised, so they never reach here.
    return False


__all__ = [
    "CONSOLE_ATTR",
    "DBT_ENVIRONMENT_BLOCKED",
    "DBT_PHASE_COMPLETED",
    "DBT_PHASE_FAILED",
    "DBT_PHASE_STARTED",
    "DBT_VALIDATION_STARTED",
    "PROJECTION_STEP_COMPLETED",
    "PROJECTION_STEP_FAILED",
    "PROJECTION_STEP_SKIPPED",
    "PROJECTION_STEP_STARTED",
    "emit",
    "timed_phase",
]
