# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Test that .github/ skills and copilot-instructions match scaffold copies.

The .github/ folder is the master source for skills and instructions.
The scaffold/ folder is the distribution copy sent to hub repos.
These must stay in sync — this test catches drift.

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
    """Verify .github/ and scaffold/ are in sync."""

    def test_no_drift(self):
        """All .github/ files must match their scaffold/ counterparts."""
        drifted = check_drift()
        if drifted:
            msg_lines = [
                f"Scaffold drift detected — {len(drifted)} file(s) out of sync:",
                "",
            ]
            for src, dst in drifted:
                msg_lines.append(
                    f"  {src.relative_to(REPO_ROOT)} ≠ {dst.relative_to(REPO_ROOT)}"
                )
            msg_lines.extend([
                "",
                "Fix: run `python scripts/sync-dev-skills.py`",
                "Or install the pre-commit hook: `powershell scripts/install-hooks.ps1`",
            ])
            pytest.fail("\n".join(msg_lines))

    def test_sync_pairs_exist(self):
        """At least some sync pairs should exist (sanity check)."""
        pairs = get_sync_pairs()
        assert len(pairs) > 0, "No sync pairs found — check .github/skills/ exists"

    def test_copilot_instructions_pair(self):
        """copilot-instructions.md must be in the sync pairs."""
        pairs = get_sync_pairs()
        instr_pairs = [
            (s, d) for s, d in pairs if "copilot-instructions" in s.name
        ]
        assert len(instr_pairs) == 1
