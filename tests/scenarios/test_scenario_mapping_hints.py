# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for DD-045: Mapping Hints.

Validates the opt-in ``--include-mapping-hints`` enrichment of ``propose-alignment``
against the acme-hub adminpulse → client scenario:

  - Default (flag off) output is unchanged — NO hint keys (design-domain contract).
  - Flag on adds deterministic transform hints (passthrough vs CAST) and structural
    hints (split_candidate on tblClient.Type with Party subclasses available).

Uses the real adminpulse vocabulary and the real kairos-ref-party.ttl reference
model (Party + Organisation/Person subclasses).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import yaml

from kairos_ontology.analyse_sources import parse_reference_model
from kairos_ontology.propose_alignment import run_propose_alignment

ACME_HUB = Path(__file__).parent / "acme-hub"
SOURCES_DIR = ACME_HUB / "integration" / "sources"
REF_PARTY = ACME_HUB / "model" / "reference-models" / "kairos-ref-party.ttl"
PARTY_URI = "https://kairos.cnext.eu/ref/party#"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _real_party_classes():
    """Parse the real party reference model into the inventory shape."""
    return parse_reference_model(REF_PARTY, include_specializations=True)["classes"]


def _tblclient_llm_response():
    """Deterministic LLM alignment for adminpulse.tblClient → Party."""
    return {
        "ref_class": "Party",
        "ref_class_confidence": 0.9,
        "column_alignments": [
            {"column": "ClientID", "ref_class": "Party",
             "ref_property": "partyIdentifier", "alignment": "semantic",
             "confidence": 0.8, "rationale": "Business id"},
            {"column": "Name", "ref_class": "Party",
             "ref_property": "partyName", "alignment": "exact",
             "confidence": 0.95, "rationale": "Name"},
            {"column": "Email", "ref_class": "Party",
             "ref_property": "email", "alignment": "exact",
             "confidence": 0.95, "rationale": "Email"},
            {"column": "Country", "ref_class": "Party",
             "ref_property": "country", "alignment": "exact",
             "confidence": 0.95, "rationale": "Country"},
            {"column": "VATNumber", "ref_class": "Party",
             "ref_property": "taxIdentifier", "alignment": "semantic",
             "confidence": 0.85, "rationale": "VAT"},
            {"column": "IsActive", "ref_property": "isActive",
             "alignment": "custom", "confidence": 0.0,
             "rationale": "No party property"},
        ],
    }


def _mock_client():
    def create_completion(**kwargs):
        return mock.MagicMock(choices=[mock.MagicMock(
            message=mock.MagicMock(content=json.dumps(_tblclient_llm_response()))
        )])
    client = mock.MagicMock()
    client.chat.completions.create = create_completion
    return client


def _affinity_dir(tmp_path):
    analysis = tmp_path / "_analysis"
    analysis.mkdir()
    affinity = {
        "system": "adminpulse",
        "analysed_at": "2026-06-13T10:00:00Z",
        "model_used": "gpt-5.4-mini",
        "schema_version": 2,
        "tables": [
            {
                "table": "tblClient",
                "total_columns": 11,
                "domain": "client",
                "domain_uris": [PARTY_URI],
                "confidence": 0.9,
                "likely_entity": "Party",
                "indicative_columns": ["Name", "Email"],
            },
        ],
        "domain_summary": [
            {"domain": "client", "table_count": 1, "tables": ["tblClient"]},
        ],
    }
    (analysis / "adminpulse-affinity.yaml").write_text(
        yaml.dump(affinity), encoding="utf-8"
    )
    return analysis


def _run(tmp_path, include_mapping_hints):
    output = tmp_path / "out"
    with mock.patch(
        "kairos_ontology.propose_alignment.get_ai_client", return_value=_mock_client()
    ), mock.patch(
        "kairos_ontology.propose_alignment.extract_ref_model_inventory",
        return_value=_real_party_classes(),
    ):
        run_propose_alignment(
            analysis_dir=_affinity_dir(tmp_path),
            sources_dir=SOURCES_DIR,
            catalog_path=None,
            output_dir=output,
            include_mapping_hints=include_mapping_hints,
        )
    data = yaml.safe_load((output / "client-alignment.yaml").read_text(encoding="utf-8"))
    return data["tables"][0]


# ---------------------------------------------------------------------------
# Regression guard — default output unchanged
# ---------------------------------------------------------------------------


class TestDefaultOutputUnchanged:
    def test_no_hint_keys_when_flag_off(self, tmp_path):
        table = _run(tmp_path, include_mapping_hints=False)
        assert "structural_hints" not in table
        for col in table["columns"]:
            for key in (
                "transform_hint", "transform_confidence",
                "requires_human_confirmation", "transform_rationale",
            ):
                assert key not in col, f"{col['column']} leaked hint key {key}"


# ---------------------------------------------------------------------------
# Flag on — transform hints
# ---------------------------------------------------------------------------


class TestTransformHints:
    def test_passthrough_for_name_and_type_match(self, tmp_path):
        table = _run(tmp_path, include_mapping_hints=True)
        country = next(c for c in table["columns"] if c["column"] == "Country")
        assert country["transform_hint"] == "source.Country"
        assert country["requires_human_confirmation"] is False

    def test_cast_for_type_mismatch(self, tmp_path):
        table = _run(tmp_path, include_mapping_hints=True)
        client_id = next(c for c in table["columns"] if c["column"] == "ClientID")
        # int source vs xsd:string target → cast candidate, must be confirmed
        assert client_id["transform_hint"] == "CAST(source.ClientID AS VARCHAR)"
        assert client_id["requires_human_confirmation"] is True

    def test_every_column_has_a_hint(self, tmp_path):
        table = _run(tmp_path, include_mapping_hints=True)
        for col in table["columns"]:
            assert col["transform_hint"], f"{col['column']} missing transform_hint"


# ---------------------------------------------------------------------------
# Flag on — structural hints
# ---------------------------------------------------------------------------


class TestStructuralHints:
    def test_split_candidate_on_type_discriminator(self, tmp_path):
        table = _run(tmp_path, include_mapping_hints=True)
        splits = [h for h in table["structural_hints"] if h["type"] == "split_candidate"]
        assert len(splits) == 1
        split = splits[0]
        assert split["discriminator_column"] == "Type"
        assert split["requires_human_confirmation"] is True
        # Party subclasses are surfaced as target candidates
        assert "Organisation" in split["target_class_candidates"]
        assert "Person" in split["target_class_candidates"]

    def test_dedup_candidate_on_id_plus_date(self, tmp_path):
        table = _run(tmp_path, include_mapping_hints=True)
        dedup = [h for h in table["structural_hints"] if h["type"] == "dedup_candidate"]
        assert len(dedup) == 1
        assert dedup[0]["natural_key_column"] == "ClientID"
        assert any(
            c in dedup[0]["ordering_column_candidates"]
            for c in ("ModifiedDate", "CreatedDate")
        )
