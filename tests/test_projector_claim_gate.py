# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
import json

from kairos_ontology.alignment_coverage import ALIGNMENT_ALGORITHM_VERSION, compute_affinity_hash
from kairos_ontology.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    EvidenceSource,
    Freshness,
    registry_path,
    write_registry,
)
from kairos_ontology.projector import run_projections


def test_projection_fails_when_claim_surfaces_are_out_of_sync(tmp_path):
    hub = tmp_path / "ontology-hub"
    ontologies = hub / "model" / "ontologies"
    extensions = hub / "model" / "extensions"
    claims = hub / "model" / "claims"
    output = hub / "output"
    ontologies.mkdir(parents=True, exist_ok=True)
    extensions.mkdir(parents=True, exist_ok=True)
    claims.mkdir(parents=True, exist_ok=True)

    (ontologies / "party.ttl").write_text(
        """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dom: <https://example.org/domain/party#> .

<https://example.org/domain/party> a owl:Ontology ;
    rdfs:label "Party"@en .

dom:Party a owl:Class ;
    rdfs:label "Party"@en ;
    rdfs:comment "Party entity."@en .
""",
        encoding="utf-8",
    )
    (extensions / "party-silver-ext.ttl").write_text(
        """@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
<https://example.org/domain/party> kairos-ext:silverIncludeImports true .
""",
        encoding="utf-8",
    )

    registry = ClaimRegistry(
        domain="party",
        generated_at="2026-06-15T00:00:00Z",
        algorithm_version=ALIGNMENT_ALGORITHM_VERSION,
        freshness=Freshness(affinity_sha256=compute_affinity_hash({("crm", "account")})),
        coverage=[CoverageSystem(system="crm", tables=[CoverageTable(table="account")])],
        claims=[
            Claim(
                id="party-trade-party",
                type="class",
                status="approved",
                disposition="claim",
                origin="imported",
                class_uri="https://example.org/ref/party#TradeParty",
                evidence_sources=[
                    EvidenceSource(type="source_table", system="crm", table="account")
                ],
            )
        ],
    )
    write_registry(registry, registry_path(claims, "party"))

    run_projections(
        ontologies_path=ontologies,
        catalog_path=hub / "catalog-v001.xml",
        output_path=output,
        target="silver",
        namespace=None,
    )

    report_path = output / "projection-report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    errors = [
        p for p in payload["projections"]
        if p.get("target") == "silver" and p.get("domain") == "party" and p.get("status") == "error"
    ]
    assert errors, payload
    assert "claims-to-silver-ext" in errors[0].get("error", "")
