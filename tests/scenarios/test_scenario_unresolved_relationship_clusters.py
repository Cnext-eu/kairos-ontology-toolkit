# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for proposal-quality — unresolved anchors emit neither
claims nor relationship clusters (uri-anchor-contract / URI-first resolution).

A table whose class anchor is left ``"unresolved"`` (ambiguous confirmed
evidence — see ``anchor_resolution.py``) never runs the LLM, so it already
produces zero property claims. Address-part-shaped columns on that same table
must ALSO never fire the deterministic address-relationship-candidate
detector: a relationship cluster naming an unresolved class would be
meaningless (and could silently smuggle a name-based guess back in through the
relationship-candidate side channel instead of the claim side channel).
"""

from __future__ import annotations

from unittest import mock

import yaml

from kairos_ontology.core.propose_alignment import (
    alignment_to_dict,
    build_domain_alignments,
)

REF_CLASSES = [
    {
        "name": "SalesContract",
        "label": "Sales Contract",
        "comment": "",
        "uri": "https://example.com/ont/commercial#SalesContract",
        "properties": [
            {"name": "contractIdentifier", "label": "Contract ID", "range": "string"},
        ],
    },
    {
        "name": "TradeTerms",
        "label": "Trade Terms",
        "comment": "",
        "uri": "https://example.com/ont/commercial#TradeTerms",
        "properties": [
            {"name": "incoterm", "label": "Incoterm", "range": "string"},
        ],
    },
]


def _write_affinity(analysis_dir):
    analysis_dir.mkdir(parents=True, exist_ok=True)
    affinity = {
        "system": "adminpulse",
        "schema_version": 2,
        "tables": [
            {
                "table": "tblContracts",
                "total_columns": 3,
                "domain": "commercial",
                "domain_uris": ["https://example.com/ont/commercial#"],
                "likely_entity": "SalesContract",
                "indicative_columns": ["billing_street"],
            },
        ],
        "domain_summary": [
            {"domain": "commercial", "table_count": 1, "tables": ["tblContracts"]},
        ],
    }
    with open(analysis_dir / "adminpulse-affinity.yaml", "w", encoding="utf-8") as f:
        yaml.dump(affinity, f)


def _write_sources(sources_dir):
    admin = sources_dir / "adminpulse"
    admin.mkdir(parents=True, exist_ok=True)
    # Two complementary address parts — would normally cluster into a single
    # 'hasBillingAddress' relationship candidate (issue #192 Phase A1).
    vocab = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
<#tblContracts> a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "tblContracts" .
<#tblContracts_billing_street> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "billing_street" ;
    kairos-bronze:dataType "nvarchar(120)" ;
    kairos-bronze:belongsToTable <#tblContracts> .
<#tblContracts_billing_city> a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "billing_city" ;
    kairos-bronze:dataType "nvarchar(80)" ;
    kairos-bronze:belongsToTable <#tblContracts> .
"""
    (admin / "adminpulse.vocabulary.ttl").write_text(vocab, encoding="utf-8")


def _write_conformance(tmp_path):
    # Same likely_entity label resolves to two distinct URIs → "ambiguous",
    # which propose_alignment always downgrades to ref_class_status
    # "unresolved" (never guesses the nearest class).
    path = tmp_path / "core-concepts-conformance.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "core_concepts": [
                    {
                        "uri": "https://example.com/ont/commercial#SalesContract",
                        "label": "SalesContract",
                        "outcome": "conforms",
                    },
                    {
                        "uri": "https://example.com/ont/commercial#TradeTerms",
                        "label": "SalesContract",
                        "outcome": "conforms",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _mock_client_never_called():
    def create_completion(**kwargs):  # pragma: no cover - must never fire
        raise AssertionError("LLM must not be called for an unresolved-anchor table")

    client = mock.MagicMock()
    client.chat.completions.create = create_completion
    return client


class TestUnresolvedAnchorEmitsNoRelationshipClusters:
    def _run(self, tmp_path):
        analysis = tmp_path / "_analysis"
        sources = tmp_path / "sources"
        _write_affinity(analysis)
        _write_sources(sources)
        conformance = _write_conformance(tmp_path)
        client = _mock_client_never_called()
        with (
            mock.patch(
                "kairos_ontology.core.propose_alignment.get_ai_client",
                return_value=client,
            ),
            mock.patch(
                "kairos_ontology.core.propose_alignment.extract_ref_model_inventory",
                return_value=REF_CLASSES,
            ),
        ):
            alignments = build_domain_alignments(
                analysis_dir=analysis,
                sources_dir=sources,
                catalog_path=None,
                domains_filter=["commercial"],
                conformance_artifact_path=conformance,
            )
        return alignment_to_dict(alignments[0])["tables"][0]

    def test_unresolved_table_has_no_property_claims_and_no_clusters(self, tmp_path):
        table = self._run(tmp_path)
        assert table["ref_class_status"] == "unresolved"
        assert table["columns"] == []
        assert table["custom_columns"] == []
        # The address-part columns would otherwise cluster into a
        # 'hasBillingAddress' relationship candidate — must not fire here.
        assert "relationship_candidates" not in table
