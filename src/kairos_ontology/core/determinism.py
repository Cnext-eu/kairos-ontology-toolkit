# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic projection context helpers.

Projection output must be a *reproducible* function of the encoded inputs.  The
generation timestamp is the main source of non-determinism: every projector and
report used to call :func:`datetime.now` independently, so two runs over the same
inputs produced byte-different output.

This module centralises the timestamp so it can be pinned to a single value for a
whole projection run and, optionally, overridden via the environment for
reproducible builds:

* ``KAIROS_GENERATED_AT`` — an explicit ISO-8601 UTC string (e.g.
  ``2026-07-19T00:00:00Z``).  Used verbatim.
* ``SOURCE_DATE_EPOCH`` — POSIX seconds (the reproducible-builds convention).
* neither set — falls back to :func:`datetime.now` (current behaviour).

Callers should resolve the timestamp **once** per run and thread it through every
target/report so filenames and embedded ``-- Generated at:`` comments agree.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

#: Environment variables consulted, in priority order.
ENV_GENERATED_AT = "KAIROS_GENERATED_AT"
ENV_SOURCE_DATE_EPOCH = "SOURCE_DATE_EPOCH"


def resolve_generated_at(env: dict[str, str] | None = None) -> datetime:
    """Resolve the generation timestamp for a projection run.

    Precedence: ``KAIROS_GENERATED_AT`` > ``SOURCE_DATE_EPOCH`` > ``now(UTC)``.

    Args:
        env: Optional environment mapping (defaults to :data:`os.environ`), mainly
            for testing.

    Returns:
        A timezone-aware :class:`datetime` in UTC.
    """
    environ = os.environ if env is None else env

    explicit = environ.get(ENV_GENERATED_AT)
    if explicit:
        return _parse_iso_utc(explicit)

    epoch = environ.get(ENV_SOURCE_DATE_EPOCH)
    if epoch:
        try:
            return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            pass

    return datetime.now(timezone.utc)


def _parse_iso_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into a UTC-aware datetime.

    Accepts a trailing ``Z`` (which :func:`datetime.fromisoformat` rejects before
    Python 3.11 and treats specially otherwise).  Naive values are assumed UTC.
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # Last resort: use the raw string date only; fall back to now on failure.
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def generated_at_iso(dt: datetime | None = None) -> str:
    """Return the canonical ``YYYY-MM-DDThh:mm:ssZ`` string for content stamps."""
    dt = resolve_generated_at() if dt is None else dt
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generated_at_slug(dt: datetime | None = None) -> str:
    """Return a filesystem-safe ``YYYY-MM-DD-HHMMSS`` slug for report filenames."""
    dt = resolve_generated_at() if dt is None else dt
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
