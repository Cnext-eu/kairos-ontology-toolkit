# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for Reference Model Inspired strategy (DD-032).

These tests verify that:
1. Locally-adopted classes (Identifier pattern) produce silver tables correctly.
2. rdfs:seeAlso back-references are present on inspired classes but ignored by projectors.
3. The Inspired approach is functionally equivalent to any other local class for
   projection purposes — no special handling needed.
"""

import pytest
from rdflib import Graph, Namespace, RDFS, URIRef

from kairos_ontology.projections.medallion_silver_projector import (
    generate_silver_artifacts,
)

from .conftest import EXTENSIONS_DIR, SHAPES_DIR, ONTOLOGIES_DIR


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client_silver_with_identifier(client_ontology):
    """Generate silver artifacts for client domain (includes Identifier pattern)."""
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


# ---------------------------------------------------------------------------
# Tests: Reference Model Inspired — Identifier pattern produces silver table
# ---------------------------------------------------------------------------

class TestInspiredIdentifierPattern:
    """The locally-adopted Identifier class should project like any local class."""

    def test_identifier_table_in_ddl(self, client_silver_with_identifier):
        """Identifier class should produce a CREATE TABLE in silver DDL."""
        ddl_key = _find_artifact(client_silver_with_identifier, ".sql")
        assert ddl_key is not None, "No DDL SQL artifact generated"
        ddl = client_silver_with_identifier[ddl_key].lower()
        assert "identifier" in ddl, (
            "DDL missing 'identifier' table — the Inspired Identifier pattern "
            "should produce a separate silver table"
        )

    def test_identifier_has_value_column(self, client_silver_with_identifier):
        """The identifier table should have identifier_value column."""
        ddl_key = _find_artifact(client_silver_with_identifier, ".sql")
        ddl = client_silver_with_identifier[ddl_key].lower()
        assert "identifier_value" in ddl, "DDL missing identifier_value column"

    def test_identifier_has_scheme_column(self, client_silver_with_identifier):
        """The identifier table should have identifier_scheme column."""
        ddl_key = _find_artifact(client_silver_with_identifier, ".sql")
        ddl = client_silver_with_identifier[ddl_key].lower()
        assert "identifier_scheme" in ddl, "DDL missing identifier_scheme column"

    def test_identifier_in_erd(self, client_silver_with_identifier):
        """The ERD should include the Identifier entity."""
        erd_key = _find_artifact(client_silver_with_identifier, ".mmd")
        if erd_key is None:
            pytest.skip("No ERD artifact generated")
        erd = client_silver_with_identifier[erd_key]
        assert "Identifier" in erd or "identifier" in erd.lower(), (
            "ERD missing Identifier entity"
        )


# ---------------------------------------------------------------------------
# Tests: rdfs:seeAlso back-reference — present but ignored by projectors
# ---------------------------------------------------------------------------

class TestSeeAlsoBackReference:
    """rdfs:seeAlso on inspired classes provides traceability without affecting projections."""

    def test_see_also_present_on_identifier(self):
        """The Identifier class should have rdfs:seeAlso pointing to the FIBO URI."""
        g = Graph()
        g.parse(ONTOLOGIES_DIR / "client.ttl", format="turtle")
        acme = Namespace("https://acme.example/ontology/client#")
        see_also = list(g.objects(acme.Identifier, RDFS.seeAlso))
        assert len(see_also) >= 1, (
            "Identifier class should have rdfs:seeAlso linking to reference model"
        )
        fibo_uri = URIRef(
            "https://spec.edmcouncil.org/fibo/ontology/FND/Arrangements/"
            "Identifiers/Identifier"
        )
        assert fibo_uri in see_also, (
            f"Expected rdfs:seeAlso to point to FIBO Identifier URI, got: {see_also}"
        )

    def test_see_also_not_in_silver_output(self, client_silver_with_identifier):
        """Silver projection output should NOT contain rdfs:seeAlso targets."""
        ddl_key = _find_artifact(client_silver_with_identifier, ".sql")
        ddl = client_silver_with_identifier[ddl_key].lower()
        assert "seealso" not in ddl, "rdfs:seeAlso should not appear in silver DDL"
        assert "fibo" not in ddl, "FIBO URIs should not appear in silver DDL"

    def test_projection_graph_excludes_fibo_uris(self, client_ontology):
        """The projection graph should NOT contain FIBO URIs from rdfs:seeAlso."""
        graph, namespace, classes = client_ontology
        fibo_ns = "https://spec.edmcouncil.org/fibo/"
        from rdflib import URIRef
        fibo_subjects = [
            s for s in graph.subjects()
            if isinstance(s, URIRef) and fibo_ns in str(s)
        ]
        assert len(fibo_subjects) == 0, (
            f"Projection graph contains FIBO URIs as subjects — "
            f"rdfs:seeAlso should be an opaque annotation. Found: {fibo_subjects[:3]}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_artifact(artifacts: dict, suffix: str) -> str | None:
    """Find the first artifact key with the given suffix."""
    for key in artifacts:
        if key.endswith(suffix):
            return key
    return None
