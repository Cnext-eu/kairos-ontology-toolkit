# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario parity for canonical direct and redirected foreign keys."""

from pathlib import Path

import yaml
import pytest
from rdflib import Graph

from kairos_ontology.core.projections.medallion_dbt_projector import (
    generate_dbt_artifacts,
)
from kairos_ontology.core.projections.medallion_gold_projector import (
    GoldContractError,
    generate_gold_artifacts,
)

from .conftest import TEMPLATE_DIR


NAMESPACE = "https://scenario.example/ontology/fk#"


ONTOLOGY = f"""
@prefix ex: <{NAMESPACE}> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<{NAMESPACE.rstrip("#")}> a owl:Ontology ;
    rdfs:label "FK parity" ;
    owl:versionInfo "1.0" .

ex:Order a owl:Class ;
    rdfs:label "Order" ; rdfs:comment "An order." ;
    kairos-ext:naturalKey "orderId" ;
    rdfs:subClassOf [
        a owl:Restriction ;
        owl:onProperty ex:placedBy ;
        owl:maxCardinality 1
    ] .
ex:Customer a owl:Class ;
    rdfs:label "Customer" ; rdfs:comment "A customer." ;
    kairos-ext:naturalKey "customerId" .
ex:OrderLine a owl:Class ;
    rdfs:label "Order line" ; rdfs:comment "An order line." ;
    kairos-ext:naturalKey "lineId" .

ex:orderId a owl:DatatypeProperty ;
    rdfs:domain ex:Order ; rdfs:range xsd:string ; rdfs:label "order ID" .
ex:customerId a owl:DatatypeProperty ;
    rdfs:domain ex:Customer ; rdfs:range xsd:string ; rdfs:label "customer ID" .
ex:lineId a owl:DatatypeProperty ;
    rdfs:domain ex:OrderLine ; rdfs:range xsd:string ; rdfs:label "line ID" .

ex:placedBy a owl:ObjectProperty ;
    rdfs:domain ex:Order ; rdfs:range ex:Customer ; rdfs:label "placed by" ;
    kairos-ext:silverForeignKeyTemporalMode "none" ;
    kairos-ext:silverForeignKeyChangeDetection false ;
    kairos-ext:silverForeignKeyCardinality "zero-or-one" ;
    kairos-ext:silverForeignKeyMissingPolicy "fail" ;
    kairos-ext:silverForeignKeyAmbiguousPolicy "fail" ;
    kairos-ext:silverForeignKeyLateParentPolicy "fail" .
ex:hasLine a owl:ObjectProperty ;
    rdfs:domain ex:Order ; rdfs:range ex:OrderLine ; rdfs:label "has line" ;
    kairos-ext:silverForeignKeyOn ex:OrderLine ;
    kairos-ext:silverForeignKeyTemporalMode "none" ;
    kairos-ext:silverForeignKeyChangeDetection false ;
    kairos-ext:silverForeignKeyCardinality "zero-or-one" ;
    kairos-ext:silverForeignKeyMissingPolicy "fail" ;
    kairos-ext:silverForeignKeyAmbiguousPolicy "fail" ;
    kairos-ext:silverForeignKeyLateParentPolicy "fail" .
"""


SOURCE = """
@prefix bronze: <https://scenario.example/bronze/erp#> .
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

bronze:ERP a kairos-bronze:SourceSystem ;
    rdfs:label "ERP" ;
    kairos-bronze:database "erp" ;
    kairos-bronze:schema "dbo" .

bronze:Orders a kairos-bronze:SourceTable ;
    kairos-bronze:sourceSystem bronze:ERP ;
    kairos-bronze:tableName "Orders" ;
    kairos-bronze:primaryKeyColumns "order_id" .
bronze:Orders_order_id a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze:Orders ;
    kairos-bronze:columnName "order_id" ;
    kairos-bronze:dataType "varchar" .
bronze:Orders_customer_id a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze:Orders ;
    kairos-bronze:columnName "customer_id" ;
    kairos-bronze:dataType "varchar" .

bronze:Customers a kairos-bronze:SourceTable ;
    kairos-bronze:sourceSystem bronze:ERP ;
    kairos-bronze:tableName "Customers" ;
    kairos-bronze:primaryKeyColumns "customer_id" .
bronze:Customers_customer_id a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze:Customers ;
    kairos-bronze:columnName "customer_id" ;
    kairos-bronze:dataType "varchar" .

bronze:OrderLines a kairos-bronze:SourceTable ;
    kairos-bronze:sourceSystem bronze:ERP ;
    kairos-bronze:tableName "OrderLines" ;
    kairos-bronze:primaryKeyColumns "line_id" .
bronze:OrderLines_line_id a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze:OrderLines ;
    kairos-bronze:columnName "line_id" ;
    kairos-bronze:dataType "varchar" .
bronze:OrderLines_order_id a kairos-bronze:SourceColumn ;
    kairos-bronze:sourceTable bronze:OrderLines ;
    kairos-bronze:columnName "order_id" ;
    kairos-bronze:dataType "varchar" .
"""


MAPPING = f"""
@prefix bronze: <https://scenario.example/bronze/erp#> .
@prefix ex: <{NAMESPACE}> .
@prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
@prefix map: <https://scenario.example/mapping/fk#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

bronze:Orders skos:exactMatch ex:Order .
bronze:Orders_order_id skos:exactMatch ex:orderId .
bronze:Orders_customer_id skos:exactMatch ex:placedBy .

bronze:Customers skos:exactMatch ex:Customer .
bronze:Customers_customer_id skos:exactMatch ex:customerId .

bronze:OrderLines skos:exactMatch ex:OrderLine .
bronze:OrderLines_line_id skos:exactMatch ex:lineId .
bronze:OrderLines_order_id skos:exactMatch ex:hasLine .

map:orders a kairos-map:TableMapping ;
    kairos-map:sourceTable bronze:Orders ;
    kairos-map:targetClass ex:Order ;
    kairos-map:mappingType "direct" ;
    kairos-map:matchType "exactMatch" .
map:customers a kairos-map:TableMapping ;
    kairos-map:sourceTable bronze:Customers ;
    kairos-map:targetClass ex:Customer ;
    kairos-map:mappingType "direct" ;
    kairos-map:matchType "exactMatch" .
map:lines a kairos-map:TableMapping ;
    kairos-map:sourceTable bronze:OrderLines ;
    kairos-map:targetClass ex:OrderLine ;
    kairos-map:mappingType "direct" ;
    kairos-map:matchType "exactMatch" .
map:orderId a kairos-map:ColumnMapping ;
    kairos-map:sourceColumn bronze:Orders_order_id ;
    kairos-map:targetProperty ex:orderId ;
    kairos-map:matchType "exactMatch" .
map:placedBy a kairos-map:ColumnMapping ;
    kairos-map:sourceColumn bronze:Orders_customer_id ;
    kairos-map:targetProperty ex:placedBy ;
    kairos-map:matchType "exactMatch" .
map:customerId a kairos-map:ColumnMapping ;
    kairos-map:sourceColumn bronze:Customers_customer_id ;
    kairos-map:targetProperty ex:customerId ;
    kairos-map:matchType "exactMatch" .
map:lineId a kairos-map:ColumnMapping ;
    kairos-map:sourceColumn bronze:OrderLines_line_id ;
    kairos-map:targetProperty ex:lineId ;
    kairos-map:matchType "exactMatch" .
map:hasLine a kairos-map:ColumnMapping ;
    kairos-map:sourceColumn bronze:OrderLines_order_id ;
    kairos-map:targetProperty ex:hasLine ;
    kairos-map:matchType "exactMatch" .
"""


PREPARATION = """
@prefix bronze: <https://scenario.example/bronze/erp#> .
@prefix prep: <https://scenario.example/preparation/erp#> .
@prefix kairos-prep: <https://kairos.cnext.eu/preparation#> .

prep:orders a kairos-prep:PreparationPolicy ;
    kairos-prep:sourceTable bronze:Orders ;
    kairos-prep:prepMode "passthrough" ;
    kairos-prep:schemaChangePolicy "fail" ;
    kairos-prep:recordKeyPolicy prep:ordersKey .
prep:ordersKey a kairos-prep:RecordKeyPolicy ;
    kairos-prep:sourceScope "erp" ;
    kairos-prep:tableScope "Orders" ;
    kairos-prep:recordKeyComponent bronze:Orders_order_id ;
    kairos-prep:recordKeyOutput prep:ordersRecordKey .
prep:ordersRecordKey a kairos-prep:PreparedColumn ;
    kairos-prep:targetColumnName "_source_record_key" ;
    kairos-prep:targetType "string" .

prep:customers a kairos-prep:PreparationPolicy ;
    kairos-prep:sourceTable bronze:Customers ;
    kairos-prep:prepMode "passthrough" ;
    kairos-prep:schemaChangePolicy "fail" ;
    kairos-prep:recordKeyPolicy prep:customersKey .
prep:customersKey a kairos-prep:RecordKeyPolicy ;
    kairos-prep:sourceScope "erp" ;
    kairos-prep:tableScope "Customers" ;
    kairos-prep:recordKeyComponent bronze:Customers_customer_id ;
    kairos-prep:recordKeyOutput prep:customersRecordKey .
prep:customersRecordKey a kairos-prep:PreparedColumn ;
    kairos-prep:targetColumnName "_source_record_key" ;
    kairos-prep:targetType "string" .

prep:lines a kairos-prep:PreparationPolicy ;
    kairos-prep:sourceTable bronze:OrderLines ;
    kairos-prep:prepMode "passthrough" ;
    kairos-prep:schemaChangePolicy "fail" ;
    kairos-prep:recordKeyPolicy prep:linesKey .
prep:linesKey a kairos-prep:RecordKeyPolicy ;
    kairos-prep:sourceScope "erp" ;
    kairos-prep:tableScope "OrderLines" ;
    kairos-prep:recordKeyComponent bronze:OrderLines_line_id ;
    kairos-prep:recordKeyOutput prep:linesRecordKey .
prep:linesRecordKey a kairos-prep:PreparedColumn ;
    kairos-prep:targetColumnName "_source_record_key" ;
    kairos-prep:targetType "string" .
"""


CLASSES = [
    {"uri": f"{NAMESPACE}Order", "name": "Order", "label": "Order", "comment": ""},
    {
        "uri": f"{NAMESPACE}Customer",
        "name": "Customer",
        "label": "Customer",
        "comment": "",
    },
    {
        "uri": f"{NAMESPACE}OrderLine",
        "name": "OrderLine",
        "label": "Order line",
        "comment": "",
    },
]


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    sources = tmp_path / "sources" / "erp"
    mappings = tmp_path / "mappings"
    sources.mkdir(parents=True)
    mappings.mkdir()
    preparation = tmp_path / "preparation"
    preparation.mkdir()
    (sources / "erp.ttl").write_text(SOURCE, encoding="utf-8")
    (mappings / "erp-to-fk.ttl").write_text(MAPPING, encoding="utf-8")
    (preparation / "erp-prep.ttl").write_text(
        PREPARATION,
        encoding="utf-8",
    )
    return sources.parent, mappings


def _table_block(ddl: str, table_name: str) -> str:
    start = ddl.index(f"CREATE TABLE {table_name} (")
    endings = [
        position
        for terminator in ("\n);", "\n)\n;")
        if (position := ddl.find(terminator, start)) >= 0
    ]
    return ddl[start:min(endings)]


def test_silver_fk_contract_is_authoritative_and_unprofiled_gold_blocks(tmp_path):
    graph = Graph()
    graph.parse(data=ONTOLOGY, format="turtle")
    sources_dir, mappings_dir = _write_inputs(tmp_path)

    dbt = generate_dbt_artifacts(
        CLASSES,
        graph,
        TEMPLATE_DIR,
        NAMESPACE,
        ontology_name="fk_parity",
        sources_dir=sources_dir,
        mappings_dir=mappings_dir,
        ontology_metadata={"generated_at": "2026-07-21T19:13:30Z"},
    )
    with pytest.raises(GoldContractError, match="profile-missing"):
        generate_gold_artifacts(
            CLASSES,
            graph,
            TEMPLATE_DIR,
            NAMESPACE,
            ontology_name="fk_parity",
            ontology_metadata={"version": "1.0"},
            sources_dir=sources_dir,
            mappings_dir=mappings_dir,
        )

    silver_ddl = dbt["analyses/fk_parity/fk_parity-ddl.sql"]
    order_sql = dbt["models/silver/fk_parity/order.sql"]
    order_line_sql = dbt["models/silver/fk_parity/order_line.sql"]
    schema = yaml.safe_load(dbt["models/silver/fk_parity/_fk_parity__models.yml"])
    schema_columns = {
        model["name"]: {column["name"] for column in model["columns"]}
        for model in schema["models"]
    }

    silver_order = _table_block(silver_ddl, "silver_fk_parity.order")
    silver_line = _table_block(silver_ddl, "silver_fk_parity.order_line")

    assert "customer_sk" in silver_order
    assert "customer_sk" in order_sql and "ref('customer')" in order_sql
    assert "customer_sk" in schema_columns["order"]

    assert "order_sk" in silver_line
    assert "order_sk" in order_line_sql and "ref('order')" in order_line_sql
    assert "order_sk" in schema_columns["order_line"]

    assert "UNENFORCED FOREIGN-KEY" in silver_ddl
    assert "REFERENCES silver_fk_parity.order (order_sk)" in silver_ddl
