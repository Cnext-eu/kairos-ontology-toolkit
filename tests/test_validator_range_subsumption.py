# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Warn when an object property's effective ranges are not a subsumption chain (#731).

`PropertyRecord.ranges` is superproperty-widened: for `hasCustomer rdfs:subPropertyOf
hasParty`, with `hasParty rdfs:range Party` and `hasCustomer rdfs:range Customer`, the
effective ranges are `{Customer, Party}`.

RDFS says the object must be in **every** range — the intersection. That only makes sense
if the ranges form a subsumption chain, and reference models routinely declare the
subproperty range without asserting `Customer rdfs:subClassOf Party`. The result is a
property whose effective range is `Customer ∩ Party` with nothing proving the intersection
is inhabited.

Deliberately a validator warning, not a compiler error. #729's relationship-endpoint check
accepts a target that is or descends from *any* declared range, because intersection
semantics would turn today-green hubs red on exactly this ontology-quality issue — the
compiler's non-suppressible safety kernel is the wrong place to adjudicate reference-model
quality.
"""

from __future__ import annotations

import textwrap

from rdflib import Graph

from kairos_ontology.core.validator import NamingDiagnostic, _check_range_subsumption

_PREFIXES = """
@prefix : <https://example.test/ont#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
"""


def _warnings(turtle: str) -> list[NamingDiagnostic]:
    graph = Graph()
    graph.parse(data=_PREFIXES + textwrap.dedent(turtle), format="turtle")
    found: list[NamingDiagnostic] = []
    _check_range_subsumption(graph, found)
    return found


def test_an_unrelated_pair_is_warned():
    """The reported shape: a subproperty narrows the range without asserting the chain."""
    found = _warnings("""
        :Party a owl:Class .
        :Customer a owl:Class .
        :hasParty a owl:ObjectProperty ; rdfs:range :Party .
        :hasCustomer a owl:ObjectProperty ;
            rdfs:subPropertyOf :hasParty ;
            rdfs:range :Customer .
    """)
    assert len(found) == 1
    assert found[0].code == "range_not_subsumption_chain"
    assert found[0].term_uri.endswith("hasCustomer")
    assert "Customer" in found[0].message and "Party" in found[0].message
    # Name where the other range came from: the author did not write it on this property.
    assert "inherited from hasParty" in found[0].message


def test_asserting_the_chain_silences_it():
    """The remedy the message names, and the whole point of the warning."""
    assert not _warnings("""
        :Party a owl:Class .
        :Customer a owl:Class ; rdfs:subClassOf :Party .
        :hasParty a owl:ObjectProperty ; rdfs:range :Party .
        :hasCustomer a owl:ObjectProperty ;
            rdfs:subPropertyOf :hasParty ;
            rdfs:range :Customer .
    """)


def test_an_indirect_chain_counts():
    """Subsumption is transitive; only an unrelated pair is a finding."""
    assert not _warnings("""
        :Party a owl:Class .
        :Organisation a owl:Class ; rdfs:subClassOf :Party .
        :Customer a owl:Class ; rdfs:subClassOf :Organisation .
        :hasParty a owl:ObjectProperty ; rdfs:range :Party .
        :hasCustomer a owl:ObjectProperty ;
            rdfs:subPropertyOf :hasParty ;
            rdfs:range :Customer .
    """)


def test_a_single_range_is_never_a_finding():
    assert not _warnings("""
        :Party a owl:Class .
        :hasParty a owl:ObjectProperty ; rdfs:range :Party .
    """)


def test_a_property_with_no_range_is_never_a_finding():
    assert not _warnings(":hasParty a owl:ObjectProperty .")


def test_a_datatype_property_is_out_of_scope():
    """The intersection argument is about class ranges; xsd types are a different
    question and would be noise here."""
    assert not _warnings("""
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        :name a owl:DatatypeProperty ; rdfs:range xsd:string .
        :shortName a owl:DatatypeProperty ;
            rdfs:subPropertyOf :name ;
            rdfs:range xsd:token .
    """)


def test_a_property_cycle_terminates():
    """Reference models are not guaranteed acyclic, and a lint must not hang on one."""
    found = _warnings("""
        :A a owl:Class .
        :B a owl:Class .
        :p a owl:ObjectProperty ; rdfs:subPropertyOf :q ; rdfs:range :A .
        :q a owl:ObjectProperty ; rdfs:subPropertyOf :p ; rdfs:range :B .
    """)
    assert {item.term_uri.rsplit("#", 1)[-1] for item in found} == {"p", "q"}


def test_a_class_cycle_terminates():
    assert _warnings("""
        :A a owl:Class ; rdfs:subClassOf :B .
        :B a owl:Class ; rdfs:subClassOf :A .
        :C a owl:Class .
        :p a owl:ObjectProperty ; rdfs:range :A .
        :r a owl:ObjectProperty ; rdfs:subPropertyOf :p ; rdfs:range :C .
    """)
