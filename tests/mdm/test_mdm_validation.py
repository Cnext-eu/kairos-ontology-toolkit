# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for MDM extension structural validation (error paths)."""

from __future__ import annotations

from rdflib import Graph

from kairos_ontology.mdm.validation import validate_mdm_extension

NS = "https://acme.example/ont/client#"

HEADER = f"""
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix : <{NS}> .
@prefix kairos-mdm: <https://kairos.cnext.eu/mdm#> .
"""


def _graph(body: str) -> Graph:
    g = Graph()
    g.parse(data=HEADER + body, format="turtle")
    return g


def test_invalid_mdm_style_is_error():
    g = _graph(
        """
        :Client a owl:Class ;
            kairos-mdm:mastered true ;
            kairos-mdm:mdmStyle "banana" .
        :name a owl:DatatypeProperty ; rdfs:domain :Client ;
            kairos-mdm:matchAttribute true .
        """
    )
    result = validate_mdm_extension(g, namespace=NS)
    assert not result["passed"]
    assert any("mdmStyle" in e for e in result["errors"])


def test_invalid_survivorship_is_error():
    g = _graph(
        """
        :vat a owl:DatatypeProperty ; rdfs:domain :Client ;
            kairos-mdm:survivorship "guesswork" .
        """
    )
    result = validate_mdm_extension(g, namespace=NS)
    assert not result["passed"]
    assert any("survivorship" in e for e in result["errors"])


def test_match_rule_without_attribute_and_bad_action_is_error():
    g = _graph(
        """
        :r a kairos-mdm:MatchRule ;
            kairos-mdm:comparator "telepathy" ;
            kairos-mdm:matchAction "explode" ;
            kairos-mdm:threshold 3.0 .
        """
    )
    result = validate_mdm_extension(g, namespace=NS)
    assert not result["passed"]
    joined = " ".join(result["errors"])
    assert "onAttribute" in joined
    assert "comparator" in joined
    assert "matchAction" in joined
    assert "threshold" in joined


def test_probabilistic_artifact_requires_digest():
    g = _graph(
        """
        :Client a owl:Class ;
            kairos-mdm:mastered true ;
            kairos-mdm:probabilisticArtifact [ kairos-mdm:artifactVersion "1.0" ] .
        :vat a owl:DatatypeProperty ; rdfs:domain :Client ;
            kairos-mdm:identifier true .
        """
    )
    result = validate_mdm_extension(g, namespace=NS)
    assert not result["passed"]
    assert any("artifactDigest" in e for e in result["errors"])


def test_bad_dq_dimension_and_threshold_is_error():
    g = _graph(
        """
        :dq a kairos-mdm:DataQualityRule ;
            kairos-mdm:onAttribute :vat ;
            kairos-mdm:dimension "vibes" ;
            kairos-mdm:scorecardThreshold 2.5 ;
            kairos-mdm:severity "meltdown" .
        """
    )
    result = validate_mdm_extension(g, namespace=NS)
    assert not result["passed"]
    joined = " ".join(result["errors"])
    assert "dimension" in joined
    assert "scorecardThreshold" in joined
    assert "severity" in joined


def test_mastered_without_match_capability_is_warning_not_error():
    g = _graph(
        """
        :Client a owl:Class ; kairos-mdm:mastered true .
        """
    )
    result = validate_mdm_extension(g, namespace=NS)
    assert result["passed"]  # warnings do not fail the gate
    assert any("no match attribute" in w for w in result["warnings"])
