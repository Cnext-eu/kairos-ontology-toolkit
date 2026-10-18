# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A shipped reference list's members become a hub seed (DD-257, #1126 P2)."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from rdflib import Graph

from kairos_ontology.cli.main import cli
from kairos_ontology.core.reference_lists import (
    GENERATED_MARKER,
    ReferenceListError,
    read_origin,
    collect_reference_list,
    default_seed_name,
    diff_seed,
    render_seed_csv,
    render_seed_docs,
)

_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix ref: <https://example.com/ont/reference-data#> .
@prefix std: <https://example.org/std/> .

<https://example.com/ont/reference-data> a owl:Ontology .

ref:TransportModeCode a owl:Class .
std:ModeList a owl:Class ;
    rdfs:subClassOf ref:TransportModeCode ;
    owl:versionInfo "2026-10-17" ;
    dcterms:source <https://example.org/std/> .
std:LegacyModeList a owl:Class ; rdfs:subClassOf ref:TransportModeCode .
std:Location a owl:Class ;
    dcterms:source <https://example.org/locations> .

std:ModeList-4 a owl:NamedIndividual, std:ModeList, ref:TransportModeCode ;
    rdf:value "4" ;
    rdfs:label "Luftverkehr"@de, "Air transport"@en .
std:ModeList-1 a owl:NamedIndividual, std:ModeList ;
    rdf:value "1" ;
    rdfs:comment "Maritime transport" .
std:ModeList-02 a owl:NamedIndividual, std:ModeList ;
    rdf:value "02" ;
    rdfs:label "Rail transport" .
std:Legacy-A a owl:NamedIndividual, std:LegacyModeList ;
    skos:notation "A" ;
    skos:prefLabel "Air (legacy)" .
std:NoCode a owl:NamedIndividual, std:ModeList ;
    rdfs:label "Has no code" .
"""


@pytest.fixture
def graph() -> Graph:
    return Graph().parse(data=_TTL, format="turtle")


class TestCollect:
    def test_the_governed_class_collects_every_list_below_it(self, graph):
        reference = collect_reference_list(
            graph, "https://example.com/ont/reference-data#TransportModeCode"
        )
        rows = [(m.code_list, m.code, m.name) for m in reference.members]
        assert rows == [
            ("LegacyModeList", "A", "Air (legacy)"),
            ("ModeList", "02", "Rail transport"),
            ("ModeList", "1", "Maritime transport"),
            ("ModeList", "4", "Air transport"),
        ]

    def test_a_member_typed_twice_belongs_to_its_most_specific_list(self, graph):
        reference = collect_reference_list(
            graph, "https://example.com/ont/reference-data#TransportModeCode"
        )
        air = next(m for m in reference.members if m.code == "4")
        assert air.code_list == "ModeList"
        assert air.iri == "https://example.org/std/ModeList-4"

    def test_the_lists_snapshot_and_source_are_kept(self, graph):
        reference = collect_reference_list(graph, "https://example.org/std/ModeList")
        assert [(p.name, p.version, p.source) for p in reference.lists] == [
            ("ModeList", "2026-10-17", "https://example.org/std/")
        ]

    def test_a_member_without_a_code_is_skipped_and_reported(self, graph):
        reference = collect_reference_list(graph, "https://example.org/std/ModeList")
        assert reference.skipped == ("https://example.org/std/NoCode",)

    def test_a_list_with_no_members_is_kind_2_or_3_not_an_empty_seed(self, graph):
        with pytest.raises(ReferenceListError, match="kind 2"):
            collect_reference_list(graph, "https://example.org/std/Location")

    def test_an_unknown_class_is_an_error(self, graph):
        with pytest.raises(ReferenceListError, match="does not resolve"):
            collect_reference_list(graph, "https://example.org/std/Missing")

    def test_two_members_with_one_key_are_rejected(self, graph):
        graph.parse(
            data="@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .\n"
            "<https://example.org/std/ModeList-4b> a <https://example.org/std/ModeList> ;"
            ' rdf:value "4" .',
            format="turtle",
        )
        with pytest.raises(ReferenceListError, match="ModeList '4'"):
            collect_reference_list(graph, "https://example.org/std/ModeList")


class TestRender:
    def test_csv_is_keyed_on_list_and_code_with_the_iri_as_a_column(self, graph):
        reference = collect_reference_list(graph, "https://example.org/std/ModeList")
        assert render_seed_csv(reference).splitlines() == [
            "code_list,code,name,iri,list_version,list_source,deprecated",
            "ModeList,02,Rail transport,https://example.org/std/ModeList-02,"
            "2026-10-17,https://example.org/std/,false",
            "ModeList,1,Maritime transport,https://example.org/std/ModeList-1,"
            "2026-10-17,https://example.org/std/,false",
            "ModeList,4,Air transport,https://example.org/std/ModeList-4,"
            "2026-10-17,https://example.org/std/,false",
        ]

    def test_docs_carry_the_marker_snapshot_and_text_types(self, graph):
        reference = collect_reference_list(graph, "https://example.org/std/ModeList")
        text = render_seed_docs(reference, "mode_list", {"code": "VARCHAR(16)"})
        assert text.startswith(GENERATED_MARKER)
        seed = yaml.safe_load(text)["seeds"][0]
        assert seed["name"] == "mode_list"
        assert seed["config"] == {"column_types": {"code": "VARCHAR(16)"}}
        assert "snapshot 2026-10-17" in seed["description"]
        assert "mode_list_local" in seed["description"]
        assert "meta" not in seed

    def test_docs_without_an_adapter_have_no_column_types(self, graph):
        reference = collect_reference_list(graph, "https://example.org/std/ModeList")
        assert "config" not in yaml.safe_load(render_seed_docs(reference, "m", None))["seeds"][0]

    def test_diff_reports_added_removed_and_changed_codes(self, graph):
        reference = collect_reference_list(graph, "https://example.org/std/ModeList")
        current = (
            "code_list,code,name,iri\n"
            "ModeList,1,Sea,https://example.org/std/ModeList-1\n"
            "ModeList,9,Gone,https://example.org/std/ModeList-9\n"
        )
        diff = diff_seed(current, reference)
        assert diff.added == (("ModeList", "02"), ("ModeList", "4"))
        assert diff.removed == (("ModeList", "9"),)
        assert diff.changed == (("ModeList", "1"),)

    def test_default_seed_name_is_the_snake_cased_local_name(self):
        assert default_seed_name("https://vocabulary.uncefact.org/TransportModeCodeList") == (
            "transport_mode_code_list"
        )


@pytest.fixture
def hub(tmp_path, monkeypatch) -> Path:
    (tmp_path / "model" / "ontologies").mkdir(parents=True)
    (tmp_path / "model" / "ontologies" / "reference-data.ttl").write_text(_TTL, encoding="utf-8")
    (tmp_path / "kairos.yaml").write_text("adapter: fabric-warehouse\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _export(*args: str):
    return CliRunner().invoke(
        cli, ["export-reference-list", *args, "--domain", "reference-data"], catch_exceptions=False
    )


_SEEDS = Path("integration") / "transforms" / "dbt" / "seeds"


class TestCli:
    def test_writes_the_seed_and_typed_docs(self, hub):
        result = _export("std:ModeList")
        assert result.exit_code == 0, result.output
        csv_text = (hub / _SEEDS / "mode_list.csv").read_text(encoding="utf-8")
        assert (
            csv_text.splitlines()[1]
            == "ModeList,02,Rail transport,https://example.org/std/ModeList-02,"
            "2026-10-17,https://example.org/std/,false"
        )
        docs = yaml.safe_load((hub / _SEEDS / "mode_list.yml").read_text(encoding="utf-8"))
        assert docs["seeds"][0]["config"]["column_types"]["code"] == "VARCHAR(16)"
        assert "Skipped 1 member" in result.output

    def test_the_adapter_option_picks_its_text_type(self, hub):
        assert _export("std:ModeList", "--adapter", "databricks").exit_code == 0
        docs = yaml.safe_load((hub / _SEEDS / "mode_list.yml").read_text(encoding="utf-8"))
        assert set(docs["seeds"][0]["config"]["column_types"].values()) == {"STRING"}

    def test_check_passes_when_current_and_fails_on_drift(self, hub):
        assert _export("std:ModeList").exit_code == 0
        assert _export("std:ModeList", "--check").exit_code == 0
        path = hub / _SEEDS / "mode_list.csv"
        path.write_text(
            path.read_text(encoding="utf-8").replace("Rail transport", "Rail"), encoding="utf-8"
        )
        result = _export("std:ModeList", "--check")
        assert result.exit_code == 1
        assert "1 changed: ModeList:02" in result.output

    def test_check_without_a_seed_fails(self, hub):
        result = _export("std:ModeList", "--check")
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_a_hand_authored_seed_is_never_replaced_without_force(self, hub):
        seeds = hub / _SEEDS
        seeds.mkdir(parents=True)
        (seeds / "mode_list.csv").write_text("code\nX\n", encoding="utf-8")
        (seeds / "mode_list.yml").write_text("version: 2\nseeds: []\n", encoding="utf-8")
        result = _export("std:ModeList")
        assert result.exit_code != 0
        assert "not generated by this command" in result.output
        assert (seeds / "mode_list.csv").read_text(encoding="utf-8") == "code\nX\n"
        assert _export("std:ModeList", "--force").exit_code == 0
        assert (seeds / "mode_list.csv").read_text(encoding="utf-8").startswith("code_list,")

    def test_a_list_without_members_is_refused(self, hub):
        result = _export("std:Location")
        assert result.exit_code != 0
        assert "kind 2" in result.output
        assert not (hub / _SEEDS).exists()

    def test_the_seed_name_can_be_chosen(self, hub):
        assert _export("ref:TransportModeCode", "--name", "transport_mode").exit_code == 0
        assert (hub / _SEEDS / "transport_mode.csv").is_file()

    def test_an_unknown_prefix_is_a_usage_error(self, hub):
        result = _export("nope:ModeList")
        assert result.exit_code == 2
        assert "prefix:Local" in result.output


class TestAll:
    """`--all` re-derives every generated seed from the origin its docs record (#1126)."""

    def test_the_header_records_class_and_domain(self, hub):
        assert _export("std:ModeList").exit_code == 0
        text = (hub / _SEEDS / "mode_list.yml").read_text(encoding="utf-8")
        assert read_origin(text) == {
            "class": "https://example.org/std/ModeList",
            "domain": "reference-data",
        }

    def test_check_all_passes_when_every_seed_is_current(self, hub):
        assert _export("std:ModeList").exit_code == 0
        assert _export("ref:TransportModeCode", "--name", "transport_mode").exit_code == 0
        result = _all("--check")
        assert result.exit_code == 0, result.output
        assert result.output.count("matches the closure") == 2

    def test_check_all_fails_on_a_stale_seed_and_says_how_to_fix_it(self, hub):
        assert _export("std:ModeList").exit_code == 0
        path = hub / _SEEDS / "mode_list.csv"
        path.write_text(path.read_text(encoding="utf-8").replace(",1,", ",9,"), encoding="utf-8")
        result = _all("--check")
        assert result.exit_code == 1
        assert "is stale" in result.output
        assert "export-reference-list --all" in result.output

    def test_all_regenerates_a_stale_seed(self, hub):
        assert _export("std:ModeList").exit_code == 0
        path = hub / _SEEDS / "mode_list.csv"
        original = path.read_text(encoding="utf-8")
        path.write_text("code_list,code,name,iri\n", encoding="utf-8")
        assert _all().exit_code == 0
        assert path.read_text(encoding="utf-8") == original

    def test_hand_authored_seeds_are_ignored(self, hub):
        seeds = hub / _SEEDS
        seeds.mkdir(parents=True)
        (seeds / "country_codes.csv").write_text("code\nBE\n", encoding="utf-8")
        (seeds / "country_codes.yml").write_text("version: 2\nseeds: []\n", encoding="utf-8")
        result = _all("--check")
        assert result.exit_code == 0
        assert "nothing to do" in result.output

    def test_a_generated_seed_without_an_origin_fails(self, hub):
        seeds = hub / _SEEDS
        seeds.mkdir(parents=True)
        (seeds / "old.csv").write_text("code_list,code,name,iri\n", encoding="utf-8")
        (seeds / "old.yml").write_text(f"{GENERATED_MARKER}\nversion: 2\n", encoding="utf-8")
        result = _all("--check")
        assert result.exit_code == 1
        assert "records no class and domain" in result.output

    def test_all_refuses_a_class_argument(self, hub):
        result = CliRunner().invoke(cli, ["export-reference-list", "std:ModeList", "--all"])
        assert result.exit_code == 2
        assert "--all takes each seed's class" in result.output

    def test_no_class_and_no_all_is_a_usage_error(self, hub):
        result = CliRunner().invoke(cli, ["export-reference-list", "--domain", "reference-data"])
        assert result.exit_code == 2
        assert "CLASS_IRI, or --all" in result.output


def _all(*args: str):
    return CliRunner().invoke(
        cli, ["export-reference-list", "--all", *args], catch_exceptions=False
    )


_CURRENCY_TTL = """\
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix iso: <https://example.org/iso4217#> .

<https://example.org/iso4217> a owl:Ontology .

iso:CurrencyCode a owl:Class ;
    owl:versionInfo "2026-09-17" ;
    dcterms:source <https://example.org/list-three.xml>, <https://example.org/list-one.xml> .
iso:numericCode a owl:DatatypeProperty ; rdfs:label "numeric code" .
iso:minorUnit a owl:DatatypeProperty ; rdfs:label "minor unit" .
iso:withdrawalDate a owl:DatatypeProperty ; rdfs:label "withdrawal date" .
iso:entity a owl:DatatypeProperty .
iso:note a owl:AnnotationProperty .

iso:EUR a owl:NamedIndividual, iso:CurrencyCode ;
    rdf:value "EUR" ; rdfs:label "Euro" ;
    iso:numericCode "978" ; iso:minorUnit 2 ;
    iso:entity "BELGIUM", "AUSTRIA" ;
    iso:note "an annotation, not a fact column" ;
    skos:altLabel "euro" .
iso:XAU a owl:NamedIndividual, iso:CurrencyCode ;
    rdf:value "XAU" ; rdfs:label "Gold" ; iso:numericCode "959" .
iso:ISJ a owl:NamedIndividual, iso:CurrencyCode ;
    rdf:value "ISJ" ; rdfs:label "Old Krona" ;
    iso:numericCode "352" ; iso:withdrawalDate "1989 to 1990" ;
    owl:deprecated "true"^^xsd:boolean .
"""

_ISO = "https://example.org/iso4217#CurrencyCode"


@pytest.fixture
def currency() -> Graph:
    return Graph().parse(data=_CURRENCY_TTL, format="turtle")


def _rows(reference) -> dict[str, dict[str, str]]:
    return {row["code"]: row for row in csv.DictReader(io.StringIO(render_seed_csv(reference)))}


class TestMemberFacts:
    """A row carries every fact the reference models state about its code (DD-258, #1137)."""

    def test_each_datatype_property_is_a_column_after_the_fixed_ones(self, currency):
        reference = collect_reference_list(currency, _ISO)
        assert reference.columns == (
            "code_list",
            "code",
            "name",
            "iri",
            "list_version",
            "list_source",
            "deprecated",
            "entity",
            "minor_unit",
            "numeric_code",
            "withdrawal_date",
        )

    def test_rows_carry_the_facts_and_leave_a_missing_fact_empty(self, currency):
        rows = _rows(collect_reference_list(currency, _ISO))
        assert rows["EUR"]["numeric_code"] == "978"
        assert rows["EUR"]["minor_unit"] == "2"
        assert rows["EUR"]["withdrawal_date"] == ""
        assert rows["XAU"]["minor_unit"] == ""

    def test_several_values_share_a_cell_sorted(self, currency):
        rows = _rows(collect_reference_list(currency, _ISO))
        assert rows["EUR"]["entity"] == "AUSTRIA | BELGIUM"

    def test_annotations_and_labels_are_not_fact_columns(self, currency):
        columns = collect_reference_list(currency, _ISO).columns
        assert "note" not in columns
        assert "alt_label" not in columns

    def test_a_withdrawn_code_stays_a_row_marked_deprecated(self, currency):
        rows = _rows(collect_reference_list(currency, _ISO))
        assert rows["ISJ"]["deprecated"] == "true"
        assert rows["ISJ"]["withdrawal_date"] == "1989 to 1990"
        assert rows["EUR"]["deprecated"] == "false"

    def test_every_row_carries_its_lists_version_and_every_source(self, currency):
        row = _rows(collect_reference_list(currency, _ISO))["EUR"]
        assert row["list_version"] == "2026-09-17"
        assert row["list_source"] == (
            "https://example.org/list-one.xml | https://example.org/list-three.xml"
        )

    def test_a_list_without_version_or_source_leaves_the_cells_empty(self, graph):
        reference = collect_reference_list(
            graph, "https://example.com/ont/reference-data#TransportModeCode"
        )
        legacy = _rows(reference)["A"]
        assert (legacy["list_version"], legacy["list_source"]) == ("", "")

    def test_two_properties_with_one_local_name_are_refused(self, currency):
        currency.parse(
            data="@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<https://example.org/other#numericCode> a owl:DatatypeProperty .\n"
            '<https://example.org/iso4217#EUR> <https://example.org/other#numericCode> "1" .',
            format="turtle",
        )
        with pytest.raises(ReferenceListError, match="share one seed column"):
            collect_reference_list(currency, _ISO)

    def test_a_property_named_like_a_fixed_column_is_refused(self, currency):
        currency.parse(
            data="@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<https://example.org/iso4217#listVersion> a owl:DatatypeProperty .\n"
            '<https://example.org/iso4217#EUR> <https://example.org/iso4217#listVersion> "x" .',
            format="turtle",
        )
        with pytest.raises(ReferenceListError, match="a fixed column"):
            collect_reference_list(currency, _ISO)

    def test_docs_describe_every_column(self, currency):
        reference = collect_reference_list(currency, _ISO)
        seed = yaml.safe_load(render_seed_docs(reference, "currency_code", None))["seeds"][0]
        described = {column["name"]: column["description"] for column in seed["columns"]}
        assert tuple(described) == reference.columns
        assert described["numeric_code"].startswith("numeric code (https://example.org/")
        assert "owl:deprecated" in described["deprecated"]

    def test_a_changed_fact_is_a_changed_code(self, currency):
        reference = collect_reference_list(currency, _ISO)
        current = render_seed_csv(reference).replace(",978,", ",999,")
        assert diff_seed(current, reference).changed == (("CurrencyCode", "EUR"),)

    def test_a_seed_from_before_the_fact_columns_reads_as_changed(self, currency):
        reference = collect_reference_list(currency, _ISO)
        old = "code_list,code,name,iri\n" + "".join(
            f"{m.code_list},{m.code},{m.name},{m.iri}\n" for m in reference.members
        )
        diff = diff_seed(old, reference)
        assert (diff.added, diff.removed) == ((), ())
        assert len(diff.changed) == 3


class TestCliFacts:
    def test_check_flags_a_seed_from_before_the_fact_columns(self, hub):
        assert _export("std:ModeList").exit_code == 0
        path = hub / _SEEDS / "mode_list.csv"
        rows = path.read_text(encoding="utf-8").splitlines()
        path.write_text(
            "\n".join(",".join(row.split(",")[:4]) for row in rows) + "\n", encoding="utf-8"
        )
        result = _export("std:ModeList", "--check")
        assert result.exit_code == 1
        assert "3 changed" in result.output

    def test_writing_reports_deprecated_codes_and_the_fact_columns(self, tmp_path, monkeypatch):
        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        (tmp_path / "model" / "ontologies" / "reference-data.ttl").write_text(
            _CURRENCY_TTL, encoding="utf-8"
        )
        (tmp_path / "kairos.yaml").write_text("adapter: fabric-warehouse\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        result = _export("iso:CurrencyCode")
        assert result.exit_code == 0, result.output
        assert "1 deprecated (withdrawn) code(s)" in result.output
        assert "numeric_code" in result.output
