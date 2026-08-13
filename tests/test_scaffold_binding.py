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
    detect_column_prefix,
    list_unscaffolded_tables,
    match_columns_to_properties,
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
    # crm.events' only column (event_id) matches no datatype property on acc:TradeParty, so #336
    # now refuses to write the schema-invalid `fields: []` binding this used to emit. The
    # ontology-stub work still runs before that refusal and must still be idempotent.
    with pytest.raises(ScaffoldBindingError, match="no datatype property"):
        _scaffold(hub_root, ref_models_dir, table="events", target_class="acc:TradeParty")
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


def test_out_pointing_at_a_directory_is_a_clean_usage_error(tmp_path, monkeypatch):
    """#346: ``--out`` pointing at an existing directory must not crash with a raw traceback."""
    hub_root, _ref_models_dir = _build_hub(tmp_path)
    monkeypatch.chdir(hub_root)
    out_dir = hub_root / "integration" / "bindings"
    assert out_dir.is_dir()
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
            "--out",
            str(out_dir),
        ],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.output
    assert "--out" in result.output
    assert "existing directory" in result.output


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


# ---------------------------------------------------------------------------
# #346: grain must never resolve to a system audit timestamp.
# ---------------------------------------------------------------------------
def test_propose_grain_prefers_pk_shaped_column_over_audit_timestamp():
    """A ``GB_PK``-shaped unique column beats a low-cardinality ``GB_SystemLastEditTimeUtc``.

    Reproduces the real #346 shape: a small sample where the audit timestamp's distinct_count
    (8) happens to be *lower* than the row count, but the heuristic must not even consider it --
    the PK-shaped column, tied for the table-wide highest distinct_count (100, i.e. one per row),
    is recognised ahead of the plain distinct-count proxy.
    """
    columns = (
        _col("GB_PK", distinct_count=100),
        _col("GB_Code", distinct_count=95),
        _col("GB_BranchName", distinct_count=90),
        _col("GB_SystemLastEditTimeUtc", distinct_count=8),
    )
    grain, note = propose_grain_columns(columns, pk_columns=())
    assert grain == ("GB_PK",)
    assert "GB_PK" in note
    assert "SystemLastEditTimeUtc" not in note


def test_propose_grain_excludes_audit_columns_and_is_honest_about_guessing():
    """No PK-shaped column: audit columns must still never be proposed as grain.

    With no ``XX_PK``-shaped column and no distinct_count evidence on any non-audit column, the
    only remaining candidates are a real (but unprofiled) business column and an audit-shaped
    column. The audit column must be excluded from candidacy, and since nothing left carries
    real evidence, the note must read as an explicit low-confidence guess -- never as a NOTE
    that could be mistaken for a finding.
    """
    columns = (
        _col("GB_Code"),
        _col("GB_SystemLastEditTimeUtc"),
        _col("GB_SystemCreateUser"),
    )
    grain, note = propose_grain_columns(columns, pk_columns=())
    assert grain == ("GB_Code",)
    assert "SystemLastEditTimeUtc" not in note
    assert "SystemCreateUser" not in note
    assert "GUESS" in note


# ---------------------------------------------------------------------------
# Second fixture hub (#336 / #314): the shared `_build_hub` above CANNOT test either fix.
# It declares only datatype properties and only unprefixed snake_case columns, so an
# object-property test or a prefixed-column test built on it passes identically before and
# after. This hub declares:
#   * an owl:ObjectProperty with NO rdfs:range (the patterns/deferred-relationship shape);
#   * a datatype property named <ClassName><Suffix> (the class-name ladder rung);
#   * columns in XX_Name, XX_YY_Name and XX_YY_NKName form.
# ---------------------------------------------------------------------------
_LOG_ONTOLOGY_IRI = "https://accelerator.test/logistics"
_LOG_NAMESPACE = "https://accelerator.test/logistics#"
_SHIPMENT_IRI = f"{_LOG_NAMESPACE}Shipment"

_LOG_ACCELERATOR_TTL = textwrap.dedent(
    """
    @prefix acl: <https://accelerator.test/logistics#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    <https://accelerator.test/logistics> a owl:Ontology ; owl:versionInfo "1.0.0" ;
      rdfs:label "Accelerator logistics module" .

    acl:Shipment a owl:Class ; rdfs:label "Shipment" .

    # Class-name ladder rung: SH_Code -> Code -> ShipmentCode -> shipmentcode.
    acl:shipmentCode a owl:DatatypeProperty ;
      rdfs:domain acl:Shipment ; rdfs:range xsd:string .
    # Single-strip rung: SH_Consignee -> Consignee -> consignee.
    acl:consignee a owl:DatatypeProperty ;
      rdfs:domain acl:Shipment ; rdfs:range xsd:string .
    # patterns/deferred-relationship: an object property with NO rdfs:range at all. Its name
    # collides with SH_CarriedBy on the single-strip rung, so it is exactly the column that
    # would land in fields: without the #314 datatype filter.
    acl:carriedBy a owl:ObjectProperty ;
      rdfs:domain acl:Shipment .
    """
).strip()

_LOG_BRONZE_TTL = textwrap.dedent(
    """
    @prefix src: <https://example.test/logsource#> .
    @prefix kb: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    src:erp a kb:SourceSystem ; rdfs:label "erp" ;
      kb:database "raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .

    src:shp a kb:SourceTable ; kb:sourceSystem src:erp ;
      kb:tableName "ShpHeader" ; kb:primaryKeyColumns "SH_PK" .
    src:shpk a kb:SourceColumn ; kb:sourceTable src:shp ;
      kb:columnName "SH_PK" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean ; kb:distinctCount "100"^^xsd:integer .
    src:shcode a kb:SourceColumn ; kb:sourceTable src:shp ;
      kb:columnName "SH_Code" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean ; kb:distinctCount "500"^^xsd:integer .
    src:shcons a kb:SourceColumn ; kb:sourceTable src:shp ;
      kb:columnName "SH_Consignee" ; kb:dataType "varchar(200)" ;
      kb:nullable "true"^^xsd:boolean .
    src:shcarr a kb:SourceColumn ; kb:sourceTable src:shp ;
      kb:columnName "SH_CarriedBy" ; kb:dataType "varchar(50)" ;
      kb:nullable "true"^^xsd:boolean .
    src:shorgcons a kb:SourceColumn ; kb:sourceTable src:shp ;
      kb:columnName "SH_ORG_Consignee" ; kb:dataType "varchar(50)" ;
      kb:nullable "true"^^xsd:boolean .
    src:shorgnkcons a kb:SourceColumn ; kb:sourceTable src:shp ;
      kb:columnName "SH_ORG_NKConsignee" ; kb:dataType "varchar(50)" ;
      kb:nullable "true"^^xsd:boolean .

    src:audit a kb:SourceTable ; kb:sourceSystem src:erp ;
      kb:tableName "ShpAudit" ; kb:primaryKeyColumns "SA_PK" .
    src:auditpk a kb:SourceColumn ; kb:sourceTable src:audit ;
      kb:columnName "SA_PK" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean ; kb:distinctCount "10"^^xsd:integer .
    src:auditts a kb:SourceColumn ; kb:sourceTable src:audit ;
      kb:columnName "SA_Whenever" ; kb:dataType "datetime" ;
      kb:nullable "true"^^xsd:boolean .
    """
).strip()

_LOG_DATA_DOMAINS_YAML = textwrap.dedent(
    """
    module_profiles:
      - id: logistics
        ontology_iri: https://accelerator.test/logistics
        version_pin: "1.0.0"
        term_namespaces:
          - https://accelerator.test/logistics#
    groups:
      - domains:
          - id: logistics
            imports:
              - profile: logistics
    """
).strip()


def _build_logistics_hub(tmp_path: Path) -> tuple[Path, Path]:
    """Build the #336/#314-capable hub. Returns (hub_root, ref_models_dir)."""
    hub_root = tmp_path / "ontology-hub"
    ref_models_dir = tmp_path / "ontology-reference-models"

    (hub_root / "model" / "ontologies").mkdir(parents=True)
    (hub_root / "integration" / "sources" / "erp").mkdir(parents=True)
    (hub_root / "integration" / "bindings").mkdir(parents=True)
    (hub_root / "kairos.yaml").write_text(
        "version: 5\nname: acmehub\nadapter: fabric\n", encoding="utf-8"
    )

    accelerator_ttl_path = (
        ref_models_dir / "accelerator-packs" / "acme" / "ontologies" / "logistics.ttl"
    )
    accelerator_ttl_path.parent.mkdir(parents=True)
    accelerator_ttl_path.write_text(_LOG_ACCELERATOR_TTL, encoding="utf-8")

    data_domains_path = (
        ref_models_dir / "accelerator-packs" / "acme" / "client-hub-blueprint" / "data-domains.yaml"
    )
    data_domains_path.parent.mkdir(parents=True)
    data_domains_path.write_text(_LOG_DATA_DOMAINS_YAML, encoding="utf-8")

    (hub_root / "catalog-v001.xml").write_text(
        textwrap.dedent(
            f"""
            <?xml version="1.0" encoding="UTF-8"?>
            <catalog xmlns="urn:oasis:names:tc:entity:xmlns:xml:catalog">
              <uri name="{_LOG_ONTOLOGY_IRI}"
                   uri="../ontology-reference-models/accelerator-packs/acme/ontologies/logistics.ttl"/>
            </catalog>
            """
        ).strip(),
        encoding="utf-8",
    )

    (hub_root / "integration" / "sources" / "erp" / "erp.vocabulary.ttl").write_text(
        _LOG_BRONZE_TTL, encoding="utf-8"
    )
    return hub_root, ref_models_dir


def _scaffold_logistics(hub_root: Path, ref_models_dir: Path, **overrides):
    kwargs = dict(
        hub_root=hub_root,
        system="erp",
        table="ShpHeader",
        archetype_id="passthrough",
        target_class=_SHIPMENT_IRI,
        domain="logistics",
        ref_models_dir=ref_models_dir,
        catalog_path=hub_root / "catalog-v001.xml",
    )
    kwargs.update(overrides)
    return run_scaffold_binding(**kwargs)


def test_prefixed_columns_match_via_single_strip_and_class_name_rungs(tmp_path):
    """#336 (c) + (d). FAILS today: the exact-only matcher matches zero of these columns."""
    hub_root, ref_models_dir = _build_logistics_hub(tmp_path)
    result = _scaffold_logistics(hub_root, ref_models_dir)

    assert result.column_prefix == "SH"
    doc = yaml.safe_load(result.binding_text)
    by_property = {f["property"]: f["expression"] for f in doc["fields"]}

    # (c) XX_Suffix resolves to <className>Suffix -- the class-name-aware rung.
    assert by_property[f"{_LOG_NAMESPACE}shipmentCode"] == "SH_Code"
    # The single-strip rung still works on its own.
    assert by_property[f"{_LOG_NAMESPACE}consignee"] == "SH_Consignee"

    # (d) The second prefix layer is NOT stripped: neither XX_YY_Name nor XX_YY_NKName reaches
    # :consignee. Two strips collapse 6 real column pairs inside a single CargoWise table.
    assert "SH_ORG_Consignee" not in by_property.values()
    assert "SH_ORG_NKConsignee" not in by_property.values()
    assert {"SH_ORG_Consignee", "SH_ORG_NKConsignee"} <= set(
        result.orphan_columns + result.technical_field_columns
    )


def test_object_property_is_a_relationship_candidate_not_a_field(tmp_path):
    """#314 (a) + (b). FAILS today: relationship_candidates is always empty (there is no
    property_type filter at all, and the column would not have matched in the first place)."""
    hub_root, ref_models_dir = _build_logistics_hub(tmp_path)
    result = _scaffold_logistics(hub_root, ref_models_dir)

    doc = yaml.safe_load(result.binding_text)
    # (a) The range-less object property never reaches fields:.
    assert f"{_LOG_NAMESPACE}carriedBy" not in {f["property"] for f in doc["fields"]}
    assert "SH_CarriedBy" not in {f["expression"] for f in doc["fields"]}
    assert "SH_CarriedBy" not in result.mapped_columns

    # (b) It IS reported as a relationship candidate, and is not silently discarded: the column
    # survives as a DD-139 relationship technical field so a relationships: entry can join it.
    assert result.relationship_candidates == (("SH_CarriedBy", f"{_LOG_NAMESPACE}carriedBy"),)
    assert result.object_property_count == 1
    assert "SH_CarriedBy" in result.technical_field_columns
    assert "SH_CarriedBy" not in result.orphan_columns
    technical = {tf["name"]: tf for tf in doc["technicalFields"]}
    assert technical["SH_CarriedBy"]["purpose"] == "relationship"
    assert any("relationship candidate" in note for note in result.notes)


def test_prefixed_scaffold_compiles_end_to_end(tmp_path):
    """#336 (e). FAILS today: nothing matches on this hub, so the binding is written with
    `fields: []` and the compiler rejects it (binding.schema, [] should be non-empty)."""
    hub_root, ref_models_dir = _build_logistics_hub(tmp_path)
    result = _scaffold_logistics(hub_root, ref_models_dir)
    assert result.written

    compiled = compile_domain(hub_root, "logistics")
    assert compiled.succeeded, {item.code: item.message for item in compiled.diagnostics.items}


def test_match_rate_is_reported_against_the_class_property_universe(tmp_path):
    """#336 item 4. FAILS today: matched_property_count / datatype_property_count do not exist."""
    hub_root, ref_models_dir = _build_logistics_hub(tmp_path)
    result = _scaffold_logistics(hub_root, ref_models_dir)

    # 2 datatype properties on acl:Shipment, both matched -- across 6 columns. A column-based
    # denominator would report 2 of 6.
    assert (result.matched_property_count, result.datatype_property_count) == (2, 2)
    assert "Matched 2 of 2 datatype properties" in result.binding_text
    assert "detected column prefix: SH_" in result.binding_text


def test_column_prefix_override_reaches_the_second_prefix_layer(tmp_path):
    """FAILS today: the `column_prefix` argument / --column-prefix option does not exist."""
    hub_root, ref_models_dir = _build_logistics_hub(tmp_path)
    result = _scaffold_logistics(hub_root, ref_models_dir, column_prefix="SH_ORG")

    doc = yaml.safe_load(result.binding_text)
    by_property = {f["property"]: f["expression"] for f in doc["fields"]}
    # With the explicit two-segment prefix, SH_ORG_Consignee reaches :consignee -- and SH_Code
    # no longer does, because SH_ is no longer the prefix being stripped.
    assert by_property[f"{_LOG_NAMESPACE}consignee"] == "SH_ORG_Consignee"
    assert f"{_LOG_NAMESPACE}shipmentCode" not in by_property
    # The NK layer is still not reached by any single strip.
    assert "SH_ORG_NKConsignee" not in by_property.values()


def test_zero_match_relation_never_reports_success_over_an_invalid_binding(tmp_path):
    """#336 (f) + item 3. FAILS today: today's code writes `fields: []`, returns written=True,
    and the CLI prints the success banner over a file `compile --check` then rejects.

    The raised ScaffoldBindingError is the type scaffold_system already catches and renders as
    declined("scaffold-failed"), so this also pins the routed-failure path.
    """
    hub_root, ref_models_dir = _build_logistics_hub(tmp_path)
    binding_path = hub_root / "integration" / "bindings" / "erp-ShpAudit-to-logistics.binding.yaml"

    with pytest.raises(ScaffoldBindingError) as excinfo:
        _scaffold_logistics(hub_root, ref_models_dir, table="ShpAudit")
    message = str(excinfo.value)
    assert "no datatype property" in message
    assert "--column-prefix" in message

    # No `*.binding.yaml` was written, so nothing the compiler globs can be invalid...
    assert not binding_path.is_file()
    # ...but the author is not left with an empty directory: a commented, ready-to-uncomment
    # skeleton lands in a sibling `.draft` that the compiler's glob never picks up.
    draft_path = Path(str(binding_path) + ".draft")
    assert draft_path.is_file()
    draft_text = draft_path.read_text(encoding="utf-8")
    assert "#fields:" in draft_text
    assert "#    expression: SA_Whenever" in draft_text
    # The draft is a parseable YAML document, just one without `fields:`.
    draft_doc = yaml.safe_load(draft_text)
    assert "fields" not in draft_doc
    assert draft_doc["source"]["relation"] == "erp.ShpAudit"

    # And the domain still compiles once a real table is scaffolded into it.
    _scaffold_logistics(hub_root, ref_models_dir)
    compiled = compile_domain(hub_root, "logistics")
    assert compiled.succeeded, {item.code: item.message for item in compiled.diagnostics.items}


def test_zero_match_relation_cli_exits_non_zero_without_a_success_banner(tmp_path, monkeypatch):
    """#336 item 3, CLI surface. FAILS today: exit_code is 0 and the output says 'Scaffolded'."""
    hub_root, _ = _build_logistics_hub(tmp_path)
    monkeypatch.chdir(hub_root)
    result = CliRunner().invoke(
        cli,
        [
            "scaffold-binding",
            "--system",
            "erp",
            "--table",
            "ShpAudit",
            "--archetype",
            "passthrough",
            "--target-class",
            _SHIPMENT_IRI,
            "--domain",
            "logistics",
        ],
    )
    assert result.exit_code != 0, result.output
    assert "Scaffolded" not in result.output
    assert "no datatype property" in result.output


# ---------------------------------------------------------------------------
# Candidate ladder / prefix detection: unit level, pinning the rejected strategies out.
# ---------------------------------------------------------------------------
def _universe(*entries):
    return [
        {"property_uri": f"https://x.test/#{name}", "name": name, "property_type": kind}
        for name, kind in entries
    ]


def test_detect_column_prefix_ignores_a_single_incidentally_prefixed_column():
    assert detect_column_prefix((_col("A_one"), _col("A_two"), _col("plain"))) == "A"
    assert detect_column_prefix((_col("A_one"), _col("plain"), _col("other"))) is None
    assert detect_column_prefix((_col("plain"), _col("other"))) is None


def test_detect_column_prefix_is_never_derived_from_a_table_name():
    # GlbCapability's real prefix is G4 and GlbCompany's is GC, but a CamelCase-initials rule
    # maps both tables to GC. Detection reads the columns, so the two cannot collide.
    assert detect_column_prefix((_col("G4_PK"), _col("G4_Code"))) == "G4"
    assert detect_column_prefix((_col("GC_PK"), _col("GC_Code"))) == "GC"


def test_ladder_stops_at_one_strip_depth():
    # JobVoyOrigin: JA_E_DEP / JA_A_DEP / JA_S_DEP are Estimated / Actual / Scheduled departure.
    # A second strip collapses all three onto `dep`, and the collapsed distinction is the
    # semantics -- so no second strip is offered.
    columns = (_col("JA_E_DEP"), _col("JA_A_DEP"), _col("JA_S_DEP"))
    matched = match_columns_to_properties(
        columns, _universe(("dep", "datatype")), target_class_uri="https://x.test/#Voyage"
    )
    assert matched.fields == {}


def test_ladder_does_not_fuzzy_or_token_subset_match():
    # JH_JobLocalReference -> jobReference was a real error of the 62%-precision fuzzy strategy.
    columns = (_col("JH_PK"), _col("JH_JobLocalReference"))
    matched = match_columns_to_properties(
        columns, _universe(("jobReference", "datatype")), target_class_uri="https://x.test/#Job"
    )
    assert matched.fields == {}


def test_annotation_properties_are_in_neither_bucket():
    columns = (_col("XX_PK"), _col("XX_Note"))
    matched = match_columns_to_properties(
        columns, _universe(("note", "annotation")), target_class_uri="https://x.test/#Thing"
    )
    assert matched.fields == {}
    assert matched.relationship_candidates == {}
