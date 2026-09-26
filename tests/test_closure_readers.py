# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The readers that used to parse one file now see the `owl:imports` closure (DD-243).

One fixture: a hub domain ``customer`` whose ``Customer`` subclasses ``base:Party`` from an
imported module that declares ``base:email`` (PII) and a relationship with an ``owl:unionOf``
domain. Read alone, ``customer.ttl`` shows a class with no properties; read through the
closure, it shows what the class actually carries.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kairos_ontology.core.alignment_report import domain_imports
from kairos_ontology.core.coverage_report import align_classes_deterministic, parse_domain_ontology
from kairos_ontology.core.ontology_integrity import (
    check_reference_model_shadowing,
    scan_hub_ontologies,
)
from kairos_ontology.core.projections.report_projector import generate_domain_overview_report
from kairos_ontology.core.validator import run_gdpr_validation, validate_gdpr

TEMPLATES = Path(__file__).resolve().parent.parent / "src" / "kairos_ontology" / "templates"

BASE = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix base: <urn:base#> .

<urn:base> a owl:Ontology ; rdfs:label "Base" .
base:Party a owl:Class ; rdfs:label "Party" ; rdfs:comment "Anyone the business deals with." .
base:Location a owl:Class ; rdfs:label "Location" .
base:email a owl:DatatypeProperty ; rdfs:label "email" ; rdfs:domain base:Party ; rdfs:range xsd:string .
base:name a owl:DatatypeProperty ; rdfs:label "name" ; rdfs:domain base:Party ; rdfs:range xsd:string .
"""

MID = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix mid: <urn:mid#> .

<urn:mid> a owl:Ontology ; rdfs:label "Mid" ; owl:imports <urn:base> .
mid:Account a owl:Class ; rdfs:label "Account" .
"""

CUSTOMER = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix base: <urn:base#> .
@prefix mid: <urn:mid#> .
@prefix : <urn:customer#> .

<urn:customer> a owl:Ontology ; rdfs:label "Customer" ; owl:versionInfo "1.0.0" ;
    owl:imports <urn:mid> .
:Customer a owl:Class ; rdfs:label "Customer" ; rdfs:comment "A party that buys." ;
    rdfs:subClassOf base:Party .
:Order a owl:Class ; rdfs:label "Order" .
:loyaltyTier a owl:DatatypeProperty ; rdfs:label "loyalty tier" ; rdfs:domain :Customer ;
    rdfs:range xsd:string .
:placedAt a owl:ObjectProperty ; rdfs:label "placed at" ;
    rdfs:domain [ owl:unionOf ( :Customer :Order ) ] ; rdfs:range base:Location .
"""


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    root = tmp_path / "hub"
    (root / "refmodels").mkdir(parents=True)
    (root / "model" / "ontologies").mkdir(parents=True)
    (root / "refmodels" / "base.ttl").write_text(BASE, encoding="utf-8")
    (root / "refmodels" / "mid.ttl").write_text(MID, encoding="utf-8")
    (root / "model" / "ontologies" / "customer.ttl").write_text(CUSTOMER, encoding="utf-8")
    (root / "catalog-v001.xml").write_text(
        '<?xml version="1.0"?>\n<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
        '  <uri name="urn:base" uri="refmodels/base.ttl"/>\n'
        '  <uri name="urn:mid" uri="refmodels/mid.ttl"/>\n</catalog>\n',
        encoding="utf-8",
    )
    return root


class TestDomainOverviewReport:
    def test_inherited_properties_are_listed_with_their_origin(self, hub: Path):
        report = generate_domain_overview_report(hub / "model" / "ontologies", TEMPLATES)
        md = report["domain-overview.md"]
        assert "| `email` | string |" in md
        assert "_(inherited from Party)_" in md
        assert "| `loyaltyTier` | string |" in md
        assert "_Extends: `Party`_" in md
        # Own classes only: the imported Party is not listed as a section of this domain.
        assert "#### Party" not in md
        assert "import closure of this domain did not fully resolve" not in md

    def test_a_union_domain_yields_a_relationship_per_member(self, hub: Path):
        md = generate_domain_overview_report(hub / "model" / "ontologies", TEMPLATES)[
            "domain-overview.md"
        ]
        assert 'Customer }|--|| Location : "placedAt"' in md
        assert 'Order }|--|| Location : "placedAt"' in md

    def test_an_unresolvable_import_is_disclosed_not_fatal(self, hub: Path):
        (hub / "catalog-v001.xml").write_text(
            '<?xml version="1.0"?>\n<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">\n'
            "</catalog>\n",
            encoding="utf-8",
        )
        md = generate_domain_overview_report(hub / "model" / "ontologies", TEMPLATES)[
            "domain-overview.md"
        ]
        assert "import closure of this domain did not fully resolve" in md
        assert "| `loyaltyTier` | string |" in md


class TestCoverageReport:
    def test_properties_include_inherited_and_union_declared(self, hub: Path):
        data = parse_domain_ontology(
            hub / "model" / "ontologies" / "customer.ttl", catalog_path=hub / "catalog-v001.xml"
        )
        customer = next(cls for cls in data["classes"] if cls["name"] == "Customer")
        by_name = {prop["name"]: prop for prop in customer["properties"]}
        assert by_name["loyaltyTier"]["origin"] == "direct"
        assert by_name["email"]["origin"] == "inherited"
        assert by_name["email"]["inherited_from"] == "urn:base#Party"
        assert "placedAt" in by_name, "an owl:unionOf domain names this class (DD-131)"
        order = next(cls for cls in data["classes"] if cls["name"] == "Order")
        assert {prop["name"] for prop in order["properties"]} == {"placedAt"}
        assert set(data["closure_modules"]) == {"urn:mid", "urn:base"}
        assert {cls["name"] for cls in data["classes"]} == {"Customer", "Order"}

    def test_imported_means_the_reference_module_is_in_the_closure(self, hub: Path):
        data = parse_domain_ontology(
            hub / "model" / "ontologies" / "customer.ttl", catalog_path=hub / "catalog-v001.xml"
        )
        ref = {
            "by_uri": {},
            "prop_by_uri": {},
            "by_name": {
                "customer": {
                    "name": "Customer",
                    "uri": "urn:base#Customer",
                    "domain": "Base",
                    "properties": [],
                },
                "order": {
                    "name": "Order",
                    "uri": "urn:elsewhere#Order",
                    "domain": "Elsewhere",
                    "properties": [],
                },
            },
        }
        results = {row["ontology_class"]: row for row in align_classes_deterministic(data, ref)}
        assert results["Customer"]["alignment"] == "imported"  # urn:base is two hops away
        assert results["Order"]["alignment"] == "name-match"  # urn:elsewhere is not imported


class TestGdprScan:
    def test_the_file_alone_sees_no_pii_and_the_closure_does(self, hub: Path, capsys):
        alone = validate_gdpr(CUSTOMER)
        assert alone["passed"] is True

        total = run_gdpr_validation(
            hub / "model" / "ontologies", catalog_path=hub / "catalog-v001.xml", hub_root=hub
        )
        assert total == 1
        out = capsys.readouterr().out
        assert "Customer.email (inherited from Party)" in out

    def test_reference_classes_are_never_judged_against_the_hub(self, hub: Path, capsys):
        run_gdpr_validation(
            hub / "model" / "ontologies", catalog_path=hub / "catalog-v001.xml", hub_root=hub
        )
        assert "Party.email" not in capsys.readouterr().out


class TestShadowing:
    _TERMS = {
        "urn:base": {"classes": {"Customer"}, "properties": set()},
        "urn:mid": {"classes": set(), "properties": set()},
    }

    def test_a_transitively_imported_name_is_flagged_only_with_the_closure(self, hub: Path):
        onts = scan_hub_ontologies(hub / "model" / "ontologies", self._TERMS)
        assert onts["customer"].imports == ("urn:mid",)

        direct_only = check_reference_model_shadowing(onts, self._TERMS)
        assert direct_only == []

        with_closure = check_reference_model_shadowing(
            onts, self._TERMS, closure_imports={"customer": {"urn:mid", "urn:base"}}
        )
        (diagnostic,) = with_closure
        assert diagnostic.code == "integrity.local-class-shadows-reference-model"
        assert "imported transitively module <urn:base>" in diagnostic.message
        assert diagnostic.remediation.startswith("add `owl:imports <urn:base>` and Reuse")
        assert "owl:equivalentClass does not anchor" in diagnostic.message


class TestDomainImports:
    def test_every_import_on_a_line_counts(self, tmp_path: Path):
        ontologies = tmp_path / "model" / "ontologies"
        ontologies.mkdir(parents=True)
        (ontologies / "party.ttl").write_text(
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "# owl:imports <urn:commented-out> .\n"
            "<urn:party> a owl:Ontology ; owl:imports <urn:a>, <urn:b> ;\n"
            "    owl:imports <urn:c> .\n",
            encoding="utf-8",
        )
        assert domain_imports(tmp_path) == {"party": {"urn:a", "urn:b", "urn:c"}}

    def test_an_unparseable_file_falls_back_to_the_text(self, tmp_path: Path):
        ontologies = tmp_path / "model" / "ontologies"
        ontologies.mkdir(parents=True)
        (ontologies / "broken.ttl").write_text(
            "<urn:broken> a owl:Ontology ; owl:imports <urn:a>, <urn:b> .\nthis is not turtle\n",
            encoding="utf-8",
        )
        assert domain_imports(tmp_path) == {"broken": {"urn:a", "urn:b"}}
