# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The reciprocal reference-models pin check (issue #541).

The reference-models repo has failed *its* build on toolkit pin drift for some time.
Nothing enforced the other direction, so this repo's pin sat at v1.20.0 while v1.33.1
was current — thirteen minor versions — and the cross-repo contract suite reported green
against a bundle that predated the defects this repo then spent a week finding.

These tests cover the script's decision logic and its rewrite, and assert the CI wiring
exists, since a check nobody runs is the state #541 describes.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "check_refmodels_pin.py"
_CI_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "refmodels-pin.yml"

sys.path.insert(0, str(_REPO_ROOT / "scripts"))

check_refmodels_pin = pytest.importorskip("check_refmodels_pin")


PIN_LINE = (
    'kairos-ontology-referencemodels = { url = "https://github.com/Cnext-eu/'
    'kairos-ontology-referencemodels/releases/download/v{tag}/'
    'kairos_ontology_referencemodels-{version}-py3-none-any.whl" }'
)


def _pyproject(tag: str = "1.33.1", channel: str | None = None) -> str:
    """A minimal pyproject carrying just the pin (and optionally a channel)."""
    body = "[tool.uv.sources]\n" + PIN_LINE.replace("{tag}", tag).replace("{version}", tag) + "\n"
    if channel is not None:
        body += f'\n[tool.kairos]\nrefmodels-channel = "{channel}"\n'
    return body


class TestPinParsing:
    def test_reads_the_pinned_tag(self):
        assert check_refmodels_pin.pinned_tag(_pyproject("1.28.1")) == "v1.28.1"

    def test_returns_none_when_no_pin_present(self):
        assert check_refmodels_pin.pinned_tag("[project]\nname = 'x'\n") is None

    def test_channel_defaults_to_stable(self):
        assert check_refmodels_pin.configured_channel(_pyproject()) == "stable"

    def test_channel_is_read_when_declared(self):
        assert check_refmodels_pin.configured_channel(_pyproject(channel="preview")) == "preview"

    def test_real_pyproject_is_parseable(self):
        """Guard against the regex drifting from the file it exists to read."""
        with (_REPO_ROOT / "pyproject.toml").open("r", encoding="utf-8", newline="") as fh:
            text = fh.read()
        assert check_refmodels_pin.pinned_tag(text) is not None
        assert check_refmodels_pin.configured_channel(text) in {"stable", "preview"}


class TestBehindComparison:
    def test_compares_numerically_not_lexicographically(self):
        assert check_refmodels_pin._is_behind("v1.9.0", "v1.33.1")
        assert not check_refmodels_pin._is_behind("v1.33.1", "v1.9.0")

    def test_equal_is_not_behind(self):
        assert not check_refmodels_pin._is_behind("v1.33.1", "v1.33.1")

    def test_ahead_is_not_behind(self):
        """A local pin ahead of the feed (mid-release) must not fail the build."""
        assert not check_refmodels_pin._is_behind("v1.34.0", "v1.33.1")


class TestLatestReleaseResolution:
    def test_delegates_to_the_shared_draft_filtering_resolver(self):
        """Latest-release logic must not be reimplemented here — #542 was a second copy."""
        with mock.patch.object(
            check_refmodels_pin, "_list_published_release_tags",
            return_value=["v1.33.1", "v1.31.0"],
        ) as listed:
            assert check_refmodels_pin.latest_release("stable") == "v1.33.1"
        assert listed.call_args[0][0] == check_refmodels_pin._REFMODELS_REPO

    def test_preview_channel_takes_the_highest_including_prereleases(self):
        with mock.patch.object(
            check_refmodels_pin, "_list_published_release_tags",
            return_value=["v1.34.0rc1", "v1.33.1"],
        ):
            assert check_refmodels_pin.latest_release("preview") == "v1.34.0rc1"
            assert check_refmodels_pin.latest_release("stable") == "v1.33.1"

    def test_falls_back_to_the_anonymous_api_when_gh_is_absent(self):
        with (
            mock.patch.object(check_refmodels_pin, "_list_published_release_tags", return_value=None),
            mock.patch.object(
                check_refmodels_pin, "_anonymous_release_tags", return_value=["v1.33.1"]
            ) as anon,
        ):
            assert check_refmodels_pin.latest_release("stable") == "v1.33.1"
        assert anon.called

    def test_undetermined_when_neither_path_resolves(self):
        with (
            mock.patch.object(check_refmodels_pin, "_list_published_release_tags", return_value=None),
            mock.patch.object(check_refmodels_pin, "_anonymous_release_tags", return_value=None),
        ):
            assert check_refmodels_pin.latest_release("stable") is None


class TestExitCodes:
    """``--check`` is what CI runs, so its exit codes are the contract."""

    def _run(self, argv, tag="1.33.1", latest="v1.33.1", channel=None, tmp_path=None):
        pyproject = tmp_path / "pyproject.toml"
        with pyproject.open("w", encoding="utf-8", newline="") as fh:
            fh.write(_pyproject(tag, channel))
        with (
            mock.patch.object(check_refmodels_pin, "PYPROJECT", pyproject),
            mock.patch.object(check_refmodels_pin, "latest_release", return_value=latest),
        ):
            return check_refmodels_pin.main(argv)

    def test_current_pin_passes(self, tmp_path, capsys):
        assert self._run(["--check"], tag="1.33.1", tmp_path=tmp_path) == 0
        assert "is current" in capsys.readouterr().out

    def test_behind_pin_fails_under_check(self, tmp_path, capsys):
        assert self._run(["--check"], tag="1.20.0", tmp_path=tmp_path) == 1
        out = capsys.readouterr().out
        assert "behind" in out
        assert "--update" in out

    def test_behind_pin_only_reports_without_check(self, tmp_path):
        """Bare invocation is a report, so a human running it locally gets exit 0."""
        assert self._run([], tag="1.20.0", tmp_path=tmp_path) == 0

    def test_unreachable_feed_does_not_fail_the_build(self, tmp_path, capsys):
        assert self._run(["--check"], tag="1.20.0", latest=None, tmp_path=tmp_path) == 0
        out = capsys.readouterr().out
        assert "undetermined" in out
        assert "Not failing" in out

    def test_missing_pin_is_an_error(self, tmp_path, capsys):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nname = 'x'\n", encoding="utf-8")
        with mock.patch.object(check_refmodels_pin, "PYPROJECT", pyproject):
            assert check_refmodels_pin.main(["--check"]) == 1
        assert "Could not find" in capsys.readouterr().out

    def test_explicit_channel_pin_must_match(self, tmp_path):
        assert self._run(["--check"], tag="1.29.0", channel="v1.29.0", tmp_path=tmp_path) == 0
        assert self._run(["--check"], tag="1.28.1", channel="v1.29.0", tmp_path=tmp_path) == 1


class TestUpdateRewrite:
    def test_rewrites_both_the_tag_and_the_wheel_filename(self, tmp_path):
        """The version appears twice in the URL; rewriting one produces a 404 pin."""
        pyproject = tmp_path / "pyproject.toml"
        with pyproject.open("w", encoding="utf-8", newline="") as fh:
            fh.write(_pyproject("1.20.0"))
        with (
            mock.patch.object(check_refmodels_pin, "PYPROJECT", pyproject),
            mock.patch.object(check_refmodels_pin, "latest_release", return_value="v1.33.1"),
            mock.patch.object(
                check_refmodels_pin.subprocess, "run",
                return_value=mock.MagicMock(returncode=0, stderr=""),
            ),
        ):
            assert check_refmodels_pin.main(["--update"]) == 0

        text = pyproject.read_text(encoding="utf-8")
        assert "download/v1.33.1/" in text
        assert "kairos_ontology_referencemodels-1.33.1-py3-none-any.whl" in text
        assert "1.20.0" not in text

    def test_preserves_crlf_line_endings(self, tmp_path):
        """``write_text`` translated newlines, turning a pin bump into a whole-file diff.

        Caught on Windows: read-then-write in default text mode rewrote every LF as CRLF,
        so `--update` produced a 178-line diff for a one-token change.
        """
        pyproject = tmp_path / "pyproject.toml"
        original = _pyproject("1.20.0").replace("\n", "\r\n")
        with pyproject.open("w", encoding="utf-8", newline="") as fh:
            fh.write(original)
        with (
            mock.patch.object(check_refmodels_pin, "PYPROJECT", pyproject),
            mock.patch.object(check_refmodels_pin, "latest_release", return_value="v1.33.1"),
            mock.patch.object(
                check_refmodels_pin.subprocess, "run",
                return_value=mock.MagicMock(returncode=0, stderr=""),
            ),
        ):
            check_refmodels_pin.main(["--update"])

        raw = pyproject.read_bytes()
        assert b"\r\n" in raw
        assert raw.count(b"\r\n") == original.count("\r\n")
        assert b"\n" not in raw.replace(b"\r\n", b"")  # no bare LF introduced

    def test_lock_failure_is_reported_as_failure(self, tmp_path, capsys):
        pyproject = tmp_path / "pyproject.toml"
        with pyproject.open("w", encoding="utf-8", newline="") as fh:
            fh.write(_pyproject("1.20.0"))
        with (
            mock.patch.object(check_refmodels_pin, "PYPROJECT", pyproject),
            mock.patch.object(check_refmodels_pin, "latest_release", return_value="v1.33.1"),
            mock.patch.object(
                check_refmodels_pin.subprocess, "run",
                return_value=mock.MagicMock(returncode=1, stderr="boom"),
            ),
        ):
            assert check_refmodels_pin.main(["--update"]) == 1
        assert "uv lock` failed" in capsys.readouterr().out


class TestCiWiring:
    """A pin check nobody runs leaves #541 exactly as it was."""

    def test_ci_runs_the_check(self):
        workflow = _CI_WORKFLOW.read_text(encoding="utf-8")
        assert "scripts/check_refmodels_pin.py --check" in workflow

    def test_the_check_is_its_own_job_with_a_token(self):
        workflow = _CI_WORKFLOW.read_text(encoding="utf-8")
        assert re.search(r"^  refmodels-pin:$", workflow, re.MULTILINE), (
            "the pin check must be a separate job so it cannot mask a test failure"
        )
        assert "GH_TOKEN:" in workflow, (
            "unauthenticated runs degrade to a pass, so the check would mean nothing"
        )


def test_script_is_executable_end_to_end():
    """Smoke test: the real script runs against the real pyproject without crashing.

    Exercises the import path (``sys.path`` insertion, shared-resolver import) that the
    mocked tests above bypass. Network-dependent, so any exit code but a crash is fine.
    """
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=_REPO_ROOT,
    )
    assert result.returncode in (0, 1), result.stderr
    assert "Traceback" not in result.stderr, result.stderr
