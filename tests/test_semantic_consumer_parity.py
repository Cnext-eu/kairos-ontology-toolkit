# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Cross-consumer closure and semantic-index parity regression for issue #224."""

import json

from kairos_ontology.core.inventory import generate_inventory, write_inventory
from kairos_ontology.core.projector import run_projections
from kairos_ontology.core.propose_alignment import _load_inventory_classes
from kairos_ontology.core.validator import run_validation


def test_transitive_closure_is_shared_by_semantic_consumers(tmp_path):
    ontologies = tmp_path / "model" / "ontologies"
    shapes = tmp_path / "model" / "shapes"
    inventory_dir = tmp_path / "inventory"
    ontologies.mkdir(parents=True)
    shapes.mkdir(parents=True)
    inventory_dir.mkdir()

    root = ontologies / "root.ttl"
    middle = ontologies / "middle.ttl"
    deepest = ontologies / "deepest.ttl"
    root.write_text(
        """\
@prefix a: <https://example.org/a#> .
@prefix c: <https://example.org/c#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
<https://example.org/a> a owl:Ontology ; owl:imports <https://example.org/b> .
a:Local a owl:Class ; rdfs:subClassOf c:Base ; rdfs:label "Local" .
""",
        encoding="utf-8",
    )
    middle.write_text(
        """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
<https://example.org/b> a owl:Ontology ; owl:imports <https://example.org/c> .
""",
        encoding="utf-8",
    )
    deepest.write_text(
        """\
@prefix c: <https://example.org/c#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
<https://example.org/c> a owl:Ontology .
c:Base a owl:Class ; rdfs:label "Base" .
c:code a owl:DatatypeProperty ;
    rdfs:domain c:Base ;
    rdfs:range xsd:string ;
    rdfs:label "Code" .
""",
        encoding="utf-8",
    )
    catalog = tmp_path / "catalog-v001.xml"
    catalog.write_text(
        """\
<?xml version="1.0" encoding="UTF-8"?>
<catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
  <uri name="https://example.org/b" uri="model/ontologies/middle.ttl"/>
  <uri name="https://example.org/c" uri="model/ontologies/deepest.ttl"/>
</catalog>
""",
        encoding="utf-8",
    )

    inventory = generate_inventory(root, catalog_path=catalog)
    write_inventory(inventory, inventory_dir / "root-inventory.yaml")
    inventory_classes = _load_inventory_classes(inventory_dir)
    local = next(
        item for item in inventory_classes if item["uri"] == "https://example.org/a#Local"
    )
    assert any(
        prop["uri"] == "https://example.org/c#code" and prop["inherited"]
        for prop in local["properties"]
    )

    shapes.joinpath("closure.shacl.ttl").write_text(
        """\
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix c: <https://example.org/c#> .
[] a sh:NodeShape ;
   sh:targetNode c:Base ;
   sh:property [ sh:path rdf:type ; sh:hasValue owl:Class ] .
""",
        encoding="utf-8",
    )
    validation_report = tmp_path / "validation.json"
    run_validation(
        ontologies_path=ontologies,
        shapes_path=shapes,
        catalog_path=catalog,
        do_syntax=False,
        do_shacl=True,
        do_consistency=False,
        report_path=validation_report,
    )
    validation = json.loads(validation_report.read_text(encoding="utf-8"))
    validation_context = validation["shacl"]["semantic_context"][str(root)]

    output = tmp_path / "output"
    run_projections(
        ontologies_path=root,
        catalog_path=catalog,
        output_path=output,
        target="prompt",
    )
    projection_report = json.loads(
        (output / "projection-report.json").read_text(encoding="utf-8")
    )
    prompt = json.loads(
        (output / "prompt" / "root-context.json").read_text(encoding="utf-8")
    )

    assert inventory["closure_hash"] == validation_context["closure_hash"]
    assert inventory["closure_hash"] == projection_report["domains"]["root"]["closure_hash"]
    assert inventory["closure_hash"] == prompt["semantic_context"]["closure_hash"]
    assert prompt["entities"]["Local"]["fields"]["code"]["type"] == "text"
