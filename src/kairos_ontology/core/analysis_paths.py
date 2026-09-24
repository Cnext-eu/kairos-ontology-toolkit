# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""File names under ``integration/sources/_analysis/`` — one place, one convention.

The directory holds three kinds of artifact, keyed three different ways, and the old
names did not say which: ``tms-affinity.yaml`` is about a *source system*,
``booking-alignment.yaml`` about an *ontology domain* (and mixes tables from several
systems), ``table-anchors.yaml`` about the whole hub. A reader could not tell whether
``booking`` was a source or a domain without opening the file.

The convention puts the scope in the name::

    src-<system>.<kind>.yaml     affinity, table-dispositions
    dom-<domain>.<kind>.yaml     alignment, unresolved-anchors
    hub.<kind>.yaml              table-anchors, gap-decisions, affinity-matrix

Every kind is still matched by one simple glob (``src-*.affinity.yaml``), and the key is
read back by stripping a fixed prefix and suffix, so a system or domain name containing
dashes round-trips.

Writers always use the new name. Readers also accept the pre-5.22 name for one minor
release (the ``evidence_loaders`` precedent of reading both locations); where a key
exists under both, the new name wins, and a writer removes the old twin of the file it
just wrote. ``update`` renames legacy files in place
(:func:`legacy_renames`), so the fallback is a bridge, not a second layout.

The two name families cannot collide: a new name ends ``.<kind>.yaml`` (dot) and an old
one ``-<kind>.yaml`` (dash), so neither glob matches the other's files.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: The directory, relative to the hub root.
ANALYSIS_RELPATH = Path("integration") / "sources" / "_analysis"

AFFINITY = "affinity"
TABLE_DISPOSITIONS = "table-dispositions"
ALIGNMENT = "alignment"
UNRESOLVED_ANCHORS = "unresolved-anchors"
TABLE_ANCHORS = "table-anchors"
GAP_DECISIONS = "gap-decisions"
AFFINITY_MATRIX = "affinity-matrix"

SOURCE_PREFIX = "src-"
DOMAIN_PREFIX = "dom-"
HUB_PREFIX = "hub."

#: Kinds keyed by source system.
SOURCE_KINDS: frozenset[str] = frozenset({AFFINITY, TABLE_DISPOSITIONS})
#: Kinds keyed by ontology domain.
DOMAIN_KINDS: frozenset[str] = frozenset({ALIGNMENT, UNRESOLVED_ANCHORS})
#: One file per hub.
HUB_KINDS: frozenset[str] = frozenset({TABLE_ANCHORS, GAP_DECISIONS, AFFINITY_MATRIX})

#: Pre-5.22 keyed kinds, named ``<key>-<kind>.yaml``. ``table-dispositions`` is absent: it
#: was one hub-wide file, and splitting it per system is a content change, not a rename
#: (see ``source_disposition``).
_LEGACY_KEYED_KINDS: frozenset[str] = frozenset({AFFINITY, ALIGNMENT, UNRESOLVED_ANCHORS})

_warned_legacy: set[Path] = set()


def analysis_dir(hub_root: Path) -> Path:
    """The hub's ``_analysis/`` directory (which may not exist yet)."""
    return Path(hub_root) / ANALYSIS_RELPATH


def _prefix(kind: str) -> str:
    if kind in SOURCE_KINDS:
        return SOURCE_PREFIX
    if kind in DOMAIN_KINDS:
        return DOMAIN_PREFIX
    raise ValueError(f"{kind!r} is not a keyed _analysis kind")


def keyed_path(directory: Path, kind: str, key: str) -> Path:
    """Where *kind* for *key* is written: ``src-<key>.<kind>.yaml`` or ``dom-<key>.…``."""
    return Path(directory) / f"{_prefix(kind)}{key}.{kind}.yaml"


def legacy_keyed_path(directory: Path, kind: str, key: str) -> Path | None:
    """The pre-5.22 name for *kind* and *key*, or ``None`` if the kind had none."""
    if kind not in _LEGACY_KEYED_KINDS:
        return None
    return Path(directory) / f"{key}-{kind}.yaml"


def hub_path(directory: Path, kind: str) -> Path:
    """Where hub-wide *kind* is written: ``hub.<kind>.yaml``."""
    if kind not in HUB_KINDS:
        raise ValueError(f"{kind!r} is not a hub-wide _analysis kind")
    return Path(directory) / f"{HUB_PREFIX}{kind}.yaml"


def legacy_hub_path(directory: Path, kind: str) -> Path:
    """The pre-5.22 name for hub-wide *kind*: ``<kind>.yaml``."""
    return Path(directory) / f"{kind}.yaml"


def glob_pattern(kind: str) -> str:
    """The hub-relative glob for *kind*, as the gate registry declares evidence."""
    base = ANALYSIS_RELPATH.as_posix()
    if kind in HUB_KINDS:
        return f"{base}/{HUB_PREFIX}{kind}.yaml"
    return f"{base}/{_prefix(kind)}*.{kind}.yaml"


def _note_legacy(directory: Path, paths: list[Path]) -> None:
    """Log once per directory that pre-5.22 names are still in use.

    Info, not a warning: the files are read correctly, ``update --check`` reports them
    and ``update`` renames them, so a warning on every command -- including ones whose
    stdout is a machine-read JSON document -- would be noise about a solved problem.
    """
    if not paths or directory in _warned_legacy:
        return
    _warned_legacy.add(directory)
    logger.info(
        "%d file(s) in %s use pre-5.22 names (%s); run 'kairos-ontology update' to rename "
        "them to the src-/dom-/hub. convention.",
        len(paths),
        directory,
        ", ".join(sorted(p.name for p in paths)),
    )


def iter_keyed(directory: Path, kind: str) -> list[tuple[str, Path]]:
    """Every ``(key, path)`` of *kind* in *directory*, sorted by key.

    Reads the new names and, during the transition, the old ones; a key present under
    both resolves to the new file. Returns ``[]`` for a missing directory.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    prefix = _prefix(kind)
    suffix = f".{kind}.yaml"
    found: dict[str, Path] = {}
    for path in directory.glob(f"{prefix}*{suffix}"):
        key = path.name[len(prefix) : -len(suffix)]
        if key:
            found[key] = path
    legacy: list[Path] = []
    if kind in _LEGACY_KEYED_KINDS:
        legacy_suffix = f"-{kind}.yaml"
        for path in directory.glob(f"*{legacy_suffix}"):
            key = path.name[: -len(legacy_suffix)]
            if key and key not in found:
                found[key] = path
                legacy.append(path)
    _note_legacy(directory, legacy)
    return sorted(found.items())


def iter_keyed_paths(directory: Path, kind: str) -> list[Path]:
    """The paths of :func:`iter_keyed`, for callers that read the key from the content."""
    return [path for _key, path in iter_keyed(directory, kind)]


def key_of(path: Path, kind: str) -> str:
    """The system or domain a *kind* file is about, from its name (either convention)."""
    name = Path(path).name
    prefix, suffix = _prefix(kind), f".{kind}.yaml"
    if name.startswith(prefix) and name.endswith(suffix):
        return name[len(prefix) : -len(suffix)]
    legacy_suffix = f"-{kind}.yaml"
    if name.endswith(legacy_suffix):
        return name[: -len(legacy_suffix)]
    return Path(name).stem


def find_keyed(directory: Path, kind: str, key: str) -> Path | None:
    """The existing file for *kind* and *key* (new name first), or ``None``."""
    new = keyed_path(directory, kind, key)
    if new.is_file():
        return new
    old = legacy_keyed_path(directory, kind, key)
    if old is not None and old.is_file():
        _note_legacy(Path(directory), [old])
        return old
    return None


def find_hub(directory: Path, kind: str) -> Path | None:
    """The existing hub-wide *kind* file (new name first), or ``None``."""
    new = hub_path(directory, kind)
    if new.is_file():
        return new
    old = legacy_hub_path(directory, kind)
    if old.is_file():
        _note_legacy(Path(directory), [old])
        return old
    return None


def read_keyed_path(directory: Path, kind: str, key: str) -> Path:
    """The file to read for *kind* and *key*: the existing one, else the new name."""
    return find_keyed(directory, kind, key) or keyed_path(directory, kind, key)


def read_hub_path(directory: Path, kind: str) -> Path:
    """The hub-wide file to read: the existing one, else the new name."""
    return find_hub(directory, kind) or hub_path(directory, kind)


def retire_legacy_keyed(directory: Path, kind: str, key: str) -> None:
    """Remove the old-name twin of a file just written under the new name.

    Called by writers after writing, so a regenerated artifact never leaves its
    superseded copy behind for a glob to find.
    """
    old = legacy_keyed_path(directory, kind, key)
    if old is not None and old.is_file() and keyed_path(directory, kind, key).is_file():
        old.unlink()


def retire_legacy_hub(directory: Path, kind: str) -> None:
    """Remove the old-name twin of a hub-wide file just written under the new name."""
    old = legacy_hub_path(directory, kind)
    if old.is_file() and hub_path(directory, kind).is_file():
        old.unlink()


def legacy_renames(directory: Path) -> list[tuple[Path, Path]]:
    """``(old, new)`` for every pre-5.22 file ``update`` should rename.

    A file whose new name already exists is *not* listed: both being present means
    something regenerated after the upgrade, and :func:`legacy_conflicts` reports it
    instead of guessing which copy is right. ``table-dispositions.yaml`` is not a
    rename (it is split per system) and is handled by ``source_disposition``.
    """
    directory = Path(directory)
    if not directory.is_dir():
        return []
    renames: list[tuple[Path, Path]] = []
    for kind in sorted(_LEGACY_KEYED_KINDS):
        suffix = f"-{kind}.yaml"
        for old in sorted(directory.glob(f"*{suffix}")):
            key = old.name[: -len(suffix)]
            new = keyed_path(directory, kind, key)
            if key and not new.exists():
                renames.append((old, new))
    for kind in sorted(HUB_KINDS):
        old, new = legacy_hub_path(directory, kind), hub_path(directory, kind)
        if old.is_file() and not new.exists():
            renames.append((old, new))
    return renames


def legacy_conflicts(directory: Path) -> list[tuple[Path, Path]]:
    """``(old, new)`` pairs where both names exist — left for a human to resolve."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    conflicts: list[tuple[Path, Path]] = []
    for kind in sorted(_LEGACY_KEYED_KINDS):
        suffix = f"-{kind}.yaml"
        for old in sorted(directory.glob(f"*{suffix}")):
            new = keyed_path(directory, kind, old.name[: -len(suffix)])
            if new.exists():
                conflicts.append((old, new))
    for kind in sorted(HUB_KINDS):
        old, new = legacy_hub_path(directory, kind), hub_path(directory, kind)
        if old.is_file() and new.exists():
            conflicts.append((old, new))
    return conflicts
