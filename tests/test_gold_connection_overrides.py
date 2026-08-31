# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Direct Lake connection: scaffolded shape, placeholder rejection, and the deploy-time
override seam the dataplatform supplies (issues #662, #663)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.projections.dbt.gold_connection import (
    GoldConnectionOverrideError,
    apply_gold_connection_override,
    parse_gold_connection_overrides,
    parse_gold_direct_lake_connection,
)
from kairos_ontology.core.projections.dbt.gold_specs import GoldContractError

_SCAFFOLD = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "kairos_ontology"
    / "scaffold"
    / "ontology-hub"
    / "kairos.yaml.template"
)
_REAL_WS = "11111111-1111-1111-1111-111111111111"
_REAL_LH = "22222222-2222-2222-2222-222222222222"
_DEFAULT_URL = f"https://onelake.dfs.fabric.microsoft.com/{_REAL_WS}/{_REAL_LH}"


def _uncommented_gold_block() -> dict:
    """Uncomment the scaffold's commented ``gold:`` example, exactly as a user would."""
    lines = _SCAFFOLD.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "# gold:")
    block = []
    for line in lines[start:]:
        if not line.startswith("#"):
            break
        block.append(re.sub(r"^# ?", "", line))
    text = "\n".join(block)
    # Fill the <...> guidance placeholders with real GUIDs, as the comment instructs.
    text = re.sub(r"<[^>]*workspace GUID>", _REAL_WS, text)
    text = re.sub(r"<[^>]*lakehouse GUID>", _REAL_LH, text)
    return yaml.safe_load(text)


def test_scaffolded_gold_example_parses_when_uncommented():
    """The scaffolded example must round-trip through the parser that consumes it.

    It shipped ``environments`` as a list of ``- name: dev`` entries while the parser
    requires a mapping keyed by environment name, so every fresh hub's first attempt at
    configuring Gold failed on a verbatim copy of its own template (issue #663).
    """
    connection = parse_gold_direct_lake_connection(_uncommented_gold_block())

    assert connection is not None
    assert connection.default_environment == "dev"
    assert sorted(item.name for item in connection.environments) == ["dev", "prod"]
    assert connection.default.workspace_id == _REAL_WS


def test_wrong_list_shape_error_shows_the_correct_shape():
    """The diagnostic must be self-correcting, not just name the symptom."""
    document = yaml.safe_load(
        "gold:\n"
        "  direct_lake_connection:\n"
        "    environments:\n"
        "      - name: dev\n"
        f"        workspace_id: {_REAL_WS}\n"
    )
    with pytest.raises(GoldContractError) as excinfo:
        parse_gold_direct_lake_connection(document)

    message = str(excinfo.value)
    assert "must be a non-empty mapping" in message
    assert "expected shape:" in message
    assert "not a list of" in message


def test_all_zero_placeholder_guid_is_rejected():
    """A GUID-shaped placeholder passes format validation but ships an undeployable model."""
    document = yaml.safe_load(
        "gold:\n"
        "  direct_lake_connection:\n"
        "    environments:\n"
        "      dev:\n"
        "        workspace_id: 00000000-0000-0000-0000-000000000000\n"
        "        lakehouse_id: 00000000-0000-0000-0000-000000000000\n"
    )
    with pytest.raises(GoldContractError, match="all-zero placeholder"):
        parse_gold_direct_lake_connection(document)


def _parameter_yaml(environments: dict[str, str]) -> str:
    return yaml.safe_dump(
        {
            "find_replace": [
                {
                    "find_value": _DEFAULT_URL,
                    "replace_value": dict(environments),
                    "item_type": "SemanticModel",
                }
            ]
        },
        sort_keys=False,
    )


def test_override_rewrites_only_the_target_environment_and_preserves_find_value():
    """``find_value`` is the hub's byte-for-byte TMDL string and must never be overridden.

    fabric-cicd matches it as a literal substring; a dataplatform-supplied value would
    silently fail to match and leave the model on the hub's default workspace (#662).
    """
    overrides = parse_gold_connection_overrides(
        yaml.safe_load(
            "environments:\n"
            "  PROD:\n"
            "    workspace_id: ${FABRIC_PROD_WS}\n"
            "    lakehouse_id: 44444444-4444-4444-4444-444444444444\n"
        ),
        {"FABRIC_PROD_WS": "33333333-3333-3333-3333-333333333333"},
    )

    rewritten, previous, new_url = apply_gold_connection_override(
        _parameter_yaml({"DEV": _DEFAULT_URL, "PROD": _DEFAULT_URL}),
        "PROD",
        overrides["PROD"],
    )

    entry = yaml.safe_load(rewritten)["find_replace"][0]
    assert entry["find_value"] == _DEFAULT_URL
    assert entry["replace_value"]["DEV"] == _DEFAULT_URL
    assert entry["replace_value"]["PROD"] == new_url
    assert previous == _DEFAULT_URL
    assert new_url == (
        "https://onelake.dfs.fabric.microsoft.com/"
        "33333333-3333-3333-3333-333333333333/44444444-4444-4444-4444-444444444444"
    )


def test_override_rejects_placeholder_and_unset_variables():
    with pytest.raises(GoldConnectionOverrideError, match="all-zero placeholder"):
        parse_gold_connection_overrides(
            yaml.safe_load(
                "environments:\n"
                "  DEV:\n"
                "    workspace_id: 00000000-0000-0000-0000-000000000000\n"
                "    lakehouse_id: 00000000-0000-0000-0000-000000000000\n"
            ),
            {},
        )

    with pytest.raises(GoldConnectionOverrideError, match="unset or empty"):
        parse_gold_connection_overrides(
            yaml.safe_load(
                "environments:\n"
                "  DEV:\n"
                "    workspace_id: ${NOT_SET_ANYWHERE}\n"
                f"    lakehouse_id: {_REAL_LH}\n"
            ),
            {},
        )


def test_override_rejects_the_wrong_list_shape():
    with pytest.raises(GoldConnectionOverrideError, match="mapping keyed by environment"):
        parse_gold_connection_overrides(
            yaml.safe_load(f"environments:\n  - name: DEV\n    workspace_id: {_REAL_WS}\n"),
            {},
        )


def test_cli_is_a_clean_no_op_without_config_or_matching_environment(tmp_path, monkeypatch):
    """Existing repos with no override file must be entirely unaffected."""
    monkeypatch.chdir(tmp_path)
    package = tmp_path / "semantic-model"
    package.mkdir()
    original = _parameter_yaml({"DEV": _DEFAULT_URL})
    (package / "parameter.yml").write_text(original, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["apply-gold-connection", "--package-dir", "semantic-model", "--environment", "DEV"],
    )
    assert result.exit_code == 0, result.output
    assert "using the hub's own Direct Lake connection" in result.output
    assert (package / "parameter.yml").read_text(encoding="utf-8") == original

    config = tmp_path / "overrides.yml"
    config.write_text(
        f"environments:\n  UAT:\n    workspace_id: {_REAL_WS}\n    lakehouse_id: {_REAL_LH}\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        cli,
        [
            "apply-gold-connection",
            "--package-dir",
            "semantic-model",
            "--environment",
            "PROD",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "declares no 'PROD' environment" in result.output
    assert (package / "parameter.yml").read_text(encoding="utf-8") == original


def test_cli_applies_override_and_logs_before_after(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    package = tmp_path / "semantic-model"
    package.mkdir()
    (package / "parameter.yml").write_text(_parameter_yaml({"DEV": _DEFAULT_URL}), encoding="utf-8")
    config = tmp_path / ".github" / "fabric" / "gold-connections.yml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "environments:\n"
        "  DEV:\n"
        "    workspace_id: 55555555-5555-5555-5555-555555555555\n"
        "    lakehouse_id: 66666666-6666-6666-6666-666666666666\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        cli,
        ["apply-gold-connection", "--package-dir", "semantic-model", "--environment", "DEV"],
    )

    assert result.exit_code == 0, result.output
    assert "before:" in result.output and "after:" in result.output
    document = yaml.safe_load((package / "parameter.yml").read_text(encoding="utf-8"))
    entry = document["find_replace"][0]
    assert entry["find_value"] == _DEFAULT_URL
    assert entry["replace_value"]["DEV"] == (
        "https://onelake.dfs.fabric.microsoft.com/"
        "55555555-5555-5555-5555-555555555555/66666666-6666-6666-6666-666666666666"
    )
