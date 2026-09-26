# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-246: AGENTS.md carries the agent instructions; the toolkit owns only a region of it."""

import os
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from kairos_ontology import __version__
from kairos_ontology.cli.main import cli
from kairos_ontology.cli.shared import (
    _MANAGED_MARKER_RE,
    _MANAGED_REGION_FILES,
    _SCAFFOLD_DIR,
    _claude_memory_without_agents_import,
    _get_managed_version,
    _get_region_version,
    _managed_dataplatform_map,
    _managed_region_update,
    _managed_scaffold_map,
    _restore_managed_files,
    _snapshot_managed_files,
)
from kairos_ontology.core.hub_utils import _is_managed_root

from .test_init import (
    _managed_content,
    _stage_current_hub_workflows,
    _stage_git_hygiene,
)

HUB_TEMPLATE = _SCAFFOLD_DIR / "AGENTS.md.template"
BODY = HUB_TEMPLATE.read_text(encoding="utf-8")
OWN_TEXT = "# Our hub\n\nAlways answer in Dutch.\n"


def _agents_text(raw: bytes) -> str:
    """Decode as `read_text` would: `write_text` emits CRLF on Windows."""
    return raw.decode("utf-8").replace("\r\n", "\n")


def _stage_current_hub(td: str) -> None:
    """Write every managed file as the running toolkit would, so `--check` passes."""
    for rel_path, scaffold_src in _managed_scaffold_map().items():
        dst = Path(td) / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(
            _managed_content(rel_path, scaffold_src.read_text(encoding="utf-8"), __version__),
            encoding="utf-8",
        )
    _stage_current_hub_workflows(td)
    _stage_git_hygiene(td)


# --- the region helpers ------------------------------------------------------------------


def test_region_markers_never_look_like_a_whole_file_managed_marker():
    """A hub's AGENTS.md must not be taken for a whole-file managed file (DD-062 anchor)."""
    rendered = _managed_region_update(None, BODY, "5.99.0")
    assert not _MANAGED_MARKER_RE.search(rendered)
    assert _get_managed_version(rendered) is None
    assert _get_region_version(rendered) == "5.99.0"


def test_missing_file_gets_the_region_and_an_empty_notes_section():
    rendered = _managed_region_update(None, BODY, "5.99.0")
    assert rendered.startswith("<!-- kairos-ontology-toolkit:managed-begin v5.99.0 -->\n")
    assert "<!-- kairos-ontology-toolkit:managed-end -->\n" in rendered
    assert rendered.rstrip().endswith("-->")
    assert "## Repository notes" in rendered


def test_unmarked_file_gets_the_region_prepended_and_keeps_its_text():
    rendered = _managed_region_update(OWN_TEXT, BODY, "5.99.0")
    assert rendered.endswith("\n" + OWN_TEXT)
    assert rendered.index("managed-end") < rendered.index("# Our hub")


def test_only_the_region_is_replaced():
    old = _managed_region_update(None, "old toolkit rules", "5.0.0")
    old = "Above the block.\n" + old + "\nBelow the block.\n"
    new = _managed_region_update(old, BODY, "5.99.0")
    assert new.startswith("Above the block.\n<!-- kairos-ontology-toolkit:managed-begin v5.99.0")
    assert new.endswith("\nBelow the block.\n")
    assert "old toolkit rules" not in new
    assert _managed_region_update(new, BODY, "5.99.0") == new


# --- init and the managed maps -----------------------------------------------------------


def test_both_maps_manage_agents_md_through_the_region_path():
    assert "AGENTS.md" in _MANAGED_REGION_FILES
    assert _managed_scaffold_map()["AGENTS.md"] == HUB_TEMPLATE
    assert (
        _managed_dataplatform_map()["AGENTS.md"]
        == _SCAFFOLD_DIR / "dataplatform-AGENTS.md.template"
    )


def test_hub_template_carries_no_toolkit_developer_rules():
    """The reason for the split: hubs received rules only toolkit contributors can act on."""
    for marker in (
        "## Code conventions",
        "SPDX-License-Identifier",
        "this repository only",
        "kairos-toolkit-dev",
        "sync_dev_skills",
    ):
        assert marker not in BODY, marker


def test_init_writes_agents_md_and_a_pointer_stub(tmp_path):
    runner = CliRunner()
    with mock.patch("kairos_ontology.cli.main.subprocess.run") as mock_run:
        mock_run.return_value = mock.MagicMock(returncode=0)
        with runner.isolated_filesystem(temp_dir=tmp_path) as td:
            Path("AGENTS.md").write_text(OWN_TEXT, encoding="utf-8")
            result = runner.invoke(
                cli, ["init", "--company-domain", "test.com", "--domain", "order"]
            )
            agents = (Path(td) / "AGENTS.md").read_text(encoding="utf-8")
            stub = (Path(td) / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")

    assert result.exit_code == 0, result.output
    assert _get_region_version(agents) == __version__
    assert agents.endswith(OWN_TEXT)
    assert "## Semantic access (DD-103)" in agents
    assert _get_managed_version(stub) == __version__
    assert "`AGENTS.md`" in stub
    assert len(stub.splitlines()) < 25


# --- update ------------------------------------------------------------------------------


def test_update_prepends_the_region_to_an_authored_agents_md_and_is_idempotent(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _stage_current_hub(td)
        agents = Path(td) / "AGENTS.md"
        agents.write_text(OWN_TEXT, encoding="utf-8")

        check = runner.invoke(cli, ["update", "--check"])
        first = runner.invoke(cli, ["update"])
        after_first = agents.read_bytes()
        second = runner.invoke(cli, ["update"])
        after_second = agents.read_bytes()

    assert check.exit_code == 1, check.output
    assert "AGENTS.md  (unmanaged" in check.output
    assert first.exit_code == 0, first.output
    assert _agents_text(after_first).endswith(OWN_TEXT)
    assert second.exit_code == 0, second.output
    assert after_first == after_second


def test_update_check_reports_an_edit_inside_the_region_and_update_restores_it(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _stage_current_hub(td)
        agents = Path(td) / "AGENTS.md"
        pristine = agents.read_text(encoding="utf-8")
        agents.write_text(
            pristine.replace("## Skill routing", "## Skill routing (edited)").replace(
                f"managed-begin v{__version__}", "managed-begin v0.0.1"
            ),
            encoding="utf-8",
        )

        check = runner.invoke(cli, ["update", "--check"])
        update = runner.invoke(cli, ["update"])
        restored = agents.read_text(encoding="utf-8")

    assert check.exit_code == 1, check.output
    assert "AGENTS.md  (0.0.1" in check.output
    assert update.exit_code == 0, update.output
    assert restored == pristine


def test_update_check_ignores_an_edit_outside_the_region(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _stage_current_hub(td)
        agents = Path(td) / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8") + OWN_TEXT, encoding="utf-8")
        before = agents.read_bytes()

        check = runner.invoke(cli, ["update", "--check"])
        update = runner.invoke(cli, ["update"])
        after = agents.read_bytes()

    assert check.exit_code == 0, check.output
    assert update.exit_code == 0, update.output
    assert before == after


# --- a CLAUDE.md that switches AGENTS.md off ---------------------------------------------


@pytest.mark.parametrize("rel_path", ["CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md"])
def test_claude_memory_without_import_is_detected(tmp_path, rel_path):
    (tmp_path / rel_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel_path).write_text("# Our rules\n", encoding="utf-8")
    assert _claude_memory_without_agents_import(tmp_path) == [rel_path]

    (tmp_path / rel_path).write_text("# Our rules\n\n@AGENTS.md\n", encoding="utf-8")
    assert _claude_memory_without_agents_import(tmp_path) == []


def test_claude_md_advisory_does_not_fail_check(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _stage_current_hub(td)
        (Path(td) / "CLAUDE.md").write_text("# Our rules\n", encoding="utf-8")
        result = runner.invoke(cli, ["update", "--check"])

    assert result.exit_code == 0, result.output
    assert "CLAUDE.md does not import AGENTS.md" in result.output
    assert "`@AGENTS.md`" in result.output


def test_no_advisory_without_a_claude_md(tmp_path):
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        _stage_current_hub(td)
        result = runner.invoke(cli, ["update", "--check"])

    assert result.exit_code == 0, result.output
    assert "does not import AGENTS.md" not in result.output


# --- transactional refresh and root detection --------------------------------------------


@pytest.mark.parametrize("present", [True, False])
def test_forced_refresh_snapshot_round_trips_agents_md(tmp_path, present):
    agents = tmp_path / "AGENTS.md"
    if present:
        agents.write_bytes(OWN_TEXT.encode("utf-8"))
    snapshot = _snapshot_managed_files(tmp_path)

    agents.write_bytes(b"partially refreshed")
    _restore_managed_files(snapshot)

    if present:
        assert agents.read_bytes() == OWN_TEXT.encode("utf-8")
    else:
        assert not agents.exists()


def test_agents_md_alone_does_not_make_a_managed_root(tmp_path):
    (tmp_path / "AGENTS.md").write_text(
        _managed_region_update(None, BODY, __version__), encoding="utf-8"
    )
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        assert not _is_managed_root(tmp_path)
    finally:
        os.chdir(old_cwd)
