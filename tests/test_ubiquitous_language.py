# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The generated ubiquitous language and concept guide (DD-232).

One SKOS concept per hub class, linked to the ontology by exactMatch and to the industry
model by broadMatch, carrying overlay language, glossary synonyms, source names and Silver
status; one collection per bounded context, else per domain. The concept guide is the
human-readable counterpart. Both are derived, deterministic, timestamp-free, and emitted for
every hub by the `ddd` target.
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest
import yaml
from rdflib import SKOS, Graph, Literal, URIRef
from rdflib.namespace import RDF

from kairos_ontology.core.projections.concept_guide_projector import (
    CONCEPT_GUIDE_NAME,
    generate_concept_guide,
    render_concept_guide,
)
from kairos_ontology.core.projections.ddd_context_projector import ContextDomain
from kairos_ontology.core.projections.ubiquitous_language_projector import (
    UBIQUITOUS_LANGUAGE_NAME,
    build_language_model,
    generate_ubiquitous_language,
    language_inputs,
    render_ubiquitous_language,
)
from kairos_ontology.core.projector import _PROJECTION_MANIFEST_NAME, run_projections

ACME_HUB = Path(__file__).parent / "scenarios" / "acme-hub"
ONTOLOGIES = ACME_HUB / "model" / "ontologies"
EXTENSIONS = ACME_HUB / "model" / "extensions"
STRATEGIC = EXTENSIONS / "ddd-contexts-ext.ttl"

INV = "https://acme.example/ontology/invoice#"
CLI = "https://acme.example/ontology/client#"
TERMS = "https://acme.example/ontology/terms#"


def _domain(name: str, *, with_overlay: bool = True) -> ContextDomain:
    graph = Graph()
    graph.parse(ONTOLOGIES / f"{name}.ttl", format="turtle")
    overlay = EXTENSIONS / f"{name}-ddd-ext.ttl"
    return ContextDomain(
        name=name,
        graph=graph,
        file=ONTOLOGIES / f"{name}.ttl",
        local_graph=graph,
        overlay_path=overlay if with_overlay and overlay.exists() else None,
    )


def _model(**kwargs):
    kwargs.setdefault("strategic_path", STRATEGIC)
    kwargs.setdefault("hub_name", "acme-hub")
    return build_language_model([_domain("client"), _domain("invoice")], **kwargs)


def _graph(ttl: str) -> Graph:
    graph = Graph()
    graph.parse(data=ttl, format="turtle")
    return graph


GLOSSARY = textwrap.dedent(
    f"""
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix g: <https://acme.example/glossary#> .
    g: a skos:ConceptScheme ; rdfs:label "Acme glossary" .
    g:Invoice a skos:Concept ; skos:inScheme g: ;
        skos:prefLabel "Invoice"@en ; skos:altLabel "Facture"@en , "Rechnung"@en ;
        skos:definition "What finance sends the client once the shipment is closed." ;
        rdfs:seeAlso <{INV}Invoice> .
    g:Gone a skos:Concept ; skos:inScheme g: ;
        skos:prefLabel "Gone"@en ; rdfs:seeAlso <{INV}NoSuchClass> .
    """
)


@pytest.fixture
def glossary_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "businessdiscovery"
    directory.mkdir()
    (directory / "acme-glossary.ttl").write_text(GLOSSARY, encoding="utf-8")
    (directory / "glossary-template.ttl").write_text(GLOSSARY, encoding="utf-8")  # ignored
    return directory


def _binding(directory: Path, name: str, cls: str, relation: str, fields: list, rels: list) -> None:
    payload = {
        "apiVersion": "kairos.eu/v5",
        "kind": "EntityBinding",
        "metadata": {"name": name, "domain": "invoice"},
        "source": {"relation": relation},
        "target": {"class": cls},
        "fields": fields,
        "relationships": rels,
    }
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.binding.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")


class TestVocabulary:
    def test_one_concept_per_hub_class_linked_by_exactmatch(self):
        model = _model()
        graph = _graph(render_ubiquitous_language(model))
        concepts = set(graph.subjects(RDF.type, SKOS.Concept))
        assert len(concepts) == len(model.classes()) == 11
        for cls in model.classes():
            concept = graph.value(predicate=SKOS.exactMatch, object=cls)
            assert concept is not None, cls
            assert (concept, SKOS.inScheme, URIRef(TERMS.rstrip("#"))) in graph
        invoice = URIRef(f"{TERMS}Invoice")
        assert graph.value(invoice, SKOS.prefLabel) == Literal("Invoice", lang="en")
        assert str(graph.value(invoice, SKOS.definition)) == "A billing invoice issued to a client."

    def test_overlay_language_becomes_skos(self):
        graph = _graph(render_ubiquitous_language(_model()))
        invoice = URIRef(f"{TERMS}Invoice")
        assert (invoice, SKOS.altLabel, Literal("Bill", lang="en")) in graph
        assert "issued document" in str(graph.value(invoice, SKOS.scopeNote))
        assert "INV-2026-000123" in str(graph.value(invoice, SKOS.example))
        assert str(graph.value(invoice, SKOS.editorialNote)) == "silver: unbound"

    def test_glossary_synonyms_join_and_stale_links_are_reported(self, glossary_dir):
        model = _model(glossary_dir=glossary_dir)
        graph = _graph(render_ubiquitous_language(model))
        invoice = URIRef(f"{TERMS}Invoice")
        labels = {str(lbl) for lbl in graph.objects(invoice, SKOS.altLabel)}
        assert labels == {"Bill", "Facture", "Rechnung"}  # "Invoice" itself is the prefLabel
        notes = {str(n) for n in graph.objects(invoice, SKOS.note)}
        assert any("What finance sends" in n for n in notes)
        assert model.stale_glossary == [("https://acme.example/glossary#Gone", f"{INV}NoSuchClass")]

    def test_collections_per_context_else_per_domain(self):
        with_ddd = _graph(render_ubiquitous_language(_model()))
        billing = URIRef(f"{TERMS}context-BillingContext")
        assert (billing, RDF.type, SKOS.Collection) in with_ddd
        assert set(with_ddd.objects(billing, SKOS.member)) == {
            URIRef(f"{TERMS}Invoice"),
            URIRef(f"{TERMS}InvoiceLine"),
        }
        plain = build_language_model(
            [_domain("client", with_overlay=False), _domain("invoice", with_overlay=False)],
            hub_name="acme-hub",
        )
        graph = _graph(render_ubiquitous_language(plain))
        assert (URIRef(f"{TERMS}domain-invoice"), RDF.type, SKOS.Collection) in graph
        assert (billing, RDF.type, SKOS.Collection) not in graph

    def test_industry_parent_is_a_broadmatch(self):
        model = build_language_model(
            [_domain("logistics", with_overlay=False)], hub_name="acme-hub"
        )
        graph = _graph(render_ubiquitous_language(model))
        carrier = URIRef(f"{TERMS}VesselCarrier")
        assert (
            carrier,
            SKOS.broadMatch,
            URIRef("https://refmodel.example/ontology/party#ShipOperator"),
        ) in graph

    def test_terms_namespace_is_the_common_prefix_of_the_hubs_ontologies(self):
        assert _model().terms_ns == TERMS
        single = build_language_model([_domain("invoice")], hub_name="acme-hub")
        assert single.terms_ns == TERMS
        empty = build_language_model(
            [ContextDomain(name="x", graph=Graph(), local_graph=Graph())], hub_name="My Hub"
        )
        assert empty.terms_ns == "https://kairos.cnext.eu/hubs/my_hub/terms#"

    def test_colliding_local_names_are_suffixed_by_domain(self):
        def domain(name: str) -> ContextDomain:
            graph = _graph(
                textwrap.dedent(
                    f"""
                    @prefix owl: <http://www.w3.org/2002/07/owl#> .
                    <https://ex.test/ont/{name}> a owl:Ontology .
                    <https://ex.test/ont/{name}#Address> a owl:Class .
                    """
                )
            )
            return ContextDomain(name=name, graph=graph, local_graph=graph)

        model = build_language_model([domain("party"), domain("billing")], hub_name="x")
        assert sorted(model.term_ids.values()) == ["Address_billing", "Address_party"]

    def test_deterministic_and_timestamp_free(self):
        first = render_ubiquitous_language(_model())
        second = render_ubiquitous_language(_model())
        assert first == second
        assert first.startswith("# Generated by kairos-ontology ")
        assert "Generated :" not in first
        assert generate_ubiquitous_language(_model()).keys() == {UBIQUITOUS_LANGUAGE_NAME}

    def test_bindings_give_sources_status_and_realised_relationships(self, tmp_path):
        bindings = tmp_path / "bindings"
        _binding(
            bindings,
            "billing-invoices",
            f"{INV}Invoice",
            "billing.invoices",
            fields=[{"property": f"{INV}invoiceNumber", "expression": "INV_NO"}],
            rels=[{"property": f"{INV}issuedTo", "target": f"{CLI}Client"}],
        )
        model = _model(bindings_dir=bindings)
        graph = _graph(render_ubiquitous_language(model))
        invoice = URIRef(f"{TERMS}Invoice")
        assert (invoice, SKOS.hiddenLabel, Literal("billing.invoices")) in graph
        assert str(graph.value(invoice, SKOS.editorialNote)) == "silver: bound"
        assert (URIRef(f"{INV}Invoice"), URIRef(f"{INV}issuedTo")) in model.bound_relationships
        assert model.columns[URIRef(f"{INV}Invoice")][URIRef(f"{INV}invoiceNumber")] == [
            ("billing", "invoices", "INV_NO")
        ]


SOURCE_TTL = textwrap.dedent(
    """
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix b: <https://acme.example/src/billing#> .
    b:Invoices a kairos-bronze:SourceTable ; kairos-bronze:tableName "invoices" .
    b:Invoices_INV_NO a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable b:Invoices ;
        kairos-bronze:columnName "INV_NO" ;
        kairos-bronze:sampleValues "INV-1 | INV-2 | INV-3 | INV-4" .
    """
)


class TestConceptGuide:
    def test_sections_and_three_names_table(self, glossary_dir, tmp_path):
        bindings = tmp_path / "bindings"
        _binding(
            bindings,
            "billing-invoices",
            f"{INV}Invoice",
            "billing.invoices",
            fields=[],
            rels=[{"property": f"{INV}issuedTo", "target": f"{CLI}Client"}],
        )
        guide = render_concept_guide(_model(glossary_dir=glossary_dir, bindings_dir=bindings))
        for heading in (
            "## Three names, one concept",
            "## Concepts by bounded context",
            "### Billing",
            "#### Invoice",
            "### Outside every bounded context",
            "## Relationship reference",
            "## Concept mapping table",
            "## Stale discovery terms",
        ):
            assert heading in guide, heading
        assert "- **Also called:** Bill, Facture, Rechnung" in guide
        assert "- **The business says:** What finance sends the client" in guide
        assert "- **Sources:** `billing.invoices`" in guide
        assert "- **Silver:** bound (no contract)" in guide
        assert "- **Refers to:** Client via `issuedTo` *(realised)*" in guide
        assert (
            "| Invoice | `billing.invoices` | `invoice:Invoice` | hub-local | bound (no contract) |"
            in guide
        )
        assert "--issuedTo--> Client (realised)" in guide
        assert "`https://acme.example/glossary#Gone` → `" in guide

    def test_grouped_by_domain_without_ddd(self):
        plain = build_language_model(
            [_domain("client", with_overlay=False), _domain("invoice", with_overlay=False)],
            hub_name="acme-hub",
        )
        guide = render_concept_guide(plain)
        assert "## Concepts by domain" in guide and "### invoice" in guide
        assert "Outside every bounded context" not in guide

    def test_samples_are_off_by_default_and_capped_when_on(self, tmp_path):
        bindings = tmp_path / "bindings"
        _binding(
            bindings,
            "billing-invoices",
            f"{INV}Invoice",
            "billing.invoices",
            fields=[{"property": f"{INV}invoiceNumber", "expression": "INV_NO"}],
            rels=[],
        )
        sources = tmp_path / "sources" / "billing"
        sources.mkdir(parents=True)
        (sources / "invoices.ttl").write_text(SOURCE_TTL, encoding="utf-8")
        model = _model(bindings_dir=bindings)
        off = render_concept_guide(model, sources_dir=tmp_path / "sources")
        assert "Sample `" not in off and "Sample values:** off" in off
        on = render_concept_guide(model, samples_per_property=2, sources_dir=tmp_path / "sources")
        assert "- **Sample `invoiceNumber`:** `INV-1`, `INV-2`" in on
        assert "INV-3" not in on and "Sample values:** included" in on

    def test_deterministic(self):
        assert render_concept_guide(_model()) == render_concept_guide(_model())
        assert generate_concept_guide(_model()).keys() == {CONCEPT_GUIDE_NAME}


class TestConfig:
    def test_samples_switch_defaults_off(self, tmp_path):
        assert language_inputs(None) == {"samples": 0}
        assert language_inputs(tmp_path) == {"samples": 0}
        (tmp_path / "kairos.yaml").write_text(
            "projections:\n  concept_guide:\n    samples: true\n", encoding="utf-8"
        )
        assert language_inputs(tmp_path) == {"samples": 3}
        (tmp_path / "kairos.yaml").write_text(
            "projections:\n  concept_guide:\n    samples: true\n    max_samples: 5\n",
            encoding="utf-8",
        )
        assert language_inputs(tmp_path) == {"samples": 5}


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    destination = tmp_path / "hub"
    shutil.copytree(ACME_HUB, destination)
    return destination


class TestProjectorWiring:
    def test_language_artifacts_land_beside_the_ddd_output_for_every_hub(self, hub, tmp_path):
        for path in (hub / "model" / "extensions").glob("*ddd*"):
            path.unlink()  # no DDD design at all
        output = tmp_path / "publish"
        run_projections(
            ontologies_path=hub / "model" / "ontologies",
            catalog_path=None,
            output_path=output,
            target="ddd",
        )
        ddd = output / "architecture" / "ddd"
        assert (ddd / UBIQUITOUS_LANGUAGE_NAME).is_file()
        assert (ddd / CONCEPT_GUIDE_NAME).is_file()
        assert (ddd / _PROJECTION_MANIFEST_NAME).is_file()
        assert not (ddd / "contexts").exists()
        text = (ddd / UBIQUITOUS_LANGUAGE_NAME).read_text(encoding="utf-8")
        assert "domain-invoice" in text and "context-" not in text
        assert (ddd / CONCEPT_GUIDE_NAME).read_text(encoding="utf-8").startswith("# Concept guide")
