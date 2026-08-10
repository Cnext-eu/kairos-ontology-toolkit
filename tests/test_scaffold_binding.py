# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for ``kairos-ontology scaffold-binding``.

Fixture pattern follows ``tests/test_compiler_accelerator_direct.py`` / ``tests/test_fit_report.py``:
a tiny synthetic "accelerator" module (no real reference-model checkout) plus a tiny Bronze
vocabulary TTL, wired together with a hub-local XML catalog and a ``data-domains.yaml`` module
profile -- exactly the shape a real accelerator-backed hub uses, just minimal.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.binding_archetypes import list_binding_archetypes
from kairos_ontology.core.compiler import compile_domain
from kairos_ontology.core.scaffold_binding import (
    ScaffoldBindingError,
    SourceColumn,
    list_unscaffolded_tables,
    propose_grain_columns,
    run_scaffold_binding,
)

_ACCELERATOR_ONTOLOGY_IRI = "https://accelerator.test/party"
_ACCELERATOR_NAMESPACE = "https://accelerator.test/party#"
_TRADE_PARTY_IRI = f"{_ACCELERATOR_NAMESPACE}TradeParty"

_ACCELERATOR_TTL = textwrap.dedent(
    """
    @prefix acc: <https://accelerator.test/party#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    <https://accelerator.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" ;
      rdfs:label "Accelerator party module" .

    acc:TradeParty a owl:Class ; rdfs:label "Trade Party" .
    acc:tradePartyId a owl:DatatypeProperty ;
      rdfs:domain acc:TradeParty ; rdfs:range xsd:string .
    acc:partyName a owl:DatatypeProperty ;
      rdfs:domain acc:TradeParty ; rdfs:range xsd:string .
    acc:registrationNumber a owl:DatatypeProperty ;
      rdfs:domain acc:TradeParty ; rdfs:range xsd:string .
    """
).strip()

_BRONZE_TTL = textwrap.dedent(
    """
    @prefix src: <https://example.test/source#> .
    @prefix kb: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    src:crm a kb:SourceSystem ; rdfs:label "crm" ;
      kb:database "raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .

    src:orgs a kb:SourceTable ; kb:sourceSystem src:crm ;
      kb:tableName "organisations" ; kb:primaryKeyColumns "trade_party_id" .
    src:tpid a kb:SourceColumn ; kb:sourceTable src:orgs ;
      kb:columnName "trade_party_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean ; kb:distinctCount "500"^^xsd:integer .
    src:pname a kb:SourceColumn ; kb:sourceTable src:orgs ;
      kb:columnName "party_name" ; kb:dataType "varchar(200)" ;
      kb:nullable "false"^^xsd:boolean .
    src:regnum a kb:SourceColumn ; kb:sourceTable src:orgs ;
      kb:columnName "registration_number" ; kb:dataType "varchar(50)" ;
      kb:nullable "true"^^xsd:boolean .
    src:parentorg a kb:SourceColumn ; kb:sourceTable src:orgs ;
      kb:columnName "parent_org_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "true"^^xsd:boolean .
    src:notes a kb:SourceColumn ; kb:sourceTable src:orgs ;
      kb:columnName "internal_notes" ; kb:dataType "varchar(4000)" ;
      kb:nullable "true"^^xsd:boolean .

    src:evt a kb:SourceTable ; kb:sourceSystem src:crm ;
      kb:tableName "events" ; kb:primaryKeyColumns "event_id" .
    src:evtid a kb:SourceColumn ; kb:sourceTable src:evt ;
      kb:columnName "event_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean .
    """
).strip()

_DATA_DOMAINS_YAML = textwrap.dedent(
    """
    module_profiles:
      - id: party
        ontology_iri: https://accelerator.test/party
        version_pin: "1.0.0"
        term_namespaces:
          - https://accelerator.test/party#
    groups:
      - domains:
          - id: party
            imports:
              - profile: party
    """
).strip()


def _build_hub(tmp_path: Path) -> tuple[Path, Path]:
    """Build a minimal hub + sibling reference-models checkout. Returns (hub_root, ref_models_dir)."""
    hub_root = tmp_path / "ontology-hub"
    ref_models_dir = tmp_path / "ontology-reference-models"

    (hub_root / "model" / "ontologies").mkdir(parents=True)
    (hub_root / "integration" / "sources" / "crm").mkdir(parents=True)
    (hub_root / "integration" / "bindings").mkdir(parents=True)
    (hub_root / "kairos.yaml").write_text(
        "version: 5\nname: acmehub\nadapter: fabric\n", encoding="utf-8"
    )

    accelerator_ttl_path = (
        ref_models_dir / "accelerator-packs" / "acme" / "ontologies" / "party.ttl"
    )
    accelerator_ttl_path.parent.mkdir(parents=True)
    accelerator_ttl_path.write_text(_ACCELERATOR_TTL, encoding="utf-8")

    data_domains_path = (
        ref_models_dir / "accelerator-packs" / "acme" / "client-hub-blueprint" / "data-domains.yaml"
    )
    data_domains_path.parent.mkdir(parents=True)
    data_domains_path.write_text(_DATA_DOMAINS_YAML, encoding="utf-8")

    catalog_path = hub_root / "catalog-v001.xml"
    catalog_path.write_text(
        textwrap.dedent(
            f"""
            <?xml version="1.0" encoding="UTF-8"?>
            <catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
              <uri name="{_ACCELERATOR_ONTOLOGY_IRI}"
                   uri="../ontology-reference-models/accelerator-packs/acme/ontologies/party.ttl"/>
            </catalog>
            """
        ).strip(),
        encoding="utf-8",
    )

    (hub_root / "integration" / "sources" / "crm" / "crm.vocabulary.ttl").write_text(
        _BRONZE_TTL, encoding="utf-8"
    )

    return hub_root, ref_models_dir


def _scaffold(hub_root: Path, ref_models_dir: Path, **overrides):
    kwargs = dict(
        hub_root=hub_root,
        system="crm",
        table="organisations",
        archetype_id="passthrough",
        target_class=_TRADE_PARTY_IRI,
        domain="party",
        ref_models_dir=ref_models_dir,
        catalog_path=hub_root / "catalog-v001.xml",
    )
    kwargs.update(overrides)
    return run_scaffold_binding(**kwargs)


# ---------------------------------------------------------------------------
# Archetype catalog
# ---------------------------------------------------------------------------
def test_list_archetypes_catalog_has_five_entries():
    archetypes = list_binding_archetypes()
    assert [a.id for a in archetypes] == [
        "event-stream",
        "line-item-child",
        "merged-master",
        "passthrough",
        "single-source-master",
    ]
    assert {a.tier for a in archetypes} == {"passthrough", "canonical"}


def test_list_archetypes_cli_prints_catalog():
    result = CliRunner().invoke(cli, ["scaffold-binding", "--list-archetypes"])
    assert result.exit_code == 0
    for archetype_id in (
        "passthrough",
        "single-source-master",
        "merged-master",
        "event-stream",
        "line-item-child",
    ):
        assert archetype_id in result.output


# ---------------------------------------------------------------------------
# --list-unscaffolded
# ---------------------------------------------------------------------------
def test_list_unscaffolded_tables_reports_unbound_tables(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)

    assert set(list_unscaffolded_tables(hub_root, "crm")) == {"organisations", "events"}

    _scaffold(hub_root, ref_models_dir)

    assert list_unscaffolded_tables(hub_root, "crm") == ("events",)


def test_list_unscaffolded_cli(tmp_path, monkeypatch):
    hub_root, _ = _build_hub(tmp_path)
    monkeypatch.chdir(hub_root)
    result = CliRunner().invoke(cli, ["scaffold-binding", "--list-unscaffolded", "--system", "crm"])
    assert result.exit_code == 0
    assert "organisations" in result.output
    assert "events" in result.output


# ---------------------------------------------------------------------------
# Passthrough: the core end-to-end promise.
# ---------------------------------------------------------------------------
def test_passthrough_compiles_unedited(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)

    result = _scaffold(hub_root, ref_models_dir)

    assert result.written
    assert result.binding_path.is_file()
    assert result.archetype.id == "passthrough"
    assert result.archetype.tier == "passthrough"

    # C2: never mint a decorative local property.
    assert set(result.mapped_columns) == {"trade_party_id", "party_name", "registration_number"}
    assert result.technical_field_columns == ("parent_org_id",)
    assert result.orphan_columns == ("internal_notes",)

    binding_doc = yaml.safe_load(result.binding_text)
    properties = {f["property"] for f in binding_doc["fields"]}
    assert properties == {
        f"{_ACCELERATOR_NAMESPACE}tradePartyId",
        f"{_ACCELERATOR_NAMESPACE}partyName",
        f"{_ACCELERATOR_NAMESPACE}registrationNumber",
    }
    tech_names = {tf["name"] for tf in binding_doc.get("technicalFields", [])}
    assert tech_names == {"parent_org_id"}
    assert binding_doc["technicalFields"][0]["purpose"] == "relationship"

    # Grain/identity are derived (not sentineled) for passthrough.
    assert binding_doc["grain"]["columns"] == ["trade_party_id"]
    assert binding_doc["identity"]["sourceKey"] == ["trade_party_id"]
    assert binding_doc["load"] == {"mode": "full-refresh"}
    assert binding_doc["metadata"]["tier"] == "passthrough"

    # Machine-managed ontology stub: created, zero local classes, imports the accelerator.
    stub = result.ontology_stub
    assert stub is not None
    assert stub.created is True
    assert stub.import_added is True
    ontology_text = stub.path.read_text(encoding="utf-8")
    assert "MACHINE-MANAGED" in ontology_text
    assert _ACCELERATOR_ONTOLOGY_IRI in ontology_text
    assert "owl:Class" not in ontology_text  # zero locally-declared classes

    # dbt staging model.
    assert result.dbt_model_written
    assert result.dbt_model_path == (
        hub_root
        / "integration"
        / "transforms"
        / "dbt"
        / "models"
        / "intermediate"
        / "party"
        / "stg_crm__organisations.sql"
    )
    sql_text = result.dbt_model_path.read_text(encoding="utf-8")
    assert "source('crm', 'organisations')" in sql_text
    assert "trade_party_id" in sql_text

    # The concrete acceptance test: compiles unedited through the REAL compiler.
    compiled = compile_domain(hub_root, "party")
    assert compiled.succeeded, {item.code: item.message for item in compiled.diagnostics.items}


def test_orphan_column_never_gets_decorative_property(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    result = _scaffold(hub_root, ref_models_dir)
    assert "internal_notes" in result.orphan_columns
    doc = yaml.safe_load(result.binding_text)
    field_columns = {f["expression"] for f in doc["fields"]}
    technical_columns = {tf["expression"] for tf in doc.get("technicalFields", [])}
    assert "internal_notes" not in field_columns
    assert "internal_notes" not in technical_columns


def test_refuses_to_overwrite_without_force(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    _scaffold(hub_root, ref_models_dir)
    with pytest.raises(ScaffoldBindingError, match="already exists"):
        _scaffold(hub_root, ref_models_dir)
    # --force succeeds.
    result = _scaffold(hub_root, ref_models_dir, force=True)
    assert result.written


# ---------------------------------------------------------------------------
# Machine-managed ontology stub: existing-file branch.
# ---------------------------------------------------------------------------
def test_stub_left_intact_when_ontology_already_imports_accelerator(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    party_path = hub_root / "model" / "ontologies" / "party.ttl"
    existing_text = textwrap.dedent(
        f"""
        @prefix party: <https://acme.example/ont/party#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        <https://acme.example/ont/party> a owl:Ontology ;
            rdfs:label "Party" ;
            owl:imports <{_ACCELERATOR_ONTOLOGY_IRI}> .

        party:LocalNote a owl:Class ; rdfs:label "Local Note" .
        """
    ).strip()
    party_path.write_text(existing_text, encoding="utf-8")

    result = _scaffold(hub_root, ref_models_dir, target_class="acc:TradeParty")

    stub = result.ontology_stub
    assert stub is None or (stub.created is False and stub.import_added is False)
    assert party_path.read_text(encoding="utf-8") == existing_text
    compiled = compile_domain(hub_root, "party")
    assert compiled.succeeded, {item.code: item.message for item in compiled.diagnostics.items}


def test_stub_appends_missing_import_preserving_existing_content(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    party_path = hub_root / "model" / "ontologies" / "party.ttl"
    existing_text = textwrap.dedent(
        """
        @prefix party: <https://acme.example/ont/party#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

        <https://acme.example/ont/party> a owl:Ontology ;
            rdfs:label "Party" .

        party:LocalNote a owl:Class ; rdfs:label "Local Note" .
        """
    ).strip()
    party_path.write_text(existing_text, encoding="utf-8")

    result = _scaffold(hub_root, ref_models_dir)

    stub = result.ontology_stub
    assert stub is not None
    assert stub.created is False
    assert stub.import_added is True
    new_text = party_path.read_text(encoding="utf-8")
    assert new_text.startswith(existing_text)
    assert _ACCELERATOR_ONTOLOGY_IRI in new_text
    assert "party:LocalNote a owl:Class" in new_text

    # Idempotent: scaffolding a second table into the same domain adds no further import.
    result2 = _scaffold(hub_root, ref_models_dir, table="events", target_class="acc:TradeParty")
    assert result2.ontology_stub is None or result2.ontology_stub.import_added is False
    assert party_path.read_text(encoding="utf-8") == new_text


# ---------------------------------------------------------------------------
# Canonical-tier archetypes: confirmation-gate acceptance test.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "archetype_id,expected_pointer",
    [
        ("single-source-master", "/grain/columns"),
        ("event-stream", "/identity/sourceKey"),
    ],
)
def test_canonical_skeleton_fails_compile_on_sentinel(tmp_path, archetype_id, expected_pointer):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    result = _scaffold(hub_root, ref_models_dir, archetype_id=archetype_id, force=True)
    assert result.archetype.tier == "canonical"

    compiled = compile_domain(hub_root, "party")
    assert not compiled.succeeded
    pointers = {item.location.pointer for item in compiled.diagnostics.items}
    assert expected_pointer in pointers, pointers


def test_line_item_child_skeleton_fails_compile_on_sentinel(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    result = _scaffold(hub_root, ref_models_dir, archetype_id="line-item-child")
    assert result.archetype.tier == "canonical"

    compiled = compile_domain(hub_root, "party")
    assert not compiled.succeeded
    pointers = {item.location.pointer for item in compiled.diagnostics.items}
    assert any(p.startswith("/relationships") for p in pointers), pointers


def test_merged_master_skeleton_fails_compile_on_sentinel_conformance(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    result = _scaffold(hub_root, ref_models_dir, archetype_id="merged-master")
    doc = yaml.safe_load(result.binding_text)
    assert doc["conformance"]["sourcePrecedence"] == -1

    compiled = compile_domain(hub_root, "party")
    assert not compiled.succeeded
    pointers = {item.location.pointer for item in compiled.diagnostics.items}
    assert any(p.startswith("/conformance") for p in pointers) or "/grain/columns" in pointers


def test_line_item_child_scaffolds_worked_relationship_example(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    result = _scaffold(hub_root, ref_models_dir, archetype_id="line-item-child")
    doc = yaml.safe_load(result.binding_text)
    assert "relationships" in doc
    relationship = doc["relationships"][0]
    assert relationship["externalReference"]["domain"] == "<CONFIRM_PARENT_DOMAIN>"
    assert "DD-138" in result.binding_text


def test_event_stream_grain_hint_embeds_detected_columns(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    # Add an event-time-shaped column to the organisations table for this test.
    vocab_path = hub_root / "integration" / "sources" / "crm" / "crm.vocabulary.ttl"
    vocab_path.write_text(
        vocab_path.read_text(encoding="utf-8")
        + "\nsrc:createdat a kb:SourceColumn ; kb:sourceTable src:orgs ;\n"
        '  kb:columnName "created_at" ; kb:dataType "datetime" ;\n'
        '  kb:nullable "false"^^xsd:boolean .\n',
        encoding="utf-8",
    )
    result = _scaffold(hub_root, ref_models_dir, archetype_id="event-stream")
    doc = yaml.safe_load(result.binding_text)
    grain_column = doc["grain"]["columns"][0]
    assert grain_column.startswith("<CONFIRM_GRAIN_COLUMN")
    assert "created_at" in grain_column


def test_scaffold_binding_cli_end_to_end(tmp_path, monkeypatch):
    hub_root, _ref_models_dir = _build_hub(tmp_path)
    monkeypatch.chdir(hub_root)
    result = CliRunner().invoke(
        cli,
        [
            "scaffold-binding",
            "--system",
            "crm",
            "--table",
            "organisations",
            "--archetype",
            "passthrough",
            "--target-class",
            _TRADE_PARTY_IRI,
            "--domain",
            "party",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Scaffolded" in result.output
    binding_path = hub_root / "integration" / "bindings" / "crm-organisations-to-party.binding.yaml"
    assert binding_path.is_file()
    compiled = compile_domain(hub_root, "party")
    assert compiled.succeeded, {item.code: item.message for item in compiled.diagnostics.items}


# ---------------------------------------------------------------------------
# --from-binding promotion path.
# ---------------------------------------------------------------------------
def test_from_binding_seeds_merged_master_fields(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    passthrough = _scaffold(hub_root, ref_models_dir)

    merged = _scaffold(
        hub_root,
        ref_models_dir,
        archetype_id="merged-master",
        from_binding=passthrough.binding_path,
        out_path=hub_root / "integration" / "bindings" / "merged-slice-1.binding.yaml",
    )

    merged_doc = yaml.safe_load(merged.binding_text)
    passthrough_doc = yaml.safe_load(passthrough.binding_text)
    assert merged_doc["fields"] == passthrough_doc["fields"]
    assert merged_doc["target"]["class"] == passthrough_doc["target"]["class"]
    assert merged_doc["grain"]["columns"] != passthrough_doc["grain"]["columns"]
    assert any("seeded from --from-binding" in note for note in merged.notes)


# ---------------------------------------------------------------------------
# Grain proposal fallback chain (unit-level, exact priority order).
# ---------------------------------------------------------------------------
def _col(name, *, nullable=False, distinct_count=None, pk=False):
    return SourceColumn(
        name=name,
        data_type="varchar(50)",
        nullable=nullable,
        samples=(),
        distinct_count=distinct_count,
        is_primary_key=pk,
    )


def test_propose_grain_prefers_highest_distinct_count_among_non_nullable():
    columns = (
        _col("a", distinct_count=10, pk=True),
        _col("b", distinct_count=99),
        _col("c", nullable=True, distinct_count=500),  # nullable: excluded despite higher count
    )
    grain, note = propose_grain_columns(columns, pk_columns=("a",))
    assert grain == ("b",)
    assert "distinct_count" in note


def test_propose_grain_falls_back_to_primary_key_without_distinct_count_evidence():
    columns = (_col("a", pk=True), _col("b"))
    grain, note = propose_grain_columns(columns, pk_columns=("a",))
    assert grain == ("a",)
    assert "primaryKeyColumns" in note


def test_propose_grain_falls_back_to_first_non_nullable_column():
    columns = (_col("a", nullable=True), _col("b"), _col("c"))
    grain, note = propose_grain_columns(columns, pk_columns=())
    assert grain == ("b",)
    assert "non-nullable" in note


def test_propose_grain_falls_back_to_first_column_when_all_nullable():
    columns = (_col("a", nullable=True), _col("b", nullable=True))
    grain, note = propose_grain_columns(columns, pk_columns=())
    assert grain == ("a",)
