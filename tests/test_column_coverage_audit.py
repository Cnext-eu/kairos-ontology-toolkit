# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the column-coverage audit (issue #353)."""

import textwrap

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.column_coverage_audit import (
    _binding_referenced_columns,
    _table_from_relation,
    run_column_coverage_audit,
)
from kairos_ontology.core.compiler.bindings import load_entity_binding


VOCAB_TTL = textwrap.dedent("""
    @prefix src: <https://example.test/source#> .
    @prefix kb: <https://kairos.cnext.eu/bronze#> .
    @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    src:app a kb:SourceSystem ; rdfs:label "app" .

    src:customers a kb:SourceTable ; kb:sourceSystem src:app ;
      kb:tableName "customers" ; kb:rowCount 100 .
    src:customer_id a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "customer_id" ; kb:dataType "varchar(50)" ;
      kb:nullable false ; kb:distinctCount 100 ; kb:sampleValues "C-1 | C-2" .
    src:customer_name a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "customer_name" ; kb:dataType "varchar(200)" ;
      kb:nullable true ; kb:distinctCount 95 ; kb:sampleValues "Acme | Globex" .
    src:internal_note a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "internal_note" ; kb:dataType "varchar(max)" ;
      kb:nullable true ; kb:distinctCount 40 ; kb:sampleValues "note" .
    src:region_code a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "region_code" ; kb:dataType "varchar(10)" ;
      kb:nullable false ; kb:distinctCount 5 ; kb:sampleValues "EMEA" .
    src:parent_customer_id a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "parent_customer_id" ; kb:dataType "varchar(50)" ;
      kb:nullable true ; kb:distinctCount 30 ; kb:sampleValues "C-9" .
    src:check_col a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "check_col" ; kb:dataType "varchar(10)" ;
      kb:nullable false ; kb:distinctCount 3 ; kb:sampleValues "OK" .
    src:source_updated_at a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "source_updated_at" ; kb:dataType "datetime" ;
      kb:nullable false ; kb:distinctCount 99 ; kb:sampleValues "2026-01-01" .
    src:systemcreatetimeutc a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "SystemCreateTimeUtc" ; kb:dataType "datetime" ;
      kb:nullable false ; kb:distinctCount 98 ; kb:sampleValues "2026-01-02" .
    src:real_orphan_col a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "real_orphan_col" ; kb:dataType "varchar(50)" ;
      kb:nullable true ; kb:distinctCount 40 ; kb:sampleValues "orphan-value" .
    src:constant_col a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "constant_col" ; kb:dataType "varchar(10)" ;
      kb:nullable false ; kb:distinctCount 1 ; kb:sampleValues "SAME" .
    src:unobserved_col a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "unobserved_col" ; kb:dataType "varchar(50)" ;
      kb:nullable true .

    src:legacy_table a kb:SourceTable ; kb:sourceSystem src:app ;
      kb:tableName "legacy_table" ; kb:rowCount 10 .
    src:legacy_col_a a kb:SourceColumn ; kb:sourceTable src:legacy_table ;
      kb:columnName "legacy_col_a" ; kb:dataType "varchar(50)" ;
      kb:nullable true ; kb:distinctCount 8 ; kb:sampleValues "x".
    src:legacy_col_b a kb:SourceColumn ; kb:sourceTable src:legacy_table ;
      kb:columnName "legacy_col_b" ; kb:dataType "varchar(50)" ;
      kb:nullable true ; kb:distinctCount 1 ; kb:sampleValues "y".
    """).strip()

BINDING_YAML = textwrap.dedent("""
    apiVersion: kairos.eu/v5
    kind: EntityBinding
    metadata:
      name: app-customer
      domain: party
    source:
      relation: app.customers
    target:
      class: party:Customer
    grain:
      columns: [customer_id, region_code]
    identity:
      strategy: source-natural
      sourceKey: [customer_id]
    load:
      mode: incremental
      scd: 2
      incremental:
        mergeIdentity: [customer_id]
        canonicalHashInputs: [customer_id, customer_name]
        cdcOperation:
          column: operation
          insertValues: [I]
          updateValues: [U]
          deleteValues: [D]
        sourceUpdatedAt: source_updated_at
        businessEffectiveAt: source_updated_at
        ingestedAt: source_updated_at
        totalOrder: [source_updated_at]
        lookback: {value: 1, unit: days}
        delete: soft-delete
        lateArrival: accept
        correction: new-version
        replay: idempotent
        backfill: merge
        schemaEvolution: fail
    fields:
      - property: party:customerId
        expression: customer_id
      - property: party:customerName
        expression: customer_name
    technicalFields:
      - name: internal_note
        expression: internal_note
        type: string
        nullable: true
        purpose: relationship
    relationships:
      - property: party:hasParent
        target: party:Customer
        join: [{ local: parent_customer_id, foreign: customer_id }]
        cardinality: many-to-one
        mode: non-temporal
        missingParent: error
        ambiguousParent: error
    quality:
      - kind: not-null
        columns: [check_col]
    """).strip()


def _write_hub(tmp_path):
    sources_dir = tmp_path / "integration" / "sources" / "app"
    bindings_dir = tmp_path / "integration" / "bindings"
    sources_dir.mkdir(parents=True)
    bindings_dir.mkdir(parents=True)
    (sources_dir / "app.vocabulary.ttl").write_text(VOCAB_TTL, encoding="utf-8")
    (bindings_dir / "app-customer.binding.yaml").write_text(BINDING_YAML, encoding="utf-8")
    return sources_dir.parent, bindings_dir


def test_binding_referenced_columns_covers_every_reference_shape():
    binding = load_entity_binding(BINDING_YAML, path="app-customer.binding.yaml")
    refs = _binding_referenced_columns(binding)

    assert "customer_id" in refs  # fields: + identity.sourceKey + grain + incremental
    assert "customer_name" in refs  # fields: + canonicalHashInputs
    assert "internal_note" in refs  # technicalFields:
    assert "region_code" in refs  # grain.columns
    assert "parent_customer_id" in refs  # relationships[].join[].local
    assert "check_col" in refs  # quality[].columns
    assert "source_updated_at" in refs  # load.incremental (sourceUpdatedAt/businessEffectiveAt/...)
    assert "real_orphan_col" not in refs
    assert "systemcreatetimeutc" not in refs  # never authored anywhere; irrelevant here


def test_table_from_relation_keeps_dotted_suffix():
    assert _table_from_relation("app.customers") == "customers"
    assert _table_from_relation("cargowise.JobShipment.sample") == "JobShipment.sample"


def test_run_column_coverage_audit_flags_real_orphan_and_excludes_noise(tmp_path):
    sources_dir, bindings_dir = _write_hub(tmp_path)

    report = run_column_coverage_audit(sources_dir=sources_dir, bindings_dir=bindings_dir)

    flagged = {f.column for f in report.orphan_columns}
    assert flagged == {"real_orphan_col"}

    finding = next(f for f in report.orphan_columns if f.column == "real_orphan_col")
    assert finding.table == "customers"
    assert finding.distinct_count == 40
    assert finding.row_count == 100
    assert finding.binding_names == ("app-customer",)

    # Referenced-anywhere columns must not be flagged, regardless of cardinality.
    assert "customer_id" not in flagged
    assert "customer_name" not in flagged
    assert "internal_note" not in flagged
    assert "region_code" not in flagged
    assert "parent_customer_id" not in flagged
    assert "check_col" not in flagged
    assert "source_updated_at" not in flagged
    # Audit-named, unreferenced, high-cardinality -- excluded by name, not cardinality.
    assert "systemcreatetimeutc" not in flagged
    # No real signal -- excluded regardless of name.
    assert "constant_col" not in flagged
    assert "unobserved_col" not in flagged


def test_run_column_coverage_audit_reports_fully_unbound_tables(tmp_path):
    sources_dir, bindings_dir = _write_hub(tmp_path)

    report = run_column_coverage_audit(sources_dir=sources_dir, bindings_dir=bindings_dir)

    unbound = {f.table: f.column_count for f in report.unbound_tables}
    assert unbound == {"legacy_table": 2}


def test_run_column_coverage_audit_empty_bindings_dir(tmp_path):
    sources_dir, _ = _write_hub(tmp_path)
    report = run_column_coverage_audit(
        sources_dir=sources_dir, bindings_dir=tmp_path / "no-bindings"
    )
    assert report.orphan_columns == []
    assert report.unbound_tables == []
    assert report.notes


def test_cli_audit_column_coverage_reports_findings(tmp_path):
    sources_dir, bindings_dir = _write_hub(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "audit-column-coverage",
            "--sources",
            str(sources_dir),
            "--bindings",
            str(bindings_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "real_orphan_col" in result.output
    assert "legacy_table" in result.output
    assert "systemcreatetimeutc" not in result.output.lower()


def test_cli_audit_column_coverage_fail_on_any(tmp_path):
    sources_dir, bindings_dir = _write_hub(tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "audit-column-coverage",
            "--sources",
            str(sources_dir),
            "--bindings",
            str(bindings_dir),
            "--fail-on",
            "any",
        ],
    )

    assert result.exit_code == 1
