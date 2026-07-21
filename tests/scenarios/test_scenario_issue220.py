# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Regression tests for issue #220 — dbt projection on multi-domain hubs.

Two orchestration/authority-gate defects blocked a governed dbt package:

1. **Full-hub projection** rejected shared/package-level artifacts (``README.md``,
   ``dbt_project.yml``, ``models/gold/shared/*``, per-source ``_sources.yml``) that
   different domains legitimately emit, reporting them as collisions.
2. **Domain-only projection** flagged required local peer-domain ``owl:imports`` as
   claim/projection drift, because the hub-domain base set was built only from the
   *selected* (loaded) domain rather than every on-disk hub domain.

These tests run the real ``run_projections`` orchestrator end-to-end.
"""

from __future__ import annotations

import shutil

import pytest

from kairos_ontology.core.claim_registry import (
    ClaimRegistry,
    Freshness,
    registry_path,
    write_registry,
)
from kairos_ontology.core.projector import run_projections

from .conftest import HUB_ROOT

pytestmark = pytest.mark.slow


# ===========================================================================
# Defect 1 — full-hub projection: shared/package artifacts reconciled, not collided
# ===========================================================================

def test_full_hub_dbt_projection_has_no_artifact_collisions(tmp_path):
    """The multi-domain acme-hub (client/invoice/logistics, both client & invoice
    emit gold) must project ``--target dbt`` without raising artifact collisions."""
    hub = tmp_path / "acme-hub"
    shutil.copytree(HUB_ROOT, hub)

    # Must not raise ProjectionRunError("... artifact collisions ...").
    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "catalog-v001.xml",  # absent → graceful fallback
        output_path=hub / "output",
        target="dbt",
    )

    dbt = hub / "output" / "medallion" / "dbt"
    # Package-level files emitted exactly once by the orchestrator.
    assert (dbt / "dbt_project.yml").is_file()
    assert (dbt / "README.md").is_file()
    # Both gold-producing domains succeeded (neither dropped by a collision).
    assert (dbt / "models" / "gold" / "client").is_dir()
    assert (dbt / "models" / "gold" / "invoice").is_dir()


def test_shared_dim_date_emitted_once_and_domain_neutral(tmp_path):
    """The conformed ``dim_date`` is a single shared, domain-neutral artifact in a
    stable ``gold_shared`` schema (identical bytes regardless of emitting domain)."""
    hub = tmp_path / "acme-hub"
    shutil.copytree(HUB_ROOT, hub)

    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=hub / "catalog-v001.xml",
        output_path=hub / "output",
        target="dbt",
    )

    dbt = hub / "output" / "medallion" / "dbt"
    dim_date = dbt / "models" / "gold" / "shared" / "dim_date.sql"
    assert dim_date.is_file()
    content = dim_date.read_text(encoding="utf-8")
    assert "schema='gold_shared'" in content
    # Domain-neutral: no single domain name leaks into the conformed dimension.
    assert "-- Domain: shared" in content
    # No per-domain gold folder duplicate.
    assert not (dbt / "models" / "gold" / "client" / "dim_date.sql").exists()


# ===========================================================================
# Defect 2 — domain-only projection: peer imports are not claim drift
# ===========================================================================

_ALPHA_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix a: <https://acme.example/ontology/alpha#> .

<https://acme.example/ontology/alpha> a owl:Ontology ;
    rdfs:label "Alpha"@en .

a:Widget a owl:Class ;
    rdfs:label "Widget"@en ;
    rdfs:comment "An alpha widget."@en .
"""

# Beta imports the *peer hub domain* alpha (a required local intra-hub import used by
# governed cross-domain relationships) — NOT a claim-driven external reference model.
_BETA_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix b: <https://acme.example/ontology/beta#> .

<https://acme.example/ontology/beta> a owl:Ontology ;
    rdfs:label "Beta"@en ;
    owl:imports <https://acme.example/ontology/alpha> .

b:Gadget a owl:Class ;
    rdfs:label "Gadget"@en ;
    rdfs:comment "A beta gadget."@en .
"""

_BETA_SILVER_EXT = """@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

<https://acme.example/ontology/beta> a
    <http://www.w3.org/2002/07/owl#Ontology> .
"""


def _build_peer_import_hub(root):
    """Two-domain hub where beta imports peer domain alpha, with a beta claims
    registry so the authority gate is active."""
    ontologies = root / "model" / "ontologies"
    extensions = root / "model" / "extensions"
    claims = root / "model" / "claims"
    for d in (ontologies, extensions, claims):
        d.mkdir(parents=True, exist_ok=True)

    (ontologies / "alpha.ttl").write_text(_ALPHA_TTL, encoding="utf-8")
    (ontologies / "beta.ttl").write_text(_BETA_TTL, encoding="utf-8")
    (extensions / "beta-silver-ext.ttl").write_text(_BETA_SILVER_EXT, encoding="utf-8")

    # A minimal, in-sync claims registry for beta: no approved *imported* class claims,
    # so no external imports are expected — the only import (peer alpha) must be
    # recognised as intra-hub, not flagged as drift.
    registry = ClaimRegistry(
        domain="beta",
        generated_at="2026-07-21T00:00:00Z",
        freshness=Freshness(affinity_sha256=""),
        coverage=[],
        claims=[],
    )
    write_registry(registry, registry_path(claims, "beta"))
    return ontologies / "beta.ttl"


def test_domain_only_projection_does_not_flag_peer_import_as_drift(tmp_path):
    """Projecting a single domain that imports a peer hub domain must not raise
    'Claim/projection drift' for that required intra-hub import (issue #220)."""
    hub = tmp_path / "peer-hub"
    beta_ttl = _build_peer_import_hub(hub)

    # At HEAD this raised ProjectionRunError (beta 'extra owl:imports .../alpha').
    run_projections(
        ontologies_path=beta_ttl,
        catalog_path=hub / "catalog-v001.xml",  # absent → graceful fallback
        output_path=hub / "output",
        target="dbt",
    )

    dbt = hub / "output" / "medallion" / "dbt"
    # Projection actually produced output for beta (domain was not dropped).
    assert dbt.is_dir()
    assert any(dbt.rglob("*.sql")) or (dbt / "dbt_project.yml").is_file()
