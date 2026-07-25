# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-107 typed mapping-expression contract and renderer tests."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest
from pyshacl import validate
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import XSD

from kairos_ontology.core.projections.dbt import (
    bind_sources,
    normalize_contract,
    normalize_mapping_expression,
    plan_materialization,
    render_project,
    shape_project,
)
from kairos_ontology.core.projections.dbt.mapping_bind import (
    bind_mapping_documents,
    bind_mapping_graph,
)
from kairos_ontology.core.projections.dbt.mapping_renderers import (
    render_mapping_expression,
    render_mapping_join_condition,
)
from kairos_ontology.core.projections.dbt.mapping_specs import (
    AuthoredCaseBranchFact,
    AuthoredExpressionFact,
    CaseExpression,
    FunctionExpression,
    LiteralExpression,
    MacroExpression,
    MAX_MAPPING_AST_DEPTH,
    MappingContractError,
    MappingInputSpec,
    MappingRoute,
    OperatorExpression,
)
from kairos_ontology.core.projections.dbt.mapping_normalize import _route
from kairos_ontology.core.projections.dbt.policy_specs import (
    CanonicalTypeKind,
    CanonicalTypeSpec,
)
from kairos_ontology.core.projections.dbt.specs import (
    ContractFact,
    JoinSpec,
    SourceBindingSpec,
    SourceSystemFact,
    SourceTableFact,
)
from tests.scenarios.conftest import (
    EXTENSIONS_DIR,
    MAPPINGS_DIR,
    SHAPES_DIR,
    SOURCES_DIR,
    TEMPLATE_DIR,
    _load_ontology,
)
from tests.test_dbt_phases import _client_inputs


KMAP = Namespace("https://kairos.cnext.eu/mapping#")
SCAFFOLD = Path(__file__).parents[1] / "src" / "kairos_ontology" / "scaffold"


def _metadata(
    resource: str,
    kind: str,
    output_type: str,
    nullable: bool,
    null_policy: str,
    capability: str,
    **values,
) -> AuthoredExpressionFact:
    return AuthoredExpressionFact(
        resource_uri=resource,
        kind=kind,
        output_type=output_type,
        nullable=str(nullable).lower(),
        null_policy=null_policy,
        determinism="deterministic",
        capabilities=(capability,),
        **values,
    )


def _input(*, physical_name: str = "source_name", nullable: bool = True) -> MappingInputSpec:
    return MappingInputSpec(
        source_column_uri="urn:source#name",
        source_table_uri="urn:source#table",
        source_name="source",
        authored_name="SourceName",
        physical_name=physical_name,
        data_type=CanonicalTypeSpec(CanonicalTypeKind.STRING),
        nullable=nullable,
        origin="prepared" if physical_name != "source_name" else "raw",
    )


def _source_fact(nullable: bool = True) -> AuthoredExpressionFact:
    return _metadata(
        "urn:expr#source",
        "source-column",
        "string",
        nullable,
        "propagate",
        "source-column",
        source_column_uri="urn:source#name",
    )


def _literal(value: str = "fallback") -> AuthoredExpressionFact:
    return _metadata(
        "urn:expr#literal",
        "literal",
        "string",
        False,
        "never-null",
        "typed-literal",
        literal_lexical=value,
        literal_datatype=str(XSD.string),
    )


def _typed_literal(
    lexical: str,
    output_type: str,
    datatype_uri: str,
) -> AuthoredExpressionFact:
    return _metadata(
        "urn:expr#typed-literal",
        "literal",
        output_type,
        False,
        "never-null",
        "typed-literal",
        literal_lexical=lexical,
        literal_datatype=datatype_uri,
    )


def _normalize(fact: AuthoredExpressionFact, *inputs: MappingInputSpec):
    return normalize_mapping_expression(
        fact,
        mapping_resource_uri="urn:mapping#name",
        inputs=tuple(inputs),
    )


def _domain_contract(domain: str, adapter: str = "fabric"):
    graph, namespace, classes = _load_ontology(domain)
    peers = [EXTENSIONS_DIR / "client-silver-ext.ttl"] if domain == "invoice" else []
    from kairos_ontology.core.projections.dbt import DbtInputs

    inputs = DbtInputs.from_call(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name=domain,
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        gold_ext_path=EXTENSIONS_DIR / f"{domain}-gold-ext.ttl",
        silver_ext_path=EXTENSIONS_DIR / f"{domain}-silver-ext.ttl",
        peer_ext_paths=peers,
        target_platform=adapter,
    )
    return normalize_contract(bind_sources(inputs))


def test_scenario_contract_contains_scalar_null_and_typed_literal_nodes():
    contract = _domain_contract("invoice")
    currency = next(
        item
        for item in contract.mapping_contract.columns
        if item.target_column_name == "currency"
    )
    line_total = next(
        item
        for item in contract.mapping_contract.columns
        if item.target_column_name == "line_total"
    )

    assert isinstance(currency.expression, FunctionExpression)
    assert currency.expression.function == "coalesce"
    assert currency.expression.metadata.nullable is False
    assert currency.expression.metadata.null_policy.value == "first-non-null"
    assert isinstance(currency.expression.arguments[1], LiteralExpression)
    assert currency.expression.arguments[1].lexical == "EUR"
    assert isinstance(line_total.expression, OperatorExpression)
    assert line_total.expression.operator == "multiply"


def test_prep_rename_is_bound_as_a_symbol_and_rendered_safely():
    bound = bind_sources(_client_inputs())
    contract = normalize_contract(bound)
    filter_mapping = next(
        item
        for item in contract.mapping_contract.tables
        if item.target_class_uri.endswith("#CorporateClient")
    )
    assert filter_mapping.row_filter is not None
    source = filter_mapping.row_filter.metadata.referenced_inputs[0]
    assert source.authored_name == "Type"
    assert source.physical_name == "client_type_code"

    shaped = shape_project(contract)
    artifacts = render_project(
        shaped,
        plan_materialization(contract, shaped),
    )
    branch = next(
        value
        for path, value in artifacts.items()
        if path.endswith("client__from_admin_pulse__tbl_client__corporate_client.sql")
    )
    assert "where ([tbl_client].[client_type_code] = 0)" in branch


def test_case_and_null_semantics_are_typed_and_immutable():
    source = _source_fact()
    condition = _metadata(
        "urn:expr#present",
        "operator",
        "boolean",
        False,
        "never-null",
        "scalar-operator",
        operation="is-not-null",
        arguments=(source,),
    )
    case = _metadata(
        "urn:expr#case",
        "case",
        "string",
        True,
        "branch",
        "case-expression",
        branches=(
            AuthoredCaseBranchFact(
                "urn:expr#branch",
                condition,
                source,
            ),
        ),
        else_expression=_literal(),
    )
    expression = _normalize(case, _input())

    assert isinstance(expression, CaseExpression)
    assert expression.metadata.nullable is True
    with pytest.raises(dataclasses.FrozenInstanceError):
        expression.branches = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("adapter", "quoted"),
    [
        ("fabric", "[src].[prepared_name]"),
        ("databricks", "`src`.`prepared_name`"),
    ],
)
def test_both_adapters_render_only_bound_identifiers(adapter: str, quoted: str):
    expression = _normalize(_source_fact(), _input(physical_name="prepared_name"))
    rendered = render_mapping_expression(
        expression,
        adapter=adapter,
        sources=(SourceBindingSpec("src", table_uri="urn:source#table"),),
    )
    assert rendered == quoted


def test_fk_join_uses_bound_prep_symbol_not_string_rewrite():
    source = _input(physical_name="renamed_fk")
    join = JoinSpec(
        join_type="left",
        alias="parent",
        condition="src.RawFk = parent.parent_id",
        source_alias="src",
        source_column_uris=(source.source_column_uri,),
        source_inputs=(source,),
        target_columns=("parent_id",),
    )
    assert render_mapping_join_condition(join, adapter="fabric") == (
        "[src].[renamed_fk] = [parent].[parent_id]"
    )


@pytest.mark.parametrize("adapter", ["fabric", "databricks"])
def test_typed_literal_codec_preserves_complex_text_without_breakout(adapter: str):
    value = "C:\\work\\new\\file, O'Brien, \\n literal\r\nactual\tcontrols\b\f — café"
    expression = _normalize(_literal(value))
    rendered = render_mapping_expression(
        expression,
        adapter=adapter,
        sources=(),
    )

    assert value not in rendered
    if adapter == "fabric":
        payload = rendered.removeprefix("CONVERT(VARCHAR(8000), 0x").removesuffix(")")
        decoded = bytes.fromhex(payload).decode("utf-8")
    else:
        payload = rendered.removeprefix("decode(unhex('").removesuffix("'), 'UTF-8')")
        decoded = bytes.fromhex(payload).decode("utf-8")
    assert decoded == value


@pytest.mark.parametrize(
    ("adapter", "output_type", "datatype_uri", "lexical", "physical_type"),
    [
        ("fabric", "date", str(XSD.date), "2026-07-25", "DATE"),
        ("databricks", "date", str(XSD.date), "2026-07-25", "DATE"),
        ("fabric", "time", str(XSD.time), "16:27:37.1234567", "TIME"),
        ("databricks", "time", str(XSD.time), "16:27:37.1234567", "STRING"),
        (
            "fabric",
            "timestamp",
            str(XSD.dateTime),
            "2026-07-25T16:27:37.123456",
            "DATETIME2(6)",
        ),
        (
            "databricks",
            "timestamp",
            str(XSD.dateTime),
            "2026-07-25T16:27:37.123456",
            "TIMESTAMP",
        ),
    ],
)
def test_temporal_literals_use_the_adapter_codec(
    adapter: str,
    output_type: str,
    datatype_uri: str,
    lexical: str,
    physical_type: str,
):
    expression = _normalize(_typed_literal(lexical, output_type, datatype_uri))

    rendered = render_mapping_expression(expression, adapter=adapter, sources=())

    assert rendered.startswith("CAST(")
    assert rendered.endswith(f" AS {physical_type})")
    expected_payload = (
        lexical.encode("utf-8").hex().upper()
        if adapter == "fabric"
        else lexical.encode("utf-8").hex().upper()
    )
    assert expected_payload in rendered


@pytest.mark.parametrize(
    "lexical",
    ["12:34", "24:00:01", "12:34:56Z", "12:34:56.12345678", "noon"],
)
def test_time_literal_requires_portable_lexical_form(lexical: str):
    with pytest.raises(MappingContractError, match="mapping.invalid-literal-lexical"):
        _normalize(_typed_literal(lexical, "time", str(XSD.time)))


@pytest.mark.parametrize(
    ("adapter", "argument_count", "expected"),
    [
        ("fabric", 1, "ROUND(7, 0)"),
        ("fabric", 2, "ROUND(7, 2)"),
        ("databricks", 1, "ROUND(7)"),
        ("databricks", 2, "ROUND(7, 2)"),
    ],
)
def test_round_is_portable_on_both_adapters(
    adapter: str,
    argument_count: int,
    expected: str,
):
    value = _typed_literal("7", "int32", str(XSD.int))
    scale = _typed_literal("2", "int32", str(XSD.int))
    expression = _normalize(
        _metadata(
            "urn:expr#round",
            "function",
            "int32",
            False,
            "propagate",
            "scalar-function",
            operation="round",
            arguments=(value, scale)[:argument_count],
        )
    )

    assert render_mapping_expression(expression, adapter=adapter, sources=()) == expected


@pytest.mark.parametrize(
    ("adapter", "expected"),
    [
        (
            "fabric",
            "CAST(LEN([src].[source_name]) + "
            "(DATALENGTH([src].[source_name]) - "
            "DATALENGTH(RTRIM([src].[source_name]))) AS BIGINT)",
        ),
        ("databricks", "LENGTH(`src`.`source_name`)"),
    ],
)
def test_length_generated_sql_counts_trailing_spaces_portably(adapter: str, expected: str):
    expression = _normalize(
        _metadata(
            "urn:expr#length",
            "function",
            "int64",
            True,
            "propagate",
            "scalar-function",
            operation="length",
            arguments=(_source_fact(),),
        ),
        _input(),
    )

    assert render_mapping_expression(
        expression,
        adapter=adapter,
        sources=(SourceBindingSpec("src", table_uri="urn:source#table"),),
    ) == expected


def test_mapping_ast_depth_fails_with_contract_error():
    fact = _literal("leaf")
    for depth in range(MAX_MAPPING_AST_DEPTH):
        fact = _metadata(
            f"urn:expr#depth-{depth}",
            "function",
            "string",
            False,
            "propagate",
            "scalar-function",
            operation="upper",
            arguments=(fact,),
        )

    with pytest.raises(MappingContractError, match="mapping.expression-too-deep"):
        _normalize(fact)


def test_contracted_virtual_route_requires_explicit_approved_evidence_and_tests():
    table_uri = "https://example.test/source#virtual"
    target_uri = "https://example.test/domain#Order"
    systems = (
        SourceSystemFact(
            uri="https://example.test/source",
            label="source",
            database="",
            schema="",
            connection_type="",
            tables=(
                SourceTableFact(
                    uri=table_uri,
                    name="virtual",
                    label="Virtual",
                    primary_key_columns=(),
                    incremental_column=None,
                    columns=(),
                    relation_kind="contracted-virtual",
                ),
            ),
        ),
    )
    incomplete = ContractFact(
        name="int_orders",
        materialization="table",
        target_class=target_uri,
        virtual_source_iri=table_uri,
        supported_adapters=("fabric", "databricks"),
        grain_key=("order_id",),
        approved=True,
    )

    with pytest.raises(
        MappingContractError,
        match="no explicit transformation decisions.*accepted evidence.*verified tests",
    ):
        _route(
            table_uri,
            target_uri,
            systems=systems,
            policy=SimpleNamespace(preparations=()),
            contracts=(("int_orders", incomplete),),
            replacement_input_uris=frozenset(),
            resource_uri="urn:mapping#orders",
        )

    complete = dataclasses.replace(
        incomplete,
        decision_statuses=("developer_approved",),
        evidence_artifacts=("integration/evidence/orders.ttl",),
        verified_tests=("unit_test_orders",),
    )
    assert _route(
        table_uri,
        target_uri,
        systems=systems,
        policy=SimpleNamespace(preparations=()),
        contracts=(("int_orders", complete),),
        replacement_input_uris=frozenset(),
        resource_uri="urn:mapping#orders",
    ) == (MappingRoute.CONTRACTED_TRANSFORMATION, "int_orders")


@pytest.mark.parametrize(
    ("macro_uri", "expected"),
    [
        ("https://kairos.cnext.eu/mapping/macro#concat", "kairos_concat"),
        ("https://kairos.cnext.eu/mapping/macro#monthName", "kairos_month_name"),
    ],
)
def test_approved_namespaced_macro_allowlist(macro_uri: str, expected: str):
    arguments = (
        (_source_fact(), _literal())
        if macro_uri.endswith("concat")
        else (
            _metadata(
                "urn:expr#date",
                "source-column",
                "date",
                False,
                "propagate",
                "source-column",
                source_column_uri="urn:source#date",
            ),
        )
    )
    inputs = (
        (_input(),)
        if macro_uri.endswith("concat")
        else (
            dataclasses.replace(
                _input(nullable=False),
                source_column_uri="urn:source#date",
                data_type=CanonicalTypeSpec(CanonicalTypeKind.DATE),
            ),
        )
    )
    output = "string"
    fact = _metadata(
        "urn:expr#macro",
        "macro",
        output,
        any(item.nullable == "true" for item in arguments),
        "propagate",
        "namespaced-macro",
        macro_uri=macro_uri,
        arguments=arguments,
    )
    expression = _normalize(fact, *inputs)
    assert isinstance(expression, MacroExpression)
    assert expression.macro_name == expected


def test_unapproved_macro_is_rejected():
    fact = _metadata(
        "urn:expr#macro",
        "macro",
        "string",
        True,
        "propagate",
        "namespaced-macro",
        macro_uri="https://example.test/macros#escapeHatch",
        arguments=(_source_fact(),),
    )
    with pytest.raises(MappingContractError, match="mapping.unapproved-macro"):
        _normalize(fact, _input())


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        ("(select x from y)", "mapping.raw-sql-subquery"),
        ("a join b on a.id=b.id", "mapping.raw-sql-join"),
        ("row_number() over (order by x)", "mapping.raw-sql-window"),
        ("sum(x) group by y", "mapping.raw-sql-aggregation"),
        ("delete from x", "mapping.raw-sql-ddl-dml"),
        ("x; drop table y", "mapping.raw-sql-statement-separator"),
        ("x -- comment", "mapping.raw-sql-comment"),
        ("x union all y", "mapping.raw-sql-grain-change"),
        ("rand()", "mapping.nondeterministic-expression"),
        ("openjson(payload)", "mapping.adapter-specific-sql"),
        ("trim(source.name)", "mapping.technical-cleanup"),
    ],
)
def test_removed_raw_sql_categories_are_rejected(sql: str, code: str):
    graph = Graph()
    resource = URIRef("urn:mapping#legacy")
    graph.add((resource, URIRef(f"{KMAP}transformExpression"), Literal(sql)))
    with pytest.raises(MappingContractError, match=code):
        bind_mapping_graph(graph)


def test_structured_technical_cleanup_points_to_prep():
    fact = _metadata(
        "urn:expr#trim",
        "function",
        "string",
        True,
        "propagate",
        "scalar-function",
        operation="trim",
        arguments=(_source_fact(),),
    )
    with pytest.raises(MappingContractError, match="mapping.technical-cleanup"):
        _normalize(fact, _input())


def test_output_type_mismatch_and_nondeterminism_are_blocking():
    mismatch = dataclasses.replace(_source_fact(), output_type="boolean")
    with pytest.raises(MappingContractError, match="mapping.output-type-mismatch"):
        _normalize(mismatch, _input())

    nondeterministic = dataclasses.replace(
        _source_fact(),
        determinism="nondeterministic",
    )
    with pytest.raises(MappingContractError, match="mapping.nondeterministic-expression"):
        _normalize(nondeterministic, _input())


def test_unknown_and_ambiguous_source_symbols_are_blocking():
    with pytest.raises(MappingContractError, match="mapping.unknown-source-column"):
        _normalize(_source_fact())
    with pytest.raises(MappingContractError, match="mapping.ambiguous-source-column"):
        _normalize(_source_fact(), _input(), _input(physical_name="other"))


def test_scenario_mappings_conform_to_v2_shapes():
    data = Graph()
    for path in sorted(MAPPINGS_DIR.rglob("*.ttl")):
        data.parse(path, format="turtle")
    shapes = Graph().parse(SCAFFOLD / "kairos-map-shapes.shacl.ttl", format="turtle")
    conforms, _, report = validate(data, shacl_graph=shapes, inference="rdfs")
    assert conforms, report


def test_raw_sql_vocabulary_and_bare_regex_rewrite_authority_are_absent():
    vocabulary = Graph().parse(SCAFFOLD / "kairos-map.ttl", format="turtle")
    for local in (
        "transform",
        "transformExpression",
        "filterCondition",
        "sourceColumns",
        "defaultValue",
        "deduplicationKey",
        "deduplicationOrder",
    ):
        assert not any(vocabulary.triples((URIRef(f"{KMAP}{local}"), None, None)))

    shape_source = (
        Path(__file__).parents[1]
        / "src"
        / "kairos_ontology"
        / "core"
        / "projections"
        / "dbt"
        / "shape.py"
    ).read_text(encoding="utf-8")
    assert "_replace_identifiers" not in shape_source
    assert r"re.sub(rf\"\\b" not in shape_source


def test_release_data_contains_mapping_provenance_and_capabilities():
    bound = bind_sources(_client_inputs())
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    release = render_project(
        shaped,
        plan_materialization(contract, shaped),
    )["__release_data__"]

    assert release["mapping_contracts"]["tables"]
    assert release["mapping_contracts"]["columns"]
    assert release["mapping_contracts"]["version"] == "2.0"
    expression = release["mapping_contracts"]["columns"][0]["expression"]
    assert expression["provenance"]["rule_id"] == "DD-107"
    assert expression["determinism"] == "deterministic"
    assert expression["referenced_inputs"]
    assert release["mapping_capabilities"]


def test_render_blocks_a_mapped_column_without_validated_ast():
    bound = bind_sources(_client_inputs())
    contract = normalize_contract(bound)
    shaped = shape_project(contract)
    model = next(
        item
        for item in shaped.silver_models
        if any(column.mapping_resource_uri for column in item.columns)
    )
    column = next(
        item for item in model.columns if item.mapping_resource_uri
    )
    invalid_model = dataclasses.replace(
        model,
        columns=tuple(
            dataclasses.replace(item, mapping_expression=None)
            if item is column
            else item
            for item in model.columns
        ),
    )
    invalid = dataclasses.replace(
        shaped,
        silver_models=tuple(
            invalid_model if item is model else item
            for item in shaped.silver_models
        ),
    )
    with pytest.raises(MappingContractError, match="mapping.render-blocked"):
        render_project(
            invalid,
            plan_materialization(contract, invalid),
        )


def test_scenario_mapping_parse_is_deterministic():
    first = bind_mapping_documents(MAPPINGS_DIR)
    second = bind_mapping_documents(MAPPINGS_DIR)
    assert first == second
