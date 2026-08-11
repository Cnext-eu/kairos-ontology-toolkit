# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Focused tests for unreleased toolkit test-ref helper logic."""

from pathlib import Path
import shutil
import subprocess
import tomllib
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import (
    _ToolkitTestRefState,
    _add_toolkit_test_ref_state,
    _dependency_files_transaction,
    _read_toolkit_test_ref_state,
    _remove_toolkit_test_ref_state,
    _resolve_toolkit_ref_sha,
    _schedule_windows_refresh,
    _rewrite_toolkit_dependency_source,
    _single_toolkit_dependency_source,
    _toolkit_git_sha_source,
    cli,
)

SHA = "0123456789abcdef0123456789abcdef01234567"
RELEASE_SOURCE = (
    "https://github.com/Cnext-eu/kairos-ontology-toolkit/releases/download/"
    "v3.8.0/kairos_ontology_toolkit-3.8.0-py3-none-any.whl"
)
GIT_SOURCE = "git+https://github.com/Cnext-eu/kairos-ontology-toolkit.git@" + SHA


def _pyproject(source: str, ending: str = "\n") -> str:
    return (
        '[project]\nname = "hub"\ndependencies = [\n'
        f'  "kairos-ontology-toolkit @ {source}",\n'
        "]\n"
        "[project.optional-dependencies]\n"
        f'flatfile = ["kairos-ontology-toolkit[flatfile] @ {source}"]\n'
        "[tool.kairos]\n"
        'channel = "preview"' + ending
    )


SCAFFOLD_TEMPLATE = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "kairos_ontology"
    / "scaffold"
    / "pyproject.toml.template"
)


def _scaffolded_pyproject() -> str:
    """Render the shipped scaffold template exactly as ``init`` does.

    A current hub declares the toolkit URL once and its extras as bare
    requirements (issue #297), so the helpers below must cope with toolkit
    requirements that carry no source at all.
    """
    return (
        SCAFFOLD_TEMPLATE.read_text(encoding="utf-8")
        .replace("{repo_name}", "hub")
        .replace("{description}", "hub")
        .replace("{toolkit_ref}", "v3.8.0")
        .replace("{toolkit_version}", "3.8.0")
        .replace("{toolkit_channel}", "preview")
    )


def test_bare_extras_requirements_are_skipped_not_rejected():
    """Url-less extras carry no source: nothing to validate, nothing to rewrite."""
    content = _scaffolded_pyproject()

    assert _single_toolkit_dependency_source(content) == RELEASE_SOURCE

    rewritten = _rewrite_toolkit_dependency_source(content, GIT_SOURCE)

    assert rewritten.count(GIT_SOURCE) == 1
    assert RELEASE_SOURCE not in rewritten
    # The bare extras requirements are untouched — they still resolve via the base pin.
    assert '"kairos-ontology-toolkit[flatfile]"' in rewritten
    assert _single_toolkit_dependency_source(rewritten) == GIT_SOURCE


def test_unsupported_url_is_still_rejected():
    """Skipping url-less requirements must not excuse a *wrong* URL."""
    content = _scaffolded_pyproject().replace(
        RELEASE_SOURCE, "https://example.invalid/kairos_ontology_toolkit-3.8.0-py3-none-any.whl"
    )

    with pytest.raises(ValueError, match="unsupported"):
        _single_toolkit_dependency_source(content)


def test_scaffolded_hub_test_ref_and_restore_round_trip(tmp_path, monkeypatch):
    """`update --test-ref` / `--restore` must work on a hub scaffolded today."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_scaffolded_pyproject(), encoding="utf-8")
    original = pyproject.read_bytes()
    monkeypatch.chdir(tmp_path)

    with (
        patch("kairos_ontology.cli.operations._resolve_toolkit_ref_sha", return_value=SHA),
        patch("kairos_ontology.cli.operations._lock_and_sync_dependency"),
        patch("kairos_ontology.cli.operations._refresh_with_installed_toolkit", return_value=0),
    ):
        tested = CliRunner().invoke(cli, ["update", "--test-ref", "feature/example"])
        assert tested.exit_code == 0, tested.output
        assert GIT_SOURCE in pyproject.read_text(encoding="utf-8")

        restored = CliRunner().invoke(cli, ["update", "--restore"])

    assert restored.exit_code == 0, restored.output
    assert pyproject.read_bytes() == original


@patch("kairos_ontology.cli.main.subprocess.run")
def test_resolve_toolkit_ref_sha_validates_and_encodes_ref(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stdout=SHA.upper() + "\n")

    assert _resolve_toolkit_ref_sha(" feature/test ref ") == SHA
    assert mock_run.call_args.args[0][2].endswith("/commits/feature%2Ftest%20ref")

    mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
    assert _resolve_toolkit_ref_sha("main") is None


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
def test_resolve_toolkit_ref_sha_rejects_invalid_or_unavailable_refs(mock_run, result, side_effect):
    mock_run.return_value = result
    mock_run.side_effect = side_effect

    assert _resolve_toolkit_ref_sha("missing-ref") is None


def test_rewrite_all_toolkit_dependencies_preserves_extras_and_comments():
    content = _pyproject(RELEASE_SOURCE)
    content += f'# "kairos-ontology-toolkit @ {RELEASE_SOURCE}"\n'

    rewritten = _rewrite_toolkit_dependency_source(content, GIT_SOURCE)

    assert _single_toolkit_dependency_source(rewritten) == GIT_SOURCE
    assert f"kairos-ontology-toolkit[flatfile] @ {GIT_SOURCE}" in rewritten
    assert f'# "kairos-ontology-toolkit @ {RELEASE_SOURCE}"' in rewritten
    assert rewritten.count(GIT_SOURCE) == 2


def test_single_dependency_source_rejects_conflicting_sources():
    content = _pyproject(RELEASE_SOURCE).replace(
        f"kairos-ontology-toolkit[flatfile] @ {RELEASE_SOURCE}",
        f"kairos-ontology-toolkit[flatfile] @ {GIT_SOURCE}",
    )

    with pytest.raises(ValueError, match="same source"):
        _single_toolkit_dependency_source(content)


@pytest.mark.parametrize("ending", ["", "\n", "\n\n"])
def test_test_ref_metadata_round_trips_without_rewriting_other_toml(ending):
    content = _pyproject(RELEASE_SOURCE, ending)
    state = _ToolkitTestRefState("feature/example", SHA, RELEASE_SOURCE)

    encoded = _add_toolkit_test_ref_state(content, state)

    assert _read_toolkit_test_ref_state(encoded) == state
    restored, decoded = _remove_toolkit_test_ref_state(encoded)
    assert restored == content
    assert decoded == state


def test_test_ref_metadata_round_trips_with_crlf_line_endings():
    content = _pyproject(RELEASE_SOURCE).replace("\n", "\r\n")
    state = _ToolkitTestRefState("feature/example", SHA, RELEASE_SOURCE)

    encoded = _add_toolkit_test_ref_state(content, state)

    assert _read_toolkit_test_ref_state(encoded) == state
    restored, decoded = _remove_toolkit_test_ref_state(encoded)
    assert restored == content
    assert decoded == state
    assert "\r\r" not in restored and not restored.endswith("\r")
    tomllib.loads(restored)
    state = _ToolkitTestRefState("main", SHA, RELEASE_SOURCE)
    content = _add_toolkit_test_ref_state(_pyproject(RELEASE_SOURCE), state)

    with pytest.raises(ValueError, match="already active"):
        _add_toolkit_test_ref_state(content, state)
    with pytest.raises(ValueError, match="contain only"):
        _read_toolkit_test_ref_state(content + "[tool.kairos.test-ref.nested]\nvalue = 1\n")


def test_dependency_transaction_restores_exact_files_on_system_exit(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    lockfile = tmp_path / "uv.lock"
    pyproject.write_bytes(b"original pyproject\r\n")
    lockfile.write_bytes(b"original lock\n")

    with pytest.raises(SystemExit):
        with _dependency_files_transaction(tmp_path):
            pyproject.write_text("changed", encoding="utf-8")
            lockfile.write_text("changed", encoding="utf-8")
            raise SystemExit(1)

    assert pyproject.read_bytes() == b"original pyproject\r\n"
    assert lockfile.read_bytes() == b"original lock\n"


def test_dependency_transaction_removes_new_lock_on_failure(tmp_path: Path):
    pyproject = tmp_path / "pyproject.toml"
    lockfile = tmp_path / "uv.lock"
    pyproject.write_text('[project]\nname = "hub"\n', encoding="utf-8")

    with pytest.raises(RuntimeError):
        with _dependency_files_transaction(tmp_path):
            lockfile.write_text("new", encoding="utf-8")
            raise RuntimeError("failed")

    assert not lockfile.exists()


def test_git_sha_source_rejects_mutable_ref():
    with pytest.raises(ValueError, match="40-character"):
        _toolkit_git_sha_source("main")


@patch("kairos_ontology.cli.operations._refresh_with_installed_toolkit", return_value=0)
@patch("kairos_ontology.cli.operations._lock_and_sync_dependency")
@patch("kairos_ontology.cli.operations._resolve_toolkit_ref_sha", return_value=SHA)
def test_update_test_ref_and_restore_round_trip(
    mock_resolve, mock_sync, mock_refresh, tmp_path, monkeypatch
):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_pyproject(RELEASE_SOURCE), encoding="utf-8")
    original_pyproject = pyproject.read_bytes()
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    test_result = runner.invoke(cli, ["update", "--test-ref", "feature/example"])

    assert test_result.exit_code == 0
    tested = pyproject.read_text(encoding="utf-8")
    assert tested.count(GIT_SOURCE) == 2
    assert _read_toolkit_test_ref_state(tested) == _ToolkitTestRefState(
        "feature/example", SHA, RELEASE_SOURCE
    )
    assert 'channel = "preview"' in tested
    mock_resolve.assert_called_once_with("feature/example")
    mock_refresh.assert_called_once_with(False, SHA)

    restore_result = runner.invoke(cli, ["update", "--restore"])

    assert restore_result.exit_code == 0, restore_result.output
    assert pyproject.read_bytes() == original_pyproject
    assert "[tool.kairos.test-ref]" not in pyproject.read_text(encoding="utf-8")
    assert mock_sync.call_count == 2
    assert mock_refresh.call_args_list[-1].args == (False, RELEASE_SOURCE)


@patch("kairos_ontology.cli.operations._refresh_with_installed_toolkit")
@patch("kairos_ontology.cli.operations._lock_and_sync_dependency")
@patch("kairos_ontology.cli.operations._resolve_toolkit_ref_sha")
def test_update_test_ref_rejects_nested_session_before_external_work(
    mock_resolve, mock_sync, mock_refresh, tmp_path, monkeypatch
):
    state = _ToolkitTestRefState("first", SHA, RELEASE_SOURCE)
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        _add_toolkit_test_ref_state(_pyproject(GIT_SOURCE), state), encoding="utf-8"
    )
    original = pyproject.read_bytes()
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["update", "--test-ref", "second"])

    assert result.exit_code == 1
    assert "already active" in result.output
    assert pyproject.read_bytes() == original
    mock_resolve.assert_not_called()
    mock_sync.assert_not_called()
    mock_refresh.assert_not_called()


@patch("kairos_ontology.cli.operations._refresh_with_installed_toolkit")
@patch("kairos_ontology.cli.operations._lock_and_sync_dependency")
def test_update_restore_rejects_missing_state(mock_sync, mock_refresh, tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_pyproject(RELEASE_SOURCE), encoding="utf-8")
    original = pyproject.read_bytes()
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["update", "--restore"])

    assert result.exit_code == 1
    assert "no active toolkit test-ref session" in result.output
    assert pyproject.read_bytes() == original
    mock_sync.assert_not_called()
    mock_refresh.assert_not_called()


@patch("kairos_ontology.cli.operations._refresh_with_installed_toolkit")
@patch("kairos_ontology.cli.operations._lock_and_sync_dependency")
@patch("kairos_ontology.cli.operations._resolve_toolkit_ref_sha", return_value=None)
def test_update_test_ref_rejects_unresolved_ref_without_changes(
    mock_resolve, mock_sync, mock_refresh, tmp_path, monkeypatch
):
    pyproject = tmp_path / "pyproject.toml"
    lockfile = tmp_path / "uv.lock"
    pyproject.write_text(_pyproject(RELEASE_SOURCE), encoding="utf-8")
    lockfile.write_bytes(b"original lock\n")
    original_pyproject = pyproject.read_bytes()
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["update", "--test-ref", "does-not-exist"])

    assert result.exit_code == 1
    assert "could not resolve" in result.output
    assert pyproject.read_bytes() == original_pyproject
    assert lockfile.read_bytes() == b"original lock\n"
    mock_sync.assert_not_called()
    mock_refresh.assert_not_called()


@patch("kairos_ontology.cli.operations._refresh_with_installed_toolkit", return_value=7)
@patch("kairos_ontology.cli.operations._resync_restored_dependency", return_value=None)
@patch("kairos_ontology.cli.operations._lock_and_sync_dependency")
@patch("kairos_ontology.cli.operations._resolve_toolkit_ref_sha", return_value=SHA)
def test_update_test_ref_rolls_back_dependency_files(
    mock_resolve, mock_sync, mock_resync, mock_refresh, tmp_path, monkeypatch
):
    pyproject = tmp_path / "pyproject.toml"
    lockfile = tmp_path / "uv.lock"
    original_pyproject = _pyproject(RELEASE_SOURCE).encode()
    original_lock = b"original lock\r\n"
    pyproject.write_bytes(original_pyproject)
    lockfile.write_bytes(original_lock)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["update", "--test-ref", "main"])

    assert result.exit_code == 1
    assert "rolled back" in result.output
    assert pyproject.read_bytes() == original_pyproject
    assert lockfile.read_bytes() == original_lock


@patch("kairos_ontology.cli.operations._resync_restored_dependency", return_value=None)
@patch("kairos_ontology.cli.operations._lock_and_sync_dependency")
@patch("kairos_ontology.cli.operations._resolve_toolkit_ref_sha", return_value=SHA)
def test_failed_forced_refresh_restores_exact_managed_state(
    mock_resolve, mock_sync, mock_resync, tmp_path, monkeypatch
):
    pyproject = tmp_path / "pyproject.toml"
    lockfile = tmp_path / "uv.lock"
    pyproject.write_text(_pyproject(RELEASE_SOURCE), encoding="utf-8")
    lockfile.write_bytes(b"original lock")

    copilot = tmp_path / ".github" / "copilot-instructions.md"
    current = tmp_path / ".github" / "skills" / "current" / "SKILL.md"
    stale_dir = tmp_path / ".github" / "skills" / "stale"
    stale = stale_dir / "SKILL.md"
    stale_extra = stale_dir / "custom-notes.txt"
    custom = tmp_path / ".github" / "skills" / "custom" / "SKILL.md"
    for path in (copilot, current, stale, stale_extra, custom):
        path.parent.mkdir(parents=True, exist_ok=True)
    copilot.write_bytes(b"original copilot")
    current.write_bytes(b"<!-- kairos-ontology-toolkit:managed v1 -->\noriginal current")
    stale.write_bytes(b"<!-- kairos-ontology-toolkit:managed v1 -->\noriginal stale")
    stale_extra.write_bytes(b"custom content beside managed skill")
    custom.write_bytes(b"unmanaged custom skill")
    original = {path: path.read_bytes() for path in (copilot, current, stale, stale_extra, custom)}
    created = tmp_path / ".github" / "skills" / "new-skill"
    monkeypatch.chdir(tmp_path)

    def partial_refresh(check, ref):
        copilot.write_bytes(b"partially updated")
        current.write_bytes(b"partially updated")
        shutil.rmtree(stale_dir)
        (created / "SKILL.md").parent.mkdir(parents=True)
        (created / "SKILL.md").write_bytes(b"<!-- kairos-ontology-toolkit:managed v2 -->\nnew")
        return 7

    with patch(
        "kairos_ontology.cli.operations._refresh_with_installed_toolkit",
        side_effect=partial_refresh,
    ):
        result = CliRunner().invoke(cli, ["update", "--test-ref", "main"])

    assert result.exit_code == 1
    assert "dependency and managed files were rolled back" in result.output
    assert all(path.read_bytes() == content for path, content in original.items())
    assert not created.exists()
    mock_resync.assert_called_once_with()


@pytest.mark.parametrize("failing_command", ["lock", "sync"])
@patch("kairos_ontology.cli.operations._refresh_with_installed_toolkit")
@patch("kairos_ontology.cli.operations._resolve_toolkit_ref_sha", return_value=SHA)
def test_uv_failure_restores_pyproject_and_lock_bytes(
    mock_resolve,
    mock_refresh,
    failing_command,
    tmp_path,
    monkeypatch,
):
    pyproject = tmp_path / "pyproject.toml"
    lockfile = tmp_path / "uv.lock"
    original_pyproject = _pyproject(RELEASE_SOURCE).encode("utf-8")
    original_lock = b"original lock\r\n\x00"
    pyproject.write_bytes(original_pyproject)
    lockfile.write_bytes(original_lock)
    monkeypatch.chdir(tmp_path)

    def run(cmd, *args, **kwargs):
        if cmd[:2] == ["uv", "lock"]:
            lockfile.write_bytes(b"lock was rewritten")
            return MagicMock(
                returncode=1 if failing_command == "lock" else 0,
                stdout="",
                stderr="lock error",
            )
        if cmd[:2] == ["uv", "sync"]:
            lockfile.write_bytes(b"sync changed lock")
            return MagicMock(
                returncode=1 if failing_command == "sync" else 0,
                stdout="",
                stderr="sync error",
            )
        raise AssertionError(f"unexpected command: {cmd}")

    with patch("kairos_ontology.cli.main.subprocess.run", side_effect=run):
        with patch("sys.platform", "linux"):
            result = CliRunner().invoke(cli, ["update", "--test-ref", "main"])

    assert result.exit_code == 1
    assert f"uv {failing_command} failed" in result.output
    assert pyproject.read_bytes() == original_pyproject
    assert lockfile.read_bytes() == original_lock
    mock_refresh.assert_not_called()


@patch("kairos_ontology.cli.operations._resolve_toolkit_ref_sha", return_value=SHA)
def test_non_windows_test_ref_reexecs_forced_refresh(mock_resolve, tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_pyproject(RELEASE_SOURCE), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with patch(
        "kairos_ontology.cli.main.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    ) as mock_run:
        with patch("sys.platform", "linux"):
            result = CliRunner().invoke(cli, ["update", "--test-ref", SHA])

    assert result.exit_code == 0
    commands = [entry.args[0] for entry in mock_run.call_args_list]
    assert commands == [
        ["uv", "lock"],
        ["uv", "sync"],
        ["uv", "run", "kairos-ontology", "update", "--force-managed"],
    ]
    assert f"@{SHA}" in pyproject.read_text(encoding="utf-8")


@patch("kairos_ontology.cli.main.os.getpid", return_value=4242)
@patch("kairos_ontology.cli.main.subprocess.Popen")
@patch("kairos_ontology.cli.operations._resolve_toolkit_ref_sha", return_value=SHA)
def test_windows_test_ref_schedules_detached_refresh(
    mock_resolve, mock_popen, mock_getpid, tmp_path, monkeypatch
):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_pyproject(RELEASE_SOURCE), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with patch(
        "kairos_ontology.cli.main.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    ) as mock_run:
        with patch("sys.platform", "win32"):
            result = CliRunner().invoke(cli, ["update", "--test-ref", "feature/example"])

    assert result.exit_code == 0
    assert [entry.args[0] for entry in mock_run.call_args_list] == [["uv", "lock"]]
    mock_popen.assert_called_once()
    script = mock_popen.call_args.args[0][-1]
    assert "Wait-Process -Id 4242" in script
    assert "uv sync" in script
    assert "uv run kairos-ontology update --force-managed" in script
    assert mock_popen.call_args.kwargs["creationflags"] & 0x00000010


@patch("kairos_ontology.cli.main.subprocess.Popen")
def test_windows_refresh_passes_apostrophe_log_path_outside_script(
    mock_popen, tmp_path, monkeypatch
):
    hub = tmp_path / "customer's-hub"
    hub.mkdir()
    monkeypatch.chdir(hub)

    assert _schedule_windows_refresh(False)

    script = mock_popen.call_args.args[0][-1]
    assert "KAIROS_REFRESH_LOG" in script
    assert str(hub) not in script
    assert mock_popen.call_args.kwargs["env"]["KAIROS_REFRESH_LOG"] == str(
        hub / ".kairos" / "upgrade-refresh.log"
    )


@patch(
    "kairos_ontology.cli.main.subprocess.Popen",
    side_effect=OSError("cannot schedule"),
)
@patch("kairos_ontology.cli.operations._resolve_toolkit_ref_sha", return_value=SHA)
def test_windows_scheduling_failure_rolls_back_dependency_files(
    mock_resolve, mock_popen, tmp_path, monkeypatch
):
    pyproject = tmp_path / "pyproject.toml"
    lockfile = tmp_path / "uv.lock"
    original_pyproject = _pyproject(RELEASE_SOURCE).encode("utf-8")
    original_lock = b"original lock bytes"
    pyproject.write_bytes(original_pyproject)
    lockfile.write_bytes(original_lock)
    monkeypatch.chdir(tmp_path)

    with patch(
        "kairos_ontology.cli.main.subprocess.run",
        return_value=MagicMock(returncode=0, stdout="", stderr=""),
    ):
        with patch("sys.platform", "win32"):
            result = CliRunner().invoke(cli, ["update", "--test-ref", "main"])

    assert result.exit_code == 1
    assert "could not schedule" in result.output
    assert "rolled back" in result.output
    assert pyproject.read_bytes() == original_pyproject
    assert lockfile.read_bytes() == original_lock


@patch("kairos_ontology.cli.operations._toolkit_version", "3.8.0")
@patch("kairos_ontology.cli.operations._managed_scaffold_map")
def test_same_version_forced_refresh_replaces_changed_managed_content(
    mock_managed_map, tmp_path, monkeypatch
):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(_pyproject(RELEASE_SOURCE), encoding="utf-8")
    scaffold = tmp_path / "scaffold-skill.md"
    scaffold.write_text("# New test-ref content\n", encoding="utf-8")
    managed = tmp_path / ".github" / "skills" / "kairos-help" / "SKILL.md"
    managed.parent.mkdir(parents=True)
    managed.write_text(
        "<!-- kairos-ontology-toolkit:managed v3.8.0 -->\n# Released content\n",
        encoding="utf-8",
    )
    mock_managed_map.return_value = {
        ".github/skills/kairos-help/SKILL.md": scaffold,
    }
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["update", "--force-managed"])

    assert result.exit_code == 0
    refreshed = managed.read_text(encoding="utf-8")
    assert "# New test-ref content" in refreshed
    assert "# Released content" not in refreshed
    assert "managed v3.8.0" in refreshed


@pytest.mark.parametrize(
    "arguments",
    [
        ["--upgrade", "--test-ref", "main"],
        ["--upgrade", "--restore"],
        ["--test-ref", "main", "--restore"],
        ["--check", "--test-ref", "main"],
        ["--check", "--restore"],
    ],
)
def test_update_rejects_conflicting_modes(arguments):
    result = CliRunner().invoke(cli, ["update", *arguments])

    assert result.exit_code == 2
