# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Inherited / cross-namespace property resolution tests (DD-108/DD-103/DD-133).

Defect #16: compile-time binding resolution must use the semantic index closure (non-asserted
RDFS profile) so a hub subclass can bind an inherited property whose ``rdfs:domain`` is an
ancestor class in a different namespace, without redeclaring it locally. Ambiguous local-name
aliases must surface a diagnostic instead of silently picking the first match.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from kairos_ontology.core.compiler import build_compile_plan, compile_domain

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
    """
).strip()


def _hub(tmp_path: Path, *, ontology: str, binding: str) -> Path:
    ontology_dir = tmp_path / "model" / "ontologies"
    source_dir = tmp_path / "integration" / "sources" / "crm"
    binding_dir = tmp_path / "integration" / "bindings"
    ontology_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    binding_dir.mkdir(parents=True)
    (tmp_path / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    (ontology_dir / "party.ttl").write_text(textwrap.dedent(ontology).strip(), encoding="utf-8")
    (source_dir / "crm.vocabulary.ttl").write_text(_SOURCE, encoding="utf-8")
    (binding_dir / "organisation.binding.yaml").write_text(
        textwrap.dedent(binding).strip(), encoding="utf-8"
    )
    return tmp_path


# An imported reference class (``bsp:TradeParty``) in a different namespace declares
# ``bsp:partyName``. The hub subclass ``party:Organisation`` only declares ``party:orgId`` and
# inherits ``bsp:partyName`` via ``rdfs:subClassOf``.
_ONTOLOGY = """
    @prefix party: <https://example.test/party#> .
    @prefix bsp: <https://example.test/base/party#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" ;
      rdfs:label "Party slice" .
    party:Organisation a owl:Class ; rdfs:label "Organisation" ;
      rdfs:subClassOf bsp:TradeParty .
    party:orgId a owl:DatatypeProperty ;
      rdfs:domain party:Organisation ; rdfs:range xsd:string .
    bsp:partyName a owl:DatatypeProperty ;
      rdfs:domain bsp:TradeParty ; rdfs:range xsd:string .
"""


def test_inherited_cross_namespace_property_is_bindable(tmp_path):
    binding = """
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
          - property: party:partyName
            expression: name
    """
    hub = _hub(tmp_path, ontology=_ONTOLOGY, binding=binding)
    result = compile_domain(hub, "party")
    assert result.succeeded, {item.code for item in result.diagnostics.items}

    plan = build_compile_plan(hub, "party")
    columns = dict(plan.silver_registry.columns)["organisation"]
    # The inherited cross-namespace property materializes as an output column, snake-cased.
    assert "party_name" in columns
    assert "org_id" in columns


def test_declared_prefix_different_from_file_stem_is_bindable(tmp_path):
    ontology = """
        @prefix equip: <https://example.test/equipment#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        <https://example.test/equipment> a owl:Ontology ; owl:versionInfo "1.0.0" .
        equip:Organisation a owl:Class ; rdfs:label "Organisation" .
        equip:orgId a owl:DatatypeProperty ;
          rdfs:domain equip:Organisation ; rdfs:range xsd:string .
        equip:partyName a owl:DatatypeProperty ;
          rdfs:domain equip:Organisation ; rdfs:range xsd:string .
    """
    binding = """
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: crm-organisation
          domain: party
        source:
          relation: crm.organisations
        target:
          class: equip:Organisation
        grain:
          columns: [org_id]
        identity:
          strategy: source-natural
          sourceKey: [org_id]
        load:
          mode: full-refresh
        fields:
          - property: equip:orgId
            expression: org_id
          - property: equip:partyName
            expression: name
    """
    result = compile_domain(_hub(tmp_path, ontology=ontology, binding=binding), "party")
    assert result.succeeded, {item.code for item in result.diagnostics.items}


def test_empty_prefix_is_bindable(tmp_path):
    ontology = """
        @prefix : <https://example.test/party#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
        :Organisation a owl:Class ; rdfs:label "Organisation" .
        :orgId a owl:DatatypeProperty ;
          rdfs:domain :Organisation ; rdfs:range xsd:string .
        :partyName a owl:DatatypeProperty ;
          rdfs:domain :Organisation ; rdfs:range xsd:string .
    """
    binding = """
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: crm-organisation
          domain: party
        source:
          relation: crm.organisations
        target:
          class: :Organisation
        grain:
          columns: [org_id]
        identity:
          strategy: source-natural
          sourceKey: [org_id]
        load:
          mode: full-refresh
        fields:
          - property: :orgId
            expression: org_id
          - property: :partyName
            expression: name
    """
    result = compile_domain(_hub(tmp_path, ontology=ontology, binding=binding), "party")
    assert result.succeeded, {item.code for item in result.diagnostics.items}


def test_full_iri_class_and_property_are_bindable(tmp_path):
    binding = """
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: crm-organisation
          domain: party
        source:
          relation: crm.organisations
        target:
          class: "https://example.test/party#Organisation"
        grain:
          columns: [org_id]
        identity:
          strategy: source-natural
          sourceKey: [org_id]
        load:
          mode: full-refresh
        fields:
          - property: "https://example.test/party#orgId"
            expression: org_id
          - property: "https://example.test/base/party#partyName"
            expression: name
    """
    result = compile_domain(_hub(tmp_path, ontology=_ONTOLOGY, binding=binding), "party")
    assert result.succeeded, {item.code for item in result.diagnostics.items}


def test_duplicate_prefix_redefinition_is_a_diagnostic(tmp_path):
    ontology = """
        @prefix party: <https://example.test/party#> .
        @prefix dup: <https://example.test/one#> .
        @prefix dup: <https://example.test/two#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
        party:Organisation a owl:Class ; rdfs:label "Organisation" .
        party:orgId a owl:DatatypeProperty ;
          rdfs:domain party:Organisation ; rdfs:range xsd:string .
    """
    binding = """
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
    """
    result = compile_domain(_hub(tmp_path, ontology=ontology, binding=binding), "party")
    assert not result.succeeded
    assert "safety.prefix-ambiguous" in {item.code for item in result.diagnostics.items}


def test_inherited_property_with_differing_source_identity_name(tmp_path):
    # Combined #6 + #16: the identity SOURCE column ``name`` differs from the inherited target
    # property ``partyName``; identity must carry the OUTPUT column, not the source column.
    binding = """
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
          sourceKey: [name]
        load:
          mode: full-refresh
        fields:
          - property: party:orgId
            expression: org_id
          - property: party:partyName
            expression: name
    """
    hub = _hub(tmp_path, ontology=_ONTOLOGY, binding=binding)
    result = compile_domain(hub, "party")
    assert result.succeeded, {item.code for item in result.diagnostics.items}
    sql = result.artifact_dict()["models/silver/party/organisation.sql"]
    # Business identity surrogate key references the OUTPUT column, never the source ``name``.
    assert "generate_surrogate_key(['party_name'])" in sql


def test_ambiguous_inherited_alias_is_a_diagnostic(tmp_path):
    ontology = """
        @prefix party: <https://example.test/party#> .
        @prefix axx: <https://example.test/base-a#> .
        @prefix bxx: <https://example.test/base-b#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" ;
          rdfs:label "Party slice" .
        party:Organisation a owl:Class ; rdfs:label "Organisation" ;
          rdfs:subClassOf axx:ThingA , bxx:ThingB .
        party:orgId a owl:DatatypeProperty ;
          rdfs:domain party:Organisation ; rdfs:range xsd:string .
        axx:label a owl:DatatypeProperty ;
          rdfs:domain axx:ThingA ; rdfs:range xsd:string .
        bxx:label a owl:DatatypeProperty ;
          rdfs:domain bxx:ThingB ; rdfs:range xsd:string .
    """
    binding = """
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
          - property: party:label
            expression: name
    """
    hub = _hub(tmp_path, ontology=ontology, binding=binding)
    result = compile_domain(hub, "party")
    assert not result.succeeded
    assert "binding.ambiguous-property" in {item.code for item in result.diagnostics.items}


def test_unambiguous_qualified_alias_still_resolves(tmp_path):
    # The same two aliased properties, but the field is qualified with the owning namespace.
    ontology = """
        @prefix party: <https://example.test/party#> .
        @prefix axx: <https://example.test/base-a#> .
        @prefix bxx: <https://example.test/base-b#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" ;
          rdfs:label "Party slice" .
        party:Organisation a owl:Class ; rdfs:label "Organisation" ;
          rdfs:subClassOf axx:ThingA , bxx:ThingB .
        party:orgId a owl:DatatypeProperty ;
          rdfs:domain party:Organisation ; rdfs:range xsd:string .
        axx:label a owl:DatatypeProperty ;
          rdfs:domain axx:ThingA ; rdfs:range xsd:string .
        bxx:label a owl:DatatypeProperty ;
          rdfs:domain bxx:ThingB ; rdfs:range xsd:string .
    """
    binding = """
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
          - property: axx:label
            expression: name
    """
    hub = _hub(tmp_path, ontology=ontology, binding=binding)
    result = compile_domain(hub, "party")
    assert result.succeeded, {item.code for item in result.diagnostics.items}


def test_ambiguous_alias_diagnostic_is_independent_of_declaration_order(tmp_path):
    template = """
        @prefix party: <https://example.test/party#> .
        @prefix axx: <https://example.test/base-a#> .
        @prefix bxx: <https://example.test/base-b#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
        party:Organisation a owl:Class ; rdfs:label "Organisation" ;
          rdfs:subClassOf axx:ThingA , bxx:ThingB .
        party:orgId a owl:DatatypeProperty ;
          rdfs:domain party:Organisation ; rdfs:range xsd:string .
        {properties}
    """
    binding = """
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
          - property: party:label
            expression: name
    """
    first_props = """
        axx:label a owl:DatatypeProperty ;
          rdfs:domain axx:ThingA ; rdfs:range xsd:string .
        bxx:label a owl:DatatypeProperty ;
          rdfs:domain bxx:ThingB ; rdfs:range xsd:string .
    """
    second_props = """
        bxx:label a owl:DatatypeProperty ;
          rdfs:domain bxx:ThingB ; rdfs:range xsd:string .
        axx:label a owl:DatatypeProperty ;
          rdfs:domain axx:ThingA ; rdfs:range xsd:string .
    """

    first = compile_domain(
        _hub(tmp_path / "first", ontology=template.format(properties=first_props), binding=binding),
        "party",
    )
    second = compile_domain(
        _hub(
            tmp_path / "second",
            ontology=template.format(properties=second_props),
            binding=binding,
        ),
        "party",
    )

    first_message = next(
        item.message
        for item in first.diagnostics.items
        if item.code == "binding.ambiguous-property"
    )
    second_message = next(
        item.message
        for item in second.diagnostics.items
        if item.code == "binding.ambiguous-property"
    )
    assert first_message == second_message


def test_cross_domain_relationship_target_diagnostic_names_external_domain(tmp_path):
    ontology = """
        @prefix party: <https://example.test/party#> .
        @prefix inv: <https://example.test/invoice#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
        party:Organisation a owl:Class ; rdfs:label "Organisation" .
        inv:Invoice a owl:Class ; rdfs:label "Invoice" .
        party:orgId a owl:DatatypeProperty ;
          rdfs:domain party:Organisation ; rdfs:range xsd:string .
        party:hasInvoice a owl:ObjectProperty ;
          rdfs:domain party:Organisation ; rdfs:range inv:Invoice .
    """
    binding = """
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
          - property: party:hasInvoice
            target: inv:Invoice
            join: [{local: org_id, foreign: org_id}]
            cardinality: many-to-one
            mode: non-temporal
            missingParent: error
            ambiguousParent: error
    """
    hub = _hub(tmp_path, ontology=ontology, binding=binding)
    (hub / "integration" / "bindings" / "invoice.binding.yaml").write_text(
        textwrap.dedent("""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: crm-invoice
              domain: invoice
            source:
              relation: crm.organisations
            target:
              class: inv:Invoice
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
        """).strip(),
        encoding="utf-8",
    )

    result = compile_domain(hub, "party")

    diagnostic = next(
        item for item in result.diagnostics.items if item.code == "safety.relationship-endpoint"
    )
    assert "bound in domain 'invoice'" in diagnostic.message
    assert "outside this domain's compile scope" in diagnostic.message
    assert "external reference" in diagnostic.message


def test_unmaterialized_relationship_join_column_message_is_actionable(tmp_path):
    ontology = """
        @prefix party: <https://example.test/party#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
        party:Organisation a owl:Class ; rdfs:label "Organisation" .
        party:orgId a owl:DatatypeProperty ;
          rdfs:domain party:Organisation ; rdfs:range xsd:string .
        party:Location a owl:Class ; rdfs:label "Location" .
        party:locationId a owl:DatatypeProperty ;
          rdfs:domain party:Location ; rdfs:range xsd:string .
        party:parentLocation a owl:ObjectProperty ;
          rdfs:domain party:Organisation ; rdfs:range party:Location .
    """
    binding = """
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
          - property: party:parentLocation
            target: party:Location
            join: [{local: parent_id, foreign: location_id}]
            cardinality: many-to-one
            mode: non-temporal
            missingParent: error
            ambiguousParent: error
    """
    hub = _hub(tmp_path, ontology=ontology, binding=binding)
    source = hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl"
    source.write_text(
        source.read_text(encoding="utf-8")
        + textwrap.dedent("""

            src:parent a kb:SourceColumn ; kb:sourceTable src:orgs ;
              kb:columnName "parent_id" ; kb:dataType "varchar(50)" ;
              kb:nullable "true"^^xsd:boolean .
            src:locations a kb:SourceTable ; kb:sourceSystem src:crm ;
              kb:tableName "locations" ; kb:primaryKeyColumns "location_id" .
            src:locationid a kb:SourceColumn ; kb:sourceTable src:locations ;
              kb:columnName "location_id" ; kb:dataType "varchar(50)" ;
              kb:nullable "false"^^xsd:boolean .
        """),
        encoding="utf-8",
    )
    # #334: the parent must be a *different* class -- a self-referential relationship is now
    # rejected outright (``relationship.self-reference-unsupported``), which would mask the
    # unmaterialized-join-local-column message this test is about.
    (hub / "integration" / "bindings" / "location.binding.yaml").write_text(
        textwrap.dedent("""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: crm-location
              domain: party
            source:
              relation: crm.locations
            target:
              class: party:Location
            grain:
              columns: [location_id]
            identity:
              strategy: source-natural
              sourceKey: [location_id]
            load:
              mode: full-refresh
            fields:
              - property: party:locationId
                expression: location_id
        """).strip(),
        encoding="utf-8",
    )

    result = compile_domain(hub, "party")

    diagnostic = next(
        item for item in result.diagnostics.items if item.code == "safety.type-incompatible"
    )
    assert "RELATIONSHIP join local column" in diagnostic.message
    assert "fields:" in diagnostic.message
    assert "join column is materialized" in diagnostic.message
