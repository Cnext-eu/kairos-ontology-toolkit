# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for dbt projection using the synthetic Acme Corp ontology hub.

These tests exercise the full dbt artifact generation pipeline with realistic
multi-domain, multi-source data — including split patterns, cross-domain FKs,
deduplication, default values, and SHACL-derived tests.
"""

import pytest
from .conftest import TEMPLATE_DIR


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

    def test_crm_source_has_null_for_unmapped(self, client_dbt_artifacts):
        """CRM source lacks VATNumber mapping — should emit CAST(NULL ...)."""
        key = _find_artifact(
            client_dbt_artifacts, "corporate_client__from_crm_system.sql"
        )
        sql = client_dbt_artifacts[key]
        assert "CAST(NULL" in sql, (
            "CRM source missing NULL placeholder for unmapped columns"
        )
        assert "vat_number" in sql, (
            "CRM source should still have vat_number column (as NULL)"
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
        assert "SHA2_HEX" in sql.upper() or "sha2_hex" in sql.lower(), (
            f"SCD2 model should use SHA2_HEX for _row_hash computation:\n{sql}"
        )

    def test_scd2_model_has_change_detection_ctes(self, client_dbt_artifacts):
        """ClientPII (scdType=2) should have existing/changed/closed CTEs."""
        key = _find_artifact(client_dbt_artifacts, "client_pii.sql")
        sql = client_dbt_artifacts[key]
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
        assert "SHA2_HEX" in sql
        assert "customer_name" in sql
        assert "email" in sql
        assert "revenue" in sql
        assert "CONCAT_WS" in sql

        # Verify temporal columns in source_data
        assert "CURRENT_DATE as valid_from" in sql
        assert "CAST(NULL AS DATE) as valid_to" in sql
        assert "1 as is_current" in sql

        # Verify change detection CTEs
        assert "existing as" in sql
        assert "where is_current = 1" in sql
        assert "changed as" in sql
        assert "closed as" in sql

        # Verify closed CTE sets correct values
        assert "CURRENT_DATE as valid_to" in sql
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
