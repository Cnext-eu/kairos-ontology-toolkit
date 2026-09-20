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


def test_the_predicate_and_the_gate_agree_on_the_plain_audit_columns():
    """The #521 cross-check (`is_audit_named`) guards this classification. Where a name is
    unambiguously an audit column, both stages must say so. The two vocabularies are
    otherwise deliberately different: the aligner also knows pipeline artifacts the gate
    has no token for (`source_id`, `load_date`), and the gate's list is wider on the
    business-ambiguous words because it only ever *withholds a rescue* -- reusing it as the
    classifier is the bug the next test pins.
    """
    for column in ("created_at", "row_version", "last_ingest_date", "changed_by"):
        assert is_audit_named(column)
        assert _is_operational_column(column), column


@pytest.mark.parametrize(
    "column",
    [
        # Each contains a token the gate's audit vocabulary also lists -- `batch`,
        # `version`, `tenant`, `snapshot`, `sync`, `delete`, `system`, `dw`, `archive` --
        # and each is business data: a production batch, a tariff or document version,
        # the customer's tenant, a stock snapshot, a sync state, a cancellation reason, a
        # vessel's deadweight, an archived flag on a contract.
        "batch_number",
        "lot_batch_code",
        "tariff_version",
        "document_version",
        "tenant_name",
        "snapshot_date",
        "sync_status",
        "delete_reason",
        "system_of_record",
        "dw_tonnage",
        "archive_box_id",
    ],
)
def test_a_business_word_the_gate_also_knows_does_not_silence_a_column(column):
    """Reusing the gate's *narrowing* vocabulary as the classifier inverted its role:
    these were auto-dispositioned `not-business-data` with no review. Being narrower than
    the gate is the safe direction -- a column not classified operational is deferred to
    a human, never removed."""
    assert not _is_operational_column(column), column


def test_the_recommendation_uses_the_same_classifier():
    """`auto_disposition` kept a parallel substring list, so `unload_date` -- a business
    event whose name contains `load_date` -- still came back `skip` after the predicate
    had moved to whole tokens."""
    from kairos_ontology.core.propose_alignment import auto_disposition, recommend_disposition

    assert auto_disposition("load_date") == "skip"
    assert auto_disposition("unload_date") is None
    assert auto_disposition("upload_timestamp") is None
    assert recommend_disposition("unload_date") == ""
    assert recommend_disposition("created_on") == "skip"


def test_an_empty_or_junk_name_is_not_operational():
    assert not _is_operational_column("")
    assert not _is_operational_column("___")


@pytest.mark.parametrize(
    "column, tokens",
    [
        ("ETLLoadDate", ["etl", "load", "date"]),
        ("DWHLoadDate", ["dwh", "load", "date"]),
        ("ETLBatchID", ["etl", "batch", "id"]),
        ("SystemCreateTimeUtc", ["system", "create", "time", "utc"]),
    ],
)
def test_an_acronym_run_splits_before_the_next_word(column, tokens):
    """The camel-case boundary only knew lower-to-upper, so `ETLLoadDate` tokenised to
    `etlload`, `date` -- a token no vocabulary can match. The substring matcher this
    replaced caught it by accident; the token matcher has to split it on purpose."""
    from kairos_ontology.core.gap_decisions import _name_tokens

    assert _name_tokens(column) == tokens
    assert _is_operational_column(column), column


# ---------------------------------------------------------------------------
# Ingestion-framework artifacts (issue #880)
# ---------------------------------------------------------------------------


class TestIngestionFrameworkArtifacts:
    """Columns written by the loader, never by the business.

    These reached the DD-169 gate as undecided business data, and the recurrence
    heuristic then proposed `blueprint-gap` for one of them — the disposition that
    asserts a reference-model defect to file upstream. They belong in the auto rule.
    """

    @pytest.mark.parametrize(
        "column",
        [
            "_rescued_data",  # Databricks/Spark unparseable-row capture
            "_corrupt_record",  # Spark JSON/CSV reader equivalent
            "ts_ms",  # Debezium CDC event timestamp
            "ttSysStartTime",  # SQL Server system-versioned temporal period
            "ttSysEndTime",
            "__index_level_0__",  # pandas index surviving a parquet round-trip
        ],
    )
    def test_the_artifact_is_operational(self, column):
        assert _is_operational_column(column)

    @pytest.mark.parametrize(
        "column",
        [
            "rescued_units",  # a salvage count is business data
            "record_type",
            "index_number",
            "ts_code",
            "tt_code",
            "corrupt_flag",
            "level_of_service",
            "data_source_name",
        ],
    )
    def test_a_business_name_sharing_a_token_is_not(self, column):
        """The pairs are pairs for this reason: every token above occurs in real names,
        and this predicate auto-disposes to not-business-data without review."""
        assert not _is_operational_column(column)

    @pytest.mark.parametrize(
        "column",
        ["_rescued_data", "_corrupt_record", "ts_ms", "ttSysStartTime", "__index_level_0__"],
    )
    def test_the_cross_check_recognises_what_the_classification_silences(self, column):
        """The documented invariant: operational implies audit-named, so #521's
        cross-check at the write site can see everything this predicate silences."""
        assert _is_operational_column(column)
        assert is_audit_named(column)
