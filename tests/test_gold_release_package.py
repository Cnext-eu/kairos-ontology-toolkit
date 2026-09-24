# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Packaging the validated Gold Power BI output into one release archive (DD-206 #8)."""

from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO

import pytest

from kairos_ontology.core.projections.dbt.gold_release_package import (
    build_powerbi_release_archive,
    filter_deployable_artifacts,
    is_deployable_item_path,
)


def _artifacts(domain: str, model_name: str) -> dict[str, str]:
    prefix = f"{domain}/{model_name}.SemanticModel"
    report = f"{domain}/{model_name}.Report"
    return {
        f"{domain}/{domain}-gold-ddl.sql": "CREATE TABLE ...",
        f"{domain}/{domain}-gold-erd.mmd": "erDiagram",
        f"{domain}/{domain}-gold-product.json": "{}",
        f"{domain}/dbt/models/gold/{domain}/_gold_models.yml": "version: 2\n",
        "parameter.yml": "find_replace: []\n",
        f"{prefix}/.platform": '{"metadata": {"type": "SemanticModel"}}',
        f"{prefix}/definition.pbism": '{"version": "4.2"}',
        f"{prefix}/definition/model.tmdl": "model Model\n",
        f"{report}/.platform": '{"metadata": {"type": "Report"}}',
        f"{report}/definition.pbir": "{}",
    }


def test_is_deployable_item_path_keeps_only_semantic_model_and_report_folders():
    assert is_deployable_item_path("invoice/Invoice.SemanticModel/definition/model.tmdl")
    assert is_deployable_item_path("invoice/Invoice.Report/.platform")
    assert not is_deployable_item_path("invoice/invoice-gold-ddl.sql")
    assert not is_deployable_item_path("invoice/invoice-gold-product.json")
    assert not is_deployable_item_path("parameter.yml")


def test_filter_deployable_artifacts_drops_hub_internal_files():
    artifacts = _artifacts("invoice", "Invoice")
    kept = filter_deployable_artifacts(artifacts)

    assert set(kept) == {
        "invoice/Invoice.SemanticModel/.platform",
        "invoice/Invoice.SemanticModel/definition.pbism",
        "invoice/Invoice.SemanticModel/definition/model.tmdl",
        "invoice/Invoice.Report/.platform",
        "invoice/Invoice.Report/definition.pbir",
    }


def test_archive_contains_both_item_folders_with_a_verifiable_sha256():
    domain_artifacts = {"invoice": _artifacts("invoice", "Invoice")}

    archive = build_powerbi_release_archive(domain_artifacts)

    assert archive is not None
    assert archive.domains == ("invoice",)
    assert hashlib.sha256(archive.zip_bytes).hexdigest() == archive.sha256

    with zipfile.ZipFile(BytesIO(archive.zip_bytes)) as zf:
        names = set(zf.namelist())
        assert any(".SemanticModel/" in name for name in names)
        assert any(".Report/" in name for name in names)
        assert not any("gold-ddl" in name for name in names)
        assert not any("gold-product" in name for name in names)
        # #993: fabric-cicd reads it from the root of the extracted archive.
        assert "parameter.yml" in names
        assert zf.read("parameter.yml").decode("utf-8") == "find_replace: []\n"


def test_archive_is_deterministic_across_rebuilds():
    domain_artifacts = {"invoice": _artifacts("invoice", "Invoice")}

    first = build_powerbi_release_archive(domain_artifacts)
    second = build_powerbi_release_archive(domain_artifacts)

    assert first is not None and second is not None
    assert first.zip_bytes == second.zip_bytes
    assert first.sha256 == second.sha256


def test_multiple_domains_are_packaged_into_one_archive():
    domain_artifacts = {
        "invoice": _artifacts("invoice", "Invoice"),
        "party": _artifacts("party", "Party"),
    }

    archive = build_powerbi_release_archive(domain_artifacts)

    assert archive is not None
    assert archive.domains == ("invoice", "party")
    with zipfile.ZipFile(BytesIO(archive.zip_bytes)) as zf:
        names = zf.namelist()
        assert any(name.startswith("invoice/Invoice.SemanticModel/") for name in names)
        assert any(name.startswith("party/Party.SemanticModel/") for name in names)


def test_no_gold_configured_domain_produces_no_archive():
    """A hub with no Gold Power BI profile must not emit a dangling artifact."""
    domain_artifacts = {
        "invoice": {
            "invoice/invoice-gold-ddl.sql": "CREATE TABLE ...",
            "invoice/invoice-gold-product.json": "{}",
        }
    }

    archive = build_powerbi_release_archive(domain_artifacts)

    assert archive is None


def test_empty_input_produces_no_archive():
    assert build_powerbi_release_archive({}) is None


def test_domain_missing_report_or_semantic_model_fails_closed():
    """DD-206 #8 item 7: fail when Gold is configured but the expected item is absent."""
    artifacts = _artifacts("invoice", "Invoice")
    del artifacts["invoice/Invoice.Report/.platform"]
    del artifacts["invoice/Invoice.Report/definition.pbir"]

    with pytest.raises(ValueError, match="Report"):
        build_powerbi_release_archive({"invoice": artifacts})


def test_one_hub_wide_parameter_file_ships_once_at_the_root():
    """#993: without it every environment deployed the hub's default workspace."""
    archive = build_powerbi_release_archive(
        {"invoice": _artifacts("invoice", "Invoice"), "party": _artifacts("party", "Party")}
    )
    assert archive is not None
    with zipfile.ZipFile(BytesIO(archive.zip_bytes)) as zf:
        assert [name for name in zf.namelist() if name.endswith("parameter.yml")] == [
            "parameter.yml"
        ]


def test_products_disagreeing_on_parameterisation_fail_closed():
    party = _artifacts("party", "Party")
    party["parameter.yml"] = "find_replace: [something-else]\n"
    with pytest.raises(ValueError, match="different parameter.yml"):
        build_powerbi_release_archive({"invoice": _artifacts("invoice", "Invoice"), "party": party})


def test_a_domain_without_items_contributes_no_parameter_file():
    """Only a packaged product's parameterisation counts; a stray one cannot conflict."""
    stray = {"other/other-gold-ddl.sql": "x", "parameter.yml": "find_replace: [stale]\n"}
    archive = build_powerbi_release_archive(
        {"invoice": _artifacts("invoice", "Invoice"), "other": stray}
    )
    assert archive is not None
