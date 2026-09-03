# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the standalone hand-authored dbt contract lint (issue #504)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.dbt_contract_lint import run_dbt_contract_lint
from kairos_ontology.core.dbt_contracts import DbtContractError, scan_dbt_contracts

_TARGET_CLASS = "https://example.test/party#Customer"


def _models_dir(hub: Path) -> Path:
    models = hub / "integration" / "transforms" / "dbt" / "models" / "intermediate"
    models.mkdir(parents=True, exist_ok=True)
    return models


def _contract(name: str, **overrides) -> dict:
    model = {
        "name": name,
        "description": f"Contracted {name}.",
        "config": {"materialized": "view", "contract": {"enforced": True}},
        "meta": {
            "kairos": {
                "target_class": _TARGET_CLASS,
                "virtual_source_iri": f"https://example.test/virtual/{name}",
                "grain": "one row per customer",
                "grain_key": ["customer_id"],
                "supported_adapters": ["fabric-warehouse"],
            }
        },
        "columns": [
            {"name": "customer_id", "data_type": "string", "data_tests": ["not_null"]},
            {"name": "customer_name", "data_type": "string"},
        ],
    }
    model["meta"]["kairos"].update(overrides)
    return model


def _write(hub: Path, *models: dict, stem: str = "schema", write_sql: bool = True) -> Path:
    models_dir = _models_dir(hub)
    for model in models:
        if write_sql:
            (models_dir / f"{model['name']}.sql").write_text("select 1\n", encoding="utf-8")
    path = models_dir / f"{stem}.yml"
    path.write_text(
        yaml.safe_dump({"version": 2, "models": list(models)}, sort_keys=False), encoding="utf-8"
    )
    return path


def _bind(hub: Path, model_name: str) -> None:
    bindings = hub / "integration" / "bindings"
    bindings.mkdir(parents=True, exist_ok=True)
    (bindings / f"{model_name}.binding.yaml").write_text(
        textwrap.dedent(f"""
            apiVersion: kairos.eu/v5
            kind: EntityBinding
            metadata:
              name: {model_name}-customer
              domain: party
            source:
              dbtModel:
                name: {model_name}
                sqlPath: integration/transforms/dbt/models/intermediate/{model_name}.sql
                contractPath: integration/transforms/dbt/models/intermediate/schema.yml
            target:
              class: party:Customer
            """).strip(),
        encoding="utf-8",
    )


def _codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


def _resolver(*known: str):
    return lambda iri: iri in set(known or (_TARGET_CLASS,))


# ---------------------------------------------------------------------------
# scan_dbt_contracts -- the non-raising split that makes a lint possible
# ---------------------------------------------------------------------------


def test_scan_collects_every_error_where_discover_would_raise_on_the_first(tmp_path: Path) -> None:
    """The whole reason the lint cannot reuse discover_dbt_contracts directly."""
    hub = tmp_path
    broken_a = _contract("int_a")
    broken_a["config"]["contract"]["enforced"] = False
    broken_b = _contract("int_b")
    broken_b["meta"]["kairos"]["grain_key"] = ["not_a_column"]
    _write(hub, broken_a, broken_b)

    scan = scan_dbt_contracts(hub / "integration" / "transforms" / "dbt", hub)

    assert len(scan.errors) == 2
    assert scan.models == ()


def test_scan_inventory_includes_models_without_a_kairos_block(tmp_path: Path) -> None:
    hub = tmp_path
    stage = {
        "name": "stg_crm__customer",
        "description": "Stage.",
        "config": {"materialized": "view", "contract": {"enforced": True}},
        "columns": [{"name": "customer_id", "data_type": "string"}],
    }
    _write(hub, stage, _contract("int_merged__customer"))

    scan = scan_dbt_contracts(hub / "integration" / "transforms" / "dbt", hub)

    assert {stub.name: stub.has_kairos_meta for stub in scan.inventory} == {
        "stg_crm__customer": False,
        "int_merged__customer": True,
    }


def test_scan_rejects_a_transforms_dir_outside_the_hub(tmp_path: Path) -> None:
    with pytest.raises(DbtContractError):
        scan_dbt_contracts(tmp_path / "elsewhere" / "dbt", tmp_path / "hub")


# ---------------------------------------------------------------------------
# run_dbt_contract_lint
# ---------------------------------------------------------------------------


def test_absent_transforms_tree_is_reported_not_silently_clean(tmp_path: Path) -> None:
    report = run_dbt_contract_lint(tmp_path)

    assert report.passed
    assert not report.transforms_present
    assert report.notes


def test_valid_contract_passes(tmp_path: Path) -> None:
    hub = tmp_path
    _write(hub, _contract("int_merged__customer"))
    _bind(hub, "int_merged__customer")

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    assert report.passed, [f.message for f in report.findings]
    assert report.contracted_models == ("int_merged__customer",)
    assert report.findings == ()


def test_duplicate_virtual_source_iri_is_reported_against_both_models(tmp_path: Path) -> None:
    """#503 item 5: hub-wide uniqueness, which a per-domain compile can never prove."""
    hub = tmp_path
    shared = "https://example.test/virtual/shared"
    _write(
        hub,
        _contract("int_merged__customer", virtual_source_iri=shared),
        _contract("int_merged__party", virtual_source_iri=shared),
    )

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    duplicates = [f for f in report.findings if f.code == "dbt-contract.virtual-source-duplicate"]
    assert len(duplicates) == 2
    assert {f.model for f in duplicates} == {"int_merged__customer", "int_merged__party"}
    assert not report.passed


def test_unresolvable_target_class_is_an_error(tmp_path: Path) -> None:
    hub = tmp_path
    _write(hub, _contract("int_merged__customer", target_class="https://example.test/party#Ghost"))

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    assert "dbt-contract.target-class-unresolved" in _codes(report)
    assert not report.passed


def test_skipped_target_class_resolution_is_noted_not_silently_passed(tmp_path: Path) -> None:
    """An empty findings list must never be mistaken for 'target classes were verified'."""
    hub = tmp_path
    _write(hub, _contract("int_merged__customer", target_class="https://example.test/party#Ghost"))
    _bind(hub, "int_merged__customer")

    report = run_dbt_contract_lint(hub, resolve_target_class=None)

    assert report.passed
    assert any("target_class resolution was not run" in note for note in report.notes)


def test_unconfirmed_scaffold_sentinel_is_named_field_by_field(tmp_path: Path) -> None:
    """scaffold-staging writes these; nothing rejected an unedited target_class before #503."""
    hub = tmp_path
    _write(hub, _contract("int_merged__customer", target_class="<CONFIRM_TARGET_CLASS>"))

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    sentinels = [f for f in report.findings if f.code == "dbt-contract.unconfirmed-sentinel"]
    assert len(sentinels) == 1
    assert "target_class" in sentinels[0].message
    # Not *also* reported as an unresolvable class -- one root cause, one finding.
    assert "dbt-contract.target-class-unresolved" not in _codes(report)


def test_stage_declaring_kairos_meta_warns_without_blocking(tmp_path: Path) -> None:
    """#504 item 7. A stage is internal to one transform, never a bindable virtual source."""
    hub = tmp_path
    _write(hub, _contract("stg_crm__customer"))
    _bind(hub, "stg_crm__customer")

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    assert "dbt-contract.stage-declares-kairos-meta" in _codes(report)
    assert report.passed, "a layering-convention warning must not block the author"


def test_intermediate_without_kairos_meta_warns_without_blocking(tmp_path: Path) -> None:
    """#504 item 8."""
    hub = tmp_path
    _write(
        hub,
        {
            "name": "int_merged__customer",
            "description": "Merged.",
            "config": {"materialized": "view", "contract": {"enforced": True}},
            "columns": [{"name": "customer_id", "data_type": "string"}],
        },
    )

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    assert "dbt-contract.intermediate-missing-kairos-meta" in _codes(report)
    assert report.passed


def test_contracted_model_no_binding_selects_warns(tmp_path: Path) -> None:
    hub = tmp_path
    _write(hub, _contract("int_merged__customer"))

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    assert "dbt-contract.model-unbound" in _codes(report)
    assert report.passed


def test_malformed_contract_does_not_hide_the_next_model(tmp_path: Path) -> None:
    """The behaviour difference from `discover_dbt_contracts`, asserted end to end."""
    hub = tmp_path
    broken = _contract("int_a")
    broken["config"]["contract"]["enforced"] = False
    _write(hub, broken, _contract("int_b", virtual_source_iri="not-an-iri"))

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    assert len([f for f in report.findings if f.code == "dbt-contract.invalid"]) == 2
    assert not report.passed


def test_report_dict_is_json_shaped_and_versioned(tmp_path: Path) -> None:
    hub = tmp_path
    _write(hub, _contract("int_merged__customer"))

    payload = run_dbt_contract_lint(hub, resolve_target_class=_resolver()).to_dict()

    assert payload["schema_version"] == 1
    assert payload["passed"] is True
    assert payload["contracted_models"] == ["int_merged__customer"]
    assert all({"code", "severity", "message", "path"} <= set(f) for f in payload["findings"])


# ---------------------------------------------------------------------------
# Authored seeds (#586 stage b)
# ---------------------------------------------------------------------------


def _seeds_dir(hub: Path) -> Path:
    seeds = hub / "integration" / "transforms" / "dbt" / "seeds"
    seeds.mkdir(parents=True, exist_ok=True)
    return seeds


def test_seeds_only_hub_reports_transforms_present(tmp_path: Path) -> None:
    """A hub whose entire authored transform layer is one reference seed HAS transforms."""
    seeds = _seeds_dir(tmp_path)
    (seeds / "country_codes.csv").write_text("code,label\nBE,Belgium\n", encoding="utf-8")

    report = run_dbt_contract_lint(tmp_path)

    assert report.transforms_present is True
    assert report.passed is True
    assert _codes(report) == set()
    assert any("only authored seeds" in note for note in report.notes)


def test_empty_transforms_tree_still_reports_nothing_authored(tmp_path: Path) -> None:
    _seeds_dir(tmp_path)

    report = run_dbt_contract_lint(tmp_path)

    assert report.transforms_present is False


def test_seed_colliding_with_a_model_name_is_an_error(tmp_path: Path) -> None:
    """Blocking, unlike the other seed findings: dbt has ONE ref() namespace."""
    hub = tmp_path
    _write(hub, _contract("int_customer"))
    (_seeds_dir(hub) / "int_customer.csv").write_text("customer_id\n1\n", encoding="utf-8")

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    collisions = [f for f in report.findings if f.code == "dbt-contract.seed-model-collision"]
    assert [f.severity for f in collisions] == ["error"]
    assert collisions[0].model == "int_customer"
    assert report.passed is False


def test_seed_that_is_not_utf8_is_an_advisory_finding(tmp_path: Path) -> None:
    hub = tmp_path
    _write(hub, _contract("int_customer"))
    (_seeds_dir(hub) / "regions.csv").write_bytes(b"code,label\r\nBE,Belgi\xeb\r\n")

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    unreadable = [f for f in report.findings if f.code == "dbt-contract.seed-unreadable"]
    assert [f.severity for f in unreadable] == ["warning"]
    assert report.passed is True


def test_headerless_seed_is_an_advisory_finding(tmp_path: Path) -> None:
    hub = tmp_path
    _write(hub, _contract("int_customer"))
    (_seeds_dir(hub) / "regions.csv").write_text("\n\n", encoding="utf-8")

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    assert "dbt-contract.seed-unreadable" in _codes(report)
    assert report.passed is True


def test_seed_docs_naming_a_nonexistent_seed_is_an_advisory_finding(tmp_path: Path) -> None:
    hub = tmp_path
    _write(hub, _contract("int_customer"))
    seeds = _seeds_dir(hub)
    (seeds / "regions.csv").write_text("code,label\nBE,Belgium\n", encoding="utf-8")
    (seeds / "regions.yml").write_text(
        yaml.safe_dump({"version": 2, "seeds": [{"name": "reigons"}]}, sort_keys=False),
        encoding="utf-8",
    )

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    unmatched = [f for f in report.findings if f.code == "dbt-contract.seed-docs-unmatched"]
    assert [f.severity for f in unmatched] == ["warning"]
    assert "reigons" in unmatched[0].message
    assert report.passed is True


def test_matching_seed_docs_produce_no_findings(tmp_path: Path) -> None:
    hub = tmp_path
    _write(hub, _contract("int_customer"))
    seeds = _seeds_dir(hub)
    (seeds / "regions.csv").write_text("code,label\nBE,Belgium\n", encoding="utf-8")
    (seeds / "regions.yml").write_text(
        yaml.safe_dump(
            {"version": 2, "seeds": [{"name": "regions", "columns": [{"name": "code"}]}]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report = run_dbt_contract_lint(hub, resolve_target_class=_resolver())

    assert not {code for code in _codes(report) if code.startswith("dbt-contract.seed-")}
