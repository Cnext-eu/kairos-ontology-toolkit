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
    """Evidence comes from the source vocabulary, never from the alignment entry."""
    assert classify_unmapped({}, "customer_segment", has_samples=False) == REASON_NO_EVIDENCE


def test_unknown_evidence_defaults_to_the_gap_not_to_silence() -> None:
    """The original bug: a custom_columns entry has no example_values key at all.

    Inferring "no evidence" from its absence marked every unmapped column evidence-free
    and emptied the gap bucket — a report that said "0 gaps" because it could not see
    any. Absent knowledge now defaults to the gap, which over-reports rather than under-
    reports, the safer direction for a gate.
    """
    assert classify_unmapped({}, "customer_segment") == REASON_NO_REFERENCE_PROPERTY
    assert (
        classify_unmapped({}, "customer_segment", has_samples=True) == REASON_NO_REFERENCE_PROPERTY
    )


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
                {"column": "Column7"},
                {"column": "empty_field"},
            ],
        )
        # An evidence-free column is only knowable from the source vocabulary.
        source = tmp_path / "integration" / "sources" / "qargo"
        source.mkdir(parents=True, exist_ok=True)
        (source / "companies.yaml").write_text(
            yaml.safe_dump(
                {"name": "companies", "columns": [{"name": "empty_field", "samples": []}]}
            ),
            encoding="utf-8",
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
            hub_root=hub,
            system="qargo",
            table="companies",
            column="quay_code",
            disposition="blueprint-gap",
            rationale="No accelerator home for quay codes.",
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
            hub_root=hub,
            system="qargo",
            table="companies",
            disposition="not-business-data",
            rationale="Scratch export.",
        )
        assert undecided_gap_columns(hub) == []

    def test_the_gate_is_domain_scoped(self, tmp_path: Path) -> None:
        from kairos_ontology.core.alignment_report import undecided_gap_columns

        analysis = tmp_path / "integration" / "sources" / "_analysis"
        _write_domain(
            analysis, "party", [_table(custom=[{"column": "a", "example_values": ["v"]}])]
        )
        _write_domain(
            analysis,
            "booking",
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


class TestDecideOnceGrouping:
    """1,096 gap columns are far fewer decisions: the same name recurs across tables."""

    def _report(self, tmp_path: Path):
        _write_domain(
            tmp_path,
            "party",
            [
                _table(
                    table="a",
                    custom=[
                        {"column": "status", "example_values": ["X"], "data_type": "varchar"},
                        {"column": "only_here", "example_values": ["Y"]},
                    ],
                ),
                _table(
                    table="b",
                    custom=[{"column": "status", "example_values": ["X"], "data_type": "int"}],
                ),
                _table(table="c", custom=[{"column": "status", "example_values": ["X"]}]),
            ],
        )
        return build_alignment_report(tmp_path)

    def test_a_recurring_name_is_one_decision(self, tmp_path: Path) -> None:
        from kairos_ontology.core.alignment_report import group_gaps_by_column

        groups = group_gaps_by_column(self._report(tmp_path))

        assert [g.column for g in groups] == ["status", "only_here"]
        assert groups[0].count == 3
        assert groups[0].tables == ["qargo.a", "qargo.b", "qargo.c"]

    def test_conflicting_types_are_surfaced_not_merged_away(self, tmp_path: Path) -> None:
        """Same name, different type across tables is worth seeing before deciding."""
        from kairos_ontology.core.alignment_report import group_gaps_by_column

        groups = group_gaps_by_column(self._report(tmp_path))
        assert groups[0].data_types == ["int", "varchar"]

    def test_grouping_is_exact_never_fuzzy(self, tmp_path: Path) -> None:
        """order_id and orderId may be different facts; a silent merge would hide that."""
        from kairos_ontology.core.alignment_report import group_gaps_by_column

        _write_domain(
            tmp_path,
            "booking",
            [
                _table(
                    table="d",
                    custom=[
                        {"column": "order_id", "example_values": ["1"]},
                        {"column": "orderId", "example_values": ["1"]},
                    ],
                )
            ],
        )
        names = {g.column for g in group_gaps_by_column(build_alignment_report(tmp_path))}
        assert {"order_id", "orderId"} <= names

    def test_rendered_view_leads_with_the_reduction(self, tmp_path: Path) -> None:
        from kairos_ontology.core.alignment_report import render_gap_groups_markdown

        rendered = render_gap_groups_markdown(self._report(tmp_path)).replace("**", "")
        assert "4 gap columns" in rendered
        assert "2 distinct names" in rendered


# ---------------------------------------------------------------------------
# In-process memo (#598)
# ---------------------------------------------------------------------------


class TestReportMemo:
    """``build_alignment_report`` resolves the whole reference vocabulary, which is
    domain-independent and dominates compile wall clock. ``compile`` asked for the
    identical report twice per invocation (DD-180 anchor gate, then DD-169 column
    gate), so the same corpus was walked twice for one command.
    """

    @staticmethod
    def _count_builds(monkeypatch) -> list[int]:
        from kairos_ontology.core import alignment_report as module

        calls = [0]
        original = module._build_alignment_report_uncached

        def counting(*args, **kwargs):
            calls[0] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(module, "_build_alignment_report_uncached", counting)
        return calls

    def test_two_identical_calls_build_once(self, tmp_path: Path, monkeypatch) -> None:
        calls = self._count_builds(monkeypatch)
        _write_domain(tmp_path, "party", [_table(custom=[{"column": "a"}])])

        first = build_alignment_report(tmp_path)
        second = build_alignment_report(tmp_path)

        assert calls[0] == 1
        assert first is second

    def test_both_compile_gates_share_one_build(self, tmp_path: Path, monkeypatch) -> None:
        """The exact #598 shape: the two gates compile runs back to back."""
        from kairos_ontology.core.alignment_report import (
            undecided_gap_columns,
            undecided_unanchored_tables,
        )

        calls = self._count_builds(monkeypatch)
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        _write_domain(
            analysis, "party", [_table(custom=[{"column": "a", "example_values": ["v"]}])]
        )

        undecided_unanchored_tables(tmp_path, domains=["party"])
        undecided_gap_columns(tmp_path, domains=["party"])

        assert calls[0] == 1

    def test_an_edited_alignment_file_is_not_served_from_the_memo(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """A path-keyed memo alone would answer from before the edit."""
        calls = self._count_builds(monkeypatch)
        _write_domain(tmp_path, "party", [_table(custom=[{"column": "a"}])])
        assert len(build_alignment_report(tmp_path).gap_columns) == 1

        _write_domain(
            tmp_path,
            "party",
            [_table(custom=[{"column": "a"}, {"column": "b"}])],
        )
        assert len(build_alignment_report(tmp_path).gap_columns) == 2
        assert calls[0] == 2

    def test_a_new_domain_file_invalidates_the_memo(self, tmp_path: Path) -> None:
        _write_domain(tmp_path, "party", [_table()])
        assert {d.domain for d in build_alignment_report(tmp_path).domains} == {"party"}

        _write_domain(tmp_path, "booking", [_table(table="orders")])
        assert {d.domain for d in build_alignment_report(tmp_path).domains} == {
            "party",
            "booking",
        }

    def test_one_build_serves_every_domain_scope(self, tmp_path: Path, monkeypatch) -> None:
        """``domains`` is filtered after the build, so it must stay out of the key --
        this is what lets a multi-domain invocation pay the corpus cost once.
        """
        from kairos_ontology.core.alignment_report import undecided_gap_columns

        calls = self._count_builds(monkeypatch)
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        _write_domain(
            analysis, "party", [_table(custom=[{"column": "a", "example_values": ["v"]}])]
        )
        _write_domain(
            analysis,
            "booking",
            [_table(table="orders", custom=[{"column": "b", "example_values": ["v"]}])],
        )

        assert len(undecided_gap_columns(tmp_path)) == 2
        assert [c.column for c in undecided_gap_columns(tmp_path, domains=["party"])] == ["a"]
        assert [c.column for c in undecided_gap_columns(tmp_path, domains=["booking"])] == ["b"]
        assert calls[0] == 1

    def test_no_cache_forces_a_rebuild(self, tmp_path: Path, monkeypatch) -> None:
        """``compile --no-cache`` sets CACHE_ENABLED=False and must bypass this too."""
        from kairos_ontology.core import ontology_loader

        calls = self._count_builds(monkeypatch)
        monkeypatch.setattr(ontology_loader, "CACHE_ENABLED", False)
        _write_domain(tmp_path, "party", [_table()])

        build_alignment_report(tmp_path)
        build_alignment_report(tmp_path)

        assert calls[0] == 2

    def test_distinct_hubs_do_not_share_a_memo_entry(self, tmp_path: Path) -> None:
        left, right = tmp_path / "left", tmp_path / "right"
        _write_domain(left, "party", [_table()])
        _write_domain(right, "booking", [_table(table="orders")])

        assert {d.domain for d in build_alignment_report(left).domains} == {"party"}
        assert {d.domain for d in build_alignment_report(right).domains} == {"booking"}
