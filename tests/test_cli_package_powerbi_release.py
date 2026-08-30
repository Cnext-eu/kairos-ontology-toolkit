# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""``kairos-ontology package-powerbi-release`` (DD-206 #8/#12 item 8).

The hub release workflow must ship one ``powerbi-semantic-model.zip`` with a recorded
SHA-256 beside the dbt release artifact, containing every Gold-configured domain's
validated Power BI output -- and must not emit a dangling archive when no domain
authors a Gold Power BI profile.
"""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import cli

_V5_FK_HUB = Path(__file__).parent / "scenarios" / "v5-hub"

_PARTY_GOLD_EXT = """
@prefix party: <https://example.test/ontology/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

<https://example.test/ontology/party>
  kairos-ext:goldSchema "gold" ;
  kairos-ext:goldProductProfile "dimensional-powerbi-v1" .

party:Customer
  kairos-ext:goldTableType "dimension" ;
  kairos-ext:goldTableName "dim_customer" ;
  kairos-ext:goldSourceModel "customer" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:dimensionExposure "current-only" ;
  kairos-ext:dimensionVersionBinding "current" .
"""


def _copy_hub(tmp_path: Path, *, with_gold_ext: bool = True) -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_V5_FK_HUB, hub)
    if with_gold_ext:
        ext_dir = hub / "model" / "extensions"
        ext_dir.mkdir(parents=True, exist_ok=True)
        (ext_dir / "party-gold-ext.ttl").write_text(_PARTY_GOLD_EXT, encoding="utf-8")
    return hub


def test_dry_run_reports_and_writes_nothing(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["package-powerbi-release"])

    assert result.exit_code == 0, result.output
    assert "Would package" in result.output
    assert "--confirm-emit" in result.output
    assert "party" in result.output
    assert not (hub / "powerbi-semantic-model.zip").exists()


def test_confirm_emit_writes_zip_and_sha256_sidecar(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["package-powerbi-release", "--confirm-emit"])

    assert result.exit_code == 0, result.output
    assert "Packaged" in result.output
    zip_path = hub / "powerbi-semantic-model.zip"
    sidecar = hub / "powerbi-semantic-model.zip.sha256"
    assert zip_path.is_file()
    assert sidecar.is_file()

    recorded_digest = sidecar.read_text(encoding="utf-8").split()[0]
    assert recorded_digest == hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert recorded_digest in result.output

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert any(".SemanticModel/" in name for name in names)
        assert any(".Report/" in name for name in names)
        assert any(name.startswith("party/") for name in names)
        # Only the deployable item folders ship -- not the DDL/ERD/DAX/dbt/report JSON.
        assert not any(name.endswith("-gold-ddl.sql") for name in names)
        assert not any(name.endswith("-gold-product.json") for name in names)


def test_no_gold_configured_domain_produces_no_zip(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path, with_gold_ext=False)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["package-powerbi-release", "--confirm-emit"])

    assert result.exit_code == 0, result.output
    assert "nothing to package" in result.output
    assert not (hub / "powerbi-semantic-model.zip").exists()
    assert not (hub / "powerbi-semantic-model.zip.sha256").exists()


def test_custom_output_path_is_respected(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path)
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(
        cli, ["package-powerbi-release", "--confirm-emit", "--output", "dist/powerbi.zip"]
    )

    assert result.exit_code == 0, result.output
    assert (hub / "dist" / "powerbi.zip").is_file()
    assert (hub / "dist" / "powerbi.zip.sha256").is_file()


def test_blocked_compile_plan_fails_before_packaging(tmp_path, monkeypatch):
    hub = _copy_hub(tmp_path)
    binding = hub / "integration" / "bindings" / "customer.binding.yaml"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            "expression: customer_id", "expression: missing_customer_id"
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(hub)

    result = CliRunner().invoke(cli, ["package-powerbi-release"])

    assert result.exit_code != 0
    assert "compile plan is blocked" in result.output
