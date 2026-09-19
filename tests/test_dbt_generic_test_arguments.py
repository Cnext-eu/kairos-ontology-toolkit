# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Generic-test arguments are nested under `arguments:` everywhere (#826).

dbt 1.10 moved a generic test's arguments under an `arguments:` key. The toolkit was half
converted: its own tests went through `_generic_test`, which nests correctly, while the
third-party `dbt_utils.unique_combination_of_columns` emissions kept the top-level form —
and both shapes landed in the same generated file.

On dbt 1.12 every such test raises `MissingArgumentsPropertyInGenericTestDeprecation`, and
dbt has these slated to become hard errors, at which point the emitted package stops
parsing. This was hidden because the hub validated on dbt 1.10 while the dataplatform
consuming its output ran 1.12, so deprecations emitted *by the hub* were only observable
*in the dataplatform* (#789 part 4). That divergence is closed; this makes the emitted
syntax match.

`config` is deliberately **not** moved: it is a dbt-level concern (where, severity, tags),
not an argument to the test, and nesting it would break the `where` clause that scopes a
grain test to current rows.
"""

from __future__ import annotations

import yaml

from kairos_ontology.core.compiler import adapt_binding, load_entity_binding
from kairos_ontology.core.projections.dbt import (
    normalize_contract,
    plan_materialization,
    render_project,
    shape_project,
)
from kairos_ontology.core.projections.dbt.diagnostics import ExecutionMode

from .test_compiler_identity_namespace import _binding, _context

_COMPOSITE_GRAIN = """
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
      columns: [order_id, alpha_src]
    identity:
      strategy: source-natural
      sourceKey: [order_id, alpha_src]
    load:
      mode: full-refresh
    fields:
      - property: order:orderId
        expression: order_id
      - property: order:alpha
        expression: alpha_src
"""


def _schema_yml(binding: str) -> str:
    bound = adapt_binding(load_entity_binding(_binding(binding), path="order.yaml"), _context())
    contract = normalize_contract(bound, ExecutionMode.FAIL_FAST)
    shaped = shape_project(contract)
    plan = plan_materialization(contract, shaped)
    return render_project(shaped, plan)["models/silver/order/_order__models.yml"]


def _model_tests(text: str) -> list:
    return yaml.safe_load(text)["models"][0].get("data_tests") or []


def test_the_emitted_properties_yaml_is_valid_yaml():
    """A whitespace-control slip in the Jinja collapses `arguments:` onto the line above
    and produces a file dbt cannot read. Parsing is the cheapest guard against that."""
    assert yaml.safe_load(_schema_yml(_COMPOSITE_GRAIN))["models"]


def test_third_party_test_arguments_are_nested():
    tests = _model_tests(_schema_yml(_COMPOSITE_GRAIN))
    entry = next(
        item["dbt_utils.unique_combination_of_columns"]
        for item in tests
        if isinstance(item, dict) and "dbt_utils.unique_combination_of_columns" in item
    )
    assert "arguments" in entry, entry
    assert entry["arguments"]["combination_of_columns"] == ["order_id", "alpha"]
    # The deprecated spelling must be gone, not merely duplicated.
    assert "combination_of_columns" not in entry


def test_no_emitted_generic_test_keeps_arguments_at_the_top_level():
    """The general invariant, not just the one test this PR moved.

    A generic test entry is `{name: {...}}`; every key inside must be `arguments` or a
    dbt-level concern. Anything else is a top-level argument and is on dbt's removal path.
    """
    allowed = {"arguments", "config", "severity", "tags", "where", "name", "description"}
    for entry in _model_tests(_schema_yml(_COMPOSITE_GRAIN)):
        if not isinstance(entry, dict):
            continue  # a bare `unique` / `not_null` takes no arguments at all
        for test_name, body in entry.items():
            if not isinstance(body, dict):
                continue
            unexpected = set(body) - allowed
            assert not unexpected, f"{test_name} carries top-level argument(s) {unexpected}"


def test_config_stays_outside_arguments():
    """`config` scopes the test (a `where` clause on current rows); it is not an argument,
    and nesting it would silently stop the scoping from applying."""
    template = (
        __import__("pathlib")
        .Path("src/kairos_ontology/templates/dbt/schema_models.yml.jinja2")
        .read_text(encoding="utf-8")
    )
    # `config:` sits at the same indentation as `arguments:`, directly under the test name.
    assert "          config:" in template
    assert "          arguments:" in template


def test_column_level_generic_tests_nest_their_arguments_too():
    """The column block kept the pre-1.10 shape after the model block was converted: a
    source-context `accepted_values` rendered `values:` at the test's top level (as a Python
    repr, at that). Same rule as above: arguments under `arguments:`, `config` beside it."""
    from pathlib import Path
    from types import SimpleNamespace

    import kairos_ontology
    from kairos_ontology.core.projections.dbt.render import _template_environment

    column = SimpleNamespace(
        name="status",
        description="Lifecycle state",
        data_type=None,
        meta={},
        tests=[
            {"accepted_values": {"values": ["A", "B"], "config": {"severity": "warn"}}},
            {"unique": {"config": {"where": "is_current = 1"}}},
            "not_null",
        ],
    )
    model = SimpleNamespace(
        name="silver_order",
        description="",
        contract_enforced=False,
        meta={},
        data_tests=[],
        grain_columns=["order_id"],
        grain_where=None,
        source_identity_columns=["order_id"],
        columns=[column],
    )
    template_root = Path(kairos_ontology.__file__).parent / "templates" / "dbt"
    text = _template_environment(str(template_root)).get_template(
        "schema_models.yml.jinja2"
    ).render(models=[model])

    rendered = yaml.safe_load(text)["models"][0]["columns"][0]["tests"]
    assert rendered[0] == {
        "accepted_values": {"arguments": {"values": ["A", "B"]}, "config": {"severity": "warn"}}
    }
    assert rendered[1] == {"unique": {"config": {"where": "is_current = 1"}}}
    assert rendered[2] == "not_null"
