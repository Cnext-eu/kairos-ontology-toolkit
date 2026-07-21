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

from kairos_ontology.core.completeness_model import (
    ALIGNMENT_ALGORITHM_VERSION,
    compute_affinity_hash,
)
from kairos_ontology.core.claim_coverage import check_claims_coverage
from kairos_ontology.core.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    Deviation,
    EvidenceSource,
    Freshness,
    OwnershipOverride,
    ReferenceData,
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


def _write_affinity_with_cols(
    analysis_dir: Path, system: str, tables: list[tuple[str, str, int]]
) -> None:
    """Write a schema_version 2 affinity report carrying per-table total_columns.

    tables = [(table, domain, total_columns), ...].
    """
    analysis_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "system": system,
        "schema_version": 2,
        "tables": [
            {"table": t, "domain": d, "total_columns": n} for t, d, n in tables
        ],
    }
    with open(analysis_dir / f"{system}-affinity.yaml", "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False)


class TestColumnOmissionGate:
    """F6 (toolkit-optimizations) — column-omission (truncation integrity) gate."""

    def _registry_with_cols(self, domain, system, table, covered_total):
        cov = CoverageTable(table=table, total_columns=covered_total,
                            mapped_columns=covered_total, custom_columns=0)
        return ClaimRegistry(
            domain=domain,
            generated_at="2026-06-15T00:00:00Z",
            algorithm_version=ALIGNMENT_ALGORITHM_VERSION,
            freshness=Freshness(
                affinity_sha256=compute_affinity_hash([(system, table)])),
            coverage=[CoverageSystem(system=system, tables=[cov])],
            claims=[],
        )

    def test_shortfall_blocks(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity_with_cols(analysis, "adminpulse", [("tblA", "party", 120)])
        # registry only covers 80 of 120 source columns (prompt truncation).
        write_registry(self._registry_with_cols("party", "adminpulse", "tblA", 80),
                       registry_path(claims, "party"))
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.is_blocking
        assert "party" in report.column_omissions
        assert "80 of 120" in report.column_omissions["party"][0]
        assert "party" not in report.ok

    def test_full_coverage_passes(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity_with_cols(analysis, "adminpulse", [("tblA", "party", 120)])
        write_registry(self._registry_with_cols("party", "adminpulse", "tblA", 120),
                       registry_path(claims, "party"))
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert not report.column_omissions
        assert report.ok == ["party"]

    def test_no_affinity_count_is_backward_compatible(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        # legacy affinity without total_columns → gate never fires.
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(self._registry_with_cols("party", "adminpulse", "tblA", 5),
                       registry_path(claims, "party"))
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert not report.column_omissions
        assert report.ok == ["party"]


class TestGrainConflictGate:
    """F2/F7 (toolkit-optimizations) — persisted grain-conflict records block."""

    def test_grain_conflict_blocks(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        reg = _registry("party", [("adminpulse", "tblA")])
        reg.grain_conflicts = [{
            "type": "grain_conflict",
            "ref_class": "Party",
            "candidate_entities": ["Company", "Person"],
            "source_tables": ["adminpulse.tblA", "adminpulse.tblB"],
            "requires_human_confirmation": True,
        }]
        write_registry(reg, registry_path(claims, "party"))
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.is_blocking
        assert "party" in report.grain_conflicts
        assert "Party: Company, Person" in report.grain_conflicts["party"]

    def test_no_conflict_does_not_block(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(_registry("party", [("adminpulse", "tblA")]),
                       registry_path(claims, "party"))
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert not report.grain_conflicts


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


def _ref_anchor(cid: str, *, status: str = "proposed", class_uri: str | None = None) -> Claim:
    """A reference_data MDM anchor claim."""
    return Claim(
        id=cid,
        type="reference_data",
        status=status,
        disposition="claim",
        mdm_anchor=True,
        class_uri=class_uri,
        reference_data=ReferenceData(code_system="ISO-3166-1", key="alpha2"),
        evidence_sources=[EvidenceSource(type="source_table", system="mdm", table="country")],
    )


class TestMdmAnchorGate:

    def test_pending_anchor_blocks_broad_claim(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        broad = _approved_class_claim("party-foo", "https://ex.org/dom#Foo")
        anchor = _ref_anchor("party-country")  # still proposed
        write_registry(
            _registry("party", [("adminpulse", "tblA")], claims=[broad, anchor]),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.anchor_pending == {"party": ["party-country"]}
        assert report.is_blocking

    def test_decided_anchor_passes(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        broad = _approved_class_claim("party-foo", "https://ex.org/dom#Foo")
        anchor = _ref_anchor(
            "party-country", status="approved", class_uri="https://ex.org/dom#Country"
        )
        write_registry(
            _registry("party", [("adminpulse", "tblA")], claims=[broad, anchor]),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.anchor_pending == {}
        assert report.anchor_missing == []

    def test_broad_claim_without_anchors_warns(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        broad = _approved_class_claim("party-foo", "https://ex.org/dom#Foo")
        write_registry(
            _registry("party", [("adminpulse", "tblA")], claims=[broad]),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.anchor_missing == ["party"]
        assert not report.is_blocking  # pragmatic — warning only
        assert report.has_warnings

    def test_no_anchor_gate_when_no_broad_claims(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        # only a proposed (not approved) class claim — not "broad"
        proposed = Claim(id="party-p", type="class", status="proposed", disposition="claim")
        write_registry(
            _registry("party", [("adminpulse", "tblA")], claims=[proposed]),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.anchor_missing == []
        assert report.anchor_pending == {}

    def test_no_mdm_anchor_flag_skips_gate(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        broad = _approved_class_claim("party-foo", "https://ex.org/dom#Foo")
        anchor = _ref_anchor("party-country")
        write_registry(
            _registry("party", [("adminpulse", "tblA")], claims=[broad, anchor]),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(
            claims_dir=claims, analysis_dir=analysis, check_mdm_anchor=False
        )
        assert report.anchor_pending == {}
        assert report.anchor_missing == []


class TestDeviationLog:

    def _gap(self, cid: str, *, deviation: Deviation | None = None) -> Claim:
        return Claim(
            id=cid,
            type="class",
            status="approved",
            disposition="gap",
            class_uri="https://client.example/native#Widget",
            deviation=deviation,
            evidence_sources=[EvidenceSource(type="source_table", system="crm", table="w")],
        )

    def test_approved_gap_without_deviation_blocks(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(
            _registry("party", [("adminpulse", "tblA")], claims=[self._gap("party-w")]),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.deviation_missing == {"party": ["party-w"]}
        assert report.is_blocking

    def test_documented_gap_passes(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        gap = self._gap(
            "party-w",
            deviation=Deviation(owner="data-arch", reason="no accelerator equivalent"),
        )
        write_registry(
            _registry("party", [("adminpulse", "tblA")], claims=[gap]),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.deviation_missing == {}

    def test_proposed_gap_not_required_to_document(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        gap = Claim(id="party-w", type="class", status="proposed", disposition="gap")
        write_registry(
            _registry("party", [("adminpulse", "tblA")], claims=[gap]),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.deviation_missing == {}


class TestOwnershipBoundary:

    def _approved(self, cid: str, uri: str, *, override: OwnershipOverride | None = None) -> Claim:
        return Claim(
            id=cid,
            type="class",
            status="approved",
            disposition="claim",
            class_uri=uri,
            ownership_override=override,
            evidence_sources=[EvidenceSource(type="source_table", system="crm", table="a")],
        )

    def test_cross_boundary_claim_blocks(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(
            _registry(
                "party", [("adminpulse", "tblA")],
                claims=[self._approved("party-acct", "https://ref.org/finance#Account")],
            ),
            registry_path(claims, "party"),
        )
        data_domains = {
            "finance": {"uris": ["https://ref.org/finance"]},
            "party": {"uris": ["https://ref.org/party"]},
        }
        report = check_claims_coverage(
            claims_dir=claims, analysis_dir=analysis, data_domains=data_domains
        )
        assert len(report.ownership_conflicts) == 1
        conf = report.ownership_conflicts[0]
        assert conf.domain == "party"
        assert conf.claim_id == "party-acct"
        assert conf.owners == ["finance"]
        assert report.is_blocking

    def test_override_clears_conflict(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        override = OwnershipOverride(owner="cdo", rationale="shared conformed dimension")
        write_registry(
            _registry(
                "party", [("adminpulse", "tblA")],
                claims=[
                    self._approved(
                        "party-acct", "https://ref.org/finance#Account", override=override
                    )
                ],
            ),
            registry_path(claims, "party"),
        )
        data_domains = {"finance": {"uris": ["https://ref.org/finance"]}}
        report = check_claims_coverage(
            claims_dir=claims, analysis_dir=analysis, data_domains=data_domains
        )
        assert report.ownership_conflicts == []
        assert not report.is_blocking

    def test_owned_claim_no_conflict(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(
            _registry(
                "party", [("adminpulse", "tblA")],
                claims=[self._approved("party-p", "https://ref.org/party#Person")],
            ),
            registry_path(claims, "party"),
        )
        data_domains = {"party": {"uris": ["https://ref.org/party"]}}
        report = check_claims_coverage(
            claims_dir=claims, analysis_dir=analysis, data_domains=data_domains
        )
        assert report.ownership_conflicts == []

    def test_no_ownership_flag_skips_check(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        write_registry(
            _registry(
                "party", [("adminpulse", "tblA")],
                claims=[self._approved("party-acct", "https://ref.org/finance#Account")],
            ),
            registry_path(claims, "party"),
        )
        data_domains = {"finance": {"uris": ["https://ref.org/finance"]}}
        report = check_claims_coverage(
            claims_dir=claims, analysis_dir=analysis,
            data_domains=data_domains, check_ownership=False,
        )
        assert report.ownership_conflicts == []

    def test_shared_dimension_override_downgrades_duplicate(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(
            analysis, "adminpulse", [("tblA", "party"), ("tblB", "commercial")]
        )
        shared = "https://ref.org/common#Country"
        override = OwnershipOverride(owner="cdo", rationale="conformed dimension")
        write_registry(
            _registry("party", [("adminpulse", "tblA")],
                      claims=[self._approved("party-country", shared)]),
            registry_path(claims, "party"),
        )
        write_registry(
            _registry("commercial", [("adminpulse", "tblB")],
                      claims=[self._approved("commercial-country", shared, override=override)]),
            registry_path(claims, "commercial"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.duplicate_approved == []
        assert len(report.shared_dimensions) == 1
        assert not report.is_blocking
        assert report.has_warnings


class TestPassthroughReview:

    def _passthrough(self, cid: str, evidence: list[EvidenceSource], *, reviewed: bool = False) -> Claim:
        return Claim(
            id=cid,
            type="property",
            status="proposed",
            disposition="passthrough",
            passthrough_reviewed=reviewed,
            evidence_sources=evidence,
        )

    def test_multi_system_passthrough_flagged(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        ev = [
            EvidenceSource(type="source_column", system="crm", table="a", column="x"),
            EvidenceSource(type="source_column", system="erp", table="b", column="x"),
        ]
        write_registry(
            _registry("party", [("adminpulse", "tblA")],
                      claims=[self._passthrough("party-x", ev)]),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.passthrough_review == {"party": ["party-x"]}
        assert not report.is_blocking  # advisory warning
        assert report.has_warnings

    def test_measure_backed_passthrough_flagged(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        ev = [EvidenceSource(type="powerbi_measure", model="ops", measure="Revenue")]
        write_registry(
            _registry("party", [("adminpulse", "tblA")],
                      claims=[self._passthrough("party-rev", ev)]),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.passthrough_review == {"party": ["party-rev"]}

    def test_reviewed_passthrough_not_flagged(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        ev = [
            EvidenceSource(type="source_column", system="crm", table="a", column="x"),
            EvidenceSource(type="source_column", system="erp", table="b", column="x"),
        ]
        write_registry(
            _registry("party", [("adminpulse", "tblA")],
                      claims=[self._passthrough("party-x", ev, reviewed=True)]),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.passthrough_review == {}

    def test_single_system_passthrough_not_flagged(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        ev = [EvidenceSource(type="source_column", system="crm", table="a", column="x")]
        write_registry(
            _registry("party", [("adminpulse", "tblA")],
                      claims=[self._passthrough("party-x", ev)]),
            registry_path(claims, "party"),
        )
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.passthrough_review == {}


class TestSlice4CLI:

    def test_anchor_pending_blocks_via_cli(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        broad = _approved_class_claim("party-foo", "https://ex.org/dom#Foo")
        anchor = _ref_anchor("party-country")
        write_registry(
            _registry("party", [("adminpulse", "tblA")], claims=[broad, anchor]),
            registry_path(claims, "party"),
        )
        result = CliRunner().invoke(cli, [
            "check-claims", "--analysis-dir", str(analysis),
            "--claims-dir", str(claims), "--no-source-coverage",
        ])
        assert result.exit_code == 1, result.output
        assert "MDM anchors undecided" in result.output

    def test_no_mdm_anchor_flag_via_cli(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        broad = _approved_class_claim("party-foo", "https://ex.org/dom#Foo")
        anchor = _ref_anchor("party-country")
        write_registry(
            _registry("party", [("adminpulse", "tblA")], claims=[broad, anchor]),
            registry_path(claims, "party"),
        )
        result = CliRunner().invoke(cli, [
            "check-claims", "--analysis-dir", str(analysis),
            "--claims-dir", str(claims), "--no-source-coverage", "--no-mdm-anchor",
        ])
        assert result.exit_code == 0, result.output

    def test_deviation_missing_blocks_via_cli(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        gap = Claim(
            id="party-w", type="class", status="approved", disposition="gap",
            class_uri="https://client.example/native#Widget",
            evidence_sources=[EvidenceSource(type="source_table", system="crm", table="w")],
        )
        write_registry(
            _registry("party", [("adminpulse", "tblA")], claims=[gap]),
            registry_path(claims, "party"),
        )
        result = CliRunner().invoke(cli, [
            "check-claims", "--analysis-dir", str(analysis),
            "--claims-dir", str(claims), "--no-source-coverage",
        ])
        assert result.exit_code == 1, result.output
        assert "Deviation log incomplete" in result.output


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

    def test_relative_overrides_resolve_from_detected_hub_root(
        self, tmp_path, monkeypatch
    ):
        repo = tmp_path / "repo"
        hub = repo / "ontology-hub"
        analysis = hub / "integration" / "sources" / "_analysis"
        claims = hub / "model" / "claims"
        mappings = hub / "model" / "mappings"
        for path in (analysis, claims, mappings):
            path.mkdir(parents=True)
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        monkeypatch.chdir(repo)

        result = CliRunner().invoke(
            cli,
            [
                "check-claims",
                "--analysis-dir",
                "integration/sources/_analysis",
                "--claims-dir",
                "model/claims",
                "--sources",
                "integration/sources",
                "--mappings",
                "model/mappings",
                "--warn-only",
            ],
        )

        assert result.exit_code == 0, result.output
        assert f"Sources:  {hub / 'integration' / 'sources'}" in result.output

    def test_cli_ignores_generated_contract_affinity_obligations(self, tmp_path):
        analysis = tmp_path / "_analysis"
        claims = tmp_path / "claims"
        sources = tmp_path / "sources"
        generated = sources / "custom-transformations"
        generated.mkdir(parents=True)
        _write_affinity(analysis, "adminpulse", [("tblA", "party")])
        _write_affinity(analysis, "int_party", [("int_party", "party")])
        write_registry(
            _registry("party", [("adminpulse", "tblA")]),
            registry_path(claims, "party"),
        )
        (generated / "int_party.vocabulary.ttl").write_text(
            """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix kairos-dbt: <https://kairos.cnext.eu/dbt-contract#> .
@prefix custom: <https://example.com/source/custom#> .
custom:party a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "int_party" ;
    kairos-dbt:sourceKind "dbt-contract" .
""",
            encoding="utf-8",
        )

        result = CliRunner().invoke(
            cli,
            [
                "check-claims",
                "--analysis-dir",
                str(analysis),
                "--claims-dir",
                str(claims),
                "--sources",
                str(sources),
                "--no-source-coverage",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "party: valid, complete, and up to date" in result.output

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
