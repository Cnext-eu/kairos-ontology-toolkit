# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for silverSourceRef annotation (DD-039).

Verifies the dbt projector emits {{ ref('model') }} instead of {{ source() }}
when a class has kairos-ext:silverSourceRef set.
"""

from pathlib import Path
from textwrap import dedent

import pytest
from rdflib import Graph

TEMPLATE_DIR = (
    Path(__file__).parent.parent
    / "src"
    / "kairos_ontology"
    / "templates"
    / "dbt"
)

NS = "http://example.org/test#"

# Minimal source vocabulary TTL
_SOURCE_TTL = dedent("""\
    @prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

    <http://example.org/source#erp> a kairos-bronze:SourceSystem ;
        rdfs:label "erp" ;
        kairos-bronze:database "erpdb" ;
        kairos-bronze:schema "dbo" .

    <http://example.org/source#tblOrders> a kairos-bronze:SourceTable ;
        rdfs:label "tblOrders" ;
        kairos-bronze:sourceSystem <http://example.org/source#erp> ;
        kairos-bronze:tableName "tblOrders" .

    <http://example.org/source#tblOrders_OrderId> a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable <http://example.org/source#tblOrders> ;
        kairos-bronze:columnName "OrderId" ;
        kairos-bronze:dataType "varchar(50)" .

    <http://example.org/source#tblOrders_Amount> a kairos-bronze:SourceColumn ;
        kairos-bronze:sourceTable <http://example.org/source#tblOrders> ;
        kairos-bronze:columnName "Amount" ;
        kairos-bronze:dataType "decimal(18,2)" .
""")

# Minimal SKOS mapping TTL
_MAPPING_TTL = dedent("""\
    @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
    @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

    # Table mapping: tblOrders → Order (direct 1:1)
    <http://example.org/source#tblOrders> skos:exactMatch <http://example.org/test#Order> ;
        kairos-map:mappingType "direct" .

    # Column mappings
    <http://example.org/source#tblOrders_OrderId> skos:exactMatch <http://example.org/test#orderId> ;
        kairos-map:transform "source.OrderId" .

    <http://example.org/source#tblOrders_Amount> skos:exactMatch <http://example.org/test#amount> ;
        kairos-map:transform "CAST(source.Amount AS DECIMAL(18,2))" .
""")

# Domain ontology TTL (without silverSourceRef — added via extension)
_ONTOLOGY_TTL = dedent("""\
    @prefix owl:  <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
    @prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
    @prefix : <http://example.org/test#> .

    <http://example.org/test> a owl:Ontology ;
        rdfs:label "Test Ontology" ;
        owl:versionInfo "1.0.0" ;
        kairos-ext:silverSchema "silver_test" .

    :Order a owl:Class ;
        rdfs:label "Order" ;
        rdfs:comment "An order entity" ;
        kairos-ext:naturalKey "orderId" .

    :orderId a owl:DatatypeProperty ;
        rdfs:label "orderId" ;
        rdfs:domain :Order ;
        rdfs:range xsd:string .

    :amount a owl:DatatypeProperty ;
        rdfs:label "amount" ;
        rdfs:domain :Order ;
        rdfs:range xsd:decimal .
""")


def _silver_ext_ttl(source_ref: str | None = None) -> str:
    """Generate silver extension TTL, optionally with silverSourceRef."""
    lines = [
        '@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .',
        '@prefix : <http://example.org/test#> .',
        '',
    ]
    if source_ref:
        lines.append(f':Order kairos-ext:silverSourceRef "{source_ref}" .')
    return "\n".join(lines)


@pytest.fixture()
def test_hub(tmp_path):
    """Create a minimal hub file structure for the dbt projector."""
    sources_dir = tmp_path / "integration" / "sources" / "erp"
    sources_dir.mkdir(parents=True)
    (sources_dir / "erp.vocabulary.ttl").write_text(_SOURCE_TTL, encoding="utf-8")

    mappings_dir = tmp_path / "model" / "mappings"
    mappings_dir.mkdir(parents=True)
    (mappings_dir / "erp-mapping.ttl").write_text(_MAPPING_TTL, encoding="utf-8")

    ontology_dir = tmp_path / "model" / "ontologies"
    ontology_dir.mkdir(parents=True)
    (ontology_dir / "test.ttl").write_text(_ONTOLOGY_TTL, encoding="utf-8")

    ext_dir = tmp_path / "model" / "extensions"
    ext_dir.mkdir(parents=True)

    return tmp_path


def _generate(test_hub: Path, source_ref: str | None = None) -> dict[str, str]:
    """Run dbt projection and return artifacts."""
    from kairos_ontology.core.projections.medallion_dbt_projector import (
        generate_dbt_artifacts,
    )

    # Write silver ext with or without sourceRef
    ext_dir = test_hub / "model" / "extensions"
    ext_path = ext_dir / "test-silver-ext.ttl"
    ext_path.write_text(_silver_ext_ttl(source_ref), encoding="utf-8")

    # Load ontology
    g = Graph()
    g.parse(test_hub / "model" / "ontologies" / "test.ttl", format="turtle")

    classes = [
        {"uri": NS + "Order", "name": "Order", "label": "Order", "comment": "An order"}
    ]
    return generate_dbt_artifacts(
        classes=classes,
        graph=g,
        template_dir=TEMPLATE_DIR,
        namespace=NS,
        ontology_name="test",
        sources_dir=test_hub / "integration" / "sources",
        mappings_dir=test_hub / "model" / "mappings",
        silver_ext_path=ext_path,
    )


class TestSilverSourceRef:
    """Tests for kairos-ext:silverSourceRef annotation (DD-039)."""

    def test_without_annotation_uses_source(self, test_hub):
        """Default: no silverSourceRef → {{ source() }}."""
        artifacts = _generate(test_hub, source_ref=None)
        sql = _find_model_sql(artifacts, "order")
        assert "source('erp', 'tblOrders')" in sql
        assert "ref(" not in sql

    def test_with_annotation_uses_ref(self, test_hub):
        """With silverSourceRef → {{ ref('model_name') }}."""
        artifacts = _generate(test_hub, source_ref="stg_erp_orders_details")
        sql = _find_model_sql(artifacts, "order")
        assert "ref('stg_erp_orders_details')" in sql
        assert "source(" not in sql

    def test_ref_model_in_from_clause(self, test_hub):
        """The ref() appears in a proper FROM context."""
        artifacts = _generate(test_hub, source_ref="stg_erp_orders_payload")
        sql = _find_model_sql(artifacts, "order")
        assert "select * from {{ ref('stg_erp_orders_payload') }}" in sql


def _find_model_sql(artifacts: dict[str, str], model_name: str) -> str:
    """Find a silver model SQL by partial name match."""
    for key, content in artifacts.items():
        if model_name in key and "silver" in key and key.endswith(".sql"):
            return content
    raise KeyError(
        f"No silver model matching '{model_name}' found in: {list(artifacts.keys())}"
    )
