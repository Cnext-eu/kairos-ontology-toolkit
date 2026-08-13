# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Regression coverage for #351.

``_wire_relationships`` derived the generated Silver FK column name (and join alias)
purely from a relationship's *target*, with no dedup across a binding's relationships.
When one binding declared two relationships landing on the same generated name -- two
relationships to the same target class, or two ``externalReference`` relationships to
the same external system -- both emitted an identically named FK column, appended twice
to the same (undeduplicated) ``fk_columns`` list, and both joins reused the same alias.
The rendered schema YAML collapses same-named columns (dict-like), so it silently
disagreed with the raw ``model.columns`` tuple the parity gate compares it against, and
the compile failed with ``compiler.render-failed: ... Silver parity blocked: ... schema
YAML columns differ from spec``. Worse, the duplicated join alias would also have made
the generated SQL join twice against the same aliased reference.

The fix only renames when there *is* a collision: a target hit by exactly one
relationship keeps the original ``{target}_sk`` column/alias unchanged; a target hit by
more than one relationship gets both the FK column and the join alias qualified with the
relationship's own resolved property column name (``f"{prop.column_name}_{target}"``),
so they no longer collide.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from kairos_ontology.core.compiler import (
    CompileMode,
    adapt_binding,
    build_compile_plan,
    compile_domain,
)
from kairos_ontology.core.compiler import kernel as kernel_module


def _hub(tmp_path: Path) -> Path:
    scenario = Path(__file__).parent / "scenarios" / "v5-hub"
    hub = tmp_path / "hub"
    shutil.copytree(scenario, hub)
    return hub


def _hub_with_colliding_relationship(tmp_path: Path) -> Path:
    """A copy of v5-hub where ``crm-customer`` gets a *second* relationship to Country.

    Adds a brand-new object property (``party:secondaryCountry``) so the second
    relationship resolves to a real, distinct property -- exercising the actual bug
    end-to-end through the public compile path, not just a hand-mutated dataclass.
    """
    hub = _hub(tmp_path)
    ontology_path = hub / "model" / "ontologies" / "party.ttl"
    ontology_path.write_text(
        ontology_path.read_text(encoding="utf-8")
        + "\nparty:secondaryCountry a owl:ObjectProperty ;\n"
        "  rdfs:domain party:Customer ; rdfs:range party:Country .\n",
        encoding="utf-8",
    )
    binding_path = hub / "integration" / "bindings" / "customer.binding.yaml"
    _insert_relationship(
        binding_path,
        "  - property: party:secondaryCountry\n"
        "    target: party:Country\n"
        "    join:\n"
        "      - local: country_code\n"
        "        foreign: code\n"
        "    cardinality: many-to-one\n"
        "    mode: non-temporal\n"
        "    missingParent: null\n"
        "    ambiguousParent: error\n",
    )
    return hub


def _insert_relationship(binding_path: Path, relationship_yaml: str) -> None:
    """Insert a relationship list item into a binding's ``relationships:`` list.

    Appending at the end of the file would land inside whatever the *last* top-level
    section happens to be (``quality:`` in these fixtures) instead of ``relationships:``,
    since a bare YAML list item has no section marker of its own. Insert it right before
    the next top-level (zero-indent) section instead.
    """
    text = binding_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith("relationships:"))
    end = next(
        (
            i
            for i in range(start + 1, len(lines))
            if lines[i].strip() and not lines[i].startswith((" ", "\t"))
        ),
        len(lines),
    )
    lines[end:end] = [relationship_yaml]
    binding_path.write_text("".join(lines), encoding="utf-8")


def _customer_bound(hub: Path):
    plan = build_compile_plan(hub, "party")
    context = plan.resolution
    bindings = plan.bindings
    bounds = tuple(adapt_binding(binding, context) for binding in bindings)
    wired, diagnostics = kernel_module._wire_relationships(bounds, bindings, context, hub)
    customer_index = next(i for i, b in enumerate(bindings) if b.name == "crm-customer")
    return wired[customer_index], diagnostics


def test_single_relationship_keeps_target_only_fk_name(tmp_path: Path) -> None:
    """Unchanged case: exactly one relationship to a target keeps ``{target}_sk``.

    This is the pre-existing, common shape (the real v5-hub fixture, untouched), and it
    must keep emitting the same column/alias names it always has -- no gratuitous
    breaking rename for binidngs that never collide.
    """
    hub = _hub(tmp_path)
    customer, diagnostics = _customer_bound(hub)

    assert diagnostics == ()
    silver_model = customer.silver_candidates[0]
    fk_columns = [column for column in silver_model.columns if column.role == "foreign-key"]
    assert [column.name for column in fk_columns] == ["country_sk"]
    assert silver_model.joins[0].alias == "country"
    assert silver_model.joins[0].fk_column == "country_sk"

    schema_model = customer.schema_candidates[0]
    schema_fk_columns = [column for column in schema_model.columns if column.role == "foreign-key"]
    assert [column.name for column in schema_fk_columns] == ["country_sk"]


def test_two_relationships_to_same_target_get_distinct_fk_names(tmp_path: Path) -> None:
    """The bug: two relationships to the same target class must no longer collide."""
    hub = _hub_with_colliding_relationship(tmp_path)
    customer, diagnostics = _customer_bound(hub)

    assert diagnostics == ()
    silver_model = customer.silver_candidates[0]
    fk_columns = [column for column in silver_model.columns if column.role == "foreign-key"]
    fk_names = [column.name for column in fk_columns]

    # Distinct names -- the core bug (identical "country_sk" appended twice).
    assert len(fk_names) == len(set(fk_names)) == 2
    assert fk_names == ["country_country_sk", "secondary_country_country_sk"]

    # Distinct join aliases too -- the duplicated alias would otherwise have produced a
    # SQL join against the same aliased reference twice.
    aliases = [join.alias for join in silver_model.joins]
    assert len(aliases) == len(set(aliases)) == 2
    assert aliases == ["country_country", "secondary_country_country"]

    # Both joins still point at the real target model (dbt ref('country') unchanged --
    # renaming the relationship/property must never rewrite the ref() target).
    assert all(join.referenced_model == "{{ ref('country') }}" for join in silver_model.joins)

    # The target-side column being joined against is still the target's own real PK
    # column name ("country_sk"), just qualified by each distinct alias now.
    expressions = {column.name: column.expression for column in fk_columns}
    assert expressions["country_country_sk"] == "[country_country].[country_sk]"
    assert expressions["secondary_country_country_sk"] == "[secondary_country_country].[country_sk]"

    schema_model = customer.schema_candidates[0]
    schema_fk_names = [
        column.name for column in schema_model.columns if column.role == "foreign-key"
    ]
    assert schema_fk_names == fk_names


def test_two_relationships_to_same_target_compile_and_render_cleanly(tmp_path: Path) -> None:
    """End-to-end repro: the full ``compile_domain`` EMIT path must succeed.

    Before the fix, this failed with ``compiler.render-failed`` because the rendered
    schema YAML (which collapses same-named columns) disagreed with the raw,
    undeduplicated ``model.columns`` the DD-110 parity gate compares it against.
    """
    hub = _hub_with_colliding_relationship(tmp_path)

    result = compile_domain(hub, "party", CompileMode.EMIT)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    assert not any(item.code == "compiler.render-failed" for item in result.diagnostics.items), [
        item.render() for item in result.diagnostics.items
    ]


def test_match_count_expression_uses_the_disambiguated_alias(tmp_path: Path) -> None:
    """``_project_relationship_match_counts`` independently derives a ``COUNT(...)``
    expression per relationship for ambiguous-parent detection. It used to re-derive the
    join alias from scratch as the bare ``target_model`` -- which was only ever correct
    because ``_wire_relationships`` always used that same bare name as the alias. Now
    that a colliding target's alias is qualified with the relationship's own property
    name, this must look up the *actual* alias ``_wire_relationships`` assigned instead
    of assuming it, or its ``COUNT()`` would reference a table alias that no longer
    appears anywhere in the rendered join.
    """
    hub = _hub_with_colliding_relationship(tmp_path)
    plan = build_compile_plan(hub, "party")
    context = plan.resolution
    bindings = plan.bindings
    bounds = tuple(adapt_binding(binding, context) for binding in bindings)
    wired_bounds, wiring_diagnostics = kernel_module._wire_relationships(
        bounds, bindings, context, hub
    )
    assert wiring_diagnostics == ()
    merged = kernel_module.merge_bound_sources(wired_bounds, bindings, context, hub_root=hub)
    contract = kernel_module.normalize_contract(merged, kernel_module.ExecutionMode.FAIL_FAST)
    shaped = kernel_module._project_relationship_match_counts(
        kernel_module.shape_project(contract), bindings, context
    )

    customer_model = next(
        model for model in shaped.silver_models if model.identity.model_name == "customer"
    )
    joins_by_alias = {join.alias: join for join in customer_model.joins}
    assert set(joins_by_alias) == {"country_country", "secondary_country_country"}

    match_count_columns = {
        column.name: column.expression
        for column in customer_model.columns
        if column.name.startswith("_kairos_fk_") and column.name.endswith("_match_count")
    }
    assert len(match_count_columns) == 2, customer_model.columns
    for expression in match_count_columns.values():
        # Each COUNT(...) must reference one of the two real, distinct join aliases --
        # never the stale bare "country" alias that no longer exists in the FROM clause.
        assert ("[country_country].[country_sk]" in expression) != (
            "[secondary_country_country].[country_sk]" in expression
        ), expression
        assert "[country].[country_sk]" not in expression, expression


def test_two_external_reference_relationships_to_same_system_get_distinct_fk_names(
    tmp_path: Path,
) -> None:
    """The ``externalReference`` flavor of the same bug (#351): two relationships to the
    same external system/model must not collide either, and must not rewrite the dbt
    ``ref()`` target (which is derived from the external system's real model name, not a
    label -- renaming it away would silently point ``ref()`` at a model that doesn't
    exist)."""
    hub = _hub(tmp_path)
    ontology_path = hub / "model" / "ontologies" / "party.ttl"
    ontology_path.write_text(
        ontology_path.read_text(encoding="utf-8")
        + "\nparty:secondaryCountry a owl:ObjectProperty ;\n"
        "  rdfs:domain party:Customer ; rdfs:range party:Country .\n",
        encoding="utf-8",
    )
    binding_path = hub / "integration" / "bindings" / "customer.binding.yaml"
    external_reference_relationship = (
        "  - property: {property}\n"
        "    target: party:Country\n"
        "    externalReference:\n"
        "      domain: reference\n"
        "      name: country_lookup\n"
        "      key:\n"
        "        - column: country_code\n"
        "          type: string\n"
        "    join:\n"
        "      - local: country_code\n"
        "        foreign: code\n"
        "    cardinality: many-to-one\n"
        "    mode: non-temporal\n"
        "    missingParent: null\n"
        "    ambiguousParent: error\n"
    )
    _insert_relationship(
        binding_path, external_reference_relationship.format(property="party:country")
    )
    _insert_relationship(
        binding_path, external_reference_relationship.format(property="party:secondaryCountry")
    )
    plan = build_compile_plan(hub, "party")
    context = plan.resolution
    bindings = plan.bindings
    bounds = tuple(adapt_binding(binding, context) for binding in bindings)
    wired, diagnostics = kernel_module._wire_relationships(bounds, bindings, context, hub)
    customer_index = next(i for i, b in enumerate(bindings) if b.name == "crm-customer")
    customer = wired[customer_index]

    assert diagnostics == ()
    silver_model = customer.silver_candidates[0]
    external_joins = [
        join for join in silver_model.joins if join.referenced_model == "{{ ref('country_lookup') }}"
    ]
    assert len(external_joins) == 2

    fk_names = [join.fk_column for join in external_joins]
    aliases = [join.alias for join in external_joins]
    assert len(fk_names) == len(set(fk_names)) == 2
    assert len(aliases) == len(set(aliases)) == 2
    assert "country_country_lookup_sk" in fk_names
    assert "secondary_country_country_lookup_sk" in fk_names

    # Both still point at the real external model -- disambiguation only touched the
    # source-side FK column name and join alias, never the dbt ref() target.
    assert all(join.referenced_model == "{{ ref('country_lookup') }}" for join in external_joins)
