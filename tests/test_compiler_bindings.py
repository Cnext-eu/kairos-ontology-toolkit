# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the v5 EntityBinding schema, loader, and expression grammar (DD-133)."""

from __future__ import annotations

import textwrap
from importlib import resources

import pytest

from kairos_ontology.core.compiler import (
    ALLOWED_FUNCTIONS,
    EntityBinding,
    ExprColumn,
    ExprFunction,
    CompileError,
    load_entity_binding,
)
from kairos_ontology.core.compiler.bindings import ExprCase, ExprLiteral, ExprOperator

VALID = textwrap.dedent("""
    apiVersion: kairos.eu/v5
    kind: EntityBinding
    metadata:
      name: crm-customer-to-party
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
      - property: party:displayName
        expression:
          fn: upper
          args: [{ column: full_name }]
    """)


def _codes(exc: CompileError) -> set[str]:
    return {d.code for d in exc.diagnostics}


def test_valid_binding_parses() -> None:
    binding = load_entity_binding(VALID, path="crm.binding.yaml")
    assert isinstance(binding, EntityBinding)
    assert binding.name == "crm-customer-to-party"
    assert binding.domain == "party"
    assert binding.source.relation == "crm.customers"
    assert binding.target_class == "party:Customer"
    assert binding.identity.strategy == "source-natural"
    assert binding.identity.source_key == ("customer_id",)
    assert binding.load_mode == "full-refresh"
    # First field is a bare-column shorthand; second is an upper() function.
    assert isinstance(binding.fields[0].expression, ExprColumn)
    assert binding.fields[0].expression.column == "customer_id"
    assert isinstance(binding.fields[1].expression, ExprFunction)
    assert binding.fields[1].expression.fn == "upper"


def test_packaged_example_loads() -> None:
    text = (
        resources.files("kairos_ontology.core.compiler")
        .joinpath("schema")
        .joinpath("example-entity-binding.yaml")
        .read_text(encoding="utf-8")
    )
    binding = load_entity_binding(text, path="example-entity-binding.yaml")
    assert binding.domain == "party"
    assert binding.relationships[0].target == "ref:Country"
    assert binding.relationships[0].missing_parent == "error"
    assert binding.quality[0].kind == "not-null"


def test_unknown_top_level_field_rejected() -> None:
    bad = VALID + "extraneous: nope\n"
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="bad.yaml")
    assert "binding.schema" in _codes(excinfo.value)


def test_duplicate_key_rejected_with_location() -> None:
    dup = VALID + "target:\n  class: party:Other\n"
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(dup, path="dup.yaml")
    codes = _codes(excinfo.value)
    assert "binding.duplicate-key" in codes
    dupdiag = next(d for d in excinfo.value.diagnostics if d.code == "binding.duplicate-key")
    assert dupdiag.location.path == "dup.yaml"
    assert dupdiag.location.line > 0


def test_wrong_api_version_rejected() -> None:
    bad = VALID.replace("kairos.eu/v5", "kairos.eu/v4")
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="bad.yaml")
    assert "binding.schema" in _codes(excinfo.value)


def test_source_requires_exactly_one_of_relation_or_model() -> None:
    both = VALID.replace(
        "source:\n  relation: crm.customers",
        "source:\n  relation: crm.customers\n  dbtModel: stg_customers",
    )
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(both, path="bad.yaml")
    assert "binding.schema" in _codes(excinfo.value)


def test_missing_required_identity_rejected() -> None:
    bad = VALID.replace(
        "identity:\n  strategy: source-natural\n  sourceKey: [customer_id]\n",
        "",
    )
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="bad.yaml")
    assert "binding.schema" in _codes(excinfo.value)


def test_disallowed_function_rejected_with_pointer() -> None:
    bad = VALID.replace("fn: upper", "fn: md5")
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="bad.yaml")
    assert "expression.function-not-allowed" in _codes(excinfo.value)
    assert "md5" not in ALLOWED_FUNCTIONS
    diag = next(d for d in excinfo.value.diagnostics if d.code == "expression.function-not-allowed")
    assert diag.location.pointer.startswith("/fields/1/expression")


def test_ambiguous_expression_node_rejected() -> None:
    bad = VALID.replace(
        "    expression:\n      fn: upper\n      args: [{ column: full_name }]",
        "    expression:\n      fn: upper\n      op: eq\n      args: [{ column: full_name }]",
    )
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="bad.yaml")
    assert "expression.ambiguous" in _codes(excinfo.value)


def test_operator_case_and_literal_parse() -> None:
    doc = VALID.replace(
        "  - property: party:displayName\n"
        "    expression:\n"
        "      fn: upper\n"
        "      args: [{ column: full_name }]\n",
        "  - property: party:score\n"
        "    expression:\n"
        "      op: add\n"
        "      args:\n"
        '        - { literal: "1", datatype: "xsd:integer" }\n'
        "        - column: raw_score\n"
        "  - property: party:tier\n"
        "    expression:\n"
        "      case:\n"
        "        - when: { column: vip }\n"
        '          then: { literal: "gold", datatype: "xsd:string" }\n'
        '      else: { literal: "standard", datatype: "xsd:string" }\n',
    )
    binding = load_entity_binding(doc, path="ops.yaml")
    add_expr = binding.fields[1].expression
    assert isinstance(add_expr, ExprOperator)
    assert add_expr.op == "add"
    assert isinstance(add_expr.args[0], ExprLiteral)
    case_expr = binding.fields[2].expression
    assert isinstance(case_expr, ExprCase)
    assert case_expr.branches[0].then.lexical == "gold"


def test_literal_requires_datatype() -> None:
    bad = VALID.replace(
        "    expression:\n      fn: upper\n      args: [{ column: full_name }]",
        "    expression:\n      literal: hi",
    )
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="bad.yaml")
    assert "expression.literal-datatype" in _codes(excinfo.value)
