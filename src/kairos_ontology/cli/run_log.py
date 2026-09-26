# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The default per-run log of a command that writes (#1011).

A compile's diagnostics reached only the console, interleaved across domains, and were
gone once the terminal scrolled. A command that writes -- ``compile --emit``,
``emit-gold``, ``package-powerbi-release`` -- now also writes a JSON-lines run log,
``<repo>/.kairos/logs/<utc>-<command>-<operation>.jsonl``, holding every diagnostic it
reported and a per-task summary. ``<repo>`` is the managed repository root, which for a
flat-layout hub is the hub itself (#1038).

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


def kairos_dir(start: Path) -> Path:
    """The repository's one ``.kairos/`` folder, for *start* or any path inside it (#1038).

    Anchored at the managed repository root, where ``update`` also keeps its
    ``upgrade-refresh.log``, not at the ``ontology-hub/`` folder: one repository had two
    ``.kairos/`` folders and the run logs were in the one nobody looked in. A flat-layout
    or standalone hub is its own root, so for it nothing moves.
    """
    from ..core.hub_utils import resolve_repo_root

    return resolve_repo_root(Path(start)) / ".kairos"


def ensure_kairos_dir(start: Path) -> Path:
    """Create :func:`kairos_dir` for *start*, ignoring itself in git; return it.

    Self-ignoring because a dataplatform's ``.gitignore`` is written once, at creation,
    and does not list ``.kairos/``. May raise ``OSError``; callers keep going without it.
    """
    directory = kairos_dir(start)
    directory.mkdir(parents=True, exist_ok=True)
    ignore = directory / ".gitignore"
    if not ignore.is_file():
        ignore.write_text("# Kairos local logs (#1011, #1038); local only.\n*\n", encoding="utf-8")
    return directory


def run_log_directory(hub: Path) -> Path:
    return kairos_dir(hub) / "logs"


def legacy_run_log_directory(hub: Path) -> Path:
    """Where run logs were kept before #1038, still read by ``logs show``."""
    return Path(hub) / ".kairos" / "logs"


def run_log_directories(start: Path) -> list[Path]:
    """The directories ``logs show`` reads for *start*: current first, then legacy.

    *start* may be the repository root, the hub, or any folder below either.
    """
    from ..core.hub_utils import find_hub_root, find_managed_root

    start = Path(start)
    root = find_managed_root(start)
    hub = find_hub_root(start) or (find_hub_root(root) if root else None)
    if hub is None and root is None:
        return []
    directories = [run_log_directory(hub or root)]
    if hub is not None:
        directories.append(legacy_run_log_directory(hub))
    return list(dict.fromkeys(d.resolve() for d in directories))


def newest_run_log(start: Path) -> Path | None:
    """The newest run log across :func:`run_log_directories`, or None.

    Names start with the UTC timestamp, so the newest is the greatest name.
    """
    logs = [p for d in run_log_directories(start) for p in d.glob("*.jsonl")]
    return max(logs, key=lambda p: p.name) if logs else None


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
