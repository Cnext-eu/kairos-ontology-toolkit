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

from kairos_ontology.core.dbt_contract_sync import build_dbt_contract_graph
from kairos_ontology.core.dbt_contracts import DbtContractColumn, DbtContractModel

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

    def test_contracted_ref_uses_exclusive_virtual_source(self, test_hub):
        contract = _contract(test_hub)
        custom_sources = test_hub / "integration" / "sources" / "custom-transformations"
        custom_sources.mkdir()
        build_dbt_contract_graph(contract).serialize(
            custom_sources / "int_orders.vocabulary.ttl",
            format="turtle",
        )
        mapping = test_hub / "model" / "mappings" / "custom.ttl"
        mapping.write_text(
            dedent(
                """\
                @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
                @prefix skos: <http://www.w3.org/2004/02/skos/core#> .

                <https://example.com/custom/orders>
                    skos:exactMatch <http://example.org/test#Order> ;
                    kairos-map:mappingType "direct" .
                <https://example.com/custom/orders/order_id>
                    skos:exactMatch <http://example.org/test#orderId> ;
                    kairos-map:transform "source.order_id" .
                <https://example.com/custom/orders/amount>
                    skos:exactMatch <http://example.org/test#amount> ;
                    kairos-map:transform "source.amount" .
                """
            ),
            encoding="utf-8",
        )
        ext_path = test_hub / "model" / "extensions" / "test-silver-ext.ttl"
        ext_path.write_text(_silver_ext_ttl("int_orders"), encoding="utf-8")
        graph = Graph().parse(test_hub / "model" / "ontologies" / "test.ttl")

        from kairos_ontology.core.projections.medallion_dbt_projector import (
            generate_dbt_artifacts,
        )

        artifacts = generate_dbt_artifacts(
            classes=[
                {
                    "uri": NS + "Order",
                    "name": "Order",
                    "label": "Order",
                    "comment": "An order",
                }
            ],
            graph=graph,
            template_dir=TEMPLATE_DIR,
            namespace=NS,
            ontology_name="test",
            sources_dir=test_hub / "integration" / "sources",
            mappings_dir=test_hub / "model" / "mappings",
            silver_ext_path=ext_path,
            contract_registry={contract.name: contract},
        )

        sql = _find_model_sql(artifacts, "order")
        assert "ref('int_orders')" in sql
        assert "tblOrders" not in sql
        source_yamls = [
            content
            for path, content in artifacts.items()
            if path.endswith("__sources.yml")
        ]
        assert source_yamls
        assert all("int_orders" not in content for content in source_yamls)

    def test_contracted_ref_requires_semantic_key_alignment(self, test_hub):
        contract = _contract(test_hub, natural_key=("amount",))
        custom_sources = test_hub / "integration" / "sources" / "custom-transformations"
        custom_sources.mkdir()
        build_dbt_contract_graph(contract).serialize(
            custom_sources / "int_orders.vocabulary.ttl",
            format="turtle",
        )
        (test_hub / "model" / "mappings" / "custom.ttl").write_text(
            dedent(
                """\
                @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
                @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
                <https://example.com/custom/orders>
                    skos:exactMatch <http://example.org/test#Order> ;
                    kairos-map:mappingType "direct" .
                <https://example.com/custom/orders/order_id>
                    skos:exactMatch <http://example.org/test#orderId> .
                <https://example.com/custom/orders/amount>
                    skos:exactMatch <http://example.org/test#amount> .
                """
            ),
            encoding="utf-8",
        )
        ext_path = test_hub / "model" / "extensions" / "test-silver-ext.ttl"
        ext_path.write_text(_silver_ext_ttl("int_orders"), encoding="utf-8")
        graph = Graph().parse(test_hub / "model" / "ontologies" / "test.ttl")

        from kairos_ontology.core.projections.medallion_dbt_projector import (
            generate_dbt_artifacts,
        )

        with pytest.raises(ValueError, match="does not align"):
            generate_dbt_artifacts(
                classes=[
                    {
                        "uri": NS + "Order",
                        "name": "Order",
                        "label": "Order",
                        "comment": "An order",
                    }
                ],
                graph=graph,
                template_dir=TEMPLATE_DIR,
                namespace=NS,
                ontology_name="test",
                sources_dir=test_hub / "integration" / "sources",
                mappings_dir=test_hub / "model" / "mappings",
                silver_ext_path=ext_path,
                contract_registry={contract.name: contract},
            )


def _find_model_sql(artifacts: dict[str, str], model_name: str) -> str:
    """Find a silver model SQL by partial name match."""
    for key, content in artifacts.items():
        if model_name in key and "silver" in key and key.endswith(".sql"):
            return content
    raise KeyError(
        f"No silver model matching '{model_name}' found in: {list(artifacts.keys())}"
    )


def _contract(
    test_hub: Path,
    *,
    natural_key: tuple[str, ...] = ("order_id",),
) -> DbtContractModel:
    sql_path = test_hub / "integration" / "transforms" / "dbt" / "models" / "int_orders.sql"
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    sql_path.write_text("select 1\n", encoding="utf-8")
    return DbtContractModel(
        name="int_orders",
        description="Conformed orders",
        materialization="table",
        target_class=NS + "Order",
        virtual_source_iri="https://example.com/custom/orders",
        grain="one row per order",
        supported_adapters=("fabric", "databricks"),
        natural_key=natural_key,
        required_packages=(),
        required_macros=(),
        columns=(
            DbtContractColumn("order_id", "string"),
            DbtContractColumn("amount", "decimal(18,2)"),
        ),
        decisions=(),
        properties_path=sql_path.with_suffix(".yml"),
        sql_path=sql_path,
    )
