# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
import json
from pathlib import Path

import kairos_ontology.core.projector as projector
import pytest
from rdflib import URIRef
from rdflib.namespace import OWL, RDF
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
from kairos_ontology.core.claim_projection_sync import (
    apply_projection_sync,
    evaluate_projection_sync,
)
from kairos_ontology.core.projector import ProjectionRunError, run_projections


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
        calls.append(
            (
                ontology_name,
                kwargs["projection_ext_path"],
                kwargs["gold_ext_path"],
            )
        )
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


def _write_transitive_module_hub(tmp_path: Path) -> tuple[Path, Path, Path]:
    hub = tmp_path / "ontology-hub"
    model = hub / "model"
    claims = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    for path in (claims, ontologies, extensions):
        path.mkdir(parents=True, exist_ok=True)

    module_a = "https://example.org/reference/module-a"
    module_b = "https://example.org/reference/module-b"
    module_a_class = module_a + "#DirectClass"
    modules = hub / "reference-models" / "modules"
    blueprint = hub / "reference-models" / "accelerator-packs" / "generic" / "client-hub-blueprint"
    modules.mkdir(parents=True)
    blueprint.mkdir(parents=True)
    (modules / "module-b.ttl").write_text(
        f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<{module_b}> a owl:Ontology ; owl:versionInfo "1.0" .
<{module_b}#TransitiveClass> a owl:Class .
""",
        encoding="utf-8",
    )
    (modules / "module-a.ttl").write_text(
        f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<{module_a}> a owl:Ontology ;
    owl:versionInfo "1.0" ;
    owl:imports <{module_b}> .
<{module_a_class}> a owl:Class .
""",
        encoding="utf-8",
    )
    (blueprint / "data-domains.yaml").write_text(
        f"""\
schema_version: "2.0"
module_profiles:
  - id: module-a
    ontology_iri: {module_a}
    version_pin: "1.0"
    term_namespaces: [{module_a}#]
    accepted_transitive_dependencies: [{module_b}]
  - id: module-b
    ontology_iri: {module_b}
    version_pin: "1.0"
    term_namespaces: [{module_b}#]
groups: []
""",
        encoding="utf-8",
    )
    catalog = hub / "catalog-v001.xml"
    catalog.write_text(
        f"""\
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="{module_a}" uri="reference-models/modules/module-a.ttl"/>
  <uri name="{module_b}" uri="reference-models/modules/module-b.ttl"/>
</catalog>
""",
        encoding="utf-8",
    )
    ontology_file = ontologies / "booking.ttl"
    ontology_file.write_text(
        """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix booking: <https://example.org/domain/booking#> .
<https://example.org/domain/booking> a owl:Ontology ;
    rdfs:label "Booking" .
booking:Booking a owl:Class ;
    rdfs:label "Booking" ;
    rdfs:comment "A booking." .
booking:usesTransitiveTerm a owl:ObjectProperty ;
    rdfs:domain booking:Booking ;
    rdfs:range <https://example.org/reference/module-b#TransitiveClass> .
""",
        encoding="utf-8",
    )
    (extensions / "booking-silver-ext.ttl").write_text(
        "@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .\n",
        encoding="utf-8",
    )
    write_registry(
        ClaimRegistry(
            domain="booking",
            claims=[
                Claim(
                    id="booking-direct-class",
                    type="class",
                    status="approved",
                    disposition="claim",
                    origin="imported",
                    class_uri=module_a_class,
                )
            ],
        ),
        claims / "booking-claims.yaml",
    )
    synced = apply_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
        domains_filter=["booking"],
        scaffold_missing=False,
        ref_models_dir=hub / "reference-models",
        catalog_path=catalog,
        accelerator="generic",
    )
    assert not synced.is_blocking
    return hub, ontology_file, catalog


def test_projector_module_scope_uses_direct_authored_imports(tmp_path, monkeypatch):
    hub, ontology_file, catalog = _write_transitive_module_hub(tmp_path)
    claims = hub / "model" / "claims"
    ontologies = hub / "model" / "ontologies"
    extensions = hub / "model" / "extensions"
    ref_models = hub / "reference-models"
    module_a = "https://example.org/reference/module-a"
    module_b = "https://example.org/reference/module-b"

    import kairos_ontology.core.claim_projection_sync as claim_sync
    import kairos_ontology.core.reference_modules as reference_modules

    real_builder = reference_modules.build_reference_module_context
    observed_contexts = []

    def recording_builder(*args, **kwargs):
        context = real_builder(*args, **kwargs)
        observed_contexts.append(
            (
                set(kwargs["imported_ontology_iris"]),
                [module.profile.id for module in context.modules],
            )
        )
        return context

    monkeypatch.setattr(claim_sync, "build_reference_module_context", recording_builder)
    monkeypatch.setattr(
        reference_modules,
        "build_reference_module_context",
        recording_builder,
    )
    projected_graphs = []

    def fake_run_projection(*args, **kwargs):
        projected_graphs.append(args[1])
        return {"booking.json": "{}"}

    monkeypatch.setattr(projector, "_run_projection", fake_run_projection)

    sync_report = evaluate_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
        domains_filter=["booking"],
        ref_models_dir=ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )
    assert not sync_report.is_blocking

    run_projections(
        ontologies_path=ontology_file,
        catalog_path=catalog,
        output_path=hub / "output",
        target="silver",
        namespace=None,
        ref_models_dir=ref_models,
        accelerator="generic",
    )

    assert observed_contexts == [
        ({module_a}, ["module-a"]),
        ({module_a}, ["module-a"]),
    ]
    assert projected_graphs
    assert (
        URIRef(module_b + "#TransitiveClass"),
        RDF.type,
        OWL.Class,
    ) in projected_graphs[0]
    assert f"owl:imports <{module_b}>" not in ontology_file.read_text(encoding="utf-8")

    ontology_file.write_text(
        "\n".join(
            line
            for line in ontology_file.read_text(encoding="utf-8").splitlines()
            if module_a not in line
        )
        + "\n",
        encoding="utf-8",
    )
    missing_report = evaluate_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
        domains_filter=["booking"],
        ref_models_dir=ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )
    assert missing_report.domains[0].missing_imports == [module_a]

    with pytest.raises(ProjectionRunError):
        run_projections(
            ontologies_path=ontology_file,
            catalog_path=catalog,
            output_path=hub / "missing-output",
            target="silver",
            namespace=None,
            ref_models_dir=ref_models,
            accelerator="generic",
        )
    errors = _projection_errors(
        hub / "missing-output",
        target="silver",
        domain="booking",
    )
    assert len(errors) == 1
    assert f"missing owl:imports {module_a}" in errors[0]["error"]
    assert module_b not in errors[0]["error"]


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

    with pytest.raises(ProjectionRunError, match="silver projection failed"):
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
        p
        for p in payload["projections"]
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
    assert calls == [("party", silver_ext, gold_ext)]


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
    assert {domain for domain, _, _ in calls} == {"invoice", "party"}
    assert all(
        silver.name == f"{domain}-silver-ext.ttl" and gold.name == f"{domain}-gold-ext.ttl"
        for domain, silver, gold in calls
    )


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
    assert not any(domain == "party" for domain, _, _ in calls)
