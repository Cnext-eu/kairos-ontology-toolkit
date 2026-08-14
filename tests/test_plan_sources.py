# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for ``plan-sources`` (issue #286): preview DD-133 §3c conformance before authoring.

Fixture pattern follows ``tests/test_authoring_scaffolds.py``'s hand-built Bronze
vocabulary graphs and ``tests/test_fit_report.py``'s hand-written binding YAML — both
keep the fixture self-contained without driving the full propose-alignment/scaffold
pipeline.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from kairos_ontology.cli.main import cli
from kairos_ontology.core.plan_sources import PlanSourcesError, run_plan_sources

BRONZE = Namespace("https://kairos.cnext.eu/bronze#")


def _write_source_table(
    sources_dir: Path, system: str, table_name: str, columns: list[tuple[str, str]]
) -> None:
    system_dir = sources_dir / system
    system_dir.mkdir(parents=True, exist_ok=True)
    source = Namespace(f"https://example.test/source/{system}#")
    graph = Graph()
    table_uri = source[table_name]
    graph.add((table_uri, RDF.type, BRONZE.SourceTable))
    graph.add((table_uri, BRONZE.tableName, Literal(table_name)))
    for name, data_type in columns:
        column = source[f"{table_name}.{name}"]
        graph.add((column, RDF.type, BRONZE.SourceColumn))
        graph.add((column, BRONZE.sourceTable, table_uri))
        graph.add((column, BRONZE.columnName, Literal(name)))
        graph.add((column, BRONZE.dataType, Literal(data_type)))
    graph.serialize(system_dir / f"{system}.vocabulary.ttl", format="turtle")


def _write_ontology(ontology_path: Path) -> None:
    ontology_path.parent.mkdir(parents=True, exist_ok=True)
    domain = Namespace("https://example.test/party#")
    graph = Graph()
    graph.bind("party", domain)
    graph.add((URIRef("https://example.test/party"), RDF.type, OWL.Ontology))
    graph.add((URIRef("https://example.test/party"), RDFS.label, Literal("Party")))
    graph.add((URIRef("https://example.test/party"), OWL.versionInfo, Literal("1.0.0")))
    graph.add((domain.Party, RDF.type, OWL.Class))
    graph.add((domain.Party, RDFS.label, Literal("Party")))
    graph.add((domain.partyId, RDF.type, OWL.DatatypeProperty))
    graph.add((domain.partyId, RDFS.domain, domain.Party))
    graph.add((domain.partyId, RDFS.range, XSD.string))
    graph.serialize(ontology_path, format="turtle")


_BINDING = textwrap.dedent(
    """
    apiVersion: kairos.eu/v5
    kind: EntityBinding
    metadata:
      name: crm-party
      domain: party
    source:
      relation: crm.customers
    target:
      class: party:Party
    grain:
      columns: [customer_id]
    identity:
      strategy: source-natural
      sourceKey: [customer_id]
    load:
      mode: full-refresh
    fields:
      - property: party:partyId
        expression: customer_id
    """
).strip()


def _hub(tmp_path: Path, *, with_binding: bool = True) -> tuple[Path, Path]:
    hub = tmp_path / "hub"
    ontology_path = hub / "model" / "ontologies" / "party.ttl"
    _write_ontology(ontology_path)
    sources_dir = hub / "integration" / "sources"
    _write_source_table(sources_dir, "crm", "customers", [("customer_id", "string")])
    if with_binding:
        bindings_dir = hub / "integration" / "bindings"
        bindings_dir.mkdir(parents=True)
        (bindings_dir / "crm-party.binding.yaml").write_text(_BINDING, encoding="utf-8")
    return hub, ontology_path


def test_no_existing_bindings_reports_empty(tmp_path):
    hub, ontology_path = _hub(tmp_path, with_binding=False)

    result = run_plan_sources(
        ontology_path,
        "party:Party",
        hub_root=hub,
        bindings_dir=hub / "integration" / "bindings",
        sources_dir=hub / "integration" / "sources",
    )

    assert result.bindings == ()
    assert result.candidate is None


def test_existing_binding_reports_grain_and_identity_type_kinds(tmp_path):
    hub, ontology_path = _hub(tmp_path)

    result = run_plan_sources(
        ontology_path,
        "party:Party",
        hub_root=hub,
        bindings_dir=hub / "integration" / "bindings",
        sources_dir=hub / "integration" / "sources",
    )

    assert len(result.bindings) == 1
    fact = result.bindings[0]
    assert fact.name == "crm-party"
    assert fact.source_ref == "crm.customers"
    assert [col.name for col in fact.grain] == ["customer_id"]
    assert fact.grain[0].kind == "string"
    assert fact.identity[0].kind == "string"


def test_candidate_with_incompatible_key_type_is_flagged(tmp_path):
    hub, ontology_path = _hub(tmp_path)
    _write_source_table(
        hub / "integration" / "sources", "erp", "parties", [("party_id", "integer")]
    )

    result = run_plan_sources(
        ontology_path,
        "party:Party",
        hub_root=hub,
        bindings_dir=hub / "integration" / "bindings",
        sources_dir=hub / "integration" / "sources",
        source="erp.parties",
        key_columns=("party_id",),
    )

    assert result.candidate is not None
    assert result.candidate.compatible is False
    assert any("int_merged__<entity>" in note for note in result.candidate.notes)


def test_candidate_with_compatible_key_type_passes(tmp_path):
    hub, ontology_path = _hub(tmp_path)
    _write_source_table(
        hub / "integration" / "sources", "erp", "parties", [("party_id", "string")]
    )

    result = run_plan_sources(
        ontology_path,
        "party:Party",
        hub_root=hub,
        bindings_dir=hub / "integration" / "bindings",
        sources_dir=hub / "integration" / "sources",
        source="erp.parties",
        key_columns=("party_id",),
    )

    assert result.candidate.compatible is True
    assert result.candidate.notes == ()


def test_candidate_without_key_column_lists_columns_only(tmp_path):
    hub, ontology_path = _hub(tmp_path)
    _write_source_table(
        hub / "integration" / "sources", "erp", "parties", [("party_id", "integer")]
    )

    result = run_plan_sources(
        ontology_path,
        "party:Party",
        hub_root=hub,
        bindings_dir=hub / "integration" / "bindings",
        sources_dir=hub / "integration" / "sources",
        source="erp.parties",
    )

    assert result.candidate.compatible is None
    assert len(result.candidate.key_columns) == 1
    assert result.candidate.key_columns[0].name == "party_id"


def test_unresolvable_class_token_raises(tmp_path):
    # An undeclared prefix cannot be expanded to a namespace at all (unlike a declared
    # prefix + made-up local name, which resolves to *some* URI whether or not any
    # class actually uses it — see resolve_token_uri in core/fit_report.py).
    hub, ontology_path = _hub(tmp_path, with_binding=False)

    with pytest.raises(PlanSourcesError):
        run_plan_sources(
            ontology_path,
            "nosuchprefix:Whatever",
            hub_root=hub,
            bindings_dir=hub / "integration" / "bindings",
            sources_dir=hub / "integration" / "sources",
        )


def test_cli_smoke(tmp_path, monkeypatch):
    hub, _ = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli, ["plan-sources", "--class", "party:Party", "--domain", "party"]
    )

    assert result.exit_code == 0, result.output
    assert "crm-party" in result.output
    assert "customer_id" in result.output
