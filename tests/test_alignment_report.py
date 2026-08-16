# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Cross-domain alignment coverage with reason codes (DD-168)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.alignment_report import (
    GAP_REASONS,
    REASON_LOW_CONFIDENCE,
    REASON_NO_EVIDENCE,
    REASON_NO_REFERENCE_PROPERTY,
    REASON_OPERATIONAL,
    REASON_ORDER,
    REASON_VENDOR_SLOT,
    build_alignment_report,
    classify_unmapped,
    render_markdown,
)


def _write_domain(directory: Path, domain: str, tables: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{domain}-alignment.yaml").write_text(
        yaml.safe_dump({"domain": domain, "tables": tables}), encoding="utf-8"
    )


def _table(system="qargo", table="companies", columns=None, custom=None) -> dict:
    return {
        "system": system,
        "table": table,
        "columns": columns or [],
        "custom_columns": custom or [],
    }


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_audit_column_is_operational_not_a_gap() -> None:
    assert classify_unmapped({}, "created_at") == REASON_OPERATIONAL


@pytest.mark.parametrize(
    "name", ["Column7", "Column18", "col_3", "Field 12", "unnamed_4", "cf1", "cfx12"]
)
def test_positional_placeholders_are_their_own_bucket(name: str) -> None:
    """AP-036: a real hub exported columns literally named Column2..Column18.

    Undetected they read as unmapped business signal, which is the noise this report
    exists to remove. The shared is_generic_vendor_slot predicate only covers the
    cf-prefixed shape.
    """
    assert classify_unmapped({"example_values": ["x"]}, name) == REASON_VENDOR_SLOT


def test_a_real_name_ending_in_a_digit_is_not_a_placeholder() -> None:
    """address_line_2 and iso_3166_1 are meaningful, not positional slots."""
    for name in ("address_line_2", "iso_3166_1", "leg_2"):
        assert classify_unmapped({"example_values": ["x"]}, name) != REASON_VENDOR_SLOT


def test_a_suggested_property_means_low_confidence_not_absent() -> None:
    entry = {"suggested_property": "https://x/#thing", "example_values": ["a"]}
    assert classify_unmapped(entry, "customer_segment") == REASON_LOW_CONFIDENCE


def test_no_samples_means_nothing_could_be_judged() -> None:
    assert classify_unmapped({}, "customer_segment") == REASON_NO_EVIDENCE


def test_real_data_with_no_candidate_is_the_gap() -> None:
    entry = {"example_values": ["ZEE", "PUR"], "data_type": "varchar"}
    assert classify_unmapped(entry, "loading_quay_code") == REASON_NO_REFERENCE_PROPERTY


def test_operational_wins_over_missing_evidence() -> None:
    """A column needing no action should not be reported as one needing investigation."""
    assert classify_unmapped({}, "updated_by") == REASON_OPERATIONAL


def test_only_actionable_buckets_count_as_gaps() -> None:
    assert GAP_REASONS == {REASON_NO_REFERENCE_PROPERTY, REASON_LOW_CONFIDENCE}
    assert REASON_OPERATIONAL not in GAP_REASONS
    assert REASON_VENDOR_SLOT not in GAP_REASONS


def test_every_reason_has_a_place_in_the_ordering() -> None:
    assert set(REASON_ORDER) == {
        REASON_NO_REFERENCE_PROPERTY,
        REASON_LOW_CONFIDENCE,
        REASON_NO_EVIDENCE,
        REASON_VENDOR_SLOT,
        REASON_OPERATIONAL,
    }
    assert REASON_ORDER[0] == REASON_NO_REFERENCE_PROPERTY


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def test_coverage_counts_mapped_against_every_column(tmp_path: Path) -> None:
    _write_domain(
        tmp_path,
        "party",
        [
            _table(
                columns=[
                    {
                        "column": "name",
                        "ref_property": "https://x/#partyName",
                        "alignment": "exact",
                    },
                    {"column": "vat", "ref_property": "https://x/#taxId", "alignment": "semantic"},
                ],
                custom=[{"column": "created_at"}, {"column": "quay", "example_values": ["ZEE"]}],
            )
        ],
    )

    report = build_alignment_report(tmp_path)

    assert report.columns == 4
    assert report.mapped == 2
    assert report.coverage == 0.5
    assert report.reason_counts() == {REASON_OPERATIONAL: 1, REASON_NO_REFERENCE_PROPERTY: 1}
    assert len(report.gap_columns) == 1


def test_domains_are_ranked_by_gap_size(tmp_path: Path) -> None:
    _write_domain(tmp_path, "small", [_table(custom=[{"column": "created_at"}])])
    _write_domain(
        tmp_path,
        "large",
        [_table(custom=[{"column": f"c{i}", "example_values": ["v"]} for i in range(5)])],
    )

    report = build_alignment_report(tmp_path)

    assert [d.domain for d in report.domains] == ["large", "small"]


def test_gaps_are_ranked_by_table(tmp_path: Path) -> None:
    _write_domain(
        tmp_path,
        "party",
        [
            _table(table="thin", custom=[{"column": "a", "example_values": ["v"]}]),
            _table(
                table="thick",
                custom=[{"column": f"c{i}", "example_values": ["v"]} for i in range(4)],
            ),
        ],
    )

    report = build_alignment_report(tmp_path)

    assert report.gaps_by_table()[0] == ("qargo.thick", 4)


def test_missing_or_empty_analysis_dir_reports_a_notice(tmp_path: Path) -> None:
    absent = build_alignment_report(tmp_path / "nope")
    assert absent.notices and absent.columns == 0

    (tmp_path / "empty").mkdir()
    empty = build_alignment_report(tmp_path / "empty")
    assert any("propose-alignment" in n for n in empty.notices)


def test_one_unreadable_file_does_not_sink_the_report(tmp_path: Path) -> None:
    _write_domain(tmp_path, "good", [_table(columns=[{"column": "a", "ref_property": "x"}])])
    (tmp_path / "bad-alignment.yaml").write_text("{[not: valid", encoding="utf-8")

    report = build_alignment_report(tmp_path)

    assert report.mapped == 1
    assert any("bad-alignment.yaml" in n for n in report.notices)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_markdown_leads_with_the_gap_not_the_raw_unmapped_count(tmp_path: Path) -> None:
    _write_domain(
        tmp_path,
        "party",
        [
            _table(
                columns=[{"column": "name", "ref_property": "x", "alignment": "exact"}],
                custom=[
                    {"column": "created_at"},
                    {"column": "quay_code", "example_values": ["ZEE"], "data_type": "varchar"},
                ],
            )
        ],
    )

    rendered = render_markdown(build_alignment_report(tmp_path))

    assert "1 carry real signal with no canonical home" in rendered.replace("**", "")
    assert "quay_code" in rendered
    # An operational column is counted but never listed as needing a decision.
    assert "created_at" not in rendered.split("## Columns needing a decision")[1]


def test_gap_table_is_truncated_with_an_honest_pointer(tmp_path: Path) -> None:
    _write_domain(
        tmp_path,
        "party",
        [_table(custom=[{"column": f"c{i}", "example_values": ["v"]} for i in range(60)])],
    )

    rendered = render_markdown(build_alignment_report(tmp_path), gap_limit=10)

    assert "and 50 more" in rendered
    assert "--format json" in rendered


@pytest.mark.parametrize("reason", list(REASON_ORDER))
def test_every_reason_carries_guidance(reason: str) -> None:
    from kairos_ontology.core.alignment_report import REASON_GUIDANCE

    assert REASON_GUIDANCE[reason].strip()


class TestPreBindingGate:
    """DD-169: real unmapped signal must be decided before entity binding."""

    def _hub(self, tmp_path: Path, custom: list[dict]) -> Path:
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        _write_domain(analysis, "party", [_table(custom=custom)])
        return tmp_path

    def test_real_signal_without_a_decision_is_reported(self, tmp_path: Path) -> None:
        from kairos_ontology.core.alignment_report import undecided_gap_columns

        hub = self._hub(tmp_path, [{"column": "quay_code", "example_values": ["ZEE"]}])
        undecided = undecided_gap_columns(hub)
        assert [c.column for c in undecided] == ["quay_code"]

    def test_noise_never_reaches_the_gate(self, tmp_path: Path) -> None:
        """Clearing this gate must mean deciding about signal, not clicking through noise."""
        from kairos_ontology.core.alignment_report import undecided_gap_columns

        hub = self._hub(
            tmp_path,
            [
                {"column": "created_at"},
                {"column": "Column7", "example_values": ["x"]},
                {"column": "empty_field"},
            ],
        )
        assert undecided_gap_columns(hub) == []

    def test_a_column_decision_clears_that_column(self, tmp_path: Path) -> None:
        from kairos_ontology.core.alignment_report import undecided_gap_columns
        from kairos_ontology.core.source_disposition import record_disposition

        hub = self._hub(
            tmp_path,
            [
                {"column": "quay_code", "example_values": ["ZEE"]},
                {"column": "lane_code", "example_values": ["A1"]},
            ],
        )
        record_disposition(
            hub_root=hub, system="qargo", table="companies", column="quay_code",
            disposition="blueprint-gap", rationale="No accelerator home for quay codes.",
        )
        assert [c.column for c in undecided_gap_columns(hub)] == ["lane_code"]

    def test_a_table_decision_covers_all_its_columns(self, tmp_path: Path) -> None:
        """Deciding a whole table is out of scope also decides its columns."""
        from kairos_ontology.core.alignment_report import undecided_gap_columns
        from kairos_ontology.core.source_disposition import record_disposition

        hub = self._hub(
            tmp_path,
            [
                {"column": "quay_code", "example_values": ["ZEE"]},
                {"column": "lane_code", "example_values": ["A1"]},
            ],
        )
        record_disposition(
            hub_root=hub, system="qargo", table="companies",
            disposition="not-business-data", rationale="Scratch export.",
        )
        assert undecided_gap_columns(hub) == []

    def test_the_gate_is_domain_scoped(self, tmp_path: Path) -> None:
        from kairos_ontology.core.alignment_report import undecided_gap_columns

        analysis = tmp_path / "integration" / "sources" / "_analysis"
        _write_domain(analysis, "party", [_table(custom=[{"column": "a", "example_values": ["v"]}])])
        _write_domain(
            analysis, "booking",
            [_table(table="orders", custom=[{"column": "b", "example_values": ["v"]}])],
        )
        assert len(undecided_gap_columns(tmp_path)) == 2
        assert [c.column for c in undecided_gap_columns(tmp_path, domains=["party"])] == ["a"]

    def test_no_alignment_yet_is_not_a_failure(self, tmp_path: Path) -> None:
        """A hub that has not aligned cannot be blocked by an alignment gate."""
        from kairos_ontology.core.alignment_report import undecided_gap_columns

        assert undecided_gap_columns(tmp_path) == []

    def test_the_gate_states_how_to_clear_it(self) -> None:
        """A hard stop that does not say how to clear it is an obstacle, not a control."""
        from kairos_ontology.core.alignment_report import GAP_RESOLUTIONS

        joined = " ".join(GAP_RESOLUTIONS)
        assert "register-concept" in joined
        assert "source-disposition set" in joined
        assert "model it in the domain that owns it" in joined
