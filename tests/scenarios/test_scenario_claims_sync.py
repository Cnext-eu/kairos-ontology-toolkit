# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for the Slice 2 claim-driven projection authority gate.

These tests exercise the bridge between the Claim Registry and the
projection-facing authored surfaces (domain ``owl:imports`` +
``kairos-ext:silverInclude``) against a *copy* of the acme-hub.

The permanent acme-hub deliberately has **no** ``model/claims/`` directory so
the projector authority gate never fires for the shared scenario projection
tests.  Each test here copies the hub into ``tmp_path``, drops a synthetic
Claim Registry referencing an external (non-acme) imported class, and verifies:

* :func:`evaluate_projection_sync` detects import + silverInclude drift,
* the ``claims-to-silver-ext`` CLI rewrites the surfaces back into sync, and
* ``run_projections`` only succeeds for an in-sync domain while a deliberately
  drifted domain is recorded as an error pointing at ``claims-to-silver-ext``.
"""

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF

from kairos_ontology.core.claim_projection_sync import evaluate_projection_sync
from kairos_ontology.core.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    EvidenceSource,
    Freshness,
    registry_path,
    write_registry,
)
from kairos_ontology.cli.main import cli
from kairos_ontology.core.projections.shared import KAIROS_EXT

from .conftest import HUB_ROOT

# External reference-model class that is NOT in any acme domain namespace.
REF_TRADE_PARTY = "https://refmodel.example/ontology/party#TradeParty"
REF_CARRIER = "https://refmodel.example/ontology/party#Carrier"
REF_PARTY_IMPORT = "https://refmodel.example/ontology/party"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _copy_hub(tmp_path: Path) -> Path:
    """Copy the acme-hub into *tmp_path* and return the working hub root."""
    hub = tmp_path / "acme-hub"
    shutil.copytree(HUB_ROOT, hub)
    return hub


def _model_dirs(hub: Path) -> tuple[Path, Path, Path]:
    """Return (claims_dir, ontologies_dir, extensions_dir) for *hub*."""
    model = hub / "model"
    return model / "claims", model / "ontologies", model / "extensions"


def _approved_imported_claim(*, claim_id: str, class_uri: str) -> Claim:
    return Claim(
        id=claim_id,
        type="class",
        status="approved",
        disposition="claim",
        origin="imported",
        class_uri=class_uri,
        evidence_sources=[
            EvidenceSource(type="source_table", system="crmsystem", table="contacts"),
        ],
    )


def _write_domain_registry(claims_dir: Path, *, domain: str, claim: Claim) -> Path:
    registry = ClaimRegistry(
        domain=domain,
        generated_at="2026-06-15T00:00:00Z",
        algorithm_version=1,
        freshness=Freshness(affinity_sha256="0" * 64),
        coverage=[CoverageSystem(system="crmsystem", tables=[CoverageTable(table="contacts")])],
        claims=[claim],
    )
    path = registry_path(claims_dir, domain)
    write_registry(registry, path)
    return path


def _run_claims_to_silver_ext(hub: Path, *, domains: str | None) -> "object":
    claims_dir, ontologies_dir, extensions_dir = _model_dirs(hub)
    args = [
        "claims-to-silver-ext",
        "--claims-dir",
        str(claims_dir),
        "--ontologies",
        str(ontologies_dir),
        "--extensions",
        str(extensions_dir),
    ]
    if domains is not None:
        args += ["--domains", domains]
    return CliRunner().invoke(cli, args)


# ---------------------------------------------------------------------------
# 1. Drift detection
# ---------------------------------------------------------------------------

def test_evaluate_projection_sync_detects_drift_against_acme_hub(tmp_path):
    hub = _copy_hub(tmp_path)
    claims_dir, ontologies_dir, extensions_dir = _model_dirs(hub)
    _write_domain_registry(
        claims_dir,
        domain="client",
        claim=_approved_imported_claim(
            claim_id="client-trade-party", class_uri=REF_TRADE_PARTY
        ),
    )

    report = evaluate_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=ontologies_dir,
        extensions_dir=extensions_dir,
        domains_filter=["client"],
    )

    assert len(report.domains) == 1
    domain = report.domains[0]
    assert domain.domain == "client"
    assert domain.error is None
    assert REF_PARTY_IMPORT in domain.missing_imports
    assert REF_TRADE_PARTY in domain.missing_includes
    assert not domain.in_sync
    assert report.is_blocking


# ---------------------------------------------------------------------------
# 2. CLI brings the surfaces back into sync
# ---------------------------------------------------------------------------

def test_claims_to_silver_ext_brings_acme_domain_into_sync(tmp_path):
    hub = _copy_hub(tmp_path)
    claims_dir, ontologies_dir, extensions_dir = _model_dirs(hub)
    _write_domain_registry(
        claims_dir,
        domain="client",
        claim=_approved_imported_claim(
            claim_id="client-trade-party", class_uri=REF_TRADE_PARTY
        ),
    )

    result = _run_claims_to_silver_ext(hub, domains="client")
    assert result.exit_code == 0, result.output

    # The ontology now declares the external import.
    onto_graph = Graph()
    onto_graph.parse(ontologies_dir / "client.ttl", format="turtle")
    onto_subj = next(onto_graph.subjects(RDF.type, OWL.Ontology))
    imports = {str(o).rstrip("#/") for o in onto_graph.objects(onto_subj, OWL.imports)}
    assert REF_PARTY_IMPORT in imports

    # The silver extension now includes the imported class.
    ext_graph = Graph()
    ext_graph.parse(extensions_dir / "client-silver-ext.ttl", format="turtle")
    include_val = ext_graph.value(
        subject=URIRef(REF_TRADE_PARTY), predicate=KAIROS_EXT.silverInclude
    )
    assert str(include_val).lower() in {"true", "1"}

    # Local acme annotations survive the rewrite (round-trip preserves them).
    acme_table = ext_graph.value(
        subject=URIRef("https://acme.example/ontology/client#CorporateClient"),
        predicate=KAIROS_EXT.silverTableName,
    )
    assert str(acme_table) == "corporate_client"

    # Re-evaluation reports the domain as in sync.
    report = evaluate_projection_sync(
        claims_dir=claims_dir,
        ontologies_dir=ontologies_dir,
        extensions_dir=extensions_dir,
        domains_filter=["client"],
    )
    assert len(report.domains) == 1
    assert report.domains[0].in_sync
    assert not report.is_blocking


# ---------------------------------------------------------------------------
# 3. Projector authority gate — passes when synced, blocks when drifted
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_silver_projection_gate_passes_in_sync_and_blocks_drift(tmp_path):
    hub = _copy_hub(tmp_path)
    claims_dir, ontologies_dir, extensions_dir = _model_dirs(hub)

    # client: approved imported claim, will be brought into sync via the CLI.
    _write_domain_registry(
        claims_dir,
        domain="client",
        claim=_approved_imported_claim(
            claim_id="client-trade-party", class_uri=REF_TRADE_PARTY
        ),
    )
    # invoice: approved imported claim left deliberately OUT of sync.
    _write_domain_registry(
        claims_dir,
        domain="invoice",
        claim=_approved_imported_claim(
            claim_id="invoice-carrier", class_uri=REF_CARRIER
        ),
    )

    # Only sync the client domain — invoice stays drifted.
    result = _run_claims_to_silver_ext(hub, domains="client")
    assert result.exit_code == 0, result.output

    from kairos_ontology.core.projector import run_projections

    output_path = hub / "output"
    run_projections(
        ontologies_path=ontologies_dir,
        catalog_path=hub / "catalog-v001.xml",  # does not exist — graceful fallback
        output_path=output_path,
        target="silver",
        namespace=None,
    )

    report = json.loads((output_path / "projection-report.json").read_text(encoding="utf-8"))
    projections = {p["domain"]: p for p in report["projections"] if "domain" in p}

    # In-sync domain projects without error.
    assert "client" in projections, report["projections"]
    assert projections["client"]["status"] == "ok", projections["client"]

    # Drifted domain is recorded as an error pointing at the remediation command.
    assert "invoice" in projections, report["projections"]
    assert projections["invoice"]["status"] == "error", projections["invoice"]
    assert "claims-to-silver-ext" in projections["invoice"]["error"]
