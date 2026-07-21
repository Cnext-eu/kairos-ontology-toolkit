# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the canonical medallion foreign-key projection contract."""

from dataclasses import FrozenInstanceError

import pytest
from rdflib import Graph, URIRef

from kairos_ontology.core.projections.shared import classify_foreign_keys


BASE = "https://example.test/fk#"


def _graph(body: str) -> Graph:
    graph = Graph()
    graph.parse(
        data=f"""
            @prefix ex: <{BASE}> .
            @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

            {body}
        """,
        format="turtle",
    )
    return graph


def test_classifier_normalizes_fk_signals_into_immutable_descriptors():
    graph = _graph(
        """
        ex:Source a owl:Class ;
            rdfs:subClassOf [
                a owl:Restriction ;
                owl:onProperty ex:byCardinality ;
                owl:maxCardinality 1
            ] .
        ex:Target a owl:Class .

        ex:byFunction a owl:ObjectProperty, owl:FunctionalProperty ;
            rdfs:domain ex:Source ; rdfs:range ex:Target .
        ex:byAnnotation a owl:ObjectProperty ;
            rdfs:domain ex:Source ; rdfs:range ex:Target ;
            kairos-ext:silverForeignKey true .
        ex:byColumn a owl:ObjectProperty ;
            rdfs:domain ex:Source ; rdfs:range ex:Target ;
            kairos-ext:silverColumnName "custom_target_sk" .
        ex:byCardinality a owl:ObjectProperty ;
            rdfs:domain ex:Source ; rdfs:range ex:Target .
        ex:unqualified a owl:ObjectProperty ;
            rdfs:domain ex:Source ; rdfs:range ex:Target .
        """
    )

    result = classify_foreign_keys(graph)
    descriptors = {str(item.property_uri).rsplit("#", 1)[-1]: item for item in result.descriptors}

    assert [str(item.property_uri) for item in result.descriptors] == sorted(
        str(item.property_uri) for item in result.descriptors
    )
    assert descriptors["byFunction"].is_silver_fk
    assert descriptors["byAnnotation"].is_silver_fk
    assert descriptors["byColumn"].is_silver_fk
    assert descriptors["byCardinality"].qualifies_silver(URIRef(f"{BASE}Source"))
    assert not descriptors["unqualified"].is_silver_fk
    assert (
        descriptors["byColumn"].physical_column_name("target", layer="silver")
        == "custom_target_sk"
    )
    assert descriptors["byColumn"].physical_column_name("target", layer="gold") == "target_sk"

    with pytest.raises(FrozenInstanceError):
        descriptors["byFunction"].reverse = True


def test_classifier_normalizes_direct_and_reverse_redirection():
    graph = _graph(
        """
        ex:Parent a owl:Class .
        ex:Child a owl:Class .

        ex:hasChild a owl:ObjectProperty ;
            rdfs:domain ex:Parent ; rdfs:range ex:Child ;
            kairos-ext:silverForeignKeyOn ex:Child ;
            kairos-ext:silverColumnName "parent_sk" ;
            kairos-ext:nullable false ;
            kairos-ext:conditionalOnType "Dependent" .

        ex:ownedBy a owl:ObjectProperty ;
            rdfs:domain ex:Child ; rdfs:range ex:Parent ;
            kairos-ext:silverForeignKeyOn ex:Child .
        """
    )

    descriptors = {
        str(item.property_uri).rsplit("#", 1)[-1]: item
        for item in classify_foreign_keys(graph).descriptors
    }
    reverse = descriptors["hasChild"]
    direct = descriptors["ownedBy"]

    assert reverse.domain_class == URIRef(f"{BASE}Parent")
    assert reverse.range_class == URIRef(f"{BASE}Child")
    assert reverse.source_class == URIRef(f"{BASE}Child")
    assert reverse.target_class == URIRef(f"{BASE}Parent")
    assert reverse.redirected and reverse.reverse
    assert reverse.nullable is False
    assert reverse.conditional_on_type == "Dependent"

    assert direct.source_class == URIRef(f"{BASE}Child")
    assert direct.target_class == URIRef(f"{BASE}Parent")
    assert direct.redirected and not direct.reverse


def test_classifier_preserves_invalid_annotation_diagnostics():
    graph = _graph(
        """
        ex:Order a owl:Class .
        ex:Customer a owl:Class .
        ex:Product a owl:Class .

        ex:missingDomain a owl:ObjectProperty ;
            rdfs:range ex:Customer ;
            kairos-ext:silverForeignKey true .
        ex:missingRange a owl:ObjectProperty ;
            rdfs:domain ex:Order ;
            kairos-ext:silverForeignKeyOn ex:Order .
        ex:invalidTarget a owl:ObjectProperty ;
            rdfs:domain ex:Order ; rdfs:range ex:Customer ;
            kairos-ext:silverForeignKeyOn ex:Product .
        """
    )

    result = classify_foreign_keys(graph)

    assert not result.descriptors
    messages = {item.kind: item.message for item in result.diagnostics}
    assert messages["incomplete_silver_foreign_key"] == (
        "silverForeignKey on missingDomain will be skipped — missing rdfs:domain. "
        "Resolve via: kairos-design-domain"
    )
    assert messages["incomplete_silver_foreign_key_on"] == (
        "silverForeignKeyOn on missingRange skipped — missing rdfs:domain or rdfs:range."
    )
    assert messages["invalid_silver_foreign_key_on"] == (
        "silverForeignKeyOn on invalidTarget specifies Product which is neither domain "
        "(Order) nor range (Customer) — skipped."
    )


def test_classifier_keeps_imported_property_and_class_uris():
    imported = "https://reference.example/party#"
    graph = _graph(
        f"""
        <{imported}TradeParty> a owl:Class .
        <{imported}Country> a owl:Class .
        <{imported}registeredIn> a owl:ObjectProperty, owl:FunctionalProperty ;
            rdfs:domain <{imported}TradeParty> ;
            rdfs:range <{imported}Country> .
        """
    )

    descriptor = classify_foreign_keys(graph).descriptors[0]

    assert descriptor.property_uri == URIRef(f"{imported}registeredIn")
    assert descriptor.source_class == URIRef(f"{imported}TradeParty")
    assert descriptor.target_class == URIRef(f"{imported}Country")
    assert descriptor.is_silver_fk
