# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the ``fit-report`` core logic (DD-144 follow-on).

fit-report answers, deterministically: of everything an accelerator already models for a
class, which properties does a binding/propose-alignment evidence source already populate,
which are still empty, and which source columns don't map anywhere. These tests cover the
core library function ``run_fit_report`` directly (per the task, the CLI is thin formatting
over this), plus one smoke test of the CLI wiring.

Fixture pattern follows ``tests/test_compiler_accelerator_direct.py`` /
``tests/test_compiler_inherited_props.py``: a synthetic accelerator base class
(``acc:TradeParty``) plus a local subclass (``party:Organisation``) that inherits its
properties, so both direct and inherited universe rows are exercised in one fixture.

The propose-alignment evidence path is fixtured by hand-writing the ``*-alignment.yaml`` shape
``alignment_to_dict``/``write_alignment_output`` produce (``core/propose_alignment.py``),
rather than driving the full LLM-backed pipeline — that keeps the fixture cheap while still
exercising the exact on-disk contract fit-report reads.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.fit_report import FitReportError, run_fit_report

_ONTOLOGY = textwrap.dedent(
    """
    @prefix party: <https://example.test/party#> .
    @prefix acc: <https://example.test/accelerator/party#> .
    @prefix owl: <http://www.w3.org/2002/07/owl#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" ;
      rdfs:label "Party slice" .
    acc:TradeParty a owl:Class ; rdfs:label "Trade Party" .
    acc:tradePartyId a owl:DatatypeProperty ;
      rdfs:domain acc:TradeParty ; rdfs:range xsd:string .
    acc:partyName a owl:DatatypeProperty ;
      rdfs:domain acc:TradeParty ; rdfs:range xsd:string .
    acc:registrationNumber a owl:DatatypeProperty ;
      rdfs:domain acc:TradeParty ; rdfs:range xsd:string .
    party:Organisation a owl:Class ; rdfs:label "Organisation" ;
      rdfs:subClassOf acc:TradeParty .
    party:localFlag a owl:DatatypeProperty ;
      rdfs:domain party:Organisation ; rdfs:range xsd:boolean .
    """
).strip()

_ORGANISATION_URI = "https://example.test/party#Organisation"
_TRADE_PARTY_URI = "https://example.test/accelerator/party#TradeParty"

_BINDING = textwrap.dedent(
    """
    apiVersion: kairos.eu/v5
    kind: EntityBinding
    metadata:
      name: crm-organisation
      domain: party
    source:
      relation: crm.organisations
    target:
      class: party:Organisation
    grain:
      columns: [org_id]
    identity:
      strategy: source-natural
      sourceKey: [org_id]
    load:
      mode: full-refresh
    fields:
      - property: acc:tradePartyId
        expression: org_id
      - property: acc:partyName
        expression: name
    technicalFields:
      - name: load_batch_id
        expression: batch_id
        type: string
        nullable: true
        purpose: identity
    """
).strip()


def _write_ontology(tmp_path: Path) -> Path:
    ontology_path = tmp_path / "party.ttl"
    ontology_path.write_text(_ONTOLOGY, encoding="utf-8")
    return ontology_path


def _write_binding(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.binding.yaml"
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Class-token resolution
# ---------------------------------------------------------------------------


def test_qname_and_full_iri_resolve_to_same_class(tmp_path):
    ontology_path = _write_ontology(tmp_path)

    by_qname = run_fit_report(ontology_path, "party:Organisation")
    by_iri = run_fit_report(ontology_path, _ORGANISATION_URI)

    assert by_qname.class_uri == _ORGANISATION_URI
    assert by_iri.class_uri == _ORGANISATION_URI
    assert by_qname.class_name == "Organisation"


def test_unresolvable_class_token_raises(tmp_path):
    ontology_path = _write_ontology(tmp_path)

    with pytest.raises(FitReportError):
        run_fit_report(ontology_path, "acc:NoSuchClass")

    with pytest.raises(FitReportError):
        run_fit_report(ontology_path, "not-a-qname-or-iri")


# ---------------------------------------------------------------------------
# Binding evidence
# ---------------------------------------------------------------------------


def test_binding_evidence_splits_populated_and_unpopulated(tmp_path):
    ontology_path = _write_ontology(tmp_path)
    binding_path = _write_binding(tmp_path / "bindings", "organisation", _BINDING)

    result = run_fit_report(ontology_path, "party:Organisation", binding_path=binding_path)

    assert result.evidence_kind == "binding"
    assert result.evidence_path == str(binding_path)

    populated_names = {item.name: item.source for item in result.populated}
    assert populated_names == {"tradePartyId": "org_id", "partyName": "name"}

    unpopulated_names = {item.name for item in result.unpopulated}
    assert unpopulated_names == {"registrationNumber", "localFlag"}

    # Origin/inheritance must survive the split: both the accelerator-inherited properties
    # and the class's own direct property remain identifiable.
    origins = {item.name: item.origin for item in (*result.populated, *result.unpopulated)}
    assert origins["tradePartyId"] == "inherited"
    assert origins["partyName"] == "inherited"
    assert origins["registrationNumber"] == "inherited"
    assert origins["localFlag"] == "direct"

    # Technical fields are context, never counted as populated ontology properties (DD-139).
    assert len(result.technical_fields) == 1
    assert result.technical_fields[0].name == "load_batch_id"
    assert result.technical_fields[0].purpose == "identity"
    assert "load_batch_id" not in populated_names
    assert "load_batch_id" not in unpopulated_names


def test_accelerator_direct_binding_with_full_iri_tokens(tmp_path):
    """DD-144: --class may point directly at the accelerator class, no local subclass."""
    ontology_path = _write_ontology(tmp_path)
    binding_text = textwrap.dedent(
        f"""
        apiVersion: kairos.eu/v5
        kind: EntityBinding
        metadata:
          name: crm-trade-party
          domain: party
        source:
          relation: crm.trade_parties
        target:
          class: "{_TRADE_PARTY_URI}"
        grain:
          columns: [trade_party_id]
        identity:
          strategy: source-natural
          sourceKey: [trade_party_id]
        load:
          mode: full-refresh
        fields:
          - property: "{_TRADE_PARTY_URI.rsplit('#', 1)[0]}#tradePartyId"
            expression: trade_party_id
        """
    ).strip()
    binding_path = _write_binding(tmp_path / "bindings", "trade-party", binding_text)

    result = run_fit_report(ontology_path, "acc:TradeParty", binding_path=binding_path)

    assert result.class_uri == _TRADE_PARTY_URI
    assert result.evidence_kind == "binding"
    populated_names = {item.name for item in result.populated}
    assert populated_names == {"tradePartyId"}
    unpopulated_names = {item.name for item in result.unpopulated}
    assert unpopulated_names == {"partyName", "registrationNumber"}


def test_autodetects_single_binding_targeting_class(tmp_path):
    ontology_path = _write_ontology(tmp_path)
    bindings_dir = tmp_path / "bindings"
    _write_binding(bindings_dir, "organisation", _BINDING)

    result = run_fit_report(ontology_path, "party:Organisation", bindings_dir=bindings_dir)

    assert result.evidence_kind == "binding"
    assert result.evidence_path == str(bindings_dir / "organisation.binding.yaml")


def test_ambiguous_autodetect_reports_note_and_no_evidence(tmp_path):
    ontology_path = _write_ontology(tmp_path)
    bindings_dir = tmp_path / "bindings"
    _write_binding(bindings_dir, "organisation-a", _BINDING)
    other_binding = _BINDING.replace("crm-organisation", "crm-organisation-b")
    _write_binding(bindings_dir, "organisation-b", other_binding)

    result = run_fit_report(ontology_path, "party:Organisation", bindings_dir=bindings_dir)

    assert result.evidence_kind == "none"
    assert result.populated == ()
    assert any("bindings target this class" in note for note in result.notes)


# ---------------------------------------------------------------------------
# propose-alignment evidence
# ---------------------------------------------------------------------------


def _write_alignment(analysis_dir: Path) -> Path:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": 3,
        "algorithm_version": 1,
        "domain": "party",
        "domain_uris": [],
        "generated_at": "2026-01-01T00:00:00Z",
        "model_used": "gpt-5.4-mini",
        "source_sha256": "",
        "tables": [
            {
                "system": "crm",
                "table": "organisations",
                "ref_class": "TradeParty",
                "ref_class_confidence": 0.9,
                "columns": [
                    {
                        "column": "org_id",
                        "data_type": "varchar(50)",
                        "ref_class": "TradeParty",
                        "ref_property": "tradePartyId",
                        "alignment": "exact",
                        "confidence": 0.95,
                        "rationale": "matches trade party id",
                    },
                    {
                        "column": "name",
                        "data_type": "varchar(200)",
                        "ref_class": "TradeParty",
                        "ref_property": "partyName",
                        "alignment": "semantic",
                        "confidence": 0.8,
                        "rationale": "matches party name",
                    },
                    {
                        "column": "notes",
                        "data_type": "varchar(500)",
                        "ref_class": "",
                        "ref_property": "",
                        "alignment": "custom",
                        "confidence": 0.0,
                        "rationale": "no reference-model equivalent",
                    },
                ],
                "custom_columns": [
                    {
                        "column": "legacy_flag",
                        "data_type": "bit",
                        "suggested_property": None,
                        "confidence": 0.0,
                        "rationale": "legacy flag, no ontology equivalent",
                        "recommended_disposition": "skip",
                    }
                ],
            }
        ],
        "reference_rollup": [],
    }
    path = analysis_dir / "party-alignment.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_source_alignment_evidence_populated_and_orphans(tmp_path):
    ontology_path = _write_ontology(tmp_path)
    analysis_dir = tmp_path / "_analysis"
    alignment_path = _write_alignment(analysis_dir)

    result = run_fit_report(
        ontology_path,
        "acc:TradeParty",
        source="crm.organisations",
        analysis_dir=analysis_dir,
    )

    assert result.evidence_kind == "source-alignment"
    assert result.evidence_path == str(alignment_path)
    assert result.source_system == "crm"
    assert result.source_table == "organisations"

    populated_names = {item.name: item.source for item in result.populated}
    assert populated_names == {"tradePartyId": "org_id", "partyName": "name"}

    unpopulated_names = {item.name for item in result.unpopulated}
    assert unpopulated_names == {"registrationNumber"}

    orphan_names = {item.column for item in result.orphan_columns}
    assert orphan_names == {"notes", "legacy_flag"}


def test_source_alignment_missing_table_reports_note(tmp_path):
    ontology_path = _write_ontology(tmp_path)
    analysis_dir = tmp_path / "_analysis"
    _write_alignment(analysis_dir)

    result = run_fit_report(
        ontology_path,
        "acc:TradeParty",
        source="crm.unknown_table",
        analysis_dir=analysis_dir,
    )

    assert result.evidence_kind == "none"
    assert result.populated == ()
    assert any("no propose-alignment evidence found" in note for note in result.notes)


# ---------------------------------------------------------------------------
# No evidence source
# ---------------------------------------------------------------------------


def test_no_evidence_source_found(tmp_path):
    ontology_path = _write_ontology(tmp_path)

    result = run_fit_report(ontology_path, "acc:TradeParty")

    assert result.evidence_kind == "none"
    assert result.populated == ()
    assert len(result.unpopulated) == 3
    assert result.notes
    assert "no evidence source found" in result.notes[0]


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------


def test_result_to_dict_is_json_serializable(tmp_path):
    ontology_path = _write_ontology(tmp_path)
    binding_path = _write_binding(tmp_path / "bindings", "organisation", _BINDING)

    result = run_fit_report(ontology_path, "party:Organisation", binding_path=binding_path)
    payload = result.to_dict()
    encoded = json.dumps(payload)
    decoded = json.loads(encoded)

    assert decoded["class_uri"] == _ORGANISATION_URI
    assert decoded["evidence"]["kind"] == "binding"
    assert {item["name"] for item in decoded["populated"]} == {"tradePartyId", "partyName"}
    assert {item["name"] for item in decoded["unpopulated"]} == {
        "registrationNumber",
        "localFlag",
    }
    assert decoded["technical_fields"][0]["purpose"] == "identity"
    assert "advisory" in decoded and "not a completeness check" in decoded["advisory"]


# ---------------------------------------------------------------------------
# CLI wiring smoke tests
# ---------------------------------------------------------------------------


def test_cli_fit_report_json_format(tmp_path):
    ontology_path = _write_ontology(tmp_path)
    binding_path = _write_binding(tmp_path / "bindings", "organisation", _BINDING)

    result = CliRunner().invoke(
        cli,
        [
            "fit-report",
            "--class",
            "party:Organisation",
            "--ontology",
            str(ontology_path),
            "--binding",
            str(binding_path),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["class_uri"] == _ORGANISATION_URI
    assert payload["evidence"]["kind"] == "binding"


def test_cli_fit_report_text_format_mentions_advisory(tmp_path):
    ontology_path = _write_ontology(tmp_path)

    result = CliRunner().invoke(
        cli,
        [
            "fit-report",
            "--class",
            "acc:TradeParty",
            "--ontology",
            str(ontology_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "advisory input to design, not a completeness check" in result.output
    assert "Unpopulated (3)" in result.output


def test_cli_fit_report_requires_ontology_or_domain(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["fit-report", "--class", "acc:TradeParty"])
    assert result.exit_code != 0
