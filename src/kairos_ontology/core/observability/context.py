# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Per-invocation operation context for log/trace correlation.

Every CLI invocation gets one stable ``operation_id`` (a UUID4 hex string) that
is attached to structured log records as ``kairos.operation.id`` so all events
emitted by one command — across compiler, projector, and offline dbt
validation — correlate. This is dependency-free: no tracing SDK is required for
plain logging; the OpenTelemetry bridge attaches the same id as a span
attribute when enabled.
"""

from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass
from typing import Final

#: Stable structured-log attribute carrying the per-invocation id.
OPERATION_ID_ATTR: Final[str] = "kairos.operation.id"


@dataclass(frozen=True, slots=True)
class OperationContext:
    """Per-invocation context propagated to log records via a context var."""

    operation_id: str


_current_context: contextvars.ContextVar[OperationContext | None] = contextvars.ContextVar(
    "kairos_operation_context", default=None
)


def new_operation_id() -> str:
    """Generate a fresh operation id (UUID4 hex)."""
    return uuid.uuid4().hex


def current_operation_id() -> str | None:
    """Return the active operation id, or ``None`` outside a CLI invocation."""
    ctx = _current_context.get()
    return ctx.operation_id if ctx is not None else None


def set_operation_context(ctx: OperationContext) -> contextvars.Token[OperationContext | None]:
    """Bind an operation context to the current logical context."""
    return _current_context.set(ctx)


def reset_operation_context(
    token: contextvars.Token[OperationContext | None],
) -> None:
    """Reset the operation context to its prior state."""
    _current_context.reset(token)


def clear_operation_context() -> None:
    """Clear any bound operation context (set the var to its default ``None``).

    Intended for tests that need a guaranteed-empty slate regardless of what a
    prior test (or a CLI-invoking test) left bound. CLI code should prefer
    :func:`reset_operation_context` with the token returned by
    :func:`set_operation_context`.
    """
    _current_context.set(None)


__all__ = [
    "OPERATION_ID_ATTR",
    "OperationContext",
    "clear_operation_context",
    "current_operation_id",
    "new_operation_id",
    "reset_operation_context",
    "set_operation_context",
]
