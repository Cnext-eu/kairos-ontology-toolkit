# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the deterministic source-coverage gate (DD-061)."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.source_coverage import (
    check_source_coverage,
    collect_mapped_subjects,
    collect_source_tables,
)

BRONZE_VOCAB = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix bronze: <https://kairos.cnext.eu/bronze/adminpulse#> .

bronze:tblA a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblA" ;
    kairos-bronze:sourceSystem bronze:AdminPulse .

bronze:tblA_col1 a kairos-bronze:SourceColumn ;
    kairos-bronze:belongsToTable bronze:tblA ;
    kairos-bronze:columnName "col1" .

bronze:tblB a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblB" ;
    kairos-bronze:sourceSystem bronze:AdminPulse .

bronze:tblB_col1 a kairos-bronze:SourceColumn ;
    kairos-bronze:belongsToTable bronze:tblB ;
    kairos-bronze:columnName "col1" .
"""

# Maps only tblA's column → a domain property; tblB left unmapped.
MAPPING_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix bronze: <https://kairos.cnext.eu/bronze/adminpulse#> .
@prefix client: <https://example.org/client#> .

bronze:tblA_col1 skos:closeMatch client:clientName .
"""


def _write_affinity(analysis_dir: Path, system: str, tables: list[tuple[str, str]]) -> None:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "system": system,
        "schema_version": 2,
        "tables": [{"table": t, "domain": d} for t, d in tables],
    }
    with open(analysis_dir / f"{system}-affinity.yaml", "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False)


def _hub(tmp_path: Path) -> tuple[Path, Path, Path]:
    analysis = tmp_path / "integration" / "sources" / "_analysis"
    sources = tmp_path / "integration" / "sources"
    mappings = tmp_path / "model" / "mappings"
    sys_dir = sources / "adminpulse"
    sys_dir.mkdir(parents=True, exist_ok=True)
    mappings.mkdir(parents=True, exist_ok=True)
    (sys_dir / "adminpulse.vocabulary.ttl").write_text(BRONZE_VOCAB, encoding="utf-8")
    return analysis, sources, mappings


class TestCollectHelpers:

    def test_collect_source_tables(self, tmp_path):
        _, sources, _ = _hub(tmp_path)
        tables = collect_source_tables(sources)
        assert ("adminpulse", "tblA") in tables
        assert ("adminpulse", "tblB") in tables
        # table URI + its column URI both present
        assert any("tblA_col1" in u for u in tables[("adminpulse", "tblA")])

    def test_collect_mapped_subjects(self, tmp_path):
        _, _, mappings = _hub(tmp_path)
        (mappings / "adminpulse-to-client.ttl").write_text(MAPPING_TTL, encoding="utf-8")
        mapped = collect_mapped_subjects(mappings)
        assert any("tblA_col1" in s for s in mapped)


class TestCheckSourceCoverage:

    def test_uncovered_table_blocks(self, tmp_path):
        analysis, sources, mappings = _hub(tmp_path)
        _write_affinity(analysis, "adminpulse", [("tblA", "party"), ("tblB", "party")])
        (mappings / "adminpulse-to-client.ttl").write_text(MAPPING_TTL, encoding="utf-8")
        report = check_source_coverage(
            analysis_dir=analysis, sources_dir=sources, mappings_dir=mappings,
        )
        assert report.is_blocking
        assert report.uncovered["party"] == ["adminpulse.tblB"]
        assert report.domain_counts["party"] == (1, 2)

    def test_fully_covered_passes(self, tmp_path):
        analysis, sources, mappings = _hub(tmp_path)
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        (mappings / "adminpulse-to-client.ttl").write_text(MAPPING_TTL, encoding="utf-8")
        report = check_source_coverage(
            analysis_dir=analysis, sources_dir=sources, mappings_dir=mappings,
        )
        assert not report.is_blocking
        assert report.uncovered == {}
        assert report.coverage_pct("party") == 100.0

    def test_no_mappings_all_uncovered(self, tmp_path):
        analysis, sources, mappings = _hub(tmp_path)
        _write_affinity(analysis, "adminpulse", [("tblA", "party"), ("tblB", "party")])
        report = check_source_coverage(
            analysis_dir=analysis, sources_dir=sources, mappings_dir=mappings,
        )
        assert report.uncovered["party"] == ["adminpulse.tblA", "adminpulse.tblB"]

    def test_domain_filter_scopes(self, tmp_path):
        analysis, sources, mappings = _hub(tmp_path)
        _write_affinity(analysis, "adminpulse", [("tblA", "party"), ("tblB", "commercial")])
        (mappings / "adminpulse-to-client.ttl").write_text(MAPPING_TTL, encoding="utf-8")
        report = check_source_coverage(
            analysis_dir=analysis, sources_dir=sources, mappings_dir=mappings,
            domains_filter=["party"],
        )
        assert "commercial" not in report.domain_counts
        assert not report.is_blocking


class TestCheckSourceCoverageCLI:

    def test_blocks_on_uncovered(self, tmp_path):
        analysis, sources, mappings = _hub(tmp_path)
        _write_affinity(analysis, "adminpulse", [("tblA", "party"), ("tblB", "party")])
        (mappings / "adminpulse-to-client.ttl").write_text(MAPPING_TTL, encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(cli, [
            "check-source-coverage",
            "--analysis-dir", str(analysis),
            "--sources", str(sources),
            "--mappings", str(mappings),
        ])
        assert result.exit_code == 1, result.output
        assert "unmapped" in result.output

    def test_warn_only_exits_zero(self, tmp_path):
        analysis, sources, mappings = _hub(tmp_path)
        _write_affinity(analysis, "adminpulse", [("tblB", "party")])
        runner = CliRunner()
        result = runner.invoke(cli, [
            "check-source-coverage",
            "--analysis-dir", str(analysis),
            "--sources", str(sources),
            "--mappings", str(mappings),
            "--warn-only",
        ])
        assert result.exit_code == 0, result.output
