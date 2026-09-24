# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""`owl:deprecated` is read, not hardcoded (#938).

The reference models mark the role subclasses a normative pattern forbids -- Consignee,
Carrier, NotifyParty -- `owl:deprecated true`, and name the replacement in the class
comment. The toolkit never read the triple: its only protection was a list of seven URIs,
and a hub binding to `mmt/party#Consignee` got no diagnostic from anchoring, compile or
validate. These pin all three.
"""

from __future__ import annotations

from pathlib import Path

from rdflib import Graph

from kairos_ontology.core.analyse_sources import is_deprecated
from kairos_ontology.core.class_anchoring import ReferenceTerm
from kairos_ontology.core.ontology_integrity import (
    DomainOntology,
    check_deprecated_reference_classes,
)

_TTL = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ref: <https://ref.test/party#> .
ref:Consignee a owl:Class ; owl:deprecated true ;
    rdfs:comment "Use TradeParty with a role assignment instead." .
ref:TradeParty a owl:Class .
"""


def test_the_triple_is_read():
    graph = Graph().parse(data=_TTL, format="turtle")
    assert is_deprecated(graph, "https://ref.test/party#Consignee")
    assert not is_deprecated(graph, "https://ref.test/party#TradeParty")


def test_validate_warns_on_a_hub_class_built_on_a_deprecated_one():
    onto = DomainOntology(
        domain="party",
        path=Path("party.ttl"),
        namespace="https://hub.test/party#",
        external_term_refs=frozenset({
            ("Receiver", "subClassOf", "https://ref.test/party#Consignee"),
            ("Customer", "subClassOf", "https://ref.test/party#TradeParty"),
        }),
    )
    module_terms = {
        "https://ref.test/party": {
            "classes": {"Consignee", "TradeParty"},
            "properties": set(),
            "deprecated": {"Consignee": "Use TradeParty with a role assignment instead."},
        }
    }

    (finding,) = check_deprecated_reference_classes({"party": onto}, module_terms)

    assert finding.code == "integrity.deprecated-reference-class"
    assert finding.level == "warning", "the ontology is valid; the shape is wrong"
    assert "Receiver" in finding.message
    assert "Use TradeParty" in finding.message, "the class names its own replacement"
    assert "qualified-role-assignment" in finding.remediation


def test_the_anchor_catalog_carries_deprecation(tmp_path, monkeypatch):
    from kairos_ontology.core import anchor_tables

    terms = [
        ReferenceTerm(uri="https://ref.test/party#Consignee", name="Consignee", label="",
                      comment="Deprecated. Use TradeParty.", module="https://ref.test/party#",
                      kind="class", deprecated=True),
        ReferenceTerm(uri="https://ref.test/party#TradeParty", name="TradeParty", label="",
                      comment="", module="https://ref.test/party#", kind="class"),
    ]
    monkeypatch.setattr(anchor_tables, "read_reference_terms", lambda *a, **k: terms)
    monkeypatch.setattr(anchor_tables, "load_data_domains", lambda *a, **k: [], raising=False)

    catalog = anchor_tables.build_class_catalog(tmp_path / "catalog.xml", tmp_path, None)

    assert catalog.index["Consignee"][0]["deprecated"] is True
    assert "deprecated" not in catalog.index["TradeParty"][0]


def test_compile_warns_on_a_binding_that_targets_a_deprecated_class(tmp_path):
    from kairos_ontology.core.compiler import CompileMode, compile_domain
    from tests.scenarios.test_scenario_v5 import _copy_hub

    hub = _copy_hub(tmp_path)
    ontology = hub / "model" / "ontologies" / "party.ttl"
    text = ontology.read_text(encoding="utf-8")
    ontology.write_text(
        text.replace(
            'party:Customer a owl:Class ; rdfs:label "Customer" .',
            'party:Customer a owl:Class ; rdfs:label "Customer" ; owl:deprecated true ;\n'
            '  rdfs:comment "Superseded by party:Account." .',
        ),
        encoding="utf-8",
    )

    result = compile_domain(hub, "party", CompileMode.CHECK)

    warnings = [d for d in result.diagnostics.items if d.code == "binding.target-class-deprecated"]
    assert warnings, [d.render() for d in result.diagnostics.items]
    assert "Superseded by party:Account." in warnings[0].message
    assert result.succeeded, "a warning, never blocking"
