# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Fresh-hub acceptance scenario for the v5 compiler."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.compiler import CompileMode, compile_domain
from kairos_ontology.core.compiler.emit import emit_artifacts
from kairos_ontology.core.compiler.quality import SAFETY_RULE_CODES

_HUB = Path(__file__).parent / "v5-hub"


def _copy_hub(tmp_path: Path, *, adapter: str = "fabric") -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_HUB, hub)
    (hub / "kairos.yaml").write_text(f"adapter: {adapter}\n", encoding="utf-8")
    return hub


def _binding(hub: Path, name: str) -> tuple[Path, dict]:
    path = hub / "integration" / "bindings" / f"{name}.binding.yaml"
    return path, yaml.safe_load(path.read_text(encoding="utf-8"))


def _write_binding(path: Path, document: dict) -> None:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _incremental(scd: int) -> dict:
    return {
        "mode": "incremental",
        "scd": scd,
        "incremental": {
            "mergeIdentity": ["customer_id"],
            "canonicalHashInputs": ["customer_id", "customer_name"],
            "cdcOperation": {
                "column": "operation",
                "insertValues": ["I"],
                "updateValues": ["U"],
                "deleteValues": ["D"],
            },
            "sourceUpdatedAt": "source_updated_at",
            "businessEffectiveAt": "effective_at",
            "ingestedAt": "ingested_at",
            "totalOrder": ["source_updated_at", "sequence_number"],
            "lookback": {"value": 2, "unit": "days"},
            "delete": "soft-delete",
            "lateArrival": "accept",
            "correction": "overwrite" if scd == 1 else "new-version",
            "replay": "idempotent",
            "backfill": "merge",
            "schemaEvolution": "append-compatible",
        },
    }


def _incremental_customer(hub: Path, scd: int, *, temporal_mode: str | None = None) -> None:
    path, document = _binding(hub, "customer")
    document["load"] = _incremental(scd)
    if temporal_mode:
        document["load"]["incremental"]["canonicalHashInputs"].append("party:country")
        relationship = document["relationships"][0]
        relationship["mode"] = temporal_mode
        relationship["temporal"] = {
            **({"childEventTime": "effective_at"} if temporal_mode == "as-of" else {}),
            "parentValidFrom": "_business_valid_from",
            "parentValidTo": "_business_valid_to",
            "openEnded": None,
            "overlap": "error",
            "lateParent": "error",
            "changeDetection": "include",
        }
    _write_binding(path, document)


def _incremental_country(hub: Path) -> None:
    path, document = _binding(hub, "country")
    policy = _incremental(2)
    policy["incremental"].update(
        {
            "mergeIdentity": ["code"],
            "canonicalHashInputs": ["code", "country_name"],
            "businessEffectiveAt": "valid_from",
        }
    )
    document["load"] = policy
    _write_binding(path, document)


def _add_conformance(hub: Path, *, compatible: bool = True) -> None:
    crm_path, crm = _binding(hub, "customer")
    policy = {
        "group": "party-customer",
        "sourcePrecedence": 1,
        "conflict": "prefer-precedence",
        "union": {
            "mode": "deduplicate",
            "deduplicateBy": ["customer_id"],
            "orderBy": [{"column": "customer_id", "direction": "ascending"}],
        },
    }
    crm["conformance"] = policy
    _write_binding(crm_path, crm)
    erp = {
        **crm,
        "metadata": {**crm["metadata"], "name": "erp-customer"},
        "source": {"relation": "erp.customers"},
        "conformance": {
            **policy,
            "group": "party-customer" if compatible else "incompatible-customer",
            "sourcePrecedence": 2,
        },
    }
    _write_binding(
        hub / "integration" / "bindings" / "erp-customer.binding.yaml",
        erp,
    )


def _codes(result) -> set[str]:
    return {item.code for item in result.diagnostics.items}


def test_v5_scenario_check_explain_and_deterministic_plan():
    checked = compile_domain(_HUB, "party", CompileMode.CHECK)
    explained = compile_domain(_HUB, "party", CompileMode.EXPLAIN)
    repeated = compile_domain(_HUB, "party", CompileMode.EXPLAIN)
    assert checked.succeeded, [item.render() for item in checked.diagnostics.items]
    assert explained.succeeded
    assert len(explained.explain.entities) == 2
    assert explained.artifacts == repeated.artifacts
    artifacts = explained.artifact_dict()
    assert set(explained.plan.artifact_paths) == set(artifacts)
    assert "models/silver/party/customer.sql" in artifacts
    assert "models/silver/party/country.sql" in artifacts
    assert "upper(" in artifacts["models/silver/party/customer.sql"].lower()
    assert "left join {{ ref('country') }}" in artifacts["models/silver/party/customer.sql"].lower()
    assert "_match_count" in artifacts["models/silver/party/customer.sql"]
    assert "tests/party/customer__reconcile_rowcount.sql" in artifacts
    forbidden = ("preparation", "stub", "release", "dq-runtime", "runtime-result")
    assert not any(token in path.lower() for path in artifacts for token in forbidden)
    schema = yaml.safe_load(artifacts["models/silver/party/_party__models.yml"])
    customer = next(model for model in schema["models"] if model["name"] == "customer")
    customer_name = next(
        column for column in customer["columns"] if column["name"] == "customer_name"
    )
    assert "not_null" in customer_name["tests"]


def test_v5_scenario_is_stateless_and_layered():
    before = {path.relative_to(_HUB) for path in _HUB.rglob("*")}
    compile_domain(_HUB, "party")
    after = {path.relative_to(_HUB) for path in _HUB.rglob("*")}
    assert before == after
    forbidden = (
        ".kairos-state",
        "readiness",
        "proposal",
        "virtual-source",
        "preparation",
        "mapping.ttl",
        "silver-ext",
        "release",
    )
    assert not any(any(token in str(path).lower() for token in forbidden) for path in after)
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import kairos_ontology.core.compiler; "
                "assert 'kairos_ontology.mdm' not in sys.modules"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr


def test_v5_scenario_emit_is_byte_deterministic_and_manifest_owned(tmp_path):
    plan = compile_domain(_HUB, "party", CompileMode.EMIT)
    first = emit_artifacts(plan.artifact_dict(), tmp_path, owned_subtree="party")
    first_bytes = {
        path.relative_to(first.target_dir): path.read_bytes()
        for path in first.target_dir.rglob("*")
        if path.is_file()
    }
    second = emit_artifacts(plan.artifact_dict(), tmp_path, owned_subtree="party")
    second_bytes = {
        path.relative_to(second.target_dir): path.read_bytes()
        for path in second.target_dir.rglob("*")
        if path.is_file()
    }
    assert first_bytes == second_bytes
    manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    manifest_paths = tuple(item["path"] for item in manifest["files"])
    assert tuple(plan.plan.artifact_paths) == tuple(sorted(plan.artifact_dict()))
    assert manifest_paths == tuple(plan.plan.artifact_paths)
    assert (second.target_dir / "models/silver/party/customer.sql").is_file()


def test_v5_reemit_prunes_stale_noncanonical_manifest_artifacts(tmp_path):
    result = compile_domain(_HUB, "party", CompileMode.EMIT)
    obsolete = {
        **result.artifact_dict(),
        "contracts/dq-runtime-result-contract.schema.json": "{}\n",
        "metadata/party-release-review.json": "{}\n",
        "models/preparation/party/customer.sql": "select 1\n",
    }
    emit_artifacts(obsolete, tmp_path, owned_subtree="party")

    reemitted = emit_artifacts(result.artifact_dict(), tmp_path, owned_subtree="party")

    assert reemitted.removed == (
        "contracts/dq-runtime-result-contract.schema.json",
        "metadata/party-release-review.json",
        "models/preparation/party/customer.sql",
    )
    manifest = json.loads(reemitted.manifest_path.read_text(encoding="utf-8"))
    manifest_paths = {item["path"] for item in manifest["files"]}
    assert not manifest_paths.intersection(obsolete.keys() - result.artifact_dict().keys())


@pytest.mark.parametrize("adapter", ["fabric", "databricks"])
def test_stage2_full_refresh_remains_unchanged_on_both_adapters(tmp_path, adapter):
    result = compile_domain(_copy_hub(tmp_path, adapter=adapter), "party", CompileMode.EXPLAIN)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    customer_sql = result.artifact_dict()["models/silver/party/customer.sql"].lower()
    assert "materialized='table'" in customer_sql
    assert "dd-109 scd" not in customer_sql
    assert "kairos_canonical_hash_v1" not in customer_sql
    assert all(entity.load.mode == "full-refresh" for entity in result.explain.entities)
    if adapter == "databricks":
        assert "`src`.`country_code`" in customer_sql
        assert "[src]" not in customer_sql
    else:
        assert "[src].[country_code]" in customer_sql
        assert "`src`" not in customer_sql


@pytest.mark.parametrize(("adapter", "scd"), [("fabric", 1), ("databricks", 2)])
def test_stage2_incremental_scd_contract_reaches_adapter_sql(tmp_path, adapter, scd):
    hub = _copy_hub(tmp_path, adapter=adapter)
    _incremental_customer(hub, scd)

    first = compile_domain(hub, "party", CompileMode.EXPLAIN)
    repeated = compile_domain(hub, "party", CompileMode.EMIT)

    assert first.succeeded, [item.render() for item in first.diagnostics.items]
    assert first.artifacts == repeated.artifacts
    sql = first.artifact_dict()["models/silver/party/customer.sql"].lower()
    assert f"dd-109 scd{scd} runtime" in sql
    assert "kairos_canonical_hash_v1" in sql
    assert "_cdc_operation" in sql
    assert "_cdc_sequence" in sql
    assert "row_number() over" in sql
    assert "soft-delete" in sql
    if scd == 2:
        assert "_business_valid_from" in sql
        assert "_business_valid_to" in sql
    explained = next(item for item in first.explain.entities if item.name == "crm-customer")
    assert explained.load.scd == scd
    assert explained.load.merge_identity == ("customer_id",)
    assert explained.load.canonical_hash_inputs == ("customer_id", "customer_name")


@pytest.mark.parametrize("mode", ["current", "as-of"])
def test_stage2_temporal_fk_has_match_count_and_fail_closed_time_semantics(tmp_path, mode):
    hub = _copy_hub(tmp_path)
    _incremental_country(hub)
    _incremental_customer(hub, 2, temporal_mode=mode)

    result = compile_domain(hub, "party", CompileMode.EXPLAIN)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    sql = result.artifact_dict()["models/silver/party/customer.sql"].lower()
    assert "_match_count" in sql
    assert "count([country].[country_sk]) over" in sql
    assert "_business_valid_from" in sql
    assert "_business_valid_to" in sql
    if mode == "as-of":
        assert "effective_at" in sql
    schema = yaml.safe_load(result.artifact_dict()["models/silver/party/_party__models.yml"])
    customer = next(model for model in schema["models"] if model["name"] == "customer")
    country = next(model for model in schema["models"] if model["name"] == "country")
    customer_tests = yaml.safe_dump(customer["data_tests"], sort_keys=True)
    country_tests = yaml.safe_dump(country["data_tests"], sort_keys=True)
    assert "kairos_temporal_fk_cardinality" in customer_tests
    assert "missing_action: fail" in customer_tests
    assert "ambiguous_action: fail" in customer_tests
    assert "kairos_runtime_half_open_intervals" in country_tests
    column_names = [column["name"] for column in customer["columns"]]
    assert len(column_names) == len(set(column_names))
    match_count = next(
        column for column in customer["columns"] if column["name"].endswith("_match_count")
    )
    assert match_count["data_type"].lower() in {"bigint", "long"}
    relationship = next(
        item for item in result.explain.entities if item.name == "crm-customer"
    ).relationship_shapes[0]
    assert relationship.mode == mode
    assert relationship.temporal


def test_stage2_conformance_is_explicit_precedence_union_and_dedup(tmp_path):
    hub = _copy_hub(tmp_path)
    _add_conformance(hub)

    result = compile_domain(hub, "party", CompileMode.EXPLAIN)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    artifacts = result.artifact_dict()
    sql = artifacts["models/silver/party/customer.sql"].lower()
    assert "union all" in sql
    assert "row_number() over" in sql
    assert sql.index("customer__from_crm__customers") < sql.index("customer__from_erp__customers")
    branches = sorted(path for path in artifacts if "customer__from_" in path)
    assert len(branches) == 2
    entities = {item.name: item for item in result.explain.entities}
    assert entities["crm-customer"].conformance.source_precedence == 1
    assert entities["erp-customer"].conformance.source_precedence == 2
    assert all(
        item.conformance.union_mode == "deduplicate"
        for item in entities.values()
        if item.conformance is not None
    )
    inputs = {item.name.replace("\\", "/") for item in result.ir.scope.inputs}
    assert "integration/sources/crm/crm.vocabulary.ttl" in inputs
    assert "integration/sources/erp/erp.vocabulary.ttl" in inputs


def test_stage2_conformance_incompatible_group_blocks_only_group(tmp_path):
    hub = _copy_hub(tmp_path)
    _add_conformance(hub, compatible=False)

    result = compile_domain(hub, "party")

    assert not result.succeeded
    assert "conformance.group-mismatch" in _codes(result)
    blocked = {item.name: item.blocked for item in result.explain.entities}
    assert blocked["crm-customer"] and blocked["erp-customer"]
    assert not blocked["crm-country"]
    assert "models/silver/party/country.sql" in result.artifact_dict()
    assert "models/silver/party/customer.sql" not in result.artifact_dict()


def test_stage2_contracted_dbt_model_uses_sql_yaml_and_provenance(tmp_path):
    hub = _copy_hub(tmp_path)
    path, document = _binding(hub, "customer")
    document["source"] = {
        "dbtModel": {
            "name": "customer_stage",
            "sqlPath": "integration/transforms/dbt/models/customer_stage.sql",
            "contractPath": "integration/transforms/dbt/models/schema.yml",
        }
    }
    _write_binding(path, document)

    result = compile_domain(hub, "party", CompileMode.EXPLAIN)

    assert result.succeeded, [item.render() for item in result.diagnostics.items]
    sql = result.artifact_dict()["models/silver/party/customer.sql"]
    assert "ref('customer_stage')" in sql
    assert "source('dbt'" not in sql
    customer = next(item for item in result.explain.entities if item.name == "crm-customer")
    assert customer.source_kind == "dbt-model"
    inputs = {item.name for item in result.ir.scope.inputs}
    assert "integration/transforms/dbt/models/customer_stage.sql" in inputs
    assert "integration/transforms/dbt/models/schema.yml" in inputs


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing", "dbt-source.path-unresolved"),
        ("bad-contract", "dbt-source.contract-not-enforced"),
    ],
)
def test_stage2_contracted_dbt_model_missing_or_bad_contract_blocks_entity(
    tmp_path, mutation, expected
):
    hub = _copy_hub(tmp_path)
    path, document = _binding(hub, "customer")
    document["source"] = {
        "dbtModel": {
            "name": "customer_stage",
            "sqlPath": "integration/transforms/dbt/models/customer_stage.sql",
            "contractPath": "integration/transforms/dbt/models/schema.yml",
        }
    }
    if mutation == "missing":
        document["source"]["dbtModel"]["sqlPath"] = "integration/transforms/dbt/models/missing.sql"
    else:
        contract = hub / "integration" / "transforms" / "dbt" / "models" / "schema.yml"
        contract.write_text(
            contract.read_text(encoding="utf-8").replace("enforced: true", "enforced: false"),
            encoding="utf-8",
        )
    _write_binding(path, document)

    result = compile_domain(hub, "party")

    assert expected in _codes(result)
    assert result.can_emit
    assert "models/silver/party/country.sql" in result.artifact_dict()
    assert "models/silver/party/customer.sql" not in result.artifact_dict()


def test_stage2_scope_provenance_is_source_scoped_and_stateless(tmp_path):
    hub = _copy_hub(tmp_path)
    before = {path.relative_to(hub): path.read_bytes() for path in hub.rglob("*") if path.is_file()}
    first = compile_domain(hub, "party", CompileMode.EXPLAIN)
    erp = hub / "integration" / "sources" / "erp" / "erp.vocabulary.ttl"
    erp.write_text(erp.read_text(encoding="utf-8") + "\n# unrelated change\n", encoding="utf-8")
    second = compile_domain(hub, "party", CompileMode.EXPLAIN)
    after = {
        path.relative_to(hub): path.read_bytes()
        for path in hub.rglob("*")
        if path.is_file() and path != erp
    }

    assert first.provenance_hash == second.provenance_hash
    assert first.artifacts == second.artifacts
    assert {
        path: content for path, content in before.items() if path != erp.relative_to(hub)
    } == after
    assert not any(".kairos-state" in str(path) for path in hub.rglob("*"))


def test_stage2_forbids_v4_and_runtime_release_artifacts(tmp_path):
    result = compile_domain(_copy_hub(tmp_path), "party", CompileMode.EMIT)

    forbidden = (
        "dq-runtime-result-contract",
        "mapping.ttl",
        "silver-ext",
        "virtual-source",
        "readiness",
        "release",
        "proposal",
    )
    assert result.succeeded
    assert not any(
        token in path.lower() or token in content.lower()
        for path, content in result.artifacts
        for token in forbidden
    )
    assert set(SAFETY_RULE_CODES) == {
        "safety.source-unresolved",
        "safety.column-unresolved",
        "safety.class-unresolved",
        "safety.property-unresolved",
        "safety.type-incompatible",
        "safety.expression-unsafe",
        "safety.grain-missing",
        "safety.identity-incomplete",
        "safety.identity-role-collision",
        "safety.incremental-identity-incomplete",
        "safety.relationship-endpoint",
        "safety.adapter-unsupported",
        "safety.artifact-collision",
    }


@pytest.mark.parametrize(
    "safety_code",
    SAFETY_RULE_CODES,
)
def test_stage2_each_non_suppressible_safety_family_blocks_in_a_fresh_hub(tmp_path, safety_code):
    hub = _copy_hub(tmp_path / safety_code.replace(".", "-"))
    customer_path, customer = _binding(hub, "customer")

    if safety_code == "safety.source-unresolved":
        customer["source"]["relation"] = "missing.customers"
    elif safety_code == "safety.column-unresolved":
        customer["fields"][1]["expression"] = "missing_name"
    elif safety_code == "safety.class-unresolved":
        customer["target"]["class"] = "party:Missing"
    elif safety_code == "safety.property-unresolved":
        customer["fields"][1]["property"] = "party:missingName"
    elif safety_code == "safety.type-incompatible":
        source = hub / "integration" / "sources" / "crm" / "crm.vocabulary.ttl"
        source.write_text(
            source.read_text(encoding="utf-8").replace(
                'kb:columnName "country_code" ; kb:dataType "char(2)"',
                'kb:columnName "country_code" ; kb:dataType "bigint"',
            ),
            encoding="utf-8",
        )
    elif safety_code == "safety.expression-unsafe":
        customer["fields"][1]["expression"] = {
            "fn": "trim",
            "args": [{"column": "customer_name"}],
        }
    elif safety_code == "safety.grain-missing":
        del customer["grain"]
    elif safety_code == "safety.identity-incomplete":
        del customer["identity"]
    elif safety_code == "safety.identity-role-collision":
        ontology = hub / "model" / "ontologies" / "party.ttl"
        ontology.write_text(
            ontology.read_text(encoding="utf-8").replace(
                "party:customer_id a owl:DatatypeProperty",
                "party:customer_sk a owl:DatatypeProperty",
            ),
            encoding="utf-8",
        )
        customer["fields"][0]["property"] = "party:customer_sk"
    elif safety_code == "safety.incremental-identity-incomplete":
        customer["load"] = _incremental(1)
        customer["load"]["incremental"]["mergeIdentity"] = ["missing_id"]
    elif safety_code == "safety.relationship-endpoint":
        customer["relationships"][0]["target"] = "party:Missing"
    elif safety_code == "safety.adapter-unsupported":
        (hub / "kairos.yaml").write_text("adapter: unsupported\n", encoding="utf-8")
    elif safety_code == "safety.artifact-collision":
        duplicate = hub / "integration" / "bindings" / "duplicate.binding.yaml"
        _write_binding(duplicate, customer)

    if safety_code != "safety.artifact-collision":
        _write_binding(customer_path, customer)
    result = compile_domain(hub, "party", CompileMode.EMIT)

    assert not result.succeeded
    assert safety_code in _codes(result), [item.render() for item in result.diagnostics.items]
    assert all(path != "models/silver/party/customer.sql" for path in result.artifact_dict())


def test_stage2_policy_failures_are_source_located_deterministic_and_non_suppressible(tmp_path):
    hub = _copy_hub(tmp_path)
    _incremental_customer(hub, 2)
    path, customer = _binding(hub, "customer")
    customer["load"]["incremental"]["cdcOperation"]["updateValues"] = ["I"]
    _write_binding(path, customer)

    first = compile_domain(hub, "party", CompileMode.CHECK)
    second = compile_domain(hub, "party", CompileMode.EXPLAIN)

    assert not first.succeeded and not second.succeeded
    assert [item.render() for item in first.diagnostics.items] == [
        item.render() for item in second.diagnostics.items
    ]
    assert "binding.cdc-operation-ambiguous" in _codes(first)
    diagnostic = next(
        item for item in first.diagnostics.items if item.code == "binding.cdc-operation-ambiguous"
    )
    assert diagnostic.location.path.endswith("customer.binding.yaml")
    assert diagnostic.location.pointer.endswith("/cdcOperation/updateValues")
    assert "models/silver/party/country.sql" in first.artifact_dict()
    assert "models/silver/party/customer.sql" not in first.artifact_dict()
