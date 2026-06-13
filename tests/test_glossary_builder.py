# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the deterministic SKOS glossary builder (DD-062)."""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner
from rdflib import RDFS, SKOS, Graph, Literal, URIRef
from rdflib.namespace import RDF

from kairos_ontology.cli.main import cli
from kairos_ontology.glossary_builder import (
    aggregate_concepts,
    build_glossary,
    build_glossary_graph,
    collect_terms,
    derive_glossary_namespace,
    read_company_info,
    to_pascal_case,
)

GLOSSARY_NS = "https://acme.com/glossary#"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _write_extraction(extraction_dir: Path, slug: str, terms: list[dict]) -> Path:
    extraction_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "version": "1.0",
        "source_file": f"{slug}.pdf",
        "source_sha256": "deadbeef",
        "strategy": "company-terminology-v1",
        "summary": "test",
        "extracted_terms": terms,
        "status": "processed",
    }
    path = extraction_dir / f"{slug}.extraction.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    return path


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_to_pascal_case():
    assert to_pascal_case("Transport Document") == "TransportDocument"
    assert to_pascal_case("empty kilometres") == "EmptyKilometres"
    assert to_pascal_case("Laden/Lossen") == "LadenLossen"
    assert to_pascal_case("") == "Concept"


def test_derive_glossary_namespace():
    assert derive_glossary_namespace("acme.com") == "https://acme.com/glossary#"
    assert derive_glossary_namespace("https://acme.com/") == "https://acme.com/glossary#"


def test_read_company_info(tmp_path: Path):
    (tmp_path / "README.md").write_text(
        "# Acme — Ontology Hub\n"
        "| **Company name**   | Acme Logistics |\n"
        "| **Company domain** | acme.com |\n",
        encoding="utf-8",
    )
    name, domain = read_company_info(tmp_path)
    assert name == "Acme Logistics"
    assert domain == "acme.com"


def test_read_company_info_missing(tmp_path: Path):
    assert read_company_info(tmp_path) == (None, None)


# --------------------------------------------------------------------------- #
# collect + aggregate
# --------------------------------------------------------------------------- #
def test_collect_terms_across_files(tmp_path: Path):
    ext = tmp_path / "_extractions"
    _write_extraction(ext, "a-pdf", [{"altLabel": "HBL", "prefLabel": "Transport Document"}])
    _write_extraction(ext, "b-pdf", [{"altLabel": "Leg", "prefLabel": "Shipment Movement"}])
    terms, sources = collect_terms(ext)
    assert len(terms) == 2
    assert sources == ["a-pdf.extraction.yaml", "b-pdf.extraction.yaml"]


def test_collect_terms_missing_dir(tmp_path: Path):
    assert collect_terms(tmp_path / "nope") == ([], [])


def test_aggregate_groups_by_linked_iri():
    terms = [
        {
            "altLabel": "HBL",
            "prefLabel": "Transport Document",
            "linked_iri": "https://acme.com/ont/logistics#TransportDocument",
            "definition": "A carrier document.",
        },
        {
            "altLabel": "House Bill",
            "prefLabel": "Transport Document",
            "linked_iri": "https://acme.com/ont/logistics#TransportDocument",
        },
    ]
    concepts, skipped = aggregate_concepts(terms)
    assert skipped == 0
    assert len(concepts) == 1
    c = concepts[0]
    assert c.local_name == "TransportDocument"
    assert c.alt_labels == ["HBL", "House Bill"]
    assert c.definition == "A carrier document."
    assert c.linked_iri == "https://acme.com/ont/logistics#TransportDocument"


def test_aggregate_groups_by_prefLabel_when_no_iri():
    terms = [
        {"altLabel": "Leg", "prefLabel": "Shipment Movement"},
        {"altLabel": "Routing Leg", "prefLabel": "shipment movement"},
    ]
    concepts, _ = aggregate_concepts(terms)
    assert len(concepts) == 1
    assert sorted(concepts[0].alt_labels) == ["Leg", "Routing Leg"]


def test_aggregate_skips_terms_without_pref_label():
    terms = [{"altLabel": "X"}, {"prefLabel": "Valid"}]
    concepts, skipped = aggregate_concepts(terms)
    assert skipped == 1
    assert len(concepts) == 1


def test_aggregate_company_specific_only():
    terms = [
        {"prefLabel": "Internal Order", "company_specific": True},
        {"prefLabel": "Invoice", "company_specific": False},
    ]
    concepts, skipped = aggregate_concepts(terms, company_specific_only=True)
    assert skipped == 1
    assert [c.pref_label for c in concepts] == ["Internal Order"]


def test_aggregate_dedupes_alt_labels():
    terms = [
        {"altLabel": "HBL", "prefLabel": "Transport Document"},
        {"altLabel": "HBL", "prefLabel": "Transport Document"},
    ]
    concepts, _ = aggregate_concepts(terms)
    assert concepts[0].alt_labels == ["HBL"]


# --------------------------------------------------------------------------- #
# graph building
# --------------------------------------------------------------------------- #
def test_build_graph_emits_valid_skos():
    terms = [
        {
            "altLabel": "HBL",
            "prefLabel": "Transport Document",
            "linked_iri": "https://acme.com/ont/logistics#TransportDocument",
            "definition": "A carrier document.",
        }
    ]
    concepts, _ = aggregate_concepts(terms)
    graph = build_glossary_graph(
        concepts, glossary_namespace=GLOSSARY_NS, scheme_label="Acme Business Glossary"
    )
    scheme = URIRef(GLOSSARY_NS)
    assert (scheme, RDF.type, SKOS.ConceptScheme) in graph

    node = URIRef(GLOSSARY_NS + "TransportDocument")
    assert (node, RDF.type, SKOS.Concept) in graph
    assert (node, SKOS.inScheme, scheme) in graph
    assert (node, SKOS.prefLabel, Literal("Transport Document", lang="en")) in graph
    assert (node, SKOS.altLabel, Literal("HBL", lang="en")) in graph
    assert (
        node,
        RDFS.seeAlso,
        URIRef("https://acme.com/ont/logistics#TransportDocument"),
    ) in graph


def test_build_graph_related_match_relation():
    terms = [
        {
            "prefLabel": "Ship Manager",
            "linked_iri": "https://ref.example/ont/party#ShipManager",
            "link_relation": "relatedMatch",
        }
    ]
    concepts, _ = aggregate_concepts(terms)
    graph = build_glossary_graph(
        concepts, glossary_namespace=GLOSSARY_NS, scheme_label="L"
    )
    node = URIRef(GLOSSARY_NS + "ShipManager")
    assert (node, SKOS.relatedMatch, URIRef("https://ref.example/ont/party#ShipManager")) in graph
    assert (node, RDFS.seeAlso, URIRef("https://ref.example/ont/party#ShipManager")) not in graph


# --------------------------------------------------------------------------- #
# end-to-end build
# --------------------------------------------------------------------------- #
def test_build_glossary_round_trips(tmp_path: Path):
    ext = tmp_path / "_extractions"
    _write_extraction(
        ext,
        "terms-pdf",
        [
            {
                "altLabel": "HBL",
                "prefLabel": "Transport Document",
                "linked_iri": "https://acme.com/ont/logistics#TransportDocument",
            }
        ],
    )
    out = tmp_path / "acme-glossary.ttl"
    result = build_glossary(
        extraction_dir=ext,
        output_path=out,
        glossary_namespace=GLOSSARY_NS,
        scheme_label="Acme Business Glossary",
    )
    assert out.is_file()
    assert len(result.concepts) == 1

    # Output must be valid, re-parseable Turtle.
    g = Graph()
    g.parse(out, format="turtle")
    node = URIRef(GLOSSARY_NS + "TransportDocument")
    assert (node, SKOS.prefLabel, Literal("Transport Document", lang="en")) in g


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def test_cli_build_glossary(tmp_path: Path, monkeypatch):
    hub = tmp_path / "ontology-hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "README.md").write_text(
        "| **Company name**   | Acme Logistics |\n"
        "| **Company domain** | acme.com |\n",
        encoding="utf-8",
    )
    ext = hub / "businessdiscovery" / "_extractions"
    _write_extraction(
        ext,
        "terms-pdf",
        [{"altLabel": "Leg", "prefLabel": "Shipment Movement"}],
    )

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["build-glossary"])
    assert result.exit_code == 0, result.output

    out = hub / "businessdiscovery" / "acme-glossary.ttl"
    assert out.is_file()
    g = Graph()
    g.parse(out, format="turtle")
    assert (None, SKOS.prefLabel, Literal("Shipment Movement", lang="en")) in g


def test_cli_build_glossary_no_extractions(tmp_path: Path, monkeypatch):
    hub = tmp_path / "ontology-hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "README.md").write_text("| **Company domain** | acme.com |\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["build-glossary"])
    assert result.exit_code == 1
    assert "No _extractions" in result.output


def test_cli_build_glossary_no_company(tmp_path: Path, monkeypatch):
    hub = tmp_path / "ontology-hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "businessdiscovery" / "_extractions").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["build-glossary"])
    assert result.exit_code == 1
    assert "company domain" in result.output.lower()
