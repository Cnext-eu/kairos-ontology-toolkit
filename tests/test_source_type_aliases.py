# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for Spark/Databricks source type spellings (#808).

A Databricks-backed hub declares ``long``/``short``/``byte`` -- Spark's names for
``bigint``/``smallint``/``tinyint`` -- because ``extract_schema`` writes the source
catalog's ``data_type`` through verbatim. The compiler's alias table knew only the
T-SQL spellings, so 123 columns on one real hub were dropped from the bound relation's
symbol table and every reference to them failed as ``safety.column-unresolved``: "not a
column of the bound relation", which was untrue and sent four authors hunting a schema
problem that did not exist.
"""

from __future__ import annotations

import textwrap

import pytest
from click.testing import CliRunner

from kairos_ontology.core.compiler import (
    CompileError,
    ResolvedColumn,
    ResolvedProperty,
    adapt_binding,
    load_entity_binding,
)
from kairos_ontology.core.projections.dbt.policy_normalize import (
    _SOURCE_TYPE_ALIASES,
    _source_type,
)
from kairos_ontology.core.projections.dbt.policy_specs import CanonicalTypeKind

from .test_compiler_adapter import _context


@pytest.mark.parametrize(
    ("spark", "tsql"),
    [("long", "bigint"), ("short", "smallint"), ("byte", "tinyint")],
)
def test_spark_integer_names_resolve_like_their_tsql_equivalents(spark, tsql):
    assert _source_type(spark) is not None
    assert _source_type(spark) == _source_type(tsql)


def test_long_is_a_64_bit_integer():
    # Not merely "resolves" -- a weight or tonnage narrowed to INT32 would silently
    # truncate, which is the failure this fix exists to avoid.
    assert _source_type("long").kind is CanonicalTypeKind.INT64
    assert _source_type("short").kind is CanonicalTypeKind.INT16
    assert _source_type("byte").kind is CanonicalTypeKind.INT16


def test_an_unknown_type_is_still_unresolvable():
    assert _source_type("geography") is None


_SPARK_BINDING = textwrap.dedent("""
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
      - property: party:grossWeight
        expression: gross_weight
    """).strip()


def _spark_context():
    """The adapter fixture, retyped the way a Databricks catalog reports it."""
    context = _context()
    relation = context.relations[0]
    relation = type(relation)(
        ref=relation.ref,
        uri=relation.uri,
        system_label=relation.system_label,
        table_name=relation.table_name,
        columns=(
            ResolvedColumn("customer_id", "long", nullable=False, is_primary_key=True),
            ResolvedColumn("gross_weight", "long", nullable=True),
        ),
    )
    return type(context)(
        domain=context.domain,
        namespace=context.namespace,
        ontology_name=context.ontology_name,
        ontology_iri=context.ontology_iri,
        ontology_version=context.ontology_version,
        template_root=context.template_root,
        target_platform=context.target_platform,
        relations=(relation,),
        classes=context.classes,
        properties=(
            context.properties[0],
            ResolvedProperty(
                ref="party:grossWeight",
                uri=f"{context.namespace}grossWeight",
                column_name="gross_weight",
                data_type="int",
                description="Gross weight in kilograms",
            ),
        ),
    )


def test_a_long_column_is_usable_as_field_grain_and_identity_key():
    # customer_id is referenced by grain.columns AND identity.sourceKey AND fields:;
    # before the fix all three reported it as absent from the relation.
    bound = adapt_binding(
        load_entity_binding(_SPARK_BINDING, path="crm-customer.yaml"),
        _spark_context(),
    )
    assert bound is not None


def test_an_unrecognised_type_names_itself_in_the_diagnostic():
    context = _spark_context()
    relation = context.relations[0]
    broken = type(context)(
        domain=context.domain,
        namespace=context.namespace,
        ontology_name=context.ontology_name,
        ontology_iri=context.ontology_iri,
        ontology_version=context.ontology_version,
        template_root=context.template_root,
        target_platform=context.target_platform,
        relations=(
            type(relation)(
                ref=relation.ref,
                uri=relation.uri,
                system_label=relation.system_label,
                table_name=relation.table_name,
                columns=(
                    ResolvedColumn("customer_id", "long", nullable=False, is_primary_key=True),
                    ResolvedColumn("gross_weight", "geography", nullable=True),
                ),
            ),
        ),
        classes=context.classes,
        properties=context.properties,
    )
    with pytest.raises(CompileError) as excinfo:
        adapt_binding(
            load_entity_binding(_SPARK_BINDING, path="crm-customer.yaml"),
            broken,
        )
    messages = " ".join(d.message for d in excinfo.value.diagnostics)
    assert "geography" in messages, messages
    assert "is not a column of the bound relation" not in messages, messages


@pytest.mark.parametrize(
    ("platform", "expected"),
    [("fabric-warehouse", "BIGINT"), ("databricks", "BIGINT")],
)
def test_the_warehouse_type_map_also_knows_long(platform, expected):
    # The half #808 did not report: scaffold-binding proposed VARCHAR(255) for every
    # long column, so the wrong type was baked into authored bindings.
    from kairos_ontology.core.projections.medallion_dbt_projector import _source_type_to_target

    assert _source_type_to_target("long", platform) == expected


def test_suggest_type_reports_long_and_lists_it_when_asked_for_something_else():
    from kairos_ontology.cli.inspection import suggest_type_cmd

    runner = CliRunner()
    assert '"int64"' in runner.invoke(suggest_type_cmd, ["long"]).output

    failure = runner.invoke(suggest_type_cmd, ["geography"])
    assert failure.exit_code != 0
    # The supported list is rendered from the compiler's table, so it cannot go stale.
    assert "long" in failure.output
    assert set(_SOURCE_TYPE_ALIASES) <= set(failure.output.replace(",", " ").split())
