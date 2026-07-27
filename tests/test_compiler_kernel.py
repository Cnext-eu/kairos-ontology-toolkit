# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the stateless v5 compiler kernel."""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from kairos_ontology.core.compiler import CompileMode, compile_domain


def _hub(tmp_path: Path, *, broken_column: bool = False) -> Path:
    ontology_dir = tmp_path / "model" / "ontologies"
    source_dir = tmp_path / "integration" / "sources" / "crm"
    binding_dir = tmp_path / "integration" / "bindings"
    ontology_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    binding_dir.mkdir(parents=True)
    (tmp_path / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    (ontology_dir / "party.ttl").write_text(
        textwrap.dedent("""
            @prefix party: <https://example.test/party#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
            party:Customer a owl:Class ; rdfs:label "Customer" .
            party:customer_id a owl:DatatypeProperty ;
              rdfs:domain party:Customer ; rdfs:range xsd:string .
            party:customerName a owl:DatatypeProperty ;
              rdfs:domain party:Customer ; rdfs:range xsd:string .
            """).strip(),
        encoding="utf-8",
    )
    (source_dir / "crm.vocabulary.ttl").write_text(
        textwrap.dedent("""
            @prefix src: <https://example.test/source#> .
            @prefix kb: <https://kairos.cnext.eu/bronze#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            src:crm a kb:SourceSystem ; rdfs:label "crm" ;
              kb:database "raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .
            src:customers a kb:SourceTable ; kb:sourceSystem src:crm ;
              kb:tableName "customers" ; kb:primaryKeyColumns "customer_id" .
            src:id a kb:SourceColumn ; kb:sourceTable src:customers ;
              kb:columnName "customer_id" ; kb:dataType "varchar(50)" ;
              kb:nullable "false"^^xsd:boolean .
            src:name a kb:SourceColumn ; kb:sourceTable src:customers ;
              kb:columnName "customer_name" ; kb:dataType "varchar(200)" ;
              kb:nullable "true"^^xsd:boolean .
            """).strip(),
        encoding="utf-8",
    )
    expression = "missing" if broken_column else "customer_name"
    (binding_dir / "customer.binding.yaml").write_text(
        textwrap.dedent(f"""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: crm-customer
              domain: party
            source:
              relation: crm.customers
            target:
              class: party:Customer
            grain:
              columns: [customer_id]
            identity:
              strategy: source-natural
              sourceKey: [customer_id]
            load:
              mode: full-refresh
            fields:
              - property: party:customer_id
                expression: customer_id
              - property: party:customerName
                expression: {expression}
            """).strip(),
        encoding="utf-8",
    )
    return tmp_path


def test_compile_domain_check_explain_and_render_are_deterministic(tmp_path):
    hub = _hub(tmp_path)
    first = compile_domain(hub, "party", CompileMode.EXPLAIN)
    second = compile_domain(hub, "party", CompileMode.EXPLAIN)
    assert first.succeeded
    assert first.artifacts == second.artifacts
    assert first.provenance_hash == second.provenance_hash
    assert first.explain is not None
    assert first.explain.entities[0].grain == ("customer_id",)
    assert "models/silver/party/customer.sql" in first.artifact_dict()


def test_compile_domain_collects_binding_error_without_writing(tmp_path):
    result = compile_domain(_hub(tmp_path, broken_column=True), "party")
    assert not result.succeeded
    assert not result.artifacts
    assert {item.code for item in result.diagnostics.items} == {"safety.column-unresolved"}


def test_missing_scope_is_a_diagnostic(tmp_path):
    result = compile_domain(tmp_path, "missing")
    assert not result.succeeded
    assert result.diagnostics.items[0].code == "safety.source-unresolved"


def test_invalid_entity_is_blocked_while_safe_entity_still_plans(tmp_path):
    scenario = Path(__file__).parent / "scenarios" / "v5-hub"
    hub = tmp_path / "hub"
    shutil.copytree(scenario, hub)
    customer = hub / "integration" / "bindings" / "customer.binding.yaml"
    customer.write_text(
        customer.read_text(encoding="utf-8").replace(
            "column: customer_name", "column: missing_name"
        ),
        encoding="utf-8",
    )
    result = compile_domain(hub, "party")
    assert not result.succeeded
    assert "models/silver/party/country.sql" in result.artifact_dict()
    assert "models/silver/party/customer.sql" not in result.artifact_dict()
    blocked = {item.name: item.blocked for item in result.explain.entities}
    assert blocked == {"crm-country": False, "crm-customer": True}


def test_unsupported_adapter_fails_closed(tmp_path):
    hub = _hub(tmp_path)
    (hub / "kairos.yaml").write_text("adapter: unknown\n", encoding="utf-8")
    result = compile_domain(hub, "party")
    assert not result.succeeded
    assert result.diagnostics.items[0].code == "safety.adapter-unsupported"


def test_empty_selected_domain_is_non_emittable(tmp_path):
    hub = _hub(tmp_path)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace("domain: party", "domain: other"),
        encoding="utf-8",
    )
    result = compile_domain(hub, "party")
    assert not result.succeeded
    assert not result.can_emit
    assert result.diagnostics.items[0].code == "safety.source-unresolved"


def test_all_malformed_selected_bindings_are_non_emittable(tmp_path):
    hub = _hub(tmp_path)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text("metadata:\n  domain: party\nunknown: rejected\n", encoding="utf-8")
    result = compile_domain(hub, "party")
    assert not result.succeeded
    assert not result.can_emit
    assert not result.artifacts


def test_invalid_unrelated_domain_binding_is_ignored(tmp_path):
    hub = _hub(tmp_path)
    unrelated_source = hub / "integration" / "sources" / "unrelated.ttl"
    unrelated_source.write_text(
        "@prefix ex: <https://example.test/source#> .\n"
        "@prefix kb: <https://kairos.cnext.eu/bronze#> .\n"
        'ex:system a kb:SourceSystem ; kb:systemName "other" .\n',
        encoding="utf-8",
    )
    other = hub / "integration" / "bindings" / "other.binding.yaml"
    other.write_text(
        "metadata:\n  domain: other\nunknown: rejected-in-v5\n",
        encoding="utf-8",
    )
    first = compile_domain(hub, "party")
    other.write_text(
        "metadata:\n  domain: other\nunknown: changed-but-unrelated\n",
        encoding="utf-8",
    )
    unrelated_source.write_text(
        unrelated_source.read_text(encoding="utf-8") + "# changed\n",
        encoding="utf-8",
    )
    second = compile_domain(hub, "party")
    assert first.succeeded and second.succeeded
    assert first.provenance_hash == second.provenance_hash
    assert all("other.binding.yaml" not in path for path in first.explain.binding_paths)


def test_property_domain_mismatch_is_blocked(tmp_path):
    hub = tmp_path / "hub"
    shutil.copytree(Path(__file__).parent / "scenarios" / "v5-hub", hub)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace("party:customer_name", "party:country_name"),
        encoding="utf-8",
    )
    result = compile_domain(hub, "party")
    assert "binding.property-domain-incompatible" in {
        item.code for item in result.diagnostics.items
    }


def test_unsupported_ambiguous_parent_first_is_blocked(tmp_path):
    hub = tmp_path / "hub"
    shutil.copytree(Path(__file__).parent / "scenarios" / "v5-hub", hub)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            "ambiguousParent: error", "ambiguousParent: first"
        ),
        encoding="utf-8",
    )
    result = compile_domain(hub, "party")
    assert "safety.adapter-unsupported" in {item.code for item in result.diagnostics.items}


@pytest.mark.parametrize("side", ["local", "foreign"])
def test_relationship_join_columns_must_resolve(tmp_path, side):
    scenario = Path(__file__).parent / "scenarios" / "v5-hub"
    hub = tmp_path / "hub"
    shutil.copytree(scenario, hub)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            f"{side}: {'country_code' if side == 'local' else 'code'}",
            f"{side}: missing",
        ),
        encoding="utf-8",
    )
    result = compile_domain(hub, "party")
    assert not result.succeeded
    assert "safety.column-unresolved" in {item.code for item in result.diagnostics.items}
