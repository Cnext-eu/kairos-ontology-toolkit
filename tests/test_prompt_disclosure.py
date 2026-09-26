# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Prompts disclose what they cut; the schema matches the prompt; profiles say what they
do not carry (DD-244, #937)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core import propose_alignment as pa
from kairos_ontology.core.analyse_sources import _build_single_call_prompt, _summarize_classes
from kairos_ontology.core.prompt_context import disclosure_line, truncate_class_pool


def _pool(count: int, *, inherited_from: int = 0) -> list[dict]:
    props = [{"name": f"p{i:03d}", "inherited": i >= count - inherited_from} for i in range(count)]
    return [{"name": "Party", "label": "Party", "properties": props}]


class TestPoolCut:
    def test_nothing_cut_means_no_line(self):
        shown, omitted = truncate_class_pool(_pool(5), max_properties=60)
        assert omitted == 0
        assert shown[0] is _pool(5)[0] or shown[0]["properties"] == _pool(5)[0]["properties"]
        assert disclosure_line() == ""

    def test_a_cut_is_counted_and_worded_for_the_model(self):
        shown, omitted = truncate_class_pool(_pool(65), max_properties=60)
        assert omitted == 5
        assert len(shown[0]["properties"]) == 60
        line = disclosure_line(omitted_properties=omitted)
        assert "5 further propert" in line
        assert "answer null" in line


class TestAlignmentPrompt:
    def test_inventory_marks_inherited_and_says_it_was_cut(self):
        text = pa._format_ref_inventory(_pool(65, inherited_from=10))
        assert "- p055 (inherited)" in text
        assert "- p059 (inherited)" in text
        assert "p060" not in text
        assert "… 5 more not listed" in text

    def test_the_prompt_ends_with_the_disclosure_only_when_cut(self):
        columns = [{"name": "party_name", "samples": []}]
        cut = pa.build_alignment_prompt("t", columns, _pool(65))
        assert "5 further propert" in cut
        assert "do not conclude the concept is absent" in cut
        whole = pa.build_alignment_prompt("t", columns, _pool(5))
        assert "further propert" not in whole

    def test_schema_and_pair_check_see_the_shown_pool(self):
        pool = _pool(65)
        shown = pa._shown_pool(pool)
        names = pa.qualified_property_names(shown)
        assert "Party.p059" in names and "Party.p060" not in names
        alignments = [
            {"alignment": "direct", "ref_class": "Party", "ref_property": "p060"},
            {"alignment": "direct", "ref_class": "Party", "ref_property": "p001"},
        ]
        repaired, rejected = pa.enforce_class_property_pairs(alignments, shown)
        assert (repaired, rejected) == (0, 1)
        assert alignments[0]["alignment"] == "custom"
        assert alignments[1]["ref_property"] == "p001"

    def test_the_pool_contract_moved(self):
        assert pa.ALIGNMENT_POOL_CONTRACT == 4


class TestClassification:
    def test_own_classes_come_first_and_the_cap_is_disclosed(self):
        classes = [
            {"uri": "urn:imported#A", "name": "A"},
            {"uri": "urn:imported#B", "name": "B"},
            {"uri": "urn:own#Z", "name": "Z"},
        ]
        summary = _summarize_classes(classes, cap=2, prefer=("urn:own",))
        assert [c["name"] for c in summary] == ["Z", "A"]
        prompt = _build_single_call_prompt(
            "t",
            [],
            [{"id": "own", "class_summary": summary, "class_summary_omitted": 1}],
        )
        assert "KEY CONCEPTS: Z, A (+1 more not listed)" in prompt


BASE = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix base: <urn:base#> .

<urn:base> a owl:Ontology ; rdfs:label "Base" .
base:Party a owl:Class ; rdfs:label "Party" ; rdfs:comment "Anyone the business deals with." .
base:name a owl:DatatypeProperty ; rdfs:domain base:Party ; rdfs:range xsd:string .
base:owns a owl:ObjectProperty ; rdfs:domain base:Party ; rdfs:range base:Party ;
    owl:inverseOf base:ownedBy .
base:ownedBy a owl:ObjectProperty .
"""

CUSTOMER = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix base: <urn:base#> .
@prefix : <urn:customer#> .

<urn:customer> a owl:Ontology ; rdfs:label "Customer" ; owl:imports <urn:base> .
:Customer a owl:Class ; rdfs:label "Customer" ; rdfs:subClassOf base:Party .
"""


@pytest.fixture
def hub(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "ontology-hub"
    (root / "refmodels").mkdir(parents=True)
    (root / "model" / "ontologies").mkdir(parents=True)
    (root / "integration").mkdir()
    (root / "refmodels" / "base.ttl").write_text(BASE, encoding="utf-8")
    (root / "model" / "ontologies" / "customer.ttl").write_text(CUSTOMER, encoding="utf-8")
    (root / "catalog-v001.xml").write_text(
        '<?xml version="1.0"?>\n<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        '  <uri name="urn:base" uri="refmodels/base.ttl"/>\n</catalog>\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return root


class TestInspection:
    def test_explain_term_names_the_fields_the_profile_does_not_carry(self, hub: Path):
        result = CliRunner().invoke(
            cli, ["explain-term", "urn:base#owns", "--domain", "customer", "--profile", "rdfs"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["term"]["inverse_properties"] == []
        assert "inverse_properties" in payload["not_carried_by_profile"]
        assert payload["coverage"]["inverse_properties"] is False

        result = CliRunner().invoke(cli, ["explain-term", "urn:base#owns", "--domain", "customer"])
        payload = json.loads(result.output)
        assert payload["not_carried_by_profile"] == []
        assert payload["term"]["inverse_properties"][0]["uri"] == "urn:base#ownedBy"

    def test_inventory_all_keeps_the_metadata(self, hub: Path):
        result = CliRunner().invoke(cli, ["show-class-inventory", "--all", "--profile", "asserted"])
        assert result.exit_code == 0, result.output
        (domain,) = json.loads(result.output)["domains"]
        assert domain["metadata"]["semantic_profile"] == "asserted"
        assert domain["metadata"]["coverage"]["inherited_properties"] is False


class TestScaffoldPrompt:
    def test_imported_classes_reach_the_prompt(self, hub: Path):
        from kairos_ontology.cli.setup import _build_ai_domain_prompt, _imported_class_context

        context = _imported_class_context(hub, [{"uri": "urn:base"}])
        assert "IMPORTED MODULE urn:base" in context
        assert "CLASS: Party (Party)" in context
        assert "- name [datatype: string]" in context
        prompt = _build_ai_domain_prompt(
            domain="sales",
            label="Sales",
            company_domain="acme.example",
            imports=[{"uri": "urn:base"}],
            context="",
            imported_context=context,
        )
        assert "Classes the imports already provide" in prompt
        assert "subclass it instead" in prompt

    def test_no_catalog_means_no_context(self, tmp_path: Path):
        from kairos_ontology.cli.setup import _imported_class_context

        assert _imported_class_context(tmp_path, [{"uri": "urn:base"}]) == ""


class TestPromptProjection:
    def test_left_out_imported_classes_are_disclosed(self, hub: Path, tmp_path: Path):
        from kairos_ontology.core.projector import run_projections

        output = tmp_path / "out"
        run_projections(
            ontologies_path=hub / "model" / "ontologies",
            catalog_path=hub / "catalog-v001.xml",
            output_path=output,
            target="prompt",
        )
        compact = json.loads(
            (output / "prompt" / "customer-context.json").read_text(encoding="utf-8")
        )
        metadata = compact["semantic_context"]
        assert metadata["truncated"] is True
        assert metadata["omitted_class_count"] == 1
        assert "urn:base" in metadata["omitted_modules"]


class TestGlossary:
    def test_a_prefixed_see_also_is_read(self, tmp_path: Path):
        directory = tmp_path / "businessdiscovery"
        directory.mkdir()
        (directory / "terms-glossary.ttl").write_text(
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "@prefix bsp: <urn:bsp#> .\n"
            '<urn:g#1> a skos:Concept ; skos:prefLabel "Shipper" ;\n'
            '    skos:definition "The party that ships." ; rdfs:seeAlso bsp:TradeParty .\n',
            encoding="utf-8",
        )
        (record,) = pa.load_glossary_records(tmp_path)
        assert record == {
            "label": "Shipper",
            "definition": "The party that ships.",
            "see_also": "urn:bsp#TradeParty",
        }
