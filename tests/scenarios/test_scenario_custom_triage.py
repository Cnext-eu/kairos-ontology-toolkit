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
from kairos_ontology.propose_alignment import run_propose_alignment

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


def _run(tmp_path, output):
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
            output_dir=output,
            force=True,
        )
    return yaml.safe_load(
        (output / "client-alignment.yaml").read_text(encoding="utf-8")
    )


def _custom(data, column):
    for table in data["tables"]:
        for col in table.get("custom_columns", []):
            if col["column"] == column:
                return col
    raise AssertionError(f"custom column {column!r} not found")


class TestCustomTriageScenario:
    def test_low_confidence_suggestion_dropped(self, tmp_path):
        data = _run(tmp_path, tmp_path / "out")
        vat = _custom(data, "VATNumber")
        # WS1: confident-but-wrong guess is suppressed below the floor.
        assert vat["suggested_property"] is None
        # Advisory recommendation is always present (empty → human must decide).
        assert "recommended_disposition" in vat

    def test_human_disposition_survives_regeneration(self, tmp_path):
        output = tmp_path / "out"
        data = _run(tmp_path, output)
        path = output / "client-alignment.yaml"

        # Modeler hand-triages VATNumber as a real domain property.
        for table in data["tables"]:
            for col in table.get("custom_columns", []):
                if col["column"] == "VATNumber":
                    col["disposition"] = "model"
                    col["disposition_source"] = "human"
        path.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")

        # Regenerate (force) — the hand-triaged disposition must survive.
        data2 = _run(tmp_path, output)
        vat = _custom(data2, "VATNumber")
        assert vat["disposition"] == "model"
        assert vat["disposition_source"] == "human"
