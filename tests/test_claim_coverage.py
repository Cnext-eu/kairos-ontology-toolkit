# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the deterministic ``check-claims`` gate (DD-EL-1).

Parity replacement for the retired ``check-alignment`` + ``check-source-coverage``
gates: confirms every affinity domain has a valid, complete, fresh Claim Registry,
blocks on cross-file duplicate approvals, and (unless skipped) on unmapped tables.
"""

from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.alignment_coverage import (
    ALIGNMENT_ALGORITHM_VERSION,
    compute_affinity_hash,
)
from kairos_ontology.claim_coverage import check_claims_coverage
from kairos_ontology.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    EvidenceSource,
    Freshness,
    registry_path,
    write_registry,
)
from kairos_ontology.cli.main import cli


def _write_affinity(analysis_dir: Path, system: str, tables: list[tuple[str, str]]) -> None:
    """Write a schema_version 2 affinity report. tables = [(table, domain), ...]."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "system": system,
        "schema_version": 2,
        "tables": [{"table": t, "domain": d} for t, d in tables],
    }
    with open(analysis_dir / f"{system}-affinity.yaml", "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False)


def _registry(
    domain: str,
    tables: list[tuple[str, str]],
    *,
    claims: list[Claim] | None = None,
    fresh: bool = True,
    algorithm_version: int | None = ALIGNMENT_ALGORITHM_VERSION,
    affinity_sha256: str | None = "__auto__",
) -> ClaimRegistry:
    """Build a Claim Registry covering ``tables`` = [(system, table), ...]."""
    systems: dict[str, list[CoverageTable]] = {}
    for system, table in tables:
        systems.setdefault(system, []).append(CoverageTable(table=table))
    coverage = [CoverageSystem(system=s, tables=t) for s, t in systems.items()]
    if affinity_sha256 == "__auto__":
        affinity_sha256 = compute_affinity_hash(tables) if fresh else "stale-digest"
    return ClaimRegistry(
        domain=domain,
        generated_at="2026-06-15T00:00:00Z",
        algorithm_version=algorithm_version,
        freshness=Freshness(affinity_sha256=affinity_sha256),
        coverage=coverage,
        claims=claims or [],
    )


def _approved_class_claim(cid: str, class_uri: str) -> Claim:
    return Claim(
        id=cid,
        type="class",
        status="approved",
        disposition="claim",
        class_uri=class_uri,
        evidence_sources=[EvidenceSource(type="source_sample", system="adminpulse")],
    )


class TestCheckClaimsCoverage:

    def test_ok_when_valid_complete_fresh(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(_registry("party", [("adminpulse", "tblA")]),
                       registry_path(claims, "party"))
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.ok == ["party"]
        assert not report.is_blocking

    def test_missing_registry_blocks(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.missing == ["party"]
        assert report.is_blocking
        assert report.uncovered_tables["party"] == ["adminpulse.tblA"]

    def test_invalid_registry_blocks(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        # approved class claim with no class_uri → structural error.
        bad = Claim(id="party-x", type="class", status="approved", disposition="claim",
                    evidence_sources=[EvidenceSource(type="source_sample")])
        write_registry(_registry("party", [("adminpulse", "tblA")], claims=[bad]),
                       registry_path(claims, "party"))
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert "party" in report.invalid
        assert report.is_blocking

    def test_incomplete_coverage_blocks(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party"), ("tblB", "party")])
        # Registry only covers tblA.
        write_registry(_registry("party", [("adminpulse", "tblA")]),
                       registry_path(claims, "party"))
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.incomplete == ["party"]
        assert report.uncovered_tables["party"] == ["adminpulse.tblB"]
        assert report.is_blocking

    def test_stale_freshness_blocks(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(_registry("party", [("adminpulse", "tblA")], fresh=False),
                       registry_path(claims, "party"))
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.stale == ["party"]
        assert report.is_blocking

    def test_no_hash_is_unverifiable(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(_registry("party", [("adminpulse", "tblA")], affinity_sha256=None),
                       registry_path(claims, "party"))
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.unverifiable == ["party"]
        assert not report.is_blocking
        assert report.has_warnings

    def test_old_algorithm_version_is_unverifiable(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(
            _registry("party", [("adminpulse", "tblA")], algorithm_version=1),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.unverifiable == ["party"]

    def test_orphan_registry_warns(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(_registry("party", [("adminpulse", "tblA")]),
                       registry_path(claims, "party"))
        # ghost registry with no matching affinity domain
        write_registry(_registry("ghost", [("adminpulse", "tblZ")]),
                       registry_path(claims, "ghost"))
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.orphan == ["ghost"]
        assert not report.is_blocking

    def test_unowned_domain_warns(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(_registry("party", [("adminpulse", "tblA")]),
                       registry_path(claims, "party"))
        report = check_claims_coverage(
            claims_dir=claims, analysis_dir=analysis,
            data_domains={"commercial": {}},  # party is NOT owned
        )
        assert report.unowned == ["party"]
        assert not report.is_blocking

    def test_known_domain_not_unowned(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(_registry("party", [("adminpulse", "tblA")]),
                       registry_path(claims, "party"))
        report = check_claims_coverage(
            claims_dir=claims, analysis_dir=analysis,
            data_domains={"party": {}},
        )
        assert report.unowned == []

    def test_duplicate_approved_across_files_blocks(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party"), ("tblB", "commercial")])
        shared = "https://example.org/dom#Foo"
        write_registry(
            _registry("party", [("adminpulse", "tblA")],
                      claims=[_approved_class_claim("party-foo", shared)]),
            registry_path(claims, "party"),
        )
        write_registry(
            _registry("commercial", [("adminpulse", "tblB")],
                      claims=[_approved_class_claim("commercial-foo", shared)]),
            registry_path(claims, "commercial"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert len(report.duplicate_approved) == 1
        dup = report.duplicate_approved[0]
        assert dup.uri == shared
        assert {dup.first, dup.second} == {"party:party-foo", "commercial:commercial-foo"}
        assert report.is_blocking

    def test_proposed_claims_counted(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        proposed = Claim(id="party-p", type="class", status="proposed", disposition="claim")
        write_registry(_registry("party", [("adminpulse", "tblA")], claims=[proposed]),
                       registry_path(claims, "party"))
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.proposed_counts == {"party": 1}
        assert report.has_undecided_claims()
        # proposed claims alone do not block.
        assert not report.is_blocking

    def test_domains_filter(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party"), ("tblB", "commercial")])
        write_registry(_registry("party", [("adminpulse", "tblA")]),
                       registry_path(claims, "party"))
        report = check_claims_coverage(
            claims_dir=claims, analysis_dir=analysis, domains_filter=["party"],
        )
        assert report.ok == ["party"]
        assert "commercial" not in report.missing


class TestCheckClaimsCLI:

    def test_blocks_when_missing(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        result = CliRunner().invoke(cli, [
            "check-claims", "--analysis-dir", str(analysis),
            "--claims-dir", str(claims), "--no-source-coverage",
        ])
        assert result.exit_code == 1, result.output
        assert "MISSING" in result.output

    def test_warn_only_exits_zero(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        result = CliRunner().invoke(cli, [
            "check-claims", "--analysis-dir", str(analysis),
            "--claims-dir", str(claims), "--no-source-coverage", "--warn-only",
        ])
        assert result.exit_code == 0, result.output

    def test_passes_when_complete(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(_registry("party", [("adminpulse", "tblA")]),
                       registry_path(claims, "party"))
        result = CliRunner().invoke(cli, [
            "check-claims", "--analysis-dir", str(analysis),
            "--claims-dir", str(claims), "--no-source-coverage",
        ])
        assert result.exit_code == 0, result.output
        assert "valid, complete, and up to date" in result.output

    def test_strict_blocks_on_proposed(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        proposed = Claim(id="party-p", type="class", status="proposed", disposition="claim")
        write_registry(_registry("party", [("adminpulse", "tblA")], claims=[proposed]),
                       registry_path(claims, "party"))
        # default: proposed claims warn but do not block
        ok = CliRunner().invoke(cli, [
            "check-claims", "--analysis-dir", str(analysis),
            "--claims-dir", str(claims), "--no-source-coverage",
        ])
        assert ok.exit_code == 0, ok.output
        # strict: proposed claims block
        strict = CliRunner().invoke(cli, [
            "check-claims", "--analysis-dir", str(analysis),
            "--claims-dir", str(claims), "--no-source-coverage", "--strict",
        ])
        assert strict.exit_code == 1, strict.output
        assert "undecided" in strict.output.lower()

    def test_legacy_alignment_file_rejected(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        analysis.mkdir(parents=True, exist_ok=True)
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        (analysis / "party-alignment.yaml").write_text("domain: party\n", encoding="utf-8")
        result = CliRunner().invoke(cli, [
            "check-claims", "--analysis-dir", str(analysis),
            "--claims-dir", str(claims), "--no-source-coverage",
        ])
        assert result.exit_code == 1, result.output
        assert "retired" in result.output
        assert "migrate-claims" in result.output
