# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for custom dbt contract discovery and validation."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.dbt_contracts import (
    APPROVED_DBT_PACKAGES,
    DbtContractError,
    discover_dbt_contracts,
)


def test_dbt_expectations_uses_metaplane_namespace() -> None:
    """dbt_expectations must be sourced from the current metaplane hub namespace."""
    assert "metaplane/dbt_expectations" in APPROVED_DBT_PACKAGES
    assert "calogica/dbt_expectations" not in APPROVED_DBT_PACKAGES


def _model() -> dict:
    return {
        "name": "int_shipment_conformed",
        "description": "Conformed shipments.",
        "config": {"materialized": "table", "contract": {"enforced": True}},
        "meta": {
            "kairos": {
                "target_class": "https://example.com/ont#ShipmentOrder",
                "virtual_source_iri": "https://example.com/source#shipmentConformed",
                "grain": "one row per source system and shipment",
                "supported_adapters": ["fabric", "databricks"],
                "natural_key": ["source_system", "shipment_id"],
                "required_packages": ["dbt-labs/dbt_utils"],
                "required_macros": ["logistics__company_description"],
                "decisions": [
                    {
                        "id": "route-fallback",
                        "statement": "Use the first available route.",
                        "evidence": [
                            {
                                "artifact": "evidence.ttl",
                                "subject": "https://example.com/evidence#Route",
                            }
                        ],
                        "confidence": "high",
                        "status": "developer_approved",
                        "approval": {
                            "actor": "developer",
                            "timestamp": "2026-07-18T12:00:00+02:00",
                        },
                        "implemented_by": {"model": "int_shipment_conformed"},
                        "verified_by": ["unit_test_route_fallback"],
                    }
                ],
            }
        },
        "columns": [
            {"name": "source_system", "data_type": "string"},
            {"name": "shipment_id", "data_type": "string"},
        ],
    }


def _hub(tmp_path: Path, model: dict | None = None) -> tuple[Path, Path, Path]:
    hub = tmp_path / "hub"
    transforms = hub / "integration" / "transforms" / "dbt"
    model_dir = transforms / "models" / "intermediate"
    model_dir.mkdir(parents=True)
    (transforms / "tests").mkdir()
    (model_dir / "int_shipment_conformed.sql").write_text("select 1\n", encoding="utf-8")
    properties = model_dir / "models.yml"
    properties.write_text(
        yaml.safe_dump(
            {
                "version": 2,
                "models": [model or _model()],
                "unit_tests": [
                    {"name": "unit_test_route_fallback", "model": "int_shipment_conformed"}
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (hub / "evidence.ttl").write_text(
        "@prefix ex: <https://example.com/evidence#> . ex:Route ex:supports ex:Rule .\n",
        encoding="utf-8",
    )
    return hub, transforms, properties


def _expect_error(tmp_path: Path, mutate, match: str) -> None:
    model = _model()
    mutate(model)
    hub, transforms, _ = _hub(tmp_path, model)
    with pytest.raises(DbtContractError, match=match):
        discover_dbt_contracts(transforms, hub)


def test_discovers_valid_contract(tmp_path: Path) -> None:
    hub, transforms, _ = _hub(tmp_path)
    contracts = discover_dbt_contracts(transforms, hub)

    assert len(contracts) == 1
    contract = contracts[0]
    assert contract.name == "int_shipment_conformed"
    assert contract.natural_key == ("source_system", "shipment_id")
    assert contract.sql_path.is_absolute()
    assert contract.decisions[0].approval is not None
    assert contract.decisions[0].evidence[0].artifact == "evidence.ttl"
    assert contract.replaces_sources == ()


@pytest.mark.parametrize("adapter", ["fabric", "databricks"])
def test_accepts_single_supported_adapter(tmp_path: Path, adapter: str) -> None:
    model = _model()
    model["meta"]["kairos"]["supported_adapters"] = [adapter]
    hub, transforms, _ = _hub(tmp_path, model)

    contract = discover_dbt_contracts(transforms, hub)[0]

    assert contract.supported_adapters == (adapter,)


def test_parses_column_not_null_tests_and_constraints(tmp_path: Path) -> None:
    model = _model()
    model["columns"][0]["data_tests"] = ["not_null"]
    model["columns"][1]["constraints"] = [{"type": "not_null"}]
    hub, transforms, _ = _hub(tmp_path, model)

    contract = discover_dbt_contracts(transforms, hub)[0]

    assert [column.not_null for column in contract.columns] == [True, True]


def test_parses_canonical_source_replacements(tmp_path: Path) -> None:
    model = _model()
    model["meta"]["kairos"]["replaces_sources"] = [
        {"table_iri": "https://example.com/source/crm#shipments"},
        {"table_iri": "https://example.com/source/erp#orders"},
    ]
    hub, transforms, _ = _hub(tmp_path, model)

    contract = discover_dbt_contracts(transforms, hub)[0]

    assert [item.table_iri for item in contract.replaces_sources] == [
        "https://example.com/source/crm#shipments",
        "https://example.com/source/erp#orders",
    ]


def test_rejects_malformed_yaml(tmp_path: Path) -> None:
    hub, transforms, properties = _hub(tmp_path)
    properties.write_text("models: [\n", encoding="utf-8")
    with pytest.raises(DbtContractError, match="could not parse YAML"):
        discover_dbt_contracts(transforms, hub)


def test_rejects_missing_model_sql(tmp_path: Path) -> None:
    hub, transforms, _ = _hub(tmp_path)
    (transforms / "models" / "intermediate" / "int_shipment_conformed.sql").unlink()
    with pytest.raises(DbtContractError, match="exactly one matching model SQL"):
        discover_dbt_contracts(transforms, hub)


def test_rejects_duplicate_model_and_column(tmp_path: Path) -> None:
    hub, transforms, properties = _hub(tmp_path)
    document = yaml.safe_load(properties.read_text(encoding="utf-8"))
    document["models"].append(copy.deepcopy(document["models"][0]))
    properties.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(DbtContractError, match="duplicate dbt model resource"):
        discover_dbt_contracts(transforms, hub)

    document["models"] = [document["models"][0]]
    document["models"][0]["columns"].append({"name": "SOURCE_SYSTEM", "data_type": "string"})
    properties.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(DbtContractError, match="duplicate output column"):
        discover_dbt_contracts(transforms, hub)


def test_rejects_unsafe_file_and_symlink_escape(tmp_path: Path) -> None:
    hub, transforms, _ = _hub(tmp_path)
    unsafe = transforms / "profiles.yml"
    unsafe.write_text("target: forbidden\n", encoding="utf-8")
    with pytest.raises(DbtContractError, match="outside the permitted"):
        discover_dbt_contracts(transforms, hub)
    unsafe.unlink()

    outside = hub / "outside.sql"
    outside.write_text("select 1\n", encoding="utf-8")
    link = transforms / "models" / "escape.sql"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(DbtContractError, match="symlink escapes"):
        discover_dbt_contracts(transforms, hub)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda m: m["meta"]["kairos"].update(supported_adapters=["snowflake"]),
            "supported_adapters",
        ),
        (
            lambda m: m["meta"]["kairos"].update(
                supported_adapters=["fabric", "fabric"]
            ),
            "unique values",
        ),
        (lambda m: m["config"].update(materialized="ephemeral"), "materialization"),
        (lambda m: m["meta"]["kairos"].update(natural_key=["missing"]), "natural_key"),
        (
            lambda m: m["meta"]["kairos"].update(required_packages=["other/package"]),
            "unapproved packages",
        ),
        (
            lambda m: m["meta"]["kairos"].update(required_macros=["kairos_reserved"]),
            "required macros",
        ),
        (
            lambda m: m["meta"]["kairos"]["decisions"][0].update(confidence="certain"),
            "confidence",
        ),
        (
            lambda m: m["meta"]["kairos"]["decisions"][0].update(status="approved"),
            "status",
        ),
        (
            lambda m: m["meta"]["kairos"]["decisions"][0].update(
                implemented_by={"model": "other_model"}
            ),
            "unknown implementing model",
        ),
        (
            lambda m: m["meta"]["kairos"]["decisions"][0].update(verified_by=["missing_test"]),
            "unknown verifying tests",
        ),
        (
            lambda m: m["meta"]["kairos"].update(replaces_sources=[]),
            "replaces_sources must be a non-empty list",
        ),
        (
            lambda m: m["meta"]["kairos"].update(
                replaces_sources=[{"table_iri": "urn:source:orders"}]
            ),
            r"table_iri must be an absolute HTTP\(S\) IRI",
        ),
        (
            lambda m: m["meta"]["kairos"].update(
                replaces_sources=[
                    {
                        "table_iri": "https://example.com/source#orders",
                        "system": "erp",
                    }
                ]
            ),
            "contains unknown keys",
        ),
        (
            lambda m: m["meta"]["kairos"].update(
                replaces_sources=[
                    {"table_iri": "https://example.com/source#orders"},
                    {"table_iri": "https://example.com/source#orders"},
                ]
            ),
            "duplicate table_iri",
        ),
    ],
)
def test_rejects_invalid_contract_fields(tmp_path: Path, mutate, match: str) -> None:
    _expect_error(tmp_path, mutate, match)


def test_rejects_invalid_evidence_and_approval(tmp_path: Path) -> None:
    _expect_error(
        tmp_path,
        lambda m: m["meta"]["kairos"]["decisions"][0].update(
            evidence=[{"artifact": "../outside.ttl"}]
        ),
        "evidence artifact path is unsafe",
    )
    _expect_error(
        tmp_path / "approval",
        lambda m: m["meta"]["kairos"]["decisions"][0].pop("approval"),
        "approval is required",
    )


def test_rejects_invalid_iris_and_grain(tmp_path: Path) -> None:
    _expect_error(
        tmp_path,
        lambda m: m["meta"]["kairos"].update(target_class="urn:shipment"),
        r"absolute HTTP\(S\) IRI",
    )
    _expect_error(
        tmp_path / "grain",
        lambda m: m["meta"]["kairos"].update(grain=""),
        "grain must be a non-empty string",
    )
