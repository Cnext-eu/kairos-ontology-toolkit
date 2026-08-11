# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Structured log formatters: human text + machine-readable JSON.

Both formatters expose the same stable field set so LLM skills and operators
can rely on:

- ``timestamp``        ISO-8601 UTC.
- ``level``           ``INFO`` / ``WARNING`` / ``ERROR`` / ...
- ``logger``          dotted logger name.
- ``event``           stable dotted event name (``record.event`` extra), if
                      the call site supplied one; otherwise omitted.
- ``message``         human-readable message (after % formatting).
- ``kairos.operation.id`` per-invocation id, when a context is bound.
- every other ``extra`` attribute on the record, redacted upstream.

JSON output is one JSON object per line (NDJSON) — the shape downstream JSON
log shippers and skill parsers expect. Text output is a single readable line
suitable for the console.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Final

from .context import OPERATION_ID_ATTR, current_operation_id

#: Fields that are part of the standard ``LogRecord`` surface and must not be
#: echoed back as a structured ``extra`` payload in JSON output.
_STD_LOGRECORD_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "message", "event",
        OPERATION_ID_ATTR,
    }
)


def _iso_timestamp(record: logging.LogRecord) -> str:
    dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _extra_payload(record: logging.LogRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in record.__dict__.items():
        if key in _STD_LOGRECORD_ATTRS:
            continue
        if key.startswith("_"):
            continue
        payload[key] = value
    return payload


def _traceback(record: logging.LogRecord) -> str | None:
    if record.exc_info is None:
        return None
    return logging.Formatter().formatException(record.exc_info)


class JsonFormatter(logging.Formatter):
    """One JSON object per line with the stable structured field set."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _iso_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if isinstance(event, str):
            payload["event"] = event
        op_id = getattr(record, OPERATION_ID_ATTR, None)
        if op_id is None:
            op_id = current_operation_id()
        if op_id is not None:
            payload[OPERATION_ID_ATTR] = op_id
        payload.update(_extra_payload(record))
        tb = _traceback(record)
        if tb is not None:
            payload["exception"] = tb
        return json.dumps(payload, sort_keys=True, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable single-line output with optional event + operation id."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        event = getattr(record, "event", None)
        if isinstance(event, str):
            message = f"{message} [event={event}]"
        op_id = getattr(record, OPERATION_ID_ATTR, None)
        if op_id is None:
            op_id = current_operation_id()
        if op_id is not None:
            message = f"{message} [{OPERATION_ID_ATTR}={op_id}]"
        asctime = self.formatTime(record, self.datefmt)
        line = f"{asctime} {record.levelname:<7} {record.name}: {message}"
        if record.exc_info:
            tb = self.formatException(record.exc_info)
            line = f"{line}\n{tb}"
        stacktrace = getattr(record, "exception.stacktrace", None)
        if stacktrace:
            line = f"{line}\n{stacktrace}"
        return line


__all__ = ["JsonFormatter", "TextFormatter"]
