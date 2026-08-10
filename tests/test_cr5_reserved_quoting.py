# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CR5 tests for adapter-specific reserved identifier quoting in dbt projection."""

import pytest

from kairos_ontology.core.projections.dbt.mapping_specs import AuthoredExpressionFact
from kairos_ontology.core.projections.medallion_dbt_projector import (
    _mapping_expression_hint,
    _quote_identifier_if_reserved,
    _source_record_key_expression,
)


def _source_column_fact(uri: str) -> AuthoredExpressionFact:
    return AuthoredExpressionFact(
        resource_uri=f"{uri}#expr",
        kind="source-column",
        output_type="string",
        nullable="false",
        null_policy="propagate",
        determinism="deterministic",
        capabilities=(),
        source_column_uri=uri,
    )


@pytest.mark.parametrize(
    ("identifier", "adapter", "expected"),
    [
        ("order", "fabric", "{{ kairos_quote_identifier('order') }}"),
        ("order", "databricks", "{{ kairos_quote_identifier('order') }}"),
        ("from", "fabric", "{{ kairos_quote_identifier('from') }}"),
        ("from", "databricks", "{{ kairos_quote_identifier('from') }}"),
        ("join", "fabric", "join"),
        ("join", "databricks", "{{ kairos_quote_identifier('join') }}"),
        ("customer_id", "fabric", "customer_id"),
        ("customer_id", "databricks", "customer_id"),
    ],
)
def test_quote_identifier_if_reserved_uses_adapter_registry(identifier, adapter, expected):
    assert _quote_identifier_if_reserved(identifier, adapter) == expected


def test_recursive_mapping_expression_hint_threads_adapter_to_children():
    order_col = "https://example.test/source#order"
    join_col = "https://example.test/source#join"
    expression = AuthoredExpressionFact(
        resource_uri="https://example.test/mapping#expr",
        kind="operator",
        output_type="boolean",
        nullable="false",
        null_policy="propagate",
        determinism="deterministic",
        capabilities=(),
        operation="equal",
        arguments=(
            _source_column_fact(order_col),
            _source_column_fact(join_col),
        ),
    )
    lookup = {
        order_col: {"name": "order"},
        join_col: {"name": "join"},
    }

    assert _mapping_expression_hint(expression, lookup, "fabric") == (
        "({{ kairos_quote_identifier('order') }} = join)"
    )
    assert _mapping_expression_hint(expression, lookup, "databricks") == (
        "({{ kairos_quote_identifier('order') }} = {{ kairos_quote_identifier('join') }})"
    )


def test_source_record_key_expression_threads_adapter_to_primary_key_columns():
    systems = [
        {
            "tables": [
                {
                    "uri": "https://example.test/source#rows",
                    "name": "rows",
                    "pk_columns": ["join"],
                    "columns": [{"name": "join", "is_pk": True}],
                }
            ]
        }
    ]
    source_ref = ("source", "rows", "https://example.test/source#rows")

    fabric_expression, fabric_after_mapping = _source_record_key_expression(
        systems,
        source_ref,
        "src",
        "fabric",
    )
    databricks_expression, databricks_after_mapping = _source_record_key_expression(
        systems,
        source_ref,
        "src",
        "databricks",
    )

    assert fabric_expression == ("{{ dbt_utils.generate_surrogate_key([\"'rows'\", 'src.join']) }}")
    assert fabric_after_mapping is False
    assert databricks_expression == (
        "{{ dbt_utils.generate_surrogate_key(["
        "\"'rows'\", \"src.{{ kairos_quote_identifier('join') }}\"]) }}"
    )
    assert databricks_after_mapping is False
