#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Sync .claude/ skills, copilot-instructions and the user guides to scaffold/.

Direction: .claude/skills/ (master) → scaffold/skills/ (distribution copy)
           .github/copilot-instructions.md (master) → scaffold/ (distribution copy)
           docs/<user guides> (master) → scaffold/docs/ (distribution copy)

.claude/skills/ is the authored source for skills — read directly by Claude Code
and by GitHub Copilot's Agent Skills support (since Copilot's December 2025
release), so one tree serves both tools. scaffold/ is what `update` distributes
to hub and dataplatform repos.

Usage:
    python scripts/sync-dev-skills.py [--check]

Flags:
    --check   Report drift without modifying files (exit 1 if out of sync)
"""

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_SKILLS = REPO_ROOT / ".claude" / "skills"
SCAFFOLD_SKILLS = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "skills"
GITHUB_INSTRUCTIONS = REPO_ROOT / ".github" / "copilot-instructions.md"
SCAFFOLD_INSTRUCTIONS = (
    REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "copilot-instructions.md"
)
DOCS = REPO_ROOT / "docs" / "guide"
SCAFFOLD_DOCS = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "docs"

#: The operator-facing guides shipped into every scaffolded hub (#739). An **allowlist**,
#: not "docs/ minus exclusions": `docs/` also holds the decision log, the architecture
#: record, DD-133, RELEASING.md and the practitioner/MDM material, none of which a hub
#: operator needs and all of which describe *this* repository. Adding a file here puts it
#: in every client hub on the next `update`, so the addition is a deliberate act.
#:
#: Kept flat except for `how-to/`, whose README is the recipe index. These are copied
#: verbatim by `_copy_managed`, so any cross-link they carry to a document outside this
#: list must be an absolute URL — a relative `../design/...` would dangle in the hub.
_USER_DOCS = (
    "USER_GUIDE.md",
    "CLI_REFERENCE.md",
    "CONSUMING_COMPILE_PLAN.md",
)

# Skill directories under .claude/skills/ that are contributor-workflow skills
# for this repo, not part of the kairos-* scaffold shipped to hub/dataplatform
# repos, and must never be synced to the scaffold. "synced" is also a name
# Claude Code reserves for claude.ai account sync and would never be authored here.
#: Skills that stay in this repository and are never shipped to a scaffolded hub or
#: dataplatform. `kairos-toolkit-dev` and `kairos-toolkit-dogfood` are maintainer
#: activities aimed at *this* repository -- dogfood is explicitly adversarial, hunting
#: toolkit gaps using a client's data -- so installing them in a client repo added 314
#: lines of irrelevant instruction and, worse, left them selectable by an agent working
#: there. `kairos-toolkit-ops` is deliberately absent from this set: clients do use it
#: to upgrade their toolkit pin, and it is in the dataplatform subset too.
_UNMANAGED_SKILL_DIRS = {
    "synced",
    "langfuse",
    "kairos-toolkit-dev",
    "kairos-toolkit-dogfood",
    # Cnext-internal, not client-facing. `SC-merge-pr` documents *this* repository's
    # release process -- `scripts/finish_pr.py`, bumping `src/kairos_ontology/__init__.py`
    # -- neither of which exists in a scaffolded repo; it shipped with a paragraph telling
    # the reader not to apply it there, which is a caveat working around a packaging
    # mistake. `SC-document` drives a Cnext Outline workspace and needs `OUTLINE_API_KEY`.
    "SC-merge-pr",
    "SC-document",
    # MDM is designed but not adopted -- see docs/dev/mdm/README.md. Shipping an authoring
    # skill for a capability no hub runs invites an agent to author policy nothing
    # consumes. The CLI surface (`mdm-validate`, optional CompilePlan policy) stays;
    # restore this skill to the scaffold when MDM goes live.
    "kairos-design-mdm",
}


# The status output below uses non-ASCII marks, and this script runs from a Git
# pre-commit hook where stdout is a legacy-codepage Windows console -- there, printing
# them raises UnicodeEncodeError and the hook fails for a cosmetic reason.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def get_sync_pairs() -> list[tuple[Path, Path]]:
    """Build the list of (source, destination) file pairs to sync."""
    pairs: list[tuple[Path, Path]] = []

    # copilot-instructions.md
    if GITHUB_INSTRUCTIONS.exists():
        pairs.append((GITHUB_INSTRUCTIONS, SCAFFOLD_INSTRUCTIONS))

    # All SKILL.md files and exemplar files (.ttl) in .claude/skills/
    if CLAUDE_SKILLS.is_dir():
        for skill_dir in sorted(CLAUDE_SKILLS.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name in _UNMANAGED_SKILL_DIRS:
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            pairs.append((skill_file, SCAFFOLD_SKILLS / skill_dir.name / "SKILL.md"))
            # Exemplar artefacts (TTL, SHACL, etc.) shipped alongside the skill
            extra_globs = [
                *skill_dir.glob("*-domain.ttl"),
                *skill_dir.glob("*-domain.shacl.ttl"),
                *skill_dir.glob("exemplar-binding.yaml"),
            ]
            for extra in sorted(extra_globs):
                pairs.append((extra, SCAFFOLD_SKILLS / skill_dir.name / extra.name))

    # User guides (#739): shipped into the hub as managed files so a hub operator has the
    # documentation locally, without needing read access to this repository.
    for name in _USER_DOCS:
        source = DOCS / name
        if source.is_file():
            pairs.append((source, SCAFFOLD_DOCS / name))
    how_to = DOCS / "how-to"
    if how_to.is_dir():
        for source in sorted(how_to.glob("*.md")):
            pairs.append((source, SCAFFOLD_DOCS / "how-to" / source.name))

    return pairs


def check_drift() -> list[tuple[Path, Path]]:
    """Return list of (source, dest) pairs that are out of sync."""
    drifted = []
    for src, dst in get_sync_pairs():
        if not dst.exists():
            drifted.append((src, dst))
            continue
        if src.read_bytes() != dst.read_bytes():
            drifted.append((src, dst))
    return drifted


def sync() -> list[tuple[Path, Path]]:
    """Copy .claude/skills/ → scaffold/skills/ for all managed files. Returns changed pairs."""
    changed = []
    for src, dst in get_sync_pairs():
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or src.read_bytes() != dst.read_bytes():
            shutil.copy2(src, dst)
            changed.append((src, dst))
    return changed


def main() -> int:
    check_only = "--check" in sys.argv

    if check_only:
        drifted = check_drift()
        if drifted:
            print(f"❌ Scaffold drift detected ({len(drifted)} file(s)):")
            for src, dst in drifted:
                print(f"   {src.relative_to(REPO_ROOT)} → {dst.relative_to(REPO_ROOT)}")
            print("\nRun: python scripts/sync-dev-skills.py")
            return 1
        else:
            print("✅ .claude/ and scaffold/ are in sync.")
            return 0
    else:
        changed = sync()
        if changed:
            print(f"✅ Synced {len(changed)} file(s) from .claude/ → scaffold/:")
            for src, dst in changed:
                print(f"   {dst.relative_to(REPO_ROOT)}")
        else:
            print("✅ Already in sync — nothing to copy.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
