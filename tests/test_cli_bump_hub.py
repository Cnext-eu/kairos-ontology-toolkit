# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for the `bump-hub` CLI command (DD-206 §12 item 4).

Mirrors ``tests/test_cli_test_ref_helpers.py``'s structure: the resolve helper is
a sibling of ``_resolve_toolkit_ref_sha`` and the rewrite helper is a sibling of
``_rewrite_toolkit_dependency_source``, so the same mocking and assertion shapes
apply, adapted to packages.yml instead of pyproject.toml.
"""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import (
    _HubPackagePin,
    _parse_hub_package_pin,
    _resolve_hub_ref_sha,
    _rewrite_hub_package_pin,
    cli,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
SHA_2 = "abcdef0123456789abcdef0123456789abcdef01"

SCAFFOLD_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "kairos_ontology"
    / "scaffold"
    / "dataplatform"
    / "packages.yml.template"
)


def _scaffolded_packages_yml(org: str = "acme", repo: str = "customer-ontology-hub") -> str:
    """Render the shipped dataplatform scaffold template exactly as init-dataplatform does."""
    return (
        SCAFFOLD_TEMPLATE.read_text(encoding="utf-8")
        .replace("{ORG}", org)
        .replace("{HUB_REPO}", repo)
        .replace("{HUB_VERSION}", "v1.0.0")
    )


# --- _parse_hub_package_pin -------------------------------------------------


def test_parse_hub_package_pin_reads_fresh_commented_scaffold():
    pin = _parse_hub_package_pin(_scaffolded_packages_yml())

    assert pin == _HubPackagePin(
        org_repo="acme/customer-ontology-hub",
        previous_revision="v1.0.0",
        was_commented=True,
    )


def test_parse_hub_package_pin_reads_active_pin():
    active = _rewrite_hub_package_pin(_scaffolded_packages_yml(), SHA)

    pin = _parse_hub_package_pin(active)

    assert pin == _HubPackagePin(
        org_repo="acme/customer-ontology-hub", previous_revision=SHA, was_commented=False
    )


def test_parse_hub_package_pin_rejects_missing_block():
    with pytest.raises(ValueError, match="could not find the hub package block"):
        _parse_hub_package_pin("packages:\n  - package: dbt_utils\n    version: 1.0.0\n")


# --- _rewrite_hub_package_pin ------------------------------------------------


def test_rewrite_uncomments_and_pins_fresh_scaffold():
    content = _scaffolded_packages_yml()

    rewritten = _rewrite_hub_package_pin(content, SHA)

    assert "  # - git:" not in rewritten
    assert '  - git: "https://github.com/acme/customer-ontology-hub.git"' in rewritten
    assert f'    revision: "{SHA}"' in rewritten
    assert "    subdirectory: ontology-hub-publish/medallion/dbt" in rewritten
    # Unrelated lines (header comments, transitive-dependency notes) are untouched.
    assert "# IMPORTANT: Uncomment the package below" in rewritten
    assert "# - dbt_utils" in rewritten

    parsed = yaml.safe_load(rewritten)
    assert parsed["packages"][0] == {
        "git": "https://github.com/acme/customer-ontology-hub.git",
        "revision": SHA,
        "subdirectory": "ontology-hub-publish/medallion/dbt",
    }


def test_rewrite_is_idempotent_across_repeated_bumps():
    once = _rewrite_hub_package_pin(_scaffolded_packages_yml(), SHA)
    twice = _rewrite_hub_package_pin(once, SHA_2)

    assert once.count("- git:") == 1
    assert twice.count("- git:") == 1
    assert f'revision: "{SHA}"' not in twice
    assert f'revision: "{SHA_2}"' in twice
    parsed = yaml.safe_load(twice)
    assert parsed["packages"][0]["revision"] == SHA_2
    # Re-bumping does not re-duplicate or re-comment the block.
    assert twice.count("subdirectory: ontology-hub-publish/medallion/dbt") == 1


def test_rewrite_normalizes_sha_case_and_whitespace():
    rewritten = _rewrite_hub_package_pin(_scaffolded_packages_yml(), f"  {SHA.upper()}  ")

    assert f'revision: "{SHA}"' in rewritten


def test_rewrite_rejects_non_sha_revision():
    with pytest.raises(ValueError, match="40-character"):
        _rewrite_hub_package_pin(_scaffolded_packages_yml(), "v1.4.0")


def test_rewrite_preserves_crlf_line_endings():
    content = _scaffolded_packages_yml().replace("\n", "\r\n")

    rewritten = _rewrite_hub_package_pin(content, SHA)

    assert f'    revision: "{SHA}"\r\n' in rewritten
    assert "\r\n\r\n" not in rewritten.split(f'revision: "{SHA}"')[0][-4:]
    # Lines outside the rewritten block keep their original CRLF endings.
    assert "# - dbt_utils\r\n" in rewritten


# --- _resolve_hub_ref_sha ----------------------------------------------------


@patch("kairos_ontology.cli.main.subprocess.run")
def test_resolve_hub_ref_sha_validates_and_encodes_ref(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout=SHA.upper() + "\n")

    assert _resolve_hub_ref_sha(" feature/test ref ", "acme/customer-ontology-hub") == SHA
    called_command = mock_run.call_args.args[0]
    assert called_command[2] == "/repos/acme/customer-ontology-hub/commits/feature%2Ftest%20ref"

    mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
    assert _resolve_hub_ref_sha("main", "acme/customer-ontology-hub") is None


@pytest.mark.parametrize(
    ("result", "side_effect"),
    [
        (MagicMock(returncode=1, stdout="", stderr="not found"), None),
        (MagicMock(returncode=0, stdout="abc123\n", stderr=""), None),
        (None, FileNotFoundError("gh")),
        (None, subprocess.TimeoutExpired(["gh", "api"], 15)),
    ],
)
@patch("kairos_ontology.cli.main.subprocess.run")
def test_resolve_hub_ref_sha_rejects_invalid_or_unavailable_refs(mock_run, result, side_effect):
    mock_run.return_value = result
    mock_run.side_effect = side_effect

    assert _resolve_hub_ref_sha("missing-ref", "acme/customer-ontology-hub") is None


def test_resolve_hub_ref_sha_rejects_blank_ref():
    assert _resolve_hub_ref_sha("   ", "acme/customer-ontology-hub") is None


# --- `bump-hub` CLI command --------------------------------------------------


@patch("kairos_ontology.cli.operations._resolve_hub_ref_sha", return_value=SHA)
def test_bump_hub_first_use_uncomments_and_pins(mock_resolve, tmp_path, monkeypatch):
    packages = tmp_path / "packages.yml"
    packages.write_text(_scaffolded_packages_yml(), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["bump-hub", "v1.4.0"])

    assert result.exit_code == 0, result.output
    assert "Uncommented and pinned" in result.output
    assert "acme/customer-ontology-hub" in result.output
    assert SHA in result.output
    assert "v1.0.0" in result.output  # previous (placeholder) value echoed for review
    mock_resolve.assert_called_once_with("v1.4.0", "acme/customer-ontology-hub")
    written = packages.read_text(encoding="utf-8")
    assert f'revision: "{SHA}"' in written
    assert "  # - git:" not in written


@patch("kairos_ontology.cli.operations._resolve_hub_ref_sha", return_value=SHA_2)
def test_bump_hub_subsequent_bump_updates_revision_in_place(mock_resolve, tmp_path, monkeypatch):
    packages = tmp_path / "packages.yml"
    packages.write_text(_rewrite_hub_package_pin(_scaffolded_packages_yml(), SHA), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["bump-hub", "main"])

    assert result.exit_code == 0, result.output
    assert "Updated" in result.output
    assert "Uncommented" not in result.output
    assert SHA in result.output  # previous SHA echoed
    assert SHA_2 in result.output  # new SHA echoed
    written = packages.read_text(encoding="utf-8")
    assert f'revision: "{SHA_2}"' in written
    assert SHA not in written.replace(SHA_2, "")


@patch("kairos_ontology.cli.operations._resolve_hub_ref_sha", return_value=None)
def test_bump_hub_fails_closed_when_ref_cannot_be_resolved(mock_resolve, tmp_path, monkeypatch):
    packages = tmp_path / "packages.yml"
    original = _scaffolded_packages_yml()
    packages.write_text(original, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["bump-hub", "does-not-exist"])

    assert result.exit_code == 1
    assert "Could not resolve hub ref" in result.output
    assert packages.read_text(encoding="utf-8") == original


def test_bump_hub_fails_closed_when_packages_yml_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["bump-hub", "v1.0.0"])

    assert result.exit_code == 1
    assert "packages.yml" in result.output
    assert "not found" in result.output


def test_bump_hub_fails_closed_when_hub_block_missing(tmp_path, monkeypatch):
    packages = tmp_path / "packages.yml"
    packages.write_text("packages:\n  - package: dbt_utils\n    version: 1.0.0\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["bump-hub", "v1.0.0"])

    assert result.exit_code == 1
    assert "could not find the hub package block" in result.output
