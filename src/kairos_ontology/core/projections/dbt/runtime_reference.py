# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Pure Python DD-109 runtime reference used by golden semantic tests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from .canonical_hash import CanonicalValue, canonical_hash_v1
from .policy_specs import (
    CorrectionAction,
    CdcOperation,
    DeleteAction,
    Scd2TimeBasis,
)


class RuntimeSemanticsError(ValueError):
    """The event stream violates deterministic DD-109 runtime facts."""


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    merge_identity: tuple[str, ...]
    operation: CdcOperation
    source_updated_at: datetime
    source_effective_at: datetime
    ingested_at: datetime
    tie_breakers: tuple[str, ...]
    values: tuple[CanonicalValue, ...]

    @property
    def total_order(self) -> tuple[object, ...]:
        return (
            self.source_effective_at,
            self.source_updated_at,
            self.ingested_at,
            *self.tie_breakers,
        )

    @property
    def event_identity(self) -> tuple[object, ...]:
        return (
            *self.merge_identity,
            *self.total_order,
        )

    @property
    def change_hash(self) -> str:
        return canonical_hash_v1(self.values)


@dataclass(frozen=True, slots=True)
class RuntimeVersion:
    merge_identity: tuple[str, ...]
    values: tuple[CanonicalValue, ...]
    change_hash: str
    source_updated_at: datetime
    source_effective_at: datetime
    ingested_at: datetime
    tie_breakers: tuple[str, ...]
    business_valid_from: datetime | None
    business_valid_to: datetime | None
    system_from: datetime
    system_to: datetime | None
    is_current: bool
    is_deleted: bool


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RuntimeSemanticsError(f"{label} must carry an explicit time zone")
    return value.astimezone(timezone.utc)


def _validated_event(event: RuntimeEvent) -> RuntimeEvent:
    if not event.merge_identity:
        raise RuntimeSemanticsError("merge identity must not be empty")
    if not event.tie_breakers:
        raise RuntimeSemanticsError("total-order tie breakers must not be empty")
    return replace(
        event,
        source_updated_at=_utc(event.source_updated_at, "source_updated_at"),
        source_effective_at=_utc(event.source_effective_at, "source_effective_at"),
        ingested_at=_utc(event.ingested_at, "ingested_at"),
    )


def deduplicate_replay(events: tuple[RuntimeEvent, ...]) -> tuple[RuntimeEvent, ...]:
    """Collapse byte-identical replay and reject contradictory exact ties."""
    by_event: dict[tuple[object, ...], RuntimeEvent] = {}
    for raw_event in events:
        event = _validated_event(raw_event)
        previous = by_event.get(event.event_identity)
        if previous is not None and (
            previous.operation is not event.operation
            or previous.change_hash != event.change_hash
        ):
            raise RuntimeSemanticsError(
                "the same complete event order carries contradictory values"
            )
        by_event[event.event_identity] = event
    return tuple(
        sorted(
            by_event.values(),
            key=lambda item: (item.merge_identity, item.total_order),
        )
    )


def bounded_lookback(
    events: tuple[RuntimeEvent, ...],
    *,
    watermark: datetime,
    amount: int,
    unit: str,
) -> tuple[RuntimeEvent, ...]:
    """Return the deterministic bounded replay window."""
    if amount < 1 or unit not in {"hours", "days"}:
        raise RuntimeSemanticsError("lookback requires positive hours or days")
    normalized_watermark = _utc(watermark, "watermark")
    delta = timedelta(hours=amount) if unit == "hours" else timedelta(days=amount)
    floor = normalized_watermark - delta
    return tuple(
        event
        for event in deduplicate_replay(events)
        if event.ingested_at >= floor
    )


def range_replay(
    events: tuple[RuntimeEvent, ...],
    *,
    start: datetime,
    end: datetime,
) -> tuple[RuntimeEvent, ...]:
    """Select a half-open business-effective backfill range."""
    normalized_start = _utc(start, "start")
    normalized_end = _utc(end, "end")
    if normalized_start >= normalized_end:
        raise RuntimeSemanticsError("range replay requires start < end")
    return tuple(
        event
        for event in deduplicate_replay(events)
        if normalized_start <= event.source_effective_at < normalized_end
    )


def _apply_delete(
    event: RuntimeEvent,
    hard_delete_action: DeleteAction,
    soft_delete_action: DeleteAction,
) -> tuple[bool, bool]:
    if event.operation is CdcOperation.DELETE:
        delete_action = hard_delete_action
        delete_kind = "captured CDC hard delete"
    elif event.operation is CdcOperation.SOFT_DELETE:
        delete_action = soft_delete_action
        delete_kind = "normalized soft-delete flag"
    else:
        return True, False
    if delete_action is DeleteAction.IGNORE:
        return False, False
    if delete_action in {DeleteAction.BLOCK, DeleteAction.QUARANTINE}:
        raise RuntimeSemanticsError(
            f"{delete_kind} requires {delete_action.value} handling outside the main relation"
        )
    if (
        event.operation is CdcOperation.DELETE
        and delete_action is DeleteAction.APPLY_OPERATION
    ):
        raise RuntimeSemanticsError(
            "physical/absence-based hard delete is unsupported; use tombstone or ignore"
        )
    return True, True


def materialize_scd1(
    events: tuple[RuntimeEvent, ...],
    *,
    delete_action: DeleteAction | None = None,
    hard_delete_action: DeleteAction = DeleteAction.TOMBSTONE,
    soft_delete_action: DeleteAction = DeleteAction.APPLY_OPERATION,
) -> tuple[RuntimeVersion, ...]:
    """Resolve one deterministic current-state row per merge identity."""
    if delete_action is not None:
        hard_delete_action = delete_action
    latest: dict[tuple[str, ...], tuple[RuntimeEvent, bool]] = {}
    for event in deduplicate_replay(events):
        include, deleted = _apply_delete(
            event,
            hard_delete_action,
            soft_delete_action,
        )
        if not include:
            continue
        previous = latest.get(event.merge_identity)
        if previous is None or event.total_order > previous[0].total_order:
            latest[event.merge_identity] = (event, deleted)
    versions: list[RuntimeVersion] = []
    for identity, (event, deleted) in sorted(latest.items()):
        versions.append(
            RuntimeVersion(
                merge_identity=identity,
                values=event.values,
                change_hash=event.change_hash,
                source_updated_at=event.source_updated_at,
                source_effective_at=event.source_effective_at,
                ingested_at=event.ingested_at,
                tie_breakers=event.tie_breakers,
                business_valid_from=None,
                business_valid_to=None,
                system_from=event.ingested_at,
                system_to=None,
                is_current=True,
                is_deleted=deleted,
            )
        )
    return tuple(versions)


def materialize_scd2(
    events: tuple[RuntimeEvent, ...],
    *,
    time_basis: Scd2TimeBasis,
    correction_action: CorrectionAction = CorrectionAction.REPLACE_BY_TOTAL_ORDER,
    delete_action: DeleteAction | None = None,
    hard_delete_action: DeleteAction = DeleteAction.TOMBSTONE,
    soft_delete_action: DeleteAction = DeleteAction.APPLY_OPERATION,
) -> tuple[RuntimeVersion, ...]:
    """Build deterministic half-open valid/system history from replayable events."""
    if delete_action is not None:
        hard_delete_action = delete_action
    replayed = deduplicate_replay(events)
    if correction_action is CorrectionAction.APPEND_CORRECTION:
        raise RuntimeSemanticsError(
            "DD-109 SCD2 append-correction is unsupported; use "
            "replace-by-total-order or revise-valid-time"
        )
    if correction_action not in {
        CorrectionAction.REPLACE_BY_TOTAL_ORDER,
        CorrectionAction.REVISE_VALID_TIME,
    }:
        raise RuntimeSemanticsError(
            f"correction event requires {correction_action.value} handling"
        )

    grouped: dict[tuple[str, ...], list[RuntimeEvent]] = {}
    for event in replayed:
        grouped.setdefault(event.merge_identity, []).append(event)
    result: list[RuntimeVersion] = []
    for identity, identity_events in sorted(grouped.items()):
        basis_groups: dict[datetime, list[RuntimeEvent]] = {}
        for event in identity_events:
            basis = (
                event.source_effective_at
                if time_basis is Scd2TimeBasis.BUSINESS_VALID
                else event.ingested_at
            )
            basis_groups.setdefault(basis, []).append(event)
        corrected: list[RuntimeEvent] = []
        for same_basis in basis_groups.values():
            ordered = sorted(same_basis, key=lambda item: item.total_order)
            corrected.append(ordered[-1])
        ordered_events = sorted(
            corrected,
            key=lambda item: (
                item.source_effective_at
                if time_basis is Scd2TimeBasis.BUSINESS_VALID
                else item.ingested_at,
                item.total_order,
            ),
        )
        changed: list[tuple[RuntimeEvent, bool]] = []
        previous_signature: tuple[str, bool] | None = None
        for event in ordered_events:
            include, deleted = _apply_delete(
                event,
                hard_delete_action,
                soft_delete_action,
            )
            if not include:
                continue
            signature = (event.change_hash, deleted)
            if signature != previous_signature:
                changed.append((event, deleted))
                previous_signature = signature

        system_order = sorted(
            (event for event, _ in changed),
            key=lambda item: (item.ingested_at, item.total_order),
        )
        system_to = {
            event.event_identity: (
                system_order[index + 1].ingested_at
                if index + 1 < len(system_order)
                else None
            )
            for index, event in enumerate(system_order)
        }
        current_event = system_order[-1] if system_order else None
        for index, (event, deleted) in enumerate(changed):
            business_from = (
                event.source_effective_at
                if time_basis is Scd2TimeBasis.BUSINESS_VALID
                else None
            )
            business_to = (
                changed[index + 1][0].source_effective_at
                if business_from is not None and index + 1 < len(changed)
                else None
            )
            result.append(
                RuntimeVersion(
                    merge_identity=identity,
                    values=event.values,
                    change_hash=event.change_hash,
                    source_updated_at=event.source_updated_at,
                    source_effective_at=event.source_effective_at,
                    ingested_at=event.ingested_at,
                    tie_breakers=event.tie_breakers,
                    business_valid_from=business_from,
                    business_valid_to=business_to,
                    system_from=event.ingested_at,
                    system_to=system_to[event.event_identity],
                    is_current=event is current_event,
                    is_deleted=deleted,
                )
            )
    return tuple(
        sorted(
            result,
            key=lambda item: (
                item.merge_identity,
                item.business_valid_from or item.system_from,
                item.system_from,
            ),
        )
    )
