#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Sync .github/ skills and copilot-instructions to scaffold/.

Direction: .github/ (master) → scaffold/ (distribution copy)

This ensures the scaffold (distributed to hub repos via `update`) always
matches the working copies used by Copilot in this repo.

Usage:
    python scripts/sync-dev-skills.py [--check]

Flags:
    --check   Report drift without modifying files (exit 1 if out of sync)
"""

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GITHUB_SKILLS = REPO_ROOT / ".github" / "skills"
SCAFFOLD_SKILLS = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "skills"
GITHUB_INSTRUCTIONS = REPO_ROOT / ".github" / "copilot-instructions.md"
SCAFFOLD_INSTRUCTIONS = (
    REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "copilot-instructions.md"
)


def get_sync_pairs() -> list[tuple[Path, Path]]:
    """Build the list of (source, destination) file pairs to sync."""
    pairs: list[tuple[Path, Path]] = []

    # copilot-instructions.md
    if GITHUB_INSTRUCTIONS.exists():
        pairs.append((GITHUB_INSTRUCTIONS, SCAFFOLD_INSTRUCTIONS))

    # All SKILL.md files in .github/skills/
    if GITHUB_SKILLS.is_dir():
        for skill_dir in sorted(GITHUB_SKILLS.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                dest = SCAFFOLD_SKILLS / skill_dir.name / "SKILL.md"
                pairs.append((skill_file, dest))

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
    """Copy .github/ → scaffold/ for all managed files. Returns changed pairs."""
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
            print("✅ .github/ and scaffold/ are in sync.")
            return 0
    else:
        changed = sync()
        if changed:
            print(f"✅ Synced {len(changed)} file(s) from .github/ → scaffold/:")
            for src, dst in changed:
                print(f"   {dst.relative_to(REPO_ROOT)}")
        else:
            print("✅ Already in sync — nothing to copy.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
