# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for dbt projection using the synthetic Acme Corp ontology hub.

These tests exercise the full dbt artifact generation pipeline with realistic
multi-domain, multi-source data — including split patterns, cross-domain FKs,
deduplication, default values, and SHACL-derived tests.
"""

import pytest


# ---------------------------------------------------------------------------
# Split pattern tests — tblClient → 3 subclasses by Type discriminator
# ---------------------------------------------------------------------------

class TestSplitPattern:
    """Each split model must have its own WHERE clause with the correct filter."""

    def test_corporate_has_type_0_filter(self, client_dbt_artifacts):
        key = _find_artifact(client_dbt_artifacts, "corporate_client.sql")
        sql = client_dbt_artifacts[key]
        assert "Type = 0" in sql or "type = 0" in sql.lower(), (
            f"CorporateClient model missing 'Type = 0' filter:\n{sql}"
        )

    def test_sole_proprietor_has_type_1_filter(self, client_dbt_artifacts):
        key = _find_artifact(client_dbt_artifacts, "sole_proprietor_client.sql")
        sql = client_dbt_artifacts[key]
        assert "Type = 1" in sql or "type = 1" in sql.lower(), (
            f"SoleProprietorClient model missing 'Type = 1' filter:\n{sql}"
        )

    def test_individual_has_type_2_filter(self, client_dbt_artifacts):
        key = _find_artifact(client_dbt_artifacts, "individual_client.sql")
        sql = client_dbt_artifacts[key]
        assert "Type = 2" in sql or "type = 2" in sql.lower(), (
            f"IndividualClient model missing 'Type = 2' filter:\n{sql}"
        )

    def test_no_cross_contamination(self, client_dbt_artifacts):
        """Sole proprietor model must NOT contain type=0 (corporate's filter)."""
        key = _find_artifact(client_dbt_artifacts, "sole_proprietor_client.sql")
        sql = client_dbt_artifacts[key].lower()
        assert "type = 0" not in sql, (
            "SoleProprietorClient incorrectly contains type=0 filter"
        )


# ---------------------------------------------------------------------------
# Cross-domain FK tests — Invoice.issuedTo → Client
# ---------------------------------------------------------------------------

class TestCrossDomainFK:
    """Invoice model should generate a join to resolve the client FK."""

    def test_invoice_model_exists(self, invoice_dbt_artifacts):
        key = _find_artifact(invoice_dbt_artifacts, "invoice.sql")
        assert key is not None, "invoice.sql artifact not generated"

    def test_invoice_references_client(self, invoice_dbt_artifacts):
        """The invoice SQL should reference client for FK resolution."""
        key = _find_artifact(invoice_dbt_artifacts, "invoice.sql")
        sql = invoice_dbt_artifacts[key].lower()
        # Should have either a join to client or a client_sk column
        has_join = "join" in sql and "client" in sql
        has_sk = "client_sk" in sql or "issued_to_sk" in sql
        assert has_join or has_sk, (
            f"Invoice model missing cross-domain FK to client:\n{sql}"
        )


# ---------------------------------------------------------------------------
# Default value tests — email column has defaultValue
# ---------------------------------------------------------------------------

class TestDefaultValues:
    """Columns with kairos-map:defaultValue should use COALESCE or fallback.

    NOTE: This is a known gap — the dbt projector does not yet apply
    kairos-map:defaultValue as COALESCE in generated SQL. This test documents
    the expected behaviour and will start passing when the feature is added.
    """

    @pytest.mark.xfail(reason="defaultValue not yet applied in dbt projector")
    def test_email_has_default(self, client_dbt_artifacts):
        """Email mapping has defaultValue 'unknown@acme.example'."""
        # Check any of the split models — they all map email
        key = _find_artifact(client_dbt_artifacts, "corporate_client.sql")
        sql = client_dbt_artifacts[key]
        has_coalesce = "COALESCE" in sql.upper() or "coalesce" in sql
        has_default = "unknown@acme.example" in sql
        assert has_coalesce or has_default, (
            f"Email column missing default value handling:\n{sql}"
        )


# ---------------------------------------------------------------------------
# Sources YAML tests — both source systems should appear
# ---------------------------------------------------------------------------

class TestSourcesYaml:
    """The _sources.yml should declare bronze source systems."""

    def test_sources_yaml_generated(self, client_dbt_artifacts):
        key = _find_artifact(client_dbt_artifacts, "_sources.yml")
        assert key is not None, "_sources.yml not generated for client domain"

    def test_sources_contains_adminpulse(self, client_dbt_artifacts):
        key = _find_artifact(client_dbt_artifacts, "_sources.yml")
        content = client_dbt_artifacts[key].lower()
        assert "adminpulse" in content, (
            "_sources.yml missing AdminPulse source system"
        )


# ---------------------------------------------------------------------------
# Schema YAML tests — SHACL-derived dbt tests
# ---------------------------------------------------------------------------

class TestSchemaYaml:
    """Schema YAML should include tests from SHACL shapes."""

    def test_schema_yaml_generated(self, client_dbt_artifacts):
        key = _find_artifact(client_dbt_artifacts, "_models.yml")
        assert key is not None, "_models.yml not generated for client domain"

    def test_not_null_on_required_columns(self, client_dbt_artifacts):
        """clientId has sh:minCount 1 → should generate not_null test."""
        key = _find_artifact(client_dbt_artifacts, "_models.yml")
        content = client_dbt_artifacts[key]
        assert "not_null" in content, (
            "Schema YAML missing not_null test for required columns"
        )


# ---------------------------------------------------------------------------
# Multi-model generation — all expected models created
# ---------------------------------------------------------------------------

class TestMultiModelGeneration:
    """All domain classes should produce dbt model artifacts."""

    def test_all_client_models_generated(self, client_dbt_artifacts):
        """Should have models for all 3 split subclasses."""
        sql_keys = [k for k in client_dbt_artifacts if k.endswith(".sql")]
        model_names = {k.split("/")[-1].replace(".sql", "") for k in sql_keys}

        assert "corporate_client" in model_names, "Missing corporate_client model"
        assert "sole_proprietor_client" in model_names, (
            "Missing sole_proprietor_client model"
        )
        assert "individual_client" in model_names, "Missing individual_client model"

    def test_invoice_models_generated(self, invoice_dbt_artifacts):
        """Should have models for Invoice and InvoiceLine."""
        sql_keys = [k for k in invoice_dbt_artifacts if k.endswith(".sql")]
        model_names = {k.split("/")[-1].replace(".sql", "") for k in sql_keys}

        assert "invoice" in model_names, "Missing invoice model"
        assert "invoice_line" in model_names, "Missing invoice_line model"


# ---------------------------------------------------------------------------
# Column mapping tests — transforms applied correctly
# ---------------------------------------------------------------------------

class TestColumnMappings:
    """Column-level transforms should appear in the generated SQL."""

    def test_mapped_columns_present(self, client_dbt_artifacts):
        """Mapped columns (e.g. vat_number) should appear in the SELECT."""
        key = _find_artifact(client_dbt_artifacts, "corporate_client.sql")
        sql = client_dbt_artifacts[key].lower()
        assert "vat_number" in sql, "Missing vat_number mapped column"

    @pytest.mark.xfail(
        reason="dbt projector uses raw column names; CAST transforms "
               "from kairos-map:transform not yet emitted in SQL"
    )
    def test_cast_transform_applied(self, client_dbt_artifacts):
        """clientId mapping has CAST(source.ClientID AS STRING)."""
        key = _find_artifact(client_dbt_artifacts, "corporate_client.sql")
        sql = client_dbt_artifacts[key].upper()
        assert "CAST" in sql and "STRING" in sql, (
            "Missing CAST transform in corporate_client model"
        )


# ---------------------------------------------------------------------------
# Reference data tests — ClientType isReferenceData
# ---------------------------------------------------------------------------

class TestReferenceData:
    """Reference data classes (isReferenceData=true) should produce models."""

    def test_client_type_model_generated(self, client_dbt_artifacts):
        """ClientType with isReferenceData=true should still get a dbt model."""
        sql_keys = [k for k in client_dbt_artifacts if k.endswith(".sql")]
        model_names = {k.split("/")[-1].replace(".sql", "") for k in sql_keys}
        assert "client_type" in model_names, (
            "Missing client_type model for reference data class"
        )

    def test_invoice_tag_model_generated(self, invoice_dbt_artifacts):
        """InvoiceTag with isReferenceData=true should produce a dbt model."""
        sql_keys = [k for k in invoice_dbt_artifacts if k.endswith(".sql")]
        model_names = {k.split("/")[-1].replace(".sql", "") for k in sql_keys}
        assert "invoice_tag" in model_names, (
            "Missing invoice_tag model for reference data class"
        )


# ---------------------------------------------------------------------------
# GDPR satellite tests — ClientPII gdprSatelliteOf
# ---------------------------------------------------------------------------

class TestGDPRSatellite:
    """ClientPII marked as gdprSatelliteOf=Client should produce a model."""

    def test_client_pii_model_generated(self, client_dbt_artifacts):
        """GDPR satellite should get its own dbt model."""
        sql_keys = [k for k in client_dbt_artifacts if k.endswith(".sql")]
        model_names = {k.split("/")[-1].replace(".sql", "") for k in sql_keys}
        assert "client_pii" in model_names, (
            "Missing client_pii model for GDPR satellite"
        )


# ---------------------------------------------------------------------------
# Derived formula tests — lineTotal derivationFormula
# ---------------------------------------------------------------------------

class TestDerivedFormula:
    """Properties with derivationFormula should appear in generated SQL."""

    def test_line_total_derived(self, invoice_dbt_artifacts):
        """lineTotal = Quantity * UnitPrice should appear as expression."""
        key = _find_artifact(invoice_dbt_artifacts, "invoice_line.sql")
        sql = invoice_dbt_artifacts[key].lower()
        assert "quantity" in sql and "unitprice" in sql, (
            f"lineTotal derived expression missing from invoice_line SQL:\n{sql}"
        )


# ---------------------------------------------------------------------------
# Junction table tests — hasTag junctionTableName
# ---------------------------------------------------------------------------

class TestJunctionTable:
    """Many-to-many properties with junctionTableName should be handled."""

    def test_has_tag_not_in_invoice_columns(self, invoice_dbt_artifacts):
        """hasTag (M:N object property) should NOT appear as a column in invoice.sql."""
        key = _find_artifact(invoice_dbt_artifacts, "invoice.sql")
        if key is None:
            pytest.skip("No invoice.sql generated")
        sql = invoice_dbt_artifacts[key].lower()
        assert "has_tag" not in sql, (
            "Junction table property hasTag should not appear as a column in invoice.sql"
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
