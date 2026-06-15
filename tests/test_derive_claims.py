# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for deterministic multi-source claim derivation (DD-EL-5)."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    EvidenceSource,
    load_registry,
    write_registry,
)
from kairos_ontology.cli.main import cli
from kairos_ontology.derive_claims import (
    class_claim_id,
    derive_claims_for_domain,
    detect_sample_signal,
    load_skos_links,
    property_claim_id,
    run_derive_claims,
)


def _base_registry() -> ClaimRegistry:
    """A small 'client' registry as propose-alignment would have written it."""
    cls = Claim(
        id=class_claim_id("client", "TradeParty"),
        type="class",
        status="proposed",
        disposition="claim",
        origin="imported",
        evidence_sources=[
            EvidenceSource(type="source_table", system="crm", table="account"),
        ],
    )
    name_prop = Claim(
        id=property_claim_id("client", "TradeParty", "legalName"),
        type="property",
        status="proposed",
        disposition="claim",
        origin="imported",
        evidence_sources=[
            EvidenceSource(type="source_column", system="crm", table="account", column="name"),
        ],
    )
    code_prop = Claim(
        id=property_claim_id("client", "TradeParty", "typeCode"),
        type="property",
        status="proposed",
        disposition="claim",
        origin="imported",
        evidence_sources=[
            EvidenceSource(
                type="source_column", system="crm", table="account", column="type_code"
            ),
        ],
    )
    return ClaimRegistry(
        domain="client",
        coverage=[
            CoverageSystem(
                system="crm",
                tables=[
                    CoverageTable(
                        table="account", total_columns=2, mapped_columns=2,
                        anchor_state="matched", ref_class="TradeParty",
                    )
                ],
            )
        ],
        claims=[cls, name_prop, code_prop],
    )


def _ev_types(claim: Claim) -> set[str]:
    return {e.type for e in claim.evidence_sources}


def _by_id(registry: ClaimRegistry, cid: str) -> Claim:
    return next(c for c in registry.claims if c.id == cid)


class TestMultiSourceAggregation:
    def test_one_claim_gains_multiple_evidence_sources(self):
        derived, stats = derive_claims_for_domain(
            "client",
            _base_registry(),
            affinity_tables=[
                {"system": "crm", "table": "account", "likely_entity": "Account",
                 "confidence": 0.9},
            ],
            tmdl_tables=[
                {"tmdl_name": "DimAccount", "reference_model_match": "TradeParty",
                 "action": "use", "_model": "SalesPBI"},
            ],
            skos_links=[
                {"system": "crm", "table": "account", "column": "", "target": "TradeParty",
                 "kind": "class", "predicate": "exactMatch"},
                {"system": "crm", "table": "account", "column": "name",
                 "target": "legalName", "kind": "property", "predicate": "exactMatch"},
            ],
            column_samples={("crm", "account", "name"): ["Acme", "Beta", "Acme", "Gamma"]},
        )

        cls = _by_id(derived, class_claim_id("client", "TradeParty"))
        # Source + affinity + tmdl + skos all land on the SAME claim.
        assert _ev_types(cls) == {
            "source_table", "affinity", "tmdl_concept_mapping", "skos_mapping",
        }

        name_prop = _by_id(derived, property_claim_id("client", "TradeParty", "legalName"))
        assert "skos_mapping" in _ev_types(name_prop)
        assert "sample_signal" in _ev_types(name_prop)  # 3 distinct → enum candidate

        code_prop = _by_id(derived, property_claim_id("client", "TradeParty", "typeCode"))
        # name-based fk-shape signal (column 'type_code')
        assert "sample_signal" in _ev_types(code_prop)

        assert stats.evidence_added >= 5
        assert stats.base_claims == 3

    def test_evidence_is_deduplicated(self):
        reg = _base_registry()
        # Run twice over the already-enriched registry — no duplicate evidence.
        derived1, _ = derive_claims_for_domain(
            "client", reg,
            affinity_tables=[{"system": "crm", "table": "account"}],
        )
        derived2, stats2 = derive_claims_for_domain(
            "client", derived1,
            affinity_tables=[{"system": "crm", "table": "account"}],
        )
        cls = _by_id(derived2, class_claim_id("client", "TradeParty"))
        affinity = [e for e in cls.evidence_sources if e.type == "affinity"]
        assert len(affinity) == 1
        assert stats2.evidence_added == 0


class TestProposedOnly:
    def test_affinity_only_table_creates_proposed_candidate(self):
        derived, stats = derive_claims_for_domain(
            "client",
            _base_registry(),
            affinity_tables=[
                {"system": "erp", "table": "orphan", "likely_entity": "Orphan",
                 "confidence": 0.7},
            ],
        )
        new = _by_id(derived, "client-affinity-erp-orphan")
        assert new.status == "proposed"
        assert new.type == "class"
        assert _ev_types(new) == {"source_table", "affinity"}
        assert stats.new_claims == 1

    def test_tmdl_new_class_creates_proposed_gap(self):
        derived, _ = derive_claims_for_domain(
            "client",
            _base_registry(),
            tmdl_tables=[
                {"tmdl_name": "DimWidget", "reference_model_match": "Widget",
                 "action": "new_class", "_model": "SalesPBI"},
            ],
        )
        gap = _by_id(derived, "client-tmdl-widget")
        assert gap.status == "proposed"
        assert gap.disposition == "gap"

    def test_all_new_claims_are_proposed(self):
        derived, _ = derive_claims_for_domain(
            "client",
            _base_registry(),
            affinity_tables=[{"system": "erp", "table": "orphan"}],
            tmdl_tables=[
                {"reference_model_match": "Widget", "action": "new_class",
                 "tmdl_name": "DimWidget"},
            ],
        )
        new_ids = {"client-affinity-erp-orphan", "client-tmdl-widget"}
        for claim in derived.claims:
            if claim.id in new_ids:
                assert claim.status == "proposed"


class TestSampleSignal:
    def test_enum_candidate(self):
        assert "enum-candidate" in detect_sample_signal("status", None, ["A", "B", "A", "B"])

    def test_fk_shape_by_name(self):
        assert "fk-shape" in (detect_sample_signal("client_id", None, None) or "")
        assert "fk-shape" in (detect_sample_signal("typeCode", None, None) or "")

    def test_no_signal(self):
        # High-cardinality, non-fk-named → no deterministic signal.
        samples = [str(i) for i in range(50)]
        assert detect_sample_signal("free_text", "str", samples) is None

    def test_enum_precedence_over_fk(self):
        # An fk-named column with few distinct values reports the enum signal.
        assert "enum-candidate" in detect_sample_signal("type_code", None, ["1", "2", "1"])


class TestRunDeriveClaims:
    def _write_hub(self, tmp_path: Path) -> tuple[Path, Path]:
        claims_dir = tmp_path / "model" / "claims"
        analysis_dir = tmp_path / "integration" / "sources" / "_analysis"
        claims_dir.mkdir(parents=True)
        analysis_dir.mkdir(parents=True)
        write_registry(_base_registry(), claims_dir / "client-claims.yaml")
        (analysis_dir / "crm-affinity.yaml").write_text(
            yaml.safe_dump({
                "schema_version": 2,
                "system": "crm",
                "tables": [
                    {"table": "account", "domain": "client", "likely_entity": "Account",
                     "confidence": 0.9},
                ],
            }),
            encoding="utf-8",
        )
        return claims_dir, analysis_dir

    def test_run_enriches_and_writes(self, tmp_path):
        claims_dir, analysis_dir = self._write_hub(tmp_path)
        report = run_derive_claims(claims_dir, analysis_dir=analysis_dir)
        assert len(report.domain_stats) == 1
        assert report.total_evidence_added >= 1
        reg = load_registry(claims_dir / "client-claims.yaml")
        cls = _by_id(reg, class_claim_id("client", "TradeParty"))
        assert "affinity" in _ev_types(cls)

    def test_concurrency_parity(self, tmp_path):
        claims_dir, analysis_dir = self._write_hub(tmp_path)
        run_derive_claims(claims_dir, analysis_dir=analysis_dir, max_workers=8)
        serial = (claims_dir / "client-claims.yaml").read_text(encoding="utf-8")

        claims_dir2, analysis_dir2 = self._write_hub(tmp_path / "second")
        run_derive_claims(claims_dir2, analysis_dir=analysis_dir2, max_workers=1)
        parallel = (claims_dir2 / "client-claims.yaml").read_text(encoding="utf-8")
        assert serial == parallel

    def test_idempotent_rerun(self, tmp_path):
        claims_dir, analysis_dir = self._write_hub(tmp_path)
        run_derive_claims(claims_dir, analysis_dir=analysis_dir)
        first = (claims_dir / "client-claims.yaml").read_text(encoding="utf-8")
        run_derive_claims(claims_dir, analysis_dir=analysis_dir)
        second = (claims_dir / "client-claims.yaml").read_text(encoding="utf-8")
        assert first == second

    def test_human_decision_preserved(self, tmp_path):
        claims_dir = tmp_path / "model" / "claims"
        claims_dir.mkdir(parents=True)
        reg = _base_registry()
        approved = _by_id(reg, class_claim_id("client", "TradeParty"))
        approved.status = "approved"
        approved.class_uri = "https://ex.org/ont/client#TradeParty"
        approved.owner = "client-team"
        write_registry(reg, claims_dir / "client-claims.yaml")

        analysis_dir = tmp_path / "_analysis"
        analysis_dir.mkdir()
        (analysis_dir / "crm-affinity.yaml").write_text(
            yaml.safe_dump({
                "schema_version": 2, "system": "crm",
                "tables": [{"table": "account", "domain": "client"}],
            }),
            encoding="utf-8",
        )

        run_derive_claims(claims_dir, analysis_dir=analysis_dir)
        out = load_registry(claims_dir / "client-claims.yaml")
        cls = _by_id(out, class_claim_id("client", "TradeParty"))
        # Curated fields survive; evidence is still enriched.
        assert cls.status == "approved"
        assert cls.class_uri == "https://ex.org/ont/client#TradeParty"
        assert cls.owner == "client-team"
        assert "affinity" in _ev_types(cls)


class TestCli:
    def test_derive_claims_cli_round_trip(self, tmp_path):
        claims_dir = tmp_path / "model" / "claims"
        analysis_dir = tmp_path / "integration" / "sources" / "_analysis"
        claims_dir.mkdir(parents=True)
        analysis_dir.mkdir(parents=True)
        write_registry(_base_registry(), claims_dir / "client-claims.yaml")
        (analysis_dir / "crm-affinity.yaml").write_text(
            yaml.safe_dump({
                "schema_version": 2, "system": "crm",
                "tables": [{"table": "account", "domain": "client"}],
            }),
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["derive-claims", "--claims-dir", str(claims_dir),
             "--analysis-dir", str(analysis_dir)],
            env={"KAIROS_SKILL_CONTEXT": "1"},
        )
        assert result.exit_code == 0, result.output
        assert "Derived claims for 1 domain" in result.output
        reg = load_registry(claims_dir / "client-claims.yaml")
        cls = _by_id(reg, class_claim_id("client", "TradeParty"))
        assert "affinity" in _ev_types(cls)


class TestSkosLoader:
    def test_decode_and_kind(self, tmp_path):
        mappings = tmp_path / "mappings"
        mappings.mkdir()
        (mappings / "ap-to-client.ttl").write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "@prefix bronze-ap: <https://acme.example/bronze/adminpulse#> .\n"
            "@prefix acme: <https://acme.example/ontology/client#> .\n"
            "bronze-ap:tblClient skos:exactMatch acme:TradeParty .\n"
            "bronze-ap:tblClient_Name skos:exactMatch acme:legalName .\n",
            encoding="utf-8",
        )
        links = load_skos_links(mappings)
        by_target = {link["target"]: link for link in links}
        assert by_target["TradeParty"]["kind"] == "class"
        assert by_target["TradeParty"]["system"] == "adminpulse"
        assert by_target["TradeParty"]["table"] == "tblClient"
        assert by_target["legalName"]["kind"] == "property"
        assert by_target["legalName"]["column"] == "Name"
