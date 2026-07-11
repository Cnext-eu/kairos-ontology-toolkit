# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Concurrency + rate-limit back-off helpers for LLM-powered commands.

The AI pre-modeling steps (``analyse-sources``, ``propose-alignment``) issue one
blocking LLM call per source table. These were historically strictly serial,
which dominates wall-clock time on large hubs (hundreds of tables → ~1 h). The
OpenAI/Azure ``chat.completions.create`` call is I/O-bound and thread-safe per
request, so a bounded thread pool delivers a near-linear speed-up.

``map_concurrent`` runs a function over items with a bounded pool and returns
results in **input order** (deterministic output is required — the alignment /
affinity YAML must diff cleanly). ``call_with_backoff`` wraps a single LLM call
with exponential back-off on rate-limit (HTTP 429) errors so higher worker
counts degrade gracefully instead of failing.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Sequence, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

DEFAULT_MAX_WORKERS = 8
DEFAULT_BACKOFF_RETRIES = 5
DEFAULT_BACKOFF_BASE_DELAY = 2.0


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Best-effort, provider-agnostic detection of a rate-limit (429) error.

    Avoids a hard dependency on a specific SDK exception hierarchy: matches on
    an HTTP 429 status code or a ``RateLimit`` class name / ``429`` in the
    message, which covers the OpenAI and Azure OpenAI clients.
    """
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status == 429:
        return True
    name = type(exc).__name__.lower()
    if "ratelimit" in name:
        return True
    return "429" in str(exc) or "rate limit" in str(exc).lower()


def call_with_backoff(
    fn: Callable[[], R],
    *,
    retries: int = DEFAULT_BACKOFF_RETRIES,
    base_delay: float = DEFAULT_BACKOFF_BASE_DELAY,
    sleep: Callable[[float], None] = time.sleep,
) -> R:
    """Call ``fn`` retrying on rate-limit errors with exponential back-off.

    Non-rate-limit exceptions propagate immediately. On the final attempt the
    rate-limit exception is re-raised so callers can handle it (the per-table
    workers in the analysis commands already catch + warn).

    Args:
        fn: Zero-arg callable performing the LLM request.
        retries: Maximum number of retry attempts after the first call.
        base_delay: Base seconds for the ``base_delay * 2**attempt`` schedule.
        sleep: Injectable sleep (tests pass a no-op).
    """
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — re-raised below if not 429
            if not _is_rate_limit_error(exc) or attempt >= retries:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Rate-limited (attempt %d/%d); backing off %.1fs",
                attempt + 1, retries, delay,
            )
            sleep(delay)
            attempt += 1


def map_concurrent(
    fn: Callable[[T], R],
    items: Sequence[T] | Iterable[T],
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    ordered: bool = True,
    on_result: Callable[[R], None] | None = None,
) -> list[R]:
    """Apply ``fn`` to each item using a bounded thread pool.

    Results are returned in **input order** when ``ordered=True`` (the default),
    which keeps generated YAML deterministic. ``on_result`` is called as each
    item completes, so callers can print progress without waiting for the whole
    ordered result set. With ``max_workers <= 1`` the work runs serially in the
    calling thread — an exact reproduction of the legacy path and a cheap escape
    hatch.

    Exceptions raised by ``fn`` propagate (the analysis commands wrap their
    per-item work so a single table failure does not abort the run).
    """
    work = list(items)
    if not work:
        return []
    if max_workers <= 1:
        results = []
        for item in work:
            result = fn(item)
            if on_result is not None:
                on_result(result)
            results.append(result)
        return results

    workers = min(max_workers, len(work))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, item): idx for idx, item in enumerate(work)}
        results: list[R | None] = [None] * len(work)
        completion_order: list[R] = []
        for fut in as_completed(futures):
            result = fut.result()
            results[futures[fut]] = result
            completion_order.append(result)
            if on_result is not None:
                on_result(result)
        if ordered:
            return [r for r in results]  # type: ignore[misc]
        return completion_order
