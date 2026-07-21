# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for F3 (toolkit-optimizations) — object-property targets.

A scalar location column attached to an object property (``hasPlaceOfReceipt``)
must not count as a resolved scalar mapping when no governed target entity
resolves: the registry would look semantically covered without a target node.

This exercises the alignment path end-to-end (mocked LLM):

* an unresolved object property downgrades the scalar column to a passthrough
  custom column and emits an ``object_property_relationship_candidate``; and
* a resolvable object property (target class governed) keeps the mapping so the
  default output stays unchanged.
"""

from __future__ import annotations

import json
from unittest import mock

import yaml

from kairos_ontology.core.propose_alignment import (
    alignment_to_dict,
    build_domain_alignments,
)


def _mock_client(table_responses: dict[str, dict]):
    def create_completion(**kwargs):
        prompt = kwargs["messages"][1]["content"]
        for table_name, response in table_responses.items():
            if table_name in prompt:
                return mock.MagicMock(choices=[mock.MagicMock(
                    message=mock.MagicMock(content=json.dumps(response)))])
        return mock.MagicMock(choices=[mock.MagicMock(
            message=mock.MagicMock(content=json.dumps({})))])

    client = mock.MagicMock()
    client.chat.completions.create = create_completion
    return client


def _write_affinity(analysis_dir):
    analysis_dir.mkdir(parents=True, exist_ok=True)
    affinity = {
        "system": "qargo",
        "schema_version": 2,
        "tables": [
            {"table": "tblShipment", "total_columns": 2, "domain": "logistics",
             "domain_uris": ["https://ex.org/ont/logistics#"],
             "likely_entity": "Shipment", "indicative_columns": ["ShipmentRef"]},
        ],
        "domain_summary": [
            {"domain": "logistics", "table_count": 1, "tables": ["tblShipment"]},
        ],
    }
    with open(analysis_dir / "qargo-affinity.yaml", "w", encoding="utf-8") as f:
        yaml.dump(affinity, f)


def _write_sources(sources_dir):
    admin = sources_dir / "qargo"
    admin.mkdir(parents=True, exist_ok=True)
    vocab = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
<#tblShipment> a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblShipment" .
<#tblShipment_ShipmentRef> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "ShipmentRef" ;
    kairos-bronze:dataType "nvarchar(50)" ;
    kairos-bronze:belongsToTable <#tblShipment> .
<#tblShipment_PlaceOfReceipt> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "PlaceOfReceipt" ;
    kairos-bronze:dataType "nvarchar(120)" ;
    kairos-bronze:belongsToTable <#tblShipment> .
"""
    (admin / "qargo.vocabulary.ttl").write_text(vocab, encoding="utf-8")


_RESPONSE = {
    "tblShipment": {
        "ref_class": "Shipment",
        "ref_class_confidence": 0.9,
        "column_alignments": [
            {"column": "ShipmentRef", "ref_class": "Shipment",
             "ref_property": "shipmentReference", "alignment": "exact",
             "confidence": 0.95, "rationale": "Direct match"},
            {"column": "PlaceOfReceipt", "ref_class": "Shipment",
             "ref_property": "hasPlaceOfReceipt", "alignment": "semantic",
             "confidence": 0.6, "rationale": "Location cluster"},
        ],
    },
}


class TestObjectPropertyTargetScenario:
    def _run(self, tmp_path, inventory):
        analysis = tmp_path / "_analysis"
        sources = tmp_path / "sources"
        _write_affinity(analysis)
        _write_sources(sources)
        client = _mock_client(_RESPONSE)
        with mock.patch(
            "kairos_ontology.core.propose_alignment.get_ai_client",
            return_value=client,
        ), mock.patch(
            "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
            return_value=inventory,
        ):
            alignments = build_domain_alignments(
                analysis_dir=analysis, sources_dir=sources, catalog_path=None,
                domains_filter=["logistics"],
            )
        return alignment_to_dict(alignments[0])

    def test_unresolved_object_property_downgrades_to_candidate(self, tmp_path):
        # Shipment has hasPlaceOfReceipt (range Location) but Location is NOT a
        # governed class in the inventory → target unresolved.
        inventory = [
            {"name": "Shipment", "uri": "https://ex.org/ont/logistics#Shipment",
             "label": "Shipment", "comment": "", "properties": [
                 {"name": "shipmentReference", "label": "Ref", "range": "string"},
                 {"name": "hasPlaceOfReceipt", "label": "Place of receipt",
                  "range": "Location"},
             ]},
        ]
        tbl = self._run(tmp_path, inventory)["tables"][0]
        mapped = [c["column"] for c in tbl["columns"]]
        custom = {c["column"]: c for c in tbl["custom_columns"]}
        # The scalar location column is NOT a resolved mapped column…
        assert "PlaceOfReceipt" not in mapped
        assert "ShipmentRef" in mapped
        # …it is retained as passthrough evidence…
        assert "PlaceOfReceipt" in custom
        assert custom["PlaceOfReceipt"]["object_property_passthrough"] is True
        # …and a relationship candidate carries the target + cardinality.
        cands = [c for c in tbl.get("relationship_candidates", [])
                 if c.get("type") == "object_property_relationship_candidate"]
        assert len(cands) == 1
        assert cands[0]["suggested_relationship"] == "hasPlaceOfReceipt"
        assert cands[0]["target_resolved"] is False
        assert cands[0]["cardinality"] == "n:1"

    def test_resolved_object_property_keeps_mapping(self, tmp_path):
        # Location IS governed → the mapping is kept (byte-identical behaviour).
        inventory = [
            {"name": "Shipment", "uri": "https://ex.org/ont/logistics#Shipment",
             "label": "Shipment", "comment": "", "properties": [
                 {"name": "shipmentReference", "label": "Ref", "range": "string"},
                 {"name": "hasPlaceOfReceipt", "label": "Place of receipt",
                  "range": "Location"},
             ]},
            {"name": "Location", "uri": "https://ex.org/ont/logistics#Location",
             "label": "Location", "comment": "", "properties": []},
        ]
        tbl = self._run(tmp_path, inventory)["tables"][0]
        mapped = [c["column"] for c in tbl["columns"]]
        assert "PlaceOfReceipt" in mapped
        cands = [c for c in tbl.get("relationship_candidates", [])
                 if c.get("type") == "object_property_relationship_candidate"]
        assert cands == []
