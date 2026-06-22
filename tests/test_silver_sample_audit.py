# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the offline silver sample audit."""

import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.silver_sample_audit import (
    load_source_samples,
    run_silver_sample_audit,
)


SOURCE_TTL = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix app: <https://kairos.cnext.eu/source/app#> .

app:app a kairos-bronze:SourceSystem ;
    rdfs:label "App" .

app:Customer a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "Customer" ;
    kairos-bronze:sourceSystem app:app .

app:Customer_Name a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "Name" ;
    kairos-bronze:dataType "varchar(100)" ;
    kairos-bronze:sampleValues "Acme | Globex" ;
    kairos-bronze:sourceTable app:Customer .

app:Customer_Amount a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "Amount" ;
    kairos-bronze:dataType "varchar(20)" ;
    kairos-bronze:sampleValues "12.5 | invalid" ;
    kairos-bronze:sourceTable app:Customer .

app:Customer_Unsampled a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "Unsampled" ;
    kairos-bronze:dataType "varchar(20)" ;
    kairos-bronze:sourceTable app:Customer .
"""

MAPPING_TTL = """\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
@prefix app: <https://kairos.cnext.eu/source/app#> .
@prefix ex: <https://example.com/domain#> .

app:Customer a skos:Concept ;
    skos:exactMatch ex:Customer ;
    kairos-map:mappingType "direct" .

app:Customer_Name skos:exactMatch ex:customerName .

app:Customer_Amount skos:exactMatch ex:amount ;
    kairos-map:transform "CAST(source.Amount AS DECIMAL(18,2))" ;
    kairos-map:sourceColumns "Amount" .

app:Customer_Unsampled skos:exactMatch ex:customerCode .
"""


def _write_fixture(tmp_path):
    sources = tmp_path / "integration" / "sources" / "app"
    mappings = tmp_path / "model" / "mappings"
    dbt = tmp_path / "output" / "medallion" / "dbt" / "models" / "silver"
    sources.mkdir(parents=True)
    mappings.mkdir(parents=True)
    dbt.mkdir(parents=True)
    (sources / "app.vocabulary.ttl").write_text(SOURCE_TTL, encoding="utf-8")
    (mappings / "app-to-domain.ttl").write_text(MAPPING_TTL, encoding="utf-8")
    (dbt / "customer.sql").write_text(
        "select Name as customer_name, Amount as amount from {{ source('app', 'Customer') }}",
        encoding="utf-8",
    )
    return sources.parent, mappings, dbt.parent.parent.parent


def test_load_source_samples_reads_sample_values(tmp_path):
    sources, _, _ = _write_fixture(tmp_path)

    columns = load_source_samples(sources)
    names = {col.name: col for col in columns.values()}

    assert names["Name"].samples == ["Acme", "Globex"]
    assert names["Name"].system == "App"
    assert names["Unsampled"].samples == []


def test_run_silver_sample_audit_reports_warnings(tmp_path):
    sources, mappings, dbt = _write_fixture(tmp_path)
    out = tmp_path / "audit"

    report = run_silver_sample_audit(
        sources_dir=sources,
        mappings_dir=mappings,
        dbt_output_dir=dbt,
        output_dir=out,
    )

    codes = {finding.code for finding in report.findings}
    assert report.mapped_columns == 3
    assert report.sampled_mapped_columns == 2
    assert "missing_mapped_samples" in codes
    assert "cast_sample_incompatibility" in codes
    assert (out / "silver-sample-audit.yaml").is_file()
    assert (out / "silver-sample-audit.md").is_file()

    data = yaml.safe_load((out / "silver-sample-audit.yaml").read_text(encoding="utf-8"))
    assert data["summary"]["mapped_columns"] == 3
    assert data["summary"]["findings"]["warning"] >= 2


def _write_single_mapping_fixture(tmp_path, target: str, sql: str):
    sources = tmp_path / "integration" / "sources" / "app"
    mappings = tmp_path / "model" / "mappings"
    dbt = tmp_path / "output" / "medallion" / "dbt" / "models" / "silver"
    sources.mkdir(parents=True)
    mappings.mkdir(parents=True)
    dbt.mkdir(parents=True)
    (sources / "app.vocabulary.ttl").write_text(
        """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix app: <https://kairos.cnext.eu/source/app#> .

app:app a kairos-bronze:SourceSystem ;
    rdfs:label "App" .

app:Order a kairos-bronze:SourceTable ;
    kairos-bronze:tableName "Order" ;
    kairos-bronze:sourceSystem app:app .

app:Order_OrderNo a kairos-bronze:SourceColumn ;
    kairos-bronze:columnName "OrderNo" ;
    kairos-bronze:dataType "varchar(100)" ;
    kairos-bronze:sampleValues "BKG-1 | BKG-2" ;
    kairos-bronze:sourceTable app:Order .
""",
        encoding="utf-8",
    )
    (mappings / "app-to-domain.ttl").write_text(
        f"""\
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix app: <https://kairos.cnext.eu/source/app#> .
@prefix booking: <https://example.com/domain/booking#> .
@prefix ex: <https://example.com/domain#> .

app:Order_OrderNo skos:closeMatch {target} .
""",
        encoding="utf-8",
    )
    (dbt / "order.sql").write_text(sql, encoding="utf-8")
    return sources.parent, mappings, dbt.parent.parent.parent


def test_audit_accepts_object_property_fk_lineage_comment(tmp_path):
    sources, mappings, dbt = _write_single_mapping_fixture(
        tmp_path,
        "booking:hasTransportPlan",
        (
            "select booking.booking_sk as booking_sk "
            "-- booking:hasTransportPlan\n"
            "from {{ source('app', 'Order') }}"
        ),
    )

    report = run_silver_sample_audit(
        sources_dir=sources,
        mappings_dir=mappings,
        dbt_output_dir=dbt,
    )

    assert not [
        finding for finding in report.findings
        if finding.code == "target_alias_not_found_in_sql"
    ]


def test_audit_warns_when_alias_and_lineage_are_missing(tmp_path):
    sources, mappings, dbt = _write_single_mapping_fixture(
        tmp_path,
        "booking:hasTransportPlan",
        "select booking.booking_sk as booking_sk from {{ source('app', 'Order') }}",
    )

    report = run_silver_sample_audit(
        sources_dir=sources,
        mappings_dir=mappings,
        dbt_output_dir=dbt,
    )

    warning = next(
        finding for finding in report.findings
        if finding.code == "target_alias_not_found_in_sql"
    )
    assert "booking:hasTransportPlan" in warning.evidence["expected_tokens"]
    assert "has_transport_plan" in warning.evidence["expected_tokens"]


def test_audit_alias_matching_uses_identifier_boundaries(tmp_path):
    sources, mappings, dbt = _write_single_mapping_fixture(
        tmp_path,
        "ex:partySk",
        "select counterparty_sk from {{ source('app', 'Order') }}",
    )

    report = run_silver_sample_audit(
        sources_dir=sources,
        mappings_dir=mappings,
        dbt_output_dir=dbt,
    )

    assert any(
        finding.code == "target_alias_not_found_in_sql"
        for finding in report.findings
    )


def test_audit_accepts_full_uri_lineage_comment(tmp_path):
    target_uri = "https://example.com/domain/booking#hasTransportPlan"
    sources, mappings, dbt = _write_single_mapping_fixture(
        tmp_path,
        "<https://example.com/domain/booking#hasTransportPlan>",
        f"select booking_sk -- {target_uri}\nfrom {{ source('app', 'Order') }}",
    )

    report = run_silver_sample_audit(
        sources_dir=sources,
        mappings_dir=mappings,
        dbt_output_dir=dbt,
    )

    assert not [
        finding for finding in report.findings
        if finding.code == "target_alias_not_found_in_sql"
    ]


def test_cli_audit_silver_samples_non_blocking_by_default(tmp_path):
    sources, mappings, dbt = _write_fixture(tmp_path)
    out = tmp_path / "audit"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "audit-silver-samples",
            "--sources", str(sources),
            "--mappings", str(mappings),
            "--dbt-output", str(dbt),
            "--output", str(out),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Audit complete" in result.output
    assert (out / "silver-sample-audit.yaml").is_file()


def test_cli_audit_silver_samples_can_fail_on_warning(tmp_path):
    sources, mappings, dbt = _write_fixture(tmp_path)
    out = tmp_path / "audit"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "audit-silver-samples",
            "--sources", str(sources),
            "--mappings", str(mappings),
            "--dbt-output", str(dbt),
            "--output", str(out),
            "--fail-on", "warning",
        ],
    )

    assert result.exit_code == 1
