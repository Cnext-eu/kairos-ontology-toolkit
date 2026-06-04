# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Shared utilities for detecting the ontology-hub root directory."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories that a scaffolded ontology-hub should contain.
_HUB_MARKER_DIRS = ("model", "integration", "output")


def find_hub_root(
    cwd: Path | None = None,
    *,
    require_model: bool = False,
) -> Path | None:
    """Detect the ontology-hub root relative to *cwd*.

    Detection order (first match wins):
    1. ``cwd/ontology-hub/model/ontologies/`` exists → ``cwd/ontology-hub``
    2. ``cwd/model/ontologies/`` exists → ``cwd`` (CWD is the hub root)
    3. ``cwd/ontology-hub/`` exists **and** contains at least one hub marker
       directory (model/, integration/, or output/) → ``cwd/ontology-hub``
       *(skipped when require_model=True)*

    Args:
        cwd: Starting directory.  Defaults to ``Path.cwd()``.
        require_model: When *True*, only return a hub root that has
            ``model/ontologies/`` present.  Use this for commands that need
            ontology files to already exist (e.g. ``coverage-report``).

    Returns:
        The hub root path, or ``None`` if no hub could be detected.
    """
    if cwd is None:
        cwd = Path.cwd()

    # 1 & 2: Check for model/ontologies/ in both candidates.
    for candidate in [cwd / "ontology-hub", cwd]:
        if (candidate / "model" / "ontologies").is_dir():
            return candidate

    if require_model:
        return None

    # 3: Freshly scaffolded hub — ontology-hub/ exists with at least one
    #    marker subdirectory, but model/ontologies/ hasn't been created yet.
    oh_dir = cwd / "ontology-hub"
    if oh_dir.is_dir():
        has_marker = any((oh_dir / m).is_dir() for m in _HUB_MARKER_DIRS)
        if has_marker:
            return oh_dir
        logger.debug(
            "Found ontology-hub/ at %s but it has no hub marker directories "
            "(%s) — ignoring.",
            oh_dir,
            ", ".join(_HUB_MARKER_DIRS),
        )

    return None
