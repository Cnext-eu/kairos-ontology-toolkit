#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Mechanical git/gh choreography for the SC-merge-pr skill.

The SC-merge-pr skill (.claude/skills/SC-merge-pr/SKILL.md) keeps judgment
calls in prose (commit wording, rebase-conflict resolution, the security
review, which issues a PR "fully resolves", PR title/body prose, whether to
ship a release and which bump size) and delegates everything mechanical here.

Usage:
    python scripts/finish_pr.py pre-pr --check [--dry-run]
    python scripts/finish_pr.py pre-pr --push [--dry-run]
    python scripts/finish_pr.py pre-pr --create --title T --body-bullet B [--body-bullet B ...]
        [--closes N ...] [--follow-up N ...] [--dry-run]
    python scripts/finish_pr.py post-merge --merge [--dry-run]
    python scripts/finish_pr.py post-merge --cleanup [--dry-run]
    python scripts/finish_pr.py tag-release --bump patch|minor|major [--dry-run]
    python scripts/finish_pr.py tag-release --tag [--dry-run]

Flags:
    --dry-run   Print what would run instead of calling git/gh.
"""

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INIT_PY = REPO_ROOT / "src" / "kairos_ontology" / "__init__.py"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

_BUMP_KINDS = ("patch", "minor", "major", "rc")


def _run(args: list[str], *, dry_run: bool, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess:
    if dry_run:
        print(f"  [dry-run] would run: {' '.join(args)}")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def check_branch_and_status(*, dry_run: bool = False) -> tuple[str, bool]:
    """Return (current branch, is_clean)."""
    branch = _run(["git", "branch", "--show-current"], dry_run=dry_run).stdout.strip()
    status = _run(["git", "status", "--porcelain"], dry_run=dry_run).stdout
    return branch or "(dry-run)", not status.strip()


def push_branch(branch: str, *, dry_run: bool = False) -> bool:
    result = _run(["git", "push", "-u", "origin", branch], dry_run=dry_run)
    return dry_run or result.returncode == 0


def render_pr_body(
    bullets: list[str], closes: list[int], follow_ups: list[int] | None = None
) -> str:
    """Render the PR body template — structure only; content is supplied by the caller.

    Closing keywords (Closes/Fixes/Resolves #NNN) go one per issue, in the
    body, per GitHub's auto-close contract — a bare title/plain-#NNN reference
    does NOT auto-close on merge. Follow-up issues are referenced without a
    keyword so they stay open.
    """
    lines = ["## Changes", ""]
    lines.extend(f"- {bullet}" for bullet in bullets)
    lines.append("")
    lines.append("## Closes")
    lines.extend(f"Closes #{n}" for n in closes)
    for n in follow_ups or ():
        lines.append(f"Follow-up: #{n}")
    lines.append("")
    lines.append("## Checklist")
    lines.append(
        "- [ ] Closing keywords (`Closes/Fixes/Resolves #NNN`) added for every issue "
        "this PR fully fixes"
    )
    lines.append("- [ ] `python -m kairos_ontology validate` passes")
    lines.append("- [ ] `python -m kairos_ontology project` regenerated (if ontology changed)")
    lines.append("- [ ] Security review passed (no path traversal, no secrets, no shell=True)")
    return "\n".join(lines) + "\n"


def create_pr(title: str, body: str, *, base: str = "main", dry_run: bool = False) -> str | None:
    result = _run(
        ["gh", "pr", "create", "--base", base, "--title", title, "--body", body],
        dry_run=dry_run,
    )
    if dry_run:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def merge_pr(*, dry_run: bool = False) -> bool:
    result = _run(["gh", "pr", "merge", "--squash", "--delete-branch"], dry_run=dry_run)
    return dry_run or result.returncode == 0


def cleanup_local_branch(branch: str, *, dry_run: bool = False) -> None:
    _run(["git", "checkout", "main"], dry_run=dry_run)
    _run(["git", "pull", "origin", "main"], dry_run=dry_run)
    _run(["git", "branch", "-d", branch], dry_run=dry_run)


def _bump(version: str, kind: str) -> str:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(.*)$", version)
    if not match:
        raise ValueError(f"Cannot parse version {version!r} as MAJOR.MINOR.PATCH[suffix]")
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    if kind == "major":
        major, minor, patch = major + 1, 0, 0
        return f"{major}.{minor}.{patch}"
    if kind == "minor":
        minor, patch = minor + 1, 0
        return f"{major}.{minor}.{patch}"
    if kind == "patch":
        patch += 1
        return f"{major}.{minor}.{patch}"
    if kind == "rc":
        rc_match = re.match(r"^rc(\d+)$", match.group(4))
        if not rc_match:
            raise ValueError(
                f"{version!r} has no 'rcN' suffix to bump — an rc bump only increments an "
                "existing release candidate (e.g. 5.1.0rc3 -> 5.1.0rc4). To start a new rc "
                "series, bump patch/minor/major first and append 'rc1' to the result yourself."
            )
        return f"{major}.{minor}.{patch}rc{int(rc_match.group(1)) + 1}"
    raise ValueError(f"Unknown bump kind {kind!r}; expected one of {_BUMP_KINDS}")


def bump_version(
    kind: str,
    *,
    init_py: Path = INIT_PY,
    changelog: Path = CHANGELOG,
    today: str | None = None,
    dry_run: bool = False,
) -> str:
    """Bump ``__version__`` in *init_py*.

    For ``patch``/``minor``/``major``, also promotes CHANGELOG's
    ``[Unreleased]`` heading to a dated ``[X.Y.Z]`` one — release.yml requires
    that heading for non-prerelease tags. For ``rc``, CHANGELOG is left
    untouched: version-check.yml explicitly makes a CHANGELOG entry optional
    for prerelease (rc/beta/alpha) versions, and this repo's own history
    (rc2 -> rc3) confirms rc bumps don't promote `[Unreleased]` — everything
    stays there until the final non-rc release.

    Returns the new version string. ``today`` defaults to the real current
    date; tests should pass an explicit value.
    """
    init_text = init_py.read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', init_text, flags=re.MULTILINE)
    if not match:
        raise ValueError(f"Could not find __version__ in {init_py}")
    new_version = _bump(match.group(1), kind)

    if kind == "rc":
        if dry_run:
            print(f"  [dry-run] would bump __version__ to {new_version!r} in {init_py}")
            print("  [dry-run] CHANGELOG.md left untouched (rc bump)")
            return new_version
        init_py.write_text(
            init_text.replace(match.group(0), f'__version__ = "{new_version}"'), encoding="utf-8"
        )
        return new_version

    changelog_text = changelog.read_text(encoding="utf-8")
    if "## [Unreleased]" not in changelog_text:
        raise ValueError(f"Could not find '## [Unreleased]' heading in {changelog}")
    stamp = today or date.today().isoformat()
    promoted = changelog_text.replace(
        "## [Unreleased]",
        f"## [Unreleased]\n\n## [{new_version}] — {stamp}",
        1,
    )

    if dry_run:
        print(f"  [dry-run] would bump __version__ to {new_version!r} in {init_py}")
        print(f"  [dry-run] would promote CHANGELOG [Unreleased] to [{new_version}] — {stamp}")
        return new_version

    init_py.write_text(
        init_text.replace(match.group(0), f'__version__ = "{new_version}"'), encoding="utf-8"
    )
    changelog.write_text(promoted, encoding="utf-8")
    return new_version


def tag_release(version: str, *, dry_run: bool = False) -> None:
    tag = f"v{version}"
    _run(["git", "tag", "-a", tag, "-m", f"Release {tag}"], dry_run=dry_run)
    _run(["git", "push", "origin", tag], dry_run=dry_run)


def _flag_value(argv: list[str], name: str) -> str | None:
    if name in argv:
        idx = argv.index(name)
        if idx + 1 < len(argv):
            return argv[idx + 1]
    return None


def _flag_values(argv: list[str], name: str) -> list[str]:
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == name and i + 1 < len(argv)]


def _ensure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 (mirrors cli/shared.py's helper).

    Prevents ``UnicodeEncodeError`` when this script prints ✅/❌ on a Windows
    console using a legacy code page (cp1252/cp437).
    """
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _ensure_utf8_stdio()
    argv = sys.argv[1:]
    if not argv:
        print("Usage: finish-pr.py <pre-pr|post-merge|tag-release> [flags]")
        return 2
    subcommand, rest = argv[0], argv[1:]
    dry_run = "--dry-run" in rest

    if subcommand == "pre-pr":
        if "--check" in rest:
            branch, clean = check_branch_and_status(dry_run=dry_run)
            print(f"  Branch: {branch}")
            print(f"  Clean:  {clean}")
            if branch == "main":
                print("  ❌ On main — switch to a feature branch first.")
                return 1
            if not clean:
                print("  ⚠️  Uncommitted changes present — commit or stash first.")
            return 0
        if "--push" in rest:
            branch, _ = check_branch_and_status(dry_run=dry_run)
            ok = push_branch(branch, dry_run=dry_run)
            print("  ✅ Pushed" if ok else "  ❌ Push failed")
            return 0 if ok else 1
        if "--create" in rest:
            title = _flag_value(rest, "--title")
            bullets = _flag_values(rest, "--body-bullet")
            closes = [int(n) for n in _flag_values(rest, "--closes")]
            follow_ups = [int(n) for n in _flag_values(rest, "--follow-up")]
            if not title:
                print("  ❌ --create requires --title")
                return 2
            body = render_pr_body(bullets, closes, follow_ups)
            url = create_pr(title, body, dry_run=dry_run)
            if dry_run:
                print("  [dry-run] would create PR with body:\n" + body)
                return 0
            print(f"  ✅ PR created: {url}" if url else "  ❌ PR creation failed")
            return 0 if url else 1
        print("  ❌ pre-pr requires one of --check, --push, --create")
        return 2

    if subcommand == "post-merge":
        if "--merge" in rest:
            ok = merge_pr(dry_run=dry_run)
            print("  ✅ Merged" if ok else "  ❌ Merge failed")
            return 0 if ok else 1
        if "--cleanup" in rest:
            branch, _ = check_branch_and_status(dry_run=dry_run)
            cleanup_local_branch(branch, dry_run=dry_run)
            print("  ✅ Local branch cleaned up")
            return 0
        print("  ❌ post-merge requires one of --merge, --cleanup")
        return 2

    if subcommand == "tag-release":
        bump_kind = _flag_value(rest, "--bump")
        if bump_kind:
            if bump_kind not in _BUMP_KINDS:
                print(f"  ❌ --bump must be one of {_BUMP_KINDS}")
                return 2
            new_version = bump_version(bump_kind, dry_run=dry_run)
            print(f"  ✅ Bumped to {new_version}")
            return 0
        if "--tag" in rest:
            init_text = INIT_PY.read_text(encoding="utf-8")
            match = re.search(r'^__version__ = "([^"]+)"$', init_text, flags=re.MULTILINE)
            if not match:
                print(f"  ❌ Could not find __version__ in {INIT_PY}")
                return 1
            tag_release(match.group(1), dry_run=dry_run)
            print(f"  ✅ Tagged v{match.group(1)}")
            return 0
        print("  ❌ tag-release requires --bump <patch|minor|major> or --tag")
        return 2

    print(f"  ❌ Unknown subcommand {subcommand!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
