# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the v5 EntityBinding schema, loader, and expression grammar (DD-133)."""

from __future__ import annotations

import textwrap
from dataclasses import FrozenInstanceError
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


def _packaged_example_text() -> str:
    return (
        resources.files("kairos_ontology.core.compiler")
        .joinpath("schema")
        .joinpath("example-entity-binding.yaml")
        .read_text(encoding="utf-8")
    )


def test_packaged_example_loads() -> None:
    text = _packaged_example_text()
    binding = load_entity_binding(text, path="example-entity-binding.yaml")
    assert binding.domain == "party"
    assert binding.relationships[0].target == "ref:Country"
    assert binding.relationships[0].missing_parent == "error"
    assert binding.load.mode == "incremental"
    assert binding.load.scd == 2
    assert binding.load.incremental is not None
    assert binding.load.incremental.canonical_hash_inputs == ("customer_id", "full_name", "country")
    assert binding.relationships[0].temporal is not None
    assert binding.relationships[0].temporal.child_event_time == "effective_at"
    assert binding.conformance is not None
    assert binding.conformance.union.mode == "deduplicate"
    assert binding.quality[0].kind == "not-null"
    assert binding.technical_fields[0].name == "account_ref"
    assert binding.technical_fields[0].purpose == "relationship"
    assert binding.technical_fields[0].type == "string"
    # #337: the cross-domain externalReference relationship previously authored
    # `missingParent: null` (unquoted YAML null, not the string enum token "null") and
    # `ambiguousParent: first` (schema-valid but rejected by the adapter -- see
    # test_compiler_kernel.py / test_wire_relationships_diagnostics.py for the
    # `safety.adapter-unsupported` coverage of that rejection). The canonical example an
    # author copies from must use values that are both schema-valid AND actually supported.
    assert binding.relationships[1].target == "billing:Account"
    assert binding.relationships[1].missing_parent == "null"
    assert binding.relationships[1].ambiguous_parent == "error"


def test_packaged_example_validates_against_its_own_raw_json_schema() -> None:
    """#337: the shipped example must be valid against the shipped schema on its own terms.

    ``load_entity_binding`` silently aliases an unquoted YAML ``null`` to the string enum
    token ``"null"`` for ``missingParent`` (see ``_alias_null_tokens``) before ever handing
    the document to ``jsonschema``, so loading successfully is not proof the document is
    schema-valid -- an author (or any external tool) validating the raw YAML straight
    against ``entity-binding.schema.json`` would still see the failure. Exercise the schema
    validator directly, bypassing the loader's coercion, to close that gap.
    """
    import yaml
    from jsonschema import Draft7Validator

    from kairos_ontology.core.compiler.bindings import _load_schema

    document = yaml.safe_load(_packaged_example_text())
    validator = Draft7Validator(_load_schema())
    errors = list(validator.iter_errors(document))
    assert errors == [], [e.message for e in errors]


def test_external_reference_relationship_parses_closed_key_contract() -> None:
    doc = (
        VALID
        + """\
relationships:
  - property: party:account
    target: billing:Account
    externalReference:
      name: account
      domain: billing
      key:
        - column: account_id
          type: string
    join:
      - local: customer_id
        foreign: account_id
    cardinality: many-to-one
    mode: non-temporal
    missingParent: error
    ambiguousParent: error
"""
    )
    binding = load_entity_binding(doc, path="external.binding.yaml")
    relationship = binding.relationships[0]
    assert relationship.external_reference is not None
    assert relationship.external_reference.name == "account"
    assert relationship.external_reference.domain == "billing"
    assert relationship.external_reference.key[0].column == "account_id"
    assert relationship.external_reference.key[0].type == "string"


@pytest.mark.parametrize(
    "bad",
    [
        "      unexpected: nope\n      key:",
        "      key:\n        - column: account_id\n          unexpected: nope\n",
        "      key:\n        - type: string\n",
    ],
)
def test_external_reference_relationship_is_closed(bad: str) -> None:
    valid_external = """\
relationships:
  - property: party:account
    target: billing:Account
    externalReference:
      name: account
      domain: billing
      key:
        - column: account_id
          type: string
    join:
      - local: customer_id
        foreign: account_id
    cardinality: many-to-one
    mode: non-temporal
    missingParent: error
    ambiguousParent: error
"""
    bad_doc = VALID + valid_external.replace("      key:", bad, 1)
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad_doc, path="external.binding.yaml")
    assert "binding.schema" in _codes(excinfo.value)


def test_unknown_top_level_field_rejected() -> None:
    bad = VALID + "extraneous: nope\n"
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="bad.yaml")
    assert "binding.schema" in _codes(excinfo.value)


_NON_TEMPORAL_REL = """\
relationships:
  - property: party:hasCountry
    target: ref:Country
    join:
      - local: country
        foreign: iso2
    cardinality: many-to-one
    mode: non-temporal
    missingParent: error
    ambiguousParent: error
"""


def test_missing_parent_accepts_yaml_null_alias() -> None:
    doc = VALID + _NON_TEMPORAL_REL.replace("missingParent: error", "missingParent: null")
    binding = load_entity_binding(doc, path="rel.binding.yaml")
    assert binding.relationships[0].missing_parent == "null"


def test_invalid_missing_parent_reports_precise_enum_message() -> None:
    doc = VALID + _NON_TEMPORAL_REL.replace("missingParent: error", "missingParent: maybe")
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(doc, path="rel.binding.yaml")
    messages = [d.message for d in excinfo.value.diagnostics]
    assert any("'maybe' is not one of" in message for message in messages)
    # The opaque anyOf/oneOf fallback message must no longer leak through.
    assert all("given schemas" not in message for message in messages)
    assert any(diag.location.line > 0 for diag in excinfo.value.diagnostics)


def test_ambiguous_parent_does_not_accept_null_alias() -> None:
    doc = VALID + _NON_TEMPORAL_REL.replace("ambiguousParent: error", "ambiguousParent: null")
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(doc, path="rel.binding.yaml")
    assert "binding.schema" in _codes(excinfo.value)
    assert any("['error', 'first']" in diag.message for diag in excinfo.value.diagnostics)


@pytest.mark.parametrize(
    ("document", "code"),
    [
        ("- not\n- a\n- mapping\n", "binding.not-a-mapping"),
        ("metadata: [\n", "binding.yaml"),
    ],
)
def test_invalid_document_shapes_have_stable_loader_codes(document: str, code: str) -> None:
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(document, path="invalid.binding.yaml")

    diagnostic = excinfo.value.diagnostics[0]
    assert diagnostic.code == code
    assert diagnostic.location.path == "invalid.binding.yaml"


@pytest.mark.parametrize(
    "bad",
    [
        VALID.replace("metadata:\n  name:", "metadata:\n  unknown: nope\n  name:"),
        VALID.replace("source:\n  relation:", "source:\n  unknown: nope\n  relation:"),
        VALID.replace("identity:\n  strategy:", "identity:\n  unknown: nope\n  strategy:"),
        VALID.replace("load:\n  mode:", "load:\n  unknown: nope\n  mode:"),
    ],
)
def test_nested_binding_objects_are_closed(bad: str) -> None:
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="closed.binding.yaml")

    diagnostic = next(item for item in excinfo.value.diagnostics if item.code == "binding.schema")
    assert diagnostic.location.path == "closed.binding.yaml"
    assert diagnostic.location.pointer


@pytest.mark.parametrize(
    "quality",
    [
        "  - kind: invented\n",
        "  - kind: unique\n    columns: [customer_id, 7]\n",
        "  - kind: not-null\n    unknown: nope\n",
    ],
)
def test_quality_checks_are_closed_and_typed(quality: str) -> None:
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(VALID + "quality:\n" + quality, path="quality.binding.yaml")

    diagnostic = next(item for item in excinfo.value.diagnostics if item.code == "binding.schema")
    assert diagnostic.location.path == "quality.binding.yaml"
    assert diagnostic.location.pointer.startswith("/quality")


def test_duplicate_key_rejected_with_location() -> None:
    dup = VALID + "target:\n  class: party:Other\n"
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(dup, path="dup.yaml")
    codes = _codes(excinfo.value)
    assert "binding.duplicate-key" in codes
    dupdiag = next(d for d in excinfo.value.diagnostics if d.code == "binding.duplicate-key")
    assert dupdiag.location.path == "dup.yaml"
    assert dupdiag.location.line > 0


def test_unsupported_api_version_rejected() -> None:
    bad = VALID.replace("kairos.eu/v5", "kairos.eu/v6")
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


def test_contracted_dbt_model_source_parses_as_frozen_metadata() -> None:
    doc = VALID.replace(
        "source:\n  relation: crm.customers",
        "source:\n"
        "  dbtModel:\n"
        "    name: int_customer\n"
        "    sqlPath: integration/transforms/dbt/models/int_customer.sql\n"
        "    contractPath: integration/transforms/dbt/models/schema.yml",
    )
    binding = load_entity_binding(doc, path="dbt.binding.yaml")
    assert binding.source.dbt_model is not None
    assert binding.source.dbt_model.name == "int_customer"
    with pytest.raises(FrozenInstanceError):
        binding.source.dbt_model.name = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("missing", ["name", "sqlPath", "contractPath"])
def test_contracted_dbt_model_requires_complete_metadata(missing: str) -> None:
    metadata = {
        "name": "int_customer",
        "sqlPath": "models/int_customer.sql",
        "contractPath": "models/schema.yml",
    }
    metadata.pop(missing)
    lines = "\n".join(f"    {key}: {value}" for key, value in metadata.items())
    doc = VALID.replace(
        "source:\n  relation: crm.customers",
        f"source:\n  dbtModel:\n{lines}",
    )
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(doc, path="dbt.binding.yaml")
    assert "binding.schema" in _codes(excinfo.value)
    assert any(diag.location.line > 0 for diag in excinfo.value.diagnostics)


def test_missing_required_identity_rejected() -> None:
    bad = VALID.replace(
        "identity:\n  strategy: source-natural\n  sourceKey: [customer_id]\n",
        "",
    )
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="bad.yaml")
    assert "binding.schema" in _codes(excinfo.value)


INCREMENTAL_LOAD = """\
load:
  mode: incremental
  scd: 2
  incremental:
    mergeIdentity: [customer_id]
    canonicalHashInputs: [customer_id, full_name]
    cdcOperation:
      column: operation
      insertValues: [I]
      updateValues: [U]
      deleteValues: [D]
    sourceUpdatedAt: source_updated_at
    businessEffectiveAt: effective_at
    ingestedAt: ingested_at
    totalOrder: [source_updated_at, sequence_number]
    lookback: {value: 1, unit: days}
    delete: soft-delete
    lateArrival: accept
    correction: new-version
    replay: idempotent
    backfill: merge
    schemaEvolution: fail
"""


def _incremental() -> str:
    return VALID.replace("load:\n  mode: full-refresh\n", INCREMENTAL_LOAD)


@pytest.mark.parametrize("scd", [1, 2])
def test_incremental_scd_contract_parses(scd: int) -> None:
    correction = "overwrite" if scd == 1 else "new-version"
    binding = load_entity_binding(
        _incremental()
        .replace("  scd: 2", f"  scd: {scd}")
        .replace("correction: new-version", f"correction: {correction}"),
        path="incremental.binding.yaml",
    )
    assert binding.load.scd == scd
    assert binding.load.incremental is not None
    assert binding.load.incremental.cdc_operation.delete_values == ("D",)
    assert binding.load.incremental.lookback.value == 1


@pytest.mark.parametrize(
    ("scd", "correction"),
    [(1, "new-version"), (2, "overwrite")],
)
def test_incremental_rejects_scd_correction_ambiguity(scd: int, correction: str) -> None:
    bad = (
        _incremental()
        .replace("  scd: 2", f"  scd: {scd}")
        .replace("correction: new-version", f"correction: {correction}")
    )
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="incremental.binding.yaml")
    assert "binding.scd-correction-incompatible" in _codes(excinfo.value)


@pytest.mark.parametrize(
    "field",
    [
        "mergeIdentity",
        "canonicalHashInputs",
        "cdcOperation",
        "sourceUpdatedAt",
        "businessEffectiveAt",
        "ingestedAt",
        "totalOrder",
        "lookback",
        "delete",
        "lateArrival",
        "correction",
        "replay",
        "backfill",
        "schemaEvolution",
    ],
)
def test_incremental_policy_rejects_every_missing_required_field(field: str) -> None:
    lines = _incremental().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"    {field}:"))
    end = start + 1
    while end < len(lines) and len(lines[end]) - len(lines[end].lstrip()) > 4:
        end += 1
    bad = "\n".join(lines[:start] + lines[end:]) + "\n"
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="incremental.binding.yaml")
    assert "binding.schema" in _codes(excinfo.value)


def test_full_refresh_rejects_scd_or_incremental_policy() -> None:
    bad = VALID.replace("load:\n  mode: full-refresh", "load:\n  mode: full-refresh\n  scd: 1")
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="full.binding.yaml")
    assert "binding.schema" in _codes(excinfo.value)


def test_ambiguous_cdc_values_rejected_at_source_location() -> None:
    bad = _incremental().replace("updateValues: [U]", "updateValues: [I]")
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="incremental.binding.yaml")
    diag = next(
        item for item in excinfo.value.diagnostics if item.code == "binding.cdc-operation-ambiguous"
    )
    assert diag.location.path == "incremental.binding.yaml"
    assert diag.location.pointer.endswith("/updateValues")
    assert diag.location.line > 0


TEMPORAL_RELATIONSHIP = """\
relationships:
  - property: party:hasCountry
    target: ref:Country
    join: [{local: country, foreign: iso2}]
    cardinality: many-to-one
    mode: as-of
    missingParent: error
    ambiguousParent: error
    temporal:
      childEventTime: effective_at
      parentValidFrom: valid_from
      parentValidTo: valid_to
      openEnded: null
      overlap: error
      lateParent: defer
      changeDetection: include
"""


def test_as_of_relationship_requires_and_parses_complete_temporal_policy() -> None:
    binding = load_entity_binding(VALID + TEMPORAL_RELATIONSHIP, path="temporal.binding.yaml")
    relationship = binding.relationships[0]
    assert relationship.mode == "as-of"
    assert relationship.temporal is not None
    assert relationship.temporal.late_parent == "defer"


def test_current_relationship_rejects_as_of_child_event_time() -> None:
    bad = (VALID + TEMPORAL_RELATIONSHIP).replace("mode: as-of", "mode: current")
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="temporal.binding.yaml")
    assert "binding.schema" in _codes(excinfo.value)


def test_current_relationship_parses_complete_temporal_policy() -> None:
    doc = (
        (VALID + TEMPORAL_RELATIONSHIP)
        .replace("mode: as-of", "mode: current")
        .replace("      childEventTime: effective_at\n", "")
    )
    binding = load_entity_binding(doc, path="current.binding.yaml")
    relationship = binding.relationships[0]
    assert relationship.mode == "current"
    assert relationship.temporal is not None
    assert relationship.temporal.child_event_time == ""


def test_non_temporal_relationship_rejects_temporal_policy() -> None:
    bad = (VALID + TEMPORAL_RELATIONSHIP).replace("mode: as-of", "mode: non-temporal")
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="temporal.binding.yaml")
    assert "binding.schema" in _codes(excinfo.value)


def test_conformance_dedup_policy_parses() -> None:
    doc = (
        VALID
        + """\
conformance:
  group: party-customer
  sourcePrecedence: 2
  conflict: prefer-precedence
  union:
    mode: deduplicate
    deduplicateBy: [customer_id]
    orderBy: [{column: source_updated_at, direction: descending}]
"""
    )
    binding = load_entity_binding(doc, path="conformance.binding.yaml")
    assert binding.conformance is not None
    assert binding.conformance.source_precedence == 2
    assert binding.conformance.union.order_by[0].direction == "descending"


def test_conformance_dedup_rejects_incomplete_ordering() -> None:
    bad = (
        VALID
        + """\
conformance:
  group: party-customer
  sourcePrecedence: 1
  conflict: error
  union:
    mode: deduplicate
    deduplicateBy: [customer_id]
"""
    )
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="conformance.binding.yaml")
    assert "binding.schema" in _codes(excinfo.value)


def test_conformance_union_all_is_closed_and_typed() -> None:
    doc = (
        VALID
        + """\
conformance:
  group: party-customer
  sourcePrecedence: 1
  conflict: error
  union:
    mode: union-all
"""
    )
    binding = load_entity_binding(doc, path="conformance.binding.yaml")
    assert binding.conformance is not None
    assert binding.conformance.union.deduplicate_by == ()
    assert binding.conformance.union.order_by == ()


def test_unknown_expression_field_rejected() -> None:
    bad = VALID.replace("fn: upper", "fn: upper\n      sql: forbidden")
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(bad, path="expression.binding.yaml")
    assert "expression.unknown-field" in _codes(excinfo.value)


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
