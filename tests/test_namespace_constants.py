# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Every namespace constant must match real data (DD-172).

``projections/shared.py`` bound ``http://schema.org/`` while every shipped reference
model binds ``https://schema.org/``. The constant therefore matched nothing, and
``schema:domainIncludes`` — the mechanism ``kairos-design-domain`` Gate 5 tells authors
to rely on — was invisible to the silver/dbt projectors, ``validate-mapping`` and source
analysis alike.

Nothing failed. An unmatched optional predicate is indistinguishable from an absent one,
so the whole REUSABLE property family simply never appeared and every consumer reported
truthfully on what it had been shown.

This test is the structural guard: a namespace constant that matches nothing in the
shipped reference models is either wrong or dead, and both are worth knowing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REFMODEL_ROOTS = (
    Path(__file__).resolve().parents[1]
    / ".venv"
    / "Lib"
    / "site-packages"
    / "kairos_ontology_referencemodels"
    / "ontology-reference-models",
)


def _reference_model_text() -> str:
    """Concatenate the shipped reference-model TTL, or skip when unavailable."""
    for root in _REFMODEL_ROOTS:
        if root.is_dir():
            chunks = []
            for path in sorted(root.rglob("*.ttl")):
                try:
                    chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    continue
            if chunks:
                return "\n".join(chunks)
    pytest.skip("reference models not installed in this environment")


def test_domain_includes_matches_the_shipped_models() -> None:
    """The specific regression: both scheme spellings must be accepted."""
    from kairos_ontology.core.projections.shared import DOMAIN_INCLUDES_PREDICATES

    text = _reference_model_text()
    bound = {
        line.split("<", 1)[1].split(">", 1)[0]
        for line in text.splitlines()
        if line.strip().startswith("@prefix schema:")
    }
    assert bound, "no reference model binds a schema: prefix — update this guard"
    for namespace in bound:
        expected = f"{namespace}domainIncludes"
        assert expected in {str(p) for p in DOMAIN_INCLUDES_PREDICATES}, (
            f"reference models bind schema: as {namespace!r}, which no accepted "
            "domainIncludes predicate matches — the predicate would silently never fire"
        )


def test_every_prefix_the_models_bind_is_reachable_by_some_constant() -> None:
    """A constant matching nothing is either wrong or dead.

    Scoped to namespaces the toolkit actually declares a constant for: the reference
    models bind many vocabularies the toolkit never reads, and demanding a constant for
    each would be noise. What must not happen is a *declared* constant silently missing
    the data it was written for.
    """
    import re

    from kairos_ontology.core.projections import shared

    text = _reference_model_text()
    bound_namespaces = set(re.findall(r"@prefix\s+[\w-]*:\s+<([^>]+)>", text))

    # Constants this module declares, by the vocabulary host they target.
    declared = {
        str(value)
        for name, value in vars(shared).items()
        if name.isupper() and hasattr(value, "__str__") and str(value).startswith("http")
    }
    schema_constants = {ns for ns in declared if "schema.org" in ns}
    schema_bound = {ns for ns in bound_namespaces if "schema.org" in ns}

    if schema_bound:
        assert schema_constants & schema_bound, (
            f"models bind {sorted(schema_bound)} but the toolkit only declares "
            f"{sorted(schema_constants)} — the constant cannot match any triple"
        )


def test_a_reusable_property_is_actually_reachable_end_to_end() -> None:
    """The canary: bsp/party declares its address family the REUSABLE way.

    If this regresses, `domainIncludes` has stopped resolving again and every consumer
    of effective_domain_classes is quietly poorer for it.
    """
    root = next((r for r in _REFMODEL_ROOTS if r.is_dir()), None)
    if root is None:
        pytest.skip("reference models not installed")
    party = root / "derived-ontologies" / "BSP" / "current" / "party" / "party.ttl"
    if not party.is_file():
        pytest.skip("bsp/party module not present in this reference-model version")

    from rdflib import Graph, URIRef

    from kairos_ontology.core.projections.shared import effective_domain_classes

    graph = Graph()
    graph.parse(party, format="turtle")
    prop = URIRef("https://www.kairosflow.ai/ont/bsp/party#hasBillingAddress")
    classes = {str(c) for c in effective_domain_classes(graph, prop)}
    assert "https://www.kairosflow.ai/ont/bsp/party#TradeParty" in classes
