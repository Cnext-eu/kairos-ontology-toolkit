# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Accelerator-direct binding resolution (DD-144).

A binding's ``target.class`` (and a relationship's ``target``) may resolve directly against
an accelerator/reference-model class with no local ``rdfs:subClassOf`` declaration at all,
because ``_ontology_symbols`` already builds its semantic index over the full resolved graph
(DD-103) — these tests prove the fallback lookup that makes that class (and its properties)
actually reachable from a binding, without weakening the existing "unresolved class" failure
path for a token that matches nothing anywhere.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from kairos_ontology.core.compiler import compile_domain

_SOURCE = textwrap.dedent(
    """
    @prefix src: <https://example.test/source#> .
    @prefix kb: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    src:crm a kb:SourceSystem ; rdfs:label "crm" ;
      kb:database "raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .
    src:orgs a kb:SourceTable ; kb:sourceSystem src:crm ;
      kb:tableName "organisations" ; kb:primaryKeyColumns "org_id" .
    src:orgid a kb:SourceColumn ; kb:sourceTable src:orgs ;
      kb:columnName "org_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean .
    src:name a kb:SourceColumn ; kb:sourceTable src:orgs ;
      kb:columnName "name" ; kb:dataType "varchar(200)" ;
      kb:nullable "false"^^xsd:boolean .
    src:tps a kb:SourceTable ; kb:sourceSystem src:crm ;
      kb:tableName "trade_parties" ; kb:primaryKeyColumns "trade_party_id" .
    src:tpid a kb:SourceColumn ; kb:sourceTable src:tps ;
      kb:columnName "trade_party_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean .
    src:tpname a kb:SourceColumn ; kb:sourceTable src:tps ;
      kb:columnName "name" ; kb:dataType "varchar(200)" ;
      kb:nullable "false"^^xsd:boolean .
    """
).strip()

# A local class (``party:Organisation``, declared first so it defines the domain namespace)
# and a distinct "accelerator" class (``acc:TradeParty``) that is NOT locally subclassed —
# unlike ``tests/test_compiler_inherited_props.py``'s ``_ONTOLOGY``, both classes are
# explicitly typed ``owl:Class`` here, and there is no ``rdfs:subClassOf`` link between them,
# so this fixture only compiles at all if the DD-144 fallback resolves ``acc:TradeParty``
# directly.
_ONTOLOGY = """
    @prefix party: <https://example.test/party#> .
    @prefix acc: <https://example.test/accelerator/party#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" ;
      rdfs:label "Party slice" .
    party:Organisation a owl:Class ; rdfs:label "Organisation" .
    party:orgId a owl:DatatypeProperty ;
      rdfs:domain party:Organisation ; rdfs:range xsd:string .
    party:tradesAs a owl:ObjectProperty ;
      rdfs:domain party:Organisation ; rdfs:range acc:TradeParty .
    acc:TradeParty a owl:Class ; rdfs:label "Trade Party" .
    acc:tradePartyId a owl:DatatypeProperty ;
      rdfs:domain acc:TradeParty ; rdfs:range xsd:string .
    acc:partyName a owl:DatatypeProperty ;
      rdfs:domain acc:TradeParty ; rdfs:range xsd:string .
"""


def _hub(tmp_path: Path, *, ontology: str, bindings: dict[str, str]) -> Path:
    ontology_dir = tmp_path / "model" / "ontologies"
    source_dir = tmp_path / "integration" / "sources" / "crm"
    binding_dir = tmp_path / "integration" / "bindings"
    ontology_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    binding_dir.mkdir(parents=True)
    (tmp_path / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    (ontology_dir / "party.ttl").write_text(textwrap.dedent(ontology).strip(), encoding="utf-8")
    (source_dir / "crm.vocabulary.ttl").write_text(_SOURCE, encoding="utf-8")
    for name, text in bindings.items():
        (binding_dir / f"{name}.binding.yaml").write_text(
            textwrap.dedent(text).strip(), encoding="utf-8"
        )
    return tmp_path


def test_binding_targets_accelerator_class_with_no_local_subclass(tmp_path):
    binding = """
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: crm-organisation
          domain: party
        source:
          relation: crm.organisations
        target:
          class: acc:TradeParty
        grain:
          columns: [org_id]
        identity:
          strategy: source-natural
          sourceKey: [org_id]
        load:
          mode: full-refresh
        fields:
          - property: acc:tradePartyId
            expression: org_id
          - property: acc:partyName
            expression: name
    """
    hub = _hub(tmp_path, ontology=_ONTOLOGY, bindings={"organisation": binding})
    result = compile_domain(hub, "party")
    assert result.succeeded, {item.code for item in result.diagnostics.items}
    assert result.explain is not None
    entity = result.explain.entities[0]
    assert entity.target_class == "acc:TradeParty"
    assert ("acc:partyName", "name") in entity.fields


def test_full_iri_accelerator_class_and_property_resolve(tmp_path):
    binding = """
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: crm-organisation
          domain: party
        source:
          relation: crm.organisations
        target:
          class: "https://example.test/accelerator/party#TradeParty"
        grain:
          columns: [org_id]
        identity:
          strategy: source-natural
          sourceKey: [org_id]
        load:
          mode: full-refresh
        fields:
          - property: "https://example.test/accelerator/party#tradePartyId"
            expression: org_id
          - property: "https://example.test/accelerator/party#partyName"
            expression: name
    """
    hub = _hub(tmp_path, ontology=_ONTOLOGY, bindings={"organisation": binding})
    result = compile_domain(hub, "party")
    assert result.succeeded, {item.code for item in result.diagnostics.items}


def test_relationship_target_resolves_against_accelerator_class(tmp_path):
    organisation = """
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: crm-organisation
          domain: party
        source:
          relation: crm.organisations
        target:
          class: party:Organisation
        grain:
          columns: [org_id]
        identity:
          strategy: source-natural
          sourceKey: [org_id]
        load:
          mode: full-refresh
        fields:
          - property: party:orgId
            expression: org_id
        relationships:
          - property: party:tradesAs
            target: acc:TradeParty
            join: [{local: org_id, foreign: trade_party_id}]
            cardinality: many-to-one
            mode: non-temporal
            missingParent: error
            ambiguousParent: error
    """
    trade_party = """
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: crm-trade-party
          domain: party
        source:
          relation: crm.trade_parties
        target:
          class: acc:TradeParty
        grain:
          columns: [trade_party_id]
        identity:
          strategy: source-natural
          sourceKey: [trade_party_id]
        load:
          mode: full-refresh
        fields:
          - property: acc:tradePartyId
            expression: trade_party_id
          - property: acc:partyName
            expression: name
    """
    hub = _hub(
        tmp_path,
        ontology=_ONTOLOGY,
        bindings={"organisation": organisation, "trade-party": trade_party},
    )
    result = compile_domain(hub, "party")
    assert result.succeeded, {item.code for item in result.diagnostics.items}


def test_unresolvable_class_still_reports_unknown_class(tmp_path):
    binding = """
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: crm-organisation
          domain: party
        source:
          relation: crm.organisations
        target:
          class: acc:NoSuchClass
        grain:
          columns: [org_id]
        identity:
          strategy: source-natural
          sourceKey: [org_id]
        load:
          mode: full-refresh
        fields:
          - property: acc:partyName
            expression: name
    """
    hub = _hub(tmp_path, ontology=_ONTOLOGY, bindings={"organisation": binding})
    result = compile_domain(hub, "party")
    assert not result.succeeded
    # binding.unknown-class is remapped to the entity-local safety code (kernel.py's
    # BLOCKING_ENTITY_CODES table) once the entity is marked blocked.
    assert "safety.class-unresolved" in {item.code for item in result.diagnostics.items}
