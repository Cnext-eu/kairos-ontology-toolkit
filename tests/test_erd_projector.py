# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit and CLI-level tests for the binding-independent ERD projector (issue #631)."""


from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, OWL, XSD

from kairos_ontology.core.projections.erd_projector import generate_erd_artifacts
from kairos_ontology.core.projector import run_projections

NS = "http://example.com/order#"
ORDER = Namespace(NS)
#: An imported reference model, outside the domain namespace.
REF = Namespace("https://example.test/ont/ref#")


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
        assert "classDiagram" in content
        assert "Customer" in content
        assert "Order" in content
        assert "places" in content

    def test_empty_graph_yields_no_artifacts(self):
        assert generate_erd_artifacts(Graph(), NS, "empty") == {}

    def test_class_with_no_relationships_still_renders_as_a_class(self):
        g = Graph()
        g.add((ORDER.Orphan, RDF.type, OWL.Class))

        artifacts = generate_erd_artifacts(g, NS, "order")

        content = artifacts["order-erd.mmd"]
        assert "class Orphan {" in content
        assert "string uri" in content

    def test_only_domain_local_classes_are_rendered(self):
        g = _base_graph()
        other_ns = Namespace("http://example.com/other#")
        g.add((other_ns.Unrelated, RDF.type, OWL.Class))

        artifacts = generate_erd_artifacts(g, NS, "order")

        content = artifacts["order-erd.mmd"]
        assert "Unrelated" not in content


class TestInheritance:
    def test_named_subclass_of_renders_as_inheritance_edge(self):
        g = _base_graph()
        g.add((ORDER.VipCustomer, RDF.type, OWL.Class))
        g.add((ORDER.VipCustomer, RDFS.subClassOf, ORDER.Customer))

        content = generate_erd_artifacts(g, NS, "order")["order-erd.mmd"]

        assert "Customer <|-- VipCustomer" in content

    def test_restriction_subclass_of_is_not_rendered_as_inheritance(self):
        # A blank-node restriction subject is cardinality metadata (see
        # TestCardinalityRestrictions below), never a superclass -- it must not
        # produce a spurious inheritance edge.
        g = _base_graph()
        restriction = BNode()
        g.add((restriction, RDF.type, OWL.Restriction))
        g.add((restriction, OWL.onProperty, ORDER.places))
        g.add((restriction, OWL.cardinality, Literal(1)))
        g.add((ORDER.Customer, RDFS.subClassOf, restriction))

        content = generate_erd_artifacts(g, NS, "order")["order-erd.mmd"]

        assert "<|--" not in content


class TestImportedReferenceModels:
    """#678/#704: the modeling style `kairos-design-domain` recommends.

    A hub's classes specialize imported reference-model classes, so every superclass
    lives outside the domain namespace. Requiring both ends of an inheritance edge to be
    namespace-local made the edge unreachable in exactly that case -- on a real hub, 1 of
    29 edges and 63 of 237 properties rendered -- which left DD-212's stated reason for
    choosing `classDiagram` over `erDiagram` inert.
    """

    @staticmethod
    def _graph():
        g = _base_graph()
        g.add((REF.TradeParty, RDF.type, OWL.Class))
        g.add((REF.legalName, RDF.type, OWL.DatatypeProperty))
        g.add((REF.legalName, RDFS.domain, REF.TradeParty))
        g.add((REF.legalName, RDFS.range, XSD.string))
        g.add((REF.Address, RDF.type, OWL.Class))
        g.add((REF.hasAddress, RDF.type, OWL.ObjectProperty))
        g.add((REF.hasAddress, RDFS.domain, REF.TradeParty))
        g.add((REF.hasAddress, RDFS.range, REF.Address))
        g.add((ORDER.Customer, RDFS.subClassOf, REF.TradeParty))
        return g

    def _content(self):
        return generate_erd_artifacts(self._graph(), NS, "order")["order-erd.mmd"]

    def test_an_imported_superclass_renders_an_inheritance_edge(self):
        assert "TradeParty <|-- Customer" in self._content()

    def test_an_imported_superclass_renders_as_a_stereotyped_stub(self):
        content = self._content()
        assert "class TradeParty {" in content
        assert "<<ont/ref>>" in content
        # A stub lists no members of its own: they are shown on the classes that
        # inherit them, so repeating them here would double every inherited attribute.
        block = content.split("class TradeParty {")[1].split("}")[0]
        assert "legalName" not in block

    def test_inherited_attributes_are_rendered_and_marked(self):
        content = self._content()
        assert "        #string legalName" in content
        # The subclass's own attribute stays unmarked.
        assert "        string customerName" in content

    def test_inherited_relationships_are_rendered_from_the_subclass(self):
        """The subclass is the class whose instances carry the relationship."""
        content = self._content()
        assert "Customer" in content and "Address" in content
        assert "hasAddress (inherited)" in content

    def test_an_unrelated_imported_class_is_still_excluded(self):
        """Scoping is by reachability, not by "render everything imported"."""
        g = self._graph()
        other = Namespace("http://example.com/other#")
        g.add((other.Unrelated, RDF.type, OWL.Class))
        assert "Unrelated" not in generate_erd_artifacts(g, NS, "order")["order-erd.mmd"]

    def test_an_inherited_attribute_is_not_repeated_when_also_declared_locally(self):
        g = self._graph()
        g.add((ORDER.legalName, RDF.type, OWL.DatatypeProperty))
        g.add((ORDER.legalName, RDFS.domain, ORDER.Customer))
        g.add((ORDER.legalName, RDFS.range, XSD.string))
        content = generate_erd_artifacts(g, NS, "order")["order-erd.mmd"]
        assert content.count("legalName") == 2  # the local one, and the inherited one

    def test_a_subclass_cycle_terminates(self):
        """An imported model may assert a cycle; a documentation pass must not hang."""
        g = self._graph()
        g.add((REF.TradeParty, RDFS.subClassOf, REF.Party))
        g.add((REF.Party, RDF.type, OWL.Class))
        g.add((REF.Party, RDFS.subClassOf, REF.TradeParty))
        assert "TradeParty <|-- Customer" in generate_erd_artifacts(g, NS, "order")["order-erd.mmd"]

    def test_the_header_states_what_the_stub_convention_means(self):
        """The old header promised the diagram "reflects the ontology graph" while
        silently dropping everything outside the namespace, so absence read as
        non-existence. Whatever is omitted has to be stated."""
        content = self._content()
        assert "stub" in content
        assert "inherited" in content


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
        assert '--> "1" Order' in relationship_line

    def test_min_zero_max_many_restriction_renders_as_zero_or_more(self):
        g = _base_graph()
        restriction = BNode()
        g.add((restriction, RDF.type, OWL.Restriction))
        g.add((restriction, OWL.onProperty, ORDER.places))
        g.add((restriction, OWL.minCardinality, Literal(0)))
        g.add((ORDER.Customer, RDFS.subClassOf, restriction))

        content = generate_erd_artifacts(g, NS, "order")["order-erd.mmd"]

        relationship_line = next(line for line in content.splitlines() if ": places" in line)
        assert '--> "0..*" Order' in relationship_line

    def test_functional_property_without_restriction_renders_as_at_most_one(self):
        g = _base_graph()
        g.add((ORDER.places, RDF.type, OWL.FunctionalProperty))

        content = generate_erd_artifacts(g, NS, "order")["order-erd.mmd"]

        relationship_line = next(line for line in content.splitlines() if ": places" in line)
        # Functional (max-cardinality-one) without an explicit min defaults to
        # "zero or one" on the range side -- distinct from the unconstrained default
        # ("zero or more", "0..*").
        assert '--> "0..1" Order' in relationship_line
        assert '--> "0..*" Order' not in relationship_line


class TestOverlayExtension:
    """Plumbing-only ``{domain}-erd-ext.ttl`` overlay hook -- no packaged vocabulary
    exists yet, so this only proves the merge itself is live end-to-end."""

    def test_overlay_triples_are_merged_into_output(self, tmp_path):
        overlay = tmp_path / "order-erd-ext.ttl"
        overlay.write_text(
            f"""
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix order: <{NS}> .

            order:VipCustomer a owl:Class ;
                rdfs:subClassOf order:Customer .
            """,
            encoding="utf-8",
        )

        content = generate_erd_artifacts(_base_graph(), NS, "order", overlay_path=overlay)[
            "order-erd.mmd"
        ]

        assert "class VipCustomer {" in content
        assert "Customer <|-- VipCustomer" in content

    def test_missing_overlay_path_leaves_output_unchanged(self, tmp_path):
        missing = tmp_path / "order-erd-ext.ttl"

        with_missing_overlay = generate_erd_artifacts(_base_graph(), NS, "order", overlay_path=missing)
        without_overlay = generate_erd_artifacts(_base_graph(), NS, "order")

        assert with_missing_overlay == without_overlay


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
        assert "classDiagram" in content

    def test_written_mmd_uses_lf_endings_on_every_platform(self, temp_dir, ontology_files):
        """Projection output must be byte-identical across platforms.

        ``Path.write_text`` opens in text mode, so Python rewrote every ``\\n`` to
        ``\\r\\n`` on Windows and left it alone on Linux -- the same inputs produced
        different bytes per platform, churning ``git diff`` on every regeneration.

        Determinism is the whole argument. Issue #698's further claim that CRLF breaks
        Mermaid does not reproduce -- mermaid-cli 11.12.0 renders a fully CRLF ``.mmd``
        fine -- so this test deliberately asserts bytes, not renderability.
        """
        output_dir = temp_dir / "output"

        run_projections(
            ontologies_path=ontology_files["dir"],
            catalog_path=None,
            output_path=output_dir,
            target="erd",
        )

        mmd_files = sorted((output_dir / "architecture" / "erd").glob("*-erd.mmd"))
        assert mmd_files
        raw = mmd_files[0].read_bytes()
        assert raw.startswith(b"%%")
        assert b"\r" not in raw

    def test_erd_is_included_in_target_all(self, temp_dir, ontology_files):
        output_dir = temp_dir / "output"

        run_projections(
            ontologies_path=ontology_files["dir"],
            catalog_path=None,
            output_path=output_dir,
            target="all",
        )

        assert (output_dir / "architecture" / "erd").exists()
