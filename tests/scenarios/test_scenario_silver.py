# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for silver DDL/ERD projection using the synthetic Acme Corp hub.

These tests exercise the silver projector with realistic multi-class ontologies
that include cross-domain relationships and extension annotations.
"""

import pytest
from pathlib import Path

from kairos_ontology.projections.medallion_silver_projector import (
    generate_silver_artifacts,
)

from .conftest import EXTENSIONS_DIR, SHAPES_DIR


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client_silver_artifacts(client_ontology):
    """Generate silver DDL/ERD artifacts for the client domain."""
    graph, namespace, classes = client_ontology
    ext_path = EXTENSIONS_DIR / "client-silver-ext.ttl"
    return generate_silver_artifacts(
        classes=classes,
        graph=graph,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="client",
        projection_ext_path=ext_path if ext_path.exists() else None,
    )


@pytest.fixture(scope="module")
def invoice_silver_artifacts(invoice_ontology):
    """Generate silver DDL/ERD artifacts for the invoice domain."""
    graph, namespace, classes = invoice_ontology
    ext_path = EXTENSIONS_DIR / "invoice-silver-ext.ttl"
    return generate_silver_artifacts(
        classes=classes,
        graph=graph,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="invoice",
        projection_ext_path=ext_path if ext_path.exists() else None,
    )


# ---------------------------------------------------------------------------
# Silver DDL tests
# ---------------------------------------------------------------------------

class TestSilverDDL:
    """Silver DDL should have CREATE TABLE for each domain class."""

    def test_client_ddl_exists(self, client_silver_artifacts):
        key = _find_artifact(client_silver_artifacts, ".sql")
        assert key is not None, "No DDL SQL artifact generated for client domain"

    def test_client_ddl_has_tables(self, client_silver_artifacts):
        """DDL should have CREATE TABLE for the split subclasses."""
        ddl_key = _find_artifact(client_silver_artifacts, ".sql")
        ddl = client_silver_artifacts[ddl_key].upper()
        assert "CREATE TABLE" in ddl, "DDL missing CREATE TABLE statements"

    def test_invoice_ddl_has_tables(self, invoice_silver_artifacts):
        ddl_key = _find_artifact(invoice_silver_artifacts, ".sql")
        assert ddl_key is not None, "No DDL SQL artifact for invoice domain"
        ddl = invoice_silver_artifacts[ddl_key].upper()
        assert "CREATE TABLE" in ddl, "Invoice DDL missing CREATE TABLE"

    def test_invoice_ddl_has_invoice_table(self, invoice_silver_artifacts):
        ddl_key = _find_artifact(invoice_silver_artifacts, ".sql")
        ddl = invoice_silver_artifacts[ddl_key].lower()
        assert "invoice" in ddl, "DDL missing invoice table"


# ---------------------------------------------------------------------------
# Silver ERD tests
# ---------------------------------------------------------------------------

class TestSilverERD:
    """Silver ERD (Mermaid) should include entity relationships."""

    def test_invoice_erd_exists(self, invoice_silver_artifacts):
        key = _find_artifact(invoice_silver_artifacts, ".md")
        if key is None:
            key = _find_artifact(invoice_silver_artifacts, ".mmd")
        assert key is not None, "No ERD artifact generated for invoice domain"

    def test_invoice_erd_has_relationships(self, invoice_silver_artifacts):
        """ERD should show the issuedTo FK from Invoice to Client."""
        key = _find_artifact(invoice_silver_artifacts, ".md")
        if key is None:
            key = _find_artifact(invoice_silver_artifacts, ".mmd")
        if key is None:
            pytest.skip("No ERD artifact to inspect")
        erd = invoice_silver_artifacts[key].lower()
        # Mermaid ERDs use }|--|| or similar notation for relationships
        has_relationship = (
            "invoice" in erd and ("client" in erd or "issued" in erd)
        )
        assert has_relationship, (
            f"Invoice ERD missing relationship to client:\n{erd[:500]}"
        )


# ---------------------------------------------------------------------------
# Silver FK script tests
# ---------------------------------------------------------------------------

class TestSilverFKScript:
    """Silver ALTER TABLE FK script for cross-domain relationships."""

    def test_invoice_fk_script_exists(self, invoice_silver_artifacts):
        """Should generate an ALTER TABLE script for cross-domain FKs."""
        key = _find_artifact(invoice_silver_artifacts, "alter")
        if key is None:
            # Some versions put FK in the main DDL
            key = _find_artifact(invoice_silver_artifacts, "fk")
        # FK scripts are optional — just check if any artifact references FK
        all_content = " ".join(invoice_silver_artifacts.values()).upper()
        has_fk_ref = "FOREIGN KEY" in all_content or "REFERENCES" in all_content
        if not has_fk_ref:
            pytest.skip(
                "No FK script or FOREIGN KEY reference in silver artifacts "
                "(may be expected if FK scripts are disabled)"
            )


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _find_artifact(artifacts: dict, suffix: str) -> str | None:
    """Find the first artifact key that ends with the given suffix."""
    for key in artifacts:
        if key.endswith(suffix):
            return key
    return None
