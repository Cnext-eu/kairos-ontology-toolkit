# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Shared utilities for detecting the ontology-hub root directory."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Directories that a scaffolded ontology-hub should contain.
_HUB_MARKER_DIRS = ("model", "integration", "output")

# Managed-file marker stamped into toolkit-managed files (.github/...).
_MANAGED_MARKER = "kairos-ontology-toolkit:managed"


def _is_managed_root(directory: Path) -> bool:
    """Return True when *directory* is a toolkit-managed hub/dataplatform root.

    A managed root is the directory that holds the toolkit pin and/or the
    toolkit-managed ``.github/`` files — i.e. the place ``update`` must operate
    on.  It is detected by any of these positive anchors:

    1. ``pyproject.toml`` referencing ``kairos-ontology-toolkit`` or a
       ``[tool.kairos]`` section (the toolkit pin — strongest signal).
    2. ``.github/copilot-instructions.md`` carrying the managed marker.
    3. A dataplatform root: ``dbt_project.yml`` **and** a managed ``.github/``.
    """
    pyproject = directory / "pyproject.toml"
    if pyproject.is_file():
        try:
            content = pyproject.read_text(encoding="utf-8")
        except OSError:
            content = ""
        if "kairos-ontology-toolkit" in content or "[tool.kairos]" in content:
            return True

    instructions = directory / ".github" / "copilot-instructions.md"
    if instructions.is_file():
        try:
            if _MANAGED_MARKER in instructions.read_text(encoding="utf-8"):
                return True
        except OSError:
            pass

    if (directory / "dbt_project.yml").is_file() and (directory / ".github").is_dir():
        return True

    return False


def find_managed_root(cwd: Path | None = None) -> Path | None:
    """Walk **up** from *cwd* to find the toolkit-managed root directory.

    Unlike :func:`find_hub_root` (which only inspects ``cwd`` and
    ``cwd/ontology-hub`` for *content* layout), this resolver searches the
    ancestor chain for the directory that owns the toolkit pin / managed
    ``.github/`` files.  This is the directory the ``update`` command must
    operate on, so running ``update`` from a content subdirectory re-roots to
    the real hub instead of scaffolding a second one.

    Args:
        cwd: Starting directory.  Defaults to ``Path.cwd()``.

    Returns:
        The managed root path, or ``None`` if no ancestor qualifies.
    """
    if cwd is None:
        cwd = Path.cwd()
    cwd = cwd.resolve()

    for directory in [cwd, *cwd.parents]:
        if _is_managed_root(directory):
            return directory
    return None


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
