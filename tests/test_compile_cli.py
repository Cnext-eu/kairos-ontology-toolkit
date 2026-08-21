# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI tests for the v5 compile command."""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.compile import _emit_compile_artifacts
from kairos_ontology.cli.main import cli
from kairos_ontology.core.compiler import CompileMode, compile_domain
from kairos_ontology.core.observability import reset_logging

from .test_compiler_kernel import _hub


@pytest.fixture(autouse=True)
def _clean_logging():
    # `cli`'s root group installs handlers and sets `propagate = False` on the
    # `kairos_ontology` logger (see configure_logging()); the normal teardown path
    # only runs on a *successful* invocation (Click's result_callback). A test in
    # this file that hits a `click.exceptions.Exit`/`SystemExit` path (e.g. the
    # discovery-gate failures below) skips that teardown and would otherwise leak
    # `propagate = False` into whichever test runs next in the session, starving
    # its `caplog` of records (see test_cli_exception_boundary.py's identical
    # fixture for the same reason).
    reset_logging()
    yield
    reset_logging()


def _contracted_hub(root):
    hub = _hub(root)
    models = hub / "integration" / "transforms" / "dbt" / "models"
    models.mkdir(parents=True)
    (models / "customer_stage.sql").write_text(
        "select customer_id, customer_name from {{ source('crm', 'customers') }}\n",
        encoding="utf-8",
    )
    (models / "schema.yml").write_text(
        textwrap.dedent("""\
        version: 2
        models:
          - name: customer_stage
            config:
              contract:
                enforced: true
            meta:
              kairos:
                grain: one row per customer
                grain_key: [customer_id]
                target_class: https://example.test/party#Customer
                virtual_source_iri: https://example.test/virtual/customer-stage
                supported_adapters: [fabric]
            columns:
              - {name: customer_id, data_type: string, data_tests: [not_null]}
              - {name: customer_name, data_type: string}
        """),
        encoding="utf-8",
    )
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            "source:\n  relation: crm.customers",
            textwrap.dedent("""\
            source:
              dbtModel:
                name: customer_stage
                sqlPath: integration/transforms/dbt/models/customer_stage.sql
                contractPath: integration/transforms/dbt/models/schema.yml"""),
        ),
        encoding="utf-8",
    )
    return hub


def test_compile_requires_exactly_one_mode(tmp_path):
    hub = _hub(tmp_path)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=hub):
        missing = runner.invoke(cli, ["compile", "party"])
        conflicting = runner.invoke(cli, ["compile", "party", "--check", "--emit"])
    assert missing.exit_code == 2
    assert conflicting.exit_code == 2
    assert "exactly one" in missing.output
    assert "cannot be combined" in conflicting.output


def test_compile_check_and_explain_may_be_combined(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    before = {path.relative_to(hub) for path in hub.rglob("*")}

    combined = CliRunner().invoke(cli, ["compile", "party", "--check", "--explain"])
    after = {path.relative_to(hub) for path in hub.rglob("*")}

    assert combined.exit_code == 0, combined.output
    assert "compile check passed" in combined.output
    assert "entity binding(s)" in combined.output
    assert before == after


def test_compile_check_and_explain_json_includes_both(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli, ["compile", "party", "--check", "--explain", "--format", "json"]
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["mode"] == "check+explain"
    assert payload["diagnostics"] == []
    assert payload["explain"]["entities"][0]["name"] == "crm-customer"


def test_compile_json_payload_includes_operation_id(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "--check", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "operation_id" in payload
    assert isinstance(payload["operation_id"], str)
    assert payload["operation_id"]  # non-empty when CLI is the entry point


def test_compile_explain_and_emit_cannot_be_combined(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "--explain", "--emit"])

    assert result.exit_code == 2
    assert "cannot be combined" in result.output


def test_compile_check_and_json_explain_are_write_free(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    before = {path.relative_to(hub) for path in hub.rglob("*")}
    checked = CliRunner().invoke(cli, ["compile", "party", "--check"])
    explained = CliRunner().invoke(cli, ["compile", "party", "--explain", "--format", "json"])
    after = {path.relative_to(hub) for path in hub.rglob("*")}
    assert checked.exit_code == 0, checked.output
    assert "compile check passed" in checked.output
    assert explained.exit_code == 0, explained.output
    payload = json.loads(explained.stdout)
    assert payload["succeeded"] is True
    assert payload["explain"]["entities"][0]["name"] == "crm-customer"
    assert before == after


def test_dbt_contract_and_dependency_resolution_run_once_per_binding(tmp_path, monkeypatch):
    """DD perf fix: a dbt-sourced binding's contract used to be read up to three times
    and its SQL dependency closure walked up to three times per compile (once in
    resolve_scope, once again in build_compile_plan's main loop, once more for target-
    class validation). Both should now run exactly once."""
    hub = _contracted_hub(tmp_path)
    monkeypatch.chdir(hub)

    from kairos_ontology.core.compiler import dbt_source

    load_contract_calls: list[Path] = []
    dependency_calls: list[Path] = []
    original_load_contract = dbt_source._load_contract
    original_dependency_paths = dbt_source._dependency_sql_paths

    def counting_load_contract(binding, path):
        load_contract_calls.append(path)
        return original_load_contract(binding, path)

    def counting_dependency_paths(binding, hub_root, selected_path):
        dependency_calls.append(selected_path)
        return original_dependency_paths(binding, hub_root, selected_path)

    monkeypatch.setattr(dbt_source, "_load_contract", counting_load_contract)
    monkeypatch.setattr(dbt_source, "_dependency_sql_paths", counting_dependency_paths)

    result = CliRunner().invoke(cli, ["compile", "party", "--check"])

    assert result.exit_code == 0, result.output
    assert "compile check passed" in result.output
    assert len(load_contract_calls) == 1
    assert len(dependency_calls) == 1


def test_no_cache_flag_forces_fresh_ontology_reparse(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    warm = CliRunner().invoke(cli, ["compile", "party", "--emit", "--confirm-emit"])
    assert warm.exit_code == 0, warm.output
    assert (hub / ".cache" / "ontology-parse").is_dir()

    from kairos_ontology.core import ontology_loader

    turtle_parses: list[object] = []
    original_parse = ontology_loader.Graph.parse

    def counting_parse(self, source=None, **kwargs):
        if kwargs.get("format") == "turtle":
            turtle_parses.append(source)
        return original_parse(self, source, **kwargs)

    monkeypatch.setattr(ontology_loader.Graph, "parse", counting_parse)

    result = CliRunner().invoke(cli, ["compile", "party", "--check", "--no-cache"])

    assert result.exit_code == 0, result.output
    assert turtle_parses  # --no-cache bypassed the warm on-disk cache


def test_compile_resolves_nested_hub_from_repository_root(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    hub = _hub(repository / "ontology-hub")
    monkeypatch.chdir(repository)

    result = CliRunner().invoke(cli, ["compile", "party", "--check"])

    assert result.exit_code == 0, result.output
    assert "compile check passed" in result.output
    assert hub.is_dir()


def test_compile_bare_emit_requires_confirm_emit_flag(tmp_path, monkeypatch):
    hub = _hub(tmp_path / "hub")
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit"])
    assert result.exit_code == 2
    assert "--confirm-emit" in result.output
    assert not (hub.parent / "ontology-hub-publish").exists()


def test_compile_emit_with_confirm_emit_succeeds(tmp_path, monkeypatch):
    hub = _hub(tmp_path / "hub")
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit", "--confirm-emit"])
    assert result.exit_code == 0, result.output


def test_emit_reads_contracted_dependencies_only_from_compile_plan(tmp_path):
    hub = _contracted_hub(tmp_path / "hub")
    result = compile_domain(hub, "party", CompileMode.EMIT)
    shutil.rmtree(hub / "integration" / "transforms")

    target = tmp_path / "publish" / "medallion" / "dbt"
    _emit_compile_artifacts(result, target)

    assert (target / "models" / "customer_stage.sql").is_file()
    assert (target / "models" / "schema.yml").is_file()


def test_compile_emit_preflights_unowned_dependency_collision(tmp_path, monkeypatch):
    hub = _contracted_hub(tmp_path / "hub")
    output = hub.parent / "ontology-hub-publish" / "medallion" / "dbt"
    collision = output / "models" / "customer_stage.sql"
    collision.parent.mkdir(parents=True)
    collision.write_text("select 'unowned'\n", encoding="utf-8")
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli,
        ["compile", "party", "--emit", "--confirm-emit"],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code != 0
    assert "collides with an unowned path" in result.output
    assert collision.read_text(encoding="utf-8") == "select 'unowned'\n"
    assert not (output / "models" / "silver" / "party" / "customer.sql").exists()


def test_compile_returns_nonzero_for_diagnostics(tmp_path, monkeypatch):
    hub = _hub(tmp_path, broken_column=True)
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--check"])
    assert result.exit_code == 1
    assert "safety.column-unresolved" in result.output


def test_compile_emit_writes_unified_dbt_project_preserving_unowned_files(tmp_path, monkeypatch):
    hub = _hub(tmp_path / "hub")
    output = hub.parent / "ontology-hub-publish" / "medallion" / "dbt"
    unrelated = output / "invoice" / "user.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep", encoding="utf-8")
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit", "--confirm-emit"])
    assert result.exit_code == 0, result.output
    assert (output / "models/silver/party/customer.sql").is_file()
    assert (output / ".kairos-compile-manifest.party.json").is_file()
    assert (output / ".kairos-compile-manifest.shared.json").is_file()
    assert not (output / "party").exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_compile_emit_rejects_an_explicit_directory_argument(tmp_path, monkeypatch):
    hub = _hub(tmp_path / "hub")
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit", "--confirm-emit", "some/dir"])
    # --emit is a pure flag; the extra token is parsed as a second DOMAIN argument
    # and rejected, so no folder can be created under the hub.
    assert result.exit_code != 0
    assert not (hub / "some").exists()
    assert not (hub / "ontology-hub-publish").exists()


def test_compile_bare_emit_targets_publish_root_without_warning(tmp_path, monkeypatch):
    hub = _hub(tmp_path / "hub")
    monkeypatch.chdir(hub)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit", "--confirm-emit"])
    assert result.exit_code == 0, result.output
    assert "outside this hub" not in result.stderr
    expected = hub.parent / "ontology-hub-publish/medallion/dbt/models/silver/party/customer.sql"
    assert expected.is_file()
    # Never nested inside the hub.
    assert not (hub / "ontology-hub-publish").exists()


def test_compile_emit_from_repo_root_lands_in_sibling_publish_root(tmp_path, monkeypatch):
    repository = tmp_path / "repository"
    hub = _hub(repository / "ontology-hub")
    monkeypatch.chdir(repository)
    result = CliRunner().invoke(cli, ["compile", "party", "--emit", "--confirm-emit"])
    assert result.exit_code == 0, result.output
    expected = repository / "ontology-hub-publish/medallion/dbt/models/silver/party/customer.sql"
    assert expected.is_file()
    assert not (hub / "ontology-hub-publish").exists()


# ---------------------------------------------------------------------------
# Issue #389/#390: `compile <domain>` is inherently single-domain, so an unresolved
# DD-148 judgment tagged to an unrelated domain must no longer block it; one tagged to
# the compiled domain, or left cross-cutting (no likely_domains), still must.
# ---------------------------------------------------------------------------


def test_compile_check_succeeds_when_unresolved_judgment_tagged_to_other_domain(
    tmp_path, monkeypatch
):
    from discovery_fixtures import write_discovery_artifact_with_unresolved_judgment

    hub = _hub(tmp_path)
    write_discovery_artifact_with_unresolved_judgment(hub, likely_domains=["customs"])
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "--check"])

    assert result.exit_code == 0, result.output
    assert "compile check passed" in result.output


def test_compile_check_fails_when_unresolved_judgment_tagged_to_compiled_domain(
    tmp_path, monkeypatch
):
    from discovery_fixtures import write_discovery_artifact_with_unresolved_judgment

    hub = _hub(tmp_path)
    write_discovery_artifact_with_unresolved_judgment(hub, likely_domains=["party"])
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "--check"])

    assert result.exit_code != 0
    assert "Unresolved discovery item" in result.output


def test_compile_check_fails_when_unresolved_judgment_is_cross_cutting(tmp_path, monkeypatch):
    from discovery_fixtures import write_discovery_artifact_with_unresolved_judgment

    hub = _hub(tmp_path)
    write_discovery_artifact_with_unresolved_judgment(hub)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "--check"])

    assert result.exit_code != 0
    assert "Unresolved discovery item" in result.output


def test_compile_blocks_on_non_degradable_integrity_failure(tmp_path, monkeypatch):
    """DD-163: binding-stage compile must refuse a cross-domain redeclaration.

    Binding authoring is where an agent is pushed to silence
    ``binding.unknown-property`` by minting the missing term locally. validate catches
    the result, but a stage later -- the previous run reached a dbt build failure first.
    """
    from kairos_ontology.cli.compile import _domain_integrity_failures

    ontologies = tmp_path / "model" / "ontologies"
    ontologies.mkdir(parents=True)
    for domain in ("party", "booking"):
        (ontologies / f"{domain}.ttl").write_text(
            f"@prefix : <https://example.com/ont/{domain}#> .\n"
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
            f"<https://example.com/ont/{domain}> a owl:Ontology ;\n"
            f'    rdfs:label "{domain}"@en ;\n'
            '    owl:versionInfo "1.0.0" .\n\n'
            ":Booking a owl:Class ;\n"
            '    rdfs:label "Booking"@en ;\n'
            '    rdfs:comment "A booking."@en .\n',
            encoding="utf-8",
        )

    failures = _domain_integrity_failures(tmp_path, "party")
    assert failures, "a class declared in two domains must block this domain's compile"
    assert all(f.code == "integrity.class-redeclared-across-domains" for f in failures)


def test_compile_integrity_guard_is_silent_on_a_clean_hub(tmp_path):
    from kairos_ontology.cli.compile import _domain_integrity_failures

    ontologies = tmp_path / "model" / "ontologies"
    ontologies.mkdir(parents=True)
    (ontologies / "party.ttl").write_text(
        "@prefix : <https://example.com/ont/party#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
        "<https://example.com/ont/party> a owl:Ontology ;\n"
        '    rdfs:label "party"@en ;\n'
        '    owl:versionInfo "1.0.0" .\n\n'
        ":Party a owl:Class ;\n"
        '    rdfs:label "Party"@en ;\n'
        '    rdfs:comment "A party."@en .\n',
        encoding="utf-8",
    )
    assert _domain_integrity_failures(tmp_path, "party") == []


def test_compile_integrity_guard_never_raises_on_a_broken_hub(tmp_path):
    """The guard must not convert an infrastructure problem into a compile failure."""
    from kairos_ontology.cli.compile import _domain_integrity_failures

    assert _domain_integrity_failures(tmp_path / "does-not-exist", "party") == []


def _add_crm_countries_table(hub: Path) -> None:
    source = hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl"
    source.write_text(
        source.read_text(encoding="utf-8")
        + textwrap.dedent("""
            src:countries a kb:SourceTable ; kb:sourceSystem src:crm ;
              kb:tableName "countries" ; kb:primaryKeyColumns "code" .
            src:country_code a kb:SourceColumn ; kb:sourceTable src:countries ;
              kb:columnName "code" ; kb:dataType "varchar(2)" ;
              kb:nullable "false"^^xsd:boolean .
            src:country_label a kb:SourceColumn ; kb:sourceTable src:countries ;
              kb:columnName "country_name" ; kb:dataType "varchar(100)" ;
              kb:nullable "true"^^xsd:boolean .
            """),
        encoding="utf-8",
    )


def _add_billing_domain_on_crm_countries(hub: Path) -> None:
    (hub / "model" / "ontologies" / "billing.ttl").write_text(
        textwrap.dedent("""
            @prefix billing: <https://example.test/billing#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            <https://example.test/billing> a owl:Ontology ; owl:versionInfo "1.0.0" .
            billing:Region a owl:Class ; rdfs:label "Region" .
            billing:code a owl:DatatypeProperty ;
              rdfs:domain billing:Region ; rdfs:range xsd:string .
            billing:region_name a owl:DatatypeProperty ;
              rdfs:domain billing:Region ; rdfs:range xsd:string .
            """).strip(),
        encoding="utf-8",
    )
    (hub / "integration" / "bindings" / "region.binding.yaml").write_text(
        textwrap.dedent("""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: crm-region
              domain: billing
            source:
              relation: crm.countries
            target:
              class: billing:Region
            grain:
              columns: [code]
            identity:
              strategy: source-natural
              sourceKey: [code]
            load:
              mode: full-refresh
            fields:
              - property: billing:code
                expression: code
              - property: billing:region_name
                expression: country_name
            """).strip(),
        encoding="utf-8",
    )


def test_sequential_emits_union_and_preserve_other_domain_source_tables(tmp_path, monkeypatch):
    hub = _hub(tmp_path / "hub")
    _add_crm_countries_table(hub)
    _add_billing_domain_on_crm_countries(hub)
    monkeypatch.chdir(hub)
    runner = CliRunner()
    for domain in ("party", "billing"):
        result = runner.invoke(cli, ["compile", domain, "--emit", "--confirm-emit"])
        assert result.exit_code == 0, result.output
    target = hub.parent / "ontology-hub-publish" / "medallion" / "dbt"
    catalog_path = target / "models" / "silver" / "_crm__sources.yml"
    catalog = catalog_path.read_text(encoding="utf-8")
    assert "customers" in catalog and "countries" in catalog

    reemitted = runner.invoke(cli, ["compile", "party", "--emit", "--confirm-emit"])

    assert reemitted.exit_code == 0, reemitted.output
    catalog = catalog_path.read_text(encoding="utf-8")
    assert "countries" in catalog, "the other domain's tables must survive a re-emit"
    assert "customers" in catalog


def test_emit_fails_closed_on_conflicting_shared_source_metadata(tmp_path, monkeypatch):
    """#584: the shared-catalog union must not let one domain's stale vocabulary win."""
    hub = _hub(tmp_path / "hub")
    _add_crm_countries_table(hub)
    _add_billing_domain_on_crm_countries(hub)
    monkeypatch.chdir(hub)
    runner = CliRunner()
    first = runner.invoke(cli, ["compile", "party", "--emit", "--confirm-emit"])
    assert first.exit_code == 0, first.output
    target = hub.parent / "ontology-hub-publish" / "medallion" / "dbt"
    vocabulary = hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl"
    vocabulary.write_text(
        vocabulary.read_text(encoding="utf-8").replace('kb:database "raw"', 'kb:database "raw2"'),
        encoding="utf-8",
    )
    before = {
        path.relative_to(target).as_posix(): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }

    conflict = runner.invoke(cli, ["compile", "billing", "--emit", "--confirm-emit"])

    assert conflict.exit_code != 0
    assert "conflicting source metadata" in conflict.output
    after = {
        path.relative_to(target).as_posix(): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }
    assert before == after, "a failed emit must leave the target tree untouched"


def _seeded_contracted_hub(root):
    hub = _contracted_hub(root)
    seeds = hub / "integration" / "transforms" / "dbt" / "seeds"
    seeds.mkdir(parents=True)
    (seeds / "country_codes.csv").write_text("code,name\nBE,Belgium\n", encoding="utf-8")
    model = hub / "integration" / "transforms" / "dbt" / "models" / "customer_stage.sql"
    model.write_text(
        "select customer_id, customer_name from {{ source('crm', 'customers') }} "
        "left join {{ ref('country_codes') }} on 1 = 1\n",
        encoding="utf-8",
    )
    return hub


def test_emit_writes_seed_dependencies_and_fails_closed_on_tampering(tmp_path):
    hub = _seeded_contracted_hub(tmp_path / "hub")
    result = compile_domain(hub, "party", CompileMode.EMIT)
    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    target = tmp_path / "publish" / "medallion" / "dbt"

    _emit_compile_artifacts(result, target)

    seed_file = target / "seeds" / "country_codes.csv"
    assert seed_file.read_text(encoding="utf-8") == "code,name\nBE,Belgium\n"
    from kairos_ontology.core.dbt_validation import _dangling_refs

    assert _dangling_refs(target) == {}

    # Re-emitting round-trips the kind="seed" dependency state.
    _emit_compile_artifacts(result, target)
    assert seed_file.read_text(encoding="utf-8") == "code,name\nBE,Belgium\n"

    # A tampered emitted seed fails closed on the next emit.
    seed_file.write_text("code,name\nXX,Tampered\n", encoding="utf-8")
    from kairos_ontology.core.compiler.emit import ManifestError

    with pytest.raises(ManifestError):
        _emit_compile_artifacts(result, target)


def test_emit_writes_seed_column_docs_and_fails_closed_on_tampering(tmp_path):
    """#586b: the sibling `seeds/<name>.yml` is emitted and manifest-owned too."""
    hub = _seeded_contracted_hub(tmp_path / "hub")
    docs_source = hub / "integration" / "transforms" / "dbt" / "seeds" / "country_codes.yml"
    docs_text = (
        "version: 2\nseeds:\n  - name: country_codes\n"
        "    description: ISO country codes.\n    columns:\n      - name: code\n"
    )
    docs_source.write_text(docs_text, encoding="utf-8")
    result = compile_domain(hub, "party", CompileMode.EMIT)
    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    target = tmp_path / "publish" / "medallion" / "dbt"

    _emit_compile_artifacts(result, target)

    planned = {item.path: item for item in result.plan.dbt_dependencies}
    assert planned["seeds/country_codes.yml"].kind == "seed_properties"
    # A properties document is not a dbt resource, so it claims no name of its own.
    assert planned["seeds/country_codes.yml"].model_name == ""
    assert planned["seeds/country_codes.csv"].model_name == "country_codes"

    docs_file = target / "seeds" / "country_codes.yml"
    assert docs_file.read_text(encoding="utf-8") == docs_text

    # Re-emitting round-trips the kind="seed_properties" dependency state.
    _emit_compile_artifacts(result, target)
    assert docs_file.read_text(encoding="utf-8") == docs_text

    docs_file.write_text("version: 2\nseeds: []\n", encoding="utf-8")
    from kairos_ontology.core.compiler.emit import ManifestError

    with pytest.raises(ManifestError):
        _emit_compile_artifacts(result, target)


def test_dependency_kind_registry_fails_closed_on_unknown_and_misplaced_kinds():
    """The registry replaced a boolean ladder whose prefix ternary assumed `models/`."""
    from kairos_ontology.cli.compile import _DEPENDENCY_KINDS, _dependency_entry_is_valid

    assert set(_DEPENDENCY_KINDS) == {"sql", "properties", "seed", "seed_properties"}

    # Every registered kind, in its correct shape.
    assert _dependency_entry_is_valid("sql", "models/int_a.sql", "int_a")
    assert _dependency_entry_is_valid("properties", "models/schema.yml", "")
    assert _dependency_entry_is_valid("seed", "seeds/regions.csv", "regions")
    assert _dependency_entry_is_valid("seed_properties", "seeds/regions.yml", "")
    assert _dependency_entry_is_valid("seed_properties", "seeds/regions.yaml", "")

    # An unregistered kind is rejected rather than silently treated as living in models/.
    assert not _dependency_entry_is_valid("snapshot", "snapshots/s.sql", "s")
    # Right kind, wrong directory.
    assert not _dependency_entry_is_valid("seed", "models/regions.csv", "regions")
    assert not _dependency_entry_is_valid("seed_properties", "models/regions.yml", "")
    assert not _dependency_entry_is_valid("properties", "seeds/schema.yml", "")
    # Right directory, wrong suffix.
    assert not _dependency_entry_is_valid("seed", "seeds/regions.yml", "regions")
    # model_name presence must match the kind's rule in both directions.
    assert not _dependency_entry_is_valid("seed", "seeds/regions.csv", "")
    assert not _dependency_entry_is_valid("seed", "seeds/regions.csv", "other")
    assert not _dependency_entry_is_valid("seed_properties", "seeds/regions.yml", "regions")


# ---------------------------------------------------------------------------
# Multiple domains per invocation (#598)
# ---------------------------------------------------------------------------


def _second_binding(hub: Path, domain: str = "booking") -> None:
    """Declare another domain, for discovery only — it need not compile."""
    (hub / "integration" / "bindings" / f"{domain}.binding.yaml").write_text(
        textwrap.dedent(f"""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: crm-{domain}
              domain: {domain}
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
            """).strip(),
        encoding="utf-8",
    )


def _two_domain_hub(tmp_path: Path) -> Path:
    """A hub where two domains both compile cleanly.

    ``_hub`` ships one domain, which cannot show that a multi-domain invocation keeps
    each domain's verdict separate or that one report build serves them all.
    """
    hub = _hub(tmp_path)
    (hub / "model" / "ontologies" / "booking.ttl").write_text(
        textwrap.dedent("""
            @prefix booking: <https://example.test/booking#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
            <https://example.test/booking> a owl:Ontology ; owl:versionInfo "1.0.0" .
            booking:Order a owl:Class ; rdfs:label "Order" .
            booking:order_id a owl:DatatypeProperty ;
              rdfs:domain booking:Order ; rdfs:range xsd:string .
            booking:orderName a owl:DatatypeProperty ;
              rdfs:domain booking:Order ; rdfs:range xsd:string .
            """).strip(),
        encoding="utf-8",
    )
    (hub / "integration" / "bindings" / "order.binding.yaml").write_text(
        textwrap.dedent("""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: crm-order
              domain: booking
            source:
              relation: crm.customers
            target:
              class: booking:Order
            grain:
              columns: [customer_id]
            identity:
              strategy: source-natural
              sourceKey: [customer_id]
            load:
              mode: full-refresh
            fields:
              - property: booking:order_id
                expression: customer_id
              - property: booking:orderName
                expression: customer_name
            """).strip(),
        encoding="utf-8",
    )
    return hub


def test_hub_domains_discovers_every_declared_domain(tmp_path):
    from kairos_ontology.cli.compile import _hub_domains

    hub = _hub(tmp_path)
    assert _hub_domains(hub) == ["party"]

    _second_binding(hub)
    assert _hub_domains(hub) == ["booking", "party"]


def test_compile_requires_a_domain_or_all(tmp_path):
    hub = _hub(tmp_path)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=hub):
        result = runner.invoke(cli, ["compile", "--check"])
    assert result.exit_code == 2
    assert "at least one DOMAIN" in result.output


def test_compile_all_and_explicit_domains_are_mutually_exclusive(tmp_path):
    hub = _hub(tmp_path)
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=hub):
        result = runner.invoke(cli, ["compile", "--all", "party", "--check"])
    assert result.exit_code == 2
    assert "do not also name DOMAINS" in result.output


def test_compile_all_compiles_every_declared_domain(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "--all", "--check"])

    assert result.exit_code == 0, result.output
    assert "party: compile check passed" in result.output


def test_compile_repeats_a_named_domain_only_once(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "party", "--check"])

    assert result.exit_code == 0, result.output
    assert result.output.count("party: compile check passed") == 1
    # One domain after dedup, so no multi-domain summary line.
    assert "domain(s) compiled" not in result.output


def test_one_domains_failure_does_not_skip_the_others(tmp_path, monkeypatch):
    """A release loop must not stop at the first bad domain, nor read as success."""
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "nosuchdomain", "--check"])

    assert result.exit_code == 1
    assert "party: compile check passed" in result.output
    assert "✗ 1/2 domain(s) compiled" in result.output
    assert "failed: nosuchdomain" in result.output


def test_single_domain_json_keeps_the_object_shape(tmp_path, monkeypatch):
    """Existing consumers parse one object; only a multi-domain call returns an array."""
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "party", "--check", "--format", "json"])

    assert result.exit_code == 0, result.output
    assert isinstance(json.loads(result.stdout), dict)


def test_multi_domain_json_returns_one_payload_per_domain(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli, ["compile", "party", "nosuchdomain", "--check", "--format", "json"]
    )

    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert [entry["domain"] for entry in payload] == ["party", "nosuchdomain"]


def test_compile_all_builds_the_alignment_report_once_for_the_whole_hub(
    tmp_path, monkeypatch
):
    """The #598 win: the domain-independent corpus walk is paid once, not per domain."""
    from kairos_ontology.core import alignment_report as module

    hub = _two_domain_hub(tmp_path)
    monkeypatch.chdir(hub)

    calls = [0]
    original = module._build_alignment_report_uncached

    def counting(*args, **kwargs):
        calls[0] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "_build_alignment_report_uncached", counting)
    result = CliRunner().invoke(cli, ["compile", "--all", "--check"])

    assert result.exit_code == 0, result.output
    assert "✓ 2/2 domain(s) compiled" in result.output
    # Two domains x two gates = four asks, one build.
    assert calls[0] == 1


def test_multi_domain_json_stdout_stays_machine_readable(tmp_path, monkeypatch):
    """stdout under --format json is the payload and nothing else.

    The multi-domain progress summary is for a human watching a release loop; printed
    to stdout it lands after the closing bracket and makes the whole document fail to
    parse, which is exactly how a consumer would meet it.
    """
    hub = _two_domain_hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["compile", "--all", "--check", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [entry["domain"] for entry in payload] == ["booking", "party"]
    assert "domain(s) compiled" not in result.stdout
