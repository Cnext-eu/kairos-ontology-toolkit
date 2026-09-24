# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Detect an alignment artifact stale against its domain's activated module list (#518).

A ``<domain>-alignment.yaml`` records the ``domain_uris`` it was generated against: the
``imports[].uri`` list of the blueprint's data domain, which is also what the current side
of the comparison reads. When a blueprint change adds or removes an activated module, the
file is silently stale and downstream stages consume it as if it were current.

What this does *not* see: a change inside an activated module (a reference-models upgrade
that adds an ``owl:imports`` two hops down) or an added ``cross_domain_relationships``
bridge. Both change the class inventory the alignment was built from and leave the module
list unchanged. A resolved-closure comparison would need the catalog at check time; this
one deliberately stays a cheap list comparison.

The failure is invisible *and it points the wrong way*. What surfaces is
``integrity.managed-import-unused``: "this domain imports a module and references nothing
from it", which reads as a **sourcing** gap ("we have no data for this") when the real
cause is a **staleness** gap ("we never looked"). On a hub using those warnings as a
sourcing backlog (DD-187), a stale file corrupts the backlog.

Distinct from #513, which is the hub's imports going stale against the *blueprint*. This is
the alignment going stale against the hub's own imports.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

from . import analysis_paths


@dataclass(frozen=True, slots=True)
class ClosureDrift:
    """What changed in a domain's import closure since its alignment was generated."""

    domain: str
    added: tuple[str, ...]
    removed: tuple[str, ...]

    @property
    def is_stale(self) -> bool:
        return bool(self.added or self.removed)

    def describe(self) -> str:
        """One line naming what moved, and which direction the reader should read it."""
        parts: list[str] = []
        if self.added:
            parts.append(f"{len(self.added)} module(s) added since: {', '.join(self.added)}")
        if self.removed:
            parts.append(
                f"{len(self.removed)} module(s) removed since: {', '.join(self.removed)}"
            )
        return (
            f"{analysis_paths.keyed_path(Path(), analysis_paths.ALIGNMENT, self.domain).name} is stale against the domain's activated module list -- "
            + "; ".join(parts)
            + ". Nothing in it could have referenced an added module, so an "
            "'unused import' finding for one is a staleness gap, not a sourcing gap. "
            "Re-run `propose-alignment` for this domain."
        )


def closure_fingerprint(domain_uris: Iterable[str]) -> str:
    """Return a stable digest of a resolved import closure.

    Normalised the way the artifact stores them -- sorted, trailing ``#``/``/`` stripped --
    so a reordering or a cosmetic trailing character is not reported as drift.
    """
    normalized = sorted({str(uri).rstrip("#/") for uri in domain_uris if str(uri).strip()})
    return hashlib.sha256("\n".join(normalized).encode("utf-8")).hexdigest()


def detect_closure_drift(
    alignment_path: Path,
    current_uris: Iterable[str],
) -> ClosureDrift | None:
    """Compare one alignment artifact against the domain's current closure.

    Returns ``None`` when the file cannot be read, records no ``domain_uris``, or is
    current. An unreadable or pre-fingerprint artifact is *not* reported as stale: this
    warns about a real difference, and guessing would train readers to ignore it.
    """
    try:
        document = yaml.safe_load(Path(alignment_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(document, dict):
        return None
    recorded = document.get("domain_uris")
    if not isinstance(recorded, list) or not recorded:
        return None

    def _normalize(values: Iterable[str]) -> set[str]:
        return {str(value).rstrip("#/") for value in values if str(value).strip()}

    was = _normalize(recorded)
    now = _normalize(current_uris)
    if not now:
        # Nothing resolved for the domain now: that is a different problem, and calling
        # every module "removed" would be a misleading way to report it.
        return None
    domain = str(
        document.get("domain") or analysis_paths.key_of(Path(alignment_path), analysis_paths.ALIGNMENT)
    )
    drift = ClosureDrift(
        domain=domain,
        added=tuple(sorted(now - was)),
        removed=tuple(sorted(was - now)),
    )
    return drift if drift.is_stale else None
