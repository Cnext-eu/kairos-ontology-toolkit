# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the deterministic alignment-coverage gate (DD-061)."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.alignment_coverage import (
    ALIGNMENT_HASH_SCHEMA_VERSION,
    CustomColumn,
    check_alignment_coverage,
    collect_custom_columns,
    collect_review_columns,
    compute_affinity_hash,
    load_affinity_domain_tables,
)
from kairos_ontology.cli.main import cli


def _write_affinity(analysis_dir: Path, system: str, tables: list[tuple[str, str]]) -> None:
    """Write a schema_version 2 affinity report. tables = [(table, domain), ...]."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "system": system,
        "schema_version": 2,
        "tables": [
            {"table": tbl, "domain": dom, "total_columns": 3}
            for tbl, dom in tables
        ],
    }
    with open(analysis_dir / f"{system}-affinity.yaml", "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False)


def _write_alignment(
    analysis_dir: Path,
    domain: str,
    tables: list[tuple[str, str]],
    *,
    schema_version: int = ALIGNMENT_HASH_SCHEMA_VERSION,
    source_sha256: str | None = "__auto__",
    custom: dict[tuple[str, str], list[dict]] | None = None,
) -> None:
    """Write an alignment file. tables = [(system, table), ...].

    ``custom`` maps a ``(system, table)`` pair to a list of ``custom_columns``
    entries (each a dict with at least ``column``; optional ``suggested_property``
    and ``disposition``).
    """
    analysis_dir.mkdir(parents=True, exist_ok=True)
    if source_sha256 == "__auto__":
        source_sha256 = compute_affinity_hash(tables)
    custom = custom or {}
    data: dict = {
        "schema_version": schema_version,
        "domain": domain,
        "tables": [
            {
                "system": s,
                "table": t,
                "custom_columns": custom.get((s, t), []),
            }
            for s, t in tables
        ],
    }
    if source_sha256 is not None:
        data["source_sha256"] = source_sha256
    with open(analysis_dir / f"{domain}-alignment.yaml", "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False)


class TestComputeAffinityHash:

    def test_order_and_duplicate_insensitive(self):
        a = compute_affinity_hash([("sys", "t1"), ("sys", "t2")])
        b = compute_affinity_hash([("sys", "t2"), ("sys", "t1"), ("sys", "t1")])
        assert a == b

    def test_changes_with_new_table(self):
        a = compute_affinity_hash([("sys", "t1")])
        b = compute_affinity_hash([("sys", "t1"), ("sys", "t2")])
        assert a != b


class TestLoadAffinityDomainTables:

    def test_groups_by_domain(self, tmp_path):
        _write_affinity(tmp_path, "adminpulse", [("tblA", "party"), ("tblB", "commercial")])
        _write_affinity(tmp_path, "erp", [("tblC", "party")])
        result = load_affinity_domain_tables(tmp_path)
        assert result["party"] == {("adminpulse", "tblA"), ("erp", "tblC")}
        assert result["commercial"] == {("adminpulse", "tblB")}

    def test_ignores_unclassified_and_v1(self, tmp_path):
        _write_affinity(tmp_path, "adminpulse", [("tblA", "party"), ("tblB", "")])
        # schema_version 1 file ignored
        with open(tmp_path / "old-affinity.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"system": "old", "schema_version": 1, "tables": [
                {"table": "tblX", "domain": "party"}]}, f)
        result = load_affinity_domain_tables(tmp_path)
        assert result == {"party": {("adminpulse", "tblA")}}


class TestCheckAlignmentCoverage:

    def test_ok_when_complete_and_fresh(self, tmp_path):
        _write_affinity(tmp_path, "adminpulse", [("tblA", "party"), ("tblB", "party")])
        _write_alignment(tmp_path, "party",
                         [("adminpulse", "tblA"), ("adminpulse", "tblB")])
        report = check_alignment_coverage(analysis_dir=tmp_path)
        assert report.ok == ["party"]
        assert not report.is_blocking

    def test_missing_alignment_blocks(self, tmp_path):
        _write_affinity(tmp_path, "adminpulse", [("tblA", "party")])
        report = check_alignment_coverage(analysis_dir=tmp_path)
        assert report.missing == ["party"]
        assert report.is_blocking
        assert report.uncovered_tables["party"] == ["adminpulse.tblA"]

    def test_incomplete_alignment_blocks(self, tmp_path):
        _write_affinity(tmp_path, "adminpulse", [("tblA", "party"), ("tblB", "party")])
        _write_alignment(tmp_path, "party", [("adminpulse", "tblA")])
        report = check_alignment_coverage(analysis_dir=tmp_path)
        assert report.incomplete == ["party"]
        assert report.is_blocking
        assert report.uncovered_tables["party"] == ["adminpulse.tblB"]

    def test_stale_alignment_blocks(self, tmp_path):
        _write_affinity(tmp_path, "adminpulse", [("tblA", "party")])
        # alignment covers tblA but stored hash is for a different set
        _write_alignment(tmp_path, "party", [("adminpulse", "tblA")],
                         source_sha256=compute_affinity_hash([("adminpulse", "stale")]))
        report = check_alignment_coverage(analysis_dir=tmp_path)
        assert report.stale == ["party"]
        assert report.is_blocking

    def test_v1_file_is_unverifiable(self, tmp_path):
        _write_affinity(tmp_path, "adminpulse", [("tblA", "party")])
        _write_alignment(tmp_path, "party", [("adminpulse", "tblA")],
                         schema_version=1, source_sha256=None)
        report = check_alignment_coverage(analysis_dir=tmp_path)
        assert report.unverifiable == ["party"]
        assert not report.is_blocking
        assert report.has_warnings

    def test_orphan_alignment_warns(self, tmp_path):
        _write_affinity(tmp_path, "adminpulse", [("tblA", "party")])
        _write_alignment(tmp_path, "party", [("adminpulse", "tblA")])
        _write_alignment(tmp_path, "ghost", [("adminpulse", "tblZ")])
        report = check_alignment_coverage(analysis_dir=tmp_path)
        assert report.orphan == ["ghost-alignment.yaml"]
        assert report.has_warnings

    def test_domain_filter(self, tmp_path):
        _write_affinity(tmp_path, "adminpulse", [("tblA", "party"), ("tblB", "commercial")])
        _write_alignment(tmp_path, "party", [("adminpulse", "tblA")])
        report = check_alignment_coverage(analysis_dir=tmp_path, domains_filter=["party"])
        assert report.ok == ["party"]
        # commercial out of scope → not reported missing
        assert report.missing == []


class TestCheckAlignmentCLI:

    def test_blocks_when_missing(self, tmp_path):
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        runner = CliRunner()
        result = runner.invoke(cli, [
            "check-alignment", "--analysis-dir", str(analysis),
        ])
        assert result.exit_code == 1, result.output
        assert "MISSING" in result.output

    def test_warn_only_exits_zero(self, tmp_path):
        analysis = tmp_path / "_analysis"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        runner = CliRunner()
        result = runner.invoke(cli, [
            "check-alignment", "--analysis-dir", str(analysis), "--warn-only",
        ])
        assert result.exit_code == 0, result.output

    def test_passes_when_complete(self, tmp_path):
        analysis = tmp_path / "_analysis"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        _write_alignment(analysis, "party", [("adminpulse", "tblA")])
        runner = CliRunner()
        result = runner.invoke(cli, [
            "check-alignment", "--analysis-dir", str(analysis),
        ])
        assert result.exit_code == 0, result.output
        assert "up to date" in result.output


# ---------------------------------------------------------------------------
# Issue #164 — custom-column triage
# ---------------------------------------------------------------------------


class TestCollectCustomColumns:

    def test_extracts_and_classifies(self):
        data = {
            "tables": [
                {
                    "system": "qargo",
                    "table": "companies",
                    "custom_columns": [
                        {"column": "credit_limit", "suggested_property": "creditLimit"},
                        {"column": "created_at"},
                    ],
                }
            ]
        }
        cols = collect_custom_columns(data)
        assert len(cols) == 2
        biz = next(c for c in cols if c.column == "credit_limit")
        assert biz.identity == "qargo.companies.credit_limit"
        assert biz.suggested_property == "creditLimit"
        assert biz.operational is False
        assert biz.disposed is False
        audit = next(c for c in cols if c.column == "created_at")
        assert audit.operational is True

    def test_disposed_when_disposition_set(self):
        cc = CustomColumn(system="s", table="t", column="c", disposition="skip")
        assert cc.disposed is True
        assert CustomColumn(system="s", table="t", column="c").disposed is False
        assert CustomColumn(
            system="s", table="t", column="c", disposition="  "
        ).disposed is False

    def test_handles_missing_custom_columns(self):
        assert collect_custom_columns({"tables": [{"system": "s", "table": "t"}]}) == []


class TestCustomColumnReport:

    def _setup(self, tmp_path, custom):
        _write_affinity(tmp_path, "qargo", [("companies", "party")])
        _write_alignment(
            tmp_path, "party", [("qargo", "companies")],
            custom={("qargo", "companies"): custom},
        )

    def test_collected_in_report(self, tmp_path):
        self._setup(tmp_path, [{"column": "credit_limit"}])
        report = check_alignment_coverage(analysis_dir=tmp_path)
        assert "party" in report.custom_columns
        assert report.has_undisposed_custom_columns is True
        assert len(report.undisposed_custom_columns("party")) == 1

    def test_disposed_columns_not_flagged(self, tmp_path):
        self._setup(tmp_path, [{"column": "credit_limit", "disposition": "model"}])
        report = check_alignment_coverage(analysis_dir=tmp_path)
        assert report.has_undisposed_custom_columns is False
        assert report.undisposed_custom_columns("party") == []

    def test_no_custom_columns(self, tmp_path):
        self._setup(tmp_path, [])
        report = check_alignment_coverage(analysis_dir=tmp_path)
        assert report.has_undisposed_custom_columns is False
        assert report.custom_columns == {}

    def test_collected_even_when_incomplete(self, tmp_path):
        # Domain has two affinity tables but only one is aligned (incomplete);
        # custom columns on the aligned table must still surface.
        _write_affinity(tmp_path, "qargo", [("companies", "party"), ("contacts", "party")])
        _write_alignment(
            tmp_path, "party", [("qargo", "companies")],
            source_sha256="stale-or-partial",
            custom={("qargo", "companies"): [{"column": "credit_limit"}]},
        )
        report = check_alignment_coverage(analysis_dir=tmp_path)
        assert "party" in report.incomplete
        assert report.has_undisposed_custom_columns is True


class TestStrictCustomColumnGate:

    def _setup(self, tmp_path, custom):
        analysis = tmp_path / "_analysis"
        _write_affinity(analysis, "qargo", [("companies", "party")])
        _write_alignment(
            analysis, "party", [("qargo", "companies")],
            custom={("qargo", "companies"): custom},
        )
        return analysis

    def test_default_warns_does_not_block(self, tmp_path):
        analysis = self._setup(tmp_path, [{"column": "credit_limit"}])
        result = CliRunner().invoke(cli, [
            "check-alignment", "--analysis-dir", str(analysis),
        ])
        assert result.exit_code == 0, result.output
        assert "credit_limit" in result.output

    def test_strict_blocks_undisposed(self, tmp_path):
        analysis = self._setup(tmp_path, [{"column": "credit_limit"}])
        result = CliRunner().invoke(cli, [
            "check-alignment", "--analysis-dir", str(analysis), "--strict",
        ])
        assert result.exit_code == 1, result.output
        assert "untriaged custom columns" in result.output

    def test_strict_passes_when_all_disposed(self, tmp_path):
        analysis = self._setup(
            tmp_path, [{"column": "credit_limit", "disposition": "model"}]
        )
        result = CliRunner().invoke(cli, [
            "check-alignment", "--analysis-dir", str(analysis), "--strict",
        ])
        assert result.exit_code == 0, result.output

    def test_strict_warn_only_exits_zero(self, tmp_path):
        analysis = self._setup(tmp_path, [{"column": "credit_limit"}])
        result = CliRunner().invoke(cli, [
            "check-alignment", "--analysis-dir", str(analysis),
            "--strict", "--warn-only",
        ])
        assert result.exit_code == 0, result.output


def _write_alignment_with_reviews(
    analysis_dir: Path,
    domain: str,
    system: str,
    table: str,
    columns: list[dict],
) -> None:
    """Write an alignment file whose single table has the given ``columns``."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": ALIGNMENT_HASH_SCHEMA_VERSION,
        "domain": domain,
        "source_sha256": compute_affinity_hash([(system, table)]),
        "tables": [{"system": system, "table": table, "columns": columns}],
    }
    with open(analysis_dir / f"{domain}-alignment.yaml", "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False)


class TestCollectReviewColumns:
    def test_collects_only_flagged(self):
        data = {
            "tables": [
                {
                    "system": "qargo",
                    "table": "companies",
                    "columns": [
                        {"column": "name", "ref_property": "partyName"},
                        {"column": "SHIPPER_STREET", "ref_property": "partyName",
                         "review": True, "review_reason": "address-part column"},
                    ],
                }
            ]
        }
        flagged = collect_review_columns(data)
        assert len(flagged) == 1
        assert flagged[0].column == "SHIPPER_STREET"
        assert flagged[0].identity == "qargo.companies.SHIPPER_STREET"
        assert "address-part" in flagged[0].reason

    def test_empty_when_none_flagged(self):
        data = {"tables": [{"system": "s", "table": "t",
                            "columns": [{"column": "c", "ref_property": "p"}]}]}
        assert collect_review_columns(data) == []


class TestReviewColumnsReportOnly:

    def _setup(self, tmp_path):
        analysis = tmp_path / "_analysis"
        _write_affinity(analysis, "qargo", [("companies", "party")])
        _write_alignment_with_reviews(
            analysis, "party", "qargo", "companies",
            columns=[
                {"column": "SHIPPER_STREET", "ref_property": "partyName",
                 "review": True, "review_reason": "address-part column mapped to "
                 "non-address property"},
            ],
        )
        return analysis

    def test_review_columns_collected(self, tmp_path):
        analysis = self._setup(tmp_path)
        report = check_alignment_coverage(analysis_dir=analysis)
        assert "party" in report.review_columns
        assert report.review_columns["party"][0].column == "SHIPPER_STREET"

    def test_review_does_not_block(self, tmp_path):
        """DD-069: review flags are report-only — never block, even with --strict."""
        analysis = self._setup(tmp_path)
        report = check_alignment_coverage(analysis_dir=analysis)
        assert report.is_blocking is False
        assert report.has_undisposed_custom_columns is False

    def test_cli_reports_review_section(self, tmp_path):
        analysis = self._setup(tmp_path)
        for flag in ([], ["--strict"]):
            result = CliRunner().invoke(cli, [
                "check-alignment", "--analysis-dir", str(analysis), *flag,
            ])
            assert result.exit_code == 0, result.output
            assert "flagged for review" in result.output
            assert "SHIPPER_STREET" in result.output
