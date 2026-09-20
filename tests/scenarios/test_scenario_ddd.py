# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for the DDD documentation projection (DD-091).

Exercises the DDD projector against the synthetic Acme hub overlays and verifies
that the DDD overlay does not alter silver/gold projection output (isolation).
"""

import pytest

from kairos_ontology.core.projections.ddd_projector import generate_ddd_artifacts

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
    """The invoice overlay references contexts declared hub-wide (DD-229)."""
    graph, namespace, _classes = invoice_ontology
    overlay = EXTENSIONS_DIR / "invoice-ddd-ext.ttl"
    return generate_ddd_artifacts(
        graph=graph,
        namespace=namespace,
        ontology_name="invoice",
        overlay_path=overlay if overlay.exists() else None,
        strategic_path=EXTENSIONS_DIR / "ddd-contexts-ext.ttl",
    )


class TestDddProjectionOutput:
    def test_two_per_domain_artifacts(self, client_ddd_artifacts):
        """The per-domain context map is retired (DD-230): the hub-wide one under
        `contexts/` replaces it, drawn by `ddd_context_projector`."""
        assert set(client_ddd_artifacts) == {
            "client-aggregate-overview.mmd",
            "client-ddd-report.md",
        }

    def test_report_points_at_the_hub_wide_map(self, client_ddd_artifacts):
        md = client_ddd_artifacts["client-ddd-report.md"]
        assert "contexts/context-map.mmd" in md
        assert "| Client Management | Conformist | Reference Data |" in md

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

    def test_invoice_report_carries_subdomain_and_invariants(self, invoice_ddd_artifacts):
        md = invoice_ddd_artifacts["invoice-ddd-report.md"]
        assert "| Billing | Core Domain | yes |" in md
        assert "| Taxation | Generic Subdomain |" in md
        assert "## Invariants" in md
        assert "- **Invoice:** An invoice total equals the sum of its line amounts." in md
        assert "| Billing | Customer-Supplier | Taxation |" in md

    def test_client_report_lists_only_its_own_contexts(self, client_ontology):
        """With the strategic file merged, the client report must not list Billing/Taxation."""
        graph, namespace, _classes = client_ontology
        artifacts = generate_ddd_artifacts(
            graph,
            namespace,
            "client",
            overlay_path=EXTENSIONS_DIR / "client-ddd-ext.ttl",
            strategic_path=EXTENSIONS_DIR / "ddd-contexts-ext.ttl",
        )
        md = artifacts["client-ddd-report.md"]
        assert "Client Management" in md and "Reference Data" in md
        assert "| Billing |" not in md and "| Taxation |" not in md
        assert "2 other bounded context(s) are declared hub-wide" in md

    def test_strategic_file_alone_yields_nothing_for_a_domain(self, client_ontology):
        graph, namespace, _classes = client_ontology
        assert (
            generate_ddd_artifacts(
                graph,
                namespace,
                "client",
                overlay_path=None,
                strategic_path=EXTENSIONS_DIR / "ddd-contexts-ext.ttl",
            )
            == {}
        )

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

    def test_silver_output_unaffected_by_ddd_overlay(self, client_dbt_artifacts):
        artifacts = client_dbt_artifacts
        # No DDD predicates should appear in generated silver DDL/ERD.
        blob = "\n".join(value for value in artifacts.values() if isinstance(value, str))
        assert "kairos-ddd" not in blob
        assert "BoundedContext" not in blob
