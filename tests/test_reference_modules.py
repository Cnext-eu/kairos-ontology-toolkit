# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for managed reference-module activation (CR-TK-01/02)."""

from __future__ import annotations

import pytest
import yaml
from rdflib import Graph

from kairos_ontology.core.reference_modules import (
    build_reference_module_context,
    load_accelerator_module_config,
)

MODULE_IRI = "https://example.org/reference/orders"
TERM_NS = MODULE_IRI + "#"


def _write_reference_pack(tmp_path):
    ref_models = tmp_path / "reference-models"
    blueprint = ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint"
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


def _add_unrelated_broken_module(ref_models):
    config_path = (
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint" / "data-domains.yaml"
    )
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["module_profiles"].append(
        {
            "id": "broken",
            "ontology_iri": "https://example.org/reference/broken",
            "catalog_uri": "https://example.org/reference/broken",
            "version_pin": "1.0",
            "term_namespaces": ["https://example.org/reference/broken#"],
        }
    )
    data["groups"].append(
        {
            "id": "unrelated",
            "domains": [{"id": "billing", "imports": [{"profile": "broken"}]}],
        }
    )
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


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


def test_domain_scoped_context_ignores_unrelated_broken_module(tmp_path):
    ref_models, catalog = _write_reference_pack(tmp_path)
    _add_unrelated_broken_module(ref_models)

    context = build_reference_module_context(
        ref_models,
        catalog_path=catalog,
        accelerator="generic",
        requested_domains=["orders"],
    )

    assert [module.profile.id for module in context.modules] == ["orders"]
    assert context.diagnostics == ()


def test_profile_rejects_term_namespace_as_ontology_iri(tmp_path):
    ref_models, _catalog = _write_reference_pack(tmp_path)
    path = (
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint" / "data-domains.yaml"
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
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint" / "data-domains.yaml"
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
        ref_models / "accelerator-packs" / "generic" / "client-hub-blueprint" / "data-domains.yaml"
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
