# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for the integration projector with kairos-int: annotations.

Validates that kairos-int: annotations from the client-integration-ext.ttl flow
through to the generated mapping JSON, including ontology-level defaults,
class-level overrides, and property-level validation/coercion rules.
"""

import json
from pathlib import Path

import pytest

from .conftest import EXTENSIONS_DIR, MAPPINGS_DIR, SOURCES_DIR, TEMPLATE_DIR


@pytest.fixture(scope="module")
def client_integration_artifacts():
    """Generate integration artifacts for the client domain with integration-ext."""
    from .conftest import _load_ontology

    graph, namespace, classes = _load_ontology("client")

    from kairos_ontology.projections.integration_projector import (
        generate_integration_artifacts,
    )

    silver_ext = EXTENSIONS_DIR / "client-silver-ext.ttl"
    int_ext = EXTENSIONS_DIR / "client-integration-ext.ttl"
    return generate_integration_artifacts(
        classes=classes,
        graph=graph,
        template_dir=TEMPLATE_DIR,
        namespace=namespace,
        ontology_name="client",
        sources_dir=SOURCES_DIR,
        mappings_dir=MAPPINGS_DIR,
        silver_ext_path=silver_ext if silver_ext.exists() else None,
        integration_ext_path=int_ext if int_ext.exists() else None,
    )


def _get_mapping(artifacts: dict, entity_name: str) -> dict | None:
    """Find a mapping JSON for a given entity name."""
    for key, content in artifacts.items():
        if key.endswith("-mapping.json"):
            doc = json.loads(content)
            if doc.get("metadata", {}).get("entity") == entity_name:
                return doc
    return None


# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------


class TestSchemaVersion:
    """Verify schema was bumped to v2 when integration section is present."""

    def test_schema_v2(self, client_integration_artifacts):
        for key, content in client_integration_artifacts.items():
            if key.endswith("-mapping.json"):
                doc = json.loads(content)
                assert doc["$schema"].endswith("/v2"), (
                    f"{key}: expected schema v2, got {doc['$schema']}"
                )


# ---------------------------------------------------------------------------
# Class-level integration annotations
# ---------------------------------------------------------------------------


class TestClassLevelIntegration:
    """Class-level kairos-int: annotations flow to mapping JSON."""

    def test_client_load_strategy(self, client_integration_artifacts):
        mapping = _get_mapping(client_integration_artifacts, "Client")
        if mapping is None:
            pytest.skip("No Client mapping found")
        int_meta = mapping.get("integration", {})
        assert int_meta.get("load_strategy") == "incremental"

    def test_client_incremental_watermark(self, client_integration_artifacts):
        mapping = _get_mapping(client_integration_artifacts, "Client")
        if mapping is None:
            pytest.skip("No Client mapping found")
        int_meta = mapping.get("integration", {})
        assert int_meta.get("incremental_watermark") == "createdAt"

    def test_client_batch_size_override(self, client_integration_artifacts):
        mapping = _get_mapping(client_integration_artifacts, "Client")
        if mapping is None:
            pytest.skip("No Client mapping found")
        int_meta = mapping.get("integration", {})
        assert int_meta.get("batch_size") == 1000

    def test_client_priority(self, client_integration_artifacts):
        mapping = _get_mapping(client_integration_artifacts, "Client")
        if mapping is None:
            pytest.skip("No Client mapping found")
        int_meta = mapping.get("integration", {})
        assert int_meta.get("priority") == 10

    def test_client_validation_mode(self, client_integration_artifacts):
        mapping = _get_mapping(client_integration_artifacts, "Client")
        if mapping is None:
            pytest.skip("No Client mapping found")
        int_meta = mapping.get("integration", {})
        assert int_meta.get("validation_mode") == "strict"

    def test_client_post_load_hook(self, client_integration_artifacts):
        mapping = _get_mapping(client_integration_artifacts, "Client")
        if mapping is None:
            pytest.skip("No Client mapping found")
        int_meta = mapping.get("integration", {})
        assert int_meta.get("post_load_hook") == "notify-downstream"


# ---------------------------------------------------------------------------
# Ontology-level defaults inherited by entities without overrides
# ---------------------------------------------------------------------------


class TestOntologyDefaults:
    """Ontology-level defaults flow through for un-overridden entities."""

    def test_default_error_strategy(self, client_integration_artifacts):
        mapping = _get_mapping(client_integration_artifacts, "ClientType")
        if mapping is None:
            pytest.skip("No ClientType mapping found")
        int_meta = mapping.get("integration", {})
        # ClientType has no errorStrategy override → inherits ontology default
        assert int_meta.get("error_strategy") == "dead-letter"

    def test_default_batch_size_inherited(self, client_integration_artifacts):
        mapping = _get_mapping(client_integration_artifacts, "ClientType")
        if mapping is None:
            pytest.skip("No ClientType mapping found")
        int_meta = mapping.get("integration", {})
        # ClientType has no batchSize override → inherits 500
        assert int_meta.get("batch_size") == 500

    def test_clienttype_priority(self, client_integration_artifacts):
        mapping = _get_mapping(client_integration_artifacts, "ClientType")
        if mapping is None:
            pytest.skip("No ClientType mapping found")
        int_meta = mapping.get("integration", {})
        assert int_meta.get("priority") == 1


# ---------------------------------------------------------------------------
# Property-level integration annotations
# ---------------------------------------------------------------------------


class TestPropertyLevelIntegration:
    """Property-level kairos-int: annotations appear in column_mappings."""

    def test_email_sensitive_data(self, client_integration_artifacts):
        mapping = _get_mapping(client_integration_artifacts, "Client")
        if mapping is None:
            pytest.skip("No Client mapping found")
        email_cols = [
            c for c in mapping.get("column_mappings", [])
            if c.get("target_property") == "email"
        ]
        if not email_cols:
            pytest.skip("No email column mapping found")
        int_annot = email_cols[0].get("integration", {})
        assert int_annot.get("sensitive_data") is True

    def test_email_validation_rule(self, client_integration_artifacts):
        mapping = _get_mapping(client_integration_artifacts, "Client")
        if mapping is None:
            pytest.skip("No Client mapping found")
        email_cols = [
            c for c in mapping.get("column_mappings", [])
            if c.get("target_property") == "email"
        ]
        if not email_cols:
            pytest.skip("No email column mapping found")
        int_annot = email_cols[0].get("integration", {})
        assert "LENGTH(value) <= 254" in int_annot.get("validation_rule", "")

    def test_vat_coercion_rule(self, client_integration_artifacts):
        mapping = _get_mapping(client_integration_artifacts, "Client")
        if mapping is None:
            pytest.skip("No Client mapping found")
        vat_cols = [
            c for c in mapping.get("column_mappings", [])
            if c.get("target_property") == "vatNumber"
        ]
        if not vat_cols:
            pytest.skip("No vatNumber column mapping found")
        int_annot = vat_cols[0].get("integration", {})
        assert int_annot.get("coercion_rule") == "TRIM(UPPER(value))"


# ---------------------------------------------------------------------------
# Integration section always present (even with defaults)
# ---------------------------------------------------------------------------


class TestIntegrationSectionPresent:
    """Every mapping doc has an 'integration' section."""

    def test_all_mappings_have_integration(self, client_integration_artifacts):
        for key, content in client_integration_artifacts.items():
            if key.endswith("-mapping.json"):
                doc = json.loads(content)
                assert "integration" in doc, (
                    f"{key}: missing 'integration' section"
                )
                assert isinstance(doc["integration"], dict)
