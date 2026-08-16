# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Per-table vocabulary is a projection of the aggregate, never a re-derivation (DD-182).

`import-source` writes each table twice: once into the source's aggregate
`<system>.vocabulary.ttl` and once into `vocabulary/<table>.vocabulary.ttl`.
Deriving the two independently let them drift. The aggregate is updated by an
in-place merge that syncs a fixed list of managed predicates; the per-table
files were regenerated wholesale from the source schema. An enrichment added to
the generator but not to the merge's sync list therefore landed in one and never
the other.

`formatHint` did exactly that, on 38 columns of the live hub. The source catalog
could not decide which definition was authoritative, reported 75 conflicts, and
refused to load — blocking affinity, alignment and everything downstream.

These tests pin the property that makes that class of bug impossible: whatever
the aggregate says about a table is, verbatim, what its per-table file says.
"""

from rdflib import Graph, Namespace, RDF, URIRef

from kairos_ontology.core.import_source import (
    generate_vocabulary_ttl,
    split_vocabulary_by_table,
)

BR = Namespace("https://kairos.cnext.eu/bronze#")

DATA = {
    "system": "acme",
    "extracted_at": "2026-08-16",
    "connection": {"database": "db", "schema": "dbo"},
    "tables": [
        {
            "name": "stops",
            "columns": [
                {"name": "id", "data_type": "int", "nullable": False, "is_primary_key": True},
                {
                    "name": "window_start",
                    "data_type": "varchar",
                    "nullable": True,
                    "format_hint": "date",
                },
                {
                    "name": "status",
                    "data_type": "varchar",
                    "nullable": True,
                    "sample_values": ["OPEN", "DONE"],
                },
            ],
        },
        {
            "name": "orders",
            "columns": [{"name": "order_no", "data_type": "varchar", "nullable": False}],
        },
    ],
}


def split(data=DATA):
    ttl = generate_vocabulary_ttl(data)
    return ttl, split_vocabulary_by_table(
        ttl, system_name=data["system"], extracted_at=data.get("extracted_at", "")
    )


def table_facts(graph, table_uri):
    """Every triple the source catalog's signature covers: the table and its columns."""
    columns = set(graph.subjects(BR.belongsToTable, table_uri))
    columns.update(graph.subjects(BR.sourceTable, table_uri))
    return {
        (str(s), str(p), str(o))
        for s in {table_uri, *columns}
        for p, o in graph.predicate_objects(s)
    }


class TestProjectionIsFaithful:
    def test_every_table_is_split_out(self):
        _, per = split()
        assert set(per) == {"stops", "orders"}

    def test_table_and_column_triples_match_the_aggregate_exactly(self):
        """The property that makes the catalog conflict impossible."""
        ttl, per = split()
        agg = Graph()
        agg.parse(data=ttl, format="turtle")
        for name in per:
            uri = URIRef(f"https://kairos.cnext.eu/source/acme#{name}")
            one = Graph()
            one.parse(data=per[name], format="turtle")
            assert table_facts(one, uri) == table_facts(agg, uri), (
                f"{name}: per-table file disagrees with the aggregate"
            )

    def test_format_hint_survives_the_split(self):
        """The exact predicate whose loss blocked the live hub."""
        _, per = split()
        one = Graph()
        one.parse(data=per["stops"], format="turtle")
        hints = {str(o) for o in one.objects(None, BR.formatHint)}
        assert hints == {"date"}

    def test_a_predicate_the_merge_never_syncs_still_survives(self):
        """Regression guard: the split must not have its own allow-list."""
        data = {
            **DATA,
            "tables": [
                {
                    "name": "t",
                    "columns": [
                        {
                            "name": "c",
                            "data_type": "varchar",
                            "nullable": True,
                            "format_hint": "email",
                            "suggested_fk": "other.id",
                        }
                    ],
                }
            ],
        }
        ttl, per = split(data)
        agg, one = Graph(), Graph()
        agg.parse(data=ttl, format="turtle")
        one.parse(data=per["t"], format="turtle")
        uri = URIRef("https://kairos.cnext.eu/source/acme#t")
        assert table_facts(one, uri) == table_facts(agg, uri)

    def test_columns_are_not_leaked_between_tables(self):
        _, per = split()
        one = Graph()
        one.parse(data=per["orders"], format="turtle")
        names = {str(o) for o in one.objects(None, BR.columnName)}
        assert names == {"order_no"}


class TestPerFileMetadata:
    def test_each_file_declares_its_own_ontology(self):
        _, per = split()
        one = Graph()
        one.parse(data=per["stops"], format="turtle")
        ont = URIRef("https://kairos.cnext.eu/source/acme/vocabulary/stops")
        assert (ont, RDF.type, None) in one

    def test_system_context_is_repeated_in_each_file(self):
        _, per = split()
        for name in per:
            one = Graph()
            one.parse(data=per[name], format="turtle")
            assert list(one.subjects(RDF.type, BR.SourceSystem)), f"{name} lost system context"

    def test_provenance_header_names_the_table(self):
        _, per = split()
        assert "# Table : stops" in per["stops"]


class TestCatalogAcceptsTheResult:
    def test_no_conflict_when_both_files_are_loaded(self, tmp_path):
        """End to end: the catalog must load both forms without complaint."""
        from kairos_ontology.core.source_catalog import build_source_catalog

        ttl, per = split()
        sysdir = tmp_path / "acme"
        (sysdir / "vocabulary").mkdir(parents=True)
        (sysdir / "acme.vocabulary.ttl").write_text(ttl, encoding="utf-8")
        for name, text in per.items():
            (sysdir / "vocabulary" / f"{name}.vocabulary.ttl").write_text(text, encoding="utf-8")

        catalog = build_source_catalog(tmp_path)
        assert catalog.conflicts == [], catalog.conflicts
        assert len(catalog.tables) == 2

    def test_a_deliberately_edited_per_table_file_is_still_caught(self, tmp_path):
        """The guard must stay able to detect a real divergence."""
        from kairos_ontology.core.source_catalog import build_source_catalog

        ttl, per = split()
        sysdir = tmp_path / "acme"
        (sysdir / "vocabulary").mkdir(parents=True)
        (sysdir / "acme.vocabulary.ttl").write_text(ttl, encoding="utf-8")
        tampered = per["stops"].replace('"date"', '"datetime"')
        (sysdir / "vocabulary" / "stops.vocabulary.ttl").write_text(tampered, encoding="utf-8")
        (sysdir / "vocabulary" / "orders.vocabulary.ttl").write_text(
            per["orders"], encoding="utf-8"
        )

        catalog = build_source_catalog(tmp_path)
        assert any("conflicting" in c for c in catalog.conflicts)
