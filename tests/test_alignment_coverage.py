# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the deterministic alignment-coverage gate (DD-061)."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.alignment_coverage import (
    ALIGNMENT_HASH_SCHEMA_VERSION,
    check_alignment_coverage,
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
) -> None:
    """Write an alignment file. tables = [(system, table), ...]."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    if source_sha256 == "__auto__":
        source_sha256 = compute_affinity_hash(tables)
    data: dict = {
        "schema_version": schema_version,
        "domain": domain,
        "tables": [{"system": s, "table": t} for s, t in tables],
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
