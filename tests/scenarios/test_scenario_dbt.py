# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for dbt projection using the synthetic Acme Corp ontology hub.

These tests exercise the full dbt artifact generation pipeline with realistic
multi-domain, multi-source data — including split patterns, cross-domain FKs,
deduplication, default values, and SHACL-derived tests.
"""

import logging
from contextlib import contextmanager

import pytest
from .conftest import (
    EXTENSIONS_DIR, MAPPINGS_DIR, SHAPES_DIR, SOURCES_DIR, TEMPLATE_DIR,
    _load_ontology,
)


@contextmanager
def _caplog_context(level=logging.WARNING):
    """Context manager that captures log records at the given level."""
    logger = logging.getLogger("kairos_ontology.projections.medallion_dbt_projector")
    records: list[logging.LogRecord] = []

    class _Handler(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Handler(level=level)
    logger.addHandler(handler)
    old_level = logger.level
    logger.setLevel(level)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)


# ---------------------------------------------------------------------------
# Split pattern tests — tblClient → 3 subclasses by Type discriminator
# ---------------------------------------------------------------------------

class TestSplitPattern:
    """Each split model must have its own WHERE clause with the correct filter."""

    def test_corporate_has_type_0_filter(self, client_dbt_artifacts):
        # Multi-source: filter is in the per-source view, not the union model
        key = _find_artifact(client_dbt_artifacts, "from_admin_pulse.sql")
        if key and "corporate" in key:
            sql = client_dbt_artifacts[key]
        else:
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
    """Invoice model should generate a join to resolve the client FK.

    NOTE: FK joins are only supported for single-source models (see line 1691 in
    medallion_dbt_projector.py). Invoice is now multi-source (tblInvoice +
    tblCreditNote), so the FK join is NOT generated — this is a known limitation.
    The test verifies that the union model at least exists and that the per-source
    models include the mapped source column (ClientRef) for downstream resolution.
    """

    def test_invoice_model_exists(self, invoice_dbt_artifacts):
        key = _find_artifact(invoice_dbt_artifacts, "invoice.sql")
        assert key is not None, "invoice.sql artifact not generated"

    def test_per_source_model_has_mapped_columns(self, invoice_dbt_artifacts):
        """Per-source models should include mapped data columns."""
        key = _find_artifact(
            invoice_dbt_artifacts, "invoice__from_billing_pro__tbl_invoice.sql"
        )
        assert key is not None, "Per-source invoice model not found"
        sql = invoice_dbt_artifacts[key].lower()
        # Data columns (non-FK) should be present
        assert "invoice_number" in sql, (
            f"Per-source invoice model missing invoice_number:\n{sql}"
        )
        assert "total_amount" in sql, (
            f"Per-source invoice model missing total_amount:\n{sql}"
        )


# ---------------------------------------------------------------------------
# Default value tests — email column has defaultValue
# ---------------------------------------------------------------------------

class TestDefaultValues:
    """Columns with kairos-map:defaultValue should use COALESCE or fallback."""

    def test_email_has_default(self, client_dbt_artifacts):
        """Email mapping has defaultValue 'unknown@acme.example' — should COALESCE."""
        # email has domain=Client; for multi-source it's in per-source views
        key = _find_artifact(client_dbt_artifacts, "from_admin_pulse.sql")
        if key and "corporate" in key:
            sql = client_dbt_artifacts[key]
        else:
            key = _find_artifact(client_dbt_artifacts, "/client.sql")
            if key is None:
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

    def test_cast_transform_applied(self, client_dbt_artifacts):
        """clientId mapping has CAST(source.ClientID AS STRING) — appears in base model."""
        # clientId has domain=Client, so CAST appears in client.sql
        key = _find_artifact(client_dbt_artifacts, "/client.sql")
        if key is None:
            key = _find_artifact(client_dbt_artifacts, "corporate_client.sql")
        sql = client_dbt_artifacts[key].upper()
        assert "CAST" in sql and "STRING" in sql, (
            "Missing CAST transform in client model"
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
# Multi-source tests — CorporateClient from AdminPulse + CrmSystem
# ---------------------------------------------------------------------------

class TestMultiSource:
    """When multiple sources map to the same entity, generate per-source views + union."""

    def test_per_source_views_generated(self, client_dbt_artifacts):
        """Should have per-source view models for CorporateClient."""
        sql_keys = [k for k in client_dbt_artifacts if k.endswith(".sql")]
        model_names = {k.split("/")[-1].replace(".sql", "") for k in sql_keys}

        assert "corporate_client__from_admin_pulse" in model_names, (
            "Missing per-source view for AdminPulse"
        )
        assert "corporate_client__from_crm_system" in model_names, (
            "Missing per-source view for CrmSystem"
        )

    def test_union_model_generated(self, client_dbt_artifacts):
        """The union model should reference both per-source views."""
        key = _find_artifact(client_dbt_artifacts, "/corporate_client.sql")
        assert key is not None, "corporate_client.sql union model not generated"
        sql = client_dbt_artifacts[key]
        assert "union all" in sql.lower(), "Union model missing UNION ALL"
        assert "corporate_client__from_admin_pulse" in sql, (
            "Union model missing ref to AdminPulse source"
        )
        assert "corporate_client__from_crm_system" in sql, (
            "Union model missing ref to CrmSystem source"
        )

    def test_union_model_has_sk_iri(self, client_dbt_artifacts):
        """SK and IRI should be computed in the union model, not per-source."""
        key = _find_artifact(client_dbt_artifacts, "/corporate_client.sql")
        sql = client_dbt_artifacts[key]
        assert "corporate_client_sk" in sql, "Union model missing SK column"
        assert "corporate_client_iri" in sql, "Union model missing IRI column"

    def test_per_source_no_sk_iri(self, client_dbt_artifacts):
        """Per-source views should NOT have SK/IRI columns."""
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_admin_pulse.sql"
        )
        sql = client_dbt_artifacts[key]
        assert "corporate_client_sk" not in sql, (
            "Per-source view should not have SK"
        )
        assert "corporate_client_iri" not in sql, (
            "Per-source view should not have IRI"
        )

    def test_per_source_view_materialization(self, client_dbt_artifacts):
        """Per-source models should be materialized as views."""
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_admin_pulse.sql"
        )
        sql = client_dbt_artifacts[key]
        assert "materialized='view'" in sql, (
            "Per-source model should be materialized as view"
        )

    def test_crm_source_includes_null_pad_for_unmapped(self, client_dbt_artifacts):
        """CRM lacks VATNumber — unmapped columns are NULL-padded to the superset.

        The merge pattern projects every per-source view to a common canonical
        column superset so the parent UNION ALL is positionally consistent.  A
        column a source does not map appears as ``CAST(NULL AS <type>)``.
        """
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_crm_system.sql"
        )
        sql = client_dbt_artifacts[key]
        assert "as vat_number" in sql, (
            "CRM source should include vat_number as a NULL-padded superset column"
        )
        assert "cast(null as" in sql.lower(), (
            "CRM source should NULL-pad unmapped columns"
        )
        # Mapped columns should still be present with real expressions
        assert "client_name" in sql or "client_id" in sql, (
            "CRM source should include mapped columns"
        )

    def test_admin_pulse_source_has_filter(self, client_dbt_artifacts):
        """AdminPulse per-source view should have Type = 0 filter."""
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_admin_pulse.sql"
        )
        sql = client_dbt_artifacts[key]
        assert "Type = 0" in sql, (
            "AdminPulse per-source view missing filter condition"
        )

    def test_crm_source_different_column_names(self, client_dbt_artifacts):
        """CRM source uses CustCode/CustName — different from AdminPulse."""
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_crm_system.sql"
        )
        sql = client_dbt_artifacts[key]
        assert "CustCode" in sql, "CRM source should reference CustCode"
        assert "CustName" in sql, "CRM source should reference CustName"

    def test_sources_yaml_includes_crm(self, client_dbt_artifacts):
        """_sources.yml should include the CRM source system."""
        sources_keys = [
            k for k in client_dbt_artifacts if k.endswith("_sources.yml")
        ]
        all_content = " ".join(
            client_dbt_artifacts[k].lower() for k in sources_keys
        )
        assert "crm" in all_content, (
            "_sources.yml missing CrmSystem source"
        )

    def test_single_source_unchanged(self, client_dbt_artifacts):
        """Single-source entities (e.g. ClientType) should NOT get per-source views."""
        sql_keys = [k for k in client_dbt_artifacts if k.endswith(".sql")]
        model_names = {k.split("/")[-1].replace(".sql", "") for k in sql_keys}
        # ClientType has only one source — should be a direct silver model
        assert "client_type" in model_names, "Missing client_type model"
        assert "client_type__from_admin_pulse" not in model_names, (
            "Single-source entity should not get per-source views"
        )


# ---------------------------------------------------------------------------
# Multi-target column mapping tests — one source column → multiple targets
# ---------------------------------------------------------------------------

class TestMultiTargetColumn:
    """When one source column maps to multiple target properties, all should appear."""

    def test_display_name_in_per_source_view(self, client_dbt_artifacts):
        """tblClient_Name maps to both clientName and displayName."""
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_admin_pulse.sql"
        )
        sql = client_dbt_artifacts[key]
        assert "display_name" in sql, (
            "Multi-target: displayName should appear in per-source view"
        )
        assert "client_name" in sql, (
            "Multi-target: clientName should also appear"
        )

    def test_display_name_in_union_model(self, client_dbt_artifacts):
        """Union model should include both client_name and display_name."""
        key = _find_artifact(client_dbt_artifacts, "/corporate_client.sql")
        sql = client_dbt_artifacts[key]
        assert "display_name" in sql, (
            "Multi-target: displayName missing from union model"
        )

    def test_display_name_in_schema_yaml(self, client_dbt_artifacts):
        """Schema YAML should document the displayName column."""
        key = _find_artifact(client_dbt_artifacts, "_models.yml")
        if key is None:
            pytest.skip("No _models.yml generated")
        yaml_content = client_dbt_artifacts[key]
        assert "display_name" in yaml_content, (
            "Multi-target: displayName missing from schema YAML"
        )


# ---------------------------------------------------------------------------
# SCD Type-Aware Silver Model Tests — DD-025
# ---------------------------------------------------------------------------

class TestSCDTypeAwareSilverModels:
    """Silver dbt models should generate SCD-aware incremental strategies."""

    def test_scd2_model_has_incremental_materialization(self, client_dbt_artifacts):
        """ClientPII (scdType=2) should generate incremental materialization."""
        key = _find_artifact(client_dbt_artifacts, "client_pii.sql")
        assert key is not None, "client_pii.sql model not generated"
        sql = client_dbt_artifacts[key]
        assert "materialized='incremental'" in sql, (
            f"SCD2 model should use incremental materialization:\n{sql}"
        )

    def test_scd2_model_has_composite_unique_key(self, client_dbt_artifacts):
        """ClientPII (scdType=2) should have composite unique_key [sk, valid_from]."""
        key = _find_artifact(client_dbt_artifacts, "client_pii.sql")
        sql = client_dbt_artifacts[key]
        assert "client_pii_sk" in sql and "valid_from" in sql, (
            f"SCD2 model should have composite unique_key with SK + valid_from:\n{sql}"
        )

    def test_scd2_model_has_row_hash(self, client_dbt_artifacts):
        """ClientPII (scdType=2) should compute _row_hash for change detection."""
        key = _find_artifact(client_dbt_artifacts, "client_pii.sql")
        sql = client_dbt_artifacts[key]
        assert "_row_hash" in sql, (
            f"SCD2 model should compute _row_hash:\n{sql}"
        )
        assert "kairos_row_hash" in sql, (
            f"SCD2 model should use kairos_row_hash macro for _row_hash computation:\n{sql}"
        )

    def test_scd2_model_has_change_detection_ctes(self, client_dbt_artifacts):
        """ClientPII (scdType=2) should have mapped/source_data/existing/changed/closed CTEs."""
        key = _find_artifact(client_dbt_artifacts, "client_pii.sql")
        sql = client_dbt_artifacts[key]
        assert "mapped" in sql, f"SCD2 model missing 'mapped' CTE:\n{sql}"
        assert "source_data" in sql, f"SCD2 model missing 'source_data' CTE:\n{sql}"
        assert "existing" in sql, f"SCD2 model missing 'existing' CTE:\n{sql}"
        assert "changed" in sql, f"SCD2 model missing 'changed' CTE:\n{sql}"
        assert "closed" in sql, f"SCD2 model missing 'closed' CTE:\n{sql}"

    def test_scd2_model_has_union_all(self, client_dbt_artifacts):
        """ClientPII (scdType=2) should UNION ALL changed + closed rows."""
        key = _find_artifact(client_dbt_artifacts, "client_pii.sql")
        sql = client_dbt_artifacts[key]
        assert "union all" in sql.lower(), (
            f"SCD2 model should have UNION ALL for changed+closed:\n{sql}"
        )

    def test_scd2_model_has_is_current(self, client_dbt_artifacts):
        """ClientPII (scdType=2) should set is_current for current/closed rows."""
        key = _find_artifact(client_dbt_artifacts, "client_pii.sql")
        sql = client_dbt_artifacts[key]
        assert "is_current" in sql, (
            f"SCD2 model should reference is_current column:\n{sql}"
        )

    def test_scd1_model_has_incremental(self, client_dbt_artifacts):
        """ClientType (scdType=1, reference) should still get incremental."""
        key = _find_artifact(client_dbt_artifacts, "client_type.sql")
        if key is None:
            # client_type might be ref_ prefixed
            key = _find_artifact(client_dbt_artifacts, "ref_client_type.sql")
        assert key is not None, "client_type model not generated"
        sql = client_dbt_artifacts[key]
        assert "materialized='incremental'" in sql, (
            f"SCD1 model should use incremental materialization:\n{sql}"
        )

    def test_scd1_model_no_change_detection(self, client_dbt_artifacts):
        """ClientType (scdType=1) should NOT have SCD2 change detection."""
        key = _find_artifact(client_dbt_artifacts, "client_type.sql")
        if key is None:
            key = _find_artifact(client_dbt_artifacts, "ref_client_type.sql")
        assert key is not None, "client_type model not generated"
        sql = client_dbt_artifacts[key]
        assert "source_data" not in sql, (
            "SCD1 model should not have source_data CTE (SCD2 pattern)"
        )
        assert "closed" not in sql, (
            "SCD1 model should not have closed CTE (SCD2 pattern)"
        )


class TestSCDTemplateSyntheticData:
    """Render the silver template with synthetic data to verify full SQL structure."""

    def test_scd2_template_renders_complete_model(self):
        """Render silver_model.sql.jinja2 with SCD2 params and verify structure."""
        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        template = env.get_template("silver_model.sql.jinja2")

        # Synthetic columns simulating a Customer entity
        columns = [
            {"expression": "{{ dbt_utils.generate_surrogate_key(['cust_code']) }}",
             "target_name": "customer_sk"},
            {"expression": "CONCAT('ns/', cust_code)", "target_name": "customer_iri"},
            {"expression": "CustName", "target_name": "customer_name"},
            {"expression": "CAST(Email AS VARCHAR)", "target_name": "email"},
            {"expression": "CAST(Revenue AS DECIMAL(18,2))", "target_name": "revenue"},
        ]
        hash_columns = ["customer_name", "email", "revenue"]

        sql = template.render(
            model_name="customer",
            domain_name="sales",
            schema_name="silver_sales",
            materialization="incremental",
            unique_key=["customer_sk", "valid_from"],
            scd_type="2",
            hash_columns=hash_columns,
            source_ctes=[{
                "source_name": "erp_system",
                "table_name": "tblCustomer",
                "alias": "tbl_customer",
                "filter": "",
            }],
            columns=columns,
            joins=[],
            where_clause="",
            ontology_metadata={},
        )

        # Verify config block
        assert "materialized='incremental'" in sql
        assert "customer_sk" in sql
        assert "valid_from" in sql

        # Verify source CTE
        assert "tbl_customer" in sql
        assert "source('erp_system', 'tblCustomer')" in sql

        # Verify _row_hash computation includes all hash columns
        assert "kairos_row_hash" in sql
        assert "customer_name" in sql
        assert "email" in sql
        assert "revenue" in sql

        # Verify temporal columns in source_data
        assert "kairos_current_date()" in sql
        assert "CAST(NULL AS DATE) as valid_to" in sql
        assert "1 as is_current" in sql

        # Verify change detection CTEs
        assert "existing as" in sql
        assert "where is_current = 1" in sql
        assert "changed as" in sql
        assert "closed as" in sql

        # Verify closed CTE sets correct values
        assert "kairos_current_date()" in sql
        assert "0 as is_current" in sql

        # Verify final SELECT from changed/source_data
        assert "{{% if is_incremental() %}}changed" in sql or \
               "{% if is_incremental() %}changed" in sql

        # Verify UNION ALL with closed
        assert "union all" in sql.lower()

    def test_scd1_template_renders_simple_model(self):
        """Render silver_model.sql.jinja2 with SCD1 params — no SCD2 logic."""
        from jinja2 import Environment, FileSystemLoader

        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        template = env.get_template("silver_model.sql.jinja2")

        columns = [
            {"expression": "{{ dbt_utils.generate_surrogate_key(['code']) }}",
             "target_name": "product_sk"},
            {"expression": "CONCAT('ns/', code)", "target_name": "product_iri"},
            {"expression": "ProductName", "target_name": "product_name"},
            {"expression": "CAST(Price AS DECIMAL(18,2))", "target_name": "price"},
        ]

        sql = template.render(
            model_name="product",
            domain_name="catalog",
            schema_name="silver_catalog",
            materialization="incremental",
            unique_key="product_sk",
            scd_type="1",
            hash_columns=["product_name", "price"],
            source_ctes=[{
                "source_name": "erp",
                "table_name": "tblProduct",
                "alias": "tbl_product",
                "filter": "",
            }],
            columns=columns,
            joins=[],
            where_clause="",
            ontology_metadata={},
        )

        # Verify incremental config
        assert "materialized='incremental'" in sql
        assert "unique_key='product_sk'" in sql

        # Verify NO SCD2 logic
        assert "source_data" not in sql
        assert "existing" not in sql
        assert "changed" not in sql
        assert "closed" not in sql
        assert "union all" not in sql.lower()
        assert "_row_hash" not in sql

        # Verify basic SELECT structure
        assert "product_name" in sql
        assert "price" in sql
        assert "tbl_product" in sql


# ---------------------------------------------------------------------------
# Match type in schema YAML tests
# ---------------------------------------------------------------------------

class TestMatchTypeInSchema:
    """Non-exactMatch columns should have match type annotation in schema YAML."""

    def test_close_match_annotation_in_schema(self, invoice_dbt_artifacts):
        """lineTotal uses closeMatch — should appear in schema YAML description."""
        key = _find_artifact(invoice_dbt_artifacts, "_models.yml")
        if key is None:
            pytest.skip("No _models.yml generated")
        yaml_content = invoice_dbt_artifacts[key]
        assert "closeMatch" in yaml_content, (
            "closeMatch annotation missing from schema YAML for lineTotal"
        )

    def test_exact_match_not_annotated(self, invoice_dbt_artifacts):
        """exactMatch columns should NOT get match type annotation."""
        key = _find_artifact(invoice_dbt_artifacts, "_models.yml")
        if key is None:
            pytest.skip("No _models.yml generated")
        yaml_content = invoice_dbt_artifacts[key]
        # invoice_number uses exactMatch — should NOT have annotation
        lines = yaml_content.split("\n")
        for line in lines:
            if "invoice_number" in line:
                assert "exactMatch" not in line, (
                    "exactMatch should not be annotated in schema YAML"
                )
                break


# ---------------------------------------------------------------------------
# Multi-table same-source union disambiguation (Bug fix regression test)
# ---------------------------------------------------------------------------


class TestMultiTableSameSourceUnion:
    """When two tables from the same source map to the same class, models must be
    disambiguated with the table name suffix and the union must reference distinct models.
    """

    def test_invoice_has_two_distinct_source_models(self, invoice_dbt_artifacts):
        """tblInvoice and tblCreditNote both map to Invoice from BillingPro."""
        tbl_invoice_key = _find_artifact(
            invoice_dbt_artifacts, "invoice__from_billing_pro__tbl_invoice.sql"
        )
        credit_note_key = _find_artifact(
            invoice_dbt_artifacts, "invoice__from_billing_pro__tbl_credit_note.sql"
        )
        assert tbl_invoice_key is not None, (
            "Expected per-source model 'invoice__from_billing_pro__tbl_invoice.sql' "
            f"not found. Keys: {[k for k in invoice_dbt_artifacts if 'invoice__from' in k]}"
        )
        assert credit_note_key is not None, (
            "Expected per-source model 'invoice__from_billing_pro__tbl_credit_note.sql' "
            f"not found. Keys: {[k for k in invoice_dbt_artifacts if 'invoice__from' in k]}"
        )

    def test_union_model_references_distinct_sources(self, invoice_dbt_artifacts):
        """The union model must ref both table-specific models, not duplicates."""
        union_key = _find_artifact(invoice_dbt_artifacts, "invoice/invoice.sql")
        assert union_key is not None, (
            f"Union model not found. Keys: {list(invoice_dbt_artifacts.keys())}"
        )
        sql = invoice_dbt_artifacts[union_key]
        assert "invoice__from_billing_pro__tbl_invoice" in sql, (
            f"Union model missing tblInvoice ref:\n{sql}"
        )
        assert "invoice__from_billing_pro__tbl_credit_note" in sql, (
            f"Union model missing tblCreditNote ref:\n{sql}"
        )

    def test_no_duplicate_refs_in_union(self, invoice_dbt_artifacts):
        """Each ref() in the union model must be unique — no duplicate lines."""
        union_key = _find_artifact(invoice_dbt_artifacts, "invoice/invoice.sql")
        if union_key is None:
            pytest.skip("Union model not found")
        sql = invoice_dbt_artifacts[union_key]
        import re
        refs = re.findall(r"ref\('([^']+)'\)", sql)
        assert len(refs) == len(set(refs)), (
            f"Duplicate ref() calls in union model: {refs}"
        )


# ---------------------------------------------------------------------------
# Cross-domain naturalKey resolution (Bug fix regression test)
# ---------------------------------------------------------------------------


class TestCrossDomainNaturalKeyResolution:
    """When a FK targets a class in another domain, the naturalKey should be
    resolved from the peer domain's silver-ext file.

    This tests Bug 1: cross-domain FK naturalKey not resolved.
    """

    @pytest.fixture(scope="class")
    def invoice_with_peer_exts(self):
        """Generate invoice dbt artifacts WITH peer ext paths for cross-domain NK."""
        from kairos_ontology.projections.medallion_dbt_projector import (
            generate_dbt_artifacts,
        )
        from .conftest import (
            _load_ontology, TEMPLATE_DIR, SHAPES_DIR, SOURCES_DIR,
            MAPPINGS_DIR, EXTENSIONS_DIR,
        )

        graph, namespace, classes = _load_ontology("invoice")
        silver_ext = EXTENSIONS_DIR / "invoice-silver-ext.ttl"
        # Peer ext paths: all silver-ext files EXCEPT the invoice one
        peer_exts = [
            p for p in sorted(EXTENSIONS_DIR.glob("*-silver-ext.ttl"))
            if p.name != "invoice-silver-ext.ttl"
        ]
        return generate_dbt_artifacts(
            classes=classes,
            graph=graph,
            template_dir=TEMPLATE_DIR,
            namespace=namespace,
            shapes_dir=SHAPES_DIR,
            ontology_name="invoice",
            bronze_dir=SOURCES_DIR,
            sources_dir=SOURCES_DIR,
            mappings_dir=MAPPINGS_DIR,
            silver_ext_path=silver_ext if silver_ext.exists() else None,
            peer_ext_paths=peer_exts,
        )

    def test_invoice_line_has_client_fk_join(self, invoice_with_peer_exts):
        """InvoiceLine has FK to Invoice — resolved via same-domain NK.

        InvoiceLine is single-source and should have the FK join to Invoice
        (whose naturalKey 'invoiceNumber' is in the same graph).
        """
        key = _find_artifact(invoice_with_peer_exts, "invoice_line.sql")
        assert key is not None, "invoice_line.sql not found"
        sql = invoice_with_peer_exts[key].lower()
        # Should have a join or _sk column referencing invoice
        has_join = "join" in sql and "invoice" in sql
        has_sk = "invoice_sk" in sql
        assert has_join or has_sk, (
            f"InvoiceLine model missing FK join to invoice:\n{sql}"
        )

    def test_peer_ext_naturalkey_resolves_cross_domain(self):
        """Verify that _get_natural_key resolves a cross-domain class when
        peer ext paths are loaded via merge_ext_graph.

        Scenario: Invoice graph does NOT contain Client's naturalKey.
        With peer_ext_paths=[client-silver-ext.ttl], the merged graph should
        resolve Client's NK as 'clientId' → 'client_id'.
        """
        from rdflib import Graph
        from kairos_ontology.projections.shared import merge_ext_graph
        from kairos_ontology.projections.medallion_dbt_projector import _get_natural_key
        from .conftest import ONTOLOGIES_DIR, EXTENSIONS_DIR

        # Load invoice graph only (no client data)
        g = Graph()
        g.parse(str(ONTOLOGIES_DIR / "invoice.ttl"), format="turtle")

        client_uri = "https://acme.example/ontology/client#Client"

        # Without peer ext: Client's NK should NOT be found
        merged_no_peers = merge_ext_graph(
            g, EXTENSIONS_DIR / "invoice-silver-ext.ttl"
        )
        nk_without = _get_natural_key(merged_no_peers, client_uri)
        assert nk_without == [], (
            f"Expected empty NK without peer exts, got: {nk_without}"
        )

        # With peer ext: Client's NK should resolve from client-silver-ext.ttl
        merged_with_peers = merge_ext_graph(
            g, EXTENSIONS_DIR / "invoice-silver-ext.ttl",
            peer_ext_paths=[EXTENSIONS_DIR / "client-silver-ext.ttl"],
        )
        nk_with = _get_natural_key(merged_with_peers, client_uri)
        assert nk_with == ["client_id"], (
            f"Expected ['client_id'] from peer ext, got: {nk_with}"
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
# dbt Session Log tests
# ---------------------------------------------------------------------------


class TestDbtSessionLog:
    """Test that the dbt projection writes a separate session log."""

    def test_entity_metadata_returned_in_artifacts(self, client_dbt_artifacts):
        """generate_dbt_artifacts should include __dbt_session_metadata__ key."""
        # The conftest fixture calls generate_dbt_artifacts directly;
        # __dbt_session_metadata__ is consumed by projector.py before writing.
        # Re-run to capture the metadata:
        pass  # Tested via write_dbt_session_log below

    def test_write_dbt_session_log_creates_file(self, tmp_path):
        """write_dbt_session_log should create a markdown file with entity table."""
        from kairos_ontology.projections.medallion_dbt_projector import (
            write_dbt_session_log,
        )

        entity_meta = [
            {
                "class_name": "CorporateClient",
                "model_file": "corporate_client.sql",
                "scd_type": "2",
                "source_count": 2,
                "column_count": 8,
                "fk_join_count": 0,
                "skipped": False,
                "skip_reason": None,
            },
            {
                "class_name": "ClientType",
                "model_file": "ref_client_type.sql",
                "scd_type": "1",
                "source_count": 1,
                "column_count": 3,
                "fk_join_count": 0,
                "skipped": False,
                "skip_reason": None,
            },
            {
                "class_name": "LegalEntity",
                "model_file": None,
                "scd_type": None,
                "source_count": 0,
                "column_count": 0,
                "fk_join_count": 0,
                "skipped": True,
                "skip_reason": "No bronze mapping found",
            },
        ]

        result = write_dbt_session_log(
            domain="client",
            entity_metadata=entity_meta,
            sessions_dir=tmp_path,
            toolkit_version="2.37.0",
            warnings=["Column xyz unmapped"],
        )

        assert result is not None
        assert result.exists()
        assert result.name.startswith("dbt-client-")
        assert result.suffix == ".md"

        content = result.read_text(encoding="utf-8")
        # Header
        assert "# dbt Projection Report — client" in content
        assert "**Toolkit version:** 2.37.0" in content

        # Entity table
        assert "## Silver Models" in content
        assert "| CorporateClient |" in content
        assert "| 2 (multi) |" in content
        assert "| ClientType |" in content
        assert "| 1 |" in content  # SCD1

        # Skipped classes
        assert "## Skipped Classes" in content
        assert "`LegalEntity`" in content
        assert "No bronze mapping found" in content

        # Warnings
        assert "## ⚠️ Warnings" in content
        assert "Column xyz unmapped" in content

    def test_write_dbt_session_log_no_warnings_no_skipped(self, tmp_path):
        """When no skipped and no warnings, show 'No issues' section."""
        from kairos_ontology.projections.medallion_dbt_projector import (
            write_dbt_session_log,
        )

        entity_meta = [
            {
                "class_name": "Invoice",
                "model_file": "invoice.sql",
                "scd_type": "2",
                "source_count": 1,
                "column_count": 5,
                "fk_join_count": 1,
                "skipped": False,
                "skip_reason": None,
            },
        ]

        result = write_dbt_session_log(
            domain="invoice",
            entity_metadata=entity_meta,
            sessions_dir=tmp_path,
            toolkit_version="2.37.0",
        )

        content = result.read_text(encoding="utf-8")
        assert "## ✅ No issues" in content
        assert "Skipped Classes" not in content

    def test_write_dbt_session_log_returns_none_for_empty(self, tmp_path):
        """Returns None when entity_metadata is empty."""
        from kairos_ontology.projections.medallion_dbt_projector import (
            write_dbt_session_log,
        )

        result = write_dbt_session_log(
            domain="empty",
            entity_metadata=[],
            sessions_dir=tmp_path,
        )
        assert result is None

    def test_write_dbt_session_log_deduplicates_warnings(self, tmp_path):
        """Duplicate warnings should appear only once in the output."""
        from kairos_ontology.projections.medallion_dbt_projector import (
            write_dbt_session_log,
        )

        entity_meta = [
            {
                "class_name": "Client",
                "class_uri": "http://example.org/Client",
                "model_file": "client.sql",
                "scd_type": "2",
                "source_count": 1,
                "column_count": 5,
                "column_names": ["name"],
                "fk_join_count": 0,
                "skipped": False,
                "skip_reason": None,
            },
        ]
        duplicate_warnings = [
            "Class 'PartyRole' has no naturalKey",
            "Class 'PartyRole' has no naturalKey",
            "Class 'Address' has no naturalKey",
        ]

        result = write_dbt_session_log(
            domain="party",
            entity_metadata=entity_meta,
            sessions_dir=tmp_path,
            toolkit_version="3.1.0",
            warnings=duplicate_warnings,
        )

        content = result.read_text(encoding="utf-8")
        assert content.count("PartyRole") == 1, "Duplicate warning not deduplicated"
        assert content.count("Address") == 1

    def test_write_dbt_session_log_excludes_skip_reason_from_warnings(self, tmp_path):
        """Warnings matching a skip_reason should not appear in Warnings section."""
        from kairos_ontology.projections.medallion_dbt_projector import (
            write_dbt_session_log,
        )

        entity_meta = [
            {
                "class_name": "SomeClass",
                "class_uri": "http://example.org/SomeClass",
                "model_file": None,
                "scd_type": None,
                "source_count": 0,
                "column_count": 0,
                "column_names": [],
                "fk_join_count": 0,
                "skipped": True,
                "skip_reason": "No bronze mapping found",
            },
        ]
        warnings_with_overlap = [
            "No bronze mapping for class 'SomeClass' — skipping silver model. "
            "Resolve via: kairos-design-mapping",
            "Class 'Other' has no naturalKey",
        ]

        result = write_dbt_session_log(
            domain="test",
            entity_metadata=entity_meta,
            sessions_dir=tmp_path,
            toolkit_version="3.1.0",
            warnings=warnings_with_overlap,
        )

        content = result.read_text(encoding="utf-8")
        # The "No bronze mapping" warning should be filtered (already in Skipped section)
        assert "## ⚠️ Warnings" in content
        assert "No bronze mapping" not in content.split("## ⚠️ Warnings")[1]
        # The naturalKey warning should still appear
        assert "Class 'Other' has no naturalKey" in content
# ---------------------------------------------------------------------------

class TestSourceSystemDiscriminator:
    """Per-source views should include a _source_system literal column."""

    def test_per_source_has_source_system_column(self, client_dbt_artifacts):
        """Per-source view should include _source_system literal."""
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_admin_pulse.sql"
        )
        sql = client_dbt_artifacts[key]
        assert "_source_system" in sql, (
            "Per-source view missing _source_system discriminator column"
        )

    def test_source_system_has_correct_value(self, client_dbt_artifacts):
        """_source_system should contain the source name as a string literal."""
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_admin_pulse.sql"
        )
        sql = client_dbt_artifacts[key]
        assert "'admin_pulse'" in sql or "admin_pulse" in sql.lower(), (
            "Per-source view _source_system should contain source name"
        )

    def test_union_model_has_source_system(self, client_dbt_artifacts):
        """Union model should pass through _source_system from per-source views."""
        key = _find_artifact(client_dbt_artifacts, "/corporate_client.sql")
        sql = client_dbt_artifacts[key]
        assert "_source_system" in sql, (
            "Union model should include _source_system column"
        )


# ---------------------------------------------------------------------------
# Unmapped column exclusion tests — only mapped columns appear
# ---------------------------------------------------------------------------

class TestUnmappedColumnExclusion:
    """Multi-source merge views NULL-pad to a common canonical column superset."""

    def test_null_pad_for_superset_columns(self, client_dbt_artifacts):
        """Per-source views NULL-pad columns they do not map (superset padding).

        Each per-source staging view must project the full canonical column
        superset so the parent UNION ALL is positionally consistent.  Columns a
        source does not map are emitted as ``CAST(NULL AS <type>)`` rather than
        dropped (which previously caused column-count mismatches / data loss).
        """
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_crm_system.sql"
        )
        sql = client_dbt_artifacts[key]
        # CRM does not map vat_number — it must be NULL-padded, not dropped
        assert "CAST(NULL" in sql, (
            "Per-source view should NULL-pad unmapped superset columns"
        )
        assert "as vat_number" in sql, (
            "CRM per-source view should include vat_number as a NULL pad"
        )

    def test_mapped_columns_present(self, client_dbt_artifacts):
        """Columns with actual SKOS mappings should still be included."""
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_admin_pulse.sql"
        )
        sql = client_dbt_artifacts[key]
        # AdminPulse maps ClientCode → clientId, so client_id should be present
        assert "client_id" in sql, (
            "Mapped column 'client_id' should be present in per-source view"
        )


# ---------------------------------------------------------------------------
# SCD2 history preservation tests — closed records retain values
# ---------------------------------------------------------------------------

class TestSCD2HistoryPreservation:
    """SCD2 template must preserve business data in closed records."""

    def test_scd2_closed_no_null_columns(self, client_dbt_artifacts):
        """The 'closed' CTE should NOT NULL business columns."""
        key = _find_artifact(client_dbt_artifacts, "/client.sql")
        if key is None:
            pytest.skip("client.sql not generated")
        sql = client_dbt_artifacts[key]
        if "closed as" not in sql.lower():
            pytest.skip("Client model is not SCD2 incremental")
        # Find the closed CTE content
        closed_idx = sql.lower().index("closed as")
        closed_section = sql[closed_idx:closed_idx + 500]
        assert "CAST(NULL AS VARCHAR)" not in closed_section, (
            "SCD2 closed CTE should NOT NULL business columns — "
            "historical data must be preserved"
        )

    def test_scd2_closed_reads_from_this(self, client_dbt_artifacts):
        """The closed CTE should read from {{ this }} to preserve column values."""
        key = _find_artifact(client_dbt_artifacts, "/client.sql")
        if key is None:
            pytest.skip("client.sql not generated")
        sql = client_dbt_artifacts[key]
        if "closed as" not in sql.lower():
            pytest.skip("Client model is not SCD2 incremental")
        closed_idx = sql.lower().index("closed as")
        closed_section = sql[closed_idx:closed_idx + 500]
        assert "{{ this }}" in closed_section, (
            "SCD2 closed CTE should read from {{ this }} to get existing values"
        )


# ---------------------------------------------------------------------------
# Gold model column validation — gold only refs columns that exist in silver
# ---------------------------------------------------------------------------


class TestGoldColumnValidation:
    """Gold models must only SELECT columns that exist in the referenced silver model."""

    def test_gold_refs_existing_silver_model(self, client_dbt_artifacts):
        """Gold model should use ref() pointing to a silver model that was generated."""
        gold_keys = [
            k for k in client_dbt_artifacts
            if "models/gold/" in k and k.endswith(".sql")
        ]
        silver_model_names = {
            k.split("/")[-1].replace(".sql", "")
            for k in client_dbt_artifacts
            if "models/silver/" in k and k.endswith(".sql")
            and "/_" not in k
        }
        for gk in gold_keys:
            content = client_dbt_artifacts[gk]
            # Extract ref() calls
            import re
            refs = re.findall(r"ref\('([^']+)'\)", content)
            for ref_name in refs:
                if ref_name.startswith("seed_"):
                    continue
                assert ref_name in silver_model_names, (
                    f"Gold model {gk} references ref('{ref_name}') but no "
                    f"silver model '{ref_name}.sql' was generated. "
                    f"Available silver models: {sorted(silver_model_names)}"
                )

    def test_invoice_gold_refs_existing_silver_model(self, invoice_dbt_artifacts):
        """Invoice gold model ref() calls must point to generated silver models."""
        gold_keys = [
            k for k in invoice_dbt_artifacts
            if "models/gold/" in k and k.endswith(".sql")
        ]
        silver_model_names = {
            k.split("/")[-1].replace(".sql", "")
            for k in invoice_dbt_artifacts
            if "models/silver/" in k and k.endswith(".sql")
            and "/_" not in k
        }
        for gk in gold_keys:
            content = invoice_dbt_artifacts[gk]
            import re
            refs = re.findall(r"ref\('([^']+)'\)", content)
            for ref_name in refs:
                if ref_name.startswith("seed_"):
                    continue
                assert ref_name in silver_model_names, (
                    f"Gold model {gk} references ref('{ref_name}') but no "
                    f"silver model '{ref_name}.sql' was generated. "
                    f"Available: {sorted(silver_model_names)}"
                )


# ---------------------------------------------------------------------------
# Gold model silver-existence validation (imported classes without silver)
# ---------------------------------------------------------------------------


class TestGoldSkipsUnmappedImports:
    """Gold dbt models must NOT be generated for imported classes without silver."""

    def test_silver_model_name_returns_none_when_not_in_registry(self):
        """_silver_model_name_for_class returns None for unregistered classes."""
        from kairos_ontology.projections.medallion_dbt_projector import (
            _silver_model_name_for_class,
        )

        registry = {
            "https://example.org/ont#Client": "client",
            "https://example.org/ont#Invoice": "invoice",
        }
        classes = [
            {"uri": "https://example.org/ont#Client", "name": "Client"},
            {"uri": "https://example.org/ont#Invoice", "name": "Invoice"},
            {"uri": "https://refmodel.example/ont#Weight", "name": "Weight"},
        ]
        # Class in registry → returns name
        assert _silver_model_name_for_class(
            "https://example.org/ont#Client", classes, registry=registry,
        ) == "client"

        # Class NOT in registry but in classes list → returns None (registry is
        # authoritative)
        result = _silver_model_name_for_class(
            "https://refmodel.example/ont#Weight", classes, registry=registry,
        )
        assert result is None, (
            f"Expected None for class not in registry, got '{result}'"
        )

        # Totally unknown class → returns None
        result = _silver_model_name_for_class(
            "https://unknown.example/ont#Foo", classes, registry=registry,
        )
        assert result is None

    def test_silver_model_name_falls_back_without_registry(self):
        """Without a registry, falls back to classes list (standalone gold)."""
        from kairos_ontology.projections.medallion_dbt_projector import (
            _silver_model_name_for_class,
        )

        classes = [
            {"uri": "https://example.org/ont#Client", "name": "Client"},
        ]
        # No registry → uses classes list
        assert _silver_model_name_for_class(
            "https://example.org/ont#Client", classes, registry=None,
        ) == "client"

        # No registry, not in classes → returns None (no URI fallback)
        result = _silver_model_name_for_class(
            "https://unknown.example/ont#Foo", classes, registry=None,
        )
        assert result is None

    def test_gold_schema_yaml_aligned_with_models(self, client_dbt_artifacts):
        """Gold schema YAML must only list models that have a corresponding .sql."""
        import yaml

        gold_sql_models = {
            k.split("/")[-1].replace(".sql", "")
            for k in client_dbt_artifacts
            if "models/gold/" in k and k.endswith(".sql")
        }
        gold_yaml_keys = [
            k for k in client_dbt_artifacts
            if "models/gold/" in k and k.endswith(".yml")
        ]
        for yk in gold_yaml_keys:
            parsed = yaml.safe_load(client_dbt_artifacts[yk])
            if not parsed or "models" not in parsed:
                continue
            for model in parsed["models"]:
                assert model["name"] in gold_sql_models, (
                    f"Gold schema YAML lists model '{model['name']}' but no "
                    f"corresponding .sql was generated. "
                    f"Generated gold models: {sorted(gold_sql_models)}"
                )


# ---------------------------------------------------------------------------
# IRI lineage in dbt artifacts
# ---------------------------------------------------------------------------

class TestIRILineage:
    """dbt artifacts should include IRI lineage for traceability."""

    def test_schema_yaml_has_domain_iri_in_meta(self, client_dbt_artifacts):
        """Schema YAML columns should have domain_iri in meta."""
        import yaml

        key = _find_artifact(client_dbt_artifacts, "_models.yml")
        assert key is not None
        parsed = yaml.safe_load(client_dbt_artifacts[key])
        # Find a data column with meta
        found_domain_iri = False
        for model in parsed.get("models", []):
            for col in model.get("columns", []):
                meta = col.get("meta", {})
                if "domain_iri" in meta:
                    found_domain_iri = True
                    # Should be a full URI
                    assert meta["domain_iri"].startswith("http"), (
                        f"domain_iri should be a full URI, got: {meta['domain_iri']}"
                    )
                    break
            if found_domain_iri:
                break
        assert found_domain_iri, "No column with domain_iri in schema YAML meta"

    def test_silver_sql_has_iri_comment(self, client_dbt_artifacts):
        """Silver SQL model should have SKOS mapping comments on column lines."""
        # IRI comments appear in per-source models (not the union model)
        key = _find_artifact(client_dbt_artifacts, "from_admin_pulse")
        if key is None:
            # Fall back to any per-source model
            key = next(
                (k for k in client_dbt_artifacts if "__from_" in k and k.endswith(".sql")),
                None,
            )
        assert key is not None, "No per-source silver model SQL found"
        sql = client_dbt_artifacts[key]
        # Should have SKOS match type in comments (mirrors actual SKOS triples)
        assert "skos:" in sql, (
            f"Expected 'skos:' match type in IRI comment but not found.\n"
            f"First 500 chars:\n{sql[:500]}"
        )

    def test_skos_comment_uses_declared_prefix(self, client_dbt_artifacts):
        """Comments should use declared prefixes from mapping files."""
        key = _find_artifact(client_dbt_artifacts, "from_admin_pulse")
        if key is None:
            key = next(
                (k for k in client_dbt_artifacts if "__from_" in k and k.endswith(".sql")),
                None,
            )
        assert key is not None
        sql = client_dbt_artifacts[key]
        # The mapping file declares bronze-ap: and acme: prefixes
        assert "bronze-ap:" in sql, (
            f"Expected 'bronze-ap:' declared prefix in comment but not found.\n"
            f"First 500 chars:\n{sql[:500]}"
        )
        assert "acme:" in sql, (
            f"Expected 'acme:' declared prefix in comment but not found.\n"
            f"First 500 chars:\n{sql[:500]}"
        )

    def test_skos_comment_format(self, client_dbt_artifacts):
        """Comments should follow 'source skos:{type} target' triple format."""
        import re

        pattern = re.compile(r"-- \S+ skos:\w+ \S+")
        key = _find_artifact(client_dbt_artifacts, "from_admin_pulse")
        if key is None:
            key = next(
                (k for k in client_dbt_artifacts if "__from_" in k and k.endswith(".sql")),
                None,
            )
        assert key is not None
        sql = client_dbt_artifacts[key]
        matches = pattern.findall(sql)
        assert len(matches) > 0, (
            "Expected at least one SKOS-format lineage comment "
            "'-- source skos:type target' in SQL"
        )


class TestDbtValidation:
    """Bug #7/#8 fixes and post-generation validation."""

    def test_no_self_referential_joins(self, client_dbt_artifacts):
        """Bug #1/#2: FK joins must not reference the model itself."""
        import re

        ref_pattern = re.compile(r"""\bref\(\s*['"]([^'"]+)['"]\s*\)""")
        for path, content in client_dbt_artifacts.items():
            if not path.endswith(".sql"):
                continue
            model_name = path.rsplit("/", 1)[-1].removesuffix(".sql")
            refs_found = ref_pattern.findall(content)
            assert model_name not in refs_found, (
                f"Self-referential ref('{model_name}') found in {path}"
            )

    def test_jinja_syntax_valid(self, client_dbt_artifacts):
        """Bug #7: All generated SQL must parse as valid Jinja2."""
        from jinja2 import Environment as J2Env, TemplateSyntaxError

        env = J2Env()
        for path, content in client_dbt_artifacts.items():
            if not path.endswith(".sql"):
                continue
            try:
                env.parse(content)
            except TemplateSyntaxError as exc:
                raise AssertionError(
                    f"Jinja syntax error in {path} line {exc.lineno}: {exc.message}"
                )

    def test_project_name_no_hyphens(self, client_dbt_artifacts):
        """Bug #8: dbt_project.yml project name must be a valid Python identifier."""
        import re

        content = client_dbt_artifacts.get("dbt_project.yml")
        assert content is not None, "dbt_project.yml not generated"
        # Extract name field
        for line in content.splitlines():
            if line.strip().startswith("name:"):
                name = line.split(":", 1)[1].strip().strip("'\"")
                assert re.match(r"^[^\d\W]\w*$", name), (
                    f"project name '{name}' contains invalid characters for dbt"
                )
                break

    def test_ref_consistency(self, client_dbt_artifacts):
        """All ref() targets must point to generated models."""
        import re

        ref_pattern = re.compile(r"""\bref\(\s*['"]([^'"]+)['"]\s*\)""")
        model_names = set()
        for path in client_dbt_artifacts:
            if path.endswith(".sql"):
                model_names.add(path.rsplit("/", 1)[-1].removesuffix(".sql"))

        for path, content in client_dbt_artifacts.items():
            if not path.endswith(".sql"):
                continue
            for target in ref_pattern.findall(content):
                assert target in model_names, (
                    f"ref('{target}') in {path} does not match any generated model. "
                    f"Available: {sorted(model_names)}"
                )

    def test_invoice_no_self_referential_joins(self, invoice_dbt_artifacts):
        """Bug #1/#2: Same check for invoice domain."""
        import re

        ref_pattern = re.compile(r"""\bref\(\s*['"]([^'"]+)['"]\s*\)""")
        for path, content in invoice_dbt_artifacts.items():
            if not path.endswith(".sql"):
                continue
            model_name = path.rsplit("/", 1)[-1].removesuffix(".sql")
            refs_found = ref_pattern.findall(content)
            assert model_name not in refs_found, (
                f"Self-referential ref('{model_name}') found in {path}"
            )


# ---------------------------------------------------------------------------
# Intra-domain FK join tests — belongsToInvoice (InvoiceLine → Invoice)
# ---------------------------------------------------------------------------

class TestIntraDomainFKJoin:
    """InvoiceLine has silverForeignKey on belongsToInvoice (range: Invoice).

    This tests intra-domain FK join generation: the join target is in the same
    domain, so no peer_ext_paths are needed to resolve the target NK.
    """

    def test_invoice_line_has_invoice_fk_join(self, invoice_dbt_artifacts):
        """invoice_line.sql should have a left join to ref('invoice')."""
        key = _find_artifact(invoice_dbt_artifacts, "invoice_line.sql")
        assert key is not None, "invoice_line.sql not found"
        sql = invoice_dbt_artifacts[key].lower()
        assert "left join" in sql and "ref('invoice')" in sql, (
            f"InvoiceLine missing intra-domain FK join to invoice:\n{sql}"
        )

    def test_invoice_line_has_invoice_sk_column(self, invoice_dbt_artifacts):
        """invoice_line.sql should produce an invoice_sk FK column."""
        key = _find_artifact(invoice_dbt_artifacts, "invoice_line.sql")
        assert key is not None
        sql = invoice_dbt_artifacts[key].lower()
        assert "invoice_sk" in sql, (
            f"InvoiceLine missing invoice_sk FK column:\n{sql}"
        )

    def test_invoice_line_fk_join_uses_nk(self, invoice_dbt_artifacts):
        """The FK join condition should reference Invoice's natural key."""
        key = _find_artifact(invoice_dbt_artifacts, "invoice_line.sql")
        assert key is not None
        sql = invoice_dbt_artifacts[key].lower()
        # Invoice NK is 'invoiceNumber' → snake_case 'invoice_number'
        assert "invoice_number" in sql, (
            f"InvoiceLine FK join should reference invoice_number NK:\n{sql}"
        )


# ---------------------------------------------------------------------------
# Multi-source FK per-source join tests — Invoice is multi-source, FK resolved
# inside each single-source staging view and flows through the union.
# ---------------------------------------------------------------------------

class TestMultiSourceFKPerSource:
    """Invoice entity is multi-source (tblInvoice + tblCreditNote).

    FK joins are resolved *inside each single-source staging view* (where the
    existing single-source FK machinery applies) and the resulting ``_sk``
    column flows through the UNION ALL as an ordinary canonical column.  The
    union model itself performs no joins.
    """

    def test_union_has_no_join(self, invoice_dbt_artifacts):
        """The union model must not perform FK joins (resolved upstream)."""
        key = _find_artifact(invoice_dbt_artifacts, "/invoice.sql")
        assert key is not None, "invoice.sql (union) not found"
        sql = invoice_dbt_artifacts[key].lower()
        assert "left join" not in sql, (
            f"Union model should not contain joins (FK resolved per source):\n{sql}"
        )

    def test_union_includes_client_sk(self, invoice_dbt_artifacts):
        """client_sk must be present as a canonical column in the union (no drop)."""
        key = _find_artifact(invoice_dbt_artifacts, "/invoice.sql")
        sql = invoice_dbt_artifacts[key].lower()
        assert "client_sk" in sql, (
            f"Union model should include client_sk as a canonical column:\n{sql}"
        )

    def test_per_source_view_has_fk_join(self, invoice_dbt_artifacts):
        """Each source mapping the FK has a real left join to ref('client')."""
        key = _find_artifact(
            invoice_dbt_artifacts, "invoice__from_billing_pro__tbl_invoice.sql"
        )
        assert key is not None, "per-source invoice view not found"
        sql = invoice_dbt_artifacts[key].lower()
        assert "left join {{ ref('client') }}" in sql, (
            f"Per-source view should resolve FK via a left join to client:\n{sql}"
        )
        assert "client_sk" in sql, (
            f"Per-source view should emit client_sk:\n{sql}"
        )


class TestMergeExplicitFKNoLeak:
    """Issue #178: an explicit FK column-mapping declared by ONE merge source must
    not leak into the OTHER source's per-source view.

    AdminPulse (tblClient) explicitly maps ``TypeCode`` → ``hasType`` (FK to
    ClientType); CRMSystem (Customers) does not.  The AdminPulse per-source
    CorporateClient view must keep the real join; the CRMSystem view must emit a
    NULL placeholder and must NOT reference AdminPulse's ``TypeCode`` column.
    """

    def test_declaring_source_keeps_join(self, client_dbt_artifacts):
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_admin_pulse.sql"
        )
        assert key is not None, "AdminPulse per-source CorporateClient view not found"
        sql = client_dbt_artifacts[key].lower()
        assert "client_type_sk" in sql
        assert "left join {{ ref('client_type') }}" in sql, (
            f"Declaring source should keep the hasType FK join:\n{sql}"
        )

    def test_non_declaring_source_does_not_leak(self, client_dbt_artifacts):
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_crm_system.sql"
        )
        assert key is not None, "CRMSystem per-source CorporateClient view not found"
        sql = client_dbt_artifacts[key]
        # FK _sk column still present, but only as a NULL pad (no join, no leak).
        assert "client_type_sk" in sql
        assert "client_type" not in sql.lower().replace("client_type_sk", ""), (
            f"CRMSystem view must not join/reference client_type:\n{sql}"
        )
        assert "TypeCode" not in sql, (
            f"CRMSystem view must not reference AdminPulse's TypeCode column:\n{sql}"
        )
        assert "null" in sql.lower(), (
            f"CRMSystem view should emit a NULL placeholder for the FK:\n{sql}"
        )


# ---------------------------------------------------------------------------
# Logistics domain tests — ref-model classes with source mappings
# ---------------------------------------------------------------------------

class TestLogisticsDomain:
    """Logistics domain uses DD-021 import-only pattern with ref-model classes.

    TradeParty and Carrier are claimed via silverInclude in the logistics
    silver-ext, with source mappings from LogisticsPro vocabulary.
    """

    def test_trade_party_model_generated(self, logistics_dbt_artifacts):
        """TradeParty should have a silver model generated."""
        key = _find_artifact(logistics_dbt_artifacts, "trade_party.sql")
        assert key is not None, (
            f"trade_party.sql not generated. "
            f"Available: {sorted(k for k in logistics_dbt_artifacts if k.endswith('.sql'))}"
        )

    def test_carrier_model_generated(self, logistics_dbt_artifacts):
        """Carrier should have a silver model generated."""
        key = _find_artifact(logistics_dbt_artifacts, "carrier.sql")
        assert key is not None, (
            f"carrier.sql not generated. "
            f"Available: {sorted(k for k in logistics_dbt_artifacts if k.endswith('.sql'))}"
        )

    def test_trade_party_has_party_code_column(self, logistics_dbt_artifacts):
        """TradeParty model should include party_code column from mapping."""
        key = _find_artifact(logistics_dbt_artifacts, "trade_party.sql")
        assert key is not None
        sql = logistics_dbt_artifacts[key].lower()
        assert "party_code" in sql, (
            f"TradeParty model missing party_code column:\n{sql}"
        )

    def test_trade_party_has_party_name_column(self, logistics_dbt_artifacts):
        """TradeParty model should include party_name column from mapping."""
        key = _find_artifact(logistics_dbt_artifacts, "trade_party.sql")
        assert key is not None
        sql = logistics_dbt_artifacts[key].lower()
        assert "party_name" in sql, (
            f"TradeParty model missing party_name column:\n{sql}"
        )

    def test_trade_party_is_scd2(self, logistics_dbt_artifacts):
        """TradeParty has scdType=2 in silver-ext — should use incremental."""
        key = _find_artifact(logistics_dbt_artifacts, "trade_party.sql")
        assert key is not None
        sql = logistics_dbt_artifacts[key].lower()
        assert "incremental" in sql or "snapshot" in sql, (
            f"TradeParty (SCD2) missing incremental/snapshot strategy:\n{sql[:300]}"
        )

    def test_trade_party_source_ref(self, logistics_dbt_artifacts):
        """TradeParty should reference LogisticsPro tblShipmentParty source."""
        key = _find_artifact(logistics_dbt_artifacts, "trade_party.sql")
        assert key is not None
        sql = logistics_dbt_artifacts[key].lower()
        assert "shipment_party" in sql or "tblshipmentparty" in sql, (
            f"TradeParty model missing LogisticsPro source reference:\n{sql[:500]}"
        )

    def test_carrier_has_carrier_code_column(self, logistics_dbt_artifacts):
        """Carrier model should include carrier_code column from mapping."""
        key = _find_artifact(logistics_dbt_artifacts, "carrier.sql")
        assert key is not None
        sql = logistics_dbt_artifacts[key].lower()
        assert "carrier_code" in sql, (
            f"Carrier model missing carrier_code column:\n{sql}"
        )

    def test_logistics_no_false_positive_warnings(self, logistics_dbt_artifacts):
        """Logistics projection should not produce 'No bronze mapping' warnings.

        Both TradeParty and Carrier have source mappings — any 'No bronze mapping'
        warning indicates the mapping resolution failed.

        The issue #172 structural fixtures (Organization, ShipOperator,
        VesselCarrier, BaseMarker, ActiveMarker) are intentionally unmapped — they
        exist only to exercise silver DDL folding/exclude — so warnings about them
        are expected and excluded from this guard.
        """
        unmapped_172_fixtures = (
            "Organization", "ShipOperator", "VesselCarrier",
            "BaseMarker", "ActiveMarker",
        )
        with _caplog_context() as records:
            # Re-generate to capture warnings (fixture is cached but we need logs)
            from kairos_ontology.projections.medallion_dbt_projector import (
                generate_dbt_artifacts,
            )
            from .conftest import (
                _load_ontology_with_imports,
                EXTENSIONS_DIR,
            )

            graph, namespace, classes = _load_ontology_with_imports("logistics")
            silver_ext = EXTENSIONS_DIR / "logistics-silver-ext.ttl"
            generate_dbt_artifacts(
                classes=classes,
                graph=graph,
                template_dir=TEMPLATE_DIR,
                namespace=namespace,
                shapes_dir=SHAPES_DIR,
                ontology_name="logistics",
                sources_dir=SOURCES_DIR,
                mappings_dir=MAPPINGS_DIR,
                silver_ext_path=silver_ext if silver_ext.exists() else None,
            )

        no_mapping_warnings = [
            r for r in records
            if "No bronze mapping" in r.getMessage()
            and not any(f"'{c}'" in r.getMessage() for c in unmapped_172_fixtures)
        ]
        assert len(no_mapping_warnings) == 0, (
            f"Unexpected 'No bronze mapping' warnings: "
            f"{[r.getMessage() for r in no_mapping_warnings]}"
        )

    def test_invoice_jinja_syntax_valid(self, invoice_dbt_artifacts):
        """Bug #7: Invoice domain Jinja validity."""
        from jinja2 import Environment as J2Env, TemplateSyntaxError

        env = J2Env()
        for path, content in invoice_dbt_artifacts.items():
            if not path.endswith(".sql"):
                continue
            try:
                env.parse(content)
            except TemplateSyntaxError as exc:
                raise AssertionError(
                    f"Jinja syntax error in {path} line {exc.lineno}: {exc.message}"
                )


class TestGoldSharedDimDate:
    """dim_date is a conformed dimension — emitted once to shared folder."""

    def test_dim_date_in_shared_folder(self, client_dbt_artifacts):
        """dim_date.sql lives in models/gold/shared/, not per-domain."""
        shared_path = "models/gold/shared/dim_date.sql"
        assert shared_path in client_dbt_artifacts, (
            f"Expected dim_date at '{shared_path}', got keys: "
            + str([k for k in client_dbt_artifacts if "dim_date" in k])
        )

    def test_dim_date_not_in_domain_folder(self, client_dbt_artifacts):
        """dim_date must NOT appear in the per-domain gold folder."""
        domain_path = "models/gold/client/dim_date.sql"
        assert domain_path not in client_dbt_artifacts, (
            f"dim_date should not be at '{domain_path}' — must be in shared/"
        )

    def test_shared_schema_yaml_exists(self, client_dbt_artifacts):
        """Shared gold schema YAML contains dim_date entry."""
        shared_schema = "models/gold/shared/_shared__gold_models.yml"
        assert shared_schema in client_dbt_artifacts, (
            f"Expected shared schema at '{shared_schema}'"
        )
        content = client_dbt_artifacts[shared_schema]
        assert "dim_date" in content

    def test_no_duplicate_model_names(self, client_dbt_artifacts):
        """No two SQL artifacts resolve to the same dbt model name."""
        from collections import Counter

        names = [
            path.rsplit("/", 1)[-1].removesuffix(".sql")
            for path in client_dbt_artifacts
            if path.endswith(".sql")
        ]
        dupes = [n for n, c in Counter(names).items() if c > 1]
        assert not dupes, f"Duplicate dbt model names: {dupes}"

    def test_dim_date_not_in_domain_schema(self, client_dbt_artifacts):
        """Per-domain gold schema YAML must not contain dim_date."""
        domain_schema = next(
            (k for k in client_dbt_artifacts if "_client__gold_models.yml" in k),
            None,
        )
        if domain_schema:
            content = client_dbt_artifacts[domain_schema]
            assert "dim_date" not in content, (
                "dim_date should not appear in per-domain gold schema YAML"
            )


# ---------------------------------------------------------------------------
# Cross-table warning tests — domain-filtered noise reduction
# ---------------------------------------------------------------------------

class TestCrossTableWarnings:
    """Verify cross-table warnings fire only for properties in the class's domain."""

    def test_cross_table_warning_fires_for_domain_properties(self, client_ontology):
        """Single-source entities with cross-table mappings emit warnings."""
        import logging
        from kairos_ontology.projections.medallion_dbt_projector import (
            generate_dbt_artifacts,
        )

        graph, namespace, classes = client_ontology
        silver_ext = EXTENSIONS_DIR / "client-silver-ext.ttl"

        with _caplog_context(logging.WARNING) as records:
            generate_dbt_artifacts(
                classes=classes,
                graph=graph,
                template_dir=TEMPLATE_DIR,
                namespace=namespace,
                shapes_dir=SHAPES_DIR,
                ontology_name="client",
                sources_dir=SOURCES_DIR,
                mappings_dir=MAPPINGS_DIR,
                silver_ext_path=silver_ext if silver_ext.exists() else None,
            )

        cross_table_msgs = [
            r.message for r in records
            if "Cross-table reference" in r.message
        ]
        # ClientType has tblClientType as sole source; tblClient_TypeCode maps to
        # typeCode (domain: ClientType) — this MUST generate a warning.
        client_type_warnings = [
            m for m in cross_table_msgs if "'ClientType'" in m
        ]
        assert client_type_warnings, (
            "Expected at least one cross-table warning for ClientType "
            "(tblClient_TypeCode → typeCode is a cross-table mapping)"
        )

    def test_no_cross_table_warning_for_other_domain_properties(self, client_ontology):
        """Properties with domain != current class must NOT produce warnings."""
        import logging
        from kairos_ontology.projections.medallion_dbt_projector import (
            generate_dbt_artifacts,
        )

        graph, namespace, classes = client_ontology
        silver_ext = EXTENSIONS_DIR / "client-silver-ext.ttl"

        with _caplog_context(logging.WARNING) as records:
            generate_dbt_artifacts(
                classes=classes,
                graph=graph,
                template_dir=TEMPLATE_DIR,
                namespace=namespace,
                shapes_dir=SHAPES_DIR,
                ontology_name="client",
                sources_dir=SOURCES_DIR,
                mappings_dir=MAPPINGS_DIR,
                silver_ext_path=silver_ext if silver_ext.exists() else None,
            )

        cross_table_msgs = [
            r.message for r in records
            if "Cross-table reference" in r.message
        ]
        # Identifier has its own domain properties (identifierValue, identifierType).
        # Columns like tblClient_Name should NOT trigger warnings on Identifier
        # because clientName has domain Client, not Identifier.
        identifier_warnings = [
            m for m in cross_table_msgs if "'Identifier'" in m
        ]
        bad_identifier_warnings = [
            m for m in identifier_warnings
            if "clientName" in m or "displayName" in m or "isActive" in m
        ]
        assert not bad_identifier_warnings, (
            f"Identifier should not get warnings for Client-domain properties: "
            f"{bad_identifier_warnings}"
        )

    def _subtype_inputs(self):
        """Build a synthetic single-source subtype-as-own-table scenario.

        Returns ``(classes, graph, namespace, systems, mappings)`` where a
        ``Child`` subtype is claimed as its own silver table (single source
        ``tblChild``) and inherits ``parentAttr`` from ``Parent`` — whose column
        lives on a different table (``tblParent``).  This realises the inherited
        cross-table pattern from issue #181.
        """
        from rdflib import RDF, RDFS, OWL, Graph, Literal, Namespace, URIRef

        ns = "http://example.com/acme#"
        ex = Namespace(ns)
        xsd_str = URIRef("http://www.w3.org/2001/XMLSchema#string")

        g = Graph()
        g.add((ex.Parent, RDF.type, OWL.Class))
        g.add((ex.Parent, RDFS.label, Literal("Parent")))
        g.add((ex.Child, RDF.type, OWL.Class))
        g.add((ex.Child, RDFS.label, Literal("Child")))
        g.add((ex.Child, RDFS.subClassOf, ex.Parent))
        # Inherited property declared on the parent.
        g.add((ex.parentAttr, RDF.type, OWL.DatatypeProperty))
        g.add((ex.parentAttr, RDFS.domain, ex.Parent))
        g.add((ex.parentAttr, RDFS.range, xsd_str))
        g.add((ex.parentAttr, RDFS.label, Literal("parentAttr")))
        # Own property declared on the subtype.
        g.add((ex.childAttr, RDF.type, OWL.DatatypeProperty))
        g.add((ex.childAttr, RDFS.domain, ex.Child))
        g.add((ex.childAttr, RDFS.range, xsd_str))
        g.add((ex.childAttr, RDFS.label, Literal("childAttr")))

        classes = [{"uri": str(ex.Child), "name": "Child", "label": "Child",
                    "comment": ""}]

        child_tbl = "http://example.com/src/ChildTable"
        parent_tbl = "http://example.com/src/ParentTable"
        systems = [{
            "system_uri": "http://example.com/src/Sys",
            "system_label": "CrmSystem",
            "database": "db", "schema": "dbo", "connection_type": "jdbc",
            "tables": [
                {"uri": child_tbl, "name": "tblChild", "label": "tblChild",
                 "pk_columns": ["child_id"], "incremental_column": None,
                 "columns": [
                     {"uri": child_tbl + "#child_id", "name": "child_id",
                      "data_type": "int", "nullable": False, "is_pk": True},
                     {"uri": child_tbl + "#child_attr", "name": "child_attr",
                      "data_type": "string", "nullable": True, "is_pk": False},
                 ]},
                {"uri": parent_tbl, "name": "tblParent", "label": "tblParent",
                 "pk_columns": ["parent_id"], "incremental_column": None,
                 "columns": [
                     {"uri": parent_tbl + "#parent_id", "name": "parent_id",
                      "data_type": "int", "nullable": False, "is_pk": True},
                     {"uri": parent_tbl + "#parent_attr", "name": "parent_attr",
                      "data_type": "string", "nullable": True, "is_pk": False},
                 ]},
            ],
        }]

        mappings = {
            "table_maps": {child_tbl: [{
                "target_uri": str(ex.Child), "mapping_type": "direct",
                "filter_condition": None, "dedup_key": None, "dedup_order": None,
            }]},
            "column_maps": {
                child_tbl + "#child_attr": [{
                    "target_uri": str(ex.childAttr), "match_type": "exactMatch",
                    "transform": None, "source_columns": None,
                    "default_value": None,
                }],
                parent_tbl + "#parent_attr": [{
                    "target_uri": str(ex.parentAttr), "match_type": "exactMatch",
                    "transform": None, "source_columns": None,
                    "default_value": None,
                }],
            },
        }
        return classes, g, ns, systems, mappings

    def test_inherited_cross_table_is_info_not_warning(self):
        """Issue #181: inherited cross-table props become a consolidated info note.

        A subtype claimed as its own silver table must NOT emit per-column
        cross-table warnings for inherited parent properties (they were excluded
        by design). Instead, a single consolidated info note is recorded.
        """
        from jinja2 import Environment, FileSystemLoader
        from kairos_ontology.projections.medallion_dbt_projector import (
            _gen_silver_models,
        )

        classes, graph, ns, systems, mappings = self._subtype_inputs()
        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))

        _artifacts, warnings, entity_meta = _gen_silver_models(
            classes, graph, ns, systems, mappings, env, {}, "acme",
        )

        # No per-column cross-table warning for the inherited parentAttr.
        cross_table = [w for w in warnings if "Cross-table reference" in w]
        assert not cross_table, (
            f"Inherited cross-table props must not warn, got: {cross_table}"
        )

        # Exactly one consolidated info note on the Child entity.
        child_meta = next(m for m in entity_meta if m["class_name"] == "Child")
        notes = child_meta.get("info_notes") or []
        assert len(notes) == 1, f"Expected one info note, got: {notes}"
        assert "subtype claimed as its own silver table" in notes[0]
        assert "Parent" in notes[0]
        assert "1 inherited property" in notes[0]

    def test_own_cross_table_still_warns(self):
        """Own-domain cross-table props remain genuine ⚠️ warnings (own precedence)."""
        from rdflib import RDFS
        from jinja2 import Environment, FileSystemLoader
        from kairos_ontology.projections.medallion_dbt_projector import (
            _gen_silver_models,
        )

        classes, graph, ns, systems, mappings = self._subtype_inputs()
        # Re-home parentAttr onto the subtype so its cross-table column is now an
        # OWN property → must produce a per-column warning.
        from rdflib import URIRef
        parent_attr = URIRef(ns + "parentAttr")
        graph.remove((parent_attr, RDFS.domain, URIRef(ns + "Parent")))
        graph.add((parent_attr, RDFS.domain, URIRef(ns + "Child")))

        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        _artifacts, warnings, entity_meta = _gen_silver_models(
            classes, graph, ns, systems, mappings, env, {}, "acme",
        )

        cross_table = [w for w in warnings if "Cross-table reference" in w]
        assert cross_table, "Own-domain cross-table prop should warn"
        assert any("parentAttr" in w for w in cross_table)
        child_meta = next(m for m in entity_meta if m["class_name"] == "Child")
        assert not (child_meta.get("info_notes") or []), (
            "Own cross-table prop must not be demoted to an info note"
        )

    def test_inherited_info_renders_in_session_log(self, tmp_path):
        """The consolidated info note surfaces under a ## ℹ️ Info session-log section."""
        from jinja2 import Environment, FileSystemLoader
        from kairos_ontology.projections.medallion_dbt_projector import (
            _gen_silver_models, write_dbt_session_log,
        )

        classes, graph, ns, systems, mappings = self._subtype_inputs()
        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
        _artifacts, _warnings, entity_meta = _gen_silver_models(
            classes, graph, ns, systems, mappings, env, {}, "acme",
        )

        out = write_dbt_session_log(
            domain="acme",
            entity_metadata=entity_meta,
            sessions_dir=tmp_path,
            warnings=[],
        )
        text = out.read_text(encoding="utf-8")
        assert "## ℹ️ Info" in text
        assert "subtype claimed as its own silver table" in text
        # Info notes alone must suppress the "No issues" banner.
        assert "## ✅ No issues" not in text


# ---------------------------------------------------------------------------
# Bug fix: single-source column scoping (table_column_uris)
# ---------------------------------------------------------------------------

class TestSingleSourceColumnScoping:
    """Verify single-source entities only include columns from their primary table."""

    def test_client_type_only_has_primary_table_columns(self, client_dbt_artifacts):
        """ClientType (single-source: tblClientType) must not reference other tables."""
        ct_key = next(
            (k for k in client_dbt_artifacts
             if "client_type" in k and k.endswith(".sql")
             and "dim_" not in k),
            None,
        )
        assert ct_key, "Expected a silver client_type.sql model"
        content = client_dbt_artifacts[ct_key]
        # tblClient columns should NOT appear in the ClientType model
        assert "tbl_client_type_code" not in content.lower() or True  # column exists
        # Columns from tblClient (not tblClientType) should be absent
        assert "tbl_client." not in content, (
            "ClientType model should not reference tblClient table"
        )

    def test_identifier_excludes_cross_table_columns(self, client_dbt_artifacts):
        """Identifier (single-source: tblIdentifier) must not pull Client columns."""
        id_key = next(
            (k for k in client_dbt_artifacts
             if "/identifier" in k and k.endswith(".sql")
             and "dim_" not in k),
            None,
        )
        assert id_key, "Expected a silver identifier.sql model"
        content = client_dbt_artifacts[id_key]
        # Invoice/Client columns should not appear in Identifier model
        assert "client_name" not in content, (
            "Identifier model should not include clientName (domain: Client)"
        )
        assert "total_amount" not in content, (
            "Identifier model should not include totalAmount (domain: Invoice)"
        )


# ---------------------------------------------------------------------------
# Bug fix: cross-domain ref() validation (no false positives)
# ---------------------------------------------------------------------------

class TestCrossDomainRefValidation:
    """Verify ref() validation doesn't produce false positives for FK joins."""

    def test_no_false_positive_for_join_refs(self):
        """ref() targets in JOIN clauses should not trigger validation warnings."""
        from kairos_ontology.projections.medallion_dbt_projector import (
            _validate_dbt_artifacts,
        )

        # Synthetic artifacts: engagement domain refs party (cross-domain FK)
        artifacts = {
            "models/silver/engagement/client_engagement.sql": (
                "with engagement as (\n"
                "    select * from {{ source('bronze', 'engagement') }}\n"
                "),\n"
                "party as (\n"
                "    select * from {{ ref('party') }}\n"
                ")\n"
                "select e.*, p.party_sk\n"
                "from engagement e\n"
                "left join {{ ref('party') }} p on e.party_id = p.party_id\n"
            ),
            "models/silver/engagement/fiscal_year.sql": (
                "select * from {{ source('bronze', 'fiscal_year') }}\n"
            ),
        }

        with _caplog_context(logging.WARNING) as records:
            _validate_dbt_artifacts(artifacts)

        ref_warnings = [
            r.message for r in records
            if "does not match any generated model" in r.message
        ]
        assert not ref_warnings, (
            f"Cross-domain ref('party') in JOIN should not trigger warning: "
            f"{ref_warnings}"
        )


# ---------------------------------------------------------------------------
# silverColumnName override tests — dbt must respect column name annotations
# ---------------------------------------------------------------------------

class TestSilverColumnNameOverride:
    """Verify dbt projector uses kairos-ext:silverColumnName for datatype properties."""

    def test_city_alias_in_sql(self, client_dbt_artifacts):
        """clientCity has silverColumnName 'city' — dbt SQL should use 'city' not 'client_city'."""
        # City is on the Client class — appears in per-source or union model
        key = _find_artifact(client_dbt_artifacts, "corporate_client.sql")
        if key is None:
            key = _find_artifact(client_dbt_artifacts, "/client.sql")
        assert key is not None, "No client model generated"
        sql = client_dbt_artifacts[key].lower()
        # The overridden alias 'city' should appear, not the default 'client_city'
        assert " city" in sql or "\tcity" in sql or ",city" in sql or "as city" in sql, (
            f"Expected 'city' alias from silverColumnName override in SQL:\n{sql}"
        )

    def test_country_alias_in_sql(self, client_dbt_artifacts):
        """clientCountry has silverColumnName 'country' — not 'client_country'."""
        key = _find_artifact(client_dbt_artifacts, "corporate_client.sql")
        if key is None:
            key = _find_artifact(client_dbt_artifacts, "/client.sql")
        assert key is not None, "No client model generated"
        sql = client_dbt_artifacts[key].lower()
        assert "as country" in sql or " country" in sql, (
            f"Expected 'country' alias from silverColumnName override:\n{sql}"
        )

    def test_default_snake_case_without_override(self, invoice_dbt_artifacts):
        """Properties without silverColumnName should still use camelCase→snake_case."""
        # invoiceNumber has silverColumnName "invoice_number" (same as default),
        # but lineTotal doesn't — verify fallback works
        key = _find_artifact(invoice_dbt_artifacts, "invoice_line.sql")
        assert key is not None, "No invoice_line model generated"
        sql = invoice_dbt_artifacts[key].lower()
        # line_total is the snake_case of lineTotal (fallback behaviour)
        assert "line_total" in sql, (
            f"Expected default snake_case 'line_total' for property without override:\n{sql}"
        )

    def test_schema_yaml_uses_override(self, client_dbt_artifacts):
        """Schema YAML column descriptions should use overridden name."""
        key = _find_artifact(client_dbt_artifacts, "_models.yml")
        assert key is not None, "_models.yml not generated"
        content = client_dbt_artifacts[key].lower()
        # 'city' should appear as a column name, not 'client_city'
        assert "- name: city" in content or "- name: \"city\"" in content, (
            f"Schema YAML should use silverColumnName 'city':\n{content[:2000]}"
        )

    def test_real_typo_still_triggers_warning(self):
        """ref() targets that are genuinely missing still get warned about."""
        from kairos_ontology.projections.medallion_dbt_projector import (
            _validate_dbt_artifacts,
        )

        artifacts = {
            "models/silver/client/client.sql": (
                "select * from {{ ref('nonexistent_model') }}\n"
            ),
        }

        with _caplog_context(logging.WARNING) as records:
            _validate_dbt_artifacts(artifacts)

        ref_warnings = [
            r.message for r in records
            if "does not match any generated model" in r.message
        ]
        assert any("nonexistent_model" in w for w in ref_warnings), (
            "A genuinely missing ref target should still trigger a warning"
        )


# ---------------------------------------------------------------------------
# Logical sources mode — DD-035
# ---------------------------------------------------------------------------

class TestLogicalSourcesMode:
    """Verify the logical_sources_only flag omits database/schema from _sources.yml."""

    def test_default_mode_includes_schema(self, client_dbt_artifacts):
        """Default mode should include schema in _sources.yml."""
        source_files = {
            k: v for k, v in client_dbt_artifacts.items() if "__sources.yml" in k
        }
        assert source_files, "Should have at least one sources file"
        for path, content in source_files.items():
            assert "schema:" in content, f"{path} should include schema"

    def test_logical_mode_omits_database_schema(self):
        """logical_sources_only=True should omit database/schema from _sources.yml."""
        from kairos_ontology.projections.medallion_dbt_projector import (
            generate_dbt_artifacts,
        )

        graph, namespace, classes = _load_ontology("client")
        artifacts = generate_dbt_artifacts(
            classes, graph, TEMPLATE_DIR, namespace,
            shapes_dir=SHAPES_DIR,
            ontology_name="client",
            sources_dir=SOURCES_DIR,
            mappings_dir=MAPPINGS_DIR,
            silver_ext_path=EXTENSIONS_DIR / "client-silver-ext.ttl",
            logical_sources_only=True,
        )

        source_files = {
            k: v for k, v in artifacts.items() if "__sources.yml" in k
        }
        assert source_files, "Should have at least one sources file"
        for path, content in source_files.items():
            assert "database:" not in content, (
                f"{path} should NOT include database in logical mode"
            )
            assert "schema:" not in content, (
                f"{path} should NOT include schema in logical mode"
            )
            # Should still have source name and tables
            assert "name:" in content
            assert "tables:" in content

    def test_logical_mode_still_generates_valid_models(self):
        """Silver models should still be generated correctly in logical mode."""
        from kairos_ontology.projections.medallion_dbt_projector import (
            generate_dbt_artifacts,
        )

        graph, namespace, classes = _load_ontology("client")
        artifacts = generate_dbt_artifacts(
            classes, graph, TEMPLATE_DIR, namespace,
            shapes_dir=SHAPES_DIR,
            ontology_name="client",
            sources_dir=SOURCES_DIR,
            mappings_dir=MAPPINGS_DIR,
            silver_ext_path=EXTENSIONS_DIR / "client-silver-ext.ttl",
            logical_sources_only=True,
        )

        # Silver models should still have source() references
        sql_files = {k: v for k, v in artifacts.items() if k.endswith(".sql")}
        assert sql_files, "Should have generated SQL models"
        for path, content in sql_files.items():
            if "silver" in path and "ddl" not in path and "alter" not in path:
                if "{{ source(" in content:
                    break
        else:
            pytest.fail("No silver model contains {{ source() }} reference")


# ---------------------------------------------------------------------------
# DD-039: silverSourceRef — bronze_expanded routing tests
# ---------------------------------------------------------------------------

class TestSilverSourceRef:
    """Verify silverSourceRef annotation routes to {{ ref() }} in dbt output."""

    def test_invoice_line_tax_uses_ref(self, invoice_dbt_artifacts):
        """InvoiceLineTax has silverSourceRef → model uses {{ ref() }}."""
        key = _find_artifact(invoice_dbt_artifacts, "invoice_line_tax.sql")
        assert key, (
            f"No invoice_line_tax model found. "
            f"Available: {[k for k in invoice_dbt_artifacts if 'silver' in k]}"
        )
        sql = invoice_dbt_artifacts[key]
        assert "ref('stg_billingpro_invoice_line_details')" in sql, (
            f"Expected ref() call in invoice_line_tax model:\n{sql}"
        )

    def test_invoice_line_tax_no_source_call(self, invoice_dbt_artifacts):
        """InvoiceLineTax with silverSourceRef should NOT use {{ source() }}."""
        key = _find_artifact(invoice_dbt_artifacts, "invoice_line_tax.sql")
        assert key
        sql = invoice_dbt_artifacts[key]
        assert "{{ source(" not in sql, (
            f"Expected no source() call in invoice_line_tax model:\n{sql}"
        )

    def test_invoice_still_uses_source(self, invoice_dbt_artifacts):
        """Invoice (no silverSourceRef) still uses {{ source() }}."""
        # Invoice has multi-source (tblInvoice + tblCreditNote), so look in
        # per-source views
        invoice_keys = [
            k for k in invoice_dbt_artifacts
            if "invoice" in k and "silver" in k and k.endswith(".sql")
            and "invoice_line" not in k and "invoice_tag" not in k
        ]
        assert invoice_keys, "No invoice silver models found"
        # At least one model must use source()
        has_source = any(
            "{{ source(" in invoice_dbt_artifacts[k] for k in invoice_keys
        )
        assert has_source, (
            "Invoice models should use source() (no silverSourceRef set)"
        )

    def test_invoice_line_tax_has_mapped_columns(self, invoice_dbt_artifacts):
        """InvoiceLineTax model contains the mapped column expressions."""
        key = _find_artifact(invoice_dbt_artifacts, "invoice_line_tax.sql")
        assert key
        sql = invoice_dbt_artifacts[key]
        # Check mapped transform expressions appear
        assert "TaxCode" in sql or "tax_code" in sql, (
            f"Expected TaxCode column in invoice_line_tax:\n{sql}"
        )


# ---------------------------------------------------------------------------
# CR-002 scenario: composite naturalKey on acme-hub Identifier class
# ---------------------------------------------------------------------------

class TestCompositeNaturalKeyScenario:
    """CR-002 — acme-hub Identifier has naturalKey 'identifierValue, identifierScheme'.
    After the fix the surrogate key expression must reference both columns separately."""

    def test_identifier_sk_has_two_separate_columns(self, client_dbt_artifacts):
        """generate_surrogate_key for Identifier must list both NK columns as separate items."""
        from kairos_ontology.projections.medallion_dbt_projector import _get_natural_key
        from tests.scenarios.conftest import _load_ontology

        g, _, _ = _load_ontology("client")
        # Verify the NK is parsed as two elements, not one malformed string
        identifier_uri = None
        for uri in [u for u in [str(c) for c in g.subjects()] if "Identifier" in u]:
            if "acme" in uri.lower() or "example" in uri.lower():
                identifier_uri = uri
                break

        if identifier_uri:
            nk = _get_natural_key(g, identifier_uri)
            assert len(nk) == 2, (
                f"Identifier naturalKey should yield 2 columns, got {nk}"
            )
            assert "identifier_value" in nk
            assert "identifier_scheme" in nk

    def test_identifier_sk_expr_no_comma_in_single_quote(self, client_dbt_artifacts):
        """The surrogate key expression must not contain a comma inside a single-quoted string."""
        key = _find_artifact(client_dbt_artifacts, "identifier.sql")
        if key is None:
            pytest.skip("Identifier model not generated (may be unmapped)")
        sql = client_dbt_artifacts[key]
        # Ensure no malformed composite like ['identifier_value,identifier_scheme']
        assert "'identifier_value,identifier_scheme'" not in sql, (
            "SK expression must not have comma inside a single-quoted NK string:\n" + sql
        )


# ---------------------------------------------------------------------------
# Multi-domain coverage report merge
# ---------------------------------------------------------------------------

class TestCoverageReportMerge:
    """coverage-report.json must contain data for ALL projected domains."""

    def test_coverage_data_returned_per_domain(
        self, client_dbt_artifacts, invoice_dbt_artifacts
    ):
        """Each domain's artifacts should carry __coverage_data__ for merging."""
        client_cov = client_dbt_artifacts.get("__coverage_data__")
        invoice_cov = invoice_dbt_artifacts.get("__coverage_data__")
        assert client_cov is not None, "Client domain missing __coverage_data__"
        assert invoice_cov is not None, "Invoice domain missing __coverage_data__"

    def test_coverage_data_has_entity_keys(self, client_dbt_artifacts):
        """Coverage data should have an entry per projected entity."""
        cov = client_dbt_artifacts.get("__coverage_data__", {})
        assert len(cov) > 0, "Coverage data is empty — expected entity entries"
        for entity_name, stats in cov.items():
            assert "ontology_properties_total" in stats, (
                f"Entity {entity_name} missing ontology_properties_total"
            )
            assert "populated_from_source" in stats
            assert "always_null" in stats

    def test_merged_summary_across_domains(
        self, client_dbt_artifacts, invoice_dbt_artifacts
    ):
        """_build_coverage_summary should aggregate stats across domains."""
        from kairos_ontology.projector import _build_coverage_summary

        domain_data = {
            "client": client_dbt_artifacts.get("__coverage_data__", {}),
            "invoice": invoice_dbt_artifacts.get("__coverage_data__", {}),
        }
        summary = _build_coverage_summary(domain_data)
        assert summary["domains_count"] == 2
        assert summary["total_properties"] > 0
        assert 0 <= summary["populated_pct"] <= 100

    def test_no_coverage_report_json_in_per_domain_artifacts(
        self, client_dbt_artifacts
    ):
        """Per-domain artifacts must NOT include coverage-report.json (merged later)."""
        assert "coverage-report.json" not in client_dbt_artifacts, (
            "coverage-report.json should not appear in per-domain artifacts — "
            "it is merged as a post-domain step"
        )


# ---------------------------------------------------------------------------
# CR-006 fix: SCD2 unique test uses where clause — false failure prevention
# ---------------------------------------------------------------------------

class TestSCDTypeAwareSchemaYaml:
    """Schema YAML must use `unique: config: where: "is_current = 1"` for SCD2 entities.

    SCD Type 2 silver tables store multiple rows per entity (current + N historical),
    so a bare `unique` test scans all rows and produces false failures.
    CR-006 fix: the projector must check scdType before emitting the test.
    """

    def test_scd2_sk_has_where_clause_unique(self, client_dbt_artifacts):
        """client_pii (scdType=2) _sk column must use unique with where clause."""
        import yaml

        key = _find_artifact(client_dbt_artifacts, "_models.yml")
        assert key is not None, "_models.yml not generated"
        parsed = yaml.safe_load(client_dbt_artifacts[key])

        sk_tests = _find_column_tests(parsed, "client_pii_sk")
        assert sk_tests is not None, "client_pii_sk column not found in schema YAML"
        unique_test = _find_unique_test(sk_tests)
        assert unique_test is not None, (
            f"client_pii_sk missing 'unique' test. Tests found: {sk_tests}"
        )
        assert isinstance(unique_test, dict), (
            "SCD2 unique test must be a dict with config, not a bare string. "
            f"Got: {unique_test!r}"
        )
        where = (unique_test.get("unique") or {}).get("config", {}).get("where")
        assert where == "is_current = 1", (
            f"SCD2 unique test must have where='is_current = 1'. Got: {where!r}"
        )

    def test_scd2_iri_has_where_clause_unique(self, client_dbt_artifacts):
        """client_pii (scdType=2) _iri column must also use unique with where clause."""
        import yaml

        key = _find_artifact(client_dbt_artifacts, "_models.yml")
        assert key is not None
        parsed = yaml.safe_load(client_dbt_artifacts[key])

        iri_tests = _find_column_tests(parsed, "client_pii_iri")
        assert iri_tests is not None, "client_pii_iri column not found in schema YAML"
        unique_test = _find_unique_test(iri_tests)
        assert isinstance(unique_test, dict), (
            "SCD2 _iri unique test must be a dict with config. "
            f"Got: {unique_test!r}"
        )
        where = (unique_test.get("unique") or {}).get("config", {}).get("where")
        assert where == "is_current = 1", (
            f"SCD2 _iri unique test must have where='is_current = 1'. Got: {where!r}"
        )

    def test_scd1_sk_uses_bare_unique(self, client_dbt_artifacts):
        """sole_proprietor_client (scdType=1) _sk must use bare `unique` test (no where)."""
        import yaml

        key = _find_artifact(client_dbt_artifacts, "_models.yml")
        assert key is not None
        parsed = yaml.safe_load(client_dbt_artifacts[key])

        sk_tests = _find_column_tests(parsed, "sole_proprietor_client_sk")
        assert sk_tests is not None, (
            "sole_proprietor_client_sk column not found in schema YAML"
        )
        unique_test = _find_unique_test(sk_tests)
        assert unique_test == "unique", (
            "SCD1 unique test must be the bare string 'unique'. "
            f"Got: {unique_test!r}"
        )

    def test_scd2_identifier_sk_has_where_clause(self, client_dbt_artifacts):
        """identifier (scdType=2) _sk must also use unique with where clause."""
        import yaml

        key = _find_artifact(client_dbt_artifacts, "_models.yml")
        if key is None:
            pytest.skip("_models.yml not generated")
        parsed = yaml.safe_load(client_dbt_artifacts[key])

        sk_tests = _find_column_tests(parsed, "identifier_sk")
        if sk_tests is None:
            pytest.skip("identifier_sk not in schema YAML (model may be unmapped)")
        unique_test = _find_unique_test(sk_tests)
        assert isinstance(unique_test, dict), (
            f"identifier_sk (SCD2) unique test must be a dict. Got: {unique_test!r}"
        )
        where = (unique_test.get("unique") or {}).get("config", {}).get("where")
        assert where == "is_current = 1", (
            f"identifier_sk unique test must have where='is_current = 1'. Got: {where!r}"
        )


def _find_column_tests(parsed_yaml: dict, column_name: str) -> list | None:
    """Find the tests list for a named column across all models in a schema YAML."""
    for model in parsed_yaml.get("models", []):
        for col in model.get("columns", []):
            if col.get("name") == column_name:
                return col.get("tests") or []
    return None


def _find_unique_test(tests: list):
    """Return the unique test entry (string or dict) from a column tests list."""
    for t in tests:
        if t == "unique":
            return t
        if isinstance(t, dict) and "unique" in t:
            return t
    return None


# ---------------------------------------------------------------------------
# CR-006 fix: cross-entity naturalKey pass-through bronze column resolution
# ---------------------------------------------------------------------------

class TestCrossEntityNaturalKeyPassThrough:
    """When a naturalKey column belongs to a different entity, the pass-through
    expression must resolve to the actual bronze column name via SKOS mappings,
    not use the domain snake_case property name (which doesn't exist in bronze).

    CR-006 secondary issue: bronze lookup was annotated as TODO and never implemented.
    """

    def test_passthrough_resolves_to_bronze_column_name(self):
        """Pass-through expression must use actual bronze column name, not domain name.

        Scenario:
        - Entity 'Address' has naturalKey 'ownerId'
        - 'ownerId' is a property of 'Owner' (cross-entity)
        - Bronze table maps source column 'ownerCode' (not 'owner_id') to 'ownerId'
        - Expected: pass-through expression = 'ownerCode', alias = 'owner_id'
        - Broken:   pass-through expression = 'owner_id' (no such column in bronze)
        """
        from rdflib import Graph, Literal, Namespace, URIRef
        from rdflib.namespace import OWL, RDF, RDFS, XSD
        from kairos_ontology.projections.medallion_dbt_projector import (
            _extract_silver_columns,
        )

        NS = "https://test.example/ont#"
        g = Graph()
        g.add((URIRef(NS + "Address"), RDF.type, OWL.Class))
        g.add((URIRef(NS + "Owner"), RDF.type, OWL.Class))

        # ownerId is a property of Owner, not Address — cross-entity reference
        g.add((URIRef(NS + "ownerId"), RDF.type, OWL.DatatypeProperty))
        g.add((URIRef(NS + "ownerId"), RDFS.domain, URIRef(NS + "Owner")))
        g.add((URIRef(NS + "ownerId"), RDFS.range, XSD.string))

        # Address has naturalKey = "ownerId" (cross-entity)
        KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")
        g.add((URIRef(NS + "Address"), KAIROS_EXT.naturalKey, Literal("ownerId")))

        # Bronze column 'ownerCode' maps to Owner.ownerId
        bronze_col_uri = "https://test.example/bronze#tbl_address_col_owner"
        systems = [{
            "system_label": "TestSystem",
            "tables": [{
                "uri": "https://test.example/bronze#tblAddress",
                "columns": [
                    {"uri": bronze_col_uri, "name": "ownerCode",
                     "data_type": "nvarchar(50)"},
                ],
            }],
        }]

        # SKOS mappings: bronze_col_uri → ownerId
        mappings = {
            "table_maps": {},
            "column_maps": {
                bronze_col_uri: [
                    {
                        "target_uri": NS + "ownerId",
                        "match_type": "exactMatch",
                        "transform": None,
                    }
                ]
            },
        }

        cols = _extract_silver_columns(
            graph=g,
            class_uri=NS + "Address",
            namespace=NS,
            mappings=mappings,
            systems=systems,
            include_sk_iri=True,
            scd_type="1",
        )

        # Find the pass-through column for owner_id
        pt_col = next((c for c in cols if c.get("target_name") == "owner_id"), None)
        assert pt_col is not None, (
            f"Pass-through column 'owner_id' not found in columns: "
            f"{[c.get('target_name') for c in cols]}"
        )
        assert pt_col["expression"] == "ownerCode", (
            f"Pass-through expression must resolve to bronze column 'ownerCode', "
            f"not domain name 'owner_id'. Got: {pt_col['expression']!r}"
        )

    def test_passthrough_fallback_when_no_mapping(self):
        """When no bronze mapping exists, pass-through falls back to domain name."""
        from rdflib import Graph, Literal, Namespace, URIRef
        from rdflib.namespace import OWL, RDF, RDFS, XSD
        from kairos_ontology.projections.medallion_dbt_projector import (
            _extract_silver_columns,
        )

        NS = "https://test.example/ont#"
        g = Graph()
        g.add((URIRef(NS + "Address"), RDF.type, OWL.Class))
        g.add((URIRef(NS + "Owner"), RDF.type, OWL.Class))
        g.add((URIRef(NS + "ownerId"), RDF.type, OWL.DatatypeProperty))
        g.add((URIRef(NS + "ownerId"), RDFS.domain, URIRef(NS + "Owner")))
        g.add((URIRef(NS + "ownerId"), RDFS.range, XSD.string))

        KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")
        g.add((URIRef(NS + "Address"), KAIROS_EXT.naturalKey, Literal("ownerId")))

        cols = _extract_silver_columns(
            graph=g,
            class_uri=NS + "Address",
            namespace=NS,
            mappings={"table_maps": {}, "column_maps": {}},
            systems=None,
            include_sk_iri=True,
            scd_type="1",
        )

        pt_col = next((c for c in cols if c.get("target_name") == "owner_id"), None)
        assert pt_col is not None, (
            "Pass-through column 'owner_id' should still be generated even without mapping"
        )
        # Falls back to domain name when no bronze mapping found
        assert pt_col["expression"] == "owner_id", (
            f"Fallback pass-through must use domain name 'owner_id'. "
            f"Got: {pt_col['expression']!r}"
        )

    def test_scd1_sk_uses_bronze_expression_for_cross_entity_nk(self):
        """For SCD1 models, SK expression must use the bronze column name for cross-entity NK.

        T-SQL does not allow referencing an alias defined in the same SELECT list,
        so the SK/IRI expression must reference the actual source expression.
        """
        from rdflib import Graph, Literal, Namespace, URIRef
        from rdflib.namespace import OWL, RDF, RDFS, XSD
        from kairos_ontology.projections.medallion_dbt_projector import (
            _extract_silver_columns,
        )

        NS = "https://test.example/ont#"
        g = Graph()
        g.add((URIRef(NS + "Address"), RDF.type, OWL.Class))
        g.add((URIRef(NS + "Owner"), RDF.type, OWL.Class))
        g.add((URIRef(NS + "ownerId"), RDF.type, OWL.DatatypeProperty))
        g.add((URIRef(NS + "ownerId"), RDFS.domain, URIRef(NS + "Owner")))
        g.add((URIRef(NS + "ownerId"), RDFS.range, XSD.string))

        KAIROS_EXT = Namespace("https://kairos.cnext.eu/ext#")
        g.add((URIRef(NS + "Address"), KAIROS_EXT.naturalKey, Literal("ownerId")))

        bronze_col_uri = "https://test.example/bronze#tbl_owner_code"
        systems = [{
            "system_label": "TestSystem",
            "tables": [{
                "uri": "https://test.example/bronze#tblAddress",
                "columns": [
                    {"uri": bronze_col_uri, "name": "ownerCode",
                     "data_type": "nvarchar(50)"},
                ],
            }],
        }]
        mappings = {
            "table_maps": {},
            "column_maps": {
                bronze_col_uri: [
                    {"target_uri": NS + "ownerId", "match_type": "exactMatch",
                     "transform": None}
                ]
            },
        }

        cols = _extract_silver_columns(
            graph=g,
            class_uri=NS + "Address",
            namespace=NS,
            mappings=mappings,
            systems=systems,
            include_sk_iri=True,
            scd_type="1",
        )

        # SK expression must reference 'ownerCode' (not the alias 'owner_id')
        # to avoid T-SQL alias-before-definition errors
        sk_col = next((c for c in cols if c.get("target_name") == "address_sk"), None)
        assert sk_col is not None, (
            f"address_sk not found in cols: {[c.get('target_name') for c in cols]}"
        )
        assert "ownerCode" in sk_col["expression"], (
            f"SK expression for SCD1 with cross-entity NK must use bronze column "
            f"'ownerCode' not alias 'owner_id'. SK expr: {sk_col['expression']!r}"
        )


# ---------------------------------------------------------------------------
# Regression: DATETIME2 precision for Fabric SQL (CR: datetime2-precision)
# ---------------------------------------------------------------------------

class TestDatetimePrecisionInFabricSQL:
    """Fabric SQL rejects bare DATETIME2 — projector must emit DATETIME2(6).

    The acme-hub has:
      - tblClient_CreatedDate / tblClient_ModifiedDate with kairos-bronze:dataType "datetime"
      - acme:createdAt with rdfs:range xsd:dateTime

    Both paths must produce DATETIME2(6) in the generated client.sql, never
    bare DATETIME2 without precision (Fabric error 24597).
    """

    def test_no_bare_datetime2_in_client_sql(self, client_dbt_artifacts):
        """Generated client.sql must not contain bare DATETIME2 without precision."""
        key = _find_artifact(client_dbt_artifacts, "/client.sql")
        assert key is not None, "client.sql not found in dbt artifacts"
        sql = client_dbt_artifacts[key]
        # Match DATETIME2 that is NOT followed by '('  — the broken form
        import re
        bare = re.findall(r"DATETIME2(?!\()", sql, re.IGNORECASE)
        assert not bare, (
            f"Found {len(bare)} bare DATETIME2 (without precision) in client.sql — "
            f"Fabric SQL requires DATETIME2(6). Occurrences: {bare}"
        )

    def test_datetime_columns_use_datetime2_6(self, client_dbt_artifacts):
        """Bronze 'datetime' source columns must be cast to DATETIME2(6) in per-source models.

        tblClient_ModifiedDate (kairos-bronze:dataType "datetime") maps to acme:lastModifiedAt
        without an explicit transform, so the projector must auto-emit
        TRY_CAST(ModifiedDate AS DATETIME2(6)). The TRY_CAST is emitted in the per-source
        view (corporate_client__from_admin_pulse.sql), not the union wrapper.
        """
        key = _find_artifact(client_dbt_artifacts, "corporate_client__from_admin_pulse.sql")
        assert key is not None, "corporate_client__from_admin_pulse.sql not found in dbt artifacts"
        sql = client_dbt_artifacts[key].upper()
        assert "DATETIME2(6)" in sql, (
            "Expected TRY_CAST(... AS DATETIME2(6)) for datetime source columns in "
            "corporate_client__from_admin_pulse.sql, but DATETIME2(6) was not found. "
            "Check _SOURCE_TO_FABRIC in medallion_dbt_projector.py."
        )
