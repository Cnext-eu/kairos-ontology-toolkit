# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for deterministic v5 multi-source conformance planning."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from kairos_ontology.core.compiler import (
    CompileError,
    ConformanceTypeContract,
    ProvenanceInput,
    build_conformance_plan,
    load_entity_binding,
)
from kairos_ontology.core.compiler.bindings import LoadSpec


def _binding(
    name: str,
    source: str,
    precedence: int,
    *,
    group: str = "party-customer",
    target: str = "party:Customer",
    conflict: str = "prefer-precedence",
    union: str = "union-all",
    api_version: str = "kairos.eu/v5",
):
    dedup = (
        "\n    deduplicateBy: [customer_id]"
        "\n    orderBy: [{column: updated_at, direction: descending}]"
        if union == "deduplicate"
        else ""
    )
    text = f"""\
apiVersion: {api_version}
kind: EntityBinding
metadata:
  name: {name}
  domain: party
source:
  relation: {source}
target:
  class: {target}
grain:
  columns: [customer_id]
identity:
  strategy: source-natural
  sourceKey: [customer_id]
load:
  mode: full-refresh
fields:
  - property: party:customerId
    expression: customer_id
  - property: party:displayName
    expression: display_name
conformance:
  group: {group}
  sourcePrecedence: {precedence}
  conflict: {conflict}
  union:
    mode: {union}{dedup}
"""
    return load_entity_binding(text, path=f"bindings/{name}.binding.yaml")


CONTRACT = ConformanceTypeContract(
    grain=("string",),
    identity=("string",),
    properties=(("party:customerId", "string"), ("party:displayName", "string")),
)


def _plan(*bindings, contracts=None, provenance=None):
    contracts = contracts or {binding.name: CONTRACT for binding in bindings}
    provenance = provenance or {
        binding.name: (
            ProvenanceInput(f"sources/{binding.name}.ttl", f"source={binding.name}"),
            ProvenanceInput(binding.source_path, f"binding={binding.name}"),
        )
        for binding in bindings
    }
    return build_conformance_plan(
        bindings,
        type_contracts=contracts,
        provenance_inputs=provenance,
    )


def _codes(exc: CompileError) -> set[str]:
    return {item.code for item in exc.diagnostics}


def test_builds_immutable_plan_in_precedence_then_source_order() -> None:
    second = _binding("erp-customer", "erp.customers", 2)
    first = _binding("crm-customer", "crm.customers", 1)

    plan = _plan(second, first)

    assert [source.binding_name for source in plan.groups[0].sources] == [
        "crm-customer",
        "erp-customer",
    ]
    assert plan.groups[0].sources[0].grain == (("customer_id", "string"),)
    assert plan.groups[0].sources[0].identity == (("customer_id", "string"),)
    assert [item.name for item in plan.provenance_inputs] == sorted(
        item.name for item in plan.provenance_inputs
    )
    with pytest.raises(FrozenInstanceError):
        plan.groups[0].conflict = "error"  # type: ignore[misc]


def test_input_and_provenance_order_do_not_change_plan() -> None:
    first = _binding("crm-customer", "crm.customers", 1)
    second = _binding("erp-customer", "erp.customers", 2)
    provenance = {
        first.name: (
            ProvenanceInput("z", "last"),
            ProvenanceInput("a", "first"),
        ),
        second.name: (ProvenanceInput("m", "middle"),),
    }

    assert _plan(first, second, provenance=provenance) == _plan(
        second, first, provenance=provenance
    )


def test_same_target_requires_one_explicit_matching_group() -> None:
    first = _binding("crm-customer", "crm.customers", 1)
    second = _binding("erp-customer", "erp.customers", 2, group="other")

    with pytest.raises(CompileError) as excinfo:
        _plan(first, second)

    assert "conformance.group-mismatch" in _codes(excinfo.value)


def test_same_target_rejects_an_ungrouped_binding() -> None:
    first = _binding("crm-customer", "crm.customers", 1)
    second = replace(
        _binding("erp-customer", "erp.customers", 2),
        conformance=None,
    )

    with pytest.raises(CompileError) as excinfo:
        _plan(first, second)

    assert "conformance.group-required" in _codes(excinfo.value)


def test_group_cannot_span_target_classes() -> None:
    first = _binding("crm-customer", "crm.customers", 1)
    second = _binding("erp-party", "erp.parties", 2, target="party:Party")

    with pytest.raises(CompileError) as excinfo:
        _plan(first, second)

    assert "conformance.target-mismatch" in _codes(excinfo.value)


@pytest.mark.parametrize(
    ("contracts", "code"),
    [
        (
            {
                "crm-customer": CONTRACT,
                "erp-customer": ConformanceTypeContract(
                    grain=("integer",),
                    identity=("string",),
                    properties=CONTRACT.properties,
                ),
            },
            "conformance.grain-incompatible",
        ),
        (
            {
                "crm-customer": CONTRACT,
                "erp-customer": ConformanceTypeContract(
                    grain=("string",),
                    identity=("integer",),
                    properties=CONTRACT.properties,
                ),
            },
            "conformance.identity-incompatible",
        ),
        (
            {
                "crm-customer": CONTRACT,
                "erp-customer": ConformanceTypeContract(
                    grain=("string",),
                    identity=("string",),
                    properties=(
                        ("party:customerId", "string"),
                        ("party:displayName", "integer"),
                    ),
                ),
            },
            "conformance.property-incompatible",
        ),
    ],
)
def test_rejects_incompatible_grain_identity_and_property_types(contracts, code) -> None:
    first = _binding("crm-customer", "crm.customers", 1)
    second = _binding("erp-customer", "erp.customers", 2)

    with pytest.raises(CompileError) as excinfo:
        _plan(first, second, contracts=contracts)

    assert code in _codes(excinfo.value)


def test_rejects_duplicate_source_and_precedence_with_stable_locations() -> None:
    first = _binding("a-customer", "crm.customers", 1)
    duplicate = _binding("b-customer", "crm.customers", 1)

    with pytest.raises(CompileError) as excinfo:
        _plan(duplicate, first)

    assert {
        "conformance.source-duplicate",
        "conformance.precedence-duplicate",
    } <= _codes(excinfo.value)
    assert [item.location.path for item in excinfo.value.diagnostics] == sorted(
        item.location.path for item in excinfo.value.diagnostics
    )
    assert all(item.location.pointer for item in excinfo.value.diagnostics)


def test_rejects_conflict_and_union_policy_disagreement() -> None:
    first = _binding("crm-customer", "crm.customers", 1)
    second = _binding(
        "erp-customer",
        "erp.customers",
        2,
        conflict="error",
        union="deduplicate",
    )

    with pytest.raises(CompileError) as excinfo:
        _plan(first, second)

    assert {
        "conformance.conflict-incompatible",
        "conformance.union-incompatible",
    } <= _codes(excinfo.value)


def test_rejects_cross_feature_load_policy_conflict() -> None:
    first = _binding("crm-customer", "crm.customers", 1)
    second = replace(
        _binding("erp-customer", "erp.customers", 2),
        load=LoadSpec(mode="incremental", scd=1),
    )

    with pytest.raises(CompileError) as excinfo:
        _plan(first, second)

    diagnostic = next(
        item for item in excinfo.value.diagnostics if item.code == "conformance.load-incompatible"
    )
    assert diagnostic.location.path == "bindings/erp-customer.binding.yaml"
    assert diagnostic.location.pointer == "/load"


def test_deduplication_must_use_declared_identity() -> None:
    first = _binding("crm-customer", "crm.customers", 1, union="deduplicate")
    second = _binding("erp-customer", "erp.customers", 2, union="deduplicate")
    object.__setattr__(
        second.conformance.union,
        "deduplicate_by",
        ("display_name",),
    )

    with pytest.raises(CompileError) as excinfo:
        _plan(first, second)

    assert "conformance.dedup-identity-incompatible" in _codes(excinfo.value)


def test_requires_complete_type_contracts_and_provenance() -> None:
    first = _binding("crm-customer", "crm.customers", 1)
    second = _binding("erp-customer", "erp.customers", 2)

    with pytest.raises(CompileError) as excinfo:
        _plan(
            first,
            second,
            contracts={first.name: CONTRACT},
            provenance={first.name: (ProvenanceInput("crm", "content"),)},
        )

    assert {
        "conformance.type-contract-missing",
        "conformance.provenance-missing",
    } <= _codes(excinfo.value)


def test_rejects_single_source_group_and_v4_without_compatibility() -> None:
    binding = _binding("crm-customer", "crm.customers", 1)
    with pytest.raises(CompileError) as excinfo:
        _plan(binding)
    assert "conformance.group-single-source" in _codes(excinfo.value)

    binding = replace(binding, api_version="kairos.eu/v4")
    with pytest.raises(CompileError) as excinfo:
        _plan(binding)
    assert "conformance.api-version" in _codes(excinfo.value)
