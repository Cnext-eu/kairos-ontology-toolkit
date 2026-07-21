# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for the deterministic lifecycle gate (DD-101) over acme-hub.

Complements the synthetic-hub unit tests in ``tests/test_lifecycle_gate.py`` by
proving the composed gate behaves correctly against the real, multi-domain,
multi-pattern acme-hub fixture (split/discriminator mappings, several source
systems) rather than only a minimal single-class synthetic hub.

The permanent acme-hub deliberately has no ``model/claims/`` directory (mirrors
``tests/scenarios/test_scenario_claims_sync.py``), so each test copies the hub
into ``tmp_path`` before dropping a synthetic Claim Registry.
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

from kairos_ontology.core.lifecycle_gate import evaluate_lifecycle_gate

from .conftest import HUB_ROOT

CLIENT_CLASS_URI = "https://acme.example/ontology/client#Client"
PROSPECT_URI = "https://acme.example/ontology/client#Prospect"

PROSPECT_TTL_APPEND = textwrap.dedent(
    """\

    # ---------------------------------------------------------------------------
    # Injected for the DD-101 lifecycle-gate scenario: approved, no bronze mapping.
    # ---------------------------------------------------------------------------
    acme:Prospect a owl:Class ;
        rdfs:label "Prospect" ;
        rdfs:comment "A pre-sales lead — approved but not yet bound to any source." .
    """
)


def _copy_hub(tmp_path: Path) -> Path:
    hub = tmp_path / "acme-hub"
    shutil.copytree(HUB_ROOT, hub)
    return hub


def _write_client_claims(hub: Path, claims_yaml: str) -> None:
    claims_dir = hub / "model" / "claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / "client-claims.yaml").write_text(claims_yaml, encoding="utf-8")


def _evaluate(hub: Path):
    return evaluate_lifecycle_gate(
        hub_root=hub,
        claims_dir=hub / "model" / "claims",
        analysis_dir=hub / "integration" / "sources" / "_analysis",
        sources_dir=hub / "integration" / "sources",
        mappings_dir=hub / "model" / "mappings",
        ontologies_dir=hub / "model" / "ontologies",
        extensions_dir=hub / "model" / "extensions",
    )


def test_gate_over_pristine_acme_hub_has_no_claims_authority(tmp_path):
    """No `model/claims/` -> every domain is vacuously release-eligible."""
    hub = _copy_hub(tmp_path)
    report = _evaluate(hub)

    assert report.release == ()
    assert report.claims.proposed_counts == {}
    assert report.claims.is_blocking is False
    assert report.projection_sync.is_blocking is False
    assert report.is_blocking is False


def test_gate_detects_injected_approved_unbound_claim(tmp_path):
    """An approved claim for a brand-new, unmapped class blocks release (DD-096)."""
    hub = _copy_hub(tmp_path)
    client_ttl = hub / "model" / "ontologies" / "client.ttl"
    client_ttl.write_text(
        client_ttl.read_text(encoding="utf-8") + PROSPECT_TTL_APPEND, encoding="utf-8"
    )
    _write_client_claims(
        hub,
        textwrap.dedent(
            f"""\
            domain: client
            schema_version: 1
            claims:
              - id: client-prospect
                type: class
                class_uri: {PROSPECT_URI}
                origin: authored
                status: approved
                disposition: claim
            """
        ),
    )

    report = _evaluate(hub)

    assert len(report.release) == 1
    fact = report.release[0]
    assert fact.domain == "client"
    assert fact.aspirational_classes == ("Prospect",)
    assert fact.reasons["Prospect"] == "approved claim, no bronze mapping (aspirational)"
    assert fact.release_eligible is False
    assert report.release_blocking_domains == ("client",)
    assert report.is_blocking is True


def test_gate_recognizes_real_split_mapped_class_as_bound(tmp_path):
    """An approved claim for an already-mapped class is bound.

    ``Client`` is the S3 discriminator **parent** absorbing acme-hub's real
    ``adminpulse-to-client.ttl`` split mapping (one bronze table -> 3 subtypes
    folded into their parent, DD-073) — a materially different, non-trivial
    binding path than a simple direct 1:1 mapping, proving
    ``analyze_domain_from_hub`` agrees with the dbt projector's own
    ``compute_source_bindings``/folding logic on a realistic hub. The folded
    subtypes themselves (``CorporateClient`` et al.) are ``FOLDED``, not
    ``BOUND`` — they have no separate physical model of their own.
    """
    hub = _copy_hub(tmp_path)
    _write_client_claims(
        hub,
        textwrap.dedent(
            f"""\
            domain: client
            schema_version: 1
            claims:
              - id: client-base
                type: class
                class_uri: {CLIENT_CLASS_URI}
                origin: authored
                status: approved
                disposition: claim
            """
        ),
    )

    report = _evaluate(hub)

    fact = report.release[0]
    assert fact.domain == "client"
    assert fact.aspirational_classes == ()
    assert "Client" in fact.bound_classes
    assert fact.release_eligible is True
    assert report.release_blocking_domains == ()


def test_gate_proposed_claim_on_real_hub_is_not_release_blocking(tmp_path):
    """A `proposed` (not yet approved) claim never blocks release (DD-094)."""
    hub = _copy_hub(tmp_path)
    client_ttl = hub / "model" / "ontologies" / "client.ttl"
    client_ttl.write_text(
        client_ttl.read_text(encoding="utf-8") + PROSPECT_TTL_APPEND, encoding="utf-8"
    )
    _write_client_claims(
        hub,
        textwrap.dedent(
            f"""\
            domain: client
            schema_version: 1
            claims:
              - id: client-prospect
                type: class
                class_uri: {PROSPECT_URI}
                origin: authored
                status: proposed
                disposition: claim
            """
        ),
    )

    report = _evaluate(hub)

    fact = report.release[0]
    assert fact.aspirational_classes == ()
    assert fact.release_eligible is True
    assert report.is_blocking is False
