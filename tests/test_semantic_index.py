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
    alternate_legal_name = index.property_by_uri("https://example.org/alternate#legalName")
    owns = index.property_by_uri("https://example.org/main#owns")
    alternate_party = index.class_by_uri("https://example.org/alternate#Party")

    assert [item.uri for item in company.equivalent_classes] == [
        "https://example.org/alternate#Party"
    ]
    assert company.restrictions[0].kind == "minCardinality"
    assert company.restrictions[0].value == 1
    assert [item.uri for item in legal_name.superproperties] == ["https://example.org/main#name"]
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
    assert [item.uri for item in owns.inverse_properties] == ["https://example.org/main#ownedBy"]
    assert [item.uri for item in index.individuals] == ["https://example.org/main#active"]


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

    assert [item.uri for item in company.ancestors] == ["https://example.org/main#Organisation"]
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


def test_slice_enriches_property_links_but_to_dict_stays_bare(tmp_path):
    """#759: a slice link carried only `uri`/`provenance`/`distance`, so every
    `show-class-inventory` reader had to look each property up again. The enrichment is
    additive and confined to `slice()`; `to_dict()` feeds closure hashes and determinism
    baselines and must not move."""
    index = _load(tmp_path, SemanticProfile.KAIROS_DESIGN)

    company = next(
        item
        for item in index.slice()["classes"]
        if item["uri"] == "https://example.org/main#Company"
    )
    by_uri = {link["uri"]: link for link in company["direct_properties"]}
    assert by_uri["https://example.org/main#employeeCount"] == {
        "uri": "https://example.org/main#employeeCount",
        "provenance": by_uri["https://example.org/main#employeeCount"]["provenance"],
        "distance": 1,
        "name": "employeeCount",
        "property_type": "datatype",
        "ranges": ["http://www.w3.org/2001/XMLSchema#integer"],
    }
    inherited = {link["uri"]: link for link in company["inherited_properties"]}
    assert inherited["https://example.org/main#owns"]["property_type"] == "object"
    assert inherited["https://example.org/main#owns"]["ranges"] == [
        "https://example.org/main#Party"
    ]

    bare = next(
        item
        for item in index.to_dict()["classes"]
        if item["uri"] == "https://example.org/main#Company"
    )
    assert set(bare["direct_properties"][0]) == {"uri", "provenance", "distance"}


ORPHANED_DOMAIN_ONTOLOGY = """\
@prefix ex: <https://example.org/main#> .
@prefix absent: <https://example.org/absent#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<https://example.org/main> a owl:Ontology ; owl:versionInfo "1.0" .

ex:Present a owl:Class .
ex:RdfsTyped a rdfs:Class .
ex:ImpliedByParent rdfs:subClassOf ex:Present .

# Attaches: its domain is a declared owl:Class.
ex:onPresent a owl:DatatypeProperty ; rdfs:domain ex:Present ; rdfs:range xsd:string .
# Attaches: rdfs:Class counts, and so does a class implied by rdfs:subClassOf.
ex:onRdfsTyped a owl:DatatypeProperty ; rdfs:domain ex:RdfsTyped ; rdfs:range xsd:string .
ex:onImplied a owl:DatatypeProperty ; rdfs:domain ex:ImpliedByParent ; rdfs:range xsd:string .
# Does NOT attach: the module declares the prefix but never imports it, so the class
# is never typed here. This is the shipped defect in bsp/financial.
ex:orphaned a owl:DatatypeProperty ; rdfs:domain absent:NeverDeclared ; rdfs:range xsd:string .
"""


def test_a_domain_naming_an_absent_class_is_recorded_not_dropped(tmp_path):
    """The silent version of this made a real reference term look like a missing one."""
    path = tmp_path / "orphan.ttl"
    path.write_text(ORPHANED_DOMAIN_ONTOLOGY, encoding="utf-8")
    index = load_ontology(path, profile=SemanticProfile.KAIROS_DESIGN).semantic_index

    assert index.unattached_property_domains == (
        ("https://example.org/main#orphaned", "https://example.org/absent#NeverDeclared"),
    )


def test_the_wider_class_universe_is_honoured(tmp_path):
    """rdfs:Class and subClassOf-implied targets must not be reported as unattached.

    The class universe here is wider than ``rdf:type owl:Class``; a narrower predicate
    would report two false positives on this fixture alone.
    """
    path = tmp_path / "orphan.ttl"
    path.write_text(ORPHANED_DOMAIN_ONTOLOGY, encoding="utf-8")
    index = load_ontology(path, profile=SemanticProfile.KAIROS_DESIGN).semantic_index

    reported = {prop for prop, _ in index.unattached_property_domains}
    assert "https://example.org/main#onRdfsTyped" not in reported
    assert "https://example.org/main#onImplied" not in reported


def test_a_clean_closure_reports_nothing(tmp_path):
    index = _load(tmp_path, SemanticProfile.KAIROS_DESIGN)
    assert index.unattached_property_domains == ()


def test_unattached_domains_stay_out_of_the_serialized_index(tmp_path):
    """It describes what the closure failed to hold, so it must not move a closure hash."""
    path = tmp_path / "orphan.ttl"
    path.write_text(ORPHANED_DOMAIN_ONTOLOGY, encoding="utf-8")
    index = load_ontology(path, profile=SemanticProfile.KAIROS_DESIGN).semantic_index

    assert index.unattached_property_domains  # precondition: there is something to leak
    assert "unattached_property_domains" not in index.to_dict()


def _scan_provenance(result, subject, predicate=None, obj=None):
    """The pre-#598 implementation: scan the sources in closure order, first match wins."""
    for source in result.sources:
        if predicate is None:
            if any(source.graph.triples((subject, None, None))):
                return source.manifest.source_identity, source.manifest.import_depth
        elif (subject, predicate, obj) in source.graph:
            return source.manifest.source_identity, source.manifest.import_depth
    return result.manifest[0].source_identity, result.manifest[0].import_depth


def test_indexed_provenance_matches_a_source_scan(tmp_path):
    """#598: provenance is looked up in a per-result index; the answer must not move.

    A two-file closure where the import also states facts about a root class, so "first
    source in closure order" is actually exercised.
    """
    from rdflib import RDF, RDFS, URIRef

    from kairos_ontology.core import semantic_index

    (tmp_path / "base.ttl").write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "<urn:base> a owl:Ontology .\n"
        "<urn:Thing> a owl:Class .\n"
        '<urn:Party> rdfs:comment "stated by the import too" .\n',
        encoding="utf-8",
    )
    (tmp_path / "catalog.xml").write_text(
        '<?xml version="1.0"?>\n<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        '  <uri name="urn:base" uri="base.ttl"/>\n</catalog>\n',
        encoding="utf-8",
    )
    root = tmp_path / "root.ttl"
    root.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "<urn:root> a owl:Ontology ; owl:imports <urn:base> .\n"
        "<urn:Party> a owl:Class ; rdfs:subClassOf <urn:Thing> .\n",
        encoding="utf-8",
    )
    result = load_ontology(
        root, catalog_path=tmp_path / "catalog.xml", profile=SemanticProfile.RDFS
    )
    assert len(result.sources) == 2, "the import must resolve for this test to mean anything"
    subjects = {s for s in result.graph.subjects()} | {URIRef("urn:Absent")}
    for subject in subjects:
        got = semantic_index._term_provenance(result, subject)
        assert (got.source_identity, got.import_depth) == _scan_provenance(result, subject)
    for triple in list(result.graph) + [(URIRef("urn:Party"), RDF.type, URIRef("urn:Nope"))]:
        got = semantic_index._term_provenance(result, *triple)
        assert (got.source_identity, got.import_depth) == _scan_provenance(result, *triple)
        assert semantic_index._is_asserted(result, *triple) == any(
            triple in source.graph for source in result.sources
        )
    assert semantic_index._is_asserted(
        result, URIRef("urn:Party"), RDFS.subClassOf, URIRef("urn:Thing")
    )


def test_only_owl_rl_copies_the_closure_graph(tmp_path):
    """#598: the read-only profiles index the load result's own graph; OWL RL expands a
    copy, so the load result is never mutated."""
    from kairos_ontology.core import semantic_index

    path = tmp_path / "model.ttl"
    path.write_text(ONTOLOGY, encoding="utf-8")
    result = load_ontology(path, profile=SemanticProfile.RDFS)
    assert semantic_index._semantic_graph(result, SemanticProfile.RDFS) is result.graph
    before = len(result.graph)
    expanded = semantic_index._semantic_graph(result, SemanticProfile.OWL_RL)
    assert expanded is not result.graph
    assert len(result.graph) == before
    assert len(expanded) > before
