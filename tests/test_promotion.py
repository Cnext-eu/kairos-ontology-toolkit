# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""One commit promoted through dev -> uat -> prod (DD-256, #1114)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.hub_release_lock import (
    HUB_RELEASE_LOCK_PATH,
    HubReleaseLock,
    HubReleaseLockError,
    check_lock_matches_pin,
    parse_hub_release_lock,
    read_hub_release_lock,
    render_hub_release_lock,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
OTHER_SHA = "fedcba9876543210fedcba9876543210fedcba98"
ARCHIVE = "a" * 64
_SCAFFOLD = Path(__file__).resolve().parents[1] / "src" / "kairos_ontology" / "scaffold"
_WORKFLOWS = _SCAFFOLD / "dataplatform" / ".github" / "workflows"

_PACKAGES = """packages:
  - git: "https://github.com/acme/customer-ontology-hub.git"
    revision: "{sha}"
    subdirectory: ontology-hub-publish/medallion/dbt
"""


def _platform(root: Path, *, pinned: str = SHA, lock: HubReleaseLock | None = None) -> Path:
    (root / "packages.yml").write_text(_PACKAGES.format(sha=pinned), encoding="utf-8")
    (root / "dbt_project.yml").write_text(
        yaml.safe_dump({"name": "platform", "profile": "platform"}), encoding="utf-8"
    )
    targets = {
        name: {
            "type": "fabric",
            "server": f"{name}.datawarehouse.fabric.microsoft.com",
            "database": "gold_wh",
        }
        for name in ("dev", "uat", "prod")
    }
    (root / "profiles.yml").write_text(
        yaml.safe_dump({"platform": {"target": "dev", "outputs": targets}}), encoding="utf-8"
    )
    if lock is not None:
        (root / HUB_RELEASE_LOCK_PATH).write_text(render_hub_release_lock(lock), "utf-8")
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    for name in ("deploy-powerbi-semantic-model.yml", "promote.yml"):
        (workflows / name).write_text(
            (_WORKFLOWS / f"{name}.template").read_text(encoding="utf-8"), encoding="utf-8"
        )
    return root


class TestLock:
    def test_render_and_parse_round_trip(self, tmp_path):
        lock = HubReleaseLock(tag="v1.4.0", hub_sha=SHA, archive_sha256=ARCHIVE)
        (tmp_path / HUB_RELEASE_LOCK_PATH).write_text(render_hub_release_lock(lock), "utf-8")
        assert read_hub_release_lock(tmp_path) == lock
        assert read_hub_release_lock(tmp_path / "none") is None

    @pytest.mark.parametrize(
        ("text", "match"),
        [
            ("- tag\n", "mapping"),
            (f"tag: v1\nhub_sha: {SHA}\narchive_sha256: {ARCHIVE}\nextra: 1\n", "unknown"),
            (f"tag: v1\nhub_sha: abc\narchive_sha256: {ARCHIVE}\n", "40-character"),
            (f"tag: v1\nhub_sha: {SHA}\narchive_sha256: abc\n", "SHA-256"),
            (f"tag: ''\nhub_sha: {SHA}\narchive_sha256: {ARCHIVE}\n", "release tag"),
        ],
    )
    def test_malformed_locks_are_rejected(self, text, match):
        with pytest.raises(HubReleaseLockError, match=match):
            parse_hub_release_lock(text)

    def test_the_lock_must_name_the_pinned_commit(self):
        lock = HubReleaseLock(tag="v1.4.0", hub_sha=SHA, archive_sha256=ARCHIVE)
        check_lock_matches_pin(lock, SHA.upper())
        with pytest.raises(HubReleaseLockError, match="different hub commits"):
            check_lock_matches_pin(lock, OTHER_SHA)


class TestBumpHub:
    @patch("kairos_ontology.cli.operations._fetch_hub_release_archive_sha256", return_value=ARCHIVE)
    @patch("kairos_ontology.cli.operations._resolve_hub_ref_sha", return_value=SHA)
    def test_a_release_tag_writes_the_lock_beside_the_pin(self, _sha, _archive, tmp_path, monkeypatch):
        _platform(tmp_path, pinned=OTHER_SHA)
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["bump-hub", "v1.4.0"])

        assert result.exit_code == 0, result.output
        assert read_hub_release_lock(tmp_path) == HubReleaseLock("v1.4.0", SHA, ARCHIVE)
        assert f'revision: "{SHA}"' in (tmp_path / "packages.yml").read_text("utf-8")
        assert "Wrote hub-release.lock" in result.output

    @patch("kairos_ontology.cli.operations._fetch_hub_release_archive_sha256", return_value=None)
    @patch("kairos_ontology.cli.operations._resolve_hub_ref_sha", return_value=OTHER_SHA)
    def test_a_branch_leaves_the_lock_and_warns_it_is_stale(self, _sha, _archive, tmp_path, monkeypatch):
        lock = HubReleaseLock("v1.4.0", SHA, ARCHIVE)
        _platform(tmp_path, lock=lock)
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(cli, ["bump-hub", "main"])

        assert result.exit_code == 0, result.output
        assert read_hub_release_lock(tmp_path) == lock
        assert "still deploys v1.4.0" in result.output
        assert "fails closed" in result.output


def _invoke(*args: str):
    return CliRunner().invoke(cli, list(args))


class TestHubReleaseCommand:
    def test_without_a_lock_only_dbt_is_promoted(self, tmp_path):
        _platform(tmp_path)
        result = _invoke("hub-release", "--project-dir", str(tmp_path), "--format", "github-output")
        assert result.exit_code == 0, result.output
        assert result.output.strip() == "deploy=false"

    def test_a_consistent_lock_is_printed_for_the_workflow(self, tmp_path):
        _platform(tmp_path, lock=HubReleaseLock("v1.4.0", SHA, ARCHIVE))
        result = _invoke("hub-release", "--project-dir", str(tmp_path), "--format", "github-output")
        assert result.exit_code == 0, result.output
        assert dict(line.split("=", 1) for line in result.output.split()) == {
            "deploy": "true",
            "hub_release_tag": "v1.4.0",
            "expected_hub_sha": SHA,
            "expected_archive_sha256": ARCHIVE,
        }

    def test_a_lock_for_another_hub_commit_fails(self, tmp_path):
        _platform(tmp_path, pinned=OTHER_SHA, lock=HubReleaseLock("v1.4.0", SHA, ARCHIVE))
        result = _invoke("hub-release", "--project-dir", str(tmp_path))
        assert result.exit_code != 0
        assert "bump-hub" in result.output


class TestCheckEnvironments:
    def test_a_ready_platform_passes(self, tmp_path):
        _platform(tmp_path, lock=HubReleaseLock("v1.4.0", SHA, ARCHIVE))
        with patch(
            "kairos_ontology.cli.environment._github_environments",
            return_value={"dev", "uat", "prod"},
        ):
            result = _invoke(
                "check-environments", "--project-dir", str(tmp_path), "--github-repo", "acme/dp"
            )
        assert result.exit_code == 0, result.output
        assert "All environments can be promoted." in result.output
        assert "✓ uat (fabric)" in result.output

    def test_problems_name_their_fix(self, tmp_path):
        _platform(tmp_path, pinned=OTHER_SHA, lock=HubReleaseLock("v1.4.0", SHA, ARCHIVE))
        profile = yaml.safe_load((tmp_path / "profiles.yml").read_text("utf-8"))
        profile["platform"]["outputs"]["prod"]["server"] = "{your-prod-workspace}.example"
        del profile["platform"]["outputs"]["uat"]
        (tmp_path / "profiles.yml").write_text(yaml.safe_dump(profile), encoding="utf-8")
        (tmp_path / "dbt_project.yml").write_text(
            yaml.safe_dump(
                {
                    "name": "platform",
                    "profile": "platform",
                    "vars": {"kairos": {"environments": {"qa": {"models_workspace": "x"}}}},
                }
            ),
            encoding="utf-8",
        )
        with patch("kairos_ontology.cli.environment._github_environments", return_value={"dev"}):
            result = _invoke(
                "check-environments", "--project-dir", str(tmp_path), "--github-repo", "acme/dp"
            )

        assert result.exit_code != 0
        assert "prod: " in result.output and "scaffold placeholder" in result.output
        assert "vars.kairos.environments.qa names no dbt target" in result.output
        assert "different hub commits" in result.output
        assert "no GitHub Environment 'prod'" in result.output
        assert "repo:acme/dp:environment:prod" in result.output
        assert "KAIROS_PROMOTION_PATH" in result.output  # uat is missing from the path

    def test_an_endpoint_read_from_an_env_var_is_named_as_the_problem(self, tmp_path):
        """The deploy passes dbt no GitHub Environment variable, so the endpoint is unset.

        `resolve-environment --offline` still defers it (a local `.env` may set it), but the
        promotion check fails with the fix: the endpoint belongs in profiles.yml.
        """
        _platform(tmp_path)
        profile = yaml.safe_load((tmp_path / "profiles.yml").read_text("utf-8"))
        for output in profile["platform"]["outputs"].values():
            output["server"] = "{{ env_var('FABRIC_SERVER') }}"
        (tmp_path / "profiles.yml").write_text(yaml.safe_dump(profile), encoding="utf-8")

        result = _invoke("check-environments", "--project-dir", str(tmp_path))

        assert result.exit_code != 0
        assert "uat: the endpoint reads FABRIC_SERVER" in result.output
        assert "write the 'uat' target's endpoint into profiles.yml" in result.output
        offline = _invoke(
            "resolve-environment", "--target", "uat", "--project-dir", str(tmp_path), "--offline"
        )
        assert offline.exit_code == 0, offline.output
        # Online (as the deploy runs) an unset variable still fails.
        online = _invoke(
            "resolve-environment", "--target", "uat", "--project-dir", str(tmp_path)
        )
        assert online.exit_code != 0
        assert "env_var('FABRIC_SERVER')" in online.output

    def test_a_deploy_workflow_promote_cannot_call_is_a_problem(self, tmp_path):
        """A frozen, customized deploy copy has no workflow_call: promote.yml would fail."""
        _platform(tmp_path)
        (tmp_path / ".github" / "workflows" / "deploy-powerbi-semantic-model.yml").write_text(
            "on:\n  workflow_dispatch: {}\njobs: {}\n", encoding="utf-8"
        )
        result = _invoke("check-environments", "--project-dir", str(tmp_path))
        assert result.exit_code != 0
        assert "no `workflow_call` trigger" in result.output
        assert "customized-workflows" in result.output

    def test_a_github_enterprise_repo_is_queried_on_its_host(self, tmp_path):
        from kairos_ontology.cli.environment import _split_github_repo

        assert _split_github_repo("ghe.example/acme/dp", tmp_path) == ("ghe.example", "acme/dp")
        completed = type("Done", (), {"stdout": "https://ghe.example/acme/dp.git\n"})()
        with patch("subprocess.run", return_value=completed):
            assert _split_github_repo("acme/dp", tmp_path) == ("ghe.example", "acme/dp")
            assert _split_github_repo("acme/other", tmp_path) == ("github.com", "acme/other")

    def test_no_profile_says_how_to_start(self, tmp_path):
        (tmp_path / "dbt_project.yml").write_text("name: p\nprofile: p\n", encoding="utf-8")
        result = _invoke("check-environments", "--project-dir", str(tmp_path))
        assert result.exit_code != 0
        assert "one target per environment" in result.output


def _workflow(name: str) -> dict:
    text = (_WORKFLOWS / name).read_text(encoding="utf-8")
    return yaml.safe_load(text.replace("{DBT_CI_PROFILE_YAML}", "          ci: {}"))


class TestPromoteWorkflow:
    def test_one_pinned_commit_goes_through_each_environment_in_order(self):
        workflow = _workflow("promote.yml.template")
        triggers = workflow[True]
        assert triggers["push"] == {"branches": ["main"]}
        assert "ref" in triggers["workflow_dispatch"]["inputs"]
        jobs = workflow["jobs"]
        assert list(jobs) == ["pin", "dev", "uat", "prod"]
        for name, needs in (("dev", "pin"), ("uat", ["pin", "dev"]), ("prod", ["pin", "uat"])):
            job = jobs[name]
            assert job["needs"] == needs
            assert job["uses"] == "./.github/workflows/deploy-powerbi-semantic-model.yml"
            assert job["with"] == {
                "target_environment": name,
                "ref": "${{ needs.pin.outputs.sha }}",
                "build_dbt": True,
            }
            assert job["secrets"] == "inherit"
            assert f"',{name},'" in job["if"]
        for name in ("uat", "prod"):
            assert "!failure() && !cancelled()" in jobs[name]["if"]

    def test_the_pin_resolves_a_full_sha_and_the_path_variable(self):
        step = _workflow("promote.yml.template")["jobs"]["pin"]["steps"][0]
        assert "gh api" in step["run"] and "[0-9a-f]{40}" in step["run"]
        assert step["env"]["PROMOTION_PATH"] == "${{ vars.KAIROS_PROMOTION_PATH || 'dev,uat,prod' }}"

    def test_the_deploy_workflow_is_callable_with_the_dispatch_inputs(self):
        triggers = _workflow("deploy-powerbi-semantic-model.yml.template")[True]
        called = set(triggers["workflow_call"]["inputs"])
        dispatched = set(triggers["workflow_dispatch"]["inputs"])
        assert called == dispatched
        assert {"target_environment", "ref", "build_dbt"} <= called

    def test_the_deploy_builds_dbt_before_publishing_in_one_job(self):
        workflow = _workflow("deploy-powerbi-semantic-model.yml.template")
        steps = workflow["jobs"]["deploy"]["steps"]
        names = [step.get("name", step.get("uses", "")) for step in steps]
        order = [
            "Resolve the hub release to deploy",
            "Azure login (service principal)",
            "Resolve the environment from its dbt target",
            "dbt build (target environment)",
            "Download semantic model package from ontology-hub release",
            "Apply the environment's Gold connection",
            "Publish semantic model and report to Fabric workspace",
        ]
        assert [names.index(name) for name in order] == sorted(names.index(n) for n in order)
        checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v4")
        assert checkout["with"]["ref"] == "${{ inputs.ref || github.sha }}"
        build = steps[names.index("dbt build (target environment)")]
        assert build["if"] == "${{ inputs.build_dbt }}"
        assert "--profiles-dir . --target \"$TARGET_ENVIRONMENT\"" in build["run"]
        assert "'environment' || 'cli'" in build["env"]["DBT_FABRIC_AUTHENTICATION"]
        apply = steps[names.index("Apply the environment's Gold connection")]
        assert "--from-dbt-target" in apply["run"] and "--environment" in apply["run"]
        assert workflow["jobs"]["deploy"]["concurrency"]["cancel-in-progress"] is False

    def test_pr_validate_checks_the_lock(self):
        steps = _workflow("pr-validate.yml.template")["jobs"]["validate"]["steps"]
        (step,) = [s for s in steps if s.get("name", "").startswith("Check hub-release.lock")]
        assert step["run"] == "uv run --no-sync kairos-ontology hub-release"


class TestHubAccessAndAzureLogin:
    """Fracht's frozen deploy did these two things the managed template could not (DD-256)."""

    @pytest.mark.parametrize(
        ("name", "job"),
        [("deploy-powerbi-semantic-model.yml.template", "deploy"), ("pr-validate.yml.template", "validate")],
    )
    def test_a_github_app_can_replace_the_hub_token(self, name, job):
        text = (_WORKFLOWS / name).read_text(encoding="utf-8")
        steps = _workflow(name)["jobs"][job]["steps"]
        (app,) = [s for s in steps if s.get("id") == "hub_app"]
        assert app["uses"] == "actions/create-github-app-token@v3"
        assert app["if"] == "${{ vars.KAIROS_HUB_APP_CLIENT_ID != '' }}"
        assert app["with"]["private-key"] == "${{ secrets.KAIROS_HUB_APP_PRIVATE_KEY }}"
        # Every use of the hub token prefers the App's, and HUB_REPO_TOKEN still works alone.
        assert "secrets.HUB_REPO_TOKEN }}" in text
        assert text.count("${{ secrets.HUB_REPO_TOKEN }}") == 0
        names = [s.get("name", "") for s in steps]
        assert names.index("Mint a hub repository token from the GitHub App") < names.index(
            "Authenticate to the hub package repository"
        )

    def test_azure_ids_are_read_from_variables_first(self):
        steps = _workflow("deploy-powerbi-semantic-model.yml.template")["jobs"]["deploy"]["steps"]
        (login,) = [s for s in steps if s.get("uses") == "azure/login@v2"]
        assert login["with"]["client-id"] == "${{ vars.AZURE_CLIENT_ID || secrets.AZURE_CLIENT_ID }}"
        assert login["with"]["tenant-id"] == "${{ vars.AZURE_TENANT_ID || secrets.AZURE_TENANT_ID }}"



class TestShellVariablesSurviveRendering:
    """#1114: `${HUB_REPO}` in the deploy workflow became `$<hub repo>` on every render."""

    TEMPLATE = (
        'env:\n  HUB_REPO: "{HUB_REPO}"\n'
        'run: gh api "repos/${HUB_ORG}/${HUB_REPO}/commits/x" # {ORG}\n'
    )

    def test_render_leaves_shell_variables_alone(self):
        from kairos_ontology.cli.workflow_refresh import render

        rendered = render(self.TEMPLATE, {"HUB_REPO": "hub", "ORG": "acme"})
        assert 'HUB_REPO: "hub"' in rendered
        assert "repos/${HUB_ORG}/${HUB_REPO}/commits" in rendered
        assert "# acme" in rendered

    def test_a_correct_rendering_is_current_and_the_legacy_one_is_repaired(self, tmp_path):
        from kairos_ontology.cli.workflow_refresh import classify, render

        target = tmp_path / "deploy.yml"
        target.write_text(render(self.TEMPLATE, {"HUB_REPO": "hub", "ORG": "acme"}), "utf-8")
        current = classify(target, self.TEMPLATE)
        assert current.state == "current"
        assert current.substitutions == {"HUB_REPO": "hub", "ORG": "acme"}

        legacy = self.TEMPLATE.replace("{HUB_REPO}", "hub").replace("{ORG}", "acme")
        target.write_text(legacy, encoding="utf-8")
        outdated = classify(target, self.TEMPLATE)
        assert outdated.state == "outdated" and outdated.refreshable
        assert outdated.substitutions == {"HUB_REPO": "hub", "ORG": "acme"}
        assert "${HUB_REPO}" in render(self.TEMPLATE, outdated.substitutions)

    def test_init_dataplatform_keeps_the_deploy_workflows_shell_variables(self):
        from kairos_ontology.cli.setup import _render_scaffold

        text = (_WORKFLOWS / "deploy-powerbi-semantic-model.yml.template").read_text("utf-8")
        rendered = _render_scaffold(text, {"{ORG}": "acme", "{HUB_REPO}": "hub"})
        assert '--repo "${HUB_ORG}/${HUB_REPO}"' in rendered
        assert 'HUB_REPO: "hub"' in rendered and 'HUB_ORG: "acme"' in rendered

    def test_a_missing_deploy_workflow_is_installed_from_the_pin(self, tmp_path):
        from kairos_ontology.cli.operations import _derived_workflow_substitutions

        _platform(tmp_path)
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = ["dbt-fabric>=1.11"]\n', encoding="utf-8"
        )
        derived = _derived_workflow_substitutions(tmp_path)
        assert derived["ORG"] == "acme" and derived["HUB_REPO"] == "customer-ontology-hub"
        assert "DBT_CI_PROFILE_YAML" in derived
