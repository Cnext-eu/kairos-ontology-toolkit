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

A variable that is *set but malformed* is rejected with :class:`ValueError`
rather than silently falling back to :func:`datetime.now`.  A typo in a
reproducible-build pin must fail loudly, not quietly emit non-reproducible
output.  An unset or whitespace-only variable is treated as absent.

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

    A set-but-malformed pin raises :class:`ValueError` instead of silently
    defaulting to the current time; an unset or whitespace-only variable is
    treated as absent and defers to the next source.

    Args:
        env: Optional environment mapping (defaults to :data:`os.environ`), mainly
            for testing.

    Returns:
        A timezone-aware :class:`datetime` in UTC.

    Raises:
        ValueError: If ``KAIROS_GENERATED_AT`` is not a valid ISO-8601 timestamp,
            or ``SOURCE_DATE_EPOCH`` is not an in-range integer of POSIX seconds.
    """
    environ = os.environ if env is None else env

    explicit = environ.get(ENV_GENERATED_AT, "").strip()
    if explicit:
        return _parse_iso_utc(explicit)

    epoch = environ.get(ENV_SOURCE_DATE_EPOCH, "").strip()
    if epoch:
        try:
            seconds = int(epoch)
        except ValueError as exc:
            raise ValueError(
                f"{ENV_SOURCE_DATE_EPOCH}={epoch!r} is not a valid integer number of POSIX seconds"
            ) from exc
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError(
                f"{ENV_SOURCE_DATE_EPOCH}={epoch!r} is out of range for a POSIX timestamp"
            ) from exc

    return datetime.now(timezone.utc)


def _parse_iso_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp into a UTC-aware datetime.

    Accepts a trailing ``Z`` (which :func:`datetime.fromisoformat` rejects before
    Python 3.11 and treats specially otherwise).  Naive values are assumed UTC.

    Raises:
        ValueError: If *value* is not a valid ISO-8601 timestamp, so a malformed
            ``KAIROS_GENERATED_AT`` pin fails loudly rather than silently
            defaulting to the current time.
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"{ENV_GENERATED_AT}={value!r} is not a valid ISO-8601 timestamp "
            "(expected e.g. 2026-07-19T00:00:00Z)"
        ) from exc
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
