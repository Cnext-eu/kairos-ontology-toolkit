# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``core.prompt_context`` renders the closure index for a prompt and discloses cuts (DD-243).

Also pins ``SemanticIndex.carries`` / ``coverage`` (#937): the map of which fields a profile
populates must agree with what ``build_semantic_index`` actually fills.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kairos_ontology.core.ontology_loader import SemanticProfile, load_ontology
from kairos_ontology.core.prompt_context import DISCLOSURE_TEMPLATE, render_class_context
from kairos_ontology.core.semantic_index import PROFILE_COVERAGE, PROFILE_DEPENDENT_FIELDS

BASE = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix base: <urn:base#> .

<urn:base> a owl:Ontology .
base:Party a owl:Class ; rdfs:label "Party" ; rdfs:comment "Anyone the business deals with." .
base:name a owl:DatatypeProperty ; rdfs:domain base:Party ; rdfs:range xsd:string .
base:email a owl:DatatypeProperty ; rdfs:domain base:Party ; rdfs:range xsd:string .
base:owns a owl:ObjectProperty ; rdfs:domain base:Party ; rdfs:range base:Party ;
    owl:inverseOf base:ownedBy .
base:ownedBy a owl:ObjectProperty .
"""

ROOT_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix base: <urn:base#> .
@prefix ex: <urn:root#> .

<urn:root> a owl:Ontology ; owl:imports <urn:base> .
ex:Customer a owl:Class ; rdfs:label "Customer" ; rdfs:subClassOf base:Party .
ex:loyaltyTier a owl:DatatypeProperty ; rdfs:domain ex:Customer ; rdfs:range xsd:string .
ex:Lead a owl:Class ; rdfs:label "Lead" .
"""

CUSTOMER = "urn:root#Customer"
LEAD = "urn:root#Lead"


@pytest.fixture
def closure(tmp_path: Path):
    (tmp_path / "base.ttl").write_text(BASE, encoding="utf-8")
    (tmp_path / "root.ttl").write_text(ROOT_TTL, encoding="utf-8")
    (tmp_path / "catalog.xml").write_text(
        '<?xml version="1.0"?>\n<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        '  <uri name="urn:base" uri="base.ttl"/>\n</catalog>\n',
        encoding="utf-8",
    )

    def load(profile: SemanticProfile):
        return load_ontology(
            tmp_path / "root.ttl", catalog_path=tmp_path / "catalog.xml", profile=profile
        ).semantic_index

    return load


class TestRenderClassContext:
    def test_inherited_properties_are_listed_with_their_origin(self, closure):
        index = closure(SemanticProfile.KAIROS_DESIGN)
        rendered = render_class_context(index, [CUSTOMER])
        assert "CLASS: Customer (Customer)" in rendered.text
        assert "- loyaltyTier [datatype: string]" in rendered.text
        assert "- name [datatype: string] (inherited from Party)" in rendered.text
        assert "- owns [object: Party] (inherited from Party)" in rendered.text
        assert not rendered.truncated
        assert "NOTE:" not in rendered.text
        assert set(rendered.shown[CUSTOMER]) == {
            "urn:root#loyaltyTier",
            "urn:base#name",
            "urn:base#email",
            "urn:base#owns",
        }

    def test_a_property_cut_is_disclosed_and_shown_matches_the_text(self, closure):
        index = closure(SemanticProfile.KAIROS_DESIGN)
        rendered = render_class_context(index, [CUSTOMER], max_properties=2)
        assert rendered.omitted_property_count == 2
        assert len(rendered.shown[CUSTOMER]) == 2
        assert "… 2 more not listed" in rendered.text
        assert DISCLOSURE_TEMPLATE.format(classes=0, properties=2) in rendered.text
        # Direct properties survive a cut before inherited ones, and what is shown is what
        # the text lists.
        assert "urn:root#loyaltyTier" in rendered.shown[CUSTOMER]
        for uri in rendered.shown[CUSTOMER]:
            assert uri.rsplit("#", 1)[-1] in rendered.text

    def test_a_class_cut_is_disclosed(self, closure):
        index = closure(SemanticProfile.KAIROS_DESIGN)
        rendered = render_class_context(index, [CUSTOMER, LEAD], max_classes=1)
        assert rendered.omitted_class_count == 1
        assert LEAD not in rendered.shown
        assert "1 further class(es)" in rendered.text

    def test_a_class_with_no_properties_says_so(self, closure):
        index = closure(SemanticProfile.KAIROS_DESIGN)
        rendered = render_class_context(index, [LEAD])
        assert "properties: (none declared)" in rendered.text
        assert rendered.shown[LEAD] == []

    def test_an_unknown_uri_is_skipped_not_invented(self, closure):
        index = closure(SemanticProfile.KAIROS_DESIGN)
        rendered = render_class_context(index, ["urn:root#Nope", LEAD])
        assert "(1 listed)" in rendered.text
        assert "Nope" not in rendered.text


class TestProfileCoverage:
    @pytest.mark.parametrize("profile", list(SemanticProfile))
    def test_the_coverage_map_matches_what_the_index_actually_fills(self, closure, profile):
        """Pins PROFILE_COVERAGE to build_semantic_index: the closure declares an
        inherited property (Customer < Party) and an inverse (owns/ownedBy), so a field
        the profile carries is non-empty here and a field it does not carry is empty."""
        index = closure(profile)
        customer = index.class_by_uri(CUSTOMER)
        owns = index.property_by_uri("urn:base#owns")
        observed = {
            "inherited_properties": bool(customer.inherited_properties),
            "inverse_properties": bool(owns.inverse_properties),
        }
        for field, filled in observed.items():
            assert index.carries(field) == filled, (profile, field)
        assert index.coverage == {
            field: field in PROFILE_COVERAGE[profile] for field in PROFILE_DEPENDENT_FIELDS
        }

    def test_slice_metadata_carries_the_coverage_map(self, closure):
        index = closure(SemanticProfile.RDFS)
        metadata = index.slice(max_classes=1)["metadata"]
        assert metadata["coverage"]["inherited_properties"] is True
        assert metadata["coverage"]["inverse_properties"] is False

    def test_to_dict_is_unchanged(self, closure):
        """Closure hashes and determinism baselines read to_dict; coverage stays out."""
        assert "coverage" not in closure(SemanticProfile.RDFS).to_dict()
