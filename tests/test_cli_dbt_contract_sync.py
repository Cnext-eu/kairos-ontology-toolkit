# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Minimal CLI tests for sync-dbt-contracts."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import _SKILL_COVERED_COMMANDS, cli


def test_sync_command_noops_for_existing_hub_without_transforms(tmp_path: Path) -> None:
    hub = tmp_path / "ontology-hub"
    (hub / "integration").mkdir(parents=True)

    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["sync-dbt-contracts"])

    assert result.exit_code == 0, result.output
    assert "nothing to synchronize" in result.output


def test_sync_command_check_exits_nonzero_on_drift(tmp_path: Path, monkeypatch) -> None:
    from kairos_ontology.core.dbt_contract_sync import (
        DbtContractSyncItem,
        DbtContractSyncReport,
    )

    output = tmp_path / "generated.ttl"

    def fake_sync(hub_root, **kwargs):
        return DbtContractSyncReport(
            Path(kwargs["transforms_dir"]),
            Path(kwargs["sources_dir"]),
            True,
            (DbtContractSyncItem("model", output, "missing", "would_create"),),
        )

    monkeypatch.setattr("kairos_ontology.core.dbt_contract_sync.sync_dbt_contracts", fake_sync)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli,
        [
            "sync-dbt-contracts",
            "--check",
            "--transforms",
            "custom/transforms",
            "--sources",
            "custom/sources",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 1
    assert "would_create: model" in result.output


def test_sync_command_is_skill_gated() -> None:
    assert _SKILL_COVERED_COMMANDS["sync-dbt-contracts"] == "kairos-develop-dbt-transformation"
