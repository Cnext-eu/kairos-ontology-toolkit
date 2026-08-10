# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for DD-139 authored passthrough technical columns.

DD-139 amends DD-107 with an explicit, closed-schema, authored ``technicalFields:`` construct
that materializes a source expression as a Silver output column without asserting a new
ontology property. Auto-materialization stays rejected (DD-139 explicitly parks it): a
technical field is only ever produced by an authored ``technicalFields:`` entry.

These tests cover, in order:
  * schema/loader parsing and closed-schema rejection (``bindings.py``);
  * adapter-level materialization, quality/identity resolution, and type incompatibility
    (``adapter.py``);
  * kernel-level output-name collision and duplicate-source-ambiguous safety diagnostics, an
    end-to-end compile that replaces the old "map the FK join column as a scalar field"
    workaround, and ``--explain`` labelling (``kernel.py`` / ``result.py``).
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from kairos_ontology.core.compiler import (
    CompileError,
    ExplainTechnicalField,
    ResolutionContext,
    ResolvedClass,
    ResolvedColumn,
    ResolvedProperty,
    ResolvedRelation,
    adapt_binding,
    compile_domain,
    load_entity_binding,
)
from kairos_ontology.core.compiler.bindings import ExprColumn

_NS = "https://acme.example/ontology/party#"
_IRI = "https://acme.example/ontology/party"

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
    """)


def _codes(exc: CompileError) -> set[str]:
    return {d.code for d in exc.diagnostics}


# --------------------------------------------------------------------------------------
# bindings.py: schema/loader parsing and closed-schema rejection.
# --------------------------------------------------------------------------------------
def test_technical_field_parses() -> None:
    doc = VALID + textwrap.dedent("""\
        technicalFields:
          - name: account_ref
            expression: account_id
            type: string
            nullable: true
            purpose: relationship
        """)
    binding = load_entity_binding(doc, path="technical.binding.yaml")
    assert len(binding.technical_fields) == 1
    technical_field = binding.technical_fields[0]
    assert technical_field.name == "account_ref"
    assert isinstance(technical_field.expression, ExprColumn)
    assert technical_field.expression.column == "account_id"
    assert technical_field.type == "string"
    assert technical_field.nullable is True
    assert technical_field.purpose == "relationship"


def test_technical_field_is_closed_schema() -> None:
    doc = VALID + textwrap.dedent("""\
        technicalFields:
          - name: account_ref
            expression: account_id
            type: string
            nullable: true
            purpose: relationship
            unexpected: nope
        """)
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(doc, path="bad.yaml")
    assert "binding.schema" in _codes(excinfo.value)


@pytest.mark.parametrize("missing", ["name", "expression", "type", "nullable", "purpose"])
def test_technical_field_requires_every_field(missing: str) -> None:
    fields = {
        "name": "account_ref",
        "expression": "account_id",
        "type": "string",
        "nullable": "true",
        "purpose": "relationship",
    }
    fields.pop(missing)
    body = "\n    ".join(f"{key}: {value}" for key, value in fields.items())
    doc = VALID + f"technicalFields:\n  - {body}\n"
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(doc, path="bad.yaml")
    assert "binding.schema" in _codes(excinfo.value)


@pytest.mark.parametrize("bad_type", ["varchar", "int", "INT32", ""])
def test_technical_field_type_is_a_closed_enum(bad_type: str) -> None:
    doc = VALID + textwrap.dedent(f"""\
        technicalFields:
          - name: account_ref
            expression: account_id
            type: "{bad_type}"
            nullable: true
            purpose: relationship
        """)
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(doc, path="bad.yaml")
    assert "binding.schema" in _codes(excinfo.value)


def test_technical_field_type_enum_matches_canonical_type_kind() -> None:
    """The schema's ``technicalFields[].type`` enum must equal the full
    ``CanonicalTypeKind`` vocabulary so the two cannot drift again (DD-107/DD-139).

    Previously the enum listed only 7 of the 12 canonical kinds, so tokens the
    normalizer accepts (e.g. ``float64``) were rejected by the schema.
    """
    from kairos_ontology.core.compiler.bindings import _load_schema
    from kairos_ontology.core.projections.dbt.policy_normalize import CanonicalTypeKind

    schema = _load_schema()
    enum = set(schema["definitions"]["technicalField"]["properties"]["type"]["enum"])
    assert enum == {kind.value for kind in CanonicalTypeKind}


@pytest.mark.parametrize("token", ["int16", "float64", "time", "binary", "json"])
def test_technical_field_accepts_previously_missing_canonical_tokens(token: str) -> None:
    """Canonical kinds that the earlier 7-token enum omitted now parse."""
    doc = VALID + textwrap.dedent(f"""\
        technicalFields:
          - name: account_ref
            expression: account_id
            type: {token}
            nullable: true
            purpose: relationship
        """)
    binding = load_entity_binding(doc, path="technical.binding.yaml")
    assert binding.technical_fields[0].type == token


@pytest.mark.parametrize("bad_purpose", ["technical", "join", ""])
def test_technical_field_purpose_is_a_closed_enum(bad_purpose: str) -> None:
    doc = VALID + textwrap.dedent(f"""\
        technicalFields:
          - name: account_ref
            expression: account_id
            type: string
            nullable: true
            purpose: "{bad_purpose}"
        """)
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(doc, path="bad.yaml")
    assert "binding.schema" in _codes(excinfo.value)


def test_technical_field_reuses_the_closed_expression_grammar() -> None:
    """A disallowed function inside a technicalFields expression is rejected identically."""
    doc = VALID + textwrap.dedent("""\
        technicalFields:
          - name: account_ref
            expression:
              fn: md5
              args: [{ column: account_id }]
            type: string
            nullable: true
            purpose: relationship
        """)
    with pytest.raises(CompileError) as excinfo:
        load_entity_binding(doc, path="bad.yaml")
    assert "expression.function-not-allowed" in _codes(excinfo.value)


# --------------------------------------------------------------------------------------
# adapter.py: materialization, quality/identity resolution, type incompatibility.
# --------------------------------------------------------------------------------------
def _context() -> ResolutionContext:
    return ResolutionContext(
        domain="party",
        namespace=_NS,
        ontology_name="party",
        ontology_iri=_IRI,
        ontology_version="0.1.0",
        template_root=str(
            Path(__file__).resolve().parents[1]
            / "src"
            / "kairos_ontology"
            / "templates"
            / "dbt"
        ),
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
                    ResolvedColumn("account_id", "varchar(50)", nullable=True),
                ),
            ),
        ),
        classes=(
            ResolvedClass(ref="party:Customer", uri=f"{_NS}Customer", name="Customer"),
        ),
        properties=(
            ResolvedProperty(
                ref="party:customerId",
                uri=f"{_NS}customerId",
                column_name="customer_id",
                data_type="string",
            ),
        ),
    )


TECHNICAL_FIELD = textwrap.dedent("""\
    technicalFields:
      - name: account_ref
        expression: account_id
        type: string
        nullable: true
        purpose: relationship
    """)


def test_technical_field_materializes_as_a_silver_column() -> None:
    from kairos_ontology.core.projections.dbt import (
        normalize_contract,
        plan_materialization,
        render_project,
        shape_project,
    )
    from kairos_ontology.core.projections.dbt.diagnostics import ExecutionMode

    binding = load_entity_binding(VALID + TECHNICAL_FIELD, path="crm.binding.yaml")
    bound = adapt_binding(binding, _context())
    contract = normalize_contract(bound, ExecutionMode.FAIL_FAST)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    artifacts = render_project(shaped, plan)
    sql = artifacts["models/silver/party/customer.sql"]
    assert "account_id" in sql
    assert "account_ref" in sql


def test_technical_field_satisfies_quality_column_materialization() -> None:
    doc = VALID + TECHNICAL_FIELD + "quality:\n  - kind: not-null\n    columns: [account_id]\n"
    binding = load_entity_binding(doc, path="crm.binding.yaml")
    bound = adapt_binding(binding, _context())
    mapping = next(
        item for item in bound.mappings.columns if item.target_column_name == "account_ref"
    )
    assert "not_null" in next(
        column.tests
        for model in bound.silver_candidates
        for column in model.columns
        if column.mapping_resource_uri == mapping.resource_uri
    )


def test_technical_field_satisfies_identity_key_materialization() -> None:
    doc = VALID.replace(
        "identity:\n  strategy: source-natural\n  sourceKey: [customer_id]\n",
        "identity:\n  strategy: source-natural\n  sourceKey: [customer_id]\n"
        "  businessKey: [account_id]\n",
    )
    doc = doc + TECHNICAL_FIELD
    binding = load_entity_binding(doc, path="crm.binding.yaml")
    # Must not raise identity.authored-key-not-supplied: the technical field materializes
    # the business-key source column even though it maps no ontology property.
    bound = adapt_binding(binding, _context())
    assert bound.policy_facts.identities[0].natural_keys.values == ("account_ref",)


def test_technical_field_type_incompatible_with_physical_column_is_rejected() -> None:
    doc = VALID + textwrap.dedent("""\
        technicalFields:
          - name: account_ref
            expression: account_id
            type: int32
            nullable: true
            purpose: relationship
        """)
    binding = load_entity_binding(doc, path="crm.binding.yaml")
    with pytest.raises(CompileError) as excinfo:
        adapt_binding(binding, _context())
    diagnostic = next(
        item for item in excinfo.value.diagnostics if item.code == "technical-field.type-incompatible"
    )
    assert "account_ref" in diagnostic.message
    assert diagnostic.location.pointer == "/technicalFields/0/type"


@pytest.mark.parametrize(
    "token,kind",
    [
        ("int32", "int32"),
        ("int64", "int64"),
        ("string", "string"),
        ("decimal", "decimal"),
        ("date", "date"),
        ("timestamp", "timestamp"),
        ("boolean", "boolean"),
    ],
)
def test_target_type_resolves_canonical_kind_tokens(token: str, kind: str) -> None:
    """`_target_type` must accept the canonical kind tokens the entity-binding schema
    enum allows (e.g. ``int32``/``int64``), not only XSD IRIs and SQL aliases.

    Regression guard for the schema/normalizer vocabulary mismatch where
    ``technicalFields[].type: int32`` compiled to ``mapping.unknown-target-type``.
    """
    from kairos_ontology.core.projections.dbt.policy_normalize import (
        CanonicalTypeKind,
        _target_type,
    )

    spec = _target_type(token)
    assert spec is not None
    assert spec.kind is CanonicalTypeKind(kind)


def test_technical_field_canonical_kind_token_compiles_for_integer_source() -> None:
    """An ``int32`` technicalField over a physical ``int`` source column must compile.

    Before the fix, the schema-allowed ``int32`` token reached the normalizer and raised
    ``mapping.unknown-target-type``; the SQL alias ``int`` was rejected by the schema enum.
    This test pins the resolved happy path end-to-end through ``adapt_binding`` with an
    integer-typed primary key and identity-claim technical field.
    """
    context = ResolutionContext(
        domain="party",
        namespace=_NS,
        ontology_name="party",
        ontology_iri=_IRI,
        ontology_version="0.1.0",
        template_root=str(
            Path(__file__).resolve().parents[1]
            / "src"
            / "kairos_ontology"
            / "templates"
            / "dbt"
        ),
        target_platform="fabric",
        relations=(
            ResolvedRelation(
                ref="crm.customers",
                uri="https://acme.example/bronze/crm#customers",
                system_label="crm",
                table_name="customers",
                columns=(
                    ResolvedColumn("customer_id", "int", nullable=False, is_primary_key=True),
                    ResolvedColumn("account_id", "varchar(50)", nullable=True),
                ),
            ),
        ),
        classes=(
            ResolvedClass(ref="party:Customer", uri=f"{_NS}Customer", name="Customer"),
        ),
        properties=(
            ResolvedProperty(
                ref="party:customerId",
                uri=f"{_NS}customerId",
                column_name="customer_id",
                data_type="int32",
            ),
        ),
    )
    doc = textwrap.dedent("""
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
          strategy: surrogate
          sourceKey: [customer_id]
        load:
          mode: full-refresh
        fields:
          - property: party:customerId
            expression: customer_id
        technicalFields:
          - name: source_id
            expression: customer_id
            type: int32
            nullable: false
            purpose: identity
        """)
    binding = load_entity_binding(doc, path="crm.binding.yaml")
    bound = adapt_binding(binding, context)
    mapping = next(
        item for item in bound.mappings.columns if item.target_column_name == "source_id"
    )
    assert mapping.target_data_type == "int32"
    assert not mapping.target_is_object_property


def test_technical_field_is_not_emitted_as_an_ontology_property() -> None:
    """The synthetic technical marker URI is never mistaken for a real ontology property."""
    binding = load_entity_binding(VALID + TECHNICAL_FIELD, path="crm.binding.yaml")
    bound = adapt_binding(binding, _context())
    mapping = next(
        item for item in bound.mappings.columns if item.target_column_name == "account_ref"
    )
    assert not mapping.target_is_object_property
    assert mapping.target_property_uri != f"{_NS}account_ref"
    assert "technical" in mapping.target_property_uri


# --------------------------------------------------------------------------------------
# kernel.py / result.py: safety diagnostics, end-to-end compile, and --explain labelling.
# --------------------------------------------------------------------------------------
def _hub(tmp_path: Path) -> Path:
    scenario = Path(__file__).parent / "scenarios" / "v5-hub"
    hub = tmp_path / "hub"
    shutil.copytree(scenario, hub)
    return hub


def _customer_binding_path(hub: Path) -> Path:
    return hub / "integration" / "bindings" / "customer.binding.yaml"


def _replace_country_code_field_with_technical_field(hub: Path, *, name: str = "country_code") -> None:
    """Swap the old DD-107 "map the FK join column as a scalar field" workaround for DD-139."""
    binding_path = _customer_binding_path(hub)
    text = binding_path.read_text(encoding="utf-8")
    text = text.replace(
        "  - property: party:country_code\n    expression: country_code\n",
        "",
    )
    text += textwrap.dedent(f"""\
        technicalFields:
          - name: {name}
            expression: country_code
            type: string
            nullable: true
            purpose: relationship
        """)
    binding_path.write_text(text, encoding="utf-8")


def test_technical_field_replaces_the_scalar_field_workaround_and_compiles_cleanly(
    tmp_path: Path,
) -> None:
    hub = _hub(tmp_path)
    _replace_country_code_field_with_technical_field(hub)

    result = compile_domain(hub, "party")

    assert result.succeeded, result.diagnostics.items
    sql = result.artifact_dict()["models/silver/party/customer.sql"]
    assert "country_code" in sql
    entity = next(item for item in result.explain.entities if item.name == "crm-customer")
    assert entity.technical_fields == (
        ExplainTechnicalField(
            name="country_code",
            expression="country_code",
            type="string",
            nullable=True,
            purpose="relationship",
        ),
    )
    # A technical field is never an ontology property: it must not also show up in the
    # semantic `fields` explain pairs.
    assert "party:country_code" not in {prop for prop, _ in entity.fields}


def test_technical_field_output_collision_with_semantic_field_is_rejected(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    binding_path = _customer_binding_path(hub)
    text = binding_path.read_text(encoding="utf-8")
    # "customer_id" is already the output column of party:customer_id.
    text += textwrap.dedent("""\
        technicalFields:
          - name: customer_id
            expression: country_code
            type: string
            nullable: true
            purpose: relationship
        """)
    binding_path.write_text(text, encoding="utf-8")

    result = compile_domain(hub, "party")

    assert not result.succeeded
    assert "technical-field.output-collision" in {item.code for item in result.diagnostics.items}


def test_technical_field_duplicate_source_ambiguous_purpose_is_rejected(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    binding_path = _customer_binding_path(hub)
    text = binding_path.read_text(encoding="utf-8")
    text += textwrap.dedent("""\
        technicalFields:
          - name: country_code_technical_a
            expression: country_code
            type: string
            nullable: true
            purpose: relationship
          - name: country_code_technical_b
            expression: country_code
            type: string
            nullable: true
            purpose: relationship
        """)
    binding_path.write_text(text, encoding="utf-8")

    result = compile_domain(hub, "party")

    assert not result.succeeded
    codes = {item.code for item in result.diagnostics.items}
    assert "technical-field.duplicate-source-ambiguous" in codes


def test_technical_field_distinct_purposes_allow_duplicate_source_reuse(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    binding_path = _customer_binding_path(hub)
    text = binding_path.read_text(encoding="utf-8")
    text += textwrap.dedent("""\
        technicalFields:
          - name: country_code_relationship
            expression: country_code
            type: string
            nullable: true
            purpose: relationship
          - name: country_code_quality
            expression: country_code
            type: string
            nullable: true
            purpose: quality
        """)
    binding_path.write_text(text, encoding="utf-8")

    result = compile_domain(hub, "party")

    assert result.succeeded, result.diagnostics.items
