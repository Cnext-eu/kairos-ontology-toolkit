# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Which dispositions answer for a table's columns as well (#881).

A table-grain decision used to retire every gap column in that table from the DD-169
gate, whatever the decision said. On one real hub, 40 table-grain `deferred` records
retired 1,643 columns and the gate never fired once — the ontology came out large and
the silver layer far narrower than the source system.

The cascade is right for exactly two values. `deferred` means "in scope, not modelled
yet", which is the state the gate exists to keep raising; `bound` and
`registered-extension` assert the table *is* being modelled, which is when the gate
matters most.
"""

import pytest
import yaml

from kairos_ontology.core.alignment_report import undecided_gap_columns
from kairos_ontology.core.source_disposition import CASCADING_DISPOSITIONS, DISPOSITIONS

SYSTEM = "src"
TABLE = "cargo"


def _hub(tmp_path, ledger_entries):
    analysis = tmp_path / "integration" / "sources" / "_analysis"
    analysis.mkdir(parents=True)
    (analysis / "roro-alignment.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "domain": "roro",
                "tables": [
                    {
                        "system": SYSTEM,
                        "table": TABLE,
                        "ref_class": "CargoItem",
                        "source_column_count": 3,
                        "columns": [],
                        "custom_columns": [
                            {"column": name, "data_type": "string",
                             "suggested_property": None, "rationale": "no property fits"}
                            for name in ("WIDGET_A", "WIDGET_B", "WIDGET_C")
                        ],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (analysis / "table-dispositions.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "tables": ledger_entries}), encoding="utf-8"
    )
    return tmp_path


def _table_entry(disposition):
    return [{"system": SYSTEM, "table": TABLE, "disposition": disposition,
             "rationale": "why", "decided_by": "user"}]


class TestTableGrainCascade:
    def test_an_undecided_table_owes_every_column(self, tmp_path):
        assert len(undecided_gap_columns(_hub(tmp_path, []))) == 3

    @pytest.mark.parametrize("disposition", sorted(CASCADING_DISPOSITIONS))
    def test_a_cascading_disposition_answers_for_the_columns(self, tmp_path, disposition):
        """`not-business-data` and `blueprint-gap` say something about the columns."""
        hub = _hub(tmp_path / disposition, _table_entry(disposition))

        assert undecided_gap_columns(hub) == []

    @pytest.mark.parametrize(
        "disposition", sorted(set(DISPOSITIONS) - CASCADING_DISPOSITIONS)
    )
    def test_every_other_disposition_still_owes_them(self, tmp_path, disposition):
        """`deferred` is in scope and unmodelled; `bound` and `registered-extension`
        assert the table is being modelled. None of the three answers for a column."""
        hub = _hub(tmp_path / disposition, _table_entry(disposition))

        assert len(undecided_gap_columns(hub)) == 3

    def test_deferred_is_the_one_that_used_to_hide_everything(self, tmp_path):
        """Named on its own because it is the trap: the only value that is not an
        assertion about the data being junk or the blueprint being broken, so it is what
        an operator reaches for."""
        hub = _hub(tmp_path, _table_entry("deferred"))

        assert len(undecided_gap_columns(hub)) == 3

    def test_column_grain_decisions_still_clear_the_gate(self, tmp_path):
        """A hub that did the expensive right thing is unaffected by the change."""
        entries = [
            {"system": SYSTEM, "table": TABLE, "column": name,
             "disposition": "registered-extension", "rationale": "real business data",
             "decided_by": "user"}
            for name in ("WIDGET_A", "WIDGET_B", "WIDGET_C")
        ]

        assert undecided_gap_columns(_hub(tmp_path, entries)) == []

    def test_a_cascading_table_and_a_column_decision_do_not_conflict(self, tmp_path):
        entries = _table_entry("not-business-data") + [
            {"system": SYSTEM, "table": TABLE, "column": "WIDGET_A",
             "disposition": "deferred", "rationale": "x", "decided_by": "user"}
        ]

        assert undecided_gap_columns(_hub(tmp_path, entries)) == []


def test_the_cascading_set_is_a_subset_of_the_closed_disposition_set():
    """A typo here would silence a disposition nobody can record."""
    assert CASCADING_DISPOSITIONS <= set(DISPOSITIONS)
