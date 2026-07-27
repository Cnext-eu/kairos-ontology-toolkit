# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""End-to-end tests for the v5 binding adapter (DD-133).

These prove that a parsed ``EntityBinding`` plus a resolved symbol context adapts to a
``BoundSources`` the *existing* immutable dbt pipeline accepts, and that the pipeline renders
deterministic Fabric dbt artifacts — reusing the seam proven in ``tmp_spike/seam_spike.py``.
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

_NS = "https://acme.example/ontology/party#"
_IRI = "https://acme.example/ontology/party"

BINDING = textwrap.dedent("""
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
      - property: party:customerId
        expression: customer_id
      - property: party:customerName
        expression:
          fn: upper
          args: [{ column: customer_name }]
    """).strip()


def _context() -> ResolutionContext:
    return ResolutionContext(
        domain="party",
        namespace=_NS,
        ontology_name="party",
        ontology_iri=_IRI,
        ontology_version="0.1.0",
        template_root=_TEMPLATE_ROOT,
        target_platform="fabric",
        relations=(
            ResolvedRelation(
                ref="crm.customers",
                uri="https://acme.example/bronze/crm#customers",
                system_label="crm",
                table_name="customers",
                columns=(
                    ResolvedColumn(
                        "customer_id", "varchar(50)", nullable=False, is_primary_key=True
                    ),
                    ResolvedColumn("customer_name", "varchar(200)", nullable=True),
                ),
            ),
        ),
        classes=(
            ResolvedClass(
                ref="party:Customer",
                uri=f"{_NS}Customer",
                name="Customer",
                label="Customer",
                comment="A party that buys.",
            ),
        ),
        properties=(
            ResolvedProperty(
                ref="party:customerId",
                uri=f"{_NS}customerId",
                column_name="customer_id",
                data_type="string",
                description="CRM natural key",
            ),
            ResolvedProperty(
                ref="party:customerName",
                uri=f"{_NS}customerName",
                column_name="customer_name",
                data_type="string",
                description="Upper-cased display name",
            ),
        ),
    )


def _render(binding_text: str, context: ResolutionContext) -> dict[str, str]:
    binding = load_entity_binding(binding_text, path="crm-customer.yaml")
    bound = adapt_binding(binding, context)
    contract = normalize_contract(bound, ExecutionMode.FAIL_FAST)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    return render_project(shaped, plan)


def test_adapter_renders_silver_sql():
    artifacts = _render(BINDING, _context())
    sql_path = "models/silver/party/customer.sql"
    assert sql_path in artifacts
    sql = artifacts[sql_path]
    assert "upper(" in sql.lower()
    assert "customer_id" in sql
    assert "customer_name" in sql


def test_adapter_is_deterministic():
    first = _render(BINDING, _context())
    second = _render(BINDING, _context())
    file_first = {k: v for k, v in first.items() if isinstance(v, str)}
    file_second = {k: v for k, v in second.items() if isinstance(v, str)}
    assert file_first == file_second


def test_unknown_property_is_reported_with_location():
    context = _context()
    broken = BINDING.replace("party:customerName", "party:doesNotExist")
    with pytest.raises(CompileError) as excinfo:
        adapt_binding(load_entity_binding(broken, path="b.yaml"), context)
    codes = {d.code for d in excinfo.value.diagnostics}
    assert "binding.unknown-property" in codes


def test_unknown_source_column_is_reported():
    context = _context()
    broken = BINDING.replace("column: customer_name", "column: missing_col")
    with pytest.raises(CompileError) as excinfo:
        adapt_binding(load_entity_binding(broken, path="b.yaml"), context)
    codes = {d.code for d in excinfo.value.diagnostics}
    assert "binding.unknown-column" in codes


def test_unknown_relation_is_reported():
    context = _context()
    broken = BINDING.replace("relation: crm.customers", "relation: crm.unknown")
    with pytest.raises(CompileError) as excinfo:
        adapt_binding(load_entity_binding(broken, path="b.yaml"), context)
    codes = {d.code for d in excinfo.value.diagnostics}
    assert "binding.unknown-relation" in codes


def test_disallowed_technical_function_rejected_by_loader():
    broken = BINDING.replace("fn: upper", "fn: trim")
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(broken, path="b.yaml")
    codes = {d.code for d in excinfo.value.diagnostics}
    assert "expression.function-not-allowed" in codes


def test_incompatible_authored_null_policy_is_rejected():
    broken = BINDING.replace("      fn: upper\n", "      fn: upper\n      nullPolicy: never-null\n")
    with pytest.raises(CompileError) as excinfo:
        adapt_binding(load_entity_binding(broken, path="b.yaml"), _context())
    assert "binding.null-policy-incompatible" in {item.code for item in excinfo.value.diagnostics}


def test_explicit_null_uses_target_property_type():
    binding = BINDING.replace(
        "expression:\n      fn: upper\n      args: [{ column: customer_name }]",
        "expression: null",
    )
    artifacts = _render(binding, _context())
    sql = artifacts["models/silver/party/customer.sql"]
    assert "NULL" in sql
    assert "as customer_name" in sql
