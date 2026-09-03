# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-109 canonical hashing and runtime reference semantics."""

from __future__ import annotations

import dataclasses
import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from kairos_ontology.core.adapters import dbt_profile_type
from jinja2 import Environment

from kairos_ontology.core.projections.dbt.canonical_hash import (
    CANONICAL_HASH_V1_GOLDEN_VECTORS,
    CanonicalHashError,
    CanonicalHashSqlInput,
    CanonicalValue,
    canonical_hash_v1,
    canonical_serialize_v1,
    canonical_type_label,
    render_canonical_hash_sql_v1,
    validate_runtime_sql_static,
)
from kairos_ontology.core.projections.dbt.policy_specs import (
    CanonicalTypeKind,
    CanonicalTypeSpec,
    CorrectionAction,
    CdcOperation,
    DeleteAction,
    Scd2TimeBasis,
)
from kairos_ontology.core.projections.dbt.runtime_reference import (
    RuntimeEvent,
    RuntimeSemanticsError,
    bounded_lookback,
    deduplicate_replay,
    materialize_scd1,
    materialize_scd2,
    range_replay,
)


STRING = CanonicalTypeSpec(CanonicalTypeKind.STRING)
TIMESTAMP = CanonicalTypeSpec(CanonicalTypeKind.TIMESTAMP)
UTC = timezone.utc


def _value(kind: CanonicalTypeKind, value: object, **parameters: int) -> CanonicalValue:
    return CanonicalValue(CanonicalTypeSpec(kind, **parameters), value)


def test_golden_vector_bytes_and_sha256_are_frozen():
    assert {item.name for item in CANONICAL_HASH_V1_GOLDEN_VECTORS} == {
        "null-string",
        "empty-string",
        "unicode",
        "decimal",
        "date",
        "time",
        "timestamp",
        "binary",
        "json",
        "unicode-gt8k-bytes",
        "binary-gt8k-bytes",
    }
    for vector in CANONICAL_HASH_V1_GOLDEN_VECTORS:
        assert hashlib.sha256(vector.canonical_bytes).hexdigest() == vector.sha256


@pytest.mark.parametrize(
    ("name", "values"),
    [
        ("null-string", (CanonicalValue(STRING, None),)),
        ("empty-string", (CanonicalValue(STRING, ""),)),
        ("unicode", (CanonicalValue(STRING, "Café \U0001f642"),)),
        (
            "decimal",
            (
                _value(
                    CanonicalTypeKind.DECIMAL,
                    Decimal("123.4000"),
                    precision=18,
                    scale=4,
                ),
            ),
        ),
        ("date", (_value(CanonicalTypeKind.DATE, date(2026, 7, 25)),)),
        (
            "time",
            (_value(CanonicalTypeKind.TIME, time(17, 35, 33, 752000)),),
        ),
        (
            "timestamp",
            (
                CanonicalValue(
                    TIMESTAMP,
                    datetime(
                        2026,
                        7,
                        25,
                        19,
                        35,
                        33,
                        752000,
                        tzinfo=timezone(timedelta(hours=2)),
                    ),
                ),
            ),
        ),
        ("binary", (_value(CanonicalTypeKind.BINARY, bytes.fromhex("00ff10")),)),
        (
            "json",
            (
                _value(
                    CanonicalTypeKind.JSON,
                    {"z": [True, None, 2], "a": "é"},
                ),
            ),
        ),
        (
            "unicode-gt8k-bytes",
            (CanonicalValue(STRING, "\u00e9" * 5000),),
        ),
        (
            "binary-gt8k-bytes",
            (_value(CanonicalTypeKind.BINARY, bytes(range(256)) * 36),),
        ),
    ],
)
def test_reference_codec_matches_every_golden_vector(name, values):
    expected = next(vector for vector in CANONICAL_HASH_V1_GOLDEN_VECTORS if vector.name == name)
    assert canonical_serialize_v1(values) == expected.canonical_bytes
    assert canonical_hash_v1(values) == expected.sha256


def test_null_empty_unicode_and_json_order_are_unambiguous():
    assert canonical_hash_v1((CanonicalValue(STRING, None),)) != canonical_hash_v1(
        (CanonicalValue(STRING, ""),)
    )
    with pytest.raises(CanonicalHashError, match="NFC"):
        canonical_hash_v1((CanonicalValue(STRING, "e\u0301"),))
    json_type = CanonicalTypeSpec(CanonicalTypeKind.JSON)
    assert canonical_hash_v1((CanonicalValue(json_type, '{"b":2,"a":1}'),)) == canonical_hash_v1(
        (CanonicalValue(json_type, {"a": 1, "b": 2}),)
    )


@pytest.mark.parametrize(
    "value",
    [
        _value(CanonicalTypeKind.FLOAT64, 1.5),
        _value(
            CanonicalTypeKind.DECIMAL,
            Decimal("1.234"),
            precision=8,
            scale=2,
        ),
        CanonicalValue(TIMESTAMP, datetime(2026, 7, 25, 12, 0)),
        _value(CanonicalTypeKind.JSON, {"ambiguous": 1.25}),
    ],
)
def test_ambiguous_or_unsupported_values_are_rejected(value):
    with pytest.raises(CanonicalHashError):
        canonical_hash_v1((value,))


def test_fabric_and_databricks_hash_sql_share_contract_without_legacy_ambiguity():
    inputs = (
        CanonicalHashSqlInput("business_id", STRING),
        CanonicalHashSqlInput(
            "amount",
            CanonicalTypeSpec(CanonicalTypeKind.DECIMAL, precision=18, scale=2),
        ),
        CanonicalHashSqlInput("event_at", TIMESTAMP),
    )
    fabric = render_canonical_hash_sql_v1(inputs, "fabric-warehouse")
    databricks = render_canonical_hash_sql_v1(inputs, "databricks")
    for sql in (fabric, databricks):
        lowered = sql.lower()
        assert "kairos-canonical-hash|v1|" in lowered
        assert "sha2" in lowered
        assert "concat_ws" not in lowered
        assert "md5" not in lowered
        assert "typed-length-delimited-null" not in lowered
        assert "decimal(18,2):n:0:;" in lowered
    assert "hashbytes('sha2_256'" in fabric.lower()
    assert "collate latin1_general_100_bin2_utf8" in fabric.lower()
    assert "sha2(encode(" in databricks.lower()
    assert "varchar(8000)" not in fabric.lower()
    assert "varbinary(8000)" not in fabric.lower()
    assert "varchar(max)" in fabric.lower()
    assert "varbinary(max)" in fabric.lower()
    assert "to_utc_timestamp" not in databricks.lower()


@pytest.mark.parametrize("adapter", ["fabric-warehouse", "databricks"])
def test_packaged_macro_and_python_renderer_do_not_drift(adapter):
    inputs = (
        CanonicalHashSqlInput("business_id", STRING),
        CanonicalHashSqlInput(
            "amount",
            CanonicalTypeSpec(CanonicalTypeKind.DECIMAL, precision=18, scale=2),
        ),
        CanonicalHashSqlInput("event_at", TIMESTAMP),
    )
    macro_path = (
        Path(__file__).parents[1]
        / "src"
        / "kairos_ontology"
        / "templates"
        / "dbt"
        / "macros"
        / "kairos_canonical_hash_v1.sql"
    )
    env = Environment()
    env.globals.update(
        target=SimpleNamespace(type=dbt_profile_type(adapter)),
        exceptions=SimpleNamespace(
            raise_compiler_error=lambda message: (_ for _ in ()).throw(CanonicalHashError(message))
        ),
    )
    macro = env.from_string(macro_path.read_text(encoding="utf-8")).module
    macro_sql = macro.kairos_canonical_hash_v1(
        [item.expression for item in inputs],
        [canonical_type_label(item.data_type) for item in inputs],
    )
    python_sql = render_canonical_hash_sql_v1(inputs, adapter)

    def normalize(sql):
        return re.sub(r"\s+", "", sql).lower()

    assert normalize(macro_sql) == normalize(python_sql)


@pytest.mark.parametrize(
    ("adapter", "token"),
    [
        ("fabric-warehouse", "SHA2(value, 256)"),
        ("databricks", "HASHBYTES('SHA2_256', value)"),
        ("databricks", "value COLLATE Latin1_General_100_BIN2_UTF8"),
    ],
)
def test_runtime_static_validation_rejects_foreign_or_truncating_tokens(
    adapter,
    token,
):
    with pytest.raises(CanonicalHashError, match="forbidden token"):
        validate_runtime_sql_static(f"select {token}", adapter)


def _event(
    *,
    value: str,
    effective_day: int,
    ingested_hour: int,
    sequence: str,
    operation: CdcOperation = CdcOperation.UPDATE,
) -> RuntimeEvent:
    return RuntimeEvent(
        merge_identity=("entity-1",),
        operation=operation,
        source_updated_at=datetime(2026, 7, effective_day, 12, tzinfo=UTC),
        source_effective_at=datetime(2026, 7, effective_day, tzinfo=UTC),
        ingested_at=datetime(2026, 7, 25, ingested_hour, tzinfo=UTC),
        tie_breakers=(sequence,),
        values=(CanonicalValue(STRING, value),),
    )


def test_scd1_total_order_replay_delete_and_reinsert_are_idempotent():
    first = _event(value="A", effective_day=20, ingested_hour=10, sequence="1")
    correction = _event(value="B", effective_day=20, ingested_hour=11, sequence="2")
    deleted = _event(
        value="B",
        effective_day=21,
        ingested_hour=12,
        sequence="3",
        operation=CdcOperation.DELETE,
    )
    replayed = materialize_scd1((first, correction, correction, deleted))
    assert len(replayed) == 1
    assert replayed[0].is_deleted
    reinsert = _event(
        value="C",
        effective_day=22,
        ingested_hour=13,
        sequence="4",
        operation=CdcOperation.INSERT,
    )
    result = materialize_scd1((first, correction, deleted, reinsert, reinsert))
    assert len(result) == 1
    assert not result[0].is_deleted
    assert result[0].values[0].value == "C"


def test_exact_total_order_tie_with_different_values_fails_closed():
    first = _event(value="A", effective_day=20, ingested_hour=10, sequence="1")
    tied = dataclasses.replace(
        first,
        values=(CanonicalValue(STRING, "contradiction"),),
    )
    with pytest.raises(RuntimeSemanticsError, match="contradictory"):
        deduplicate_replay((first, tied))


def test_scd2_separates_business_valid_and_system_time_with_half_open_intervals():
    late = _event(value="late", effective_day=20, ingested_hour=12, sequence="2")
    earlier = _event(value="early", effective_day=19, ingested_hour=11, sequence="1")
    corrected = _event(value="corrected", effective_day=20, ingested_hour=13, sequence="3")
    versions = materialize_scd2(
        (late, earlier, corrected, corrected),
        time_basis=Scd2TimeBasis.BUSINESS_VALID,
        correction_action=CorrectionAction.REPLACE_BY_TOTAL_ORDER,
    )
    assert [item.values[0].value for item in versions] == ["early", "corrected"]
    assert versions[0].business_valid_to == versions[1].business_valid_from
    assert versions[0].system_from != versions[0].business_valid_from
    assert sum(item.is_current for item in versions) == 1


def test_scd2_append_correction_reference_fails_closed():
    with pytest.raises(RuntimeSemanticsError, match="DD-109 SCD2 append-correction"):
        materialize_scd2(
            (_event(value="A", effective_day=20, ingested_hour=10, sequence="1"),),
            time_basis=Scd2TimeBasis.BUSINESS_VALID,
            correction_action=CorrectionAction.APPEND_CORRECTION,
        )


def test_load_history_never_uses_business_effective_time_as_system_time():
    versions = materialize_scd2(
        (
            _event(value="A", effective_day=20, ingested_hour=10, sequence="1"),
            _event(value="B", effective_day=19, ingested_hour=11, sequence="2"),
        ),
        time_basis=Scd2TimeBasis.LOAD_HISTORY,
    )
    assert all(item.business_valid_from is None for item in versions)
    assert [item.system_from.hour for item in versions] == [10, 11]
    assert versions[0].system_to == versions[1].system_from


def test_delete_block_quarantine_lookback_and_range_replay_are_explicit():
    deleted = _event(
        value="A",
        effective_day=20,
        ingested_hour=10,
        sequence="1",
        operation=CdcOperation.DELETE,
    )
    for action in (DeleteAction.BLOCK, DeleteAction.QUARANTINE):
        with pytest.raises(RuntimeSemanticsError, match=action.value):
            materialize_scd1((deleted,), delete_action=action)
    old = _event(value="old", effective_day=18, ingested_hour=8, sequence="1")
    events = (
        dataclasses.replace(
            old,
            ingested_at=datetime(2026, 7, 23, 8, tzinfo=UTC),
        ),
        _event(value="new", effective_day=24, ingested_hour=12, sequence="2"),
    )
    assert (
        len(
            bounded_lookback(
                events,
                watermark=datetime(2026, 7, 25, 14, tzinfo=UTC),
                amount=1,
                unit="days",
            )
        )
        == 1
    )
    assert range_replay(
        events,
        start=datetime(2026, 7, 24, tzinfo=UTC),
        end=datetime(2026, 7, 25, tzinfo=UTC),
    ) == (events[1],)


def test_hard_and_soft_delete_policies_are_independent():
    active = _event(
        value="active",
        effective_day=19,
        ingested_hour=9,
        sequence="0",
    )
    hard = _event(
        value="hard",
        effective_day=20,
        ingested_hour=10,
        sequence="1",
        operation=CdcOperation.DELETE,
    )
    soft = _event(
        value="soft",
        effective_day=21,
        ingested_hour=11,
        sequence="2",
        operation=CdcOperation.SOFT_DELETE,
    )
    ignored_hard = materialize_scd1(
        (active, hard),
        hard_delete_action=DeleteAction.IGNORE,
        soft_delete_action=DeleteAction.APPLY_OPERATION,
    )
    assert len(ignored_hard) == 1
    assert ignored_hard[0].values[0].value == "active"
    assert not ignored_hard[0].is_deleted
    soft_result = materialize_scd1(
        (soft,),
        hard_delete_action=DeleteAction.IGNORE,
        soft_delete_action=DeleteAction.APPLY_OPERATION,
    )
    assert len(soft_result) == 1
    assert soft_result[0].is_deleted
    with pytest.raises(RuntimeSemanticsError, match="absence-based hard delete"):
        materialize_scd1(
            (hard,),
            hard_delete_action=DeleteAction.APPLY_OPERATION,
            soft_delete_action=DeleteAction.IGNORE,
        )


def test_exact_total_order_tie_with_different_operations_fails_closed():
    update = _event(value="same", effective_day=20, ingested_hour=10, sequence="1")
    deleted = dataclasses.replace(update, operation=CdcOperation.DELETE)
    with pytest.raises(RuntimeSemanticsError, match="contradictory"):
        deduplicate_replay((update, deleted))
