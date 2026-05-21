# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Unit tests for the TMDL parser."""

import pytest

from kairos_ontology.tmdl_parser import (
    TmdlColumn,
    TmdlMeasure,
    TmdlModel,
    TmdlRelationship,
    TmdlTable,
    parse_model_tmdl,
    parse_tmdl_content,
)


# ---------------------------------------------------------------------------
# Table + column parsing
# ---------------------------------------------------------------------------


class TestParseTableColumns:
    """Tests for parsing table definitions with columns."""

    def test_basic_table_with_columns(self):
        content = """\
table d_Asset
\tlineageTag: abc-123

\tcolumn UnitType
\t\tdataType: string
\t\tlineageTag: def-456
\t\tsourceColumn: UnitType

\tcolumn Weight
\t\tdataType: double
\t\tformatString: 0.00
\t\tsourceColumn: Weight_KG
\t\tisHidden: true
"""
        results = parse_tmdl_content(content)
        assert len(results) == 1
        table = results[0]
        assert isinstance(table, TmdlTable)
        assert table.name == "d_Asset"
        assert table.lineage_tag == "abc-123"
        assert len(table.columns) == 2

        col1 = table.columns[0]
        assert col1.name == "UnitType"
        assert col1.data_type == "string"
        assert col1.source_column == "UnitType"
        assert col1.is_hidden is False

        col2 = table.columns[1]
        assert col2.name == "Weight"
        assert col2.data_type == "double"
        assert col2.format_string == "0.00"
        assert col2.source_column == "Weight_KG"
        assert col2.is_hidden is True

    def test_hidden_table(self):
        content = """\
table _MeasureTable
\tisHidden: true
\tlineageTag: hidden-123
"""
        results = parse_tmdl_content(content)
        table = results[0]
        assert table.is_hidden is True
        assert table.name == "_MeasureTable"

    def test_table_type_inference(self):
        fact = TmdlTable(name="f_ShippedVolumes")
        assert fact.table_type == "fact"

        dim = TmdlTable(name="d_Customer")
        assert dim.table_type == "dimension"

        bridge = TmdlTable(name="bridge_CustomerProduct")
        assert bridge.table_type == "bridge"

        measure_only = TmdlTable(name="KPIs", measures=[TmdlMeasure(name="Total")])
        assert measure_only.table_type == "measure_table"

        unknown = TmdlTable(name="SomeTable", columns=[TmdlColumn(name="col1")])
        assert unknown.table_type == "unknown"

    def test_empty_table(self):
        content = """\
table EmptyTable
\tlineageTag: empty-000
"""
        results = parse_tmdl_content(content)
        assert len(results) == 1
        table = results[0]
        assert table.name == "EmptyTable"
        assert table.columns == []
        assert table.measures == []

    def test_column_with_quoted_name(self):
        content = """\
table d_Route
\tcolumn 'Route Name'
\t\tdataType: string
\t\tsourceColumn: RouteName
"""
        results = parse_tmdl_content(content)
        table = results[0]
        assert table.columns[0].name == "Route Name"


# ---------------------------------------------------------------------------
# Measure parsing (including multiline DAX)
# ---------------------------------------------------------------------------


class TestParseMeasures:
    """Tests for parsing measures with DAX expressions."""

    def test_single_line_measure(self):
        content = """\
table f_Sales
\tmeasure TotalSales = SUM(f_Sales[Amount])
\t\tformatString: #,##0.00
"""
        results = parse_tmdl_content(content)
        table = results[0]
        assert len(table.measures) == 1
        m = table.measures[0]
        assert m.name == "TotalSales"
        assert m.expression == "SUM(f_Sales[Amount])"
        assert m.format_string == "#,##0.00"

    def test_multiline_dax_measure(self):
        content = """\
table f_Sales
\tmeasure GrossMargin =
\t\tVAR Revenue = SUM(f_Sales[Revenue])
\t\tVAR Cost = SUM(f_Sales[Cost])
\t\tRETURN Revenue - Cost
\t\tformatString: #,##0.00
"""
        results = parse_tmdl_content(content)
        table = results[0]
        m = table.measures[0]
        assert m.name == "GrossMargin"
        assert "VAR Revenue" in m.expression
        assert "RETURN Revenue - Cost" in m.expression
        assert m.format_string == "#,##0.00"

    def test_measure_with_empty_expression(self):
        content = """\
table Measures
\tmeasure Placeholder =
\t\tformatString: 0
"""
        results = parse_tmdl_content(content)
        table = results[0]
        m = table.measures[0]
        assert m.name == "Placeholder"
        # Expression is empty because formatString immediately follows
        assert m.expression == ""


# ---------------------------------------------------------------------------
# Relationship parsing
# ---------------------------------------------------------------------------


class TestParseRelationships:
    """Tests for parsing relationship definitions."""

    def test_basic_relationship(self):
        content = """\
relationship rel_001
\tfromTable: f_Sales
\tfromColumn: CustomerKey
\ttoTable: d_Customer
\ttoColumn: CustomerKey
\tfromCardinality: many
\ttoCardinality: one
\tcrossFilteringBehavior: oneDirection
"""
        results = parse_tmdl_content(content)
        assert len(results) == 1
        rel = results[0]
        assert isinstance(rel, TmdlRelationship)
        assert rel.name == "rel_001"
        assert rel.from_table == "f_Sales"
        assert rel.from_column == "CustomerKey"
        assert rel.to_table == "d_Customer"
        assert rel.to_column == "CustomerKey"
        assert rel.from_cardinality == "many"
        assert rel.to_cardinality == "one"
        assert rel.cross_filtering == "oneDirection"
        assert rel.is_active is True

    def test_inactive_relationship(self):
        content = """\
relationship rel_inactive
\tfromTable: f_Budget
\tfromColumn: DateKey
\ttoTable: d_Date
\ttoColumn: DateKey
\tfromCardinality: many
\ttoCardinality: one
\tisActive: false
"""
        results = parse_tmdl_content(content)
        rel = results[0]
        assert rel.is_active is False

    def test_multiple_relationships(self):
        content = """\
relationship rel_001
\tfromTable: f_Sales
\tfromColumn: CustomerKey
\ttoTable: d_Customer
\ttoColumn: CustomerKey
\tfromCardinality: many
\ttoCardinality: one

relationship rel_002
\tfromTable: f_Sales
\tfromColumn: ProductKey
\ttoTable: d_Product
\ttoColumn: ProductKey
\tfromCardinality: many
\ttoCardinality: one
"""
        results = parse_tmdl_content(content)
        assert len(results) == 2
        assert results[0].name == "rel_001"
        assert results[1].name == "rel_002"


# ---------------------------------------------------------------------------
# Model metadata parsing
# ---------------------------------------------------------------------------


class TestParseModelMetadata:
    """Tests for parsing model.tmdl metadata."""

    def test_model_metadata(self):
        content = """\
compatibilityLevel: 1604
defaultMode: directLake
culture: en-US
"""
        meta = parse_model_tmdl(content)
        assert meta["compatibilityLevel"] == "1604"
        assert meta["defaultMode"] == "directLake"
        assert meta["culture"] == "en-US"

    def test_model_metadata_partial(self):
        content = """\
compatibilityLevel: 1550
"""
        meta = parse_model_tmdl(content)
        assert meta["compatibilityLevel"] == "1550"
        assert "defaultMode" not in meta


# ---------------------------------------------------------------------------
# Partition parsing
# ---------------------------------------------------------------------------


class TestParsePartitions:
    """Tests for parsing table partition definitions."""

    def test_partition_with_mode(self):
        content = """\
table d_Customer
\tpartition CustomerData
\t\tmode: import
\t\ttype: m
"""
        results = parse_tmdl_content(content)
        table = results[0]
        assert len(table.partitions) == 1
        p = table.partitions[0]
        assert p.name == "CustomerData"
        assert p.mode == "import"
        assert p.source_type == "m"

    def test_calculated_partition(self):
        content = """\
table CalcTable
\tpartition CalcPartition
\t\ttype: calculated
"""
        results = parse_tmdl_content(content)
        table = results[0]
        assert table.partitions[0].source_type == "calculated"
        assert table.partition_type == "calculated"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and special patterns."""

    def test_multiple_tables_in_one_file(self):
        content = """\
table d_Customer
\tcolumn Name
\t\tdataType: string

table d_Product
\tcolumn SKU
\t\tdataType: string
"""
        results = parse_tmdl_content(content)
        assert len(results) == 2
        assert results[0].name == "d_Customer"
        assert results[1].name == "d_Product"

    def test_comments_are_ignored(self):
        content = """\
/// This is a comment
table d_Test
\t/// Another comment
\tcolumn Col1
\t\tdataType: int64
"""
        results = parse_tmdl_content(content)
        assert len(results) == 1
        assert results[0].columns[0].data_type == "int64"

    def test_table_with_description(self):
        content = """\
table d_Geography
\tdescription: "Geographic dimension table"
\tcolumn Country
\t\tdataType: string
\t\tdescription: "Country name"
"""
        results = parse_tmdl_content(content)
        table = results[0]
        assert table.description == "Geographic dimension table"
        assert table.columns[0].description == "Country name"
