# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Ownership and reconciliation for the cross-domain ``models/gold/shared/`` subtree.

An approved calendar renders to ``models/gold/shared/dim_date.sql`` -- deliberately not
under the declaring domain, because one hub materializes one governed calendar and every
Gold model reads it. But the emitter claimed those files for the *declaring domain's*
manifest, so the second domain to author an approved calendar could not compile into the
same target at all (issue #849): its emit saw a file owned by somebody else and failed
closed with ``ArtifactCollisionError`` naming a path the author never wrote.

The subtree belongs to the shared manifest, like every other cross-domain artifact. That
alone makes two calendar-bearing domains coexist, but it also means "whoever compiled
last" would decide the shared bytes -- so this module unions them instead, and fails
closed when the disagreement is real.

The distinction that matters: two domains declaring the same calendar bounds produce a
*byte-identical* ``dim_date.sql`` and differ only in which profile URI is recorded as its
provenance. That is not a conflict, it is one table with two contributors. Two domains
declaring different bounds produce one physical table with two incompatible definitions,
and reconciling that silently would be worse than the collision it replaced.
"""

from __future__ import annotations

from typing import Any

import yaml

SHARED_GOLD_PREFIX = "models/gold/shared/"

#: The rendered schema yml for the shared subtree. Unioned rather than overwritten.
SHARED_GOLD_MODELS_PATH = f"{SHARED_GOLD_PREFIX}_shared__gold_models.yml"

#: Per-domain provenance, and the only key two domains may legitimately disagree on.
_CONTRIBUTED_KEY = "calendar_profile"


class SharedGoldUnionError(ValueError):
    """Two domains render incompatible bytes for one shared Gold artifact.

    Raised only for a genuine disagreement about the materialized table -- different
    calendar bounds, week pattern or fiscal year start. The caller translates this into
    an emission failure, so nothing is written.
    """


def is_shared_gold_artifact(path: str) -> bool:
    """Whether *path* is materialized once for the hub rather than owned by a domain."""
    return path.startswith(SHARED_GOLD_PREFIX)


def union_shared_gold_artifact(path: str, existing: str, incoming: str) -> str:
    """Reconcile one shared Gold artifact across two domains, or fail closed.

    *existing* is what a previous domain's emit left on disk; *incoming* is what this
    domain renders. Returns the bytes to write.
    """
    if existing == incoming:
        return incoming
    if path != SHARED_GOLD_MODELS_PATH:
        # dim_date.sql and anything else added later: the shared subtree is the physical
        # table, so differing bytes mean the two domains disagree about what is built.
        raise SharedGoldUnionError(
            f"{path!r} is materialized once for the hub, but two domains render it "
            "differently; reconcile the calendar profiles so they declare the same "
            "bounds, week pattern and fiscal year start"
        )
    return _union_models_yaml(existing, incoming)


def _union_models_yaml(existing: str, incoming: str) -> str:
    existing_doc = yaml.safe_load(existing) or {}
    incoming_doc = yaml.safe_load(incoming) or {}
    merged: dict[str, Any] = dict(incoming_doc)
    by_name = {model.get("name"): model for model in existing_doc.get("models", []) or []}
    models: list[dict[str, Any]] = []
    for model in incoming_doc.get("models", []) or []:
        previous = by_name.pop(model.get("name"), None)
        models.append(model if previous is None else _union_model(previous, model))
    # A model only the previous domain declared stays: this run re-reads the shared
    # subtree rather than owning it, and dropping it would delete another domain's work.
    models.extend(by_name.values())
    merged["models"] = sorted(models, key=lambda item: str(item.get("name", "")))
    return yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)


def _union_model(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    name = incoming.get("name")
    existing_meta = dict(existing.get("meta") or {})
    incoming_meta = dict(incoming.get("meta") or {})
    contributed = _contributors(existing_meta) | _contributors(incoming_meta)
    comparable_existing = {**existing, "meta": _without_contributors(existing_meta)}
    comparable_incoming = {**incoming, "meta": _without_contributors(incoming_meta)}
    if comparable_existing != comparable_incoming:
        raise SharedGoldUnionError(
            f"two domains describe the shared Gold model {name!r} differently: "
            f"{_first_difference(comparable_existing, comparable_incoming)}. "
            "One hub materializes one governed calendar; the profiles must agree."
        )
    meta = dict(incoming_meta)
    # Scalar while one domain declares it, so every existing hub's bytes are unchanged;
    # a list once several do, because naming one of them would be an arbitrary choice
    # and naming none would lose the provenance this key exists to carry.
    if contributed:
        ordered = sorted(contributed)
        meta[_CONTRIBUTED_KEY] = ordered[0] if len(ordered) == 1 else ordered
    return {**incoming, "meta": meta}


def _contributors(meta: dict[str, Any]) -> set[str]:
    value = meta.get(_CONTRIBUTED_KEY)
    if isinstance(value, list):
        return {str(item) for item in value}
    return {str(value)} if value else set()


def _without_contributors(meta: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in meta.items() if key != _CONTRIBUTED_KEY}


def _first_difference(existing: dict[str, Any], incoming: dict[str, Any]) -> str:
    """Name the disagreeing key rather than dumping two whole model definitions.

    The operator has to act on this message by editing one of two calendar profiles, and
    a diff of every calendar column buries the one field that actually differs.
    """
    for key in sorted({*existing, *incoming}):
        left, right = existing.get(key), incoming.get(key)
        if left == right:
            continue
        if key == "meta" and isinstance(left, dict) and isinstance(right, dict):
            return _first_difference(left, right)
        return f"{key} is {left!r} in one and {right!r} in the other"
    return "they differ"
