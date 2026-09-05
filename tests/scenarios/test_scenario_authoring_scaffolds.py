# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for authoring from the complete ACME hub evidence."""

from __future__ import annotations

from pathlib import Path

from kairos_ontology.core.authoring_scaffolds import build_mapping_scaffold
from kairos_ontology.core.projections.dbt.mapping_bind import bind_mapping_graph


def test_acme_physical_source_mapping_preview_is_valid_and_unapproved() -> None:
    hub = Path(__file__).parent / "acme-hub"
    scaffold = build_mapping_scaffold(
        source_root=hub / "integration" / "sources",
        ontology_path=hub / "model" / "ontologies" / "client.ttl",
        source_table_uri="https://acme.example/bronze/crmsystem#Customers",
        target_class_uri="https://acme.example/ontology/client#CorporateClient",
        catalog_path=hub / "catalog-v001.xml",
    )

    assert scaffold.validation["passed"] is True
    assert scaffold.proposals >= 1
    assert bind_mapping_graph(scaffold.graph).tables == ()
    assert len(bind_mapping_graph(scaffold.graph, include_proposals=True).tables) == 1
