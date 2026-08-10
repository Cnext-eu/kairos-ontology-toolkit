# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for ``kairos-ontology scaffold-system``.

Fixture pattern follows ``tests/test_scaffold_binding.py``: a tiny synthetic accelerator module
(two classes, so two different tables can align to two different target classes), a tiny Bronze
vocabulary TTL with three tables, and a hand-authored ``party-alignment.yaml`` under
``integration/sources/_analysis/`` in the exact on-disk shape
``propose_alignment.alignment_to_dict`` writes -- no real LLM call, no real propose-alignment
run. One table (``organisations``) has alignment evidence pointing at ``TradeParty``, a second
(``contacts``) has alignment evidence pointing at ``Contact``, and a third (``audit_log``) has no
alignment evidence at all.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.scaffold_system import (
    _decline_if_not_mechanical,
    _resolve_target_class,
    run_scaffold_system,
)

_ACCELERATOR_ONTOLOGY_IRI = "https://accelerator.test/party"
_ACCELERATOR_NAMESPACE = "https://accelerator.test/party#"
_TRADE_PARTY_IRI = f"{_ACCELERATOR_NAMESPACE}TradeParty"
_CONTACT_IRI = f"{_ACCELERATOR_NAMESPACE}Contact"

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

    acc:Contact a owl:Class ; rdfs:label "Contact" .
    acc:contactId a owl:DatatypeProperty ;
      rdfs:domain acc:Contact ; rdfs:range xsd:string .
    acc:contactName a owl:DatatypeProperty ;
      rdfs:domain acc:Contact ; rdfs:range xsd:string .
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

    src:contacts a kb:SourceTable ; kb:sourceSystem src:crm ;
      kb:tableName "contacts" ; kb:primaryKeyColumns "contact_id" .
    src:cid a kb:SourceColumn ; kb:sourceTable src:contacts ;
      kb:columnName "contact_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean ; kb:distinctCount "300"^^xsd:integer .
    src:cname a kb:SourceColumn ; kb:sourceTable src:contacts ;
      kb:columnName "contact_name" ; kb:dataType "varchar(200)" ;
      kb:nullable "false"^^xsd:boolean .

    src:audit a kb:SourceTable ; kb:sourceSystem src:crm ;
      kb:tableName "audit_log" ; kb:primaryKeyColumns "log_id" .
    src:logid a kb:SourceColumn ; kb:sourceTable src:audit ;
      kb:columnName "log_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean .
    src:msg a kb:SourceColumn ; kb:sourceTable src:audit ;
      kb:columnName "message" ; kb:dataType "varchar(4000)" ;
      kb:nullable "true"^^xsd:boolean .
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


def _alignment_document(**overrides) -> dict:
    doc = {
        "schema_version": 3,
        "algorithm_version": 1,
        "domain": "party",
        "domain_uris": [_ACCELERATOR_ONTOLOGY_IRI],
        "generated_at": "2026-01-01T00:00:00Z",
        "model_used": "test",
        "tables": [
            {
                "system": "crm",
                "table": "organisations",
                "ref_class": "TradeParty",
                "ref_class_confidence": 0.92,
                "columns": [],
                "custom_columns": [],
            },
            {
                "system": "crm",
                "table": "contacts",
                "ref_class": "Contact",
                "ref_class_confidence": 0.88,
                "columns": [],
                "custom_columns": [],
            },
        ],
        "reference_rollup": [],
    }
    doc.update(overrides)
    return doc


def _build_hub(tmp_path: Path, *, alignment_document: dict | None = None) -> tuple[Path, Path]:
    """Build a minimal hub + sibling reference-models checkout + propose-alignment evidence."""
    hub_root = tmp_path / "ontology-hub"
    ref_models_dir = tmp_path / "ontology-reference-models"

    (hub_root / "model" / "ontologies").mkdir(parents=True)
    (hub_root / "integration" / "sources" / "crm").mkdir(parents=True)
    (hub_root / "integration" / "sources" / "_analysis").mkdir(parents=True)
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

    doc = alignment_document if alignment_document is not None else _alignment_document()
    (hub_root / "integration" / "sources" / "_analysis" / "party-alignment.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False), encoding="utf-8"
    )

    return hub_root, ref_models_dir


def _run(hub_root: Path, ref_models_dir: Path, **overrides):
    kwargs = dict(
        hub_root=hub_root,
        system="crm",
        ref_models_dir=ref_models_dir,
        catalog_path=hub_root / "catalog-v001.xml",
        analysis_dir=hub_root / "integration" / "sources" / "_analysis",
    )
    kwargs.update(overrides)
    return run_scaffold_system(**kwargs)


# ---------------------------------------------------------------------------
# Core end-to-end promise: alignment evidence -> scaffolded; no evidence -> declined.
# ---------------------------------------------------------------------------
def test_scaffolds_tables_with_alignment_evidence_declines_others(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)

    result = _run(hub_root, ref_models_dir)

    assert result.dry_run is False
    scaffolded_by_table = {item.table: item for item in result.scaffolded}
    assert set(scaffolded_by_table) == {"organisations", "contacts"}
    assert scaffolded_by_table["organisations"].target_class == _TRADE_PARTY_IRI
    assert scaffolded_by_table["organisations"].domain == "party"
    assert scaffolded_by_table["contacts"].target_class == _CONTACT_IRI
    for item in result.scaffolded:
        assert item.written
        assert item.binding_path.is_file()

    declined_by_table = {item.table: item for item in result.declined}
    assert set(declined_by_table) == {"audit_log"}
    assert declined_by_table["audit_log"].reason == "no-alignment-evidence"
    assert "propose-alignment" in declined_by_table["audit_log"].detail

    # compile --check ran against the one touched domain, cleanly.
    assert result.domains_compiled == ("party",)
    for item in result.scaffolded:
        assert item.compile_diagnostics == ()


def test_cli_end_to_end(tmp_path, monkeypatch):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    monkeypatch.chdir(hub_root)
    # scaffold-system auto-detects ref-models via the standard sibling-directory convention.
    (hub_root.parent / "ontology-reference-models").exists()

    result = CliRunner().invoke(
        cli,
        ["scaffold-system", "--system", "crm", "--ref-models", str(ref_models_dir)],
    )
    assert result.exit_code == 0, result.output
    assert "Scaffolded 2 table(s); declined 1 table(s)." in result.output
    assert "no-alignment-evidence" in result.output

    json_result = CliRunner().invoke(
        cli,
        [
            "scaffold-system",
            "--system",
            "crm",
            "--ref-models",
            str(ref_models_dir),
            "--format",
            "json",
        ],
    )
    # Second invocation: everything scaffoldable is already covered.
    assert json_result.exit_code == 0, json_result.output
    import json as _json

    payload = _json.loads(json_result.output)
    assert payload["scaffolded"] == []
    reasons = {item["table"]: item["reason"] for item in payload["declined"]}
    assert reasons["organisations"] == "already-covered"
    assert reasons["contacts"] == "already-covered"
    assert reasons["audit_log"] == "no-alignment-evidence"


# ---------------------------------------------------------------------------
# --dry-run: nothing written, but the report still reflects what would happen.
# ---------------------------------------------------------------------------
def test_dry_run_writes_nothing(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)

    result = _run(hub_root, ref_models_dir, dry_run=True)

    assert result.dry_run is True
    assert {item.table for item in result.scaffolded} == {"organisations", "contacts"}
    for item in result.scaffolded:
        assert item.written is False
        assert not item.binding_path.exists()
        assert item.compile_diagnostics == ()
    assert result.domains_compiled == ()
    assert any("dry-run" in note for note in result.notes)

    # Nothing on disk changed: no bindings, no ontology stub, no dbt models.
    bindings_dir = hub_root / "integration" / "bindings"
    assert list(bindings_dir.glob("*.binding.yaml")) == []
    assert not (hub_root / "model" / "ontologies" / "party.ttl").exists()
    dbt_dir = hub_root / "integration" / "transforms" / "dbt" / "models" / "intermediate" / "party"
    assert not dbt_dir.exists()

    # A real run afterwards still works normally (dry-run left no partial state behind).
    real_result = _run(hub_root, ref_models_dir)
    assert {item.table for item in real_result.scaffolded} == {"organisations", "contacts"}
    for item in real_result.scaffolded:
        assert item.written


# ---------------------------------------------------------------------------
# Idempotency: running twice reports "already-covered" the second time.
# ---------------------------------------------------------------------------
def test_running_twice_is_safe(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)

    first = _run(hub_root, ref_models_dir)
    assert len(first.scaffolded) == 2

    second = _run(hub_root, ref_models_dir)
    assert second.scaffolded == ()
    reasons = {item.table: item.reason for item in second.declined}
    assert reasons == {
        "organisations": "already-covered",
        "contacts": "already-covered",
        "audit_log": "no-alignment-evidence",
    }
    # No compile ran (nothing was written this time).
    assert second.domains_compiled == ()


# ---------------------------------------------------------------------------
# First-cut "mechanical passthrough candidate" heuristic (unit-level).
# ---------------------------------------------------------------------------
def test_decline_if_not_mechanical_flags_low_confidence():
    document = _alignment_document()
    table_dict = {
        "system": "crm",
        "table": "organisations",
        "ref_class": "TradeParty",
        "ref_class_confidence": 0.2,
    }
    detail = _decline_if_not_mechanical(document, table_dict, "TradeParty")
    assert detail is not None
    assert "confidence" in detail.lower()


def test_decline_if_not_mechanical_flags_shared_ref_class():
    document = _alignment_document(
        tables=[
            {
                "system": "crm",
                "table": "organisations",
                "ref_class": "TradeParty",
                "ref_class_confidence": 0.9,
            },
            {
                "system": "crm",
                "table": "organisations_legacy",
                "ref_class": "TradeParty",
                "ref_class_confidence": 0.9,
            },
        ]
    )
    table_dict = document["tables"][0]
    detail = _decline_if_not_mechanical(document, table_dict, "TradeParty")
    assert detail is not None
    assert "organisations_legacy" in detail
    assert "merged-master" in detail


def test_decline_if_not_mechanical_accepts_clean_single_source_table():
    document = _alignment_document()
    table_dict = document["tables"][0]
    assert _decline_if_not_mechanical(document, table_dict, "TradeParty") is None


def test_multi_source_merge_signal_declines_both_tables(tmp_path):
    doc = _alignment_document(
        tables=[
            {
                "system": "crm",
                "table": "organisations",
                "ref_class": "TradeParty",
                "ref_class_confidence": 0.9,
            },
            {
                "system": "crm",
                "table": "contacts",
                "ref_class": "TradeParty",
                "ref_class_confidence": 0.9,
            },
        ]
    )
    hub_root, ref_models_dir = _build_hub(tmp_path, alignment_document=doc)

    result = _run(hub_root, ref_models_dir)

    assert result.scaffolded == ()
    reasons = {item.table: item.reason for item in result.declined}
    assert reasons["organisations"] == "non-mechanical"
    assert reasons["contacts"] == "non-mechanical"


# ---------------------------------------------------------------------------
# Target-class resolution (unit-level): never invents a guess.
# ---------------------------------------------------------------------------
def test_resolve_target_class_success(tmp_path):
    hub_root, ref_models_dir = _build_hub(tmp_path)
    document = _alignment_document()
    class_uri, domain, detail = _resolve_target_class(
        document, document["tables"][0], catalog_path=hub_root / "catalog-v001.xml"
    )
    assert class_uri == _TRADE_PARTY_IRI
    assert domain == "party"
    assert detail == ""


def test_resolve_target_class_declines_when_ref_class_empty(tmp_path):
    hub_root, _ref_models_dir = _build_hub(tmp_path)
    document = _alignment_document()
    table_dict = {
        "system": "crm",
        "table": "audit_log",
        "ref_class": "",
        "ref_class_status": "unmatched",
    }
    class_uri, domain, detail = _resolve_target_class(
        document, table_dict, catalog_path=hub_root / "catalog-v001.xml"
    )
    assert class_uri is None
    assert domain == "party"
    assert "no confident accelerator class" in detail


def test_resolve_target_class_declines_stale_ref_class(tmp_path):
    hub_root, _ref_models_dir = _build_hub(tmp_path)
    document = _alignment_document()
    table_dict = {
        "system": "crm",
        "table": "organisations",
        "ref_class": "DoesNotExist",
        "ref_class_confidence": 0.9,
    }
    class_uri, domain, detail = _resolve_target_class(
        document, table_dict, catalog_path=hub_root / "catalog-v001.xml"
    )
    assert class_uri is None
    assert "does not resolve to any class" in detail


# ---------------------------------------------------------------------------
# Unknown --system.
# ---------------------------------------------------------------------------
def test_unknown_system_raises(tmp_path):
    from kairos_ontology.core.scaffold_system import ScaffoldSystemError

    hub_root, ref_models_dir = _build_hub(tmp_path)
    with pytest.raises(ScaffoldSystemError):
        _run(hub_root, ref_models_dir, system="does-not-exist")
