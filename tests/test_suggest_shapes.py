# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for draft SHACL shape suggestions from bronze profiling metadata."""

from rdflib import Graph, Literal, Namespace, RDF, RDFS, XSD

from kairos_ontology.core.analyse_sources import KAIROS_BRONZE
from kairos_ontology.core.suggest_shapes import build_shapes_graph, suggest_shapes
from kairos_ontology.core.validator import validate_content

SH = Namespace("http://www.w3.org/ns/shacl#")
SRC = Namespace("https://kairos.cnext.eu/source/test#")


def _write_vocab(path):
    graph = Graph()
    graph.bind("kairos-bronze", KAIROS_BRONZE)
    graph.bind("src", SRC)

    table = SRC.Orders
    graph.add((table, RDF.type, KAIROS_BRONZE.SourceTable))
    graph.add((table, KAIROS_BRONZE.tableName, Literal("Orders")))

    columns = [
        ("Status", "string", False, ["new", "paid", "closed"], 3),
        ("Amount", "decimal", True, ["10.50", "20.00", "30.25"], None),
        ("Email", "string", True, ["jane.doe@example.com", "john@example.org"], 2),
        ("Priority", "string", True, ["low", "medium", "high", "urgent", "deferred"], None),
    ]
    for name, data_type, nullable, samples, distinct_count in columns:
        column = SRC[f"Orders_{name}"]
        graph.add((column, RDF.type, KAIROS_BRONZE.SourceColumn))
        graph.add((column, KAIROS_BRONZE.belongsToTable, table))
        graph.add((column, KAIROS_BRONZE.columnName, Literal(name)))
        graph.add((column, KAIROS_BRONZE.dataType, Literal(data_type)))
        graph.add((column, KAIROS_BRONZE.nullable, Literal(nullable, datatype=XSD.boolean)))
        graph.add((column, KAIROS_BRONZE.sampleValues, Literal(" | ".join(samples))))
        if distinct_count is not None:
            graph.add((column, KAIROS_BRONZE.distinctCount, Literal(distinct_count)))

    graph.serialize(destination=path, format="turtle")
    return path


def _draft_graph(tmp_path):
    vocab_path = _write_vocab(tmp_path / "source.vocabulary.ttl")
    out_path = suggest_shapes(vocab_path, tmp_path / "output" / "shapes-draft" / "source.ttl")
    graph = Graph()
    graph.parse(out_path, format="turtle")
    return graph, out_path


def _property_shape(graph, name):
    matches = [
        subject
        for subject in graph.subjects(SH.name, Literal(name))
        if (subject, RDF.type, SH.PropertyShape) in graph
    ]
    assert len(matches) == 1
    return matches[0]


def test_datatype_is_present_for_every_column(tmp_path):
    graph, _ = _draft_graph(tmp_path)

    property_shapes = list(graph.subjects(RDF.type, SH.PropertyShape))
    assert len(property_shapes) == 4
    for shape in property_shapes:
        assert (shape, SH.datatype, None) in graph


def test_min_count_only_uses_bronze_nullability(tmp_path):
    graph, _ = _draft_graph(tmp_path)
    status_shape = _property_shape(graph, "Status")
    amount_shape = _property_shape(graph, "Amount")

    assert (status_shape, SH.minCount, Literal(1)) in graph
    assert (amount_shape, SH.minCount, None) not in graph


def test_no_sample_derived_min_or_max_inclusive(tmp_path):
    graph, out_path = _draft_graph(tmp_path)
    serialized = out_path.read_text(encoding="utf-8")

    assert (None, SH.minInclusive, None) not in graph
    assert (None, SH.maxInclusive, None) not in graph
    assert "minInclusive" not in serialized
    assert "maxInclusive" not in serialized


def test_pii_email_is_not_enumerated_or_exposed(tmp_path):
    graph, out_path = _draft_graph(tmp_path)
    email_shape = _property_shape(graph, "Email")
    serialized = out_path.read_text(encoding="utf-8")

    assert (email_shape, SH["in"], None) not in graph
    assert "jane.doe@example.com" not in serialized
    assert "john@example.org" not in serialized


def test_sh_in_requires_real_low_distinct_count(tmp_path):
    graph, _ = _draft_graph(tmp_path)
    status_shape = _property_shape(graph, "Status")
    priority_shape = _property_shape(graph, "Priority")

    assert (status_shape, SH["in"], None) in graph
    assert (priority_shape, SH["in"], None) not in graph
    assert len(list(graph.triples((None, SH["in"], None)))) == 1
    comments = [str(comment) for comment in graph.objects(priority_shape, RDFS.comment)]
    assert "possible enum (unverified: only 5 sampled values)" in comments


def test_generated_graph_round_trips_through_validator(tmp_path):
    graph, _ = _draft_graph(tmp_path)

    result = validate_content(graph.serialize(format="turtle"), do_shacl=False)

    assert result["syntax"]["passed"]


def test_suggest_shapes_refuses_overwrite_without_force(tmp_path):
    vocab_path = _write_vocab(tmp_path / "source.vocabulary.ttl")
    out_path = tmp_path / "output" / "shapes-draft" / "source.ttl"

    assert suggest_shapes(vocab_path, out_path) == out_path
    try:
        suggest_shapes(vocab_path, out_path)
    except FileExistsError as exc:
        assert "Refusing to overwrite existing draft shapes file" in str(exc)
    else:
        raise AssertionError("Expected FileExistsError")

    suggest_shapes(vocab_path, out_path, force=True, include_sample_values=False)
    assert out_path.exists()


def test_draft_ttl_suffix_is_not_loaded_by_validator_shapes_glob(tmp_path):
    vocab_path = _write_vocab(tmp_path / "source.vocabulary.ttl")
    out_path = tmp_path / "model" / "shapes" / "_draft" / "source.ttl"

    suggest_shapes(vocab_path, out_path)

    assert out_path.exists()
    assert not out_path.name.endswith(".shacl.ttl")
    assert list((tmp_path / "model" / "shapes").glob("**/*.shacl.ttl")) == []


def test_include_sample_values_false_omits_example_comments():
    graph = build_shapes_graph(
        {
            "Orders": [
                {
                    "name": "Status",
                    "data_type": "string",
                    "nullable": True,
                    "samples": ["new", "paid"],
                }
            ]
        },
        include_sample_values=False,
    )
    comments = [str(comment) for comment in graph.objects(None, RDFS.comment)]

    assert all("Example values:" not in comment for comment in comments)
