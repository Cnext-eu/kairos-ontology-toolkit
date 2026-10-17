# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The dbt target is the environment authority (DD-255, #1114)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.dbt_environment import (
    EnvironmentResolutionError,
    find_profiles_dir,
    load_dbt_target,
    load_kairos_vars,
    resolve_environment,
)
from kairos_ontology.core.fabric_api import FABRIC_API, FabricApiError, FabricClient
from kairos_ontology.core.projections.dbt.gold_connection import (
    UNRESOLVED_ONELAKE_URL,
    GoldConnectionEnvironmentSpec,
    GoldDirectLakeEnvironmentSpec,
)

GOLD_WS = "11111111-1111-1111-1111-111111111111"
OTHER_WS = "22222222-2222-2222-2222-222222222222"
MODELS_WS = "33333333-3333-3333-3333-333333333333"
WAREHOUSE = "44444444-4444-4444-4444-444444444444"
HOST = "abc123.datawarehouse.fabric.microsoft.com"


def _project(
    root: Path,
    targets: dict,
    *,
    kairos_vars: dict | None = None,
    profile: str = "platform",
) -> Path:
    project = {"name": "platform", "profile": profile}
    if kairos_vars is not None:
        project["vars"] = {"kairos": kairos_vars}
    (root / "dbt_project.yml").write_text(yaml.safe_dump(project), encoding="utf-8")
    (root / "profiles.yml").write_text(
        yaml.safe_dump({profile: {"target": "dev", "outputs": targets}}), encoding="utf-8"
    )
    return root


def _fabric(server: str = HOST, database: str = "gold_wh") -> dict:
    return {
        "type": "fabric",
        "server": server,
        "database": database,
        "schema": "dbo",
        "authentication": "environment",
    }


class FakeFabric:
    """Serves the two Fabric listings from dictionaries and records the calls."""

    def __init__(self, workspaces: dict[str, str], warehouses: dict[str, list[dict]]):
        self.workspaces = workspaces
        self.warehouses = warehouses
        self.calls: list[str] = []

    def __call__(self, url: str, token: str) -> dict:
        assert token == "token"
        self.calls.append(url)
        path = url.removeprefix(FABRIC_API)
        if path == "/workspaces":
            return {"value": [{"id": k, "displayName": v} for k, v in self.workspaces.items()]}
        workspace = path.split("/")[2]
        if workspace not in self.warehouses:
            raise FabricApiError(f"GET {url} failed: HTTP 403")
        return {"value": self.warehouses[workspace]}

    def client(self) -> FabricClient:
        return FabricClient(token="token", transport=self)


def _warehouse(item_id: str, name: str, host: str = HOST) -> dict:
    return {"id": item_id, "displayName": name, "properties": {"connectionString": host}}


@pytest.fixture
def fabric() -> FakeFabric:
    return FakeFabric(
        {GOLD_WS: "gdwh-dev", OTHER_WS: "sandbox", MODELS_WS: "gdwh-models-dev"},
        {
            GOLD_WS: [_warehouse(WAREHOUSE, "gold_wh"), _warehouse("x", "staging_wh")],
            OTHER_WS: [_warehouse("y", "gold_wh", host="other.datawarehouse.fabric.microsoft.com")],
        },
    )


class TestProfiles:
    def test_profiles_dir_follows_dbts_order(self, tmp_path):
        (tmp_path / "profiles.yml").write_text("{}", encoding="utf-8")
        assert find_profiles_dir(tmp_path, Path("x"), {}) == Path("x")
        assert find_profiles_dir(tmp_path, None, {"DBT_PROFILES_DIR": "y"}) == Path("y")
        assert find_profiles_dir(tmp_path, None, {}) == tmp_path
        assert find_profiles_dir(tmp_path / "none", None, {}) == Path.home() / ".dbt"

    def test_env_var_is_rendered_and_a_missing_one_is_named(self, tmp_path):
        _project(
            tmp_path,
            {"uat": _fabric(server="{{ env_var('UAT_SERVER') }}", database="{{ env_var('DB', 'gold_wh') }}")},
        )
        target = load_dbt_target(tmp_path, "UAT", environ={"UAT_SERVER": HOST})
        assert (target.key, target.get("server"), target.get("database")) == (
            "uat",
            HOST,
            "gold_wh",
        )
        with pytest.raises(EnvironmentResolutionError, match="env_var\\('UAT_SERVER'\\)"):
            load_dbt_target(tmp_path, "uat", environ={}).get("server")

    def test_only_env_var_jinja_is_supported(self, tmp_path):
        _project(tmp_path, {"dev": _fabric(server="{{ target.name }}.example")})
        with pytest.raises(EnvironmentResolutionError, match="beyond env_var"):
            load_dbt_target(tmp_path, "dev", environ={}).get("server")

    def test_an_unread_secret_never_blocks_resolution(self, tmp_path):
        """Only the fields resolution reads are rendered."""
        _project(tmp_path, {"dev": {**_fabric(), "password": "{{ env_var('NOT_SET') }}"}})
        assert load_dbt_target(tmp_path, "dev", environ={}).get("server") == HOST

    def test_scaffold_placeholders_and_missing_targets_fail_with_the_fix(self, tmp_path):
        _project(tmp_path, {"dev": _fabric(server="{your-dev-workspace}.datawarehouse")})
        with pytest.raises(EnvironmentResolutionError, match="scaffold placeholder"):
            load_dbt_target(tmp_path, "dev", environ={}).get("server")
        with pytest.raises(EnvironmentResolutionError, match="no target 'prod'.*Add it"):
            load_dbt_target(tmp_path, "prod", environ={})

    def test_targets_that_differ_only_in_case_are_ambiguous(self, tmp_path):
        _project(tmp_path, {"dev": _fabric(), "DEV": _fabric()})
        with pytest.raises(EnvironmentResolutionError, match="same environment"):
            load_dbt_target(tmp_path, "dev", environ={})


class TestKairosVars:
    def test_vars_are_keyed_by_normalised_environment(self, tmp_path):
        _project(
            tmp_path,
            {"dev": _fabric()},
            kairos_vars={"environments": {"DEV": {"models_workspace": "gdwh-models-dev"}}},
        )
        assert load_kairos_vars(tmp_path) == {"dev": {"models_workspace": "gdwh-models-dev"}}

    @pytest.mark.parametrize(
        ("kairos_vars", "match"),
        [
            ({"environment": {}}, "unknown key"),
            ({"environments": [{"dev": {}}]}, "mapping keyed by environment"),
            ({"environments": {"dev": {"models": "x"}}}, "allowed"),
            ({"environments": {"dev": {"models_workspace": ""}}}, "name or GUID"),
            ({"environments": {"dev": {}, "Dev": {}}}, "twice"),
        ],
    )
    def test_malformed_vars_are_rejected(self, tmp_path, kairos_vars, match):
        _project(tmp_path, {"dev": _fabric()}, kairos_vars=kairos_vars)
        with pytest.raises(EnvironmentResolutionError, match=match):
            load_kairos_vars(tmp_path)

    def test_no_vars_is_fine(self, tmp_path):
        _project(tmp_path, {"dev": _fabric()})
        assert load_kairos_vars(tmp_path) == {}


class TestResolveFabric:
    def test_the_warehouse_is_found_by_endpoint_and_name(self, tmp_path, fabric):
        _project(tmp_path, {"dev": _fabric(server=f"tcp:{HOST.upper()},1433")})

        resolved = resolve_environment(tmp_path, "dev", environ={}, client=fabric.client())

        assert (resolved.gold_workspace_id, resolved.gold_item_id) == (GOLD_WS, WAREHOUSE)
        # The models and reports workspaces default to the Gold workspace.
        assert resolved.models_workspace_id == resolved.reports_workspace_id == GOLD_WS
        assert "fabric-api" in resolved.sources["gold_item_id"]
        assert resolved.connection_override() == GoldDirectLakeEnvironmentSpec(
            name="dev", workspace_id=GOLD_WS, item_id=WAREHOUSE
        )

    def test_vars_name_the_models_workspace_and_hint_the_gold_one(self, tmp_path, fabric):
        _project(
            tmp_path,
            {"dev": _fabric()},
            kairos_vars={
                "environments": {
                    "dev": {"models_workspace": "gdwh-models-dev", "gold_workspace": "gdwh-dev"}
                }
            },
        )

        resolved = resolve_environment(tmp_path, "dev", environ={}, client=fabric.client())

        assert resolved.models_workspace_id == resolved.reports_workspace_id == MODELS_WS
        # The hint scoped the search to one workspace: no scan of the sandbox.
        assert not any(OTHER_WS in call for call in fabric.calls)

    def test_explicit_environment_variables_win_and_skip_the_api(self, tmp_path, fabric):
        _project(tmp_path, {"dev": _fabric()})
        environ = {
            "FABRIC_ITEM_ID": WAREHOUSE,
            "FABRIC_WORKSPACE_ID": MODELS_WS,
            "FABRIC_REPORTS_WORKSPACE_ID": OTHER_WS,
        }

        resolved = resolve_environment(tmp_path, "dev", environ=environ, client=fabric.client())

        # Legacy: without FABRIC_GOLD_WORKSPACE_ID the Gold workspace is FABRIC_WORKSPACE_ID.
        assert (resolved.gold_workspace_id, resolved.gold_item_id) == (MODELS_WS, WAREHOUSE)
        assert resolved.reports_workspace_id == OTHER_WS
        assert fabric.calls == []
        assert resolved.sources["gold_workspace_id"] == "env FABRIC_WORKSPACE_ID"

    def test_an_item_id_without_a_workspace_is_rejected(self, tmp_path, fabric):
        _project(tmp_path, {"dev": _fabric()})
        with pytest.raises(EnvironmentResolutionError, match="FABRIC_ITEM_ID is set without"):
            resolve_environment(
                tmp_path, "dev", environ={"FABRIC_ITEM_ID": WAREHOUSE}, client=fabric.client()
            )

    def test_no_match_lists_what_is_at_the_endpoint(self, tmp_path, fabric):
        _project(tmp_path, {"dev": _fabric(database="missing_wh")})
        with pytest.raises(EnvironmentResolutionError, match="'gold_wh', 'staging_wh'"):
            resolve_environment(tmp_path, "dev", environ={}, client=fabric.client())

    def test_two_matches_ask_for_a_hint(self, tmp_path, fabric):
        fabric.warehouses[OTHER_WS] = [_warehouse("z", "gold_wh")]
        _project(tmp_path, {"dev": _fabric()})
        with pytest.raises(EnvironmentResolutionError, match="gold_workspace to choose one"):
            resolve_environment(tmp_path, "dev", environ={}, client=fabric.client())

    def test_an_unknown_workspace_name_lists_the_visible_ones(self, tmp_path, fabric):
        _project(
            tmp_path,
            {"dev": _fabric()},
            kairos_vars={"environments": {"dev": {"models_workspace": "nope"}}},
        )
        with pytest.raises(EnvironmentResolutionError, match="visible: \\['gdwh-dev'"):
            resolve_environment(tmp_path, "dev", environ={}, client=fabric.client())

    def test_offline_checks_shape_without_calling_fabric(self, tmp_path, fabric):
        _project(
            tmp_path,
            {"dev": _fabric()},
            kairos_vars={"environments": {"dev": {"models_workspace": "gdwh-models-dev"}}},
        )

        resolved = resolve_environment(
            tmp_path, "dev", environ={}, client=fabric.client(), offline=True
        )

        assert fabric.calls == []
        assert resolved.gold_item_id is None and resolved.models_workspace_id is None
        assert "offline" in resolved.sources["gold_item_id"]
        assert "offline" in resolved.sources["models_workspace_id"]
        with pytest.raises(EnvironmentResolutionError, match="not resolved"):
            resolved.connection_override()

    def test_an_unsupported_adapter_is_rejected(self, tmp_path):
        _project(tmp_path, {"dev": {"type": "postgres", "host": "x"}})
        with pytest.raises(EnvironmentResolutionError, match="type 'postgres'"):
            resolve_environment(tmp_path, "dev", environ={}, offline=True)


class TestResolveDatabricks:
    def test_the_target_is_the_connection_and_no_api_is_called(self, tmp_path, fabric):
        _project(
            tmp_path,
            {
                "uat": {
                    "type": "databricks",
                    "host": "https://adb-3333.33.azuredatabricks.net/",
                    "http_path": "/sql/1.0/warehouses/uat0000",
                    "token": "{{ env_var('DBT_DATABRICKS_TOKEN') }}",
                }
            },
        )

        resolved = resolve_environment(
            tmp_path, "uat", environ={"FABRIC_WORKSPACE_ID": MODELS_WS}, client=fabric.client()
        )

        assert fabric.calls == []
        assert resolved.connection_override() == GoldConnectionEnvironmentSpec(
            name="uat",
            server_hostname="adb-3333.33.azuredatabricks.net",
            http_path="/sql/1.0/warehouses/uat0000",
        )
        assert resolved.models_workspace_id == MODELS_WS


class TestFabricClient:
    def test_pages_are_followed(self):
        pages = {
            f"{FABRIC_API}/workspaces": {"value": [{"id": "a"}], "continuationToken": "t 1"},
            f"{FABRIC_API}/workspaces?continuationToken=t%201": {"value": [{"id": "b"}]},
        }
        client = FabricClient(token="x", transport=lambda url, token: pages[url])
        assert [ws.id for ws in client.workspaces()] == ["a", "b"]

    def test_the_token_is_requested_once_and_lazily(self):
        calls = []

        def provider():
            calls.append(1)
            return "x"

        client = FabricClient(transport=lambda url, token: {"value": []}, token_provider=provider)
        assert calls == []
        client.workspaces()
        client.warehouses("w")
        assert calls == [1]


def _package(tmp_path: Path, parameter: dict) -> Path:
    package = tmp_path / "semantic-model"
    package.mkdir()
    (package / "parameter.yml").write_text(yaml.safe_dump(parameter), encoding="utf-8")
    return package


_UNRESOLVED = {
    "find_replace": [
        {"find_value": UNRESOLVED_ONELAKE_URL, "replace_value": {}, "item_type": "SemanticModel"}
    ]
}


class TestCli:
    def test_resolve_environment_prints_github_output(self, tmp_path, monkeypatch):
        _project(tmp_path, {"uat": _fabric()})
        monkeypatch.setenv("FABRIC_ITEM_ID", WAREHOUSE)
        monkeypatch.setenv("FABRIC_GOLD_WORKSPACE_ID", GOLD_WS)
        monkeypatch.delenv("FABRIC_WORKSPACE_ID", raising=False)
        monkeypatch.delenv("FABRIC_REPORTS_WORKSPACE_ID", raising=False)
        result = CliRunner().invoke(
            cli,
            [
                "resolve-environment", "--target", "UAT", "--project-dir", str(tmp_path),
                "--format", "github-output",
            ],
        )
        assert result.exit_code == 0, result.output
        lines = dict(line.split("=", 1) for line in result.output.strip().splitlines())
        assert lines["environment"] == "uat"
        assert lines["gold_item_id"] == WAREHOUSE
        assert lines["models_workspace_id"] == GOLD_WS

    def test_resolve_environment_offline_json_and_errors(self, tmp_path, monkeypatch):
        _project(tmp_path, {"dev": _fabric()})
        for name in ("FABRIC_ITEM_ID", "FABRIC_WORKSPACE_ID", "FABRIC_REPORTS_WORKSPACE_ID"):
            monkeypatch.delenv(name, raising=False)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["resolve-environment", "--target", "dev", "--project-dir", str(tmp_path),
             "--offline", "--format", "json"],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["sources"]["gold_item_id"].endswith("offline)")

        result = runner.invoke(
            cli, ["resolve-environment", "--target", "prod", "--project-dir", str(tmp_path)]
        )
        assert result.exit_code != 0
        assert "no target 'prod'" in result.output

    def test_apply_from_dbt_target_fills_a_hub_that_declares_nothing(self, tmp_path, monkeypatch):
        project = tmp_path / "platform"
        project.mkdir()
        _project(project, {"uat": _fabric()})
        package = _package(tmp_path, _UNRESOLVED)
        monkeypatch.setenv("FABRIC_ITEM_ID", WAREHOUSE)
        monkeypatch.setenv("FABRIC_WORKSPACE_ID", GOLD_WS)

        result = CliRunner().invoke(
            cli,
            ["apply-gold-connection", "--package-dir", str(package), "--from-dbt-target", "uat",
             "--project-dir", str(project)],
        )

        assert result.exit_code == 0, result.output
        assert "resolved from dbt target 'uat'" in result.output
        entry = yaml.safe_load((package / "parameter.yml").read_text("utf-8"))["find_replace"][0]
        assert entry["find_value"] == UNRESOLVED_ONELAKE_URL
        assert entry["replace_value"] == {
            "uat": f"https://onelake.dfs.fabric.microsoft.com/{GOLD_WS}/{WAREHOUSE}"
        }

    def test_a_hub_that_declares_nothing_fails_closed_without_a_target(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.chdir(tmp_path)
        package = _package(tmp_path, _UNRESOLVED)
        result = CliRunner().invoke(
            cli, ["apply-gold-connection", "--package-dir", str(package), "--environment", "dev"]
        )
        assert result.exit_code != 0
        assert "The hub declares no environments (DD-255)" in result.output
        assert "--from-dbt-target" in result.output

    def test_environment_and_target_must_agree(self, tmp_path, monkeypatch):
        _project(tmp_path, {"uat": _fabric()})
        monkeypatch.setenv("FABRIC_ITEM_ID", WAREHOUSE)
        monkeypatch.setenv("FABRIC_WORKSPACE_ID", GOLD_WS)
        package = _package(tmp_path, _UNRESOLVED)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["apply-gold-connection", "--package-dir", str(package), "--environment", "prod",
             "--from-dbt-target", "uat", "--project-dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "different environments" in result.output

        result = runner.invoke(cli, ["apply-gold-connection", "--package-dir", str(package)])
        assert result.exit_code != 0
        assert "--from-dbt-target" in result.output
