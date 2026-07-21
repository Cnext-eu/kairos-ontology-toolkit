# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the versioned semantic index (DD-103)."""

from kairos_ontology.core.ontology_loader import SemanticProfile, load_ontology
from kairos_ontology.core.semantic_index import SEMANTIC_INDEX_VERSION


ONTOLOGY = """\
@prefix ex: <https://example.org/main#> .
@prefix alt: <https://example.org/alternate#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://example.org/main> a owl:Ontology ; owl:versionInfo "2.0" .

ex:Party a owl:Class .
alt:Party a owl:Class .
ex:Organisation a owl:Class ; rdfs:subClassOf ex:Party .
ex:Company a owl:Class ; rdfs:subClassOf ex:Organisation ;
    owl:equivalentClass alt:Party ;
    rdfs:subClassOf [
        a owl:Restriction ;
        owl:onProperty ex:employeeCount ;
        owl:minCardinality 1
    ] .
ex:Composite a owl:Class ;
    owl:equivalentClass [ owl:intersectionOf ( ex:Party ex:Organisation ) ] .

ex:name a owl:DatatypeProperty ;
    rdfs:domain ex:Party ;
    rdfs:range xsd:string .
ex:legalName a owl:DatatypeProperty ;
    rdfs:subPropertyOf ex:name ;
    rdfs:domain ex:Organisation ;
    owl:equivalentProperty alt:legalName .
alt:legalName a owl:DatatypeProperty .
ex:employeeCount a owl:DatatypeProperty ;
    rdfs:domain ex:Company ;
    rdfs:range xsd:integer .
ex:owns a owl:ObjectProperty ; rdfs:domain ex:Party ; rdfs:range ex:Party ;
    owl:inverseOf ex:ownedBy .
ex:ownedBy a owl:ObjectProperty .

ex:active a ex:Status ; rdfs:label "Active" .
ex:Status a owl:Class .
"""


def _load(tmp_path, profile: SemanticProfile):
    path = tmp_path / "model.ttl"
    path.write_text(ONTOLOGY, encoding="utf-8")
    return load_ontology(path, profile=profile).semantic_index


def test_rdfs_profile_distinguishes_direct_and_inherited_properties(tmp_path):
    index = _load(tmp_path, SemanticProfile.RDFS)
    company = index.class_by_uri("https://example.org/main#Company")

    assert [item.uri for item in company.direct_properties] == [
        "https://example.org/main#employeeCount"
    ]
    assert {item.uri for item in company.inherited_properties} == {
        "https://example.org/main#legalName",
        "https://example.org/main#name",
        "https://example.org/main#owns",
    }
    assert [(item.uri, item.distance) for item in company.ancestors] == [
        ("https://example.org/main#Organisation", 1),
        ("https://example.org/main#Party", 2),
    ]


def test_duplicate_local_names_remain_distinct(tmp_path):
    index = _load(tmp_path, SemanticProfile.KAIROS_DESIGN)
    parties = [item for item in index.classes if item.name == "Party"]

    assert {item.uri for item in parties} == {
        "https://example.org/alternate#Party",
        "https://example.org/main#Party",
    }


def test_design_profile_exposes_equivalence_inverse_individuals_and_restrictions(tmp_path):
    index = _load(tmp_path, SemanticProfile.KAIROS_DESIGN)
    company = index.class_by_uri("https://example.org/main#Company")
    legal_name = index.property_by_uri("https://example.org/main#legalName")
    alternate_legal_name = index.property_by_uri(
        "https://example.org/alternate#legalName"
    )
    owns = index.property_by_uri("https://example.org/main#owns")
    alternate_party = index.class_by_uri("https://example.org/alternate#Party")

    assert [item.uri for item in company.equivalent_classes] == [
        "https://example.org/alternate#Party"
    ]
    assert company.restrictions[0].kind == "minCardinality"
    assert company.restrictions[0].value == 1
    assert [item.uri for item in legal_name.superproperties] == [
        "https://example.org/main#name"
    ]
    assert [item.uri for item in legal_name.equivalent_properties] == [
        "https://example.org/alternate#legalName"
    ]
    assert [item.uri for item in alternate_legal_name.equivalent_properties] == [
        "https://example.org/main#legalName"
    ]
    assert [item.uri for item in alternate_party.equivalent_classes] == [
        "https://example.org/main#Company"
    ]
    assert {item.uri for item in legal_name.domains} == {
        "https://example.org/main#Organisation",
        "https://example.org/main#Party",
    }
    assert [item.uri for item in owns.inverse_properties] == [
        "https://example.org/main#ownedBy"
    ]
    assert [item.uri for item in index.individuals] == [
        "https://example.org/main#active"
    ]


def test_design_profile_exposes_rdf_list_members(tmp_path):
    index = _load(tmp_path, SemanticProfile.KAIROS_DESIGN)
    composite = index.class_by_uri("https://example.org/main#Composite")

    assert [item.uri for item in composite.intersection_members] == [
        "https://example.org/main#Organisation",
        "https://example.org/main#Party",
    ]


def test_asserted_profile_does_not_leak_design_or_transitive_facts(tmp_path):
    index = _load(tmp_path, SemanticProfile.ASSERTED)
    company = index.class_by_uri("https://example.org/main#Company")

    assert [item.uri for item in company.ancestors] == [
        "https://example.org/main#Organisation"
    ]
    assert company.inherited_properties == ()
    assert company.equivalent_classes == ()
    assert company.restrictions == ()
    assert index.individuals == ()


def test_index_serialization_and_slice_disclose_semantic_coverage(tmp_path):
    index = _load(tmp_path, SemanticProfile.KAIROS_DESIGN)

    serialized = index.to_dict()
    sliced = index.slice(max_classes=2)

    assert serialized["semantic_index_version"] == SEMANTIC_INDEX_VERSION
    assert serialized["semantic_profile"] == "kairos-design"
    assert sliced["metadata"]["closure_hash"] == index.closure_hash
    assert sliced["metadata"]["included_class_count"] == 2
    assert sliced["metadata"]["total_class_count"] == len(index.classes)
    assert sliced["metadata"]["truncated"] is True
    assert sliced["metadata"]["selection_rule"] == "uri-order"
