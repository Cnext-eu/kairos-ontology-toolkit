# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for binding-owned DD-109 load-policy adaptation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from kairos_ontology.core.compiler.bindings import (
    CdcOperationSpec,
    EntityBinding,
    GrainSpec,
    IdentitySpec,
    IncrementalPolicy,
    LoadSpec,
    LookbackSpec,
    SourceRef,
)
from kairos_ontology.core.compiler.load_policy import adapt_load_policy
from kairos_ontology.core.compiler.result import CompileError
from kairos_ontology.core.projections.dbt.canonical_hash import (
    CANONICAL_HASH_ALGORITHM,
    CANONICAL_HASH_VERSION,
)
from kairos_ontology.core.projections.dbt.policy_specs import (
    CorrectionAction,
    ScdType,
)


def _binding(*, scd: int = 2, correction: str = "new-version") -> EntityBinding:
    incremental = IncrementalPolicy(
        merge_identity=("customer_id",),
        canonical_hash_inputs=("customer_id", "display_name"),
        cdc_operation=CdcOperationSpec(
            column="operation",
            insert_values=("I",),
            update_values=("U",),
            delete_values=("D",),
        ),
        source_updated_at="source_updated_at",
        business_effective_at="effective_at",
        ingested_at="ingested_at",
        total_order=("source_updated_at", "sequence_number"),
        lookback=LookbackSpec(value=2, unit="days"),
        delete="soft-delete",
        late_arrival="accept",
        correction=correction,
        replay="idempotent",
        backfill="merge",
        schema_evolution="append-compatible",
    )
    return EntityBinding(
        api_version="kairos.eu/v5",
        name="crm-customer",
        domain="party",
        source=SourceRef(relation="crm.customers"),
        target_class="party:Customer",
        grain=GrainSpec(("customer_id",)),
        identity=IdentitySpec("source-natural", ("customer_id",)),
        load=LoadSpec(mode="incremental", scd=scd, incremental=incremental),
        fields=(),
        source_path="model/bindings/crm.binding.yaml",
    )


@pytest.mark.parametrize(
    ("scd", "correction", "effective_correction"),
    [
        (1, "overwrite", CorrectionAction.REPLACE_BY_TOTAL_ORDER),
        (2, "new-version", CorrectionAction.REVISE_VALID_TIME),
    ],
)
def test_adapts_complete_incremental_scd_policy(
    scd: int,
    correction: str,
    effective_correction: CorrectionAction,
) -> None:
    result = adapt_load_policy(_binding(scd=scd, correction=correction))

    assert result.scd_type is not None
    assert result.scd_type.value is ScdType(str(scd))
    assert result.incremental is not None
    assert result.incremental.merge_identity.values == ("customer_id",)
    assert result.incremental.cdc_operation.values == ("_cdc_operation",)
    assert result.incremental.source_updated_at.values == ("_source_updated_at",)
    assert result.incremental.source_effective_at.values == ("_source_effective_at",)
    assert result.incremental.ingested_at.values == ("_ingested_at",)
    assert result.incremental.total_order.values == ("_cdc_sequence",)
    assert result.incremental.lookback.values == ("2 days",)
    assert result.incremental.hard_delete.values == ("ignore",)
    assert result.incremental.soft_delete.values == ("apply-operation",)
    assert result.incremental.late_arrival.values == ("reconcile-with-lookback",)
    assert result.incremental.correction.values == (effective_correction.value,)
    assert result.incremental.replay.values == ("idempotent-merge",)
    assert result.incremental.backfill.values == ("range-replay-approved",)
    assert result.incremental.schema_change.values == ("approved-contract-update",)
    assert result.canonical_hash is not None
    assert result.canonical_hash.version.values == (CANONICAL_HASH_VERSION,)
    assert result.canonical_hash.algorithm.values == (CANONICAL_HASH_ALGORITHM,)
    assert result.canonical_hash.inputs.values == ("customer_id", "display_name")
    assert result.canonical_hash.inputs.ordered


def test_full_refresh_produces_no_incremental_facts() -> None:
    binding = replace(_binding(), load=LoadSpec(mode="full-refresh"))
    result = adapt_load_policy(binding)
    assert result.mode == "full-refresh"
    assert result.scd_type is None
    assert result.incremental is None
    assert result.canonical_hash is None


@pytest.mark.parametrize(
    ("load", "code", "pointer"),
    [
        (
            LoadSpec(mode="full-refresh", scd=2),
            "load-policy.full-refresh-details",
            "/load",
        ),
        (
            LoadSpec(mode="invented"),
            "load-policy.unsupported-mode",
            "/load/mode",
        ),
    ],
)
def test_invalid_load_modes_have_stable_source_located_codes(
    load: LoadSpec, code: str, pointer: str
) -> None:
    with pytest.raises(CompileError) as excinfo:
        adapt_load_policy(replace(_binding(), load=load))

    diagnostic = next(item for item in excinfo.value.diagnostics if item.code == code)
    assert diagnostic.code == code
    assert diagnostic.location.path == "model/bindings/crm.binding.yaml"
    assert diagnostic.location.pointer == pointer


def test_incremental_never_infers_missing_scd_or_policy() -> None:
    binding = replace(_binding(), load=LoadSpec(mode="incremental"))
    with pytest.raises(CompileError) as excinfo:
        adapt_load_policy(binding)
    assert [item.code for item in excinfo.value.diagnostics] == [
        "load-policy.incremental-required",
        "load-policy.scd-required",
    ]
    assert all(
        item.location.path == "model/bindings/crm.binding.yaml"
        for item in excinfo.value.diagnostics
    )
    assert {item.location.pointer for item in excinfo.value.diagnostics} == {
        "/load/incremental",
        "/load/scd",
    }


def test_incomplete_policy_reports_deterministic_source_locations() -> None:
    binding = _binding()
    assert binding.load.incremental is not None
    policy = replace(
        binding.load.incremental,
        canonical_hash_inputs=(),
        total_order=("sequence_number", "sequence_number"),
        cdc_operation=replace(
            binding.load.incremental.cdc_operation,
            update_values=("I",),
        ),
    )
    binding = replace(binding, load=replace(binding.load, incremental=policy))

    with pytest.raises(CompileError) as excinfo:
        adapt_load_policy(binding)

    rendered = tuple(item.render() for item in excinfo.value.diagnostics)
    assert rendered == tuple(sorted(rendered))
    assert {item.code for item in excinfo.value.diagnostics} == {
        "load-policy.ambiguous-cdc-value",
        "load-policy.duplicate-value",
        "load-policy.incomplete",
    }
    assert all(
        item.location.path == "model/bindings/crm.binding.yaml"
        for item in excinfo.value.diagnostics
    )


def test_invalid_action_is_a_diagnostic_not_an_adapter_key_error() -> None:
    binding = _binding()
    assert binding.load.incremental is not None
    policy = replace(binding.load.incremental, delete="invented")
    binding = replace(binding, load=replace(binding.load, incremental=policy))

    with pytest.raises(CompileError) as excinfo:
        adapt_load_policy(binding)

    diagnostic = excinfo.value.diagnostics[0]
    assert diagnostic.code == "load-policy.unsupported-action"
    assert diagnostic.location.pointer == "/load/incremental/delete"


@pytest.mark.parametrize(
    ("mutation", "code", "pointer"),
    [
        (
            lambda policy: replace(policy, canonical_hash_inputs=("customer_id", "customer_id")),
            "load-policy.duplicate-value",
            "/load/incremental/canonicalHashInputs",
        ),
        (
            lambda policy: replace(policy, ingested_at=policy.source_updated_at),
            "load-policy.ambiguous-runtime-fields",
            "/load/incremental",
        ),
        (
            lambda policy: replace(
                policy,
                cdc_operation=replace(policy.cdc_operation, insert_values=()),
            ),
            "load-policy.incomplete-cdc",
            "/load/incremental/cdcOperation/insertValues",
        ),
        (
            lambda policy: replace(
                policy,
                cdc_operation=replace(policy.cdc_operation, delete_values=("D", "D")),
            ),
            "load-policy.duplicate-cdc-value",
            "/load/incremental/cdcOperation/deleteValues",
        ),
        (
            lambda policy: replace(policy, lookback=LookbackSpec(value=0, unit="days")),
            "load-policy.invalid-lookback",
            "/load/incremental/lookback",
        ),
        (
            lambda policy: replace(policy, correction="overwrite"),
            "load-policy.scd-correction-incompatible",
            "/load/incremental/correction",
        ),
    ],
)
def test_each_incremental_policy_diagnostic_is_stable_and_source_located(
    mutation, code: str, pointer: str
) -> None:
    binding = _binding()
    assert binding.load.incremental is not None
    policy = mutation(binding.load.incremental)
    binding = replace(binding, load=replace(binding.load, incremental=policy))

    with pytest.raises(CompileError) as excinfo:
        adapt_load_policy(binding)

    diagnostic = next(item for item in excinfo.value.diagnostics if item.code == code)
    assert diagnostic.location.path == "model/bindings/crm.binding.yaml"
    assert diagnostic.location.pointer == pointer


@pytest.mark.parametrize(
    ("field", "pointer"),
    [
        ("delete", "/load/incremental/delete"),
        ("late_arrival", "/load/incremental/lateArrival"),
        ("replay", "/load/incremental/replay"),
        ("backfill", "/load/incremental/backfill"),
        ("schema_evolution", "/load/incremental/schemaEvolution"),
    ],
)
def test_every_incremental_action_is_explicitly_validated(field: str, pointer: str) -> None:
    binding = _binding()
    assert binding.load.incremental is not None
    policy = replace(binding.load.incremental, **{field: "invented"})
    binding = replace(binding, load=replace(binding.load, incremental=policy))

    with pytest.raises(CompileError) as excinfo:
        adapt_load_policy(binding)

    diagnostic = next(
        item for item in excinfo.value.diagnostics if item.code == "load-policy.unsupported-action"
    )
    assert diagnostic.location.pointer == pointer
