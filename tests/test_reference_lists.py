# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A shipped reference list's members become a hub seed (DD-257, #1126 P2)."""

from __future__ import annotations

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
            "code_list,code,name,iri",
            "ModeList,02,Rail transport,https://example.org/std/ModeList-02",
            "ModeList,1,Maritime transport,https://example.org/std/ModeList-1",
            "ModeList,4,Air transport,https://example.org/std/ModeList-4",
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
            == "ModeList,02,Rail transport,https://example.org/std/ModeList-02"
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
