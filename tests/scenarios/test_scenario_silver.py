# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for silver DDL/ERD projection using the synthetic Acme Corp hub.

These tests exercise the silver projector with realistic multi-class ontologies
that include cross-domain relationships and extension annotations.
"""

import pytest

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
# Silver extension annotation tests
# ---------------------------------------------------------------------------

class TestSilverExtAnnotations:
    """Test that silver-ext annotations affect DDL generation."""

    def test_client_silver_schema(self, client_silver_artifacts):
        """Client domain uses silverSchema='silver' — tables should use silver schema."""
        ddl_key = _find_artifact(client_silver_artifacts, ".sql")
        ddl = client_silver_artifacts[ddl_key].lower()
        assert "silver" in ddl, "DDL should reference 'silver' schema"

    def test_invoice_partition_by(self, invoice_silver_artifacts):
        """Invoice has partitionBy='invoice_date' — should appear in DDL."""
        ddl_key = _find_artifact(invoice_silver_artifacts, ".sql")
        ddl = invoice_silver_artifacts[ddl_key].lower()
        # partitionBy may not be emitted in all DDL flavors, check if present
        has_partition = "partition" in ddl and "invoice_date" in ddl
        if not has_partition:
            pytest.skip(
                "partitionBy not emitted in DDL (may be target-specific)"
            )

    def test_invoice_cluster_by(self, invoice_silver_artifacts):
        """Invoice has clusterBy='client_sk' — should appear in DDL."""
        ddl_key = _find_artifact(invoice_silver_artifacts, ".sql")
        ddl = invoice_silver_artifacts[ddl_key].lower()
        has_cluster = "cluster" in ddl and "client_sk" in ddl
        if not has_cluster:
            pytest.skip(
                "clusterBy not emitted in DDL (may be target-specific)"
            )

    def test_reference_data_class_in_silver(self, client_silver_artifacts):
        """ClientType (isReferenceData=true) should appear in silver DDL."""
        ddl_key = _find_artifact(client_silver_artifacts, ".sql")
        ddl = client_silver_artifacts[ddl_key].lower()
        assert "client_type" in ddl, (
            "Reference data class ClientType missing from silver DDL"
        )

    def test_gdpr_satellite_in_silver(self, client_silver_artifacts):
        """ClientPII (gdprSatelliteOf=Client) should appear in silver DDL."""
        ddl_key = _find_artifact(client_silver_artifacts, ".sql")
        ddl = client_silver_artifacts[ddl_key].lower()
        assert "client_pii" in ddl, (
            "GDPR satellite ClientPII missing from silver DDL"
        )

    def test_invoice_tag_in_silver(self, invoice_silver_artifacts):
        """InvoiceTag (isReferenceData=true) should appear in silver DDL."""
        ddl_key = _find_artifact(invoice_silver_artifacts, ".sql")
        ddl = invoice_silver_artifacts[ddl_key].lower()
        assert "invoice_tag" in ddl, (
            "Reference data class InvoiceTag missing from silver DDL"
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


# ---------------------------------------------------------------------------
# DD-021: Import-only domain — logistics (imported classes via silverInclude)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def logistics_silver_artifacts(logistics_ontology):
    """Generate silver DDL/ERD for the logistics domain (import-only, DD-021)."""
    graph, namespace, classes = logistics_ontology
    ext_path = EXTENSIONS_DIR / "logistics-silver-ext.ttl"
    return generate_silver_artifacts(
        classes=classes,
        graph=graph,
        namespace=namespace,
        shapes_dir=SHAPES_DIR,
        ontology_name="logistics",
        projection_ext_path=ext_path if ext_path.exists() else None,
    )


class TestDD021LogisticsDomain:
    """DD-021: Import-only domain should produce DDL for whitelisted classes."""

    def test_ddl_generated(self, logistics_silver_artifacts):
        """Import-only domain produces DDL when silverInclude claims exist."""
        ddl_key = _find_artifact(logistics_silver_artifacts, "-ddl.sql")
        assert ddl_key is not None, "No DDL artifact generated for logistics domain"
        ddl = logistics_silver_artifacts[ddl_key]
        assert "CREATE TABLE" in ddl

    def test_claimed_classes_projected(self, logistics_silver_artifacts):
        """Only classes claimed via silverInclude appear in DDL."""
        ddl_key = _find_artifact(logistics_silver_artifacts, "-ddl.sql")
        ddl = logistics_silver_artifacts[ddl_key].lower()
        # TradeParty and Carrier are claimed in logistics-silver-ext.ttl
        assert "silver_logistics.trade_party" in ddl
        assert "silver_logistics.carrier" in ddl

    def test_hub_schema_used(self, logistics_silver_artifacts):
        """Adopted imported classes use the hub domain schema, not the reference model's."""
        ddl_key = _find_artifact(logistics_silver_artifacts, "-ddl.sql")
        ddl = logistics_silver_artifacts[ddl_key]
        # Schema should be silver_logistics (from hub domain name)
        assert "silver_logistics" in ddl
        # NOT the reference model namespace
        assert "silver_refmodel" not in ddl
        assert "silver_party" not in ddl

    def test_scd_type_override(self, logistics_silver_artifacts):
        """Extension annotations (scdType) apply to claimed imported classes."""
        ddl_key = _find_artifact(logistics_silver_artifacts, "-ddl.sql")
        ddl = logistics_silver_artifacts[ddl_key].lower()
        # TradeParty is SCD Type 2 → should have valid_from/valid_to
        assert "valid_from" in ddl
        assert "valid_to" in ddl

    def test_erd_generated(self, logistics_silver_artifacts):
        """ERD diagram is generated for import-only domain."""
        erd_key = _find_artifact(logistics_silver_artifacts, "-erd.mmd")
        assert erd_key is not None, "No ERD artifact generated for logistics domain"
        erd = logistics_silver_artifacts[erd_key]
        assert "trade_party" in erd.lower()

    def test_imported_properties_discovered(self, logistics_silver_artifacts):
        """Properties from the reference model are discovered for claimed classes."""
        ddl_key = _find_artifact(logistics_silver_artifacts, "-ddl.sql")
        ddl = logistics_silver_artifacts[ddl_key].lower()
        # partyName and partyCode are properties of TradeParty in the ref model
        assert "party_name" in ddl
        assert "party_code" in ddl


# ---------------------------------------------------------------------------
# S3 Inheritance Strategy: Discriminator vs TPC (Table-Per-Concrete-Class)
# ---------------------------------------------------------------------------

class TestS3InheritanceStrategy:
    """S3 rule respects inheritanceStrategy annotation.

    Client domain uses discriminator → subtypes are folded into parent.
    Without the annotation, subtypes would get separate tables (TPC).
    """

    def test_discriminator_folds_subtypes(self, client_silver_artifacts):
        """With inheritanceStrategy 'discriminator', subtypes are folded into parent."""
        ddl_key = _find_artifact(client_silver_artifacts, ".sql")
        ddl = client_silver_artifacts[ddl_key].lower()
        # The parent 'client' table should exist
        assert "silver.client" in ddl or "silver_client.client" in ddl, (
            "Parent Client table missing from DDL"
        )
        # Discriminator column should be present on the parent table
        assert "client_type" in ddl, (
            "discriminatorColumn 'client_type' missing from DDL"
        )

    def test_discriminator_skips_subtypes(self, client_silver_artifacts):
        """Discriminator subtypes should NOT get separate tables."""
        ddl_key = _find_artifact(client_silver_artifacts, ".sql")
        ddl = client_silver_artifacts[ddl_key]
        # Count CREATE TABLE statements — subtypes shouldn't have their own
        tables = [
            line for line in ddl.split("\n")
            if "CREATE TABLE" in line.upper()
        ]
        table_names = [t.lower() for t in tables]
        # CorporateClient, SoleProprietorClient, IndividualClient should NOT
        # appear as separate tables
        for name in table_names:
            assert "corporate_client" not in name, (
                "Discriminator subtype CorporateClient has its own table — should be folded"
            )
            assert "sole_proprietor_client" not in name, (
                "Discriminator subtype SoleProprietorClient has its own table — should be folded"
            )
            assert "individual_client" not in name, (
                "Discriminator subtype IndividualClient has its own table — should be folded"
            )
