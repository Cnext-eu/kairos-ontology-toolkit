# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Shared utilities for detecting the ontology-hub root directory."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Directories that a scaffolded ontology-hub should contain.  ``output`` is no
# longer a hub component — derived artifacts live in a sibling publish root (see
# ``publish_root``), so it is not a hub marker.
_HUB_MARKER_DIRS = ("model", "integration")

# Name of the sibling folder (at the repository root, next to ``ontology-hub``)
# that holds all derived/emitted artifacts.
_PUBLISH_DIRNAME = "ontology-hub-publish"

# Managed-file marker stamped into toolkit-managed files (.github/...).
_MANAGED_MARKER = "kairos-ontology-toolkit:managed"


def is_authored_discovery_ttl(path: Path) -> bool:
    """Return True when *path* is a genuinely authored ``.ttl`` file, not a scaffold template.

    Single shared predicate for ``hub_inspection._authored_ttl`` and the DD-148 discovery
    gate in ``conformance_artifact.check_discovery_gate``. A scaffold-provided template
    (init copies ``businessdiscovery/glossary-template.ttl`` into every freshly-scaffolded
    hub) is not authored evidence — counting it as "present" silently disables the discovery
    gate on a hub with zero real content (issue #288). Both copies of this predicate had the
    identical bug until they were unified here; keep it in this leaf module (no imports of
    ``hub_inspection``/``conformance_artifact``) so the two call sites cannot drift apart
    again.
    """
    return (
        path.suffix == ".ttl"
        and not path.name.endswith(".template")
        and not path.name.endswith("-template.ttl")
    )


# Filename patterns that are NOT domain ontologies and should be skipped.
_NON_DOMAIN_PREFIXES = ("_",)
_NON_DOMAIN_SUFFIXES = ("-silver-ext", "-ext")


def is_domain_ontology_stem(stem: str) -> bool:
    """Return True when *stem* (a ``.ttl`` filename without extension) names a domain ontology.

    Excludes annotation/configuration files such as ``*-silver-ext.ttl``/``*-ext.ttl``
    and metadata files whose name starts with ``_`` (e.g. ``_master.ttl``,
    ``_foundation.ttl``). Single shared predicate for ``core/projector.py``,
    ``core/validator.py``, ``core/hub_inspection.py``, and ``core/catalog_test.py`` —
    kept in this leaf module (no rdflib/projector import) so the four copies cannot
    drift apart again (issue #289).
    """
    if any(stem.startswith(prefix) for prefix in _NON_DOMAIN_PREFIXES):
        return False
    if any(stem.endswith(suffix) for suffix in _NON_DOMAIN_SUFFIXES):
        return False
    return True


def is_domain_ontology(path: Path) -> bool:
    """Return True if *path* looks like a domain ontology file.

    See :func:`is_domain_ontology_stem` for the exclusion rules.
    """
    return is_domain_ontology_stem(path.stem)


# --- Placeholder / unedited-template detection (D2, issue #416) -----------
#
# Single shared home for "is this scaffold-provided text or a real, authored
# answer" predicates, so the extraction-content lint (#416a) and the decision
# content lint (#416c) key off one definition instead of two independently
# drifting heuristics. This subsumes the ``<CONFIRM_...>`` sentinel family
# already used by ``scaffold_staging.py``/``scaffold_binding.py`` (e.g.
# ``SENTINEL_TARGET_CLASS = "<CONFIRM_TARGET_CLASS>"``): those are angle-bracket
# stubs like any other, so the generic check below recognises them without
# either module needing to import this one or duplicate the pattern.

_PLACEHOLDER_TOKEN_RE = re.compile(r"<[^<>]+>")
_PLACEHOLDER_WORDS = frozenset({"TODO", "TBD"})
_WORD_RE = re.compile(r"[A-Za-z]+")


def is_scaffold_placeholder_text(value: Any) -> bool:
    """Return True when *value* still reads like an unedited scaffold stub.

    Recognises angle-bracket placeholders (``<option>``, ``<CONFIRM_GRAIN>``,
    ...) and bare ``TODO``/``TBD`` markers. A non-string value is never a
    placeholder (nothing to flag); an empty/blank string is also not itself a
    placeholder -- callers that also want to reject *empty* should check that
    separately (see :func:`placeholder_fields`).
    """
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if _PLACEHOLDER_TOKEN_RE.search(text):
        return True
    tokens = {t.upper() for t in _WORD_RE.findall(text)}
    return bool(tokens & _PLACEHOLDER_WORDS)


def placeholder_fields(
    mapping: dict[str, Any] | None,
    *,
    required: tuple[str, ...],
) -> list[str]:
    """Return the subset of *required* keys that are missing, empty, or placeholder text.

    Generic "is this field actually filled in" check shared by content-lint
    callers (extraction ``summary``/``strategy`` for #416a; decision
    frontmatter fields for #416c). A key counts as unfilled when it is absent,
    ``None``, blank/placeholder text, or an empty list/tuple/dict.
    """
    if not isinstance(mapping, dict):
        return list(required)
    unfilled: list[str] = []
    for key in required:
        value = mapping.get(key)
        if value is None:
            unfilled.append(key)
        elif isinstance(value, str):
            if not value.strip() or is_scaffold_placeholder_text(value):
                unfilled.append(key)
        elif isinstance(value, (list, tuple, dict)) and not value:
            unfilled.append(key)
    return unfilled


def body_is_unedited_template(body: str, template: str) -> bool:
    """Return True when *body* is, modulo surrounding whitespace, *template* verbatim.

    Keys a lint off exact identity with a known scaffold body (e.g.
    ``decision_records.TEMPLATE_BODY``) rather than a fragile heuristic over
    the body's structure -- see #416c: the existing rejected-alternative
    heuristic is fooled by the template's own placeholder row, which is
    exactly the "unedited stub" case this function exists to catch instead.
    """
    return body.strip() == template.strip()


def publish_root(hub: Path) -> Path:
    """Return the derived-output publish root for *hub*.

    Derived/emitted artifacts (the dbt project, Power BI, Neo4j, Azure Search,
    reports, validation reports, etc.) live **outside** the authored hub
    directory, in a sibling folder at the repository root:
    ``<hub.parent>/ontology-hub-publish``.

    Callers must pass the *hub root* (as returned by :func:`find_hub_root`), not
    the current working directory — otherwise the sibling would resolve one level
    too high.  For a not-yet-discovered hub, use ``publish_root(cwd /
    "ontology-hub")``.
    """
    return hub.parent / _PUBLISH_DIRNAME


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


def resolve_repo_root(hub_root: Path) -> Path:
    """Return the repository root that owns *hub_root*.

    The repo root is the nearest ancestor of *hub_root* (including *hub_root*
    itself) that carries the toolkit pin or managed ``.github/`` files — see
    :func:`find_managed_root`. Bare/test hubs (a hub directory with no managed
    ancestor) degrade to the hub root itself, so
    ``resolve_repo_root(hub) == hub.resolve()`` means "standalone hub: the hub
    root is the only resolution base". The result is always resolved; compare
    against ``hub_root.resolve()``, not the raw *hub_root*.
    """
    return find_managed_root(hub_root) or hub_root.resolve()


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
       directory (model/ or integration/) → ``cwd/ontology-hub``
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
            "Found ontology-hub/ at %s but it has no hub marker directories (%s) — ignoring.",
            oh_dir,
            ", ".join(_HUB_MARKER_DIRS),
        )

    return None


def resolve_hub_output_dir(
    relative: Path | str,
    *,
    cwd: Path | None = None,
) -> tuple[Path, Path | None]:
    """Resolve a hub-relative output path against the detected hub root.

    Single implementation for the "where does this command write?" question.
    ``import-flatfile``, ``import-source`` and ``import-tmdl`` each carried a
    verbatim copy of hub-detect + warn + relative-fallback; issues #288 and #289
    are the record of what happens when duplicated predicates in this codebase
    drift, so this lives here and they all call it (issue #296).

    Unlike :func:`find_hub_root`, this also searches **ancestor** directories, so
    running a command from inside the hub (``ontology-hub/integration/``) resolves
    to the hub root rather than producing a doubly-nested
    ``integration/integration/...`` tree (DD-064). Ancestors must carry
    ``model/ontologies/`` (``require_model=True``) — a bare ``ontology-hub/``
    directory name several levels up is too weak a signal to redirect writes to.

    Args:
        relative: Hub-relative destination, e.g. ``integration/discovery/bi``.
        cwd: Starting directory. Defaults to ``Path.cwd()``.

    Returns:
        ``(output_dir, hub_root)``. When no hub can be detected, ``hub_root`` is
        ``None`` and ``output_dir`` is *relative* itself (i.e. cwd-relative).
        Callers must tell the user where output went in that case — writing to a
        guessed relative path silently is the defect this helper exists to stop.
    """
    relative = Path(relative)
    if cwd is None:
        cwd = Path.cwd()

    hub_root = find_hub_root(cwd)
    if hub_root is None:
        for ancestor in cwd.parents:
            hub_root = find_hub_root(ancestor, require_model=True)
            if hub_root is not None:
                logger.debug(
                    "Resolved hub root %s from ancestor of %s.",
                    hub_root,
                    cwd,
                )
                break

    if hub_root is not None:
        return hub_root / relative, hub_root

    return relative, None
