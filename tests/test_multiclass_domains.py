# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for multi-class property domain resolution (issue #240, DD-131).

Covers the three union forms — ``owl:unionOf`` domains, ``schema:domainIncludes``,
and repeated ``rdfs:domain`` — across the shared helper and the semantic index
(the resolution path used by ``validate-mapping``).
"""

from rdflib import Graph, Namespace

from kairos_ontology.core.ontology_loader import SemanticProfile, load_ontology
from kairos_ontology.core.projections.shared import (
    SCHEMA,
    effective_domain_classes,
    properties_with_domain,
)

EX = Namespace("https://example.org/main#")

ONTOLOGY = """\
@prefix ex: <https://example.org/main#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix schema: <http://schema.org/> .

<https://example.org/main> a owl:Ontology ; owl:versionInfo "1.0" .

# Two classes with NO common local parent.
ex:Invoice a owl:Class ; rdfs:label "Invoice" ; rdfs:comment "An invoice." .
ex:Charge a owl:Class ; rdfs:label "Charge" ; rdfs:comment "A charge line." .

# 1. owl:unionOf domain — the DL-correct "applies to A or B" form.
ex:currencyUnion a owl:DatatypeProperty ;
    rdfs:label "currency (union)" ;
    rdfs:comment "Shared currency via owl:unionOf domain." ;
    rdfs:domain [ owl:unionOf ( ex:Invoice ex:Charge ) ] ;
    rdfs:range xsd:string .

# 2. schema:domainIncludes — additive, entailment-free.
ex:amountIncludes a owl:DatatypeProperty ;
    rdfs:label "amount (domainIncludes)" ;
    rdfs:comment "Shared amount via schema:domainIncludes." ;
    schema:domainIncludes ex:Invoice , ex:Charge ;
    rdfs:range xsd:decimal .

# 3. Repeated rdfs:domain — treated as union.
ex:chargeTypeRepeat a owl:DatatypeProperty ;
    rdfs:label "charge type (repeated domain)" ;
    rdfs:comment "Shared charge type via repeated rdfs:domain." ;
    rdfs:domain ex:Invoice , ex:Charge ;
    rdfs:range xsd:string .

# Control: a plain single-class property.
ex:invoiceNumber a owl:DatatypeProperty ;
    rdfs:label "invoice number" ;
    rdfs:comment "Single-class property." ;
    rdfs:domain ex:Invoice ;
    rdfs:range xsd:string .
"""

SHARED_PROPS = (EX.currencyUnion, EX.amountIncludes, EX.chargeTypeRepeat)


def _graph() -> Graph:
    graph = Graph()
    graph.parse(data=ONTOLOGY, format="turtle")
    return graph


def test_effective_domain_classes_resolves_all_three_forms():
    graph = _graph()
    for prop in SHARED_PROPS:
        assert effective_domain_classes(graph, prop) == {EX.Invoice, EX.Charge}, prop


def test_effective_domain_classes_single_class_unchanged():
    graph = _graph()
    assert effective_domain_classes(graph, EX.invoiceNumber) == {EX.Invoice}


def test_properties_with_domain_includes_domain_includes_only_props():
    graph = _graph()
    props = properties_with_domain(graph)
    # amountIncludes has no rdfs:domain at all — only schema:domainIncludes.
    assert EX.amountIncludes in props
    assert set(SHARED_PROPS) <= props
    assert EX.invoiceNumber in props


def test_semantic_index_attaches_shared_property_to_every_member_class(tmp_path):
    path = tmp_path / "model.ttl"
    path.write_text(ONTOLOGY, encoding="utf-8")
    index = load_ontology(path, profile=SemanticProfile.RDFS).semantic_index

    for class_local in ("Invoice", "Charge"):
        uris = {
            row["property_uri"]
            for row in index.class_properties(f"https://example.org/main#{class_local}")
        }
        for prop in SHARED_PROPS:
            assert str(prop) in uris, f"{prop} missing on {class_local}"


def test_semantic_index_property_domains_list_all_member_classes(tmp_path):
    path = tmp_path / "model.ttl"
    path.write_text(ONTOLOGY, encoding="utf-8")
    index = load_ontology(path, profile=SemanticProfile.RDFS).semantic_index

    for prop in SHARED_PROPS:
        record = index.property_by_uri(str(prop))
        assert record is not None
        domain_uris = {link.uri for link in record.domains}
        assert domain_uris == {str(EX.Invoice), str(EX.Charge)}, prop


def test_schema_namespace_constant():
    assert str(SCHEMA.domainIncludes) == "http://schema.org/domainIncludes"


# ---------------------------------------------------------------------------
# validate-mapping acceptance (issue #240 acceptance criterion)
# ---------------------------------------------------------------------------

_VM_ONTOLOGY = """\
@prefix ex: <https://example.org/main#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix schema: <http://schema.org/> .

<https://example.org/main> a owl:Ontology ; owl:versionInfo "1.0" .

ex:Invoice a owl:Class ; rdfs:label "Invoice" ; rdfs:comment "An invoice." .
ex:Charge a owl:Class ; rdfs:label "Charge" ; rdfs:comment "A charge line." .

ex:currencyUnion a owl:DatatypeProperty ;
    rdfs:label "currency" ; rdfs:comment "Shared currency (owl:unionOf domain)." ;
    rdfs:domain [ owl:unionOf ( ex:Invoice ex:Charge ) ] ;
    rdfs:range xsd:string .

ex:amountIncludes a owl:DatatypeProperty ;
    rdfs:label "amount" ; rdfs:comment "Shared amount (schema:domainIncludes)." ;
    schema:domainIncludes ex:Invoice , ex:Charge ;
    rdfs:range xsd:decimal .

# Control: single-class property owned only by Invoice.
ex:invoiceNumber a owl:DatatypeProperty ;
    rdfs:label "invoice number" ; rdfs:comment "Invoice-only property." ;
    rdfs:domain ex:Invoice ;
    rdfs:range xsd:string .
"""

_VM_SOURCE = """\
@prefix bronze: <https://example.org/bronze#> .
@prefix kb: <https://kairos.cnext.eu/bronze#> .

bronze:chargeTable a kb:SourceTable .
bronze:chargeCurrency a kb:SourceColumn ; kb:sourceTable bronze:chargeTable .
bronze:chargeAmount a kb:SourceColumn ; kb:sourceTable bronze:chargeTable .
bronze:chargeNumber a kb:SourceColumn ; kb:sourceTable bronze:chargeTable .
"""


def _mapping_graph(target_property: str, source_column: str) -> Graph:
    """Build an in-memory mapping graph: chargeTable -> Charge, one column mapping."""
    ttl = f"""\
@prefix ex: <https://example.org/main#> .
@prefix bronze: <https://example.org/bronze#> .
@prefix kmap: <https://kairos.cnext.eu/mapping#> .
@prefix map: <https://example.org/mapping#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

map:t_charge a kmap:TableMapping ;
    kmap:mappingType "direct" ; kmap:matchType "exactMatch" ;
    kmap:sourceTable bronze:chargeTable ; kmap:targetClass ex:Charge .

map:c_charge a kmap:ColumnMapping ;
    kmap:matchType "exactMatch" ;
    kmap:sourceColumn bronze:{source_column} ; kmap:targetProperty ex:{target_property} .

bronze:chargeTable skos:exactMatch ex:Charge .
bronze:{source_column} skos:exactMatch ex:{target_property} .
"""
    graph = Graph()
    graph.parse(data=ttl, format="turtle")
    return graph


def _write_scope(tmp_path):
    onto = tmp_path / "main.ttl"
    onto.write_text(_VM_ONTOLOGY, encoding="utf-8")
    source_root = tmp_path / "sources"
    source_root.mkdir()
    (source_root / "bronze.ttl").write_text(_VM_SOURCE, encoding="utf-8")
    return onto, source_root


def _outside_class_codes(report) -> list[str]:
    return [
        d["resource_uri"]
        for d in report["diagnostics"]
        if d["code"] == "mapping.property-outside-target-class"
    ]


def test_validate_mapping_accepts_union_domain_property_from_member_class(tmp_path):
    from kairos_ontology.core.design_validation import validate_mapping_design

    onto, source_root = _write_scope(tmp_path)
    report = validate_mapping_design(
        mapping_paths=(),
        mapping_graph=_mapping_graph("currencyUnion", "chargeCurrency"),
        source_root=source_root,
        ontology_path=onto,
    )
    assert _outside_class_codes(report) == []


def test_validate_mapping_accepts_domain_includes_property_from_member_class(tmp_path):
    from kairos_ontology.core.design_validation import validate_mapping_design

    onto, source_root = _write_scope(tmp_path)
    report = validate_mapping_design(
        mapping_paths=(),
        mapping_graph=_mapping_graph("amountIncludes", "chargeAmount"),
        source_root=source_root,
        ontology_path=onto,
    )
    assert _outside_class_codes(report) == []


def test_validate_mapping_still_rejects_property_outside_target_class(tmp_path):
    """Negative control: an Invoice-only property mapped from a Charge table is
    still flagged, proving the acceptance above is not vacuous."""
    from kairos_ontology.core.design_validation import validate_mapping_design

    onto, source_root = _write_scope(tmp_path)
    report = validate_mapping_design(
        mapping_paths=(),
        mapping_graph=_mapping_graph("invoiceNumber", "chargeNumber"),
        source_root=source_root,
        ontology_path=onto,
    )
    assert _outside_class_codes(report), "expected property-outside-target-class diagnostic"
