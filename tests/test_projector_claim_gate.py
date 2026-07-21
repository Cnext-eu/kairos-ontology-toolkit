# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
import json
from pathlib import Path

import kairos_ontology.core.projector as projector
from kairos_ontology.core.completeness_model import (
    ALIGNMENT_ALGORITHM_VERSION,
    compute_affinity_hash,
)
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
from kairos_ontology.core.claim_projection_sync import apply_projection_sync
from kairos_ontology.core.projector import run_projections


def _write_synced_claim_domain(hub: Path, domain: str) -> tuple[Path, Path]:
    ontologies = hub / "model" / "ontologies"
    extensions = hub / "model" / "extensions"
    claims = hub / "model" / "claims"
    ontologies.mkdir(parents=True, exist_ok=True)
    extensions.mkdir(parents=True, exist_ok=True)
    claims.mkdir(parents=True, exist_ok=True)

    class_name = f"{domain.title().replace('_', '')}Imported"
    class_uri = f"https://example.org/ref/{domain}#{class_name}"
    local_class = f"{domain.title().replace('_', '')}Local"
    (ontologies / f"{domain}.ttl").write_text(
        f"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dom: <https://example.org/domain/{domain}#> .

<https://example.org/domain/{domain}> a owl:Ontology ;
    rdfs:label "{domain.title()}"@en .

dom:{local_class} a owl:Class ;
    rdfs:label "{local_class}"@en ;
    rdfs:comment "{local_class} entity."@en .
""",
        encoding="utf-8",
    )
    (extensions / f"{domain}-silver-ext.ttl").write_text(
        """@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
""",
        encoding="utf-8",
    )
    (extensions / f"{domain}-gold-ext.ttl").write_text(
        """@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
""",
        encoding="utf-8",
    )

    registry = ClaimRegistry(
        domain=domain,
        generated_at="2026-06-15T00:00:00Z",
        algorithm_version=ALIGNMENT_ALGORITHM_VERSION,
        freshness=Freshness(affinity_sha256=compute_affinity_hash({("crm", domain)})),
        coverage=[CoverageSystem(system="crm", tables=[CoverageTable(table=domain)])],
        claims=[
            Claim(
                id=f"{domain}-imported",
                type="class",
                status="approved",
                disposition="claim",
                origin="imported",
                class_uri=class_uri,
                evidence_sources=[EvidenceSource(type="source_table", system="crm", table=domain)],
            )
        ],
    )
    write_registry(registry, registry_path(claims, domain))
    sync_report = apply_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
        scaffold_missing=False,
    )
    assert not sync_report.is_blocking
    return extensions / f"{domain}-silver-ext.ttl", extensions / f"{domain}-gold-ext.ttl"


def _stub_powerbi_projection(monkeypatch):
    calls = []

    def fake_run_projection(*args, **kwargs):
        ontology_name = args[6]
        calls.append((ontology_name, kwargs["projection_ext_path"]))
        return {f"{ontology_name}.json": "{}"}

    monkeypatch.setattr(projector, "_run_projection", fake_run_projection)
    return calls


def _projection_errors(output, *, target: str, domain: str):
    payload = json.loads((output / "projection-report.json").read_text(encoding="utf-8"))
    return [
        p
        for p in payload["projections"]
        if p.get("target") == target and p.get("domain") == domain and p.get("status") == "error"
    ]


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


def test_powerbi_claim_gate_uses_silver_ext_but_projection_uses_gold_ext(tmp_path, monkeypatch):
    hub = tmp_path / "ontology-hub"
    silver_ext, gold_ext = _write_synced_claim_domain(hub, "party")
    output = hub / "output"
    calls = _stub_powerbi_projection(monkeypatch)

    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=None,
        output_path=output,
        target="powerbi",
        namespace=None,
        degraded=True,
    )

    assert _projection_errors(output, target="powerbi", domain="party") == []
    assert silver_ext.exists()
    assert calls == [("party", gold_ext)]


def test_powerbi_claim_gate_uses_each_domains_exact_silver_ext(tmp_path, monkeypatch):
    hub = tmp_path / "ontology-hub"
    _write_synced_claim_domain(hub, "invoice")
    _write_synced_claim_domain(hub, "party")
    output = hub / "output"
    calls = _stub_powerbi_projection(monkeypatch)

    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=None,
        output_path=output,
        target="powerbi",
        namespace=None,
        degraded=True,
    )

    assert _projection_errors(output, target="powerbi", domain="invoice") == []
    assert _projection_errors(output, target="powerbi", domain="party") == []
    assert {domain for domain, _ in calls} == {"invoice", "party"}
    assert all(path.name == f"{domain}-gold-ext.ttl" for domain, path in calls)


def test_powerbi_claim_gate_does_not_borrow_peer_silver_ext(tmp_path, monkeypatch):
    hub = tmp_path / "ontology-hub"
    silver_ext, _gold_ext = _write_synced_claim_domain(hub, "party")
    _write_synced_claim_domain(hub, "other")
    silver_ext.unlink()
    output = hub / "output"
    calls = _stub_powerbi_projection(monkeypatch)

    run_projections(
        ontologies_path=hub / "model" / "ontologies",
        catalog_path=None,
        output_path=output,
        target="powerbi",
        namespace=None,
        degraded=True,
    )

    errors = _projection_errors(output, target="powerbi", domain="party")
    assert errors
    assert "missing extension file" in errors[0].get("error", "")
    assert "party-silver-ext.ttl" in errors[0].get("error", "")
    assert "other-silver-ext.ttl" not in errors[0].get("error", "")
    assert ("party", hub / "model" / "extensions" / "party-gold-ext.ttl") not in calls
