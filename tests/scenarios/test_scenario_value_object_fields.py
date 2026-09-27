# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A single-valued value object's scalars are fields of its parent (DD-252, #811).

Exercised end to end through ``compile_domain`` on a copy of the ``v5-hub`` fixture. The
value object ``acc:Money`` lives in a second namespace, the shape of an accelerator range
class no binding targets, so the kernel must index its properties for the ``via`` alone.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kairos_ontology.core.compiler import CompileMode, compile_domain
from kairos_ontology.core.compiler.adapter import ResolvedProperty, value_object_column_name
from kairos_ontology.core.compiler.bindings import load_entity_binding
from kairos_ontology.core.compiler.contract_conformance import contract_binding_diagnostics

_HUB = Path(__file__).parent / "v5-hub"
_BINDING = "integration/bindings/customer.binding.yaml"
_MODELS_YML = "models/silver/party/_party__models.yml"

# hasCreditLimit is functional; hasBalance is bounded by a max-1 class restriction;
# hasPayment is unbounded, so it can never be inlined.
_VALUE_OBJECT = """
@prefix acc: <https://example.test/accelerator/money#> .
acc:Money a owl:Class ; rdfs:label "Money" .
acc:amountValue a owl:DatatypeProperty ; rdfs:domain acc:Money ; rdfs:range xsd:decimal .
acc:currencyCode a owl:DatatypeProperty ; rdfs:domain acc:Money ; rdfs:range xsd:string .
party:hasCreditLimit a owl:ObjectProperty, owl:FunctionalProperty ;
  rdfs:domain party:Customer ; rdfs:range acc:Money .
party:hasBalance a owl:ObjectProperty ; rdfs:domain party:Customer ; rdfs:range acc:Money .
party:Customer rdfs:subClassOf [ a owl:Restriction ;
  owl:onProperty party:hasBalance ; owl:maxCardinality 1 ] .
party:hasPayment a owl:ObjectProperty ; rdfs:domain party:Customer ; rdfs:range acc:Money .
"""


def _hub(tmp_path: Path, *fields: dict) -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_HUB, hub)
    (hub / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    ontology = hub / "model" / "ontologies" / "party.ttl"
    ontology.write_text(ontology.read_text(encoding="utf-8") + _VALUE_OBJECT, "utf-8")
    path = hub / _BINDING
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["fields"].extend(fields)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return hub


def _customer_columns(result) -> dict[str, dict]:
    schema = yaml.safe_load(result.artifact_dict()[_MODELS_YML])
    customer = next(item for item in schema["models"] if item["name"] == "customer")
    return {column["name"]: column for column in customer["columns"]}


def _codes(result) -> dict[str, str]:
    return {item.code: item.message for item in result.diagnostics.items}


_CREDIT = {"property": "acc:currencyCode", "via": "party:hasCreditLimit",
           "expression": "country_code"}
_BALANCE = {"property": "acc:currencyCode", "via": "party:hasBalance",
            "expression": "country_code"}


def test_two_value_objects_of_one_class_become_two_parent_columns(tmp_path: Path) -> None:
    result = compile_domain(_hub(tmp_path, _CREDIT, _BALANCE), "party", CompileMode.EMIT)
    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    columns = _customer_columns(result)
    assert {"credit_limit_currency_code", "balance_currency_code"} <= set(columns)
    provenance = columns["credit_limit_currency_code"]["meta"]["provenance"]
    assert "property:https://example.test/accelerator/money#currencyCode" in provenance
    assert "via:https://example.test/ontology/party#hasCreditLimit" in provenance
    # An ordinary field carries no via.
    assert not any(
        item.startswith("via:") for item in columns["customer_name"]["meta"]["provenance"]
    )


def test_an_unbounded_via_is_refused_with_the_restriction_to_add(tmp_path: Path) -> None:
    field = {"property": "acc:currencyCode", "via": "party:hasPayment",
             "expression": "country_code"}
    result = compile_domain(_hub(tmp_path, field), "party", CompileMode.EMIT)
    assert not result.succeeded
    message = _codes(result)["binding.value-object-not-single-valued"]
    assert "declares no upper bound" in message
    assert "owl:onProperty party:hasPayment ; owl:maxCardinality 1" in message
    assert "relationships:" in message


@pytest.mark.parametrize(
    ("field", "code", "fragment"),
    [
        ({"property": "acc:currencyCode", "via": "party:customer_name",
          "expression": "country_code"},
         "binding.value-object-via-not-object-property", "is a datatype property"),
        ({"property": "party:customer_name", "via": "party:hasCreditLimit",
          "expression": "country_code"},
         "safety.property-unresolved", "Properties it has: acc:amountValue, acc:currencyCode"),
        ({"property": "acc:currencyCode", "via": "party:noSuchLink",
          "expression": "country_code"},
         "safety.property-unresolved", "party:noSuchLink"),
    ],
)
def test_a_malformed_via_field_is_reported(tmp_path: Path, field, code, fragment) -> None:
    result = compile_domain(_hub(tmp_path, field), "party", CompileMode.EMIT)
    assert not result.succeeded
    codes = _codes(result)
    assert code in codes, [item.render() for item in result.diagnostics.items]
    assert fragment in codes[code]


def test_the_same_path_twice_is_a_duplicate(tmp_path: Path) -> None:
    result = compile_domain(_hub(tmp_path, _CREDIT, dict(_CREDIT)), "party", CompileMode.EMIT)
    assert "field.duplicate-property" in _codes(result)


def test_the_object_property_rejection_points_at_via(tmp_path: Path) -> None:
    field = {"property": "party:hasCreditLimit", "expression": "country_code"}
    result = compile_domain(_hub(tmp_path, field), "party", CompileMode.EMIT)
    assert "via: party:hasCreditLimit" in _codes(result)["safety.relationship-endpoint"]


@pytest.mark.parametrize(
    ("via", "leaf", "column"),
    [
        ("has_gross_weight", "weight_value", "gross_weight_value"),
        ("has_weight", "weight_unit", "weight_unit"),
        ("has_flag_state", "flag_state_country_code", "flag_state_country_code"),
        ("has_credit_limit", "currency_code", "credit_limit_currency_code"),
        ("capacity", "value", "capacity_value"),
    ],
)
def test_the_column_is_named_from_both_hops(via: str, leaf: str, column: str) -> None:
    def prop(name: str) -> ResolvedProperty:
        return ResolvedProperty(ref=name, uri=name, column_name=name, data_type="string")

    assert value_object_column_name(prop(via), prop(leaf)) == column


def test_a_governed_class_refuses_a_via_field() -> None:
    text = (_HUB / _BINDING).read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    document["fields"].append(_CREDIT)
    binding = load_entity_binding(yaml.safe_dump(document), path="customer.binding.yaml")
    contract = SimpleNamespace(entity_for=lambda _: object(), source_path="silver.yaml")
    diagnostics = contract_binding_diagnostics(binding, contract)
    assert [item.code for item in diagnostics] == ["contract.value-object-field-unsupported"]
    assert diagnostics[0].location.pointer == "/fields/3/via"


def test_fit_report_counts_the_via_as_populated(tmp_path: Path) -> None:
    from kairos_ontology.core.fit_report import run_fit_report

    hub = _hub(tmp_path, _CREDIT)
    result = run_fit_report(
        hub / "model" / "ontologies" / "party.ttl",
        "party:Customer",
        binding_path=hub / _BINDING,
    )
    populated = {item.name: item.source for item in result.populated}
    assert populated["hasCreditLimit"] == "value object: acc:currencyCode <- country_code"
    assert "hasBalance" in {item.name for item in result.unpopulated}


def test_the_sample_audit_finds_a_via_column_by_its_own_name() -> None:
    from kairos_ontology.core.projections.dbt.mapping_bind import mapping_context
    from kairos_ontology.core.projections.dbt.mapping_specs import (
        ColumnMappingFact,
        SourceMappings,
    )

    fact = ColumnMappingFact(
        resource_uri="urn:m:1",
        source_column_uri="urn:c:1",
        target_property_uri="https://example.test/accelerator/money#currencyCode",
        match_type="exact",
        target_column_name="credit_limit_currency_code",
        via_property_uri="https://example.test/ontology/party#hasCreditLimit",
    )
    plain = ColumnMappingFact(
        resource_uri="urn:m:2", source_column_uri="urn:c:2",
        target_property_uri="urn:p", match_type="exact", target_column_name="p",
    )
    maps, _ = mapping_context(SourceMappings(tables=(), columns=(fact, plain)))
    assert maps["column_maps"]["urn:c:1"][0]["target_column_name"] == "credit_limit_currency_code"
    assert "target_column_name" not in maps["column_maps"]["urn:c:2"][0]
