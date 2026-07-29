# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused Stage 2 temporal relationship compiler tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from kairos_ontology.core.compiler.bindings import (
    EntityBinding,
    GrainSpec,
    IdentitySpec,
    LoadSpec,
    RelationshipJoin,
    RelationshipSpec,
    SourceRef,
    TemporalRelationshipPolicy,
)
from kairos_ontology.core.compiler.result import CompileError
from kairos_ontology.core.compiler.temporal import (
    AmbiguousParentAction,
    LateParentAction,
    MissingParentAction,
    OpenEndedPolicy,
    OverlapAction,
    adapt_temporal_relationships,
)
from kairos_ontology.core.projections.dbt.canonical_hash import temporal_match_count_column
from kairos_ontology.core.projections.dbt.policy_specs import (
    IntervalBoundary,
    LookupCardinality,
    TemporalMode,
)


def _relationship(mode: str = "as-of") -> RelationshipSpec:
    return RelationshipSpec(
        property="party:country",
        target="ref:Country",
        on=(RelationshipJoin(local="country_code", foreign="iso2"),),
        cardinality="many-to-one",
        mode=mode,
        missing_parent="error",
        ambiguous_parent="error",
        temporal=(
            None
            if mode == "non-temporal"
            else TemporalRelationshipPolicy(
                child_event_time="effective_at" if mode == "as-of" else "",
                parent_valid_from="valid_from",
                parent_valid_to="valid_to",
                open_ended="null",
                overlap="error",
                late_parent="defer",
                change_detection="include",
            )
        ),
        pointer="/relationships/0",
    )


def _binding(*relationships: RelationshipSpec) -> EntityBinding:
    return EntityBinding(
        api_version="kairos.eu/v5",
        name="customer",
        domain="party",
        source=SourceRef(relation="crm.customer"),
        target_class="party:Customer",
        grain=GrainSpec(columns=("customer_id",)),
        identity=IdentitySpec(strategy="source-natural", source_key=("customer_id",)),
        load=LoadSpec(mode="full-refresh"),
        fields=(),
        relationships=relationships,
        source_path="model/bindings/customer.yaml",
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("non-temporal", TemporalMode.NONE),
        ("current", TemporalMode.CURRENT),
        ("as-of", TemporalMode.AS_OF),
    ],
)
def test_adapts_all_relationship_modes(mode: str, expected: TemporalMode) -> None:
    fact = adapt_temporal_relationships(_binding(_relationship(mode)))[0]

    assert fact.mode is expected
    assert fact.match_count.column == temporal_match_count_column("party:country")
    assert fact.match_count.count_before_resolution is True
    assert fact.match_count.lookup_cardinality is LookupCardinality.EXACTLY_ONE
    assert fact.match_count.minimum == 1
    assert fact.match_count.maximum == 1
    assert fact.source_location.path == "model/bindings/customer.yaml"
    assert fact.source_location.pointer == "/relationships/0"

    if expected is TemporalMode.NONE:
        assert fact.parent_time is None
        assert fact.participates_in_change_detection is None
    else:
        assert fact.parent_time is not None
        assert fact.parent_time.interval is IntervalBoundary.CLOSED_OPEN
        assert fact.parent_time.open_ended is OpenEndedPolicy.NULL
        assert fact.parent_time.overlap_action is OverlapAction.ERROR
        assert fact.parent_time.late_parent_action is LateParentAction.DEFER
        assert fact.participates_in_change_detection is True


def test_null_and_first_actions_define_observable_match_count_behavior() -> None:
    relationship = replace(
        _relationship(),
        missing_parent="null",
        ambiguous_parent="first",
        temporal=replace(
            _relationship().temporal,
            open_ended="max-value",
            overlap="latest-start",
            late_parent="null",
            change_detection="exclude",
        ),
    )

    fact = adapt_temporal_relationships(_binding(relationship))[0]

    assert fact.missing_parent_action is MissingParentAction.NULL
    assert fact.ambiguous_parent_action is AmbiguousParentAction.FIRST
    assert fact.match_count.lookup_cardinality is LookupCardinality.ZERO_OR_ONE
    assert fact.match_count.minimum == 0
    assert fact.match_count.zero_match_action is MissingParentAction.NULL
    assert fact.match_count.multiple_match_action is AmbiguousParentAction.FIRST
    assert fact.parent_time is not None
    assert fact.parent_time.open_ended is OpenEndedPolicy.MAX_VALUE
    assert fact.parent_time.overlap_action is OverlapAction.LATEST_START
    assert fact.participates_in_change_detection is False
    with pytest.raises(FrozenInstanceError):
        fact.match_count.maximum = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    ("relationship", "code"),
    [
        (
            replace(_relationship("non-temporal"), temporal=_relationship().temporal),
            "temporal.policy-forbidden",
        ),
        (replace(_relationship("current"), temporal=None), "temporal.policy-required"),
        (
            replace(
                _relationship("as-of"),
                temporal=replace(_relationship().temporal, child_event_time=""),
            ),
            "temporal.child-event-time-required",
        ),
        (
            replace(
                _relationship("current"),
                temporal=replace(
                    _relationship("current").temporal,
                    child_event_time="unexpected",
                ),
            ),
            "temporal.child-event-time-forbidden",
        ),
        (
            replace(
                _relationship(),
                temporal=replace(_relationship().temporal, change_detection=""),
            ),
            "temporal.change-detection-invalid",
        ),
        (
            replace(
                _relationship(),
                temporal=replace(
                    _relationship().temporal,
                    parent_valid_to="valid_from",
                ),
            ),
            "temporal.parent-validity-collision",
        ),
        (replace(_relationship(), on=()), "temporal.join-missing"),
        (
            replace(
                _relationship(),
                temporal=replace(_relationship().temporal, parent_valid_from=""),
            ),
            "temporal.parent-validity-incomplete",
        ),
        (
            replace(
                _relationship(),
                temporal=replace(_relationship().temporal, open_ended="invented"),
            ),
            "temporal.open-ended-invalid",
        ),
    ],
)
def test_rejects_incomplete_or_contradictory_time_semantics(
    relationship: RelationshipSpec, code: str
) -> None:
    with pytest.raises(CompileError) as excinfo:
        adapt_temporal_relationships(_binding(relationship))

    diagnostic = next(item for item in excinfo.value.diagnostics if item.code == code)
    assert diagnostic.rule_id == "DD-109-temporal-fk"
    assert diagnostic.location.path == "model/bindings/customer.yaml"
    assert diagnostic.location.pointer.startswith("/relationships/0/")


@pytest.mark.parametrize(
    ("field", "value", "code", "pointer"),
    [
        ("cardinality", "many", "temporal.cardinality-invalid", "/cardinality"),
        ("missing_parent", "skip", "temporal.missing-action-invalid", "/missingParent"),
        (
            "ambiguous_parent",
            "random",
            "temporal.ambiguous-action-invalid",
            "/ambiguousParent",
        ),
    ],
)
def test_rejects_incomplete_lookup_actions(field: str, value: str, code: str, pointer: str) -> None:
    relationship = replace(_relationship(), **{field: value})

    with pytest.raises(CompileError) as excinfo:
        adapt_temporal_relationships(_binding(relationship))

    diagnostic = next(item for item in excinfo.value.diagnostics if item.code == code)
    assert diagnostic.location.pointer == f"/relationships/0{pointer}"


@pytest.mark.parametrize(
    ("field", "value", "code", "pointer"),
    [
        ("overlap", "ignore", "temporal.overlap-action-invalid", "/overlap"),
        ("late_parent", "first", "temporal.late-action-invalid", "/lateParent"),
    ],
)
def test_rejects_incomplete_parent_actions(field: str, value: str, code: str, pointer: str) -> None:
    relationship = replace(
        _relationship(),
        temporal=replace(_relationship().temporal, **{field: value}),
    )

    with pytest.raises(CompileError) as excinfo:
        adapt_temporal_relationships(_binding(relationship))

    diagnostic = next(item for item in excinfo.value.diagnostics if item.code == code)
    assert diagnostic.location.pointer == f"/relationships/0/temporal{pointer}"


def test_diagnostics_are_deterministic_and_duplicate_properties_are_rejected() -> None:
    first = replace(_relationship(), cardinality="many", pointer="/relationships/0")
    second = replace(
        _relationship(),
        mode="sometimes",
        pointer="/relationships/1",
    )

    with pytest.raises(CompileError) as excinfo:
        adapt_temporal_relationships(_binding(first, second))

    assert [item.code for item in excinfo.value.diagnostics] == [
        "temporal.cardinality-invalid",
        "temporal.mode-invalid",
        "temporal.property-duplicate",
    ]
    assert [item.location.pointer for item in excinfo.value.diagnostics] == [
        "/relationships/0/cardinality",
        "/relationships/1/mode",
        "/relationships/1/property",
    ]
