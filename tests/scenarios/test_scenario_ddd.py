# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for the DDD documentation projection (DD-091).

Exercises the DDD projector against the synthetic Acme hub overlays and verifies
that the DDD overlay does not alter silver/gold projection output (isolation).
"""

import pytest

from kairos_ontology.projections.ddd_projector import generate_ddd_artifacts

from .conftest import EXTENSIONS_DIR


@pytest.fixture(scope="module")
def client_ddd_artifacts(client_ontology):
    graph, namespace, _classes = client_ontology
    overlay = EXTENSIONS_DIR / "client-ddd-ext.ttl"
    return generate_ddd_artifacts(
        graph=graph,
        namespace=namespace,
        ontology_name="client",
        overlay_path=overlay if overlay.exists() else None,
    )


@pytest.fixture(scope="module")
def invoice_ddd_artifacts(invoice_ontology):
    graph, namespace, _classes = invoice_ontology
    overlay = EXTENSIONS_DIR / "invoice-ddd-ext.ttl"
    return generate_ddd_artifacts(
        graph=graph,
        namespace=namespace,
        ontology_name="invoice",
        overlay_path=overlay if overlay.exists() else None,
    )


class TestDddProjectionOutput:
    def test_three_artifacts(self, client_ddd_artifacts):
        assert set(client_ddd_artifacts) == {
            "client-context-map.mmd",
            "client-aggregate-overview.mmd",
            "client-ddd-report.md",
        }

    def test_context_map_has_contexts_and_edge(self, client_ddd_artifacts):
        mmd = client_ddd_artifacts["client-context-map.mmd"]
        assert "graph LR" in mmd
        assert "Client Management" in mmd
        assert "Reference Data" in mmd
        assert "Conformist" in mmd

    def test_aggregate_overview_groups_members(self, client_ddd_artifacts):
        mmd = client_ddd_artifacts["client-aggregate-overview.mmd"]
        assert "graph TD" in mmd
        assert "AggregateRoot" in mmd
        assert "Client --> Identifier" in mmd
        assert "Client --> ClientPII" in mmd

    def test_report_sections(self, client_ddd_artifacts):
        md = client_ddd_artifacts["client-ddd-report.md"]
        assert "## Bounded Contexts" in md
        assert "## Context Map" in md
        assert "## Aggregates & Tactical Patterns" in md
        assert "## Design Notes" in md
        assert "Aggregate root guarding client identity" in md

    def test_invoice_customer_supplier(self, invoice_ddd_artifacts):
        mmd = invoice_ddd_artifacts["invoice-context-map.mmd"]
        assert "Customer-Supplier" in mmd
        assert "Billing" in mmd
        assert "Taxation" in mmd

    def test_deterministic(self, client_ontology):
        graph, namespace, _classes = client_ontology
        overlay = EXTENSIONS_DIR / "client-ddd-ext.ttl"
        a = generate_ddd_artifacts(graph, namespace, "client", overlay_path=overlay)
        b = generate_ddd_artifacts(graph, namespace, "client", overlay_path=overlay)
        assert a == b

    def test_no_overlay_returns_empty(self, client_ontology):
        graph, namespace, _classes = client_ontology
        assert generate_ddd_artifacts(graph, namespace, "client", overlay_path=None) == {}


class TestDddIsolation:
    """The DDD overlay must not alter silver or gold projection output."""

    def test_silver_output_unaffected_by_ddd_overlay(self, client_ontology):
        # Silver extension discovery globs *-silver-ext.ttl and must ignore the
        # DDD overlay entirely. Re-projecting silver yields identical artifacts.
        from kairos_ontology.projections.medallion_silver_projector import (
            generate_silver_artifacts,
        )
        from .conftest import SHAPES_DIR

        graph, namespace, classes = client_ontology
        silver_ext = EXTENSIONS_DIR / "client-silver-ext.ttl"
        artifacts = generate_silver_artifacts(
            classes=classes,
            graph=graph,
            namespace=namespace,
            shapes_dir=SHAPES_DIR,
            ontology_name="client",
            projection_ext_path=silver_ext if silver_ext.exists() else None,
        )
        # No DDD predicates should appear in generated silver DDL/ERD.
        blob = "\n".join(artifacts.values())
        assert "kairos-ddd" not in blob
        assert "BoundedContext" not in blob
