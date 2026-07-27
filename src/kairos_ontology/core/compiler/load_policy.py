# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Adapt v5 binding load policy to the immutable DD-109 policy contract."""

from __future__ import annotations

from dataclasses import dataclass

from ..projections.dbt.canonical_hash import (
    CANONICAL_HASH_ALGORITHM,
    CANONICAL_HASH_NULL_REPRESENTATION,
    CANONICAL_HASH_VERSION,
)
from ..projections.dbt.policy_normalize import _normalize_hashes, _normalize_incremental
from ..projections.dbt.policy_specs import (
    AuthoredValuesFact,
    BackfillAction,
    CorrectionAction,
    DeleteAction,
    EffectiveValue,
    HashPolicyFact,
    IncrementalPolicyFact,
    LateArrivalAction,
    PolicyProvenance,
    PolicySource,
    ReplayAction,
    ScdType,
)
from .bindings import EntityBinding, IncrementalPolicy
from .result import CompileDiagnostic, CompileError, SourceLocation

_RULE = "DD-109-runtime"
_DELETE_ACTIONS = {
    "error": (DeleteAction.BLOCK, DeleteAction.BLOCK),
    "hard-delete": (DeleteAction.TOMBSTONE, DeleteAction.IGNORE),
    "soft-delete": (DeleteAction.IGNORE, DeleteAction.APPLY_OPERATION),
    "ignore": (DeleteAction.IGNORE, DeleteAction.IGNORE),
}
_LATE_ACTIONS = {
    "error": LateArrivalAction.BLOCK,
    "accept": LateArrivalAction.RECONCILE_WITH_LOOKBACK,
}
_CORRECTION_ACTIONS = {
    "error": CorrectionAction.BLOCK,
    "overwrite": CorrectionAction.REPLACE_BY_TOTAL_ORDER,
    "new-version": CorrectionAction.REVISE_VALID_TIME,
}
_REPLAY_ACTIONS = {
    "error": ReplayAction.BLOCK,
    "idempotent": ReplayAction.IDEMPOTENT_MERGE,
}
_BACKFILL_ACTIONS = {
    "error": BackfillAction.BLOCK,
    "merge": BackfillAction.RANGE_REPLAY_APPROVED,
    "replace-window": BackfillAction.FULL_REBUILD_APPROVED,
}
_SCHEMA_ACTIONS = {"fail": "fail", "append-compatible": "approved-contract-update"}


@dataclass(frozen=True, slots=True)
class LoadPolicyFacts:
    """Adapter carrier composed only of existing immutable policy facts/specs."""

    mode: str
    scd_type: EffectiveValue[ScdType] | None = None
    incremental: IncrementalPolicyFact | None = None
    canonical_hash: HashPolicyFact | None = None


def _location(binding: EntityBinding, pointer: str) -> SourceLocation:
    return SourceLocation(path=binding.source_path, pointer=pointer)


def _diagnostic(
    binding: EntityBinding,
    code: str,
    message: str,
    pointer: str,
    *,
    rule_id: str = _RULE,
) -> CompileDiagnostic:
    return CompileDiagnostic(
        code=code,
        message=message,
        location=_location(binding, pointer),
        rule_id=rule_id,
    )


def _fact(resource: str, predicate: str, values: tuple[str, ...], *, ordered: bool = False):
    return AuthoredValuesFact(
        resource_uri=resource,
        predicate_uri=predicate,
        values=values,
        ordered=ordered,
    )


def _provenance(resource: str, predicate: str, rule_id: str) -> PolicyProvenance:
    return PolicyProvenance(
        source=PolicySource.AUTHORED,
        rule_id=rule_id,
        resource_uri=resource,
        predicate_uri=predicate,
    )


def _effective(resource: str, predicate: str, value, rule_id: str):
    return EffectiveValue(value, _provenance(resource, predicate, rule_id))


def _validate_incremental(
    binding: EntityBinding, policy: IncrementalPolicy, scd: int
) -> tuple[CompileDiagnostic, ...]:
    diagnostics: list[CompileDiagnostic] = []
    ordered_lists = {
        "mergeIdentity": policy.merge_identity,
        "canonicalHashInputs": policy.canonical_hash_inputs,
        "totalOrder": policy.total_order,
    }
    for field, values in ordered_lists.items():
        pointer = f"/load/incremental/{field}"
        if not values or any(not value.strip() for value in values):
            diagnostics.append(
                _diagnostic(
                    binding,
                    "load-policy.incomplete",
                    f"{field} must be a non-empty ordered list",
                    pointer,
                )
            )
        elif len(set(values)) != len(values):
            diagnostics.append(
                _diagnostic(
                    binding,
                    "load-policy.duplicate-value",
                    f"{field} values must be unique and explicitly ordered",
                    pointer,
                )
            )

    runtime_fields = {
        "cdcOperation/column": policy.cdc_operation.column,
        "sourceUpdatedAt": policy.source_updated_at,
        "businessEffectiveAt": policy.business_effective_at,
        "ingestedAt": policy.ingested_at,
    }
    for field, value in runtime_fields.items():
        if not value.strip():
            diagnostics.append(
                _diagnostic(
                    binding,
                    "load-policy.incomplete",
                    f"{field} must name an authored source column",
                    f"/load/incremental/{field}",
                )
            )
    populated_runtime_fields = [value for value in runtime_fields.values() if value.strip()]
    if len(set(populated_runtime_fields)) != len(populated_runtime_fields):
        diagnostics.append(
            _diagnostic(
                binding,
                "load-policy.ambiguous-runtime-fields",
                "CDC operation, source-update, business-effective, and ingestion columns "
                "must be distinct",
                "/load/incremental",
                rule_id="DD-109-time",
            )
        )

    cdc_sets = {
        "insertValues": policy.cdc_operation.insert_values,
        "updateValues": policy.cdc_operation.update_values,
        "deleteValues": policy.cdc_operation.delete_values,
    }
    for field, values in cdc_sets.items():
        pointer = f"/load/incremental/cdcOperation/{field}"
        if not values or any(not value for value in values):
            diagnostics.append(
                _diagnostic(
                    binding,
                    "load-policy.incomplete-cdc",
                    f"{field} must contain at least one non-empty operation value",
                    pointer,
                    rule_id="DD-109-cdc",
                )
            )
        elif len(set(values)) != len(values):
            diagnostics.append(
                _diagnostic(
                    binding,
                    "load-policy.duplicate-cdc-value",
                    f"{field} operation values must be unique",
                    pointer,
                    rule_id="DD-109-cdc",
                )
            )
    for left, right in (
        ("insertValues", "updateValues"),
        ("insertValues", "deleteValues"),
        ("updateValues", "deleteValues"),
    ):
        overlap = sorted(set(cdc_sets[left]) & set(cdc_sets[right]))
        if overlap:
            diagnostics.append(
                _diagnostic(
                    binding,
                    "load-policy.ambiguous-cdc-value",
                    f"CDC values {overlap!r} occur in both {left} and {right}",
                    f"/load/incremental/cdcOperation/{right}",
                    rule_id="DD-109-cdc",
                )
            )

    if policy.lookback.value <= 0 or policy.lookback.unit not in {"hours", "days"}:
        diagnostics.append(
            _diagnostic(
                binding,
                "load-policy.invalid-lookback",
                "lookback must be a positive number of hours or days",
                "/load/incremental/lookback",
                rule_id="DD-109-lookback",
            )
        )
    allowed_corrections = {1: {"error", "overwrite"}, 2: {"error", "new-version"}}
    if policy.correction not in allowed_corrections[scd]:
        diagnostics.append(
            _diagnostic(
                binding,
                "load-policy.scd-correction-incompatible",
                f"SCD{scd} correction must be one of {sorted(allowed_corrections[scd])}",
                "/load/incremental/correction",
                rule_id="DD-109-correction",
            )
        )
    action_values = {
        "delete": (policy.delete, _DELETE_ACTIONS),
        "lateArrival": (policy.late_arrival, _LATE_ACTIONS),
        "replay": (policy.replay, _REPLAY_ACTIONS),
        "backfill": (policy.backfill, _BACKFILL_ACTIONS),
        "schemaEvolution": (policy.schema_evolution, _SCHEMA_ACTIONS),
    }
    for field, (value, supported) in action_values.items():
        if value not in supported:
            diagnostics.append(
                _diagnostic(
                    binding,
                    "load-policy.unsupported-action",
                    f"{field} must be one of {sorted(supported)}, not {value!r}",
                    f"/load/incremental/{field}",
                )
            )
    return tuple(diagnostics)


def adapt_load_policy(binding: EntityBinding) -> LoadPolicyFacts:
    """Validate and adapt one binding-owned load policy without inferring SCD behavior."""
    load = binding.load
    if load.mode == "full-refresh":
        if load.scd is not None or load.incremental is not None:
            raise CompileError(
                [
                    _diagnostic(
                        binding,
                        "load-policy.full-refresh-details",
                        "full-refresh forbids SCD and incremental policy details",
                        "/load",
                    )
                ]
            )
        return LoadPolicyFacts(mode="full-refresh")

    diagnostics: list[CompileDiagnostic] = []
    if load.mode != "incremental":
        diagnostics.append(
            _diagnostic(
                binding,
                "load-policy.unsupported-mode",
                f"load mode must be full-refresh or incremental, not {load.mode!r}",
                "/load/mode",
            )
        )
    if load.scd not in {1, 2}:
        diagnostics.append(
            _diagnostic(
                binding,
                "load-policy.scd-required",
                "incremental load requires explicit scd: 1 or scd: 2",
                "/load/scd",
                rule_id="DD-109-scd",
            )
        )
    if load.incremental is None:
        diagnostics.append(
            _diagnostic(
                binding,
                "load-policy.incremental-required",
                "incremental load requires the complete incremental policy",
                "/load/incremental",
                rule_id="DD-109-incremental",
            )
        )
    if diagnostics:
        raise CompileError(diagnostics)

    assert load.scd is not None and load.incremental is not None
    policy = load.incremental
    diagnostics.extend(_validate_incremental(binding, policy, load.scd))
    if diagnostics:
        raise CompileError(diagnostics)

    resource = f"binding:{binding.name}:load"
    incremental_resource = f"{resource}:incremental"
    hash_resource = f"{resource}:canonical-hash"
    hard_delete, soft_delete = _DELETE_ACTIONS[policy.delete]

    def authored(name: str, *values: str, ordered: bool = False) -> AuthoredValuesFact:
        return _fact(
            incremental_resource,
            f"binding:load/incremental/{name}",
            tuple(values),
            ordered=ordered,
        )

    incremental_fact = IncrementalPolicyFact(
        resource_uri=incremental_resource,
        merge_identity=authored("mergeIdentity", *policy.merge_identity, ordered=True),
        cdc_operation=authored("cdcOperation/column", "_cdc_operation"),
        source_updated_at=authored("sourceUpdatedAt", "_source_updated_at"),
        source_effective_at=authored("businessEffectiveAt", "_source_effective_at"),
        ingested_at=authored("ingestedAt", "_ingested_at"),
        total_order=authored("totalOrder", "_cdc_sequence", ordered=True),
        lookback=authored("lookback", f"{policy.lookback.value} {policy.lookback.unit}"),
        hard_delete=authored("delete", hard_delete.value),
        soft_delete=authored("delete", soft_delete.value),
        late_arrival=authored("lateArrival", _LATE_ACTIONS[policy.late_arrival].value),
        correction=authored("correction", _CORRECTION_ACTIONS[policy.correction].value),
        replay=authored("replay", _REPLAY_ACTIONS[policy.replay].value),
        backfill=authored("backfill", _BACKFILL_ACTIONS[policy.backfill].value),
        schema_change=authored("schemaEvolution", _SCHEMA_ACTIONS[policy.schema_evolution]),
    )
    hash_fact = HashPolicyFact(
        resource_uri=hash_resource,
        version=_fact(hash_resource, "binding:hash/contractVersion", (CANONICAL_HASH_VERSION,)),
        algorithm=_fact(hash_resource, "binding:hash/algorithm", (CANONICAL_HASH_ALGORITHM,)),
        inputs=_fact(
            hash_resource,
            "binding:hash/inputs",
            policy.canonical_hash_inputs,
            ordered=True,
        ),
        null_representation=_fact(
            hash_resource,
            "binding:hash/nullRepresentation",
            (CANONICAL_HASH_NULL_REPRESENTATION,),
        ),
    )

    # Exercise the existing DD-109 normalizers here so the adapter cannot drift into a
    # parallel interpretation of the immutable runtime facts.
    _normalize_incremental((incremental_fact,))
    _normalize_hashes((hash_fact,))

    return LoadPolicyFacts(
        mode="incremental",
        scd_type=_effective(
            resource,
            "binding:load/scd",
            ScdType(str(load.scd)),
            "DD-109-scd",
        ),
        incremental=incremental_fact,
        canonical_hash=hash_fact,
    )
