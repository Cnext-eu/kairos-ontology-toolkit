# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The one reader of the hub's own ontology IRIs (DD-248 §5).

A hub has no ``base_iri`` setting: ``init`` mints ``https://<company>/ont/<domain>`` into
each file and does not retain it. Every later question -- "is this property hub-local?",
"which namespace does ``scaffold-extensions`` mint into?", "is this IRI one of ours?" --
was answered by a separate heuristic (a catalog regex, a ``_master.ttl`` regex, "differs
from the anchor class's module", an ``example.com`` fallback). This module answers them
all from the same fact: the ``owl:Ontology`` IRI each file under ``model/ontologies/``
declares. It reads through the inventoried per-file primitive and never parses on its
own account.
"""

from __future__ import annotations

import logging
from pathlib import Path

from .catalog_utils import _declared_ontology_iri
from .ontology_integrity import _hub_ontologies_fingerprint, _namespace_of as namespace_of

__all__ = [
    "domain_namespace",
    "hub_ontology_iris",
    "hub_ontology_namespaces",
    "is_hub_namespace",
    "namespace_of",
    "reset_hub_namespace_cache",
]

logger = logging.getLogger(__name__)

_CACHE: dict[tuple[str, str], dict[str, str]] = {}


def hub_ontology_iris(hub_root: Path) -> dict[str, str]:
    """``{file stem: ontology IRI}`` for every ``model/ontologies/*.ttl`` declaring one.

    IRIs are returned without a trailing ``#`` or ``/``. ``_master`` and ``_foundation``
    are included: the hub authors them too. A file that does not parse, or declares no
    ``owl:Ontology``, is skipped; the single-file validator reports that, not this.
    Memoised on the directory's content, so an edited file invalidates the answer.
    """
    ontologies_dir = Path(hub_root) / "model" / "ontologies"
    if not ontologies_dir.is_dir():
        return {}
    key = (
        str(ontologies_dir.resolve()),
        _hub_ontologies_fingerprint(ontologies_dir, include_managed=True),
    )
    cached = _CACHE.get(key)
    if cached is not None:
        return dict(cached)
    found: dict[str, str] = {}
    for path in sorted(ontologies_dir.glob("*.ttl")):
        try:
            iri = _declared_ontology_iri(path)
        except Exception:  # noqa: BLE001 - a malformed sibling is the validator's finding
            logger.debug("Could not read the ontology IRI of %s", path, exc_info=True)
            continue
        if iri:
            found[path.stem] = iri.rstrip("#/")
    _CACHE[key] = dict(found)
    return found


def hub_ontology_namespaces(hub_root: Path) -> frozenset[str]:
    """The bare IRIs (no ``#``/``/``) of every ontology the hub authors."""
    return frozenset(hub_ontology_iris(hub_root).values())


def domain_namespace(hub_root: Path, domain: str) -> str | None:
    """``"<iri>#"`` for one domain file, or ``None`` when it declares no ontology."""
    iri = hub_ontology_iris(hub_root).get(domain)
    return f"{iri}#" if iri else None


def is_hub_namespace(uri: str, namespaces: frozenset[str]) -> bool:
    """True when *uri*'s namespace is one the hub authors."""
    return namespace_of(uri).rstrip("#/") in namespaces


def reset_hub_namespace_cache() -> None:
    _CACHE.clear()
