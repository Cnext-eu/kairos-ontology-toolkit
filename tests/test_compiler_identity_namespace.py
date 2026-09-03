# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Identity namespace decoupling tests for the v5 binding adapter (DD-108/DD-133).

Defect #6: the identity fact must carry the emitted target OUTPUT column names, never the raw
SOURCE column names, so a binding whose source key column name differs from the target property
local name compiles and produces coherent, output-named identity/grain.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from kairos_ontology.core.compiler import (
    CompileError,
    ResolutionContext,
    ResolvedClass,
    ResolvedColumn,
    ResolvedProperty,
    ResolvedRelation,
    adapt_binding,
    load_entity_binding,
)
from kairos_ontology.core.projections.dbt import (
    normalize_contract,
    plan_materialization,
    render_project,
    shape_project,
)
from kairos_ontology.core.projections.dbt.diagnostics import ExecutionMode

_TEMPLATE_ROOT = str(
    Path(__file__).resolve().parents[1] / "src" / "kairos_ontology" / "templates" / "dbt"
)

_NS = "https://acme.example/ontology/order#"
_IRI = "https://acme.example/ontology/order"


def _context() -> ResolutionContext:
    return ResolutionContext(
        domain="order",
        namespace=_NS,
        ontology_name="order",
        ontology_iri=_IRI,
        ontology_version="0.1.0",
        template_root=_TEMPLATE_ROOT,
        target_platform="fabric-warehouse",
        relations=(
            ResolvedRelation(
                ref="ops.orders",
                uri="https://acme.example/bronze/ops#orders",
                system_label="ops",
                table_name="orders",
                columns=(
                    ResolvedColumn("order_id", "varchar(50)", nullable=False, is_primary_key=True),
                    ResolvedColumn("name", "varchar(200)", nullable=False),
                    ResolvedColumn("alpha_src", "varchar(50)", nullable=False),
                    ResolvedColumn("beta_src", "varchar(50)", nullable=False),
                    ResolvedColumn("dup", "varchar(50)", nullable=False),
                    ResolvedColumn("lonely", "varchar(50)", nullable=False),
                    # Source columns whose output aliases are unrelated names entirely
                    # (not just reordered/suffixed), mirroring the real reported binding.
                    ResolvedColumn("booking_id", "varchar(50)", nullable=False),
                    ResolvedColumn("party_id", "varchar(50)", nullable=False),
                    ResolvedColumn("party_role", "varchar(50)", nullable=False),
                ),
            ),
        ),
        classes=(
            ResolvedClass(
                ref="order:Order",
                uri=f"{_NS}Order",
                name="Order",
                label="Order",
                comment="A purchase order.",
            ),
        ),
        properties=(
            ResolvedProperty(
                ref="order:orderId",
                uri=f"{_NS}orderId",
                column_name="order_id",
                data_type="string",
            ),
            # Target property whose local name differs from the source column ``name``.
            ResolvedProperty(
                ref="order:orderReference",
                uri=f"{_NS}orderReference",
                column_name="order_reference",
                data_type="string",
            ),
            ResolvedProperty(
                ref="order:alpha",
                uri=f"{_NS}alpha",
                column_name="alpha",
                data_type="string",
            ),
            ResolvedProperty(
                ref="order:beta",
                uri=f"{_NS}beta",
                column_name="beta",
                data_type="string",
            ),
            # Unrelated output names for the sibling-alias regression below.
            ResolvedProperty(
                ref="order:transportOrderReference",
                uri=f"{_NS}transportOrderReference",
                column_name="transport_order_reference",
                data_type="string",
            ),
            ResolvedProperty(
                ref="order:partyRef",
                uri=f"{_NS}partyRef",
                column_name="party_ref",
                data_type="string",
            ),
            ResolvedProperty(
                ref="order:sourcePartyRoleValue",
                uri=f"{_NS}sourcePartyRoleValue",
                column_name="source_party_role_value",
                data_type="string",
            ),
        ),
    )


def _binding(body: str) -> str:
    return textwrap.dedent(body).strip()


def _natural_keys(binding_text: str) -> tuple[str, ...]:
    binding = load_entity_binding(binding_text, path="order.yaml")
    bound = adapt_binding(binding, _context())
    return bound.policy_facts.identities[0].natural_keys.values


def test_source_key_name_differs_from_target_property_compiles_and_renders():
    text = _binding("""
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: ops-order
          domain: order
        source:
          relation: ops.orders
        target:
          class: order:Order
        grain:
          columns: [order_id]
        identity:
          strategy: source-natural
          sourceKey: [name]
        load:
          mode: full-refresh
        fields:
          - property: order:orderId
            expression: order_id
          - property: order:orderReference
            expression: name
    """)
    # Identity fact carries the target OUTPUT column, not the source column ``name``.
    assert _natural_keys(text) == ("order_reference",)

    bound = adapt_binding(load_entity_binding(text, path="order.yaml"), _context())
    contract = normalize_contract(bound, ExecutionMode.FAIL_FAST)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    artifacts = render_project(shaped, plan)
    sql = artifacts["models/silver/order/order.sql"]
    # Generated identity references the snake-cased OUTPUT column, never the source ``name``.
    assert "order_reference" in sql


def test_explicit_business_key_resolves_to_output_columns():
    text = _binding("""
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: ops-order
          domain: order
        source:
          relation: ops.orders
        target:
          class: order:Order
        grain:
          columns: [order_id]
        identity:
          strategy: source-natural
          sourceKey: [order_id]
          businessKey: [name]
        load:
          mode: full-refresh
        fields:
          - property: order:orderId
            expression: order_id
          - property: order:orderReference
            expression: name
    """)
    assert _natural_keys(text) == ("order_reference",)


def test_composite_key_preserves_order():
    text = _binding("""
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: ops-order
          domain: order
        source:
          relation: ops.orders
        target:
          class: order:Order
        grain:
          columns: [order_id]
        identity:
          strategy: source-natural
          sourceKey: [beta_src, alpha_src]
        load:
          mode: full-refresh
        fields:
          - property: order:orderId
            expression: order_id
          - property: order:alpha
            expression: alpha_src
          - property: order:beta
            expression: beta_src
    """)
    assert _natural_keys(text) == ("beta", "alpha")


def test_composite_business_key_does_not_emit_extraneous_placeholder_test():
    """Regression for bug #17a.

    A resolved composite business-key identity never carries real
    `_source_system`/`_source_record_key` columns, so the DD-108 fallback pair must not
    be emitted as a second `unique_combination_of_columns` test alongside the real,
    grain-based one -- that placeholder pair referenced nonexistent columns and always
    errored against a live warehouse.
    """
    text = _binding("""
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: ops-order
          domain: order
        source:
          relation: ops.orders
        target:
          class: order:Order
        grain:
          columns: [order_id]
        identity:
          strategy: source-natural
          sourceKey: [beta_src, alpha_src]
        load:
          mode: full-refresh
        fields:
          - property: order:orderId
            expression: order_id
          - property: order:alpha
            expression: alpha_src
          - property: order:beta
            expression: beta_src
    """)
    bound = adapt_binding(load_entity_binding(text, path="order.yaml"), _context())
    contract = normalize_contract(bound, ExecutionMode.FAIL_FAST)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    artifacts = render_project(shaped, plan)
    schema_yml = artifacts["models/silver/order/_order__models.yml"]

    assert schema_yml.count("unique_combination_of_columns") == 1
    assert "_source_system" not in schema_yml
    assert "_source_record_key" not in schema_yml


def test_surrogate_key_references_source_expressions_not_sibling_aliases():
    """Regression for bug #16 (real, reproduced against a live Fabric warehouse).

    A composite `source-natural` identity whose sourceKey columns map to entirely
    unrelated output aliases (not just a suffix/reorder) must hash the real
    source-side expression for each key column, never the column's own bare output
    alias -- referencing a sibling SELECT-list alias from another expression in the
    same SELECT list is invalid SQL. `column.expression` is empty for ordinary
    `fields:`-mapped columns (the real text lives in `column.mapping_expression`,
    rendered only at final SQL time); the prior fallback to the bare column name
    silently produced exactly the invalid SQL this test guards against.
    """
    text = _binding("""
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: ops-order
          domain: order
        source:
          relation: ops.orders
        target:
          class: order:Order
        grain:
          columns: [order_id]
        identity:
          strategy: source-natural
          sourceKey: [booking_id, party_id, party_role]
        load:
          mode: full-refresh
        fields:
          - property: order:orderId
            expression: order_id
          - property: order:transportOrderReference
            expression: booking_id
          - property: order:partyRef
            expression: party_id
          - property: order:sourcePartyRoleValue
            expression: party_role
    """)
    bound = adapt_binding(load_entity_binding(text, path="order.yaml"), _context())
    contract = normalize_contract(bound, ExecutionMode.FAIL_FAST)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    artifacts = render_project(shaped, plan)
    sql = artifacts["models/silver/order/order.sql"]

    hash_start = sql.index("generate_surrogate_key(")
    hash_call = sql[hash_start : sql.index(") }}", hash_start)]
    assert "[src].[booking_id]" in hash_call
    assert "[src].[party_id]" in hash_call
    assert "[src].[party_role]" in hash_call
    # The output aliases must not appear as bare, unqualified names inside the hash --
    # they are only valid as the SELECT list's own column aliases, defined alongside
    # (never inside) this expression.
    assert "'transport_order_reference'" not in hash_call
    assert "'party_ref'" not in hash_call
    assert "'source_party_role_value'" not in hash_call


def test_identity_key_without_field_mapping_is_actionable():
    text = _binding("""
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: ops-order
          domain: order
        source:
          relation: ops.orders
        target:
          class: order:Order
        grain:
          columns: [order_id]
        identity:
          strategy: source-natural
          sourceKey: [lonely]
        load:
          mode: full-refresh
        fields:
          - property: order:orderId
            expression: order_id
    """)
    with pytest.raises(CompileError) as excinfo:
        adapt_binding(load_entity_binding(text, path="order.yaml"), _context())
    diagnostics = {d.code: d.message for d in excinfo.value.diagnostics}
    assert "identity.authored-key-not-supplied" in diagnostics
    message = diagnostics["identity.authored-key-not-supplied"]
    assert "lonely" in message
    assert "IDENTITY" in message
    assert "fields:" in message
    assert "scalar target property" in message


def test_identity_key_mapping_ambiguity_is_reported():
    text = _binding("""
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: ops-order
          domain: order
        source:
          relation: ops.orders
        target:
          class: order:Order
        grain:
          columns: [order_id]
        identity:
          strategy: source-natural
          sourceKey: [dup]
        load:
          mode: full-refresh
        fields:
          - property: order:orderId
            expression: order_id
          - property: order:alpha
            expression: dup
          - property: order:beta
            expression: dup
    """)
    with pytest.raises(CompileError) as excinfo:
        adapt_binding(load_entity_binding(text, path="order.yaml"), _context())
    codes = {d.code for d in excinfo.value.diagnostics}
    assert "identity.ambiguous-key-mapping" in codes
