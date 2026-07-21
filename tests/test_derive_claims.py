# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for deterministic multi-source claim derivation (DD-095)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.core.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    EvidenceSource,
    dump_registry,
    load_registry,
    write_registry,
)
from kairos_ontology.cli.main import cli
from kairos_ontology.core.conformance_artifact import (
    ARTIFACT_RELPATH,
    ConformanceArtifactError,
    compute_scorecard,
)
from kairos_ontology.core.derive_claims import (
    CONFORMANCE_EVIDENCE_TYPE,
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


def _conformance_artifact() -> dict:
    concepts = [
        {
            "uri": "https://example.org/ref/core#Conforming",
            "label": "Conforming",
            "tier": "required",
            "outcome": "conforms",
        },
        {
            "uri": "https://example.org/ref/core#RenamedStandard",
            "label": "Renamed Standard",
            "tier": "required",
            "outcome": "conforms-with-rename",
            "rename_to": "Business Name",
        },
        {
            "uri": "https://example.org/ref/core#PartialConcept",
            "label": "Partial Concept",
            "tier": "recommended",
            "outcome": "partial",
        },
        {
            "uri": "https://example.org/ref/core#DeviatingConcept",
            "label": "Deviating Concept",
            "tier": "recommended",
            "outcome": "deviates",
            "deviation_reason": "The business uses a different lifecycle.",
        },
        {
            "uri": "https://example.org/ref/core#OptionalConcept",
            "label": "Optional Concept",
            "tier": "optional",
            "outcome": "conforms",
        },
        {
            "uri": "https://example.org/ref/core#ExcludedConcept",
            "label": "Excluded Concept",
            "tier": "optional",
            "outcome": "not-applicable",
        },
    ]
    return {
        "schema_version": 1,
        "archetype": {"id": "test-archetype"},
        "core_concepts": concepts,
        "scorecard": compute_scorecard(concepts),
    }


def _write_conformance(hub_root: Path, artifact: dict | None = None) -> Path:
    path = hub_root / ARTIFACT_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(artifact or _conformance_artifact(), sort_keys=False),
        encoding="utf-8",
    )
    return path


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


class TestConformanceEvidence:
    def test_all_outcomes_map_to_proposed_claim_policy(self):
        derived, stats = derive_claims_for_domain(
            "client",
            _base_registry(),
            conformance_artifact=_conformance_artifact(),
        )

        expected = {
            "Conforming": "claim",
            "RenamedStandard": "claim",
            "PartialConcept": "specialize",
            "DeviatingConcept": "gap",
            "OptionalConcept": "claim",
        }
        for local_name, disposition in expected.items():
            claim = _by_id(derived, class_claim_id("client", local_name))
            assert claim.status == "proposed"
            assert claim.type == "class"
            assert claim.disposition == disposition
            assert claim.class_uri == f"https://example.org/ref/core#{local_name}"
            assert CONFORMANCE_EVIDENCE_TYPE in _ev_types(claim)
            assert "Human approval is required" in (claim.rationale or "")

        renamed = _by_id(
            derived,
            class_claim_id("client", "RenamedStandard"),
        )
        assert "Business Name" in (renamed.rationale or "")
        assert "rename_to" in renamed.evidence_sources[0].note
        assert all(c.id != class_claim_id("client", "Business Name") for c in derived.claims)

        gap = _by_id(derived, class_claim_id("client", "DeviatingConcept"))
        assert gap.deviation is not None
        assert gap.deviation.reason == "The business uses a different lifecycle."
        assert "deviation_reason" in gap.evidence_sources[0].note

        assert all(
            c.id != class_claim_id("client", "ExcludedConcept")
            for c in derived.claims
        )
        assert stats.conformance_concepts == 6
        assert stats.conformance_proposals == 5
        assert stats.conformance_not_applicable == 1
        assert stats.new_claims == 5

    def test_conformance_rerun_is_byte_stable_and_deduplicated(self):
        artifact = _conformance_artifact()
        first, _ = derive_claims_for_domain(
            "client",
            _base_registry(),
            conformance_artifact=artifact,
        )
        second, stats = derive_claims_for_domain(
            "client",
            first,
            conformance_artifact=artifact,
        )

        assert dump_registry(first) == dump_registry(second)
        assert stats.evidence_added == 0
        for claim in second.claims:
            keys = [
                (
                    ev.type,
                    ev.system or "",
                    ev.table or "",
                    ev.column or "",
                    ev.model or "",
                    ev.measure or "",
                    ev.note or "",
                )
                for ev in claim.evidence_sources
            ]
            assert keys == sorted(keys)

    def test_not_applicable_removes_prior_generated_proposal(self):
        artifact = _conformance_artifact()
        first, _ = derive_claims_for_domain(
            "client",
            _base_registry(),
            conformance_artifact=artifact,
        )
        artifact["core_concepts"][0]["outcome"] = "not-applicable"
        artifact["scorecard"] = compute_scorecard(artifact["core_concepts"])

        second, stats = derive_claims_for_domain(
            "client",
            first,
            conformance_artifact=artifact,
        )

        assert all(
            claim.id != class_claim_id("client", "Conforming")
            for claim in second.claims
        )
        assert stats.conformance_not_applicable == 2

    def test_contradictory_concepts_fail_explicitly(self):
        artifact = _conformance_artifact()
        duplicate = dict(artifact["core_concepts"][0])
        duplicate["outcome"] = "partial"
        artifact["core_concepts"].append(duplicate)
        artifact["scorecard"] = compute_scorecard(artifact["core_concepts"])

        with pytest.raises(ConformanceArtifactError, match="duplicate concept URI"):
            derive_claims_for_domain(
                "client",
                _base_registry(),
                conformance_artifact=artifact,
            )


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

    def test_default_conformance_artifact_is_cached_and_stable(self, tmp_path):
        claims_dir, analysis_dir = self._write_hub(tmp_path)
        _write_conformance(tmp_path)

        first_report = run_derive_claims(claims_dir, analysis_dir=analysis_dir)
        first = (claims_dir / "client-claims.yaml").read_text(encoding="utf-8")
        second_report = run_derive_claims(claims_dir, analysis_dir=analysis_dir)
        second = (claims_dir / "client-claims.yaml").read_text(encoding="utf-8")

        assert first == second
        assert first_report.total_conformance_proposals == 5
        assert second_report.total_conformance_proposals == 5
        assert second_report.written == []

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

    def test_conformance_preserves_prior_human_decision(self, tmp_path):
        claims_dir = tmp_path / "model" / "claims"
        claims_dir.mkdir(parents=True)
        curated_uri = "https://example.org/client#ReviewedConforming"
        prior = Claim(
            id=class_claim_id("client", "Conforming"),
            type="class",
            status="approved",
            disposition="skip",
            origin="imported",
            class_uri=curated_uri,
            owner="domain-steward",
            rationale="Human-reviewed exclusion.",
            evidence_sources=[EvidenceSource(type="review", note="approved by steward")],
        )
        registry = _base_registry()
        registry.claims.append(prior)
        write_registry(registry, claims_dir / "client-claims.yaml")
        _write_conformance(tmp_path)

        run_derive_claims(claims_dir)

        out = load_registry(claims_dir / "client-claims.yaml")
        claim = _by_id(out, class_claim_id("client", "Conforming"))
        assert claim.status == "approved"
        assert claim.disposition == "skip"
        assert claim.owner == "domain-steward"
        assert claim.rationale == "Human-reviewed exclusion."
        assert claim.class_uri == curated_uri
        assert CONFORMANCE_EVIDENCE_TYPE in _ev_types(claim)

    def test_unknown_conformance_outcome_is_validation_error(self, tmp_path):
        claims_dir, analysis_dir = self._write_hub(tmp_path)
        artifact = _conformance_artifact()
        artifact["core_concepts"][0]["outcome"] = "mystery"
        artifact["scorecard"] = compute_scorecard(artifact["core_concepts"])
        _write_conformance(tmp_path, artifact)

        with pytest.raises(ConformanceArtifactError, match="invalid outcome 'mystery'"):
            run_derive_claims(claims_dir, analysis_dir=analysis_dir)

    def test_malformed_conformance_yaml_is_parse_error(self, tmp_path):
        claims_dir, analysis_dir = self._write_hub(tmp_path)
        path = tmp_path / ARTIFACT_RELPATH
        path.parent.mkdir(parents=True)
        path.write_text("core_concepts: [\n", encoding="utf-8")

        with pytest.raises(ConformanceArtifactError, match="Could not parse"):
            run_derive_claims(claims_dir, analysis_dir=analysis_dir)

    def test_absent_conformance_artifact_is_compatible(self, tmp_path):
        claims_dir, analysis_dir = self._write_hub(tmp_path)

        report = run_derive_claims(claims_dir, analysis_dir=analysis_dir)

        assert report.total_conformance_proposals == 0
        assert all(
            CONFORMANCE_EVIDENCE_TYPE not in _ev_types(claim)
            for claim in load_registry(claims_dir / "client-claims.yaml").claims
        )


class TestCli:
    def test_derive_claims_cli_round_trip(self, tmp_path):
        claims_dir = tmp_path / "model" / "claims"
        analysis_dir = tmp_path / "integration" / "sources" / "_analysis"
        claims_dir.mkdir(parents=True)
        analysis_dir.mkdir(parents=True)
        write_registry(_base_registry(), claims_dir / "client-claims.yaml")
        _write_conformance(tmp_path)
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
        assert "5/6 conformance proposal(s)" in result.output
        reg = load_registry(claims_dir / "client-claims.yaml")
        cls = _by_id(reg, class_claim_id("client", "TradeParty"))
        assert "affinity" in _ev_types(cls)
        conformance_claim = _by_id(reg, class_claim_id("client", "OptionalConcept"))
        assert conformance_claim.status == "proposed"


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
