# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for DD-070 (issue #166): cross-module candidate properties.

Exercises ``propose-alignment --cross-module`` against the acme-hub
adminpulse → client scenario. ``tblClient`` carries a ``City`` column that, with
only the home Party reference model available, would be force-fit onto a party
scalar. With the widened accelerator pool a shared ``reference-data#Address``
class becomes a real STEP-2 candidate, so ``City`` maps to ``Address.city`` and is
tagged with its owning ``ref_module`` — while the *table* still classifies to the
home ``Party`` class (two-pool design).

Follows the established scenario pattern (mapping-hints) of mocking
``extract_ref_model_inventory`` + the LLM client so the test is deterministic and
self-contained while still driving the real ``run_propose_alignment`` pipeline and
the real adminpulse bronze vocabulary.
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
ADDRESS_URI = "https://kairos.cnext.eu/ref/reference-data#"


def _party_classes():
    return parse_reference_model(REF_PARTY, include_specializations=True)["classes"]


def _address_class():
    return {
        "name": "Address",
        "label": "Address",
        "comment": "A postal address",
        "properties": [
            {"name": "street", "label": "Street", "range": "string"},
            {"name": "city", "label": "City", "range": "string"},
            {"name": "postalCode", "label": "Postal Code", "range": "string"},
        ],
        "source_uri": ADDRESS_URI,
        "module": "reference-data",
        "ref_class_id": "reference-data:Address",
        "belongs_to_domains": ["client", "invoice"],
    }


def _inventory_side_effect(domain_uris, catalog_path, *,
                           inventory_dir=None, module_map=None):
    if module_map is None:
        # Home pool (STEP 1 + rollup): real party classes, untagged.
        return _party_classes()
    # Widened accelerator pool (STEP 2): home party classes tagged + sibling Address.
    widened = []
    for cls in _party_classes():
        tagged = dict(cls)
        tagged["source_uri"] = PARTY_URI
        tagged["module"] = "client"
        tagged["ref_class_id"] = f"client:{cls['name']}"
        tagged["belongs_to_domains"] = ["client"]
        widened.append(tagged)
    widened.append(_address_class())
    return widened


def _llm_response():
    """tblClient → Party (home); City → the sibling Address.city."""
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
            {"column": "City", "ref_class": "Address", "ref_module": "reference-data",
             "ref_property": "city", "alignment": "semantic",
             "confidence": 0.85, "rationale": "City belongs on a shared Address"},
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
    analysis.mkdir()
    affinity = {
        "system": "adminpulse",
        "analysed_at": "2026-06-14T10:00:00Z",
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
                "indicative_columns": ["Name", "Email", "City"],
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


def _run(tmp_path, *, cross_module):
    output = tmp_path / "out"
    kw = {}
    if cross_module:
        kw = {"cross_module": True, "accelerator": "logistics",
              "ref_models_dir": tmp_path}
    with mock.patch(
        "kairos_ontology.propose_alignment.get_ai_client", return_value=_mock_client()
    ), mock.patch(
        "kairos_ontology.propose_alignment.extract_ref_model_inventory",
        side_effect=_inventory_side_effect,
    ), mock.patch(
        "kairos_ontology.analyse_sources.load_accelerator_uri_modules",
        return_value={
            PARTY_URI: {"module": "client", "domains": ["client"]},
            ADDRESS_URI: {"module": "reference-data",
                          "domains": ["client", "invoice"]},
        },
    ):
        run_propose_alignment(
            analysis_dir=_affinity_dir(tmp_path),
            sources_dir=SOURCES_DIR,
            catalog_path=None,
            output_dir=output,
            **kw,
        )
    return yaml.safe_load(
        (output / "client-alignment.yaml").read_text(encoding="utf-8")
    )


class TestCrossModuleScenario:
    def test_city_matches_sibling_address_module(self, tmp_path):
        data = _run(tmp_path, cross_module=True)
        tbl = data["tables"][0]
        # Two-pool: the TABLE still classifies to the home Party class.
        assert tbl["ref_class"] == "Party"
        city = next(c for c in tbl["columns"] if c["column"] == "City")
        assert city["ref_class"] == "Address"
        assert city["ref_module"] == "reference-data"
        assert city["belongs_to_domains"] == ["client", "invoice"]

    def test_cross_module_matches_section(self, tmp_path):
        data = _run(tmp_path, cross_module=True)
        assert data["alignment_params_sha256"]
        matches = data["cross_module_matches"]
        assert len(matches) == 1
        assert matches[0]["ref_class"] == "Address"
        assert matches[0]["ref_module"] == "reference-data"
        assert matches[0]["source_columns"] == ["adminpulse.tblClient.City"]
        # Home rollup is NOT seeded from the accelerator inventory.
        rollup_classes = {r["ref_class"] for r in data["reference_rollup"]}
        assert "Address" not in rollup_classes

    def test_default_run_has_no_cross_module_fields(self, tmp_path):
        data = _run(tmp_path, cross_module=False)
        assert "cross_module_matches" not in data
        assert "alignment_params_sha256" not in data
        for col in data["tables"][0]["columns"]:
            assert "ref_module" not in col
