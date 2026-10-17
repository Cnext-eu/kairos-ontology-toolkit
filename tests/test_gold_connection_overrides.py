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
    text = re.sub(r"<[^>]*(?:lakehouse|Warehouse) GUID>", _REAL_LH, text)
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
        _parameter_yaml({"dev": _DEFAULT_URL, "prod": _DEFAULT_URL}),
        "PROD",
        overrides["prod"],
    )

    entry = yaml.safe_load(rewritten)["find_replace"][0]
    assert entry["find_value"] == _DEFAULT_URL
    assert entry["replace_value"]["dev"] == _DEFAULT_URL
    assert entry["replace_value"]["prod"] == new_url
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
    """Existing repos with no override file are unaffected for a declared environment."""
    monkeypatch.chdir(tmp_path)
    package = tmp_path / "semantic-model"
    package.mkdir()
    original = _parameter_yaml({"dev": _DEFAULT_URL, "prod": _DEFAULT_URL})
    (package / "parameter.yml").write_text(original, encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["apply-gold-connection", "--package-dir", "semantic-model", "--environment", "DEV"],
    )
    assert result.exit_code == 0, result.output
    assert "using the hub's own connection" in result.output
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
    assert "declares no 'prod' environment" in result.output
    assert (package / "parameter.yml").read_text(encoding="utf-8") == original


def test_cli_fails_closed_on_an_environment_parameter_yml_does_not_declare(tmp_path, monkeypatch):
    """#993: fabric-cicd skips an undeclared environment and deploys the default one."""
    monkeypatch.chdir(tmp_path)
    package = tmp_path / "semantic-model"
    package.mkdir()
    (package / "parameter.yml").write_text(_parameter_yaml({"dev": _DEFAULT_URL}), encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        ["apply-gold-connection", "--package-dir", "semantic-model", "--environment", "uat"],
    )
    assert result.exit_code != 0
    assert "does not declare the 'uat' environment" in result.output
    assert "['dev']" in result.output


def test_an_older_hubs_uppercase_keys_are_lowercased_and_logged(tmp_path, monkeypatch):
    """#1114: a `DEV`/`dev` casing mismatch used to fail; keys are now case-insensitive."""
    monkeypatch.chdir(tmp_path)
    package = tmp_path / "semantic-model"
    package.mkdir()
    (package / "parameter.yml").write_text(
        _parameter_yaml({"DEV": _DEFAULT_URL, "PROD": _DEFAULT_URL}), encoding="utf-8"
    )

    result = CliRunner().invoke(
        cli,
        ["apply-gold-connection", "--package-dir", "semantic-model", "--environment", "Dev"],
    )

    assert result.exit_code == 0, result.output
    assert "Lowercased parameter.yml environment key(s) ['DEV', 'PROD']" in result.output
    entry = yaml.safe_load((package / "parameter.yml").read_text(encoding="utf-8"))
    assert set(entry["find_replace"][0]["replace_value"]) == {"dev", "prod"}


def test_keys_that_differ_only_in_case_fail_closed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    package = tmp_path / "semantic-model"
    package.mkdir()
    (package / "parameter.yml").write_text(
        _parameter_yaml({"DEV": _DEFAULT_URL, "dev": _DEFAULT_URL}), encoding="utf-8"
    )
    result = CliRunner().invoke(
        cli,
        ["apply-gold-connection", "--package-dir", "semantic-model", "--environment", "dev"],
    )
    assert result.exit_code != 0
    assert "twice under different casing" in result.output

    with pytest.raises(GoldConnectionOverrideError, match="are the same environment"):
        parse_gold_connection_overrides(
            {
                "environments": {
                    "DEV": {"workspace_id": _REAL_WS, "item_id": _REAL_LH},
                    "dev": {"workspace_id": _REAL_WS, "item_id": _REAL_LH},
                }
            },
            {},
        )


def test_cli_fails_closed_without_parameter_yml(tmp_path, monkeypatch):
    """#993: an archive without it deployed the default workspace to every environment."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "semantic-model").mkdir()
    result = CliRunner().invoke(
        cli,
        ["apply-gold-connection", "--package-dir", "semantic-model", "--environment", "DEV"],
    )
    assert result.exit_code != 0
    assert "re-release the hub" in result.output


def test_an_override_can_add_an_environment_the_hub_never_declared(tmp_path, monkeypatch):
    """The dataplatform's own environment, resolved from the deploy environment, passes."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", _REAL_WS)
    monkeypatch.setenv("FABRIC_ITEM_ID", _REAL_LH)
    package = tmp_path / "semantic-model"
    package.mkdir()
    (package / "parameter.yml").write_text(_parameter_yaml({"DEV": _DEFAULT_URL}), encoding="utf-8")
    config = tmp_path / "overrides.yml"
    config.write_text(
        "environments:\n  UAT:\n"
        '    workspace_id: "${FABRIC_WORKSPACE_ID}"\n'
        '    lakehouse_id: "${FABRIC_ITEM_ID}"\n',
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        cli,
        [
            "apply-gold-connection",
            "--package-dir",
            "semantic-model",
            "--environment",
            "UAT",
            "--config",
            str(config),
        ],
    )
    assert result.exit_code == 0, result.output
    assert f"{_REAL_WS}/{_REAL_LH}" in (package / "parameter.yml").read_text(encoding="utf-8")


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
    assert entry["replace_value"]["dev"] == (
        "https://onelake.dfs.fabric.microsoft.com/"
        "55555555-5555-5555-5555-555555555555/66666666-6666-6666-6666-666666666666"
    )


def test_only_the_target_environment_is_resolved():
    """#993: a DEV deploy must not fail on PROD's unset ${VAR}."""
    document = {
        "environments": {
            "DEV": {"workspace_id": _REAL_WS, "lakehouse_id": _REAL_LH},
            "PROD": {"workspace_id": "${UNSET_WS}", "lakehouse_id": "${UNSET_ITEM}"},
        }
    }
    resolved = parse_gold_connection_overrides(document, {}, only="DEV")
    assert set(resolved) == {"dev"}
    with pytest.raises(GoldConnectionOverrideError):
        parse_gold_connection_overrides(document, {}, only="PROD")


class TestItemId:
    """DD-239: the Fabric item Gold lives in -- for fabric-warehouse, the Warehouse."""

    def test_item_id_is_the_key_and_renders_the_same_url(self):
        from kairos_ontology.core.projections.dbt.gold_connection import _direct_lake_environment

        spec = _direct_lake_environment("PROD", {"workspace_id": _REAL_WS, "item_id": _REAL_LH})
        assert spec.item_id == _REAL_LH
        assert spec.lakehouse_id == _REAL_LH  # deprecated read alias

    def test_lakehouse_id_still_parses_with_a_deprecation_warning(self):
        from kairos_ontology.core.projections.dbt.gold_connection import _direct_lake_environment

        with pytest.warns(FutureWarning, match="rename it to 'item_id'"):
            spec = _direct_lake_environment(
                "PROD", {"workspace_id": _REAL_WS, "lakehouse_id": _REAL_LH}
            )
        assert spec.item_id == _REAL_LH

    def test_both_names_at_once_are_rejected(self):
        from kairos_ontology.core.projections.dbt.gold_connection import _direct_lake_environment

        with pytest.raises(GoldContractError, match="both 'item_id'"):
            _direct_lake_environment(
                "PROD",
                {"workspace_id": _REAL_WS, "item_id": _REAL_LH, "lakehouse_id": _REAL_LH},
            )

    def test_the_override_file_accepts_item_id(self):
        document = {"environments": {"UAT": {"workspace_id": "${WS}", "item_id": "${ITEM}"}}}
        resolved = parse_gold_connection_overrides(
            document, {"WS": _REAL_WS, "ITEM": _REAL_LH}, only="UAT"
        )
        assert resolved["uat"].item_id == _REAL_LH


class TestEnvironmentKeys:
    """#1114: one spelling of an environment key across hub, dataplatform and deploy."""

    def test_hub_keys_and_default_are_lowercased(self):
        document = {
            "gold": {
                "direct_lake_connection": {
                    "default_environment": "DEV",
                    "environments": {
                        "DEV": {"workspace_id": _REAL_WS, "item_id": _REAL_LH},
                        " Prod ": {"workspace_id": _REAL_WS, "item_id": _REAL_LH},
                    },
                }
            }
        }
        connection = parse_gold_direct_lake_connection(document)
        assert connection.default_environment == "dev"
        assert [item.name for item in connection.environments] == ["dev", "prod"]

    def test_hub_keys_that_differ_only_in_case_are_rejected(self):
        from kairos_ontology.core.projections.dbt.gold_connection import (
            parse_gold_databricks_connection,
        )

        environment = {"server_hostname": "adb-1.1.azuredatabricks.net", "http_path": "/sql/x"}
        document = {
            "gold": {
                "databricks_connection": {
                    "default_environment": "dev",
                    "environments": {"dev": environment, "DEV": environment},
                }
            }
        }
        with pytest.raises(GoldContractError, match="are the same environment"):
            parse_gold_databricks_connection(document)


def _databricks_parameter_yaml() -> str:
    from kairos_ontology.core.projections.dbt.gold_connection import (
        parse_gold_databricks_connection,
    )
    from kairos_ontology.core.projections.dbt.gold_render import _parameter_yaml as render

    connection = parse_gold_databricks_connection(
        {
            "gold": {
                "databricks_connection": {
                    "environments": {
                        "DEV": {
                            "server_hostname": "adb-1111.11.azuredatabricks.net",
                            "http_path": "/sql/1.0/warehouses/dev0000",
                        }
                    }
                }
            }
        }
    )
    return render(connection)


class TestDatabricksOverride:
    """#1114: an override rewrites only the entries of its own kind."""

    def test_databricks_override_rewrites_each_field_with_its_own_value(self):
        overrides = parse_gold_connection_overrides(
            {
                "environments": {
                    "UAT": {
                        "server_hostname": "adb-3333.33.azuredatabricks.net",
                        "http_path": "/sql/1.0/warehouses/uat0000",
                    }
                }
            },
            {},
        )
        rewritten, previous, new = apply_gold_connection_override(
            _databricks_parameter_yaml(), "uat", overrides["uat"]
        )

        entries = yaml.safe_load(rewritten)["find_replace"]
        by_find = {entry["find_value"]: entry["replace_value"] for entry in entries}
        assert by_find["adb-1111.11.azuredatabricks.net"]["uat"] == (
            "adb-3333.33.azuredatabricks.net"
        )
        assert by_find["/sql/1.0/warehouses/dev0000"]["uat"] == "/sql/1.0/warehouses/uat0000"
        assert "onelake" not in rewritten
        assert previous == ""
        assert new == "adb-3333.33.azuredatabricks.net, /sql/1.0/warehouses/uat0000"

    def test_a_direct_lake_override_against_a_databricks_model_fails_closed(self):
        """The old override wrote a OneLake URL into the hostname and HTTP path."""
        overrides = parse_gold_connection_overrides(
            {"environments": {"uat": {"workspace_id": _REAL_WS, "item_id": _REAL_LH}}}, {}
        )
        with pytest.raises(GoldConnectionOverrideError, match="other kind of semantic model"):
            apply_gold_connection_override(
                _databricks_parameter_yaml(), "uat", overrides["uat"]
            )

    def test_a_databricks_override_against_a_direct_lake_model_fails_closed(self):
        overrides = parse_gold_connection_overrides(
            {
                "environments": {
                    "uat": {"server_hostname": "adb-3.3.azuredatabricks.net", "http_path": "/x"}
                }
            },
            {},
        )
        with pytest.raises(GoldConnectionOverrideError, match="other kind of semantic model"):
            apply_gold_connection_override(
                _parameter_yaml({"dev": _DEFAULT_URL}), "uat", overrides["uat"]
            )

    def test_mixed_and_unknown_keys_are_rejected(self):
        with pytest.raises(GoldConnectionOverrideError, match="mixes Direct Lake keys"):
            parse_gold_connection_overrides(
                {
                    "environments": {
                        "uat": {"workspace_id": _REAL_WS, "http_path": "/sql/1.0/warehouses/x"}
                    }
                },
                {},
            )
        with pytest.raises(GoldConnectionOverrideError, match="unknown key"):
            parse_gold_connection_overrides(
                {"environments": {"uat": {"workspace": _REAL_WS}}}, {}
            )
