# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Stage 2 relationship validation and immutable temporal lookup facts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from kairos_ontology.core.projections.dbt.canonical_hash import temporal_match_count_column
from kairos_ontology.core.projections.dbt.policy_specs import (
    IntervalBoundary,
    LookupCardinality,
    TemporalMode,
)

from .bindings import EntityBinding, RelationshipJoin, RelationshipSpec
from .result import CompileDiagnostic, CompileError, SourceLocation


class RelationshipCardinality(str, Enum):
    """Authored child-to-parent relationship cardinality."""

    MANY_TO_ONE = "many-to-one"
    ONE_TO_ONE = "one-to-one"


class MissingParentAction(str, Enum):
    """Action when a lookup has no matching parent."""

    ERROR = "error"
    NULL = "null"


class AmbiguousParentAction(str, Enum):
    """Action when a lookup has multiple matching parents after overlap handling."""

    ERROR = "error"
    FIRST = "first"


class OpenEndedPolicy(str, Enum):
    """Representation of an unbounded parent validity interval."""

    NULL = "null"
    MAX_VALUE = "max-value"


class OverlapAction(str, Enum):
    """Action when parent validity intervals overlap."""

    ERROR = "error"
    LATEST_START = "latest-start"


class LateParentAction(str, Enum):
    """Action when the required temporal parent has not arrived."""

    ERROR = "error"
    NULL = "null"
    DEFER = "defer"


@dataclass(frozen=True, slots=True)
class ParentTimeFact:
    """Complete parent validity semantics for a temporal relationship."""

    valid_from_column: str
    valid_to_column: str
    open_ended: OpenEndedPolicy
    interval: IntervalBoundary
    overlap_action: OverlapAction
    late_parent_action: LateParentAction
    child_event_time_column: str | None


@dataclass(frozen=True, slots=True)
class MatchCountFact:
    """Adapter-neutral behavior for the pre-resolution relationship match count."""

    column: str
    lookup_cardinality: LookupCardinality
    minimum: int
    maximum: int
    count_before_resolution: bool
    zero_match_action: MissingParentAction
    multiple_match_action: AmbiguousParentAction


@dataclass(frozen=True, slots=True)
class TemporalRelationshipFact:
    """Validated immutable relationship authority consumed by later adapter integration."""

    property_uri: str
    target_class: str
    joins: tuple[RelationshipJoin, ...]
    cardinality: RelationshipCardinality
    mode: TemporalMode
    missing_parent_action: MissingParentAction
    ambiguous_parent_action: AmbiguousParentAction
    parent_time: ParentTimeFact | None
    match_count: MatchCountFact
    participates_in_change_detection: bool | None
    source_location: SourceLocation


_MODE = {
    "non-temporal": TemporalMode.NONE,
    "current": TemporalMode.CURRENT,
    "as-of": TemporalMode.AS_OF,
}


def adapt_temporal_relationships(
    binding: EntityBinding,
) -> tuple[TemporalRelationshipFact, ...]:
    """Validate and adapt all relationship modes without selecting adapter behavior.

    The loader's JSON schema normally enforces these constraints. This boundary validates
    them again because bindings are public frozen types and may be constructed directly.
    Match counts always describe the candidate set before ``latest-start`` or ``first`` is
    applied, so missing and ambiguity decisions remain observable downstream.
    """

    diagnostics: list[CompileDiagnostic] = []
    facts: list[TemporalRelationshipFact] = []
    seen_properties: set[str] = set()

    for index, relationship in enumerate(binding.relationships):
        pointer = relationship.pointer or f"/relationships/{index}"
        location = SourceLocation(path=binding.source_path, pointer=pointer)
        before = len(diagnostics)

        mode = _enum_value(
            relationship.mode,
            _MODE,
            "temporal.mode-invalid",
            "relationship mode",
            _child(location, "/mode"),
            diagnostics,
        )
        cardinality = _enum_value(
            relationship.cardinality,
            {item.value: item for item in RelationshipCardinality},
            "temporal.cardinality-invalid",
            "relationship cardinality",
            _child(location, "/cardinality"),
            diagnostics,
        )
        missing = _enum_value(
            relationship.missing_parent,
            {item.value: item for item in MissingParentAction},
            "temporal.missing-action-invalid",
            "missing-parent action",
            _child(location, "/missingParent"),
            diagnostics,
        )
        ambiguous = _enum_value(
            relationship.ambiguous_parent,
            {item.value: item for item in AmbiguousParentAction},
            "temporal.ambiguous-action-invalid",
            "ambiguous-parent action",
            _child(location, "/ambiguousParent"),
            diagnostics,
        )

        if not relationship.on:
            _add(
                diagnostics,
                "temporal.join-missing",
                "relationship requires at least one local-to-parent join",
                _child(location, "/join"),
            )
        if relationship.property in seen_properties:
            _add(
                diagnostics,
                "temporal.property-duplicate",
                (
                    f"relationship property '{relationship.property}' is duplicated; "
                    "its deterministic match-count column would collide"
                ),
                _child(location, "/property"),
            )
        seen_properties.add(relationship.property)

        parent_time, participates = _parent_time(relationship, mode, location, diagnostics)
        if len(diagnostics) != before or None in {mode, cardinality, missing, ambiguous}:
            continue

        assert isinstance(mode, TemporalMode)
        assert isinstance(cardinality, RelationshipCardinality)
        assert isinstance(missing, MissingParentAction)
        assert isinstance(ambiguous, AmbiguousParentAction)
        lookup_cardinality = (
            LookupCardinality.EXACTLY_ONE
            if missing is MissingParentAction.ERROR
            else LookupCardinality.ZERO_OR_ONE
        )
        facts.append(
            TemporalRelationshipFact(
                property_uri=relationship.property,
                target_class=relationship.target,
                joins=relationship.on,
                cardinality=cardinality,
                mode=mode,
                missing_parent_action=missing,
                ambiguous_parent_action=ambiguous,
                parent_time=parent_time,
                match_count=MatchCountFact(
                    column=temporal_match_count_column(relationship.property),
                    lookup_cardinality=lookup_cardinality,
                    minimum=1 if missing is MissingParentAction.ERROR else 0,
                    maximum=1,
                    count_before_resolution=True,
                    zero_match_action=missing,
                    multiple_match_action=ambiguous,
                ),
                participates_in_change_detection=participates,
                source_location=location,
            )
        )

    if diagnostics:
        raise CompileError(diagnostics)
    return tuple(facts)


def _parent_time(
    relationship: RelationshipSpec,
    mode: TemporalMode | None,
    location: SourceLocation,
    diagnostics: list[CompileDiagnostic],
) -> tuple[ParentTimeFact | None, bool | None]:
    temporal = relationship.temporal
    if mode is TemporalMode.NONE:
        if temporal is not None:
            _add(
                diagnostics,
                "temporal.policy-forbidden",
                "non-temporal relationship must not declare temporal policy",
                _child(location, "/temporal"),
            )
        return None, None
    if mode not in {TemporalMode.CURRENT, TemporalMode.AS_OF}:
        return None, None
    if temporal is None:
        _add(
            diagnostics,
            "temporal.policy-required",
            f"{mode.value} relationship requires complete parent-time policy",
            _child(location, "/temporal"),
        )
        return None, None

    if not temporal.parent_valid_from or not temporal.parent_valid_to:
        _add(
            diagnostics,
            "temporal.parent-validity-incomplete",
            "temporal relationship requires parent valid-from and valid-to columns",
            _child(location, "/temporal"),
        )
    elif temporal.parent_valid_from == temporal.parent_valid_to:
        _add(
            diagnostics,
            "temporal.parent-validity-collision",
            "parent valid-from and valid-to columns must be distinct",
            _child(location, "/temporal/parentValidTo"),
        )

    child_event_time: str | None = temporal.child_event_time or None
    if mode is TemporalMode.AS_OF and child_event_time is None:
        _add(
            diagnostics,
            "temporal.child-event-time-required",
            "as-of relationship requires a child event-time column",
            _child(location, "/temporal/childEventTime"),
        )
    if mode is TemporalMode.CURRENT and child_event_time is not None:
        _add(
            diagnostics,
            "temporal.child-event-time-forbidden",
            "current relationship must not declare child event time",
            _child(location, "/temporal/childEventTime"),
        )

    open_ended = _enum_value(
        temporal.open_ended,
        {item.value: item for item in OpenEndedPolicy},
        "temporal.open-ended-invalid",
        "open-ended policy",
        _child(location, "/temporal/openEnded"),
        diagnostics,
    )
    overlap = _enum_value(
        temporal.overlap,
        {item.value: item for item in OverlapAction},
        "temporal.overlap-action-invalid",
        "overlap action",
        _child(location, "/temporal/overlap"),
        diagnostics,
    )
    late_parent = _enum_value(
        temporal.late_parent,
        {item.value: item for item in LateParentAction},
        "temporal.late-action-invalid",
        "late-parent action",
        _child(location, "/temporal/lateParent"),
        diagnostics,
    )
    participates = _enum_value(
        temporal.change_detection,
        {"include": True, "exclude": False},
        "temporal.change-detection-invalid",
        "change-detection participation",
        _child(location, "/temporal/changeDetection"),
        diagnostics,
    )
    if None in {open_ended, overlap, late_parent, participates}:
        return None, None
    return (
        ParentTimeFact(
            valid_from_column=temporal.parent_valid_from,
            valid_to_column=temporal.parent_valid_to,
            open_ended=open_ended,
            interval=IntervalBoundary.CLOSED_OPEN,
            overlap_action=overlap,
            late_parent_action=late_parent,
            child_event_time_column=child_event_time,
        ),
        participates,
    )


def _enum_value(
    raw: str,
    values: dict[str, object],
    code: str,
    label: str,
    location: SourceLocation,
    diagnostics: list[CompileDiagnostic],
) -> object | None:
    value = values.get(raw)
    if value is None:
        _add(
            diagnostics,
            code,
            f"invalid {label} '{raw}'; expected one of: {', '.join(sorted(values))}",
            location,
        )
    return value


def _add(
    diagnostics: list[CompileDiagnostic],
    code: str,
    message: str,
    location: SourceLocation,
) -> None:
    diagnostics.append(
        CompileDiagnostic(
            code=code,
            message=message,
            location=location,
            rule_id="DD-109-temporal-fk",
        )
    )


def _child(location: SourceLocation, suffix: str) -> SourceLocation:
    return SourceLocation(
        path=location.path,
        line=location.line,
        column=location.column,
        pointer=f"{location.pointer}{suffix}",
    )
