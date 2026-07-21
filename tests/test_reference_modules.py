# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for managed reference-module activation (CR-TK-01/02)."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner
from rdflib import Graph

from kairos_ontology.cli.main import cli
from kairos_ontology.core.claim_projection_sync import apply_projection_sync
from kairos_ontology.core.claim_registry import (
    Claim,
    ClaimRegistry,
    registry_path,
    write_registry,
)
from kairos_ontology.core.reference_modules import (
    build_managed_import_plan,
    build_reference_module_context,
    dump_activation_inventory,
    load_accelerator_module_config,
)
from kairos_ontology.core.validator import run_validation, validate_managed_imports
from kairos_ontology.core.projector import run_projections


MODULE_IRI = "https://example.org/reference/orders"
TERM_NS = MODULE_IRI + "#"


def _write_reference_pack(tmp_path):
    ref_models = tmp_path / "reference-models"
    blueprint = (
        ref_models
        / "accelerator-packs"
        / "generic"
        / "client-hub-blueprint"
    )
    blueprint.mkdir(parents=True)
    module = ref_models / "modules" / "orders.ttl"
    module.parent.mkdir()
    module.write_text(
        f"""\
@prefix ex: <{TERM_NS}> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<{MODULE_IRI}> a owl:Ontology ; owl:versionInfo "2.1.0" .
ex:Order a owl:Class .
ex:SpecialOrder a owl:Class ; rdfs:subClassOf ex:Order .
ex:InternalOrder a owl:Class ; rdfs:subClassOf ex:Order .
ex:orderNumber a owl:DatatypeProperty ; rdfs:domain ex:Order .
ex:relatedOrder a owl:ObjectProperty ; rdfs:domain ex:Order ; rdfs:range ex:Order .
""",
        encoding="utf-8",
    )
    (blueprint / "data-domains.yaml").write_text(
        f"""\
schema_version: "2.0"
module_profiles:
  - id: orders
    ontology_iri: {MODULE_IRI}
    catalog_uri: {TERM_NS}
    version_pin: 2.1.0
    term_namespaces: [{TERM_NS}]
    root_classes: [{TERM_NS}Order]
    descendants:
      policy: all
      exclude: [{TERM_NS}InternalOrder]
    projection:
      allowlist: [{TERM_NS}Order]
    default_annotation_sources: [defaults/orders.ttl]
    local_extension_namespaces: [https://example.org/hub/orders#]
groups:
  - id: operations
    domains:
      - id: orders
        imports:
          - profile: orders
""",
        encoding="utf-8",
    )
    defaults = blueprint / "defaults" / "orders.ttl"
    defaults.parent.mkdir()
    defaults.write_text(
        f"""\
@prefix ex: <{TERM_NS}> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
ex:Order kairos-ext:scdType "2" .
""",
        encoding="utf-8",
    )
    catalog = ref_models / "catalog-v001.xml"
    catalog.write_text(
        f"""\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="{TERM_NS}" uri="modules/orders.ttl"/>
  <uri name="{MODULE_IRI}" uri="modules/orders.ttl"/>
</catalog>
""",
        encoding="utf-8",
    )
    return ref_models, catalog


def _registry() -> ClaimRegistry:
    return ClaimRegistry(
        domain="orders",
        claims=[
            Claim(
                id="order-class",
                type="class",
                origin="imported",
                status="approved",
                disposition="claim",
                class_uri=TERM_NS + "SpecialOrder",
            ),
            Claim(
                id="order-number",
                type="property",
                origin="imported",
                status="approved",
                disposition="claim",
                property_uri=TERM_NS + "orderNumber",
            ),
            Claim(
                id="related-order",
                type="relationship",
                origin="imported",
                status="approved",
                disposition="specialize",
                property_uri=TERM_NS + "relatedOrder",
            ),
        ],
    )


def _domain_graph(*, imported: bool) -> Graph:
    import_line = f"owl:imports <{MODULE_IRI}> ;" if imported else ""
    graph = Graph()
    graph.parse(
        data=f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix hub: <https://example.org/hub/orders#> .
<https://example.org/hub/orders> a owl:Ontology ;
    {import_line}
    rdfs:label "Orders" .
hub:LocalOrder a owl:Class ; rdfs:subClassOf <{TERM_NS}SpecialOrder> .
""",
        format="turtle",
    )
    return graph


def test_typed_profile_resolves_document_iri_and_version(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)

    config = load_accelerator_module_config(ref_models, "generic")
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )

    assert config.profiles[0].ontology_iri == MODULE_IRI
    assert config.profiles[0].version_pin == "2.1.0"
    assert context.modules[0].ontology_iri == MODULE_IRI
    assert context.modules[0].ontology_version == "2.1.0"
    assert context.diagnostics == ()


def test_profile_rejects_term_namespace_as_ontology_iri(tmp_path):
    ref_models, _catalog = _write_reference_pack(tmp_path)
    path = (
        ref_models
        / "accelerator-packs"
        / "generic"
        / "client-hub-blueprint"
        / "data-domains.yaml"
    )
    path.write_text(
        f"""\
module_profiles:
  - id: invalid
    ontology_iri: {TERM_NS}
    version_pin: 1.0
groups: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="document IRI"):
        load_accelerator_module_config(ref_models, "generic")


def test_domain_activation_unions_profiles_across_groups(tmp_path):
    ref_models, _catalog = _write_reference_pack(tmp_path)
    path = (
        ref_models
        / "accelerator-packs"
        / "generic"
        / "client-hub-blueprint"
        / "data-domains.yaml"
    )
    path.write_text(
        f"""\
module_profiles:
  - id: first
    ontology_iri: {MODULE_IRI}
    version_pin: 2.1.0
  - id: second
    ontology_iri: https://example.org/reference/second
    version_pin: 1.0
groups:
  - id: first-group
    domains:
      - id: orders
        imports: [{{profile: first}}]
  - id: second-group
    domains:
      - id: orders
        imports: [{{profile: second}}]
""",
        encoding="utf-8",
    )

    config = load_accelerator_module_config(ref_models, "generic")

    assert config.activation("orders").module_ids == ("first", "second")


def test_version_pin_mismatch_is_structured_error(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    path = (
        ref_models
        / "accelerator-packs"
        / "generic"
        / "client-hub-blueprint"
        / "data-domains.yaml"
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace("version_pin: 2.1.0", "version_pin: 9.0"),
        encoding="utf-8",
    )

    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )

    assert context.modules == ()
    assert context.diagnostics[0].code == "module_version_mismatch"
    assert context.diagnostics[0].expected_ontology_iri == MODULE_IRI


def test_plan_unions_domain_profile_and_all_imported_claim_term_types(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )

    plan = build_managed_import_plan(
        _registry(),
        domain="orders",
        context=context,
        ontology_graph=_domain_graph(imported=False),
    )

    assert plan.expected_imports == (MODULE_IRI,)
    requirement = plan.requirements[0]
    assert set(requirement.term_uris) == {
        TERM_NS + "SpecialOrder",
        TERM_NS + "orderNumber",
        TERM_NS + "relatedOrder",
    }
    assert "data-domain:orders" in requirement.reasons
    assert set(plan.selected_class_uris) == {
        TERM_NS + "Order",
        TERM_NS + "SpecialOrder",
    }
    missing = [item for item in plan.diagnostics if item.code == "missing_managed_import"]
    assert {item.term_uri for item in missing} == set(requirement.term_uris)
    assert all(item.expected_ontology_iri == MODULE_IRI for item in missing)
    assert all(item.managed_source == "orders" for item in missing)


def test_local_claim_never_creates_an_external_import_requirement():
    ontology_iri = "https://example.org/hub/shipment"
    registry = ClaimRegistry(
        domain="shipment",
        claims=[
            Claim(
                id="shipment",
                type="class",
                status="approved",
                disposition="claim",
                class_uri=ontology_iri + "#Shipment",
            )
        ],
    )

    plan = build_managed_import_plan(
        registry,
        domain="shipment",
        local_ontology_iri=ontology_iri,
    )

    assert plan.expected_imports == ()
    assert plan.selected_class_uris == ()


def test_authored_external_term_is_validated_without_a_claim(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )

    plan = build_managed_import_plan(
        ClaimRegistry(domain="orders"),
        domain="orders",
        context=context,
        ontology_graph=_domain_graph(imported=False),
    )

    assert TERM_NS + "SpecialOrder" in plan.requirements[0].term_uris
    diagnostic = next(
        item
        for item in plan.diagnostics
        if item.term_uri == TERM_NS + "SpecialOrder"
    )
    assert diagnostic.expected_ontology_iri == MODULE_IRI
    assert diagnostic.managed_source == "orders"


def test_explicitly_accepted_transitive_dependency_uses_root_import(tmp_path):
    ref_models = tmp_path / "reference-models"
    blueprint = (
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint"
    )
    modules = ref_models / "modules"
    blueprint.mkdir(parents=True)
    modules.mkdir()
    dependency_iri = "https://example.org/reference/base"
    dependency_term = dependency_iri + "#Base"
    root_iri = "https://example.org/reference/root"
    modules.joinpath("base.ttl").write_text(
        f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<{dependency_iri}> a owl:Ontology ; owl:versionInfo "1.0" .
<{dependency_term}> a owl:Class .
""",
        encoding="utf-8",
    )
    modules.joinpath("root.ttl").write_text(
        f"""\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<{root_iri}> a owl:Ontology ;
    owl:versionInfo "1.0" ;
    owl:imports <{dependency_iri}> .
""",
        encoding="utf-8",
    )
    blueprint.joinpath("data-domains.yaml").write_text(
        f"""\
module_profiles:
  - id: root
    ontology_iri: {root_iri}
    version_pin: 1.0
    accepted_transitive_dependencies: [{dependency_iri}]
groups:
  - id: generic
    domains:
      - id: domain
        imports: [{{profile: root}}]
""",
        encoding="utf-8",
    )
    catalog = ref_models / "catalog-v001.xml"
    catalog.write_text(
        f"""\
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="{root_iri}" uri="modules/root.ttl"/>
  <uri name="{dependency_iri}" uri="modules/base.ttl"/>
</catalog>
""",
        encoding="utf-8",
    )
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )
    registry = ClaimRegistry(
        domain="domain",
        claims=[
            Claim(
                id="base",
                type="class",
                origin="imported",
                status="approved",
                disposition="claim",
                class_uri=dependency_term,
            )
        ],
    )

    plan = build_managed_import_plan(registry, domain="domain", context=context)

    assert plan.expected_imports == (root_iri,)
    transitive = next(item for item in plan.requirements if item.term_uris)
    assert transitive.expected_ontology_iri == dependency_iri
    assert transitive.accepted_transitive is True


def test_activation_inventory_is_deterministic_and_does_not_copy_definitions(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )
    plan = build_managed_import_plan(_registry(), domain="orders", context=context)

    first = dump_activation_inventory(plan.activation_inventory)
    second = dump_activation_inventory(plan.activation_inventory)
    payload = json.loads(first)
    terms = {item["uri"]: item for item in payload["terms"]}

    assert first == second
    assert "generated_at" not in payload
    assert payload["modules"][0]["ontology_iri"] == MODULE_IRI
    assert payload["modules"][0]["default_annotation_sources"] == [
        "defaults/orders.ttl"
    ]
    assert payload["modules"][0]["local_extension_namespaces"] == [
        "https://example.org/hub/orders#"
    ]
    assert terms[TERM_NS + "Order"]["selection"] == "selected"
    assert terms[TERM_NS + "SpecialOrder"]["selection"] == "selected"
    assert terms[TERM_NS + "InternalOrder"]["availability"] == "excluded"
    assert terms[TERM_NS + "orderNumber"]["inherited"] is True
    assert "definitions" not in payload


def test_invalid_profile_default_annotations_are_blocking(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    defaults = (
        ref_models
        / "accelerator-packs"
        / "generic"
        / "client-hub-blueprint"
        / "defaults"
        / "orders.ttl"
    )
    defaults.write_text("not valid turtle [", encoding="utf-8")

    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )

    assert context.modules == ()
    assert context.diagnostics[0].code == "module_default_annotations_invalid"


def test_legacy_data_domain_import_remains_supported(tmp_path):
    ref_models = tmp_path / "reference-models"
    blueprint = (
        ref_models
        / "accelerator-packs"
        / "legacy"
        / "client-hub-blueprint"
    )
    blueprint.mkdir(parents=True)
    blueprint.joinpath("data-domains.yaml").write_text(
        f"""\
groups:
  - id: operations
    domains:
      - id: orders
        imports:
          - uri: {TERM_NS}
            module: Orders
""",
        encoding="utf-8",
    )

    config = load_accelerator_module_config(ref_models, "legacy")

    assert config.profiles[0].legacy
    assert config.profiles[0].ontology_iri == MODULE_IRI
    assert config.profiles[0].version_pin is None


def test_projection_sync_uses_profiles_preserves_authored_text_and_removes_stale(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )
    model = tmp_path / "hub" / "model"
    claims = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    claims.mkdir(parents=True)
    ontologies.mkdir()
    extensions.mkdir()
    write_registry(_registry(), registry_path(claims, "orders"))
    authored = """\
# Authored domain comment must remain byte-stable.
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/hub/orders> a owl:Ontology ; rdfs:label "Orders" .
"""
    (ontologies / "orders.ttl").write_text(authored, encoding="utf-8")
    (extensions / "orders-silver-ext.ttl").write_text(
        "# Authored extension comment.\n",
        encoding="utf-8",
    )

    report = apply_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
        module_context=context,
        scaffold_missing=False,
    )

    assert not report.is_blocking
    ontology_text = (ontologies / "orders.ttl").read_text(encoding="utf-8")
    assert ontology_text.startswith(authored)
    assert f"<{MODULE_IRI}> ." in ontology_text
    assert f"<{TERM_NS}> ." not in ontology_text
    extension_text = (extensions / "orders-silver-ext.ttl").read_text(encoding="utf-8")
    assert extension_text.startswith("# Authored extension comment.\n")
    assert TERM_NS + "Order" in extension_text
    assert TERM_NS + "SpecialOrder" in extension_text
    assert TERM_NS + "orderNumber" not in extension_text
    assert TERM_NS + "relatedOrder" not in extension_text

    config_path = context.config.source_path
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            "        imports:\n          - profile: orders\n",
            "        imports: []\n",
        ),
        encoding="utf-8",
    )
    empty = ClaimRegistry(domain="orders")
    write_registry(empty, registry_path(claims, "orders"))
    stale_context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )

    stale_report = apply_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
        module_context=stale_context,
        scaffold_missing=False,
    )

    assert not stale_report.is_blocking
    assert (ontologies / "orders.ttl").read_text(encoding="utf-8") == authored
    assert (
        extensions / "orders-silver-ext.ttl"
    ).read_text(encoding="utf-8") == "# Authored extension comment.\n"


def test_profile_only_domain_scaffolds_syncs_and_removes_stale_activation(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )
    model = tmp_path / "hub" / "model"
    claims = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    claims.mkdir(parents=True)
    ontologies.mkdir()
    extensions.mkdir()

    report = apply_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
        module_context=context,
    )

    assert not report.is_blocking
    assert [item.domain for item in report.domains] == ["orders"]
    assert not (claims / "orders-claims.yaml").exists()
    assert f"<{MODULE_IRI}> ." in (ontologies / "orders.ttl").read_text(encoding="utf-8")
    extension = (extensions / "orders-silver-ext.ttl").read_text(encoding="utf-8")
    assert TERM_NS + "Order" in extension
    assert TERM_NS + "SpecialOrder" not in extension
    inventory = json.loads(dump_activation_inventory(report.domains[0].activation_inventory))
    assert inventory["modules"][0]["ontology_iri"] == MODULE_IRI

    context.config.source_path.write_text(
        context.config.source_path.read_text(encoding="utf-8").replace(
            "        imports:\n          - profile: orders\n",
            "        imports: []\n",
        ),
        encoding="utf-8",
    )
    stale_context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )
    stale_report = apply_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
        module_context=stale_context,
        scaffold_missing=False,
    )

    assert not stale_report.is_blocking
    assert [item.domain for item in stale_report.domains] == ["orders"]
    assert MODULE_IRI not in (ontologies / "orders.ttl").read_text(encoding="utf-8")
    assert TERM_NS + "Order" not in (
        extensions / "orders-silver-ext.ttl"
    ).read_text(encoding="utf-8")


def test_validator_reports_term_expected_document_iri_and_managed_source(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )
    ontology = tmp_path / "orders.ttl"
    ontology.write_text(
        """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<https://example.org/hub/orders> a owl:Ontology .
""",
        encoding="utf-8",
    )
    claims = tmp_path / "orders-claims.yaml"
    write_registry(_registry(), claims)

    diagnostics = validate_managed_imports(
        ontology,
        claims,
        module_context=context,
    )
    missing = [item for item in diagnostics if item.code == "missing_managed_import"]

    assert {item.term_uri for item in missing} == {
        TERM_NS + "SpecialOrder",
        TERM_NS + "orderNumber",
        TERM_NS + "relatedOrder",
    }
    assert all(item.expected_ontology_iri == MODULE_IRI for item in missing)
    assert all(item.managed_source == "orders" for item in missing)


def test_validation_pipeline_blocks_missing_managed_import_unless_degraded(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    model = tmp_path / "model"
    ontologies = model / "ontologies"
    claims = model / "claims"
    shapes = model / "shapes"
    ontologies.mkdir(parents=True)
    claims.mkdir()
    shapes.mkdir()
    (ontologies / "orders.ttl").write_text(
        """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<https://example.org/hub/orders> a owl:Ontology .
""",
        encoding="utf-8",
    )
    write_registry(_registry(), claims / "orders-claims.yaml")
    report = tmp_path / "validation.json"

    with pytest.raises(SystemExit):
        run_validation(
            ontologies_path=ontologies,
            shapes_path=shapes,
            catalog_path=catalog,
            do_syntax=False,
            do_shacl=False,
            do_consistency=True,
            report_path=report,
            claims_dir=claims,
            ref_models_dir=ref_models,
            accelerator="generic",
        )
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["imports"]["failed"] == 1
    assert payload["imports"]["errors"][0]["code"] == "missing_managed_import"

    run_validation(
        ontologies_path=ontologies,
        shapes_path=shapes,
        catalog_path=catalog,
        do_syntax=False,
        do_shacl=False,
        do_consistency=True,
        claims_dir=claims,
        ref_models_dir=ref_models,
        accelerator="generic",
        degraded=True,
    )


def test_claims_to_silver_ext_cli_emits_activation_inventory(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    model = tmp_path / "model"
    claims = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    claims.mkdir(parents=True)
    ontologies.mkdir()
    extensions.mkdir()
    write_registry(_registry(), claims / "orders-claims.yaml")
    (ontologies / "orders.ttl").write_text(
        """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<https://example.org/hub/orders> a owl:Ontology .
""",
        encoding="utf-8",
    )
    (extensions / "orders-silver-ext.ttl").write_text("", encoding="utf-8")
    inventory_dir = tmp_path / "activation"

    result = CliRunner().invoke(
        cli,
        [
            "claims-to-silver-ext",
            "--claims-dir",
            str(claims),
            "--ontologies",
            str(ontologies),
            "--extensions",
            str(extensions),
            "--ref-models",
            str(ref_models),
            "--catalog",
            str(catalog),
            "--accelerator",
            "generic",
            "--activation-inventory-dir",
            str(inventory_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    inventory = inventory_dir / "orders-activation.json"
    assert inventory.is_file()
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    assert payload["modules"][0]["ontology_iri"] == MODULE_IRI


def test_projector_preflight_blocks_missing_managed_import_unless_degraded(
    tmp_path,
    monkeypatch,
):
    ref_models, catalog = _write_reference_pack(tmp_path)
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )
    hub = tmp_path / "hub"
    model = hub / "model"
    claims = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    claims.mkdir(parents=True)
    ontologies.mkdir()
    extensions.mkdir()
    write_registry(_registry(), claims / "orders-claims.yaml")
    (ontologies / "orders.ttl").write_text(
        """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<https://example.org/hub/orders> a owl:Ontology .
""",
        encoding="utf-8",
    )
    (extensions / "orders-silver-ext.ttl").write_text("", encoding="utf-8")
    apply_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
        module_context=context,
        scaffold_missing=False,
    )
    ontology_path = ontologies / "orders.ttl"
    ontology_path.write_text(
        "\n".join(
            line
            for line in ontology_path.read_text(encoding="utf-8").splitlines()
            if MODULE_IRI not in line
        )
        + "\n",
        encoding="utf-8",
    )
    projection_calls: list[bool] = []

    def fake_projection(*args, **kwargs):
        projection_calls.append(True)
        return {}

    monkeypatch.setattr("kairos_ontology.core.projector._run_projection", fake_projection)

    run_projections(
        ontologies_path=ontologies,
        catalog_path=catalog,
        output_path=hub / "output",
        target="silver",
        ref_models_dir=ref_models,
        accelerator="generic",
    )
    assert projection_calls == []
    projection_report = json.loads(
        (hub / "output" / "projection-report.json").read_text(encoding="utf-8")
    )
    assert any(
        "missing owl:imports" in item.get("error", "")
        for item in projection_report["projections"]
    )

    run_projections(
        ontologies_path=ontologies,
        catalog_path=catalog,
        output_path=hub / "degraded-output",
        target="silver",
        degraded=True,
        ref_models_dir=ref_models,
        accelerator="generic",
    )
    assert projection_calls == [True]


def test_projector_preflight_applies_to_profile_only_domain(tmp_path, monkeypatch):
    ref_models, catalog = _write_reference_pack(tmp_path)
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )
    hub = tmp_path / "hub"
    model = hub / "model"
    claims = model / "claims"
    ontologies = model / "ontologies"
    extensions = model / "extensions"
    claims.mkdir(parents=True)
    ontologies.mkdir()
    extensions.mkdir()
    apply_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
        module_context=context,
    )
    ontology_path = ontologies / "orders.ttl"
    ontology_path.write_text(
        "\n".join(
            line
            for line in ontology_path.read_text(encoding="utf-8").splitlines()
            if MODULE_IRI not in line
        )
        + "\n",
        encoding="utf-8",
    )
    projection_calls: list[bool] = []

    def fake_projection(*args, **kwargs):
        projection_calls.append(True)
        return {}

    monkeypatch.setattr("kairos_ontology.core.projector._run_projection", fake_projection)

    run_projections(
        ontologies_path=ontologies,
        catalog_path=catalog,
        output_path=hub / "output",
        target="silver",
        ref_models_dir=ref_models,
        accelerator="generic",
    )

    assert projection_calls == []
    projection_report = json.loads(
        (hub / "output" / "projection-report.json").read_text(encoding="utf-8")
    )
    assert any(
        "missing owl:imports" in item.get("error", "")
        for item in projection_report["projections"]
    )


def test_projector_applies_profile_defaults_and_allowlist_in_normal_dbt_mode(
    tmp_path,
    monkeypatch,
):
    ref_models, catalog = _write_reference_pack(tmp_path)
    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
    )
    hub = tmp_path / "hub"
    claims = hub / "model" / "claims"
    ontologies = hub / "model" / "ontologies"
    extensions = hub / "model" / "extensions"
    claims.mkdir(parents=True)
    ontologies.mkdir()
    extensions.mkdir()
    write_registry(_registry(), claims / "orders-claims.yaml")
    apply_projection_sync(
        claims_dir=claims,
        ontologies_dir=ontologies,
        extensions_dir=extensions,
        module_context=context,
    )
    calls: list[dict] = []

    def fake_projection(*args, **kwargs):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr("kairos_ontology.core.projector._run_projection", fake_projection)

    run_projections(
        ontologies_path=ontologies,
        catalog_path=catalog,
        output_path=hub / "output",
        target="dbt",
        ref_models_dir=ref_models,
        accelerator="generic",
    )

    assert len(calls) == 1
    assert calls[0]["ref_model_defaults"] == [
        ref_models
        / "accelerator-packs"
        / "generic"
        / "client-hub-blueprint"
        / "defaults"
        / "orders.ttl"
    ]
    assert calls[0]["eligible_class_uris"] == {
        TERM_NS + "Order",
        TERM_NS + "SpecialOrder",
    }
