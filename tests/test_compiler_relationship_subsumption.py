# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Relationship endpoints and ``rdfs:subClassOf`` (#729).

``safety.relationship-endpoint`` compared the property's declared ``rdfs:range`` with the
authored ``target:`` class by strict URI equality. A hub that follows the prescribed pattern --
subclass the reference-model class -- therefore could not author any inherited object property
whose range is a reference class the hub also subclasses: every ``party:Site`` *is a*
``bsp:Location``, but ``bsp:Location != party:Site``.

The domain side never had this problem: ``ResolvedProperty.domain_uris`` is the set of
enumerated classes that *expose* the property (direct or inherited), not ``rdfs:domain``, so the
hub subclass was already in it (DD-133 §8b). Only the range clause is widened here, and only
downward -- a target that is the declared range or a subclass of it.
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
    src:orgsite a kb:SourceColumn ; kb:sourceTable src:orgs ;
      kb:columnName "site_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "true"^^xsd:boolean .
    src:sites a kb:SourceTable ; kb:sourceSystem src:crm ;
      kb:tableName "sites" ; kb:primaryKeyColumns "site_id" .
    src:siteid a kb:SourceColumn ; kb:sourceTable src:sites ;
      kb:columnName "site_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean .
    """
).strip()

_PREFIXES = """
    @prefix party: <https://example.test/party#> .
    @prefix bsp: <https://example.test/base/party#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
    party:orgId a owl:DatatypeProperty ;
      rdfs:domain party:Organisation ; rdfs:range xsd:string .
    party:siteRef a owl:DatatypeProperty ;
      rdfs:domain party:Organisation ; rdfs:range xsd:string .
"""


def _organisation_binding(property_token: str, target_token: str) -> str:
    return f"""
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
          - property: party:siteRef
            expression: site_id
        relationships:
          - property: {property_token}
            target: {target_token}
            join: [{{local: site_id, foreign: site_id}}]
            cardinality: many-to-one
            mode: non-temporal
            missingParent: error
            ambiguousParent: error
    """


def _parent_binding(class_token: str, id_property_token: str) -> str:
    return f"""
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: crm-parent
          domain: party
        source:
          relation: crm.sites
        target:
          class: {class_token}
        grain:
          columns: [site_id]
        identity:
          strategy: source-natural
          sourceKey: [site_id]
        load:
          mode: full-refresh
        fields:
          - property: {id_property_token}
            expression: site_id
    """


def _hub(tmp_path: Path, *, ontology: str, organisation: str, parent: str) -> Path:
    ontology_dir = tmp_path / "model" / "ontologies"
    source_dir = tmp_path / "integration" / "sources" / "crm"
    binding_dir = tmp_path / "integration" / "bindings"
    ontology_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    binding_dir.mkdir(parents=True)
    (tmp_path / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    (ontology_dir / "party.ttl").write_text(
        textwrap.dedent(_PREFIXES + ontology).strip(), encoding="utf-8"
    )
    (source_dir / "crm.vocabulary.ttl").write_text(_SOURCE, encoding="utf-8")
    (binding_dir / "organisation.binding.yaml").write_text(
        textwrap.dedent(organisation).strip(), encoding="utf-8"
    )
    (binding_dir / "parent.binding.yaml").write_text(
        textwrap.dedent(parent).strip(), encoding="utf-8"
    )
    return tmp_path


def _endpoint_messages(result) -> list[str]:
    return [
        item.message
        for item in result.diagnostics.items
        if item.code == "safety.relationship-endpoint"
    ]


def _rendered(result) -> list[str]:
    return [item.render() for item in result.diagnostics.items]


def test_relationship_to_subclass_of_declared_range_compiles(tmp_path):
    """The reported shape: reference property between reference classes, hub subclasses both."""
    ontology = """
        bsp:TradeParty a owl:Class ; rdfs:label "Trade party" .
        bsp:Location a owl:Class ; rdfs:label "Location" .
        party:Organisation a owl:Class ; rdfs:label "Organisation" ;
          rdfs:subClassOf bsp:TradeParty .
        party:Site a owl:Class ; rdfs:label "Site" ; rdfs:subClassOf bsp:Location .
        party:siteId a owl:DatatypeProperty ;
          rdfs:domain bsp:Location ; rdfs:range xsd:string .
        bsp:locatedAt a owl:ObjectProperty ;
          rdfs:domain bsp:TradeParty ; rdfs:range bsp:Location .
    """
    hub = _hub(
        tmp_path,
        ontology=ontology,
        organisation=_organisation_binding("bsp:locatedAt", "party:Site"),
        parent=_parent_binding("party:Site", "party:siteId"),
    )
    result = compile_domain(hub, "party")
    assert not _endpoint_messages(result), _endpoint_messages(result)
    assert result.succeeded, _rendered(result)


def test_relationship_to_superclass_of_declared_range_is_rejected(tmp_path):
    """The widening is one-directional.

    ``party:locatedAt`` ranges over ``party:Site``. Targeting its parent ``party:Location``
    would let a non-Site Location satisfy the join, so it must still fail.
    """
    ontology = """
        party:Organisation a owl:Class ; rdfs:label "Organisation" .
        party:Location a owl:Class ; rdfs:label "Location" .
        party:Site a owl:Class ; rdfs:label "Site" ; rdfs:subClassOf party:Location .
        party:siteId a owl:DatatypeProperty ;
          rdfs:domain party:Location ; rdfs:range xsd:string .
        party:locatedAt a owl:ObjectProperty ;
          rdfs:domain party:Organisation ; rdfs:range party:Site .
    """
    hub = _hub(
        tmp_path,
        ontology=ontology,
        organisation=_organisation_binding("party:locatedAt", "party:Location"),
        parent=_parent_binding("party:Location", "party:siteId"),
    )
    result = compile_domain(hub, "party")
    messages = _endpoint_messages(result)
    assert any("incompatible with" in message for message in messages), _rendered(result)
    assert not result.succeeded


def test_relationship_target_may_descend_from_any_declared_range(tmp_path):
    """A multi-range property accepts a target under *any* declared range, not just ``ranges[0]``.

    ``party:Facility`` sorts before ``party:Site``, so the pre-#729 single ``range_uri`` was
    ``Facility`` and a ``Site`` subclass failed. Union semantics is deliberate: requiring every
    range would newly reject reference models that declare a subproperty range without
    asserting the subsumption chain (#731 tracks that as an ontology-quality warning).
    """
    ontology = """
        party:Organisation a owl:Class ; rdfs:label "Organisation" .
        party:Facility a owl:Class ; rdfs:label "Facility" .
        party:Site a owl:Class ; rdfs:label "Site" .
        party:Warehouse a owl:Class ; rdfs:label "Warehouse" ; rdfs:subClassOf party:Site .
        party:Other a owl:Class ; rdfs:label "Other" .
        party:siteId a owl:DatatypeProperty ;
          rdfs:domain party:Site ; rdfs:range xsd:string .
        party:otherId a owl:DatatypeProperty ;
          rdfs:domain party:Other ; rdfs:range xsd:string .
        party:locatedAt a owl:ObjectProperty ;
          rdfs:domain party:Organisation ; rdfs:range party:Facility , party:Site .
    """
    accepted = _hub(
        tmp_path / "accepted",
        ontology=ontology,
        organisation=_organisation_binding("party:locatedAt", "party:Warehouse"),
        parent=_parent_binding("party:Warehouse", "party:siteId"),
    )
    result = compile_domain(accepted, "party")
    assert not _endpoint_messages(result), _endpoint_messages(result)
    assert result.succeeded, _rendered(result)

    rejected = _hub(
        tmp_path / "rejected",
        ontology=ontology,
        organisation=_organisation_binding("party:locatedAt", "party:Other"),
        parent=_parent_binding("party:Other", "party:otherId"),
    )
    result = compile_domain(rejected, "party")
    assert any("incompatible with" in m for m in _endpoint_messages(result)), _rendered(result)
    assert not result.succeeded


def test_owl_thing_range_stays_rejected_even_when_asserted_as_superclass(tmp_path):
    """``owl:Thing`` is excluded from the ancestor closure the range check consults.

    Protege-style exports assert ``rdfs:subClassOf owl:Thing`` on every class. Without the
    exclusion, ``rdfs:range owl:Thing`` would become permissive for exactly those models and
    the #330 contract (``owl:Thing`` is *worse* than omitting the range) would hold only
    conditionally.
    """
    ontology = """
        party:Organisation a owl:Class ; rdfs:label "Organisation" ;
          rdfs:subClassOf owl:Thing .
        party:Site a owl:Class ; rdfs:label "Site" ; rdfs:subClassOf owl:Thing .
        party:siteId a owl:DatatypeProperty ;
          rdfs:domain party:Site ; rdfs:range xsd:string .
        party:locatedAt a owl:ObjectProperty ;
          rdfs:domain party:Organisation ; rdfs:range owl:Thing .
    """
    hub = _hub(
        tmp_path,
        ontology=ontology,
        organisation=_organisation_binding("party:locatedAt", "party:Site"),
        parent=_parent_binding("party:Site", "party:siteId"),
    )
    result = compile_domain(hub, "party")
    assert any("incompatible with" in m for m in _endpoint_messages(result)), _rendered(result)
    assert not result.succeeded
