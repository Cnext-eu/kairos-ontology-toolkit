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
    # DD-156 evidence: distinct counts are full-table facts (warehouse-shaped
    # profile — an explicit "table" scope without a rowCount, so the sh:in
    # floor does not apply).
    graph.add((table, KAIROS_BRONZE.distinctScope, Literal("table")))

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


# --------------------------------------------------------------------------- #
# #424 / DD-076 amendment: sh:in only from full-table distinct evidence
# --------------------------------------------------------------------------- #


def _write_evidence_vocab(
    path,
    columns,
    *,
    distinct_scope=None,
    row_count=None,
    rows_sampled=None,
):
    """Write a single-table vocabulary with configurable DD-156 table evidence.

    ``columns`` is a list of dicts: name (required), data_type, nullable,
    samples, distinct_count, format_hint.
    """
    graph = Graph()
    graph.bind("kairos-bronze", KAIROS_BRONZE)
    graph.bind("src", SRC)

    table = SRC.Orders
    graph.add((table, RDF.type, KAIROS_BRONZE.SourceTable))
    graph.add((table, KAIROS_BRONZE.tableName, Literal("Orders")))
    if distinct_scope is not None:
        graph.add((table, KAIROS_BRONZE.distinctScope, Literal(distinct_scope)))
    if row_count is not None:
        graph.add((table, KAIROS_BRONZE.rowCount, Literal(row_count, datatype=XSD.integer)))
    if rows_sampled is not None:
        graph.add((table, KAIROS_BRONZE.rowsSampled, Literal(rows_sampled, datatype=XSD.integer)))

    for col in columns:
        column = SRC[f"Orders_{col['name']}"]
        graph.add((column, RDF.type, KAIROS_BRONZE.SourceColumn))
        graph.add((column, KAIROS_BRONZE.belongsToTable, table))
        graph.add((column, KAIROS_BRONZE.columnName, Literal(col["name"])))
        graph.add((column, KAIROS_BRONZE.dataType, Literal(col.get("data_type", "string"))))
        graph.add(
            (
                column,
                KAIROS_BRONZE.nullable,
                Literal(col.get("nullable", True), datatype=XSD.boolean),
            )
        )
        if col.get("samples"):
            graph.add((column, KAIROS_BRONZE.sampleValues, Literal(" | ".join(col["samples"]))))
        if col.get("distinct_count") is not None:
            graph.add((column, KAIROS_BRONZE.distinctCount, Literal(col["distinct_count"])))
        if col.get("format_hint"):
            graph.add((column, KAIROS_BRONZE.formatHint, Literal(col["format_hint"])))

    graph.serialize(destination=path, format="turtle")
    return path


def _evidence_graph(tmp_path, columns, **table_evidence):
    vocab_path = _write_evidence_vocab(
        tmp_path / "source.vocabulary.ttl", columns, **table_evidence
    )
    out_path = suggest_shapes(vocab_path, tmp_path / "draft" / "source.ttl")
    graph = Graph()
    graph.parse(out_path, format="turtle")
    return graph


def _comments(graph, shape):
    return [str(comment) for comment in graph.objects(shape, RDFS.comment)]


def test_saturated_sample_window_yields_no_sh_in(tmp_path):
    graph = _evidence_graph(
        tmp_path,
        [{"name": "Code", "samples": ["a", "b", "c", "d", "e"], "distinct_count": 5}],
        distinct_scope="sample",
        rows_sampled=5,
    )
    shape = _property_shape(graph, "Code")

    assert (shape, SH["in"], None) not in graph
    assert (
        "enum not suggested: distinctCount=5 saturates the 5-row sample window; "
        "evidence cannot distinguish an enum from an open value set."
    ) in _comments(graph, shape)


def test_small_sample_window_yields_floor_comment_not_sh_in(tmp_path):
    graph = _evidence_graph(
        tmp_path,
        [{"name": "Status", "samples": ["new", "paid", "closed"], "distinct_count": 3}],
        distinct_scope="sample",
        rows_sampled=50,
    )
    shape = _property_shape(graph, "Status")

    assert (shape, SH["in"], None) not in graph
    assert (
        "enum not suggested: only 50 rows profiled (< 100); re-import with a larger "
        "--max-rows or profile the warehouse table."
    ) in _comments(graph, shape)


def test_unsaturated_large_sample_window_yields_advisory_not_sh_in(tmp_path):
    graph = _evidence_graph(
        tmp_path,
        [{"name": "Status", "samples": ["new", "paid", "closed", "held"], "distinct_count": 4}],
        distinct_scope="sample",
        rows_sampled=1000,
    )
    shape = _property_shape(graph, "Status")

    assert (shape, SH["in"], None) not in graph
    assert (
        "possible enum: 4 distinct values in 1000 sampled rows; "
        "sample-scoped evidence — not verified against full data."
    ) in _comments(graph, shape)


def test_legacy_vocabulary_without_scope_yields_regenerate_comment_not_sh_in(tmp_path):
    graph = _evidence_graph(
        tmp_path,
        [{"name": "Status", "samples": ["new", "paid", "closed"], "distinct_count": 3}],
    )
    shape = _property_shape(graph, "Status")

    assert (shape, SH["in"], None) not in graph
    assert (
        "possible enum (unverified: profiling predates rows-sampled evidence; "
        "regenerate the source vocabulary with import-source)."
    ) in _comments(graph, shape)


def test_temporal_decimal_and_boolean_columns_are_never_enumerated(tmp_path):
    graph = _evidence_graph(
        tmp_path,
        [
            {
                "name": "CreatedAt",
                "data_type": "datetime",
                "samples": ["2026-01-01 10:00:00", "2026-01-02 11:00:00"],
                "distinct_count": 2,
            },
            {
                "name": "Rate",
                "data_type": "decimal",
                "samples": ["1.5", "2.5"],
                "distinct_count": 2,
            },
            {
                "name": "IsActive",
                "data_type": "bit",
                "samples": ["0", "1"],
                "distinct_count": 2,
            },
        ],
        distinct_scope="table",
    )

    assert list(graph.triples((None, SH["in"], None))) == []
    for name in ("CreatedAt", "Rate", "IsActive"):
        shape = _property_shape(graph, name)
        assert all("enum" not in comment.lower() for comment in _comments(graph, shape))
        # sh:datatype still carries the signal.
        assert (shape, SH.datatype, None) in graph


def test_uuid_via_format_hint_is_never_enumerated(tmp_path):
    graph = _evidence_graph(
        tmp_path,
        [
            {
                "name": "ExternalId",
                "data_type": "uniqueidentifier",
                "samples": ["x1", "x2", "x3"],
                "distinct_count": 3,
                "format_hint": "uuid",
            }
        ],
        distinct_scope="table",
    )
    shape = _property_shape(graph, "ExternalId")

    assert (shape, SH["in"], None) not in graph
    assert all("enum" not in comment.lower() for comment in _comments(graph, shape))


def test_uuid_via_sample_pattern_without_format_hint_is_never_enumerated(tmp_path):
    graph = _evidence_graph(
        tmp_path,
        [
            {
                "name": "ExternalId",
                "data_type": "nvarchar(36)",
                "samples": [
                    "a1b2c3d4-e5f6-4a3b-8c9d-ef1234567890",
                    "b2c3d4e5-f6a1-4b3c-9d8e-f01234567891",
                    "c3d4e5f6-a1b2-4c3d-8e9f-012345678912",
                ],
                "distinct_count": 3,
            }
        ],
        distinct_scope="table",
    )
    shape = _property_shape(graph, "ExternalId")

    assert (shape, SH["in"], None) not in graph
    assert all("enum" not in comment.lower() for comment in _comments(graph, shape))


def test_integer_code_column_with_table_scope_is_enumerated(tmp_path):
    graph = _evidence_graph(
        tmp_path,
        [
            {
                "name": "StatusCode",
                "data_type": "int",
                "samples": ["10", "20", "30"],
                "distinct_count": 3,
            }
        ],
        distinct_scope="table",
    )
    shape = _property_shape(graph, "StatusCode")

    assert (shape, SH["in"], None) in graph
    assert (
        "Enum constraint from full-table distinctCount=3; all 3 values observed in "
        "samples; review before publishing."
    ) in _comments(graph, shape)


def test_known_row_count_below_floor_blocks_sh_in_even_with_table_scope(tmp_path):
    graph = _evidence_graph(
        tmp_path,
        [{"name": "Status", "samples": ["new", "paid", "closed"], "distinct_count": 3}],
        distinct_scope="table",
        row_count=50,
        rows_sampled=50,
    )
    shape = _property_shape(graph, "Status")

    assert (shape, SH["in"], None) not in graph
    assert (
        "enum not suggested: only 50 rows profiled (< 100); re-import with a larger "
        "--max-rows or profile the warehouse table."
    ) in _comments(graph, shape)


def test_known_row_count_above_floor_emits_sh_in(tmp_path):
    graph = _evidence_graph(
        tmp_path,
        [{"name": "Status", "samples": ["new", "paid", "closed"], "distinct_count": 3}],
        distinct_scope="table",
        row_count=5000,
    )
    shape = _property_shape(graph, "Status")

    assert (shape, SH["in"], None) in graph


def test_end_to_end_capped_flatfile_import_yields_zero_sh_in(tmp_path):
    """A capped CSV import (distinctScope 'sample') must never produce sh:in.

    Runs the CURRENT import path (import-flatfile → import-source) end to end —
    this is the exact pipeline that produced the provably wrong single-value
    enums in #424.
    """
    import yaml

    from kairos_ontology.core.import_flatfile import run_import_flatfile
    from kairos_ontology.core.import_source import parse_source_schema_dir, run_import_source

    csv_file = tmp_path / "input" / "orders.csv"
    csv_file.parent.mkdir()
    lines = ["id,booking_status\n"] + [f"{i},TO_REQUEST\n" for i in range(50)]
    csv_file.write_text("".join(lines), encoding="utf-8")

    schema_dir = tmp_path / "extracted" / "orders"
    run_import_flatfile(csv_file, output_dir=schema_dir, max_rows=10)

    # Same assembly the import-source CLI performs for a schema directory.
    data = parse_source_schema_dir(schema_dir)
    combined = tmp_path / "combined.yaml"
    combined.write_text(yaml.dump(data, sort_keys=False), encoding="utf-8")
    vocab_path, _ = run_import_source(combined, output_dir=tmp_path / "sources")

    out_path = suggest_shapes(vocab_path, tmp_path / "draft" / "orders.ttl")
    graph = Graph()
    graph.parse(out_path, format="turtle")

    assert list(graph.triples((None, SH["in"], None))) == []
    all_comments = " ".join(str(comment) for comment in graph.objects(None, RDFS.comment))
    # booking_status: 1 distinct value in a 10-row window → floor advisory, no enum.
    assert "rows profiled" in all_comments
