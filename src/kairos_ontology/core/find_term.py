# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``find-term``: which closure properties does a name resemble? (DD-248)

The same lookup the aligner, the gap sheet and ``validate`` run, offered to a person or
an agent before it proposes a property. ``explain-term`` and ``list-class-properties``
answer by IRI; this answers by name, which is what a designer holds when the question
is "does the closure already have this?".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from .closure_lookup import DEFAULT_LIMIT, find_candidates, normalise_term, terms_from_index

__all__ = ["find_term"]


def find_term(
    hub_root: Path,
    *,
    name: str,
    domains: Sequence[str],
    catalog_path: Path | None = None,
    limit: int = DEFAULT_LIMIT,
    min_score: float = 0.0,
) -> dict[str, Any]:
    """Closure candidates for *name* in each of *domains*, as one JSON-able document.

    *min_score* is the floor a near match must reach; 0 lists everything the rules
    admit, 0.8 is what ``validate`` warns on.
    """
    from .ontology_loader import SemanticProfile, load_ontology

    hub_root = Path(hub_root)
    results: list[dict[str, Any]] = []
    for domain in domains:
        path = hub_root / "model" / "ontologies" / f"{domain}.ttl"
        if not path.is_file():
            raise FileNotFoundError(f"Domain ontology not found: {path}")
        loaded = load_ontology(
            path,
            catalog_path=catalog_path,
            profile=SemanticProfile.KAIROS_DESIGN,
            degraded=True,
        )
        index = loaded.semantic_index
        candidates = (
            find_candidates(terms_from_index(index), name, limit=limit, min_score=min_score)
            if index is not None
            else []
        )
        results.append(
            {
                "domain": domain,
                "closure_hash": loaded.closure_hash,
                "import_complete": loaded.complete,
                "candidates": [
                    {
                        "uri": c.uri,
                        "name": c.name,
                        "class_uris": list(c.class_uris),
                        "match": c.match,
                        "score": round(c.score, 2),
                    }
                    for c in candidates
                ],
            }
        )
    return {
        "schema_version": 1,
        "name": name,
        "normalised": normalise_term(name),
        "min_score": min_score,
        "domains": results,
    }
