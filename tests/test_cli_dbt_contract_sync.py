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
            "--bronze-sources",
            "integration/sources",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 1
    assert "would_create: model" in result.output


def test_sync_command_is_skill_gated() -> None:
    assert _SKILL_COVERED_COMMANDS["sync-dbt-contracts"] == "kairos-develop-dbt-transformation"


# ---------------------------------------------------------------------------
# Terminology and provenance display (validation-operations)
# ---------------------------------------------------------------------------


def test_sync_command_uses_contract_synchronization_terminology(tmp_path: Path, monkeypatch) -> None:
    """User-facing output standardizes on 'contract synchronization', not the
    older abbreviated 'dbt contract sync' phrasing."""
    from kairos_ontology import __version__
    from kairos_ontology.core.dbt_contract_sync import DbtContractSyncReport

    def fake_sync(hub_root, **kwargs):
        return DbtContractSyncReport(
            Path(kwargs["transforms_dir"]),
            Path(kwargs["sources_dir"]),
            False,
            (),
            running_toolkit_version=__version__,
        )

    monkeypatch.setattr("kairos_ontology.core.dbt_contract_sync.sync_dbt_contracts", fake_sync)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli,
        [
            "sync-dbt-contracts",
            "--transforms",
            "custom/transforms",
            "--sources",
            "custom/sources",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 0, result.output
    assert "Contract synchronization" in result.output
    assert f"running toolkit v{__version__}" in result.output
    assert "dbt contract sync complete" not in result.output


def test_sync_command_shows_prior_generator_version_when_available(
    tmp_path: Path, monkeypatch
) -> None:
    """Drift output surfaces the prior artifact's own generator version, sourced
    only from that artifact's provenance stamp — never invented."""
    from kairos_ontology.core.dbt_contract_sync import (
        DbtContractSyncItem,
        DbtContractSyncReport,
    )

    output = tmp_path / "generated.ttl"

    def fake_sync(hub_root, **kwargs):
        return DbtContractSyncReport(
            Path(kwargs["transforms_dir"]),
            Path(kwargs["sources_dir"]),
            False,
            (
                DbtContractSyncItem(
                    "model", output, "stale", "updated",
                    prior_generator_version="4.6.0",
                ),
            ),
            running_toolkit_version="4.7.0rc6",
        )

    monkeypatch.setattr("kairos_ontology.core.dbt_contract_sync.sync_dbt_contracts", fake_sync)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli,
        [
            "sync-dbt-contracts",
            "--transforms",
            "custom/transforms",
            "--sources",
            "custom/sources",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 0, result.output
    assert "prior generator: v4.6.0" in result.output
    assert "running toolkit v4.7.0rc6" in result.output


def test_sync_command_omits_prior_generator_version_when_absent(
    tmp_path: Path, monkeypatch
) -> None:
    """No prior provenance stamp existed, so nothing is displayed for it —
    absence is not papered over with a fabricated value."""
    from kairos_ontology.core.dbt_contract_sync import (
        DbtContractSyncItem,
        DbtContractSyncReport,
    )

    output = tmp_path / "generated.ttl"

    def fake_sync(hub_root, **kwargs):
        return DbtContractSyncReport(
            Path(kwargs["transforms_dir"]),
            Path(kwargs["sources_dir"]),
            False,
            (DbtContractSyncItem("model", output, "missing", "created"),),
            running_toolkit_version="4.7.0rc6",
        )

    monkeypatch.setattr("kairos_ontology.core.dbt_contract_sync.sync_dbt_contracts", fake_sync)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        cli,
        [
            "sync-dbt-contracts",
            "--transforms",
            "custom/transforms",
            "--sources",
            "custom/sources",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )

    assert result.exit_code == 0, result.output
    assert "prior generator" not in result.output
