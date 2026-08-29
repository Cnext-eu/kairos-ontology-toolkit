# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for ``scaffold-staging`` (issue #399): first-class stg_/int_merged__ scaffolding.

Fixture pattern follows ``tests/test_scaffold_binding.py``'s hand-written Bronze
vocabulary TTL -- scaffold-staging never touches ontologies/bindings, only source
vocabularies and the dbt transforms tree, so no accelerator/catalog fixture is needed.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.scaffold_binding import ScaffoldBindingError
from kairos_ontology.core.scaffold_staging import ScaffoldStagingError, run_scaffold_staging

_CRM_TTL = textwrap.dedent(
    """
    @prefix src: <https://example.test/source/crm#> .
    @prefix kb: <https://kairos.cnext.eu/bronze#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    src:customers a kb:SourceTable ; kb:sourceSystem src:crm ;
      kb:tableName "customers" ; kb:primaryKeyColumns "customer_id" .
    src:cid a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "customer_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean .
    src:cname a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "customer_name" ; kb:dataType "varchar(200)" ;
      kb:nullable "false"^^xsd:boolean .
    src:cnotes a kb:SourceColumn ; kb:sourceTable src:customers ;
      kb:columnName "crm_only_notes" ; kb:dataType "varchar(4000)" ;
      kb:nullable "true"^^xsd:boolean .
    """
).strip()

_ERP_TTL = textwrap.dedent(
    """
    @prefix src: <https://example.test/source/erp#> .
    @prefix kb: <https://kairos.cnext.eu/bronze#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

    src:parties a kb:SourceTable ; kb:sourceSystem src:erp ;
      kb:tableName "parties" ; kb:primaryKeyColumns "customer_id" .
    src:pid a kb:SourceColumn ; kb:sourceTable src:parties ;
      kb:columnName "customer_id" ; kb:dataType "varchar(50)" ;
      kb:nullable "false"^^xsd:boolean .
    src:pname a kb:SourceColumn ; kb:sourceTable src:parties ;
      kb:columnName "customer_name" ; kb:dataType "varchar(200)" ;
      kb:nullable "false"^^xsd:boolean .
    src:perpcode a kb:SourceColumn ; kb:sourceTable src:parties ;
      kb:columnName "erp_only_code" ; kb:dataType "varchar(20)" ;
      kb:nullable "true"^^xsd:boolean .
    """
).strip()


def _hub(tmp_path: Path) -> Path:
    hub = tmp_path / "hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "integration" / "sources" / "crm").mkdir(parents=True)
    (hub / "integration" / "sources" / "erp").mkdir(parents=True)
    (hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl").write_text(
        _CRM_TTL, encoding="utf-8"
    )
    (hub / "integration" / "sources" / "erp" / "erp.vocabulary.ttl").write_text(
        _ERP_TTL, encoding="utf-8"
    )
    return hub


def test_scaffolds_one_stage_per_source_plus_merged_model(tmp_path):
    hub = _hub(tmp_path)

    result = run_scaffold_staging(
        hub, entity="party", domain="party", sources=(("crm", "customers"), ("erp", "parties"))
    )

    assert [s.model_name for s in result.stages] == ["stg_crm__party", "stg_erp__party"]
    assert result.merged_model_name == "int_merged__party"
    for stage in result.stages:
        assert stage.sql_written and stage.yaml_written
        assert stage.sql_path.is_file()
        assert stage.yaml_path.is_file()
    assert result.merged_sql_written and result.merged_yaml_written
    assert result.merged_sql_path.is_file()
    assert result.merged_yaml_path.is_file()


def test_common_columns_are_the_intersection_across_stages(tmp_path):
    hub = _hub(tmp_path)

    result = run_scaffold_staging(
        hub, entity="party", domain="party", sources=(("crm", "customers"), ("erp", "parties"))
    )

    # crm has crm_only_notes, erp has erp_only_code -- only customer_id/customer_name are shared.
    assert set(result.common_columns) == {"customer_id", "customer_name"}


def test_stage_sql_reuses_render_staging_sql_source_macro(tmp_path):
    hub = _hub(tmp_path)

    result = run_scaffold_staging(
        hub, entity="party", domain="party", sources=(("crm", "customers"), ("erp", "parties"))
    )

    crm_stage = next(s for s in result.stages if s.system == "crm")
    sql = crm_stage.sql_path.read_text(encoding="utf-8")
    assert "source('crm', 'customers')" in sql
    assert "'crm' as source_system" in sql


def test_merged_sql_has_sentinels_and_refs_every_stage(tmp_path):
    hub = _hub(tmp_path)

    result = run_scaffold_staging(
        hub, entity="party", domain="party", sources=(("crm", "customers"), ("erp", "parties"))
    )

    sql = result.merged_sql_path.read_text(encoding="utf-8")
    assert "ref('stg_crm__party')" in sql
    assert "ref('stg_erp__party')" in sql
    assert "<CONFIRM_NATURAL_KEY_COLUMN>" in sql
    assert "<CONFIRM_PRIORITY_COLUMN>" in sql
    assert "kairos_survivor(" in sql


def test_merged_yaml_has_full_meta_kairos_sentinels(tmp_path):
    hub = _hub(tmp_path)

    result = run_scaffold_staging(
        hub, entity="party", domain="party", sources=(("crm", "customers"), ("erp", "parties"))
    )

    document = yaml.safe_load(result.merged_yaml_path.read_text(encoding="utf-8"))
    model = document["models"][0]
    assert model["access"] == "public"
    assert model["config"]["contract"]["enforced"] is True
    meta = model["meta"]["kairos"]
    assert meta["target_class"] == "<CONFIRM_TARGET_CLASS>"
    assert meta["virtual_source_iri"] == "<CONFIRM_VIRTUAL_SOURCE_IRI>"
    assert meta["grain_key"] == ["<CONFIRM_GRAIN_KEY_COLUMN>"]
    assert meta["supported_adapters"] == ["<CONFIRM_SUPPORTED_ADAPTER>"]


def test_stage_yaml_has_no_meta_kairos_block(tmp_path):
    # Issue #397's discover_dbt_contracts only strictly parses models with a meta.kairos
    # block -- a stage model must NOT declare one, or it would be treated as a bindable
    # virtual source and rejected for missing target_class/virtual_source_iri it will
    # never have.
    hub = _hub(tmp_path)

    result = run_scaffold_staging(
        hub, entity="party", domain="party", sources=(("crm", "customers"), ("erp", "parties"))
    )

    for stage in result.stages:
        document = yaml.safe_load(stage.yaml_path.read_text(encoding="utf-8"))
        model = document["models"][0]
        assert model["config"]["contract"]["enforced"] is True
        assert "meta" not in model
        # Stages are internal to the merged model, never a cross-project extension
        # point, so they keep dbt's default `protected` access (no explicit `access:`).
        assert "access" not in model


def test_single_source_scaffolds_trivial_passthrough_merged_model(tmp_path):
    hub = _hub(tmp_path)

    result = run_scaffold_staging(
        hub, entity="party", domain="party", sources=(("crm", "customers"),)
    )

    assert [s.model_name for s in result.stages] == ["stg_crm__party"]
    assert result.merged_model_name == "int_merged__party"
    assert result.merged_sql_written and result.merged_yaml_written

    sql = result.merged_sql_path.read_text(encoding="utf-8")
    assert sql.strip().endswith("select * from {{ ref('stg_crm__party') }}")
    assert "kairos_survivor(" not in sql
    assert "<CONFIRM_NATURAL_KEY_COLUMN>" not in sql
    assert "<CONFIRM_PRIORITY_COLUMN>" not in sql

    document = yaml.safe_load(result.merged_yaml_path.read_text(encoding="utf-8"))
    model = document["models"][0]
    assert model["access"] == "public"
    assert model["config"]["contract"]["enforced"] is True
    meta = model["meta"]["kairos"]
    assert meta["target_class"] == "<CONFIRM_TARGET_CLASS>"
    assert meta["virtual_source_iri"] == "<CONFIRM_VIRTUAL_SOURCE_IRI>"


def test_no_source_is_rejected(tmp_path):
    hub = _hub(tmp_path)

    with pytest.raises(ScaffoldStagingError):
        run_scaffold_staging(hub, entity="party", domain="party", sources=())


def test_unknown_table_raises_scaffold_binding_error(tmp_path):
    hub = _hub(tmp_path)

    with pytest.raises(ScaffoldBindingError):
        run_scaffold_staging(
            hub,
            entity="party",
            domain="party",
            sources=(("crm", "customers"), ("crm", "no_such_table")),
        )


def test_does_not_overwrite_without_force(tmp_path):
    hub = _hub(tmp_path)
    run_scaffold_staging(
        hub, entity="party", domain="party", sources=(("crm", "customers"), ("erp", "parties"))
    )

    second = run_scaffold_staging(
        hub, entity="party", domain="party", sources=(("crm", "customers"), ("erp", "parties"))
    )

    assert not second.merged_sql_written
    assert not any(s.sql_written for s in second.stages)
    assert any("already exists" in note for note in second.notes)


def test_dry_run_writes_nothing(tmp_path):
    hub = _hub(tmp_path)

    result = run_scaffold_staging(
        hub,
        entity="party",
        domain="party",
        sources=(("crm", "customers"), ("erp", "parties")),
        dry_run=True,
    )

    assert not result.merged_sql_path.exists()
    assert not any(s.sql_path.exists() for s in result.stages)


def test_cli_end_to_end(tmp_path, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli,
        [
            "scaffold-staging",
            "--entity",
            "party",
            "--domain",
            "party",
            "--source",
            "crm.customers",
            "--source",
            "erp.parties",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "stg_crm__party" in result.output
    assert "int_merged__party" in result.output
