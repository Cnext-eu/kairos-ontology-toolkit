# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`_is_operational_column` matches name tokens, not bare substrings (#522).

This predicate is load-bearing. `operational` is one of two reason codes DD-186
auto-dispositions to `not-business-data` without human review, and that is the only
disposition which *removes* a column from the DD-169 gate rather than deferring it. A
false positive therefore deletes real business data from the pipeline.

It was matched with a bare `in`, so three patterns caught far more than they intended:

| pattern | intended | also caught |
|---|---|---|
| `timestamp` | `created_timestamp` | `transaction_timestamp`, `pickup_start_timestamp` |
| `source_id` | a pipeline source identifier | `resource_id` |
| `_by` | `created_by` | `owned_by_subco` |

Measured on one hub: of 185 columns auto-dispositioned from this reason, **114 (62%)**
were contradicted by the aligner's own output in the same run.

#521 added a cross-check at the write site so the loss is no longer irreversible. This is
the classification itself, which #521 deliberately did not touch because the same list
also drives `recommend_disposition` inside the aligner.
"""

from __future__ import annotations

import pytest

from kairos_ontology.core.gap_decisions import is_audit_named
from kairos_ontology.core.propose_alignment import _is_operational_column


@pytest.mark.parametrize(
    "column",
    [
        "created_at",
        "CreatedAt",
        "updated_timestamp",
        "created_by",
        "modified_by",
        "SystemCreateTimeUtc",
        "row_version",
        "rowversion",
        "load_date",
        "load_ts",
        "source_system",
        "source_id",
        "etl_batch_id",
        "record_guid",
        "row_hash",
        "is_deleted",
    ],
)
def test_pipeline_metadata_is_still_recognised(column):
    """Narrowing must not become blindness: everything the rule is for still matches."""
    assert _is_operational_column(column), column


@pytest.mark.parametrize(
    "column",
    [
        # Occurrence times -- the central fact of an event or ledger row, not metadata
        # about it. All five were auto-dispositioned on the reported hub.
        "transaction_timestamp",
        "actual_start_timestamp",
        "planned_start_timestamp",
        "pickup_start_timestamp",
        "origin_timestamp",
        "timestamp_posted",
        # A business foreign key that merely ends in the same three letters.
        "resource_id",
        # A business relationship, not an audit trail.
        "owned_by_subco",
    ],
)
def test_business_data_is_no_longer_swept_up(column):
    assert not _is_operational_column(column), column


def test_a_bare_type_suffix_never_decides():
    """Audit intent is carried by the action, never by the type. `timestamp` on its own
    says what the column holds, not what it means."""
    assert not _is_operational_column("timestamp")
    assert _is_operational_column("created_timestamp")


def test_by_is_operational_only_in_final_position():
    assert _is_operational_column("changed_by")
    assert not _is_operational_column("owned_by_subco")
    assert not _is_operational_column("by_product_line")


def test_source_id_is_a_pair_not_a_substring():
    assert _is_operational_column("source_id")
    assert not _is_operational_column("resource_id")
    assert not _is_operational_column("outsourced_id")


def test_the_predicate_agrees_with_the_gate_wherever_the_gate_has_an_opinion():
    """The two stages disagreeing about what "audit" means is how this bug arose, so the
    aligner reuses `gap_decisions._AUDIT_NAME_TOKENS` rather than keeping a parallel list.

    The aligner is deliberately *wider* — it also covers pipeline artifacts like
    `source_id` and `load_date` that the gate has no token for — but it must never be
    narrower, or a column the gate calls audit would reach the aligner as business data.
    """
    for column in ("created_at", "row_version", "last_ingest_date", "changed_by"):
        assert is_audit_named(column)
        assert _is_operational_column(column), column


def test_an_empty_or_junk_name_is_not_operational():
    assert not _is_operational_column("")
    assert not _is_operational_column("___")
