# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the offline silver sample audit."""

import textwrap

import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.silver_sample_audit import (
    load_binding_mappings,
    load_source_samples,
    render_markdown,
    resolve_v5_column_facts,
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
@prefix map: <https://example.com/mapping/audit#> .
@prefix app: <https://kairos.cnext.eu/source/app#> .
@prefix ex: <https://example.com/domain#> .

app:Customer a skos:Concept ;
    skos:exactMatch ex:Customer .

app:Customer_Name skos:exactMatch ex:customerName .

app:Customer_Amount skos:exactMatch ex:amount .

app:Customer_Unsampled skos:exactMatch ex:customerCode .
map:table a kairos-map:TableMapping ;
    kairos-map:sourceTable app:Customer ;
    kairos-map:targetClass ex:Customer ;
    kairos-map:mappingType "direct" ;
    kairos-map:matchType "exactMatch" .
map:name a kairos-map:ColumnMapping ;
    kairos-map:sourceColumn app:Customer_Name ;
    kairos-map:targetProperty ex:customerName ;
    kairos-map:matchType "exactMatch" .
map:amount a kairos-map:ColumnMapping ;
    kairos-map:sourceColumn app:Customer_Amount ;
    kairos-map:targetProperty ex:amount ;
    kairos-map:matchType "exactMatch" .
map:code a kairos-map:ColumnMapping ;
    kairos-map:sourceColumn app:Customer_Unsampled ;
    kairos-map:targetProperty ex:customerCode ;
    kairos-map:matchType "exactMatch" .
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
@prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
@prefix map: <https://example.com/mapping/audit-single#> .
@prefix app: <https://kairos.cnext.eu/source/app#> .
@prefix booking: <https://example.com/domain/booking#> .
@prefix ex: <https://example.com/domain#> .

app:Order_OrderNo skos:closeMatch {target} .
map:order-number a kairos-map:ColumnMapping ;
    kairos-map:sourceColumn app:Order_OrderNo ;
    kairos-map:targetProperty {target} ;
    kairos-map:matchType "closeMatch" .
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
        finding for finding in report.findings if finding.code == "target_alias_not_found_in_sql"
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
        finding for finding in report.findings if finding.code == "target_alias_not_found_in_sql"
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

    assert any(finding.code == "target_alias_not_found_in_sql" for finding in report.findings)


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
        finding for finding in report.findings if finding.code == "target_alias_not_found_in_sql"
    ]


def test_cli_audit_silver_samples_non_blocking_by_default(tmp_path):
    sources, mappings, dbt = _write_fixture(tmp_path)
    out = tmp_path / "audit"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "audit-silver-samples",
            "--sources",
            str(sources),
            "--mappings",
            str(mappings),
            "--dbt-output",
            str(dbt),
            "--output",
            str(out),
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
            "--sources",
            str(sources),
            "--mappings",
            str(mappings),
            "--dbt-output",
            str(dbt),
            "--output",
            str(out),
            "--fail-on",
            "warning",
        ],
    )

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# v5 EntityBinding fixtures (issue #348: audit-silver-samples was structurally
# blind to the v5 authoring surface and reported a false 100% coverage).
# ---------------------------------------------------------------------------


def _write_v5_hub(hub_root, *, with_sample_on_name: bool = False):
    """Write a minimal v5 hub: kairos.yaml + ontology + bronze sources + one binding.

    Mirrors the fixture shape used by ``tests/test_compiler_kernel.py::_hub`` so the audit
    exercises the exact same ``resolve_scope``/``adapt_binding`` path the real compiler uses.
    """
    ontology_dir = hub_root / "model" / "ontologies"
    source_dir = hub_root / "integration" / "sources" / "crm"
    binding_dir = hub_root / "integration" / "bindings"
    ontology_dir.mkdir(parents=True)
    source_dir.mkdir(parents=True)
    binding_dir.mkdir(parents=True)
    (hub_root / "kairos.yaml").write_text("adapter: fabric\n", encoding="utf-8")
    (ontology_dir / "party.ttl").write_text(
        textwrap.dedent("""
            @prefix party: <https://example.test/party#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            <https://example.test/party> a owl:Ontology ; owl:versionInfo "1.0.0" .
            party:Customer a owl:Class ; rdfs:label "Customer" .
            party:customer_id a owl:DatatypeProperty ;
              rdfs:domain party:Customer ; rdfs:range xsd:string .
            party:customerName a owl:DatatypeProperty ;
              rdfs:domain party:Customer ; rdfs:range xsd:string .
            """).strip(),
        encoding="utf-8",
    )
    name_sample = '  kb:sampleValues "Acme | Globex" ;\n' if with_sample_on_name else ""
    (source_dir / "crm.vocabulary.ttl").write_text(
        textwrap.dedent(f"""
            @prefix src: <https://example.test/source#> .
            @prefix kb: <https://kairos.cnext.eu/bronze#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            src:crm a kb:SourceSystem ; rdfs:label "crm" ;
              kb:database "raw" ; kb:schema "dbo" ; kb:connectionType "jdbc" .
            src:customers a kb:SourceTable ; kb:sourceSystem src:crm ;
              kb:tableName "customers" ; kb:primaryKeyColumns "customer_id" .
            src:id a kb:SourceColumn ; kb:sourceTable src:customers ;
              kb:columnName "customer_id" ; kb:dataType "varchar(50)" ;
              kb:nullable "false"^^xsd:boolean ;
              kb:sampleValues "C-1 | C-2" .
            src:name a kb:SourceColumn ; kb:sourceTable src:customers ;
              kb:columnName "customer_name" ; kb:dataType "varchar(200)" ;
            {name_sample}  kb:nullable "true"^^xsd:boolean .
            """).strip(),
        encoding="utf-8",
    )
    (binding_dir / "customer.binding.yaml").write_text(
        textwrap.dedent("""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: crm-customer
              domain: party
            source:
              relation: crm.customers
            target:
              class: party:Customer
            grain:
              columns: [customer_id]
            identity:
              strategy: source-natural
              sourceKey: [customer_id]
            load:
              mode: full-refresh
            fields:
              - property: party:customer_id
                expression: customer_id
              - property: party:customerName
                expression: customer_name
            """).strip(),
        encoding="utf-8",
    )
    return source_dir.parent, ontology_dir, binding_dir


def _add_contracted_v5_binding(hub_root, binding_dir, *, replace_direct: bool) -> None:
    models = hub_root / "integration" / "transforms" / "dbt" / "models" / "intermediate"
    models.mkdir(parents=True)
    (models / "int_customer.sql").write_text(
        "select customer_id, customer_name from {{ source('crm', 'customers') }}\n",
        encoding="utf-8",
    )
    (models / "int_customer.yml").write_text(
        textwrap.dedent("""
            version: 2
            models:
              - name: int_customer
                config:
                  contract:
                    enforced: true
                meta:
                  kairos:
                    target_class: https://example.test/party#Customer
                    virtual_source_iri: https://example.test/virtual/int-customer
                    grain: one row per customer
                    grain_key: [customer_id]
                    supported_adapters: [fabric]
                columns:
                  - {name: customer_id, data_type: string, data_tests: [not_null]}
                  - {name: customer_name, data_type: string}
            """).strip()
        + "\n",
        encoding="utf-8",
    )
    direct_path = binding_dir / "customer.binding.yaml"
    document = yaml.safe_load(direct_path.read_text(encoding="utf-8"))
    document["metadata"]["name"] = "dbt-customer"
    document["source"] = {
        "dbtModel": {
            "name": "int_customer",
            "sqlPath": "integration/transforms/dbt/models/intermediate/int_customer.sql",
            "contractPath": "integration/transforms/dbt/models/intermediate/int_customer.yml",
        }
    }
    output = direct_path if replace_direct else binding_dir / "dbt-customer.binding.yaml"
    output.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_load_binding_mappings_resolves_v5_entity_bindings(tmp_path):
    sources, _, bindings = _write_v5_hub(tmp_path)

    mappings, namespaces, findings = load_binding_mappings(tmp_path, bindings)

    assert findings == []
    assert namespaces == {}
    column_maps = mappings["column_maps"]
    assert len(column_maps) == 2
    targets = {entry["target_uri"] for entries in column_maps.values() for entry in entries}
    assert targets == {
        "https://example.test/party#customer_id",
        "https://example.test/party#customerName",
    }


def test_resolve_v5_column_facts_source_system_none_does_not_filter(tmp_path):
    """``source_system=None`` (the pre-existing ``load_binding_mappings`` caller's mode)
    must resolve every binding regardless of which source system it declares -- guards the
    ``resolve_v5_column_facts`` refactor (added for the field-mapping report) against
    accidentally narrowing ``load_binding_mappings``'s own behavior."""
    sources, ontology_dir, bindings = _write_v5_hub(tmp_path)
    (bindings / "legacy-customer.binding.yaml").write_text(
        textwrap.dedent("""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: legacy-customer
              domain: party
            source:
              relation: legacy.old_customers
            target:
              class: party:Customer
            grain:
              columns: [legacy_id]
            identity:
              strategy: source-natural
              sourceKey: [legacy_id]
            load:
              mode: full-refresh
            fields:
              - property: party:customer_id
                expression: legacy_id
            """).strip(),
        encoding="utf-8",
    )
    legacy_dir = sources / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "legacy.vocabulary.ttl").write_text(
        textwrap.dedent("""
            @prefix src: <https://example.test/source/legacy#> .
            @prefix kb: <https://kairos.cnext.eu/bronze#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            src:legacy a kb:SourceSystem ; rdfs:label "legacy" .
            src:old_customers a kb:SourceTable ; kb:sourceSystem src:legacy ;
              kb:tableName "old_customers" ; kb:primaryKeyColumns "legacy_id" .
            src:id a kb:SourceColumn ; kb:sourceTable src:old_customers ;
              kb:columnName "legacy_id" ; kb:dataType "varchar(50)" ;
              kb:nullable "false"^^xsd:boolean ; kb:sampleValues "L-1" .
            """).strip(),
        encoding="utf-8",
    )

    facts, findings = resolve_v5_column_facts(tmp_path, bindings)

    assert findings == []
    source_uris = {fact.source_column_uri for fact in facts}
    assert any("crm" in uri or uri.endswith("/customer_id") for uri in source_uris)
    assert len(facts) == 3  # crm's customer_id + customerName, legacy's customer_id


def test_load_binding_mappings_is_empty_when_bindings_dir_absent(tmp_path):
    mappings, namespaces, findings = load_binding_mappings(tmp_path, tmp_path / "no-bindings")

    assert mappings == {"table_maps": {}, "column_maps": {}}
    assert namespaces == {}
    assert findings == []


def test_run_silver_sample_audit_reads_v5_bindings(tmp_path):
    sources, _, bindings = _write_v5_hub(tmp_path, with_sample_on_name=True)
    dbt = tmp_path / "dbt-output"
    dbt.mkdir()

    report = run_silver_sample_audit(
        sources_dir=sources,
        mappings_dir=tmp_path / "model" / "mappings",
        dbt_output_dir=dbt,
        bindings_dir=bindings,
        hub_root=tmp_path,
    )

    assert report.mapped_columns == 2
    assert report.sampled_mapped_columns == 2
    assert report.sample_coverage_ratio == 1.0
    assert not [f for f in report.findings if f.severity == "error"]
    assert not [f for f in report.findings if f.code == "no_mapping_surface_found"]


def test_run_silver_sample_audit_flags_v5_column_missing_samples(tmp_path):
    sources, _, bindings = _write_v5_hub(tmp_path, with_sample_on_name=False)
    dbt = tmp_path / "dbt-output"
    dbt.mkdir()

    report = run_silver_sample_audit(
        sources_dir=sources,
        mappings_dir=tmp_path / "model" / "mappings",
        dbt_output_dir=dbt,
        bindings_dir=bindings,
        hub_root=tmp_path,
    )

    assert report.mapped_columns == 2
    assert report.sampled_mapped_columns == 1
    assert report.sample_coverage_ratio == 0.5
    codes = {f.code for f in report.findings}
    assert "missing_mapped_samples" in codes


def test_audit_reports_contracted_virtual_outputs_as_unevaluated_info(tmp_path):
    sources, _, bindings = _write_v5_hub(tmp_path, with_sample_on_name=True)
    _add_contracted_v5_binding(tmp_path, bindings, replace_direct=True)
    dbt = tmp_path / "dbt-output"
    dbt.mkdir()

    report = run_silver_sample_audit(
        sources_dir=sources,
        mappings_dir=tmp_path / "model" / "mappings",
        dbt_output_dir=dbt,
        bindings_dir=bindings,
        hub_root=tmp_path,
    )

    limitations = [
        finding for finding in report.findings if finding.code == "contracted_output_not_evaluated"
    ]
    assert report.mapped_columns == 2
    assert report.sampled_mapped_columns == 0
    assert len(limitations) == 2
    assert not [finding for finding in report.findings if finding.code == "missing_source_column"]
    assert all(finding.severity == "info" for finding in limitations)
    assert all(finding.evidence["source_systems"] == ["crm"] for finding in limitations)
    assert all(finding.evidence["lineage_fully_traceable"] is True for finding in limitations)


def test_audit_preserves_real_missing_physical_column_errors(tmp_path):
    sources, mappings, dbt = _write_fixture(tmp_path)
    mapping_path = mappings / "app-to-domain.ttl"
    mapping_path.write_text(
        mapping_path.read_text(encoding="utf-8")
        + """

app:Customer_Missing skos:exactMatch ex:missingValue .
map:missing a kairos-map:ColumnMapping ;
    kairos-map:sourceColumn app:Customer_Missing ;
    kairos-map:targetProperty ex:missingValue ;
    kairos-map:matchType "exactMatch" .
""",
        encoding="utf-8",
    )

    report = run_silver_sample_audit(
        sources_dir=sources,
        mappings_dir=mappings,
        dbt_output_dir=dbt,
    )

    missing = [finding for finding in report.findings if finding.code == "missing_source_column"]
    assert len(missing) == 1
    assert missing[0].severity == "error"
    assert missing[0].evidence["source_column_uri"].endswith("Customer_Missing")


def test_cli_fail_on_error_accepts_direct_and_contracted_bindings(tmp_path, monkeypatch):
    hub_root = tmp_path / "hub"
    hub_root.mkdir()
    _sources, _ontologies, bindings = _write_v5_hub(hub_root, with_sample_on_name=True)
    _add_contracted_v5_binding(hub_root, bindings, replace_direct=False)
    monkeypatch.chdir(hub_root)

    result = CliRunner().invoke(cli, ["audit-silver-samples", "--fail-on", "error"])

    assert result.exit_code == 0, result.output
    report_path = (
        hub_root.parent
        / "ontology-hub-publish"
        / "reports"
        / "silver-sample-audit"
        / "silver-sample-audit.yaml"
    )
    document = yaml.safe_load(report_path.read_text(encoding="utf-8"))
    assert document["summary"]["mapped_columns"] == 4
    assert document["summary"]["findings"]["error"] == 0
    assert document["summary"]["findings"]["info"] == 2


def test_run_silver_sample_audit_zero_mappings_is_not_reported_as_success(tmp_path):
    sources = tmp_path / "integration" / "sources"
    sources.mkdir(parents=True)
    dbt = tmp_path / "dbt-output"
    dbt.mkdir()

    report = run_silver_sample_audit(
        sources_dir=sources,
        mappings_dir=tmp_path / "model" / "mappings",
        dbt_output_dir=dbt,
        bindings_dir=tmp_path / "integration" / "bindings",
        hub_root=tmp_path,
    )

    assert report.mapped_columns == 0
    assert report.sampled_mapped_columns == 0
    assert report.sample_coverage_ratio is None
    warning_findings = [f for f in report.findings if f.code == "no_mapping_surface_found"]
    assert len(warning_findings) == 1
    assert warning_findings[0].severity == "warning"
    assert "does not exist (v4)" in warning_findings[0].message
    assert "does not exist (v5)" in warning_findings[0].message

    markdown = render_markdown(report)
    assert "N/A" in markdown


def test_cli_audit_silver_samples_reports_v5_bindings(tmp_path, monkeypatch):
    hub_root = tmp_path / "hub"
    hub_root.mkdir()
    _write_v5_hub(hub_root, with_sample_on_name=True)
    monkeypatch.chdir(hub_root)
    runner = CliRunner()

    result = runner.invoke(cli, ["audit-silver-samples"])

    assert result.exit_code == 0, result.output
    assert "✅ Audit complete: 2 mapped column(s), 2 with samples (100% coverage)" in result.output
    assert "(v5)" in result.output


def test_cli_audit_silver_samples_zero_mappings_does_not_print_success(tmp_path, monkeypatch):
    hub_root = tmp_path / "hub"
    (hub_root / "model" / "ontologies").mkdir(parents=True)
    (hub_root / "integration" / "sources").mkdir(parents=True)
    monkeypatch.chdir(hub_root)
    runner = CliRunner()

    result = runner.invoke(cli, ["audit-silver-samples"])

    assert result.exit_code == 0, result.output
    assert "✅" not in result.output
    assert "⚠" in result.output
    assert "nothing was audited" in result.output


def test_run_silver_sample_audit_dedupes_column_mapped_by_both_surfaces(tmp_path):
    """A physical source column mapped by both v4 SKOS mappings and a v5 binding to the same
    target (e.g. mid v4-to-v5 migration) must be counted once, not twice."""
    sources, _, bindings = _write_v5_hub(tmp_path, with_sample_on_name=True)
    mappings_dir = tmp_path / "model" / "mappings"
    mappings_dir.mkdir(parents=True)
    (mappings_dir / "dup.ttl").write_text(
        textwrap.dedent("""
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
            @prefix map: <https://example.com/mapping/dup#> .
            @prefix src: <https://example.test/source#> .

            src:name skos:exactMatch <https://example.test/party#customerName> .
            map:name a kairos-map:ColumnMapping ;
                kairos-map:sourceColumn src:name ;
                kairos-map:targetProperty <https://example.test/party#customerName> ;
                kairos-map:matchType "exactMatch" .
            """).strip(),
        encoding="utf-8",
    )
    dbt = tmp_path / "dbt-output"
    dbt.mkdir()

    report = run_silver_sample_audit(
        sources_dir=sources,
        mappings_dir=mappings_dir,
        dbt_output_dir=dbt,
        bindings_dir=bindings,
        hub_root=tmp_path,
    )

    # customer_id (v5 only) + customerName (v4 AND v5, counted once) == 2, not 3.
    assert report.mapped_columns == 2
    codes = {f.code for f in report.findings}
    assert "duplicate_mapping_across_surfaces" in codes


def test_cli_audit_silver_samples_fail_on_warning_catches_zero_mappings(tmp_path, monkeypatch):
    hub_root = tmp_path / "hub"
    (hub_root / "model" / "ontologies").mkdir(parents=True)
    (hub_root / "integration" / "sources").mkdir(parents=True)
    monkeypatch.chdir(hub_root)
    runner = CliRunner()

    result = runner.invoke(cli, ["audit-silver-samples", "--fail-on", "warning"])

    assert result.exit_code == 1
