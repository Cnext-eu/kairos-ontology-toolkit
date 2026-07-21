# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for canonical completeness facts and proposal triage helpers."""

from pathlib import Path

import yaml

from kairos_ontology.core.completeness_model import (
    compute_affinity_hash,
    compute_completeness_facts,
    load_affinity_domain_tables,
)
from kairos_ontology.core.claim_coverage import evaluate_claims_coverage
from kairos_ontology.core.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    EvidenceSource,
    Freshness,
    write_registry,
)
from kairos_ontology.core.propose_alignment import (
    auto_disposition,
    is_generic_vendor_slot,
    recommend_disposition,
)
from kairos_ontology.core.source_coverage import evaluate_source_coverage


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


class TestDispositionHeuristics:
    def test_generic_vendor_slot_detection(self):
        assert is_generic_vendor_slot("CFSTRING33")
        assert is_generic_vendor_slot("CFENUMERATION54")
        assert is_generic_vendor_slot("CF12")
        assert not is_generic_vendor_slot("credit_limit")
        assert not is_generic_vendor_slot("CFWASTESURCHAMOUNT")

    def test_recommend_disposition(self):
        assert recommend_disposition("CFSTRING33") == "silver-passthrough"
        assert recommend_disposition("created_on") == "skip"
        assert recommend_disposition("tenant_id") == "skip"
        assert recommend_disposition("credit_limit") == ""

    def test_auto_disposition_narrow(self):
        assert auto_disposition("CREATEDON") == "skip"
        assert auto_disposition("tenant_id") == "skip"
        # A generic vendor slot is NOT auto-disposed (stays a conscious decision).
        assert auto_disposition("CFSTRING33") is None
        # A business column is never auto-disposed.
        assert auto_disposition("credit_limit") is None


_SOURCE_VOCABULARY = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix bronze: <https://example.com/bronze/adminpulse#> .

bronze:tblA a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblA" .

bronze:tblA_name a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze:tblA ;
    kairos-bronze:columnName "name" .
"""

_DIRECT_MAPPING = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix bronze: <https://example.com/bronze/adminpulse#> .
@prefix party: <https://example.com/ontology/party#> .

bronze:tblA_name skos:exactMatch party:name .
"""


def _write_completeness_fixture(
    tmp_path: Path,
    *,
    registry_tables: list[str],
    fresh: bool = True,
    include_mapping: bool = True,
    claims: list[Claim] | None = None,
) -> tuple[Path, Path, Path, Path]:
    """Write one tiny committed-input fixture for both completeness views."""

    analysis = tmp_path / "integration" / "sources" / "_analysis"
    sources = tmp_path / "integration" / "sources"
    mappings = tmp_path / "model" / "mappings"
    claims_dir = tmp_path / "model" / "claims"
    _write_affinity(analysis, "adminpulse", [("tblA", "party")])
    source_file = sources / "adminpulse" / "adminpulse.vocabulary.ttl"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text(_SOURCE_VOCABULARY, encoding="utf-8")
    mappings.mkdir(parents=True, exist_ok=True)
    if include_mapping:
        (mappings / "adminpulse-to-party.ttl").write_text(_DIRECT_MAPPING, encoding="utf-8")

    affinity_hash = compute_affinity_hash([("adminpulse", "tblA")])
    registry = ClaimRegistry(
        domain="party",
        algorithm_version=2,
        freshness=Freshness(
            affinity_sha256=affinity_hash if fresh else "stale-affinity-hash"
        ),
        coverage=[
            CoverageSystem(
                system="adminpulse",
                tables=[
                    CoverageTable(
                        table=table,
                        total_columns=3,
                        mapped_columns=2,
                        custom_columns=1,
                        anchor_state="fallback",
                        ref_class="Party",
                    )
                    for table in registry_tables
                ],
            )
        ],
        claims=claims or [],
    )
    write_registry(registry, claims_dir / "party-claims.yaml")
    return analysis, sources, mappings, claims_dir


class TestCanonicalCompletenessFacts:
    def test_computes_assignment_registry_mapping_and_freshness_once(self, tmp_path):
        analysis, sources, mappings, claims_dir = _write_completeness_fixture(
            tmp_path,
            registry_tables=["tblA"],
        )

        facts = compute_completeness_facts(
            analysis_dir=analysis,
            claims_dir=claims_dir,
            sources_dir=sources,
            mappings_dir=mappings,
        )

        assert facts.mapping_evaluated
        assert len(facts.tables) == 1
        fact = facts.tables[0]
        assert (fact.domain, fact.system, fact.table) == ("party", "adminpulse", "tblA")
        assert fact.assignment.total_columns == 3
        assert fact.registry_coverage is not None
        assert fact.registry_coverage.anchor_state == "fallback"
        assert fact.registry_coverage.ref_class == "Party"
        assert fact.mapping.state == "direct"
        assert fact.mapping.direct
        assert fact.mapping.replacement.covered is False
        assert fact.freshness.state == "fresh"

    def test_claim_and_source_views_preserve_complete_incomplete_and_stale_states(self, tmp_path):
        complete = tmp_path / "complete"
        incomplete = tmp_path / "incomplete"
        stale = tmp_path / "stale"
        cases = [
            (complete, ["tblA"], True, "ok"),
            (incomplete, [], True, "incomplete"),
            (stale, ["tblA"], False, "stale"),
        ]

        for root, registry_tables, fresh, expected_state in cases:
            analysis, sources, mappings, claims_dir = _write_completeness_fixture(
                root,
                registry_tables=registry_tables,
                fresh=fresh,
            )
            facts = compute_completeness_facts(
                analysis_dir=analysis,
                claims_dir=claims_dir,
                sources_dir=sources,
                mappings_dir=mappings,
            )

            claim_report = evaluate_claims_coverage(facts)
            source_report = evaluate_source_coverage(facts)

            assert getattr(claim_report, expected_state) == ["party"]
            assert source_report.domain_counts["party"] == (1, 1)
            assert not source_report.is_blocking

    def test_conformance_proposal_is_not_mapping_coverage(self, tmp_path):
        proposal = Claim(
            id="party-core-party",
            type="class",
            status="proposed",
            disposition="claim",
            evidence_sources=[
                EvidenceSource(
                    type="core_concepts_conformance",
                    system="adminpulse",
                    table="tblA",
                )
            ],
        )
        analysis, sources, mappings, claims_dir = _write_completeness_fixture(
            tmp_path,
            registry_tables=["tblA"],
            include_mapping=False,
            claims=[proposal],
        )

        facts = compute_completeness_facts(
            analysis_dir=analysis,
            claims_dir=claims_dir,
            sources_dir=sources,
            mappings_dir=mappings,
        )

        assert facts.tables[0].mapping.state == "unmapped"
        report = evaluate_source_coverage(facts)
        assert report.uncovered == {"party": ["adminpulse.tblA"]}
        assert report.is_blocking
