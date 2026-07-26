# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
from types import SimpleNamespace

from rdflib import Graph, OWL, RDF, RDFS, URIRef

from kairos_ontology.core.projections.dbt.bind import _active_source_inputs
from kairos_ontology.core.projections.dbt.mapping_specs import (
    ColumnMappingFact,
    SourceMappings,
    TableMappingFact,
)


def _table(uri: str, column_uri: str, *, relation_kind: str = "physical") -> dict:
    return {
        "uri": uri,
        "name": uri.rsplit("/", 1)[-1],
        "label": uri.rsplit("/", 1)[-1],
        "columns": [{"uri": column_uri, "name": "value"}],
        "relation_kind": relation_kind,
    }


def test_active_source_scope_excludes_unrelated_domain_and_keeps_contract_vocab():
    booking = "https://example.test/booking#Booking"
    party = "https://example.test/party#Party"
    booking_property = "https://example.test/booking#bookingName"
    party_property = "https://example.test/party#partyName"
    booking_table = "https://example.test/source/qargo/bookings"
    party_table = "https://example.test/source/crm/parties"
    virtual_table = "https://example.test/source/dbt/booking_enriched"
    booking_column = f"{booking_table}/name"
    party_column = f"{party_table}/name"
    virtual_column = f"{virtual_table}/name"

    graph = Graph()
    graph.add((URIRef(booking), RDF.type, OWL.Class))
    graph.add((URIRef(party), RDF.type, OWL.Class))
    graph.add((URIRef(booking_property), RDFS.domain, URIRef(booking)))
    graph.add((URIRef(party_property), RDFS.domain, URIRef(party)))
    systems = [
        {
            "system_uri": "urn:qargo",
            "system_label": "qargo",
            "tables": [_table(booking_table, booking_column)],
        },
        {
            "system_uri": "urn:crm",
            "system_label": "crm",
            "tables": [_table(party_table, party_column)],
        },
        {
            "system_uri": "urn:dbt",
            "system_label": "dbt",
            "tables": [
                _table(
                    virtual_table,
                    virtual_column,
                    relation_kind="contracted-virtual",
                )
            ],
        },
    ]
    mappings = SourceMappings(
        tables=(
            TableMappingFact("urn:map:booking", booking_table, booking, "direct", "exactMatch"),
            TableMappingFact("urn:map:party", party_table, party, "direct", "exactMatch"),
            TableMappingFact("urn:map:virtual", virtual_table, booking, "direct", "exactMatch"),
        ),
        columns=(
            ColumnMappingFact(
                "urn:map:booking-name",
                booking_column,
                booking_property,
                "exactMatch",
            ),
            ColumnMappingFact(
                "urn:map:party-name",
                party_column,
                party_property,
                "exactMatch",
            ),
        ),
    )
    contracts = {
        "booking_enriched": SimpleNamespace(
            name="booking_enriched",
            target_class=booking,
            virtual_source_iri=virtual_table,
            replaces_sources=(SimpleNamespace(table_iri=booking_table),),
        )
    }

    scoped_systems, scoped_mappings, scoped_contracts, scope = _active_source_inputs(
        systems=systems,
        mappings=mappings,
        contracts=contracts,
        class_uris={booking},
        graph=graph,
    )

    assert scope.table_uris == {booking_table, virtual_table}
    assert {table["uri"] for system in scoped_systems for table in system["tables"]} == {
        booking_table,
        virtual_table,
    }
    assert {item.resource_uri for item in scoped_mappings.tables} == {
        "urn:map:booking",
        "urn:map:virtual",
    }
    assert [item.resource_uri for item in scoped_mappings.columns] == [
        "urn:map:booking-name"
    ]
    assert set(scoped_contracts) == {"booking_enriched"}
    reasons = {item.table_uri: set(item.reasons) for item in scope.tables}
    assert reasons[booking_table] == {
        "domain-table-mapping:urn:map:booking",
        "contract-replacement-input:booking_enriched",
    }
    assert reasons[virtual_table] == {
        "domain-table-mapping:urn:map:virtual",
        "contract-virtual-source:booking_enriched",
    }
