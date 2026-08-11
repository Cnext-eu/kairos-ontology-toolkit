# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Redaction for structured log records.

Log records may carry ``extra`` attributes that originate from subprocess
output,profiles, or environment-shaped data. This filter masks values whose
*key* looks sensitive and collapses recognizable secret substrings inside free
text fields, so noisy but bounded dbt/subprocess output cannot leak
credentials or connection strings.

Redaction is conservative: it only touches ``LogRecord`` attributes that are
not part of the standard logging surface, plus ``record.msg`` and
``record.args`` when they are strings. It never alters the structured event
name or the stable numeric/scope attributes skills rely on.
"""

from __future__ import annotations

import logging
import re
from typing import Final, Iterable

#: Substring patterns describing likely secret payloads inside free text.
_SECRET_TEXT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)(token|secret|password|passwd|client_secret|api[-_]?key)\S*"),
    # Bearer-style tokens and Azure client secrets embedded in connection strings.
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"),
    # ODBC / SQLAlchemy password=... fragments.
    re.compile(r"(?i)password\s*=\s*[^;\s\"']+"),
    re.compile(r"(?i)user[_-]?id\s*=\s*[^;\s\"']+"),
    # UUID-like client/tenant secrets used by the offline Fabric profile.
    re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    ),
)

#: Keys (case-insensitive) whose *value* is always fully masked when present
#: as a structured ``LogRecord`` attribute.
_SENSITIVE_KEY_FRAGMENTS: Final[tuple[str, ...]] = (
    "password",
    "passwd",
    "secret",
    "token",
    "client_secret",
    "api_key",
    "apikey",
    "credential",
    "authorization",
)

_REDACTED: Final[str] = "[REDACTED]"

#: Standard ``LogRecord`` attributes that must never be treated as structured
#: ``extra`` payload (see ``logging.LogRecord``). Anything *not* in this set is
#: considered caller-supplied structured data and is subject to redaction.
_STD_LOGRECORD_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "message",
    }
)


def _looks_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(frag in lowered for frag in _SENSITIVE_KEY_FRAGMENTS)


def redact_text(value: str) -> str:
    """Mask recognizable secret substrings inside a free-text string."""
    masked = value
    for pattern in _SECRET_TEXT_PATTERNS:
        masked = pattern.sub(_REDACTED, masked)
    return masked


def _redact_value(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: (_REDACTED if _looks_sensitive(str(k)) else _redact_value(v)) for k, v in value.items()}
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


class RedactionFilter(logging.Filter):
    """A ``logging.Filter`` that masks sensitive keys/substrings in records.

    The filter returns ``True`` for every record (it never drops events); it
    only rewrites sensitive fields in place. Installed on the root logger's
    handlers, it covers every logger in the ``kairos_ontology`` tree.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact structured extra attributes carried on the record.
        for key in list(record.__dict__):
            if key in _STD_LOGRECORD_ATTRS or key == "message":
                continue
            if _looks_sensitive(key):
                setattr(record, key, _REDACTED)
            else:
                setattr(record, key, _redact_value(getattr(record, key)))
        # Redact free-text message + args (string form only).
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_value(arg) for arg in record.args)  # type: ignore[assignment]
        elif isinstance(record.args, dict):
            record.args = {  # type: ignore[assignment]
                k: (_REDACTED if _looks_sensitive(str(k)) else _redact_value(v))
                for k, v in record.args.items()
            }
        return True


def sensitive_patterns() -> Iterable[re.Pattern[str]]:
    """Expose the redaction patterns for tests and operator inspection."""
    return _SECRET_TEXT_PATTERNS


__all__ = ["RedactionFilter", "redact_text", "sensitive_patterns"]
