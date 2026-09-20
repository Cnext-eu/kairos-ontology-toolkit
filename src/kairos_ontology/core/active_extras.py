# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Which optional extras a hub environment is actually running on (#878).

``uv sync`` with no ``--extra`` installs the default dependency set and removes
everything outside it. Every ``update --upgrade``, ``--test-ref`` and ``--restore``
therefore silently uninstalled whatever extras the hub was using — and for any hub
configured against Azure Foundry or Azure AI, the extra that carries the provider SDK is
exactly what goes, so the next `anchor-tables` or `propose-alignment` fails on a missing
package the operator did not remove.

Rather than ask the hub to declare its extras twice, this infers them: an extra is
*active* when every distribution it requires is already installed. That is the same
question ``uv sync`` is about to answer destructively, asked first.

A self-referential extra (``kairos-ontology-toolkit[foundry]``, the shape every hub
pyproject uses so the toolkit version is pinned in exactly one place) is expanded
through the installed toolkit's own metadata, so ``foundry`` resolves to the
``azure-ai-projects`` it really means.
"""

from __future__ import annotations

import logging
import re
from importlib import metadata
from pathlib import Path

logger = logging.getLogger(__name__)

#: `name[extra1,extra2]` with an optional version specifier trailing it.
_REQUIREMENT_RE = re.compile(r"^\s*([A-Za-z0-9._-]+)\s*(?:\[([^\]]*)\])?")

#: `... ; extra == 'name'` in a Requires-Dist line.
_EXTRA_MARKER_RE = re.compile(r"""extra\s*==\s*['"]([^'"]+)['"]""")


def _distribution_installed(name: str) -> bool:
    try:
        metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return False
    except Exception:  # noqa: BLE001 - a malformed installed dist is not our problem
        return False
    return True


def _toolkit_extra_requirements(distribution: str, extra: str) -> list[str]:
    """Distribution names an installed package's *extra* pulls in."""
    try:
        requires = metadata.metadata(distribution).get_all("Requires-Dist") or []
    except metadata.PackageNotFoundError:
        return []
    names: list[str] = []
    for line in requires:
        marker = _EXTRA_MARKER_RE.search(line)
        if not marker or marker.group(1) != extra:
            continue
        head = _REQUIREMENT_RE.match(line.split(";", 1)[0])
        if head:
            names.append(head.group(1))
    return names


def _requirement_targets(requirement: str) -> list[str]:
    """Distribution names one requirement line resolves to.

    ``pkg[a,b]`` expands through ``pkg``'s own metadata: the bare name is already
    installed as a direct dependency, so checking it would say "active" for every extra.
    """
    head = _REQUIREMENT_RE.match(requirement)
    if not head:
        return []
    name, bracket = head.group(1), head.group(2)
    if not bracket:
        return [name]
    targets: list[str] = []
    for extra in (part.strip() for part in bracket.split(",")):
        if extra:
            targets.extend(_toolkit_extra_requirements(name, extra))
    return targets


def active_extras(hub_root: Path) -> list[str]:
    """Extras declared in the hub's ``pyproject.toml`` that are fully installed.

    Deliberately over-inclusive. Two extras that share a dependency (``azure`` and
    ``foundry`` both need ``azure-identity``) both report active when only one was asked
    for, and re-passing the other is a no-op because its packages are already there. The
    asymmetry is the point: re-installing an extra nobody wanted costs nothing, and
    dropping one the hub runs on breaks the next command.

    An extra with no resolvable requirements is not reported: it cannot be distinguished
    from an extra that is simply absent, and re-passing it would be a guess. Failure of
    any kind yields ``[]`` — losing an extra is bad, and blocking an upgrade on a
    malformed pyproject would be worse.
    """
    pyproject = Path(hub_root) / "pyproject.toml"
    if not pyproject.is_file():
        return []
    try:
        import tomllib

        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - advisory; never block an upgrade on this
        logger.debug("could not read %s for extras detection", pyproject, exc_info=True)
        return []

    optional = (data.get("project") or {}).get("optional-dependencies") or {}
    active: list[str] = []
    for extra, requirements in sorted(optional.items()):
        if not isinstance(requirements, list) or not requirements:
            continue
        targets: list[str] = []
        for requirement in requirements:
            if isinstance(requirement, str):
                targets.extend(_requirement_targets(requirement))
        if not targets:
            continue
        if all(_distribution_installed(name) for name in targets):
            active.append(extra)
    return active
