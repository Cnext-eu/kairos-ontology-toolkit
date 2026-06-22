# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Builders for a minimal, self-contained reference-models root used by archetype tests.

These fixtures avoid any dependency on a live ``kairos-ontology-referencemodels`` checkout
(the contract requires CI to run offline against bundled fixtures — DD-090).
"""

from __future__ import annotations

import json
from pathlib import Path

# Two tiny ontology modules exercising ObjectProperty domain/range + cardinality.
_BOOKING_TTL = """@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/ont/booking#> .

<https://example.org/ont/booking> a owl:Ontology ;
    owl:versionInfo "1.2.0" .

ex:Booking a owl:Class ;
    rdfs:label "Booking" ;
    rdfs:subClassOf [ a owl:Restriction ;
        owl:onProperty ex:hasCargoItem ;
        owl:minCardinality 1 ] ,
        [ a owl:Restriction ;
        owl:onProperty ex:hasBookingParty ;
        owl:maxCardinality 1 ] .

ex:CargoItem a owl:Class ;
    rdfs:label "Cargo Item" .

ex:hasCargoItem a owl:ObjectProperty ;
    rdfs:label "has cargo item" ;
    rdfs:domain ex:Booking ;
    rdfs:range ex:CargoItem .

ex:hasBookingParty a owl:ObjectProperty , owl:FunctionalProperty ;
    rdfs:label "has booking party" ;
    rdfs:domain ex:Booking ;
    rdfs:range <https://example.org/ont/party#BookingParty> .
"""

_PARTY_TTL = """@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <https://example.org/ont/party#> .

<https://example.org/ont/party> a owl:Ontology ;
    owl:versionInfo "1.0.0" .

ex:BookingParty a owl:Class ;
    rdfs:label "Booking Party" .
"""

_CATALOG_XML = """<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog" prefer="public">
  <uri name="https://example.org/ont/booking" uri="modules/booking.ttl"/>
  <uri name="https://example.org/ont/party" uri="modules/party.ttl"/>
</catalog>
"""

_OUTCOME_CODES_YAML = """schema_version: 1
codes:
  - conforms
  - conforms-with-rename
  - partial
  - deviates
  - not-applicable
"""

# A faithful (compact) copy of the shipped archetype JSON Schema (additionalProperties: false).
_ARCHETYPE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Kairos Archetype Catalog (v1)",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version", "id", "label", "description",
        "compatible_with", "ref_model_modules", "core_concepts",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "id": {"type": "string", "pattern": "^[a-z][a-z0-9]*(-[a-z0-9]+)*$"},
        "label": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 1},
        "compatible_with": {
            "type": "object",
            "additionalProperties": False,
            "required": ["repo_tag_range"],
            "properties": {
                "repo_tag_range": {"type": "string", "minLength": 1},
                "ontology_versions": {"type": "object"},
            },
        },
        "ref_model_modules": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["iri", "tier"],
                "properties": {
                    "iri": {"type": "string", "pattern": "^https?://"},
                    "tier": {"$ref": "#/$defs/tier"},
                },
            },
        },
        "core_concepts": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["uri", "tier", "label"],
                "properties": {
                    "uri": {"type": "string", "pattern": "^https?://"},
                    "tier": {"$ref": "#/$defs/tier"},
                    "label": {"type": "string", "minLength": 1},
                },
            },
        },
    },
    "$defs": {"tier": {"type": "string", "enum": ["required", "recommended", "optional"]}},
}

_ARCHETYPE_YAML = """schema_version: 1
id: test-carrier
label: "Test carrier archetype"
description: "A minimal archetype for unit tests."
compatible_with:
  repo_tag_range: ">=1.0.0,<2.0.0"
  ontology_versions:
    booking: ">=1.0.0,<2"
ref_model_modules:
  - { iri: "https://example.org/ont/booking", tier: required }
  - { iri: "https://example.org/ont/party", tier: recommended }
core_concepts:
  - { uri: "https://example.org/ont/booking#Booking", tier: required, label: "Booking" }
  - { uri: "https://example.org/ont/booking#CargoItem", tier: required, label: "Cargo Item" }
  - { uri: "https://example.org/ont/party#BookingParty", tier: recommended, label: "Booking Party" }
  - { uri: "https://example.org/ont/booking#GhostConcept", tier: optional, label: "Ghost" }
"""

_DISCOVERY_MD = """# Test carrier — discovery interview

## 1. Commercial cycle
Maps to: Booking, CargoItem

## Structural & lifecycle relationships
How many cargo items per booking?
"""


def build_refmodels_root(tmp_path: Path, *, repo_version: str = "1.11.0",
                         add_duplicate_discovery: bool = False) -> Path:
    """Create a minimal reference-models root under *tmp_path* and return the inner root.

    Layout mirrors the real repo: an outer repo dir containing ``ontology-reference-models/``
    (so :func:`normalize_refmodels_root` resolves either level) and a ``VERSION`` file.
    """
    repo = tmp_path / "refmodels-repo"
    inner = repo / "ontology-reference-models"
    (repo / "VERSION").parent.mkdir(parents=True, exist_ok=True)
    (repo / "VERSION").write_text(repo_version + "\n", encoding="utf-8")

    archetypes = inner / "blueprints" / "archetypes"
    schema_dir = archetypes / "_schema"
    modules = inner / "modules"
    discovery = inner / "accelerator-packs" / "logistics" / "discovery"
    for d in (archetypes, schema_dir, modules, discovery):
        d.mkdir(parents=True, exist_ok=True)

    (inner / "catalog-v001.xml").write_text(_CATALOG_XML, encoding="utf-8")
    (modules / "booking.ttl").write_text(_BOOKING_TTL, encoding="utf-8")
    (modules / "party.ttl").write_text(_PARTY_TTL, encoding="utf-8")
    (archetypes / "test-carrier.yaml").write_text(_ARCHETYPE_YAML, encoding="utf-8")
    (schema_dir / "archetype.schema.json").write_text(
        json.dumps(_ARCHETYPE_SCHEMA), encoding="utf-8")
    (schema_dir / "outcome-codes.yaml").write_text(_OUTCOME_CODES_YAML, encoding="utf-8")
    # Excluded-from-glob noise files (contract row 5).
    (archetypes / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    (archetypes / "README.md").write_text("# archetypes\n", encoding="utf-8")
    (discovery / "test-carrier.md").write_text(_DISCOVERY_MD, encoding="utf-8")

    if add_duplicate_discovery:
        dup = inner / "accelerator-packs" / "financial-services" / "discovery"
        dup.mkdir(parents=True, exist_ok=True)
        (dup / "test-carrier.md").write_text(_DISCOVERY_MD, encoding="utf-8")

    return inner
