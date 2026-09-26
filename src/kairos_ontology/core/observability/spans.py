# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Per-task spans for one command run (#1011, DD-242).

A run is a tree: the command, then a domain compile or a Gold product, then the gates
that judge it, then the stage that writes. Each node is a span. When it ends it writes one
``kairos.span.completed`` record, with its parent, duration, status and the diagnostics
logged inside it. The run log therefore has the hierarchy and the timings without any
tracing SDK installed.

When the OpenTelemetry export is on (:mod:`.otel`), each span is also an OTel span on the
run's tracer, and uses that span's id so the log and the trace agree. Nothing here
imports OpenTelemetry unless a tracer was installed: the helper keeps its own stack in a
ContextVar rather than asking the OTel context for the current span.

Spans are telemetry only. They never raise into the command and never change an exit
code or an artifact.
"""

from __future__ import annotations

import contextvars
import logging
import secrets
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Final, Iterator

from .context import CONSOLE_ATTR

#: One record per finished span.
SPAN_COMPLETED: Final[str] = "kairos.span.completed"

#: The kinds of task a span can stand for, outermost first.
SPAN_KINDS: Final[tuple[str, ...]] = ("run", "domain", "product", "gate", "stage")

#: ``ok`` ran to the end; ``refused`` a gate said no; ``error`` it failed or raised.
STATUSES: Final[tuple[str, ...]] = ("ok", "refused", "error")

logger = logging.getLogger("kairos_ontology.spans")


@dataclass(slots=True)
class Span:
    """One task in flight. Only this module creates them."""

    kind: str
    name: str
    span_id: str
    parent_id: str | None
    attributes: dict[str, Any]
    started: float
    status: str = "ok"
    #: Diagnostics logged inside this span or any span under it, by severity.
    diagnostics: dict[str, int] = field(default_factory=dict)
    otel_span: Any = None
    otel_token: Any = None

    def set_status(self, status: str) -> None:
        """Record the outcome. A worse status is never overwritten by a better one."""
        if STATUSES.index(status) > STATUSES.index(self.status):
            self.status = status


_stack: contextvars.ContextVar[tuple[Span, ...]] = contextvars.ContextVar(
    "kairos_span_stack", default=()
)
#: The OTel tracer of the current run, or None when the export is off.
_tracer: Any = None
#: The run span, which opens and closes in different Click callbacks.
_run: tuple[Span, contextvars.Token] | None = None


def set_tracer(tracer: Any) -> None:
    """Install (or, with None, remove) the OTel tracer later spans also report to."""
    global _tracer
    _tracer = tracer


def current_span() -> Span | None:
    """The innermost open span, or None outside any."""
    stack = _stack.get()
    return stack[-1] if stack else None


def mark_refused() -> None:
    """Mark the open tasks as refused: a gate judged the input and said no.

    The gate span and the domain or product it guards are refused together; the run
    span is left to the exit code.
    """
    for span in _stack.get():
        if span.kind != "run":
            span.set_status("refused")


def mark_error() -> None:
    """Mark the innermost span as failed without raising out of it."""
    span = current_span()
    if span is not None:
        span.set_status("error")


def count_diagnostic(severity: str) -> None:
    """Count one diagnostic against every open span, so each holds its subtree's total."""
    for span in _stack.get():
        span.diagnostics[severity] = span.diagnostics.get(severity, 0) + 1


def _primitive(value: Any) -> Any:
    """An OTel attribute value: a bool, int, float or str."""
    return value if isinstance(value, (bool, int, float, str)) else str(value)


def _start(kind: str, name: str, attributes: dict[str, Any]) -> Span:
    parent = current_span()
    span = Span(
        kind=kind,
        name=name,
        span_id=secrets.token_hex(8),
        parent_id=parent.span_id if parent is not None else None,
        attributes=attributes,
        started=perf_counter(),
    )
    if _tracer is not None:
        try:
            from opentelemetry import context as otel_context
            from opentelemetry import trace

            otel_span = _tracer.start_span(
                f"kairos.{kind}",
                attributes={
                    "kairos.span.kind": kind,
                    "kairos.span.name": name,
                    **{key: _primitive(value) for key, value in attributes.items()},
                },
            )
            span.otel_span = otel_span
            span.otel_token = otel_context.attach(trace.set_span_in_context(otel_span))
            span.span_id = format(otel_span.get_span_context().span_id, "016x")
        except Exception as exc:  # pragma: no cover - telemetry must not break a run
            logger.debug("OpenTelemetry span not started: %s", exc)
    return span


def _finish(span: Span) -> None:
    duration_ms = int((perf_counter() - span.started) * 1000)
    fields: dict[str, Any] = {
        "event": SPAN_COMPLETED,
        CONSOLE_ATTR: False,
        "span.id": span.span_id,
        "span.parent_id": span.parent_id or "",
        "span.kind": span.kind,
        "span.name": span.name,
        "span.status": span.status,
        "duration_ms": duration_ms,
        "span.diagnostics": dict(sorted(span.diagnostics.items())),
    }
    for key, value in span.attributes.items():
        fields.setdefault(key, value)
    # Written while the OTel span is still current, so an exported record carries it.
    logger.info(f"{span.kind} {span.name} {span.status} in {duration_ms} ms", extra=fields)
    if span.otel_span is None:
        return
    try:
        from opentelemetry import context as otel_context
        from opentelemetry.trace import Status, StatusCode

        for severity, count in span.diagnostics.items():
            span.otel_span.set_attribute(f"kairos.diagnostics.{severity}", count)
        span.otel_span.set_attribute("kairos.span.status", span.status)
        if span.status != "ok":
            span.otel_span.set_status(Status(StatusCode.ERROR, span.status))
        span.otel_span.end()
        otel_context.detach(span.otel_token)
    except Exception as exc:  # pragma: no cover - telemetry must not break a run
        logger.debug("OpenTelemetry span not ended: %s", exc)


@contextmanager
def task_span(kind: str, name: str, **attributes: Any) -> Iterator[Span]:
    """Run the body as one task of the current run.

    An exception marks the span ``error`` and propagates unchanged, unless the span was
    already refused: a gate that says no and then raises to stop the command is a
    refusal, not a crash.
    """
    span = _start(kind, name, attributes)
    token = _stack.set(_stack.get() + (span,))
    try:
        yield span
    except BaseException:
        if span.status == "ok":
            span.set_status("error")
        raise
    finally:
        _stack.reset(token)
        _finish(span)


def open_run_span(command: str, **attributes: Any) -> None:
    """Open the root span of this invocation; :func:`close_run_span` ends it."""
    global _run
    close_run_span(exit_code=0)
    span = _start("run", command or "kairos-ontology", attributes)
    _run = (span, _stack.set((span,)))


def close_run_span(*, exit_code: int) -> None:
    """End the root span, marking it ``error`` for a non-zero exit. Safe to call twice."""
    global _run
    if _run is None:
        return
    span, token = _run
    _run = None
    if exit_code:
        span.set_status("error")
    span.attributes["kairos.exit_code"] = exit_code
    if span.otel_span is not None:
        try:
            span.otel_span.set_attribute("kairos.exit_code", exit_code)
        except Exception:  # pragma: no cover - telemetry must not break a run
            pass
    try:
        _stack.reset(token)
    except ValueError:
        # Reset from another context (an embedder switching threads): just clear it.
        _stack.set(())
    _finish(span)


def reset_spans() -> None:
    """Forget every open span and the tracer; for tests and a fresh invocation."""
    global _run
    _run = None
    _stack.set(())
    set_tracer(None)


__all__ = [
    "SPAN_COMPLETED",
    "SPAN_KINDS",
    "Span",
    "close_run_span",
    "count_diagnostic",
    "current_span",
    "mark_error",
    "mark_refused",
    "open_run_span",
    "reset_spans",
    "set_tracer",
    "task_span",
]
