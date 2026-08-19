# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the update --upgrade CLI command.

Covers the Windows lock-file handling and the post-upgrade re-exec that refreshes
managed files under the newly-installed toolkit version (instead of the stale
in-process module).
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.cli.shared import _read_hub_channel

SCAFFOLD_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "kairos_ontology"
    / "scaffold"
    / "pyproject.toml.template"
)


@pytest.fixture
def runner():
    return CliRunner()


def _make_scaffolded_hub_pyproject(tmp_path: Path, version: str = "v3.8.0") -> Path:
    """Render the shipped scaffold template — one URL, bare extras (issue #297)."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        SCAFFOLD_TEMPLATE.read_text(encoding="utf-8")
        .replace("{repo_name}", "test-hub")
        .replace("{description}", "test-hub")
        .replace("{toolkit_ref}", version)
        .replace("{toolkit_version}", version.lstrip("v"))
        .replace("{toolkit_channel}", "preview")
        .replace("{refmodels_ref}", "v0.1.0")
        .replace("{refmodels_version}", "0.1.0"),
        encoding="utf-8",
    )
    return pyproject


def _make_hub_pyproject(tmp_path: Path, version: str = "v3.8.0") -> Path:
    """Create a minimal pyproject.toml with a toolkit dependency pin."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "test-hub"\n\ndependencies = [\n'
        f'  "kairos-ontology-toolkit @ https://github.com/Cnext-eu/'
        f"kairos-ontology-toolkit/releases/download/{version}/"
        f'kairos_ontology_toolkit-0.0.0-py3-none-any.whl",\n]\n\n'
        '[tool.kairos]\nchannel = "preview"\n',
        encoding="utf-8",
    )
    return pyproject


def _make_hub_pyproject_with_extras(tmp_path: Path, version: str = "v3.8.0") -> Path:
    """Create a pyproject.toml with a primary pin AND a [flatfile] extras pin."""
    pyproject = tmp_path / "pyproject.toml"
    whl = (
        "https://github.com/Cnext-eu/kairos-ontology-toolkit/releases/download/"
        f"{version}/kairos_ontology_toolkit-0.0.0-py3-none-any.whl"
    )
    pyproject.write_text(
        '[project]\nname = "test-hub"\n\ndependencies = [\n'
        f'  "kairos-ontology-toolkit @ {whl}",\n]\n\n'
        "[project.optional-dependencies]\n"
        f'flatfile = [\n  "kairos-ontology-toolkit[flatfile] @ {whl}",\n]\n\n'
        '[tool.kairos]\nchannel = "preview"\n',
        encoding="utf-8",
    )
    return pyproject


class TestUpdateUpgradeWindows:
    """Tests for the Windows-specific uv sync skip during --upgrade."""

    @patch("kairos_ontology.cli.main.subprocess.Popen")
    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_windows_skips_uv_sync(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, mock_popen, runner, tmp_path
    ):
        """On Windows, uv sync should be skipped after uv lock succeeds."""
        _make_hub_pyproject(tmp_path)
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "win32"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["uv", "lock"] in calls
        assert ["uv", "sync"] not in calls

    @patch("kairos_ontology.cli.main.os.getpid", return_value=4242)
    @patch("kairos_ontology.cli.main.subprocess.Popen")
    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_windows_schedules_detached_refresh(
        self,
        mock_run,
        mock_scaffold,
        mock_channel,
        mock_resolve,
        mock_popen,
        mock_getpid,
        runner,
        tmp_path,
    ):
        """On Windows, the refresh is scheduled as a detached helper (not a blocking
        re-exec), waiting on the parent PID so the .exe lock is released first."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "win32"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0
        # The blocking re-exec must NOT have been used on Windows.
        run_calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["uv", "run", "kairos-ontology", "update"] not in run_calls
        # In-process managed refresh must NOT have run (detached helper owns it).
        mock_scaffold.assert_not_called()
        # A detached helper was scheduled with the parent PID + sync + refresh.
        mock_popen.assert_called_once()
        ps_cmd = mock_popen.call_args[0][0]
        assert ps_cmd[0] == "powershell"
        script = ps_cmd[-1]
        assert "Wait-Process -Id 4242" in script
        assert "uv sync" in script
        assert "uv run kairos-ontology update" in script
        # CREATE_NEW_CONSOLE flag (0x10) is set.
        assert mock_popen.call_args.kwargs["creationflags"] & 0x00000010

    @patch("kairos_ontology.cli.main.os.getpid", return_value=4242)
    @patch("kairos_ontology.cli.main.subprocess.Popen")
    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_windows_detached_refresh_propagates_check(
        self,
        mock_run,
        mock_scaffold,
        mock_channel,
        mock_resolve,
        mock_popen,
        mock_getpid,
        runner,
        tmp_path,
    ):
        """`--upgrade --check` schedules the refresh with `update --check`."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "win32"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade", "--check"])

        assert result.exit_code == 0
        mock_popen.assert_called_once()
        script = mock_popen.call_args[0][0][-1]
        assert "uv run kairos-ontology update --force-managed --check" in script

    @patch("kairos_ontology.cli.main.subprocess.Popen", side_effect=OSError("boom"))
    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_windows_detached_fallback_on_oserror(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, mock_popen, runner, tmp_path
    ):
        """If the detached helper cannot be launched, print manual guidance and exit 1."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "win32"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 1
        assert "uv run kairos-ontology update" in result.output
        mock_scaffold.assert_not_called()

    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_non_windows_runs_uv_sync(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """On non-Windows, uv sync should still be called after uv lock."""
        _make_hub_pyproject(tmp_path)
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0
        assert "Upgraded to v3.9.0-rc.2" in result.output
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["uv", "lock"] in calls
        assert ["uv", "sync"] in calls


class TestUpdateUpgradeReexec:
    """The post-upgrade refresh must re-exec under the NEW toolkit version."""

    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_reexec_refresh_when_version_changed(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """When the target version differs, refresh is re-run via `uv run`,
        and the stale in-process managed refresh is skipped."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["uv", "run", "kairos-ontology", "update", "--force-managed"] in calls
        # In-process managed refresh must NOT have run (re-exec owns it now).
        mock_scaffold.assert_not_called()

    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_reexec_propagates_check_flag(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """`--upgrade --check` re-execs the refresh with --check appended."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade", "--check"])

        assert result.exit_code == 0
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert [
            "uv",
            "run",
            "kairos-ontology",
            "update",
            "--force-managed",
            "--check",
        ] in calls

    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_reexec_exit_code_propagates(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """A non-zero re-exec (e.g. drift under --check) propagates the exit code."""

        def _run(cmd, *args, **kwargs):
            if cmd[:4] == ["uv", "run", "kairos-ontology", "update"]:
                return MagicMock(returncode=1)
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = _run

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade", "--check"])

        assert result.exit_code == 1

    @patch("kairos_ontology.cli.operations._toolkit_version", "3.9.0rc2")
    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_no_reexec_when_version_unchanged(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """A no-op upgrade (target == running) runs the in-process refresh,
        with no re-exec (guards against recursion)."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["uv", "run", "kairos-ontology", "update"] not in calls
        # In-process refresh ran (it consulted the managed map).
        mock_scaffold.assert_called()


class TestUpdateHubRootResolution:
    """update must operate on the real managed root, never scaffold a second hub (DD-062)."""

    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_upgrade_reroots_from_subdirectory(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path, monkeypatch
    ):
        """Run from a content subdir → re-roots up and updates the parent's pin."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _make_hub_pyproject(tmp_path)
        subdir = tmp_path / "ontology-hub" / "model"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)

        with patch("sys.platform", "linux"):
            result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0
        assert "Detected hub root" in result.output
        # The parent pin was updated; no spurious pyproject in the subdir.
        assert "v3.9.0-rc.2" in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
        assert not (subdir / "pyproject.toml").exists()

    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_upgrade_refuses_when_no_hub(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path, monkeypatch
    ):
        """No pin / managed .github anywhere → hard-error, no fabrication."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        workdir = tmp_path / "not-a-hub"
        workdir.mkdir()
        monkeypatch.chdir(workdir)

        with patch("sys.platform", "linux"):
            result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 1
        assert "No ontology hub found" in result.output
        assert not (workdir / "pyproject.toml").exists()

    @patch("subprocess.run")
    def test_plain_update_still_works_in_subdir(self, mock_run, runner, tmp_path, monkeypatch):
        """Plain refresh from a content subdir re-roots to the parent hub."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _make_hub_pyproject(tmp_path)
        subdir = tmp_path / "ontology-hub" / "model"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)

        result = runner.invoke(cli, ["update", "--check"])

        assert "Detected hub root" in result.output
        # No spurious .github created in the content subdir.
        assert not (subdir / ".github").exists()


class TestUpdateUpgradeLegacyExtrasPins:
    """Back-compat for *legacy* hubs (scaffolded before toolkit 5.2) whose
    ``[project.optional-dependencies]`` still repeat the wheel URL per extra.

    Hubs scaffolded today declare the URL once and their extras as bare
    requirements (issue #297) — that shape is covered by
    ``TestUpdateUpgradeSingleUrlHub`` below and by
    ``tests/test_scaffold_toolkit_pin.py``.  These two tests exist because such
    legacy hubs are still in the field: `--upgrade` once rewrote only the primary
    pin, leaving extras pins on the old version, which made `uv lock` fail with
    conflicting URLs for the same package.  The fixture is hand-built, not
    rendered from the shipped template, precisely so it keeps that old shape.
    """

    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_legacy_extras_pin_is_rewritten_and_marker_preserved(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """Both the primary and the [flatfile] extras pin get the new version,
        and the ``[flatfile]`` extras marker is preserved."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject_with_extras(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])
                text = Path("pyproject.toml").read_text(encoding="utf-8")

        assert result.exit_code == 0
        # New version present on both pins; old version fully gone.
        assert "0.0.0-py3-none-any.whl" not in text
        assert text.count("3.9.0rc2-py3-none-any.whl") == 2
        assert text.count("/download/v3.9.0-rc.2/") == 2
        # The extras marker survived the rewrite.
        assert "kairos-ontology-toolkit[flatfile] @ " in text

    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_plain_only_pin_still_rewritten(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """A plain (no-extras) pin is still rewritten (no false negatives)."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])
                text = Path("pyproject.toml").read_text(encoding="utf-8")

        assert result.exit_code == 0
        assert "3.9.0rc2-py3-none-any.whl" in text
        assert "0.0.0-py3-none-any.whl" not in text


class TestUpdateUpgradeSingleUrlHub:
    """A hub scaffolded today carries the toolkit URL once (issue #297)."""

    @patch("kairos_ontology.cli.operations._upgrade_refmodels")
    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_upgrade_rewrites_the_single_url_and_leaves_bare_extras(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, mock_upgrade_refmodels,
        runner, tmp_path
    ):
        """The reference-models upgrade (DD-200) is exercised in its own test class
        below; mocked out to a no-op here so this stays scoped to the toolkit pin."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_scaffolded_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])
                text = Path("pyproject.toml").read_text(encoding="utf-8")

        assert result.exit_code == 0, result.output
        assert text.count("py3-none-any.whl") == 2
        assert text.count("3.9.0rc2-py3-none-any.whl") == 1
        assert text.count("0.1.0-py3-none-any.whl") == 1
        assert '"kairos-ontology-toolkit[flatfile]"' in text
        mock_upgrade_refmodels.assert_called_once_with(None)


class TestUpdateUpgradeAlsoUpgradesRefmodels:
    """`update --upgrade` also upgrades the reference-models pin, non-atomically
    with the toolkit upgrade, but never silently (issue #551, DD-200)."""

    @patch("kairos_ontology.cli.operations._upgrade_refmodels")
    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_hub_with_a_refmodels_pin_gets_it_upgraded_too(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, mock_upgrade_refmodels,
        runner, tmp_path
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_scaffolded_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0, result.output
        mock_upgrade_refmodels.assert_called_once_with(None)

    @patch("kairos_ontology.cli.operations._upgrade_refmodels")
    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_hub_with_no_refmodels_pin_is_never_touched(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, mock_upgrade_refmodels,
        runner, tmp_path
    ):
        """A dataplatform repo (dbt only) never pins reference-models at all --
        the upgrade must not be attempted, let alone fail, on its behalf."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 0, result.output
        mock_upgrade_refmodels.assert_not_called()

    @patch("kairos_ontology.cli.operations._upgrade_refmodels")
    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_refmodels_upgrade_failure_is_reported_and_exits_nonzero(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, mock_upgrade_refmodels,
        runner, tmp_path
    ):
        """The toolkit half already succeeded (its own pin is rewritten on disk);
        a refmodels failure must be named, not silently swallowed or conflated
        with the (unrelated) managed-file-refresh failure path."""
        import click

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_upgrade_refmodels.side_effect = click.ClickException("uv pip install failed: 404")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_scaffolded_hub_pyproject(Path.cwd())
                result = runner.invoke(cli, ["update", "--upgrade"])
                text = Path("pyproject.toml").read_text(encoding="utf-8")

        assert result.exit_code != 0
        assert "reference-models upgrade failed" in result.output
        assert "uv pip install failed: 404" in result.output
        # The toolkit pin rewrite that already happened is not rolled back.
        assert "3.9.0rc2-py3-none-any.whl" in text


class TestUpdateUpgradeDowngradeGuard:
    """`--upgrade` must never silently move the pin backwards.

    Every release after v5.0.2 was published as a pre-release, so the ``stable``
    channel resolves to v5.0.2: a hub pinned to a current pre-release would
    otherwise be downgraded into a toolkit predating its own scaffold.
    """

    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="stable")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_refuses_to_downgrade_the_pin(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd(), version="v4.5.0")
                result = runner.invoke(cli, ["update", "--upgrade"])
                text = Path("pyproject.toml").read_text(encoding="utf-8")

        assert result.exit_code == 1
        # Both versions and the escape hatch are named.
        assert "3.9.0rc2" in result.output
        assert "4.5.0" in result.output
        assert "--allow-downgrade" in result.output
        # The pin is untouched and nothing was locked or synced.
        assert "/download/v4.5.0/" in text
        assert ["uv", "lock"] not in [c[0][0] for c in mock_run.call_args_list]

    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="stable")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_allow_downgrade_proceeds(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd(), version="v4.5.0")
                result = runner.invoke(cli, ["update", "--upgrade", "--allow-downgrade"])
                text = Path("pyproject.toml").read_text(encoding="utf-8")

        assert result.exit_code == 0, result.output
        assert "/download/v3.9.0-rc.2/" in text

    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0-rc.2")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="preview")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_pre_release_ordering_uses_packaging_not_strings(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        """v3.10.0 → v3.9.0-rc.2 is a downgrade, though "3.10" < "3.9" as strings."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd(), version="v3.10.0")
                result = runner.invoke(cli, ["update", "--upgrade"])

        assert result.exit_code == 1
        assert "--allow-downgrade" in result.output

    @patch("kairos_ontology.cli.operations._resolve_channel", return_value="v3.9.0")
    @patch("kairos_ontology.cli.operations._read_hub_channel", return_value="stable")
    @patch("kairos_ontology.cli.operations._managed_scaffold_map", return_value={})
    @patch("subprocess.run")
    def test_upgrade_from_pre_release_to_final_is_allowed(
        self, mock_run, mock_scaffold, mock_channel, mock_resolve, runner, tmp_path
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        with patch("sys.platform", "linux"):
            with runner.isolated_filesystem(temp_dir=tmp_path):
                _make_hub_pyproject(Path.cwd(), version="v3.9.0-rc.2")
                result = runner.invoke(cli, ["update", "--upgrade"])
                text = Path("pyproject.toml").read_text(encoding="utf-8")

        assert result.exit_code == 0, result.output
        assert "/download/v3.9.0/" in text

    def test_allow_downgrade_requires_upgrade(self, runner):
        result = runner.invoke(cli, ["update", "--allow-downgrade"])

        assert result.exit_code == 2
        assert "--allow-downgrade only applies to --upgrade" in result.output


class TestReadHubChannel:
    """`_read_hub_channel` feeds the upgrade target, so a wrong answer picks the
    wrong version."""

    def test_commented_out_channel_does_not_win(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "hub"\n\n[tool.kairos]\n# channel = "preview"\nchannel = "stable"\n',
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        assert _read_hub_channel() == "stable"

    def test_reads_the_real_channel(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "hub"\n\n[tool.kairos]\nchannel = "preview"\n', encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)

        assert _read_hub_channel() == "preview"

    def test_defaults_to_stable_without_pyproject_or_key(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert _read_hub_channel() == "stable"

        (tmp_path / "pyproject.toml").write_text('[project]\nname = "hub"\n', encoding="utf-8")
        assert _read_hub_channel() == "stable"

    def test_falls_back_to_a_line_scan_for_broken_toml(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text(
            '[project\nname = broken\n[tool.kairos]\n# channel = "stable"\nchannel = "preview"\n',
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)

        assert _read_hub_channel() == "preview"
