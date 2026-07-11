# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Per-table sidecar cache for LLM-powered pre-modeling steps.

``analyse-sources`` and ``propose-alignment`` issue one paid LLM call per source
table. On re-runs, most tables are unchanged, yet every call was historically
re-issued. This module provides a lightweight, schema-neutral cache: a JSON
sidecar under ``<analysis-dir>/.cache/<command>.json`` mapping a stable input
hash → the previously computed result payload.

The cache is intentionally **outside** the output YAML so the
``schema_version: 2`` affinity / alignment contract (and the DD-061
``affinity_sha256`` freshness field) is untouched. ``--force`` bypasses the
cache entirely.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CACHE_DIRNAME = ".cache"


def compute_entry_hash(payload: Any) -> str:
    """Return a stable SHA-256 over a JSON-serialisable cache key payload.

    Keys are sorted so the digest is independent of dict ordering. Used to key
    a per-table result on its full set of inputs (table name, columns, sample
    values, candidate/shortlist signature, model, ...).
    """
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class SidecarCache:
    """JSON-backed ``input_hash → result`` cache for one command.

    Not thread-safe for writes; populate from the main thread after the
    concurrent pool drains. Reads (``get``) are safe to call concurrently.
    """

    def __init__(self, cache_path: Path, *, enabled: bool = True) -> None:
        self.cache_path = cache_path
        self.enabled = enabled
        self._entries: dict[str, Any] = {}
        if enabled:
            self._load()

    def _load(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._entries = data.get("entries", {})
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Ignoring unreadable cache %s: %s", self.cache_path, exc)
            self._entries = {}

    def get(self, key_hash: str) -> Any | None:
        """Return the cached result for ``key_hash`` or ``None`` on a miss."""
        if not self.enabled:
            return None
        return self._entries.get(key_hash)

    def put(self, key_hash: str, result: Any) -> None:
        """Record a freshly computed result under ``key_hash``."""
        self._entries[key_hash] = result

    def flush(self) -> None:
        """Persist the cache to disk (creates the ``.cache`` dir as needed)."""
        if not self.enabled:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(
                json.dumps({"entries": self._entries}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Could not write cache %s: %s", self.cache_path, exc)


def open_cache(analysis_dir: Path, command: str, *, enabled: bool = True) -> SidecarCache:
    """Open (or create) the sidecar cache for ``command`` under ``analysis_dir``."""
    cache_path = analysis_dir / CACHE_DIRNAME / f"{command}.json"
    return SidecarCache(cache_path, enabled=enabled)
