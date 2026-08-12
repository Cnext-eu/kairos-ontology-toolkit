# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for #338: ``--explain`` relationship visibility and ``_wire_relationships`` diagnostics.

Two things, per issue #338:

* ``compile --explain`` in its default text form did not print relationships at all, and
  even the JSON ``ExplainRelationship`` shape omitted the relationship's own property and
  its join columns -- a reader inspecting explain output had no way to see which
  relationships exist, let alone what they are keyed on.
* ``_wire_relationships`` had bare ``continue`` statements that dropped a relationship
  with no diagnostic. As of #334/#335, three of those conditions are already detected and
  blocked *pre-wiring* by ``_relationship_diagnostics`` (the whole binding is rejected
  before it is ever admitted into ``_wire_relationships``'s input), so they are now
  defensive/unreachable via the public ``compile_domain`` path; they are tested here by
  calling the private ``_wire_relationships`` directly with a hand-mutated
  ``RelationshipSpec`` that bypasses that upstream gate -- the only way to observe them at
  all. The fourth -- an internal relationship whose target binding is ``None`` -- is
  **not** fully unreachable: ``_relationship_diagnostics`` resolves the target binding
  from ``selected_by_name`` (every *selected* binding, computed once before the
  per-binding blocking loop runs), while ``_wire_relationships`` resolves the same lookup
  from ``valid_bindings`` (bindings that survived every check). If a relationship's target
  binding is later blocked for a reason *unrelated* to that relationship, the two views
  disagree and this branch fires for real, through the public API -- see
  ``test_wire_relationships_endpoint_diagnostic_is_reachable_when_target_blocked_unrelated``
  below. It does not change the compile's pass/fail outcome (``quality.py``'s pre-existing,
  independent ``run_safety_kernel`` already blocks that exact scenario with its own
  ``safety.relationship-endpoint``), so the practical effect is a redundant second
  diagnostic with the same code for the same cause, not a new correctness bug.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from dataclasses import replace

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.compiler import adapt_binding, build_compile_plan
from kairos_ontology.core.compiler import kernel as kernel_module
from kairos_ontology.core.compiler.bindings import RelationshipJoin


def _hub(tmp_path: Path) -> Path:
    scenario = Path(__file__).parent / "scenarios" / "v5-hub"
    hub = tmp_path / "hub"
    shutil.copytree(scenario, hub)
    return hub


def _customer_and_bounds(hub: Path):
    plan = build_compile_plan(hub, "party")
    context = plan.resolution
    bindings = plan.bindings
    bounds = tuple(adapt_binding(binding, context) for binding in bindings)
    customer = next(binding for binding in bindings if binding.name == "crm-customer")
    return context, bindings, bounds, customer


def test_wire_relationships_happy_path_emits_no_diagnostics(tmp_path: Path) -> None:
    """Baseline: the real, valid v5-hub relationship wires clean with zero diagnostics."""
    hub = _hub(tmp_path)
    context, bindings, bounds, _ = _customer_and_bounds(hub)

    _, diagnostics = kernel_module._wire_relationships(bounds, bindings, context, hub)

    assert diagnostics == ()


def test_wire_relationships_reports_unresolved_source_relation(tmp_path: Path) -> None:
    """Defensive drop #1: the binding's source relation fails to re-resolve during wiring.

    Unreachable via ``compile_domain`` today -- ``adapt_binding`` already requires the
    relation to resolve before a binding is admitted here -- so this is exercised by
    calling ``_wire_relationships`` with a context that no longer carries the relation.
    """
    hub = _hub(tmp_path)
    context, bindings, bounds, _ = _customer_and_bounds(hub)
    stripped_context = replace(context, relations=())

    _, diagnostics = kernel_module._wire_relationships(bounds, bindings, stripped_context, hub)

    assert any(item.code == "safety.source-unresolved" for item in diagnostics), diagnostics
    dropped = next(item for item in diagnostics if item.code == "safety.source-unresolved")
    assert "party:country" in dropped.message
    assert "crm-customer" in dropped.message


def test_wire_relationships_reports_unresolved_endpoint(tmp_path: Path) -> None:
    """Defensive drop #2: the relationship's target class does not resolve.

    Unreachable via ``compile_domain`` today -- ``_relationship_diagnostics`` already
    rejects this and blocks the whole binding pre-wiring -- so this is exercised by
    mutating the resolved ``RelationshipSpec`` directly, bypassing that upstream check.
    (The *other* trigger for this same branch -- an unresolved target *binding*, as
    opposed to an unresolved target *class* -- is reachable through the public API; see
    ``test_wire_relationships_endpoint_diagnostic_is_reachable_when_target_blocked_unrelated``.)
    """
    hub = _hub(tmp_path)
    context, bindings, bounds, customer = _customer_and_bounds(hub)
    relationship = customer.relationships[0]
    broken = replace(customer, relationships=(replace(relationship, target="party:DoesNotExist"),))
    mutated_bindings = tuple(
        broken if binding.name == "crm-customer" else binding for binding in bindings
    )

    _, diagnostics = kernel_module._wire_relationships(bounds, mutated_bindings, context, hub)

    assert any(item.code == "safety.relationship-endpoint" for item in diagnostics), diagnostics


def test_wire_relationships_reports_composite_join(tmp_path: Path) -> None:
    """Defensive drop #3: a composite (non-external) join is authored.

    Unreachable via ``compile_domain`` today -- ``_relationship_diagnostics`` already
    rejects a composite join and blocks the whole binding pre-wiring.
    """
    hub = _hub(tmp_path)
    context, bindings, bounds, customer = _customer_and_bounds(hub)
    relationship = customer.relationships[0]
    composite = replace(
        customer,
        relationships=(replace(relationship, on=(relationship.on[0], relationship.on[0])),),
    )
    mutated_bindings = tuple(
        composite if binding.name == "crm-customer" else binding for binding in bindings
    )

    _, diagnostics = kernel_module._wire_relationships(bounds, mutated_bindings, context, hub)

    assert any(item.code == "safety.adapter-unsupported" for item in diagnostics), diagnostics


def test_wire_relationships_reports_unmapped_foreign_column(tmp_path: Path) -> None:
    """Defensive drop #4: the join's foreign column is not mapped by the target binding.

    Unreachable via ``compile_domain`` today -- ``_relationship_diagnostics`` already
    rejects an unmapped ``join.foreign`` and blocks the whole binding pre-wiring.
    """
    hub = _hub(tmp_path)
    context, bindings, bounds, customer = _customer_and_bounds(hub)
    relationship = customer.relationships[0]
    bad_join = replace(
        customer,
        relationships=(
            replace(
                relationship,
                on=(RelationshipJoin(local="country_code", foreign="does_not_exist"),),
            ),
        ),
    )
    mutated_bindings = tuple(
        bad_join if binding.name == "crm-customer" else binding for binding in bindings
    )

    _, diagnostics = kernel_module._wire_relationships(bounds, mutated_bindings, context, hub)

    assert any(item.code == "safety.relationship-endpoint" for item in diagnostics), diagnostics
    dropped = next(item for item in diagnostics if item.code == "safety.relationship-endpoint")
    assert "does_not_exist" in dropped.message


def test_wire_relationships_endpoint_diagnostic_is_reachable_when_target_blocked_unrelated(
    tmp_path: Path,
) -> None:
    """The "target binding is None" trigger for defensive drop #2 IS reachable, for real,
    through the public ``build_compile_plan`` API -- not just via a direct call to the
    private function.

    ``_relationship_diagnostics`` resolves a relationship's target binding from
    ``selected_by_name``, a snapshot of every *selected* binding taken once before the
    per-binding blocking loop runs. ``_wire_relationships`` resolves the same lookup from
    ``valid_bindings``, which excludes any binding blocked along the way. When
    ``crm-country`` (the target of ``crm-customer``'s ``party:country`` relationship) is
    blocked for a reason that has nothing to do with that relationship -- here, an
    unresolvable field expression on ``crm-country`` itself -- ``_relationship_diagnostics``
    still sees ``crm-country`` as present (it hasn't been excluded from the snapshot yet)
    and does not flag ``crm-customer``. ``crm-customer`` then adapts cleanly and reaches
    ``_wire_relationships``, which finds ``crm-country`` absent from ``valid_bindings`` and
    raises the new diagnostic.

    This does not change the overall pass/fail outcome: ``crm-country`` was always going to
    block the compile on its own defect, and ``quality.py``'s pre-existing, independent
    ``run_safety_kernel`` already raises its own ``safety.relationship-endpoint`` for
    ``crm-customer`` in this exact scenario (``relationship.target not in targets``, checked
    after blocking is final). The two diagnostics are redundant -- same code, same
    underlying cause -- but neither is wrong, and deduplicating them is left alone
    deliberately: doing so safely would mean either suppressing this defensive check when it
    overlaps with the *non-suppressible* safety kernel (fragile -- the overlap is partial,
    not total, since this branch also fires when the target *property* or target *class*
    itself fails to resolve, cases ``run_safety_kernel`` does not cover), or weakening the
    non-suppressible kernel to defer to this defensive fallback, which cuts against its own
    documented invariant. Left as harmless, accurate noise rather than a rushed fix.
    """
    hub = _hub(tmp_path)
    country_path = hub / "integration" / "bindings" / "country.binding.yaml"
    country_path.write_text(
        country_path.read_text(encoding="utf-8").replace(
            "  - property: party:country_name\n    expression: country_name\n",
            "  - property: party:country_name\n    expression: totally_bogus_column\n",
        ),
        encoding="utf-8",
    )

    plan = build_compile_plan(hub, "party")

    assert plan.blocked
    country = next(item for item in plan.entities if item.binding.name == "crm-country")
    customer = next(item for item in plan.entities if item.binding.name == "crm-customer")
    assert country.blocked
    assert "safety.column-unresolved" in {item.code for item in country.diagnostics}
    assert not customer.blocked
    wiring_diagnostics = [
        item
        for item in customer.diagnostics
        if item.code == "safety.relationship-endpoint" and "dropped during wiring" in item.message
    ]
    assert wiring_diagnostics, [item.render() for item in customer.diagnostics]
    # The pre-existing, unrelated quality.py check for the same cause is still present too
    # (documented redundancy, see the docstring above).
    scope_diagnostics = [
        item
        for item in customer.diagnostics
        if item.code == "safety.relationship-endpoint" and "not in compile scope" in item.message
    ]
    assert scope_diagnostics, [item.render() for item in customer.diagnostics]


def test_explain_text_format_shows_relationship_property_and_join(tmp_path, monkeypatch) -> None:
    """#338: ``--explain`` text output previously showed nothing about relationships at all."""
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "--explain"])

    assert result.exit_code == 0, result.output
    assert "rel: party:country" in result.output
    assert "country_code=code" in result.output


def test_explain_json_relationship_shape_includes_property_and_join(tmp_path: Path) -> None:
    """#338: the JSON explain payload named only target/mode/cardinality, never the
    relationship's own property or its join columns."""
    hub = _hub(tmp_path)
    from kairos_ontology.core.compiler import CompileMode, compile_domain

    result = compile_domain(hub, "party", CompileMode.EXPLAIN)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    customer = next(item for item in result.explain.entities if item.name == "crm-customer")
    relationship = customer.relationship_shapes[0]
    assert relationship.property == "party:country"
    assert relationship.join == ("country_code=code",)
