# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the design-time MDM package (vocabulary, validation, projector)."""

from __future__ import annotations

import json

import pytest
from rdflib import Graph

from kairos_ontology.mdm.profile_projector import (
    extract_profile,
    generate_mdm_profile_artifacts,
)
from kairos_ontology.mdm.validation import validate_mdm_extension

NS = "https://acme.example/ont/client#"

# A domain ontology fragment merged with its MDM extension, expressed in one TTL
# document (the projector merges the two at runtime; a single graph is equivalent).
VALID_TTL = f"""
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix : <{NS}> .
@prefix kairos-mdm: <https://kairos.cnext.eu/mdm#> .

<{NS}> a owl:Ontology ;
    rdfs:label "Client domain" ;
    owl:versionInfo "1.2.0" ;
    kairos-mdm:probabilisticArtifact [
        kairos-mdm:artifactDigest "sha256:abc123" ;
        kairos-mdm:artifactVersion "2.0.0" ;
        kairos-mdm:artifactUri "https://models.acme.example/client-match@2"
    ] .

:Client a owl:Class ;
    rdfs:label "Client" ;
    kairos-mdm:mastered true ;
    kairos-mdm:mdmStyle "coexistence" ;
    kairos-mdm:makerChecker true ;
    kairos-mdm:autoActionBound 0.95 ;
    kairos-mdm:slaHours 48 ;
    kairos-mdm:escalationRole "data-owner" .

:vatNumber a owl:DatatypeProperty ;
    rdfs:label "VAT number" ;
    rdfs:domain :Client ;
    rdfs:range xsd:string ;
    kairos-mdm:identifier true ;
    kairos-mdm:identifierType "VAT" ;
    kairos-mdm:matchAttribute true ;
    kairos-mdm:authoritativeSource "crm" ;
    kairos-mdm:survivorship "source-precedence" ;
    kairos-mdm:survivorshipPriority 1 .

:legalName a owl:DatatypeProperty ;
    rdfs:label "Legal name" ;
    rdfs:domain :Client ;
    rdfs:range xsd:string ;
    kairos-mdm:matchAttribute true ;
    kairos-mdm:survivorship "most-trusted" .

:vatRule a kairos-mdm:MatchRule ;
    kairos-mdm:appliesTo :Client ;
    kairos-mdm:onAttribute :vatNumber ;
    kairos-mdm:comparator "normalized" ;
    kairos-mdm:threshold 1.0 ;
    kairos-mdm:matchAction "auto-merge" .

:vatComplete a kairos-mdm:DataQualityRule ;
    kairos-mdm:appliesTo :Client ;
    kairos-mdm:onAttribute :vatNumber ;
    kairos-mdm:dimension "completeness" ;
    kairos-mdm:scorecardThreshold 0.98 ;
    kairos-mdm:severity "error" .

:Country a owl:Class ;
    rdfs:label "Country" ;
    kairos-mdm:referenceList true ;
    kairos-mdm:referenceOwner "reference-data-team" ;
    kairos-mdm:releasePolicy "quarterly" ;
    kairos-mdm:license "ISO-3166 (public)" .

:regionSteward a kairos-mdm:StewardRole ;
    kairos-mdm:roleName "Region Steward" ;
    kairos-mdm:scope "EU" .
"""


@pytest.fixture()
def valid_graph() -> Graph:
    g = Graph()
    g.parse(data=VALID_TTL, format="turtle")
    return g


def test_validation_passes_on_valid_extension(valid_graph):
    result = validate_mdm_extension(valid_graph, namespace=NS)
    assert result["passed"], result["errors"]
    assert result["errors"] == []


def test_extract_profile_captures_mastered_concept(valid_graph):
    profile = extract_profile(valid_graph, NS, "client", {"version": "1.2.0"})
    assert profile.provenance.ontology_version == "1.2.0"
    assert len(profile.mastered_concepts) == 1

    client = profile.mastered_concepts[0]
    assert client.name == "Client"
    assert client.mdm_style == "coexistence"
    assert client.workflow.maker_checker is True
    assert client.workflow.auto_action_bound == 0.95
    assert client.workflow.sla_hours == 48

    # match attributes
    names = {a.name for a in client.match_attributes}
    assert names == {"vatNumber", "legalName"}
    vat = next(a for a in client.match_attributes if a.name == "vatNumber")
    assert vat.is_identifier is True
    assert vat.identifier_type == "VAT"
    assert vat.authoritative_sources == ["crm"]
    assert vat.survivorship == "source-precedence"

    # deterministic match rule + DQ rule attached to the concept
    assert len(client.match_rules) == 1
    assert client.match_rules[0].action == "auto-merge"
    assert len(client.data_quality) == 1
    assert client.data_quality[0].dimension == "completeness"


def test_extract_profile_captures_reference_and_roles_and_artifact(valid_graph):
    profile = extract_profile(valid_graph, NS, "client")
    assert len(profile.reference_lists) == 1
    ref = profile.reference_lists[0]
    assert ref.owner == "reference-data-team"
    assert ref.license == "ISO-3166 (public)"

    assert len(profile.steward_roles) == 1
    assert profile.steward_roles[0].name == "Region Steward"

    assert profile.probabilistic_artifact is not None
    assert profile.probabilistic_artifact.digest == "sha256:abc123"
    assert profile.probabilistic_artifact.version == "2.0.0"


def test_generate_artifacts_emits_json_and_md_with_stable_digest(tmp_path):
    ext = tmp_path / "client-mdm-ext.ttl"
    ext.write_text(VALID_TTL, encoding="utf-8")
    # Empty base graph; all triples live in the ext for this test.
    base = Graph()

    artifacts = generate_mdm_profile_artifacts(
        base, NS, "client", mdm_ext_path=ext, ontology_metadata={"version": "1.2.0"}
    )
    assert set(artifacts) == {"client-mdm-profile.json", "client-mdm-profile.md"}

    payload = json.loads(artifacts["client-mdm-profile.json"])
    assert payload["content_digest"].startswith("sha256:")
    assert payload["provenance"]["domain"] == "client"
    assert len(payload["mastered_concepts"]) == 1

    # Digest is reproducible: a second run over the same policy yields the same digest,
    # even though generated_at differs (immutability / content-addressing — ADR-11).
    artifacts2 = generate_mdm_profile_artifacts(
        base, NS, "client", mdm_ext_path=ext, ontology_metadata={"version": "1.2.0"}
    )
    payload2 = json.loads(artifacts2["client-mdm-profile.json"])
    assert payload["content_digest"] == payload2["content_digest"]

    assert "# MDM profile — client" in artifacts["client-mdm-profile.md"]


def test_generate_artifacts_empty_when_no_extension(tmp_path):
    base = Graph()
    assert generate_mdm_profile_artifacts(base, NS, "client", mdm_ext_path=None) == {}
    missing = tmp_path / "nope-mdm-ext.ttl"
    assert generate_mdm_profile_artifacts(base, NS, "client", mdm_ext_path=missing) == {}


def test_generate_artifacts_empty_when_no_mastered_or_reference(tmp_path):
    ttl = f"""
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix : <{NS}> .
    :Client a owl:Class .
    """
    ext = tmp_path / "client-mdm-ext.ttl"
    ext.write_text(ttl, encoding="utf-8")
    assert generate_mdm_profile_artifacts(Graph(), NS, "client", mdm_ext_path=ext) == {}
