# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Expressive cost-warning banner for LLM-powered pre-modeling commands.

``analyse-sources`` and ``propose-alignment`` now fan out one (or more) paid LLM
call **per source table, concurrently**. On a large hub this is hundreds of
calls in quick succession. To keep spend visible *before* it happens, both
commands print a prominent banner at the start of the run advising a
cost/value-optimized model (``gpt-5.4-mini``, the default).
"""

from __future__ import annotations

from typing import Callable

import click

# The recommended cost/value-optimized model for these tasks.
RECOMMENDED_MODEL = "gpt-5.4-mini"

_RULE = "=" * 72


def build_cost_warning(
    *,
    command: str,
    table_count: int,
    max_workers: int,
    model: str,
    force: bool,
    accuracy_sensitive: bool = False,
) -> str:
    """Return the multi-line cost-warning banner text.

    Kept pure (returns a string) so it is trivially unit-testable; rendering is
    handled by :func:`print_cost_warning`.
    """
    model_line = (
        f"  ✅ Model in use: '{model}' — recommended for this task."
        if model == RECOMMENDED_MODEL
        else (
            f"  ⚠️  Model in use: '{model}'.  STRONGLY consider the cost/value-"
            f"optimized\n     '{RECOMMENDED_MODEL}' instead (default) — frontier "
            f"models cost far more\n     for no quality gain on this task."
        )
    )
    if accuracy_sensitive and model != RECOMMENDED_MODEL:
        # Issue #182: class-anchoring / column alignment IS accuracy-sensitive, so a
        # higher tier can genuinely reduce hallucinated anchors/properties here.
        model_line = (
            f"  ⚠️  Model in use: '{model}'.  This step is ACCURACY-SENSITIVE "
            f"(class\n     anchoring & column mapping); a higher tier (e.g. via "
            f"--high-accuracy)\n     can reduce hallucinations. '{RECOMMENDED_MODEL}' "
            f"is the cheaper default."
        )
    cache_line = (
        "  ♻️  --force is set: caches are BYPASSED — every table will be re-billed."
        if force
        else "  ♻️  Unchanged tables/domains are skipped via cache (use --force to re-run)."
    )
    return "\n".join([
        "",
        f"💸 {_RULE}",
        f"💸  COSTLY LLM OPERATION  —  {command}",
        f"💸 {_RULE}",
        "  This step issues at least ONE paid LLM call per source table, now run",
        f"  CONCURRENTLY (up to {max_workers} in parallel). On a large hub this is",
        "  HUNDREDS of billed calls in quick succession.",
        "",
        f"  📊 Scale: ~{table_count} table(s) × ≥1 call each, up to {max_workers} in parallel.",
        model_line,
        cache_line,
        "  🐢 Use --max-workers 1 for the slow, cheap, fully-serial path.",
        f"💸 {_RULE}",
        "",
    ])


def print_cost_warning(
    *,
    command: str,
    table_count: int,
    max_workers: int,
    model: str,
    force: bool = False,
    quiet: bool = False,
    accuracy_sensitive: bool = False,
    stream: Callable[[str], None] | None = None,
) -> None:
    """Print the cost-warning banner to stderr unless ``quiet`` is set.

    Args:
        command: Command name shown in the banner (e.g. ``analyse-sources``).
        table_count: Number of source tables that will be processed.
        max_workers: Effective concurrency for this run.
        model: The configured LLM model id.
        force: Whether caches are bypassed (changes the cache advisory line).
        quiet: When True the banner is suppressed entirely.
        stream: Injectable writer (defaults to ``click.echo(..., err=True)`` which
            handles emoji on Windows consoles).
    """
    if quiet:
        return
    text = build_cost_warning(
        command=command,
        table_count=table_count,
        max_workers=max_workers,
        model=model,
        force=force,
        accuracy_sensitive=accuracy_sensitive,
    )
    if stream is not None:
        stream(text + "\n")
    else:
        click.echo(text, err=True)
