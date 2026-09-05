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
