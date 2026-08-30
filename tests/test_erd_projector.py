# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit and CLI-level tests for the binding-independent ERD projector (issue #631)."""


from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, OWL, XSD

from kairos_ontology.core.projections.erd_projector import generate_erd_artifacts
from kairos_ontology.core.projector import run_projections

NS = "http://example.com/order#"
ORDER = Namespace(NS)


def _base_graph() -> Graph:
    """A domain graph with classes, datatype properties, and one relationship --
    no EntityBinding, no compile-plan, no DDD overlay vocabulary anywhere."""
    g = Graph()
    g.add((ORDER.Customer, RDF.type, OWL.Class))
    g.add((ORDER.Customer, RDFS.label, Literal("Customer")))
    g.add((ORDER.Order, RDF.type, OWL.Class))
    g.add((ORDER.Order, RDFS.label, Literal("Order")))

    g.add((ORDER.customerName, RDF.type, OWL.DatatypeProperty))
    g.add((ORDER.customerName, RDFS.domain, ORDER.Customer))
    g.add((ORDER.customerName, RDFS.range, XSD.string))

    g.add((ORDER.places, RDF.type, OWL.ObjectProperty))
    g.add((ORDER.places, RDFS.domain, ORDER.Customer))
    g.add((ORDER.places, RDFS.range, ORDER.Order))
    return g


class TestBindingIndependentRendering:
    def test_produces_non_empty_erd_without_ddd_or_binding_annotations(self):
        artifacts = generate_erd_artifacts(_base_graph(), NS, "order")

        assert artifacts
        content = artifacts["order-erd.mmd"]
        assert content.strip()
        assert "erDiagram" in content
        assert "Customer" in content
        assert "Order" in content
        assert "places" in content

    def test_empty_graph_yields_no_artifacts(self):
        assert generate_erd_artifacts(Graph(), NS, "empty") == {}

    def test_class_with_no_relationships_still_renders_as_an_entity(self):
        g = Graph()
        g.add((ORDER.Orphan, RDF.type, OWL.Class))

        artifacts = generate_erd_artifacts(g, NS, "order")

        content = artifacts["order-erd.mmd"]
        assert "Orphan {" in content
        assert "string uri" in content

    def test_only_domain_local_classes_are_rendered(self):
        g = _base_graph()
        other_ns = Namespace("http://example.com/other#")
        g.add((other_ns.Unrelated, RDF.type, OWL.Class))

        artifacts = generate_erd_artifacts(g, NS, "order")

        content = artifacts["order-erd.mmd"]
        assert "Unrelated" not in content


class TestDeterminism:
    def test_same_input_produces_byte_identical_output(self):
        first = generate_erd_artifacts(_base_graph(), NS, "order")
        second = generate_erd_artifacts(_base_graph(), NS, "order")

        assert first == second
        assert first["order-erd.mmd"].encode("utf-8") == second["order-erd.mmd"].encode("utf-8")

    def test_output_is_sorted_regardless_of_triple_insertion_order(self):
        forward = _base_graph()

        reversed_graph = Graph()
        for triple in reversed(list(forward)):
            reversed_graph.add(triple)

        assert generate_erd_artifacts(forward, NS, "order") == generate_erd_artifacts(
            reversed_graph, NS, "order"
        )


class TestCardinalityRestrictions:
    def test_exact_cardinality_restriction_renders_as_exactly_one(self):
        g = _base_graph()
        restriction = BNode()
        g.add((restriction, RDF.type, OWL.Restriction))
        g.add((restriction, OWL.onProperty, ORDER.places))
        g.add((restriction, OWL.cardinality, Literal(1)))
        g.add((ORDER.Customer, RDFS.subClassOf, restriction))

        content = generate_erd_artifacts(g, NS, "order")["order-erd.mmd"]

        relationship_line = next(line for line in content.splitlines() if ": places" in line)
        assert "--||" in relationship_line

    def test_min_zero_max_many_restriction_renders_as_zero_or_more(self):
        g = _base_graph()
        restriction = BNode()
        g.add((restriction, RDF.type, OWL.Restriction))
        g.add((restriction, OWL.onProperty, ORDER.places))
        g.add((restriction, OWL.minCardinality, Literal(0)))
        g.add((ORDER.Customer, RDFS.subClassOf, restriction))

        content = generate_erd_artifacts(g, NS, "order")["order-erd.mmd"]

        relationship_line = next(line for line in content.splitlines() if ": places" in line)
        assert "--o{" in relationship_line

    def test_functional_property_without_restriction_renders_as_at_most_one(self):
        g = _base_graph()
        g.add((ORDER.places, RDF.type, OWL.FunctionalProperty))

        content = generate_erd_artifacts(g, NS, "order")["order-erd.mmd"]

        relationship_line = next(line for line in content.splitlines() if ": places" in line)
        # Functional (max-cardinality-one) without an explicit min defaults to
        # "zero or one" on the range side -- distinct from the unconstrained default
        # ("zero or more", "--o{").
        assert "--o|" in relationship_line
        assert "--o{" not in relationship_line


class TestCliLevelProjection:
    """End-to-end ``project --target erd`` coverage, mirroring how the flat
    ``neo4j``/``azure-search`` targets are exercised in test_projector.py."""

    def test_target_erd_writes_architecture_erd_directory(self, temp_dir, ontology_files):
        output_dir = temp_dir / "output"

        run_projections(
            ontologies_path=ontology_files["dir"],
            catalog_path=None,
            output_path=output_dir,
            target="erd",
        )

        erd_dir = output_dir / "architecture" / "erd"
        assert erd_dir.exists()
        mmd_files = sorted(erd_dir.glob("*-erd.mmd"))
        assert mmd_files
        content = mmd_files[0].read_text(encoding="utf-8")
        assert "erDiagram" in content

    def test_erd_is_included_in_target_all(self, temp_dir, ontology_files):
        output_dir = temp_dir / "output"

        run_projections(
            ontologies_path=ontology_files["dir"],
            catalog_path=None,
            output_path=output_dir,
            target="all",
        )

        assert (output_dir / "architecture" / "erd").exists()
