# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario tests for Reference Model Inspired strategy (DD-032).

These tests verify that:
1. Locally-adopted classes (Identifier pattern) produce silver tables correctly.
2. Alignment files in model/alignments/ are NOT loaded by the projection pipeline.
3. The Inspired approach is functionally equivalent to any other local class for
   projection purposes — no special handling needed.
"""

import pytest
from rdflib import Graph, Namespace, RDF, OWL

from kairos_ontology.projections.medallion_silver_projector import (
    generate_silver_artifacts,
)

from .conftest import EXTENSIONS_DIR, SHAPES_DIR, ALIGNMENTS_DIR


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
# Tests: Alignment file is NOT loaded during projection
# ---------------------------------------------------------------------------

class TestAlignmentFileIsolation:
    """Alignment files must never be loaded by the projection pipeline."""

    def test_alignment_file_exists(self):
        """Verify the alignment file is present in the fixture."""
        alignment = ALIGNMENTS_DIR / "client-fibo-alignment.ttl"
        assert alignment.exists(), (
            "Test fixture missing: model/alignments/client-fibo-alignment.ttl"
        )

    def test_alignment_not_in_projection_graph(self, client_ontology):
        """The projection graph should NOT contain FIBO URIs from the alignment file."""
        graph, namespace, classes = client_ontology
        fibo_ns = "https://spec.edmcouncil.org/fibo/"
        fibo_triples = [
            s for s in graph.subjects()
            if isinstance(s, (str,)) and fibo_ns in str(s)
        ]
        # Also check as URIRef
        from rdflib import URIRef
        fibo_subjects = [
            s for s in graph.subjects()
            if isinstance(s, URIRef) and fibo_ns in str(s)
        ]
        assert len(fibo_subjects) == 0, (
            f"Projection graph contains FIBO URIs — alignment file was loaded! "
            f"Found: {fibo_subjects[:3]}"
        )

    def test_skos_match_not_in_projection_graph(self, client_ontology):
        """No skos:exactMatch or skos:closeMatch triples should be in the projection graph."""
        graph, namespace, classes = client_ontology
        SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
        exact_matches = list(graph.triples((None, SKOS.exactMatch, None)))
        close_matches = list(graph.triples((None, SKOS.closeMatch, None)))
        assert len(exact_matches) == 0, (
            f"Projection graph has skos:exactMatch triples — alignment file was loaded! "
            f"Found: {exact_matches[:3]}"
        )
        assert len(close_matches) == 0, (
            f"Projection graph has skos:closeMatch triples — alignment file was loaded! "
            f"Found: {close_matches[:3]}"
        )

    def test_alignment_file_is_valid_turtle(self):
        """The alignment file should parse as valid Turtle."""
        alignment = ALIGNMENTS_DIR / "client-fibo-alignment.ttl"
        g = Graph()
        g.parse(alignment, format="turtle")
        # Should have an owl:Ontology declaration
        ontologies = list(g.subjects(RDF.type, OWL.Ontology))
        assert len(ontologies) == 1, "Alignment file should declare exactly one owl:Ontology"

    def test_alignment_has_skos_mappings(self):
        """The alignment file should contain SKOS match predicates."""
        alignment = ALIGNMENTS_DIR / "client-fibo-alignment.ttl"
        g = Graph()
        g.parse(alignment, format="turtle")
        SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
        exact = list(g.triples((None, SKOS.exactMatch, None)))
        close = list(g.triples((None, SKOS.closeMatch, None)))
        assert len(exact) + len(close) > 0, (
            "Alignment file should have at least one skos:exactMatch or skos:closeMatch"
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
