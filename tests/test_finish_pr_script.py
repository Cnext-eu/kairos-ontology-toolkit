# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for scripts/finish_pr.py (mechanical git/gh choreography for SC-merge-pr)."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import finish_pr  # noqa: E402


def test_render_pr_body_includes_closing_keywords_and_bullets():
    body = finish_pr.render_pr_body(["did a thing", "did another thing"], [175, 174])
    assert "- did a thing" in body
    assert "- did another thing" in body
    assert "Closes #175" in body
    assert "Closes #174" in body
    assert "## Checklist" in body


def test_render_pr_body_follow_up_referenced_without_closing_keyword():
    body = finish_pr.render_pr_body(["fix"], [175], follow_ups=[176])
    assert "Closes #175" in body
    assert "Follow-up: #176" in body
    assert "Closes #176" not in body


@pytest.fixture
def fixture_files(tmp_path):
    """A minimal, isolated copy of __init__.py/CHANGELOG.md — never the real repo files."""
    init_py = tmp_path / "__init__.py"
    init_py.write_text(
        '# SPDX-License-Identifier: Apache-2.0\n__version__ = "5.1.0rc3"\n',
        encoding="utf-8",
    )
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n- something\n\n"
        "## [5.0.2] — 2026-07-29\n\n### Added\n- older thing\n",
        encoding="utf-8",
    )
    return init_py, changelog


def test_bump_version_updates_init_and_changelog(fixture_files):
    init_py, changelog = fixture_files
    new_version = finish_pr.bump_version(
        "patch", init_py=init_py, changelog=changelog, today="2026-08-10"
    )
    assert new_version == "5.1.1"
    assert '__version__ = "5.1.1"' in init_py.read_text(encoding="utf-8")
    changelog_text = changelog.read_text(encoding="utf-8")
    assert "## [5.1.1] — 2026-08-10" in changelog_text
    assert "## [Unreleased]" in changelog_text  # a fresh empty heading remains


def test_bump_version_minor_and_major(fixture_files):
    init_py, changelog = fixture_files
    assert (
        finish_pr.bump_version("minor", init_py=init_py, changelog=changelog, today="2026-08-10")
        == "5.2.0"
    )


def test_bump_version_rc_increments_existing_suffix_and_skips_changelog(tmp_path):
    init_py = tmp_path / "__init__.py"
    init_py.write_text('__version__ = "5.1.0rc3"\n', encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog_before = "# Changelog\n\n## [Unreleased]\n\n### Added\n- something\n"
    changelog.write_text(changelog_before, encoding="utf-8")

    new_version = finish_pr.bump_version(
        "rc", init_py=init_py, changelog=changelog, today="2026-08-10"
    )

    assert new_version == "5.1.0rc4"
    assert '__version__ = "5.1.0rc4"' in init_py.read_text(encoding="utf-8")
    # rc bumps never touch CHANGELOG — matches this repo's own rc2 -> rc3 precedent.
    assert changelog.read_text(encoding="utf-8") == changelog_before


def test_bump_version_rc_without_existing_rc_suffix_raises(fixture_files):
    init_py, changelog = fixture_files  # fixture is plain "5.1.0rc3" -> still has rc; use non-rc
    init_py.write_text('__version__ = "5.1.0"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="no 'rcN' suffix"):
        finish_pr.bump_version("rc", init_py=init_py, changelog=changelog, today="2026-08-10")


def test_bump_version_rc_dry_run_does_not_write(tmp_path):
    init_py = tmp_path / "__init__.py"
    init_py.write_text('__version__ = "5.1.0rc3"\n', encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [Unreleased]\n", encoding="utf-8")
    before = init_py.read_text(encoding="utf-8")

    new_version = finish_pr.bump_version(
        "rc", init_py=init_py, changelog=changelog, today="2026-08-10", dry_run=True
    )

    assert new_version == "5.1.0rc4"
    assert init_py.read_text(encoding="utf-8") == before


def test_bump_version_dry_run_does_not_write(fixture_files):
    init_py, changelog = fixture_files
    before_init = init_py.read_text(encoding="utf-8")
    before_changelog = changelog.read_text(encoding="utf-8")

    new_version = finish_pr.bump_version(
        "patch", init_py=init_py, changelog=changelog, today="2026-08-10", dry_run=True
    )

    assert new_version == "5.1.1"
    assert init_py.read_text(encoding="utf-8") == before_init
    assert changelog.read_text(encoding="utf-8") == before_changelog


def test_bump_version_missing_unreleased_heading_raises(tmp_path):
    init_py = tmp_path / "__init__.py"
    init_py.write_text('__version__ = "1.0.0"\n', encoding="utf-8")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Unreleased"):
        finish_pr.bump_version("patch", init_py=init_py, changelog=changelog, today="2026-08-10")


def test_check_branch_and_status_dry_run_never_shells_out():
    with patch.object(finish_pr.subprocess, "run") as mock_run:
        branch, clean = finish_pr.check_branch_and_status(dry_run=True)
    mock_run.assert_not_called()
    assert branch == "(dry-run)"
    assert clean is True


def test_push_branch_calls_expected_argv():
    with patch.object(finish_pr.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        ok = finish_pr.push_branch("feature/foo")
    assert ok is True
    args, kwargs = mock_run.call_args
    assert args[0] == ["git", "push", "-u", "origin", "feature/foo"]


def test_merge_pr_calls_expected_argv():
    with patch.object(finish_pr.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        ok = finish_pr.merge_pr()
    assert ok is True
    args, kwargs = mock_run.call_args
    assert args[0] == ["gh", "pr", "merge", "--squash", "--delete-branch"]


def test_cleanup_local_branch_calls_expected_sequence():
    with patch.object(finish_pr.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        finish_pr.cleanup_local_branch("feature/foo")
    calls = [call.args[0] for call in mock_run.call_args_list]
    assert calls == [
        ["git", "checkout", "main"],
        ["git", "pull", "origin", "main"],
        ["git", "branch", "-d", "feature/foo"],
    ]


def test_tag_release_calls_expected_sequence():
    with patch.object(finish_pr.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        finish_pr.tag_release("5.1.1")
    calls = [call.args[0] for call in mock_run.call_args_list]
    assert calls == [
        ["git", "tag", "-a", "v5.1.1", "-m", "Release v5.1.1"],
        ["git", "push", "origin", "v5.1.1"],
    ]


def test_create_pr_calls_expected_argv_and_returns_url():
    with patch.object(finish_pr.subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "https://github.com/org/repo/pull/1\n"
        url = finish_pr.create_pr("feat: thing", "body text")
    assert url == "https://github.com/org/repo/pull/1"
    args, kwargs = mock_run.call_args
    assert args[0] == [
        "gh",
        "pr",
        "create",
        "--base",
        "main",
        "--title",
        "feat: thing",
        "--body",
        "body text",
    ]
