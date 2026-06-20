# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for issue #182 (DD-077): custom-column triage hardening.

Drives the real ``run_propose_alignment`` pipeline against the acme-hub
adminpulse → client scenario (``tblClient``) with a mocked LLM + reference-model
inventory, and asserts the deterministic / confidence-gated guarantees end to end:

* **WS1** — an unmatched custom column whose suggestion is below the confidence
  floor is emitted with ``suggested_property: null`` (no confident-but-wrong guess),
  while the advisory ``recommended_disposition`` is always present.
* **WS9** — a modeler's hand-triaged ``disposition`` (``disposition_source: human``)
  survives a regeneration of the alignment file; a heuristic-owned disposition is
  recomputed.

Follows the established scenario pattern (cross-module / mapping-hints) of mocking
``extract_ref_model_inventory`` + the LLM client so the test is deterministic and
self-contained while still exercising the real adminpulse bronze vocabulary.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import yaml

from kairos_ontology.analyse_sources import parse_reference_model
from kairos_ontology.claim_registry import load_registry, write_registry
from kairos_ontology.propose_alignment import (
    alignment_to_dict,
    build_domain_alignments,
    run_propose_alignment,
)

ACME_HUB = Path(__file__).parent / "acme-hub"
SOURCES_DIR = ACME_HUB / "integration" / "sources"
REF_PARTY = ACME_HUB / "model" / "reference-models" / "kairos-ref-party.ttl"
PARTY_URI = "https://kairos.cnext.eu/ref/party#"


def _party_classes():
    return parse_reference_model(REF_PARTY, include_specializations=True)["classes"]


def _inventory_side_effect(domain_uris, catalog_path, *,
                           inventory_dir=None, module_map=None):
    return _party_classes()


def _llm_response():
    """tblClient → Party. ``Name`` matches; ``VATNumber`` is an unmatched custom
    column the model is *not* confident about (low confidence → suggestion must be
    dropped to null)."""
    return {
        "ref_class": "Party",
        "ref_class_confidence": 0.9,
        "column_alignments": [
            {"column": "Name", "ref_class": "Party",
             "ref_property": "partyName", "alignment": "exact",
             "confidence": 0.95, "rationale": "Name"},
            {"column": "VATNumber", "ref_class": "Party",
             "ref_property": "partyIdentifier", "alignment": "custom",
             "confidence": 0.2, "rationale": "Unsure — low confidence guess"},
        ],
    }


def _mock_client():
    def create_completion(**kwargs):
        return mock.MagicMock(choices=[mock.MagicMock(
            message=mock.MagicMock(content=json.dumps(_llm_response()))
        )])
    client = mock.MagicMock()
    client.chat.completions.create = create_completion
    return client


def _affinity_dir(tmp_path):
    analysis = tmp_path / "_analysis"
    analysis.mkdir(exist_ok=True)
    affinity = {
        "system": "adminpulse",
        "analysed_at": "2026-06-15T10:00:00Z",
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
                "indicative_columns": ["Name", "VATNumber"],
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


def _run(tmp_path):
    """Build the in-memory client alignment dict (no files written)."""
    with mock.patch(
        "kairos_ontology.propose_alignment.get_ai_client", return_value=_mock_client()
    ), mock.patch(
        "kairos_ontology.propose_alignment.extract_ref_model_inventory",
        side_effect=_inventory_side_effect,
    ):
        alignments = build_domain_alignments(
            analysis_dir=_affinity_dir(tmp_path),
            sources_dir=SOURCES_DIR,
            catalog_path=None,
            force=True,
        )
    client = next(a for a in alignments if a.domain == "client")
    return alignment_to_dict(client)


def _run_to_disk(tmp_path, claims_dir, *, force=True):
    """Run the producer end-to-end, writing the Claim Registry to *claims_dir*."""
    with mock.patch(
        "kairos_ontology.propose_alignment.get_ai_client", return_value=_mock_client()
    ), mock.patch(
        "kairos_ontology.propose_alignment.extract_ref_model_inventory",
        side_effect=_inventory_side_effect,
    ):
        run_propose_alignment(
            analysis_dir=_affinity_dir(tmp_path),
            sources_dir=SOURCES_DIR,
            catalog_path=None,
            output_dir=claims_dir,
            force=force,
        )
    return claims_dir / "client-claims.yaml"


def _custom(data, column):
    for table in data["tables"]:
        for col in table.get("custom_columns", []):
            if col["column"] == column:
                return col
    raise AssertionError(f"custom column {column!r} not found")


class TestCustomTriageScenario:
    def test_low_confidence_suggestion_dropped(self, tmp_path):
        data = _run(tmp_path)
        vat = _custom(data, "VATNumber")
        # WS1: confident-but-wrong guess is suppressed below the floor.
        assert vat["suggested_property"] is None
        # Advisory recommendation is always present (empty → human must decide).
        assert "recommended_disposition" in vat

    def test_human_decision_survives_regeneration(self, tmp_path):
        # DD-EL-1: a human decision recorded on a claim must survive a producer
        # re-run via merge_preserving_decisions (the claim-level analog of the
        # retired alignment-YAML disposition preservation).
        claims_dir = tmp_path / "claims"
        reg_path = _run_to_disk(tmp_path, claims_dir)

        registry = load_registry(reg_path)
        vat_claim = next(
            c for c in registry.claims if "vatnumber" in c.id.lower()
        )
        vat_claim.status = "approved"
        vat_claim.disposition = "specialize"
        write_registry(registry, reg_path)

        # Regenerate (force) — the hand-made decision must survive.
        _run_to_disk(tmp_path, claims_dir)
        registry2 = load_registry(reg_path)
        vat2 = next(c for c in registry2.claims if "vatnumber" in c.id.lower())
        assert vat2.status == "approved"
        assert vat2.disposition == "specialize"
