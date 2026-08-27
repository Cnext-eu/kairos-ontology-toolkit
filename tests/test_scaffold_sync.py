# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Test that .claude/skills/ and copilot-instructions match scaffold copies.

.claude/skills/ is the master source for skills (read directly by both Claude
Code and GitHub Copilot). .github/copilot-instructions.md is the master source
for instructions. The scaffold/ folder is the distribution copy sent to hub and
dataplatform repos. These must stay in sync — this test catches drift.

Fix: run `python scripts/sync-dev-skills.py`
"""

import sys
from pathlib import Path

import pytest

# Add scripts to path for import
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from sync_dev_skills import check_drift, get_sync_pairs  # noqa: E402


class TestScaffoldSync:
    """Verify .claude/skills/ and copilot-instructions.md are in sync with scaffold/."""

    def test_no_drift(self):
        """All master files must match their scaffold/ counterparts."""
        drifted = check_drift()
        if drifted:
            msg_lines = [
                f"Scaffold drift detected — {len(drifted)} file(s) out of sync:",
                "",
            ]
            for src, dst in drifted:
                msg_lines.append(f"  {src.relative_to(REPO_ROOT)} ≠ {dst.relative_to(REPO_ROOT)}")
            msg_lines.extend(
                [
                    "",
                    "Fix: run `python scripts/sync-dev-skills.py`",
                    "Or install the pre-commit hook: `powershell scripts/install-hooks.ps1`",
                ]
            )
            pytest.fail("\n".join(msg_lines))

    def test_sync_pairs_exist(self):
        """At least some sync pairs should exist (sanity check)."""
        pairs = get_sync_pairs()
        assert len(pairs) > 0, "No sync pairs found — check .claude/skills/ exists"

    def test_copilot_instructions_pair(self):
        """copilot-instructions.md must be in the sync pairs."""
        pairs = get_sync_pairs()
        instr_pairs = [(s, d) for s, d in pairs if "copilot-instructions" in s.name]
        assert len(instr_pairs) == 1

    def test_unmanaged_skills_excluded_from_scaffold(self):
        """Contributor-workflow skills (e.g. langfuse) must never reach the scaffold.

        .claude/skills/ mixes toolkit-managed kairos-* skills with skills authored
        only for contributors working in this repo. Only the former may ship to
        every hub/dataplatform repo the toolkit scaffolds.
        """
        pairs = get_sync_pairs()
        destinations = "\n".join(str(d) for _, d in pairs)
        assert "langfuse" not in destinations
        assert f"{Path('skills') / 'synced'}" not in destinations
