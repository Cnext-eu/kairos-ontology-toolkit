# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A re-run of `anchor-tables` must not overwrite in silence (#877).

Anchoring is not reproducible at the prompt size it operates at — DD-177 recorded that
for a 23 KB alignment prompt, and `anchor-tables` runs a 121 KB one. Measured back to
back on one hub with a byte-identical prompt and the same seed: the anchor class moved on
12 of 39 tables, the natural key on 13, and two tables were given entirely disjoint keys.

Provider-side determinism is not on offer at this size, so the defect is not the movement
itself. It is that the movement was invisible.
"""

from kairos_ontology.core.anchor_drift import (
    compare_anchor_runs,
    render_drift_summary,
)


def _row(table, **overrides):
    row = {
        "system": "src",
        "table": table,
        "anchor": "CargoItem",
        "natural_key": ["REFXX"],
        "grain_columns": ["REFXX"],
        "domain": "roro",
        "load_hint": "scd",
        "confidence": 0.8,
    }
    row.update(overrides)
    return row


def _previous(*rows):
    return {(r["system"], r["table"]): r for r in rows}


class TestCompareAnchorRuns:
    def test_a_first_run_is_not_drift(self):
        report = compare_anchor_runs({}, [_row("cargo")])

        assert report.is_first_run
        assert render_drift_summary(report) == []

    def test_an_unchanged_rerun_says_so(self):
        report = compare_anchor_runs(_previous(_row("cargo")), [_row("cargo")])

        assert report.drifted == []
        assert report.unchanged == 1
        assert "no drift" in render_drift_summary(report)[0]

    def test_a_changed_anchor_is_reported_with_both_values(self):
        report = compare_anchor_runs(
            _previous(_row("cargo")), [_row("cargo", anchor="Shipment")]
        )

        assert len(report.drifted) == 1
        assert report.drifted[0].changed["anchor"] == ("CargoItem", "Shipment")
        assert "CargoItem → Shipment" in report.drifted[0].describe()

    def test_a_changed_natural_key_earns_its_own_warning(self):
        """It is not an advisory label: it becomes the binding's identity."""
        report = compare_anchor_runs(
            _previous(_row("cargo")), [_row("cargo", natural_key=["DOSNR", "ITEMNR"])]
        )

        text = "\n".join(render_drift_summary(report))

        assert "natural_key" in text
        assert "not advisory" in text

    def test_confidence_alone_is_counted_not_listed(self):
        """It moves on almost every row; listing it would bury what matters."""
        report = compare_anchor_runs(
            _previous(_row("cargo")), [_row("cargo", confidence=0.71)]
        )

        assert report.drifted == []
        assert report.unchanged == 1
        assert report.confidence_moved == 1

    def test_reordering_a_key_is_not_drift(self):
        """Formatting is not movement."""
        report = compare_anchor_runs(
            _previous(_row("cargo", natural_key=["A", "B"])),
            [_row("cargo", natural_key=["A", "B"])],
        )

        assert report.drifted == []

    def test_a_table_that_appeared_and_one_that_vanished(self):
        report = compare_anchor_runs(
            _previous(_row("cargo"), _row("gone")), [_row("cargo"), _row("fresh")]
        )

        assert report.added == ["src.fresh"]
        assert report.removed == ["src.gone"]

    def test_the_summary_counts_every_moved_field(self):
        report = compare_anchor_runs(
            _previous(_row("a"), _row("b"), _row("c")),
            [
                _row("a", anchor="Shipment"),
                _row("b", natural_key=["X"]),
                _row("c"),
            ],
        )

        assert report.counts() == {"anchor": 1, "natural_key": 1}
        assert report.unchanged == 1

    def test_the_report_is_serialisable_for_the_artifact(self):
        report = compare_anchor_runs(
            _previous(_row("cargo")), [_row("cargo", anchor="Shipment")]
        )

        payload = report.to_dict()

        assert payload["unchanged"] == 0
        assert payload["changed"][0]["anchor"] == {"was": "CargoItem", "now": "Shipment"}

    def test_the_advice_points_at_the_durable_seam(self):
        """DD-190's sticky statuses are the fix; the operator has to be told they exist."""
        report = compare_anchor_runs(
            _previous(_row("cargo")), [_row("cargo", anchor="Shipment")]
        )

        assert "status: confirmed" in "\n".join(render_drift_summary(report))
