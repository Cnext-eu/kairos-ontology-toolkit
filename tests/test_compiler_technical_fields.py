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
            Path(__file__).resolve().parents[1] / "src" / "kairos_ontology" / "templates" / "dbt"
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
        classes=(ResolvedClass(ref="party:Customer", uri=f"{_NS}Customer", name="Customer"),),
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


def test_uppercase_technical_field_identity_key_matches_case_insensitively() -> None:
    """#337: DD-108 identity-key matching used to be case-sensitive against a lowercased
    naturalKey expectation, while a ``technicalFields:`` remedy's emitted output column
    keeps whatever case the author chose for ``name:`` (unlike a ``fields:`` entry, whose
    output column is always forced to the ontology property's already-snake-cased name).
    A business identity key materialized via an upper-case technicalFields entry -- a common
    convention when passing a legacy vendor column like ``GC_PK`` straight through -- used to
    fail DD-108 identity validation purely over letter case, with a message that never even
    mentioned case. The match must be case-insensitive.
    """
    from kairos_ontology.core.projections.dbt import normalize_contract
    from kairos_ontology.core.projections.dbt.diagnostics import ExecutionMode

    context = ResolutionContext(
        domain="party",
        namespace=_NS,
        ontology_name="party",
        ontology_iri=_IRI,
        ontology_version="0.1.0",
        template_root=str(
            Path(__file__).resolve().parents[1] / "src" / "kairos_ontology" / "templates" / "dbt"
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
                    ResolvedColumn("GC_PK", "varchar(50)", nullable=False),
                ),
            ),
        ),
        classes=(ResolvedClass(ref="party:Customer", uri=f"{_NS}Customer", name="Customer"),),
        properties=(
            ResolvedProperty(
                ref="party:customerId",
                uri=f"{_NS}customerId",
                column_name="customer_id",
                data_type="string",
            ),
        ),
    )
    doc = VALID.replace(
        "identity:\n  strategy: source-natural\n  sourceKey: [customer_id]\n",
        "identity:\n  strategy: source-natural\n  sourceKey: [customer_id]\n"
        "  businessKey: [GC_PK]\n",
    ) + textwrap.dedent("""\
        technicalFields:
          - name: GC_PK
            expression: GC_PK
            type: string
            nullable: false
            purpose: identity
        """)
    binding = load_entity_binding(doc, path="crm.binding.yaml")
    bound = adapt_binding(binding, context)
    assert bound.policy_facts.identities[0].natural_keys.values == ("GC_PK",)
    # Must not raise identity.authored-key-not-supplied (nor the generic
    # safety.type-incompatible it used to get flattened into): the upper-case technicalFields
    # output satisfies the (lower-cased) identity key case-insensitively.
    contract = normalize_contract(bound, ExecutionMode.FAIL_FAST)
    assert contract is not None


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
        item
        for item in excinfo.value.diagnostics
        if item.code == "technical-field.type-incompatible"
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
            Path(__file__).resolve().parents[1] / "src" / "kairos_ontology" / "templates" / "dbt"
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
        classes=(ResolvedClass(ref="party:Customer", uri=f"{_NS}Customer", name="Customer"),),
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


def _replace_country_code_field_with_technical_field(
    hub: Path, *, name: str = "country_code"
) -> None:
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


# --------------------------------------------------------------------------------------
# kernel.py: the DD-139 ``join.foreign`` clause (#334) and the two relationship guards it
# requires (#334 self-reference, #335 same-domain ``externalReference``).
#
# DD-139 recorded "``identity.sourceKey``/``quality.columns``/relationship
# ``join.local``/``join.foreign`` now resolve against authored technical fields exactly as they
# do against ``fields:``" as implemented. For ``join.foreign`` that was false:
# ``_relationship_output_column`` iterated ``binding.fields`` only, so a parent join column
# carried by a technical field -- the normal shape of a surrogate technical primary key -- was
# rejected and its relationship silently dropped.
# --------------------------------------------------------------------------------------
def _country_binding_path(hub: Path) -> Path:
    return hub / "integration" / "bindings" / "country.binding.yaml"


def _carry_parent_join_column_as_technical_fields(hub: Path, *entries: tuple[str, str]) -> None:
    """Drop mapped ``party:code`` and carry the parent join column as technical field(s).

    ``party:code`` is the only reason ``join.foreign: code`` resolves in the stock hub. Once it
    is gone the customer -> country join endpoint is carried exclusively by authored
    ``technicalFields:``, which is exactly the DD-139 clause under test. ``entries`` are
    ``(output name, purpose)`` pairs, all bound to the same source column ``code``.
    """
    path = _country_binding_path(hub)
    text = path.read_text(encoding="utf-8").replace(
        "  - property: party:code\n    expression: code\n", ""
    )
    text += "technicalFields:\n"
    for name, purpose in entries:
        text += textwrap.dedent(f"""\
            - name: {name}
              expression: code
              type: string
              nullable: false
              purpose: {purpose}
            """)
    path.write_text(text, encoding="utf-8")


def test_technical_field_supplies_a_relationship_join_foreign_column(tmp_path: Path) -> None:
    """FAILS before #334: rejected as ``safety.relationship-endpoint`` "not mapped by the target
    binding".

    Asserts the emitted predicate, not merely that the compile is green -- a binding whose
    relationships were all dropped also compiles green.
    """
    hub = _hub(tmp_path)
    _carry_parent_join_column_as_technical_fields(hub, ("code", "relationship"))

    result = compile_domain(hub, "party")

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    sql = result.artifact_dict()["models/silver/party/customer.sql"].lower()
    assert "left join {{ ref('country') }}" in sql
    assert "[src].[country_code] = [country].[code]" in sql


def test_renamed_technical_field_join_uses_its_output_name_not_its_source_column(
    tmp_path: Path,
) -> None:
    """FAILS before #334 (rejected outright); also fails any verbatim ``join.foreign`` lookup.

    A technical field renames: ``name`` is the emitted output column while ``expression`` binds
    the source column the author writes as ``join.foreign``. The predicate must reference the
    output name -- emitting the source name yields a column the parent model does not have.
    """
    hub = _hub(tmp_path)
    _carry_parent_join_column_as_technical_fields(hub, ("country_pk", "relationship"))

    result = compile_domain(hub, "party")

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    artifacts = result.artifact_dict()
    customer_sql = artifacts["models/silver/party/customer.sql"].lower()
    assert "[src].[country_code] = [country].[country_pk]" in customer_sql
    assert "[country].[code]" not in customer_sql
    # The parent really does emit the output name rather than the source name.
    assert "country_pk" in artifacts["models/silver/party/country.sql"]


def test_ambiguous_technical_fields_for_one_join_foreign_column_are_rejected(
    tmp_path: Path,
) -> None:
    """FAILS before #334: today's code reports ``safety.relationship-endpoint`` instead.

    ``(source column, purpose)`` is the technical-field uniqueness key, so one source column
    legally carries two technical fields with two different output names. The join has no rule
    to choose between them, so it must say so rather than silently take the first.
    """
    hub = _hub(tmp_path)
    _carry_parent_join_column_as_technical_fields(
        hub, ("code_for_relationship", "relationship"), ("code_for_quality", "quality")
    )

    result = compile_domain(hub, "party")

    assert not result.succeeded
    ambiguous = [
        item
        for item in result.diagnostics.items
        if item.code == "technical-field.relationship-target-ambiguous"
    ]
    assert ambiguous, [item.render() for item in result.diagnostics.items]
    assert "code_for_relationship" in ambiguous[0].message
    assert "code_for_quality" in ambiguous[0].message


def test_self_referential_relationship_is_rejected_and_never_refs_its_own_model(
    tmp_path: Path,
) -> None:
    """FAILS before #334: the hub compiles green and customer.sql contains ``ref('customer')``.

    ``_wire_relationships`` derives both ``referenced_model`` and ``fk_column`` from the target
    model name, so an in-scope self-relationship emits a dbt dependency cycle plus a second
    ``customer_sk`` column. ``safety.identity-role-collision`` cannot catch it: it only reserves
    the generated FK name when ``external_reference is not None``.
    """
    hub = _hub(tmp_path)
    ontology = hub / "model" / "ontologies" / "party.ttl"
    ontology.write_text(
        ontology.read_text(encoding="utf-8") + "\nparty:parent_customer a owl:ObjectProperty ;\n"
        "  rdfs:domain party:Customer ; rdfs:range party:Customer .\n",
        encoding="utf-8",
    )
    binding_path = _customer_binding_path(hub)
    binding_path.write_text(
        binding_path.read_text(encoding="utf-8").replace(
            "relationships:\n",
            textwrap.dedent("""\
                relationships:
                  - property: party:parent_customer
                    target: party:Customer
                    join:
                      - local: customer_id
                        foreign: customer_id
                    cardinality: many-to-one
                    mode: non-temporal
                    missingParent: error
                    ambiguousParent: error
                """),
        ),
        encoding="utf-8",
    )

    result = compile_domain(hub, "party")

    assert not result.succeeded
    codes = {item.code for item in result.diagnostics.items}
    assert "relationship.self-reference-unsupported" in codes, [
        item.render() for item in result.diagnostics.items
    ]
    assert not any("ref('customer')" in content.lower() for _, content in result.artifacts)


def test_external_reference_in_the_bindings_own_domain_is_rejected(tmp_path: Path) -> None:
    """FAILS before #335: a same-domain ``externalReference`` is silently accepted, bypassing
    join validation, model-existence checking, and the ``silently-dropped-relationship`` check.

    Asserts the dedicated code, not ``safety.relationship-endpoint`` -- ten sites already
    construct that one, so pinning it would pass whether or not this check exists.
    """
    hub = _hub(tmp_path)
    binding_path = _customer_binding_path(hub)
    binding_path.write_text(
        binding_path.read_text(encoding="utf-8").replace(
            "    target: party:Country\n",
            "    target: party:Country\n"
            "    externalReference:\n"
            "      name: country\n"
            "      domain: party\n"
            "      key:\n"
            "        - column: code\n"
            "          type: string\n",
        ),
        encoding="utf-8",
    )

    result = compile_domain(hub, "party")

    assert not result.succeeded
    codes = {item.code for item in result.diagnostics.items}
    assert "relationship.external-reference-same-domain" in codes, [
        item.render() for item in result.diagnostics.items
    ]
