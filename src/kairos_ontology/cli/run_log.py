# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The default per-run log of a command that writes (#1011).

A compile's diagnostics reached only the console, interleaved across domains, and were
gone once the terminal scrolled. A command that writes -- ``compile --emit``,
``emit-gold``, ``package-powerbi-release`` -- now also writes a JSON-lines run log,
``<hub>/.kairos/logs/<utc>-<command>-<operation>.jsonl``, holding every diagnostic it
reported and a per-task summary.

Only a writing command gets one by default: ``--check`` and ``--explain`` are
write-free by contract (DD-133/140), and a log file in the hub is a write. They log to a
file with ``--log-file``, which receives the same records. ``KAIROS_RUN_LOG=0`` turns
the default off; ``--log-file`` replaces it.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from ..core.observability.context import current_operation_id
from ..core.observability.logging_config import attach_run_log

#: Run logs kept per hub; the oldest beyond this are deleted when a new one starts.
RUN_LOGS_KEPT = 20
ENV_RUN_LOG = "KAIROS_RUN_LOG"

_explicit_log_file = False
_started: Path | None = None


def reset(*, explicit_log_file: bool) -> None:
    """Called once per invocation by the CLI group, before any command runs."""
    global _explicit_log_file, _started
    _explicit_log_file = explicit_log_file
    _started = None


def started_path() -> Path | None:
    """The run log this invocation attached, or None."""
    return _started


def run_log_directory(hub: Path) -> Path:
    return Path(hub) / ".kairos" / "logs"


def start_run_log(hub: Path | None, command: str) -> Path | None:
    """Attach the default run log for *command* in *hub*; the path, or None.

    Idempotent within one invocation. Returns None outside a hub, when ``--log-file``
    was given, when ``KAIROS_RUN_LOG=0``, or when the directory cannot be written -- a
    read-only checkout still runs, it just keeps no log. The directory ignores itself in
    git, so a hub whose ``.gitignore`` predates this grows no untracked files. It is
    never inside an emission target: those live in the sibling publish root.
    """
    global _started
    if _started is not None:
        return _started
    if hub is None or _explicit_log_file:
        return None
    if os.environ.get(ENV_RUN_LOG, "").strip().lower() in {"0", "false", "no", "off"}:
        return None
    directory = run_log_directory(hub)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        ignore = directory / ".gitignore"
        if not ignore.is_file():
            ignore.write_text("# Kairos run logs (#1011); local only.\n*\n", encoding="utf-8")
        for stale in sorted(directory.glob("*.jsonl"))[: -(RUN_LOGS_KEPT - 1) or None]:
            stale.unlink(missing_ok=True)
    except OSError:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    operation = (current_operation_id() or "run")[:8]
    path = directory / f"{stamp}-{command}-{operation}.jsonl"
    try:
        attach_run_log(path)
    except OSError:
        return None
    _started = path
    return path
