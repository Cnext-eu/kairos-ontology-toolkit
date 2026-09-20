# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Detect an artifact generated against a business glossary that has since changed (#885).

The glossary is the client's own vocabulary, and unlike every other input to anchoring
and alignment it is *maintained*: a workshop adds twenty terms, a definition is corrected,
a term the business stopped using is removed. `*-alignment.yaml` already fingerprints its
affinity input (DD-094) and its resolved import closure (#518) so either going stale is
visible; the glossary was the one input nothing recorded, so updating it marked nothing.

Sibling of :mod:`alignment_closure`, deliberately the same shape: a fingerprint written
into the artifact at generation, a cheap comparison against the current value, and a
``None`` return for anything that cannot be compared. An artifact written before the
fingerprint existed is *not* reported as stale — this warns about a real difference, and
guessing would train readers to ignore it.

The digest covers the ``(prefLabel, definition)`` pairs, not the file bytes: those pairs
are what reaches a prompt, so adding a term or correcting a definition is drift and
reformatting the Turtle is not.

An **empty** fingerprint is meaningful rather than missing. It records that the artifact
was generated with no glossary in scope — the `--without-discovery` escape, or a hub that
never authored one — which is otherwise visible only on the terminal that produced it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

#: Key both generated artifacts carry.
GLOSSARY_FINGERPRINT_KEY = "glossary_sha256"

#: Fingerprint value meaning "generated with no business glossary in scope".
UNGROUNDED = "none"


@dataclass(frozen=True, slots=True)
class GlossaryDrift:
    """An artifact's recorded glossary fingerprint against the current one."""

    artifact: str
    was: str
    now: str

    @property
    def was_ungrounded(self) -> bool:
        """Whether the artifact was generated with no glossary at all."""
        return self.was == UNGROUNDED

    def describe(self) -> str:
        """One line naming what moved, and what the reader should do about it."""
        if self.was_ungrounded:
            return (
                f"{self.artifact} was generated with no business glossary in scope, and "
                "the hub has one now. Its proposed terms are source-shaped rather than "
                "grounded in the business's own vocabulary. Re-run the stage that wrote "
                "it."
            )
        if self.now == UNGROUNDED:
            return (
                f"{self.artifact} was generated against a business glossary the hub no "
                "longer has. Nothing can check what it was grounded in."
            )
        return (
            f"{self.artifact} was generated against a different version of the business "
            "glossary — terms or definitions have changed since. Its proposals were "
            "grounded in the old vocabulary. Re-run the stage that wrote it."
        )


def glossary_fingerprint(hub_root: Path | None) -> str:
    """Digest the authored glossary's ``(prefLabel, definition)`` pairs.

    Returns :data:`UNGROUNDED` when the hub has no authored glossary, so the value is
    always recordable and an artifact never omits the key for an absent glossary — an
    omitted key and a known-absent glossary are different facts.
    """
    from .propose_alignment import load_glossary_entries

    entries = load_glossary_entries(hub_root, limit=100_000)
    if not entries:
        return UNGROUNDED
    payload = "\n".join(f"{label}{definition}" for label, definition in sorted(entries))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def detect_glossary_drift(artifact_path: Path, hub_root: Path | None) -> GlossaryDrift | None:
    """Compare one generated artifact against the hub's current glossary.

    ``None`` when the file cannot be read, carries no fingerprint (generated before this
    existed), or is current.
    """
    try:
        document = yaml.safe_load(Path(artifact_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        return None
    if not isinstance(document, dict):
        return None
    recorded = document.get(GLOSSARY_FINGERPRINT_KEY)
    if not isinstance(recorded, str) or not recorded:
        return None
    current = glossary_fingerprint(hub_root)
    if recorded == current:
        return None
    return GlossaryDrift(artifact=Path(artifact_path).name, was=recorded, now=current)
