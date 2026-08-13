# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the `guard-scope` deterministic workspace-scope guard."""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.cli.main import cli

REPO_ROOT = Path(__file__).resolve().parent.parent

# The realistic layout `kairos-ontology init` produces: the hub is a *subdirectory*
# of the repo, so every porcelain path carries an `ontology-hub/` prefix that a
# hub-relative --allow glob has to survive (#329).
HUB_DIR = "ontology-hub"
BOOKING = f"{HUB_DIR}/model/ontologies/booking.ttl"
BOOKING_ALLOW = "*model/ontologies/booking.ttl"


def _git(repo_dir, *args):
    subprocess.run(["git", *args], cwd=repo_dir, check=True)


def _init_repo(repo_dir):
    _git(repo_dir, "init", "-q")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Test")
    tracked = repo_dir / BOOKING
    tracked.parent.mkdir(parents=True)
    tracked.write_text("initial", encoding="utf-8")
    _git(repo_dir, "add", "-A")
    _git(repo_dir, "commit", "-q", "-m", "init")
    return tracked


def _snapshot(*ignored_roots):
    args = ["guard-scope", "--snapshot"]
    for root in ignored_roots:
        args += ["--ignored-root", root]
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    return result.output.strip()


def _check(token, *allow_globs):
    args = ["guard-scope", "--check-since", token]
    for glob in allow_globs:
        args += ["--allow", glob]
    return CliRunner().invoke(cli, args)


def _offending(result) -> set[str]:
    """The exact set of paths the guard named, from its indented failure list."""
    return {
        line[3:]
        for line in result.output.splitlines()
        if line.startswith("   ") and not line.startswith("   HEAD moved")
    }


def test_snapshot_writes_token_path(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["guard-scope", "--snapshot"])

    assert result.exit_code == 0
    token_path = Path(result.output.strip())
    assert token_path.is_absolute()
    assert token_path.exists()
    assert tmp_path not in token_path.parents  # token lives outside the repo, in OS temp


def test_check_passes_with_only_allowed_change(tmp_path, monkeypatch):
    tracked = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    token = _snapshot()

    tracked.write_text("changed", encoding="utf-8")

    check = _check(token, BOOKING_ALLOW)

    assert check.exit_code == 0, check.output
    assert "passed" in check.output
    assert not Path(token).exists()  # token cleaned up on success


def test_check_fails_on_extra_untracked_file_outside_allowlist(tmp_path, monkeypatch):
    tracked = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    token = _snapshot()

    tracked.write_text("changed", encoding="utf-8")
    (tmp_path / "unexpected.txt").write_text("surprise", encoding="utf-8")

    check = _check(token, BOOKING_ALLOW)

    assert check.exit_code != 0
    assert "unexpected.txt" in check.output


def test_check_fails_on_extra_modified_tracked_file_outside_allowlist(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    other_file = tmp_path / "other.txt"
    other_file.write_text("original", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "add other")
    monkeypatch.chdir(tmp_path)

    token = _snapshot()

    other_file.write_text("unexpectedly modified", encoding="utf-8")

    check = _check(token, BOOKING_ALLOW)

    assert check.exit_code != 0
    assert "other.txt" in check.output


def test_check_passes_with_no_changes_and_no_allow(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    token = _snapshot()

    check = _check(token)

    assert check.exit_code == 0


def test_requires_exactly_one_mode(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    neither = CliRunner().invoke(cli, ["guard-scope"])
    assert neither.exit_code == 2
    assert "exactly one" in neither.output


def test_allow_without_check_since_rejected(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli, ["guard-scope", "--snapshot", "--allow", "*.ttl"])
    assert result.exit_code == 2
    assert "only valid with --check-since" in result.output


def test_help_states_that_gitignored_paths_are_out_of_scope():
    """#312: `validate` writes under a gitignored tree the guard cannot see."""
    help_text = CliRunner().invoke(cli, ["guard-scope", "--help"]).output

    assert "gitignored" in help_text


# --- #323: the baseline must be dirty-state-aware, not a set of path names ----


def test_further_change_to_already_dirty_tracked_file_is_reported(tmp_path, monkeypatch):
    """A file dirty *at snapshot time* may not be edited without limit (#323)."""
    tracked = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    tracked.write_text("dirty before the snapshot", encoding="utf-8")
    token = _snapshot()

    tracked.write_text("edited again inside the guarded window", encoding="utf-8")

    check = _check(token)

    assert check.exit_code != 0
    assert BOOKING in check.output


def test_further_change_to_already_dirty_untracked_file_is_reported(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    stray = tmp_path / "scratch.txt"
    stray.write_text("present and untracked before the snapshot", encoding="utf-8")
    token = _snapshot()

    stray.write_text("rewritten inside the guarded window", encoding="utf-8")

    check = _check(token)

    assert check.exit_code != 0
    assert "scratch.txt" in check.output


def test_staging_an_already_dirty_file_is_reported(tmp_path, monkeypatch):
    """`git add` leaves the bytes identical but moves " M" to "M " — a status-code-only change."""
    tracked = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    tracked.write_text("dirty before the snapshot", encoding="utf-8")
    token = _snapshot()

    _git(tmp_path, "add", BOOKING)

    check = _check(token)

    assert check.exit_code != 0
    assert BOOKING in check.output


def test_deleting_an_already_dirty_file_is_reported(tmp_path, monkeypatch):
    """ " M" to " D": the path never leaves the output, so a path-set diff is blind to it."""
    tracked = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    tracked.write_text("dirty before the snapshot", encoding="utf-8")
    token = _snapshot()

    tracked.unlink()

    check = _check(token)

    assert check.exit_code != 0
    assert BOOKING in check.output


def test_deleting_an_already_dirty_untracked_file_is_reported(tmp_path, monkeypatch):
    """The path *leaves* git's output entirely — only a symmetric compare sees it."""
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    stray = tmp_path / "scratch.txt"
    stray.write_text("present and untracked before the snapshot", encoding="utf-8")
    token = _snapshot()

    stray.unlink()

    check = _check(token)

    assert check.exit_code != 0
    assert "scratch.txt" in check.output


def test_renaming_an_already_dirty_file_reports_the_vacated_path(tmp_path, monkeypatch):
    """`-z` emits ``R  NEW`` then a separate ``OLD`` field — both sides must be recorded."""
    _init_repo(tmp_path)
    other_file = tmp_path / "other.txt"
    other_file.write_text("original", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "add other")
    monkeypatch.chdir(tmp_path)

    other_file.write_text("dirty before the snapshot", encoding="utf-8")
    token = _snapshot()

    _git(tmp_path, "mv", "other.txt", "renamed.txt")

    check = _check(token, "*renamed.txt")

    assert check.exit_code != 0
    # Exactly the vacated path: a parser that mistook the bare OLD field for a
    # second "XY PATH" record would additionally report the slice "er.txt".
    assert _offending(check) == {"other.txt"}


def test_dirty_baseline_left_untouched_still_passes(tmp_path, monkeypatch):
    """The regression guard: pre-existing dirt is the baseline, not an offence."""
    tracked = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    tracked.write_text("dirty before the snapshot", encoding="utf-8")
    (tmp_path / "scratch.txt").write_text("untracked before the snapshot", encoding="utf-8")
    token = _snapshot()

    check = _check(token)

    assert check.exit_code == 0, check.output
    assert "passed" in check.output


def test_commit_inside_the_window_is_reported(tmp_path, monkeypatch):
    """A commit empties the status output; only a recorded HEAD sha catches it."""
    tracked = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    tracked.write_text("dirty before the snapshot", encoding="utf-8")
    token = _snapshot()

    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "sneaky commit inside the guarded window")

    # Even with the edited path explicitly allowed, the moved HEAD must fail.
    check = _check(token, BOOKING_ALLOW)

    assert check.exit_code != 0
    assert "HEAD moved" in check.output


def test_directory_entry_yields_a_verdict_rather_than_a_crash(tmp_path, monkeypatch):
    """An embedded git repo surfaces as `?? nested/` — a path with no file to hash."""
    tracked = _init_repo(tmp_path)
    nested = tmp_path / "nested"
    nested.mkdir()
    _git(nested, "init", "-q")
    (nested / "inner.txt").write_text("inner", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    token = _snapshot()

    assert _check(token).exit_code == 0  # untouched directory entry is baseline, not an offence

    token = _snapshot()
    tracked.write_text("changed", encoding="utf-8")
    check = _check(token)

    assert check.exit_code != 0
    assert _offending(check) == {BOOKING}  # a real verdict, not a traceback


# --- non-ASCII paths: porcelain v1 quotes and octal-escapes them --------------

EN_DASH_REL = f"{HUB_DIR}/model/bi/Fee – Actual.ttl"


def test_non_ascii_path_is_reported_verbatim_and_matchable_by_a_glob(tmp_path, monkeypatch):
    en_dash = tmp_path / EN_DASH_REL
    _init_repo(tmp_path)
    en_dash.parent.mkdir(parents=True)
    en_dash.write_text("initial", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "add a report with an en dash in its name")
    monkeypatch.chdir(tmp_path)

    token = _snapshot()
    en_dash.write_text("changed", encoding="utf-8")

    check = _check(token)
    assert check.exit_code != 0
    # The real path, not `"ontology-hub/model/bi/Fee \342\200\223 Actual.ttl"`.
    assert EN_DASH_REL in check.output
    assert "\\342" not in check.output

    token = _snapshot()
    en_dash.write_text("changed again", encoding="utf-8")
    assert _check(token, "*bi/*").exit_code == 0


# --- token format ------------------------------------------------------------


def test_legacy_token_is_rejected_rather_than_misparsed(tmp_path, monkeypatch):
    """An unrecognised token must hard-error: a misread baseline reports a pass."""
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    legacy = tmp_path.parent / "legacy-token.txt"
    legacy.write_text(" M ontology-hub/model/ontologies/booking.ttl\n", encoding="utf-8")

    check = _check(str(legacy))

    assert check.exit_code != 0
    assert "token format" in check.output


def test_token_carries_a_format_marker_on_its_first_line(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    token = Path(_snapshot())

    assert token.read_text(encoding="utf-8").splitlines()[0] == "kairos-guard-scope/1"


# --- running from inside the hub ---------------------------------------------


def test_check_works_when_run_from_inside_the_hub(tmp_path, monkeypatch):
    """Porcelain paths are repo-root-relative; resolving them against cwd doubles the prefix."""
    tracked = _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path / HUB_DIR)

    tracked.write_text("dirty before the snapshot", encoding="utf-8")
    token = _snapshot()

    tracked.write_text("edited again inside the guarded window", encoding="utf-8")

    check = _check(token)

    assert check.exit_code != 0
    assert BOOKING in check.output


# --- #329: the published --allow globs must match a real hub-layout path ------


@pytest.mark.parametrize(
    ("skill", "placeholders", "sample_path"),
    [
        (
            "kairos-design-domain",
            {"<domain>": "booking"},
            f"{HUB_DIR}/model/ontologies/booking.ttl",
        ),
        (
            "kairos-design-mapping",
            {"<source>": "erp", "<domain>": "booking"},
            f"{HUB_DIR}/integration/bindings/erp-to-booking.binding.yaml",
        ),
    ],
)
def test_published_skill_allow_glob_matches_a_real_hub_path(skill, placeholders, sample_path):
    """Extracted from SKILL.md, not retyped — a re-word that breaks the glob fails here."""
    text = (REPO_ROOT / ".github" / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
    globs = re.findall(r'guard-scope --check-since <token> --allow "([^"]+)"', text)
    assert globs, f"no guard-scope --allow glob found in {skill}/SKILL.md"

    for glob in globs:
        for placeholder, value in placeholders.items():
            glob = glob.replace(placeholder, value)
        assert fnmatch.fnmatch(sample_path, glob), (
            f"{skill}: --allow {glob!r} cannot match the repo-root-relative "
            f"path {sample_path!r} that `git status --porcelain` emits"
        )
        # …and it must still match a hub whose model/ sits at the repo root.
        root_layout = sample_path[len(HUB_DIR) + 1 :]
        assert fnmatch.fnmatch(root_layout, glob), (
            f"{skill}: --allow {glob!r} cannot match the root-hub layout {root_layout!r}"
        )


# --- #312: opt-in visibility into gitignored paths via --ignored-root --------

IGNORED_DIR = "ontology-hub-publish"
IGNORED_FILE_REL = f"{IGNORED_DIR}/validation-report.json"


def _init_repo_with_ignored_publish_dir(repo_dir):
    """Like _init_repo, but also scaffolds the real hub .gitignore shape for
    ontology-hub-publish/: directories are explicitly un-ignored so only the
    files within are ignored (required for git to report them individually
    under --ignored=matching rather than collapsing the whole directory)."""
    tracked = _init_repo(repo_dir)
    gitignore = repo_dir / ".gitignore"
    gitignore.write_text(
        f"{IGNORED_DIR}/**\n!{IGNORED_DIR}/**/\n!{IGNORED_DIR}/**/.gitkeep\n",
        encoding="utf-8",
    )
    _git(repo_dir, "add", "-A")
    _git(repo_dir, "commit", "-q", "-m", "scaffold gitignore for the publish dir")
    return tracked


def _write_ignored_report(repo_dir):
    ignored_file = repo_dir / IGNORED_FILE_REL
    ignored_file.parent.mkdir(parents=True, exist_ok=True)
    ignored_file.write_text('{"passed": true}', encoding="utf-8")
    return ignored_file


def test_write_into_gitignored_path_is_invisible_without_opt_in(tmp_path, monkeypatch):
    """Documents the gap #312 reports: with no --ignored-root, a write landing in
    a gitignored tree (e.g. validate's report) is completely invisible to the guard."""
    _init_repo_with_ignored_publish_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    token = _snapshot()  # no --ignored-root

    _write_ignored_report(tmp_path)

    check = _check(token)
    assert check.exit_code == 0, check.output


def test_write_into_opted_in_ignored_root_is_detected_and_named(tmp_path, monkeypatch):
    _init_repo_with_ignored_publish_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    token = _snapshot(IGNORED_DIR)

    _write_ignored_report(tmp_path)

    check = _check(token)

    assert check.exit_code != 0
    assert IGNORED_FILE_REL in check.output


def test_write_into_opted_in_ignored_root_passes_when_allowed(tmp_path, monkeypatch):
    _init_repo_with_ignored_publish_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    token = _snapshot(IGNORED_DIR)

    _write_ignored_report(tmp_path)

    check = _check(token, f"{IGNORED_DIR}/*.json")

    assert check.exit_code == 0, check.output


def test_ignored_root_combined_with_check_since_is_a_usage_error(tmp_path, monkeypatch):
    _init_repo_with_ignored_publish_dir(tmp_path)
    monkeypatch.chdir(tmp_path)

    token = _snapshot()

    result = CliRunner().invoke(
        cli,
        ["guard-scope", "--check-since", token, "--ignored-root", IGNORED_DIR],
    )

    assert result.exit_code == 2
    assert "only valid with --snapshot" in result.output


def test_old_token_without_ignored_roots_key_still_parses_and_works(tmp_path, monkeypatch):
    """A token written before --ignored-root existed lacks the key entirely; it must
    still parse and behave exactly as it did before (empty ignored scope)."""
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    old_token_path = tmp_path.parent / "pre-ignored-roots-token.txt"
    old_token_path.write_text(
        "kairos-guard-scope/1\n" + json.dumps({"head": head, "entries": {}}),
        encoding="utf-8",
    )

    check = _check(str(old_token_path))

    assert check.exit_code == 0, check.output


def test_help_documents_the_ignored_root_opt_in():
    help_text = CliRunner().invoke(cli, ["guard-scope", "--help"]).output
    assert "--ignored-root" in help_text
