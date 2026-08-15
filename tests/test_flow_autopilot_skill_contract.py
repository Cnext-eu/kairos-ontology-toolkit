# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Anchor contracts for the ``kairos-flow-autopilot`` skill.

The autopilot skill has no executable-command test (it is a fleet orchestration
skill, not a CLI-integrated one), but its guidance must not regress silently.
These anchors pin the key obligations the skill imposes on an autopilot run.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SKILL_ROOTS = [
    REPO_ROOT / ".github" / "skills",
    REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "skills",
]

AUTOPILOT_ANCHORS = [
    # The skill's core contract
    "declare the bounded scope before starting",
    "stopping stage",
    "toolkit version",
    # Stage ladder
    "validate",
    "compile --check",
    # Stage 0 AI provider preflight
    "check-ai-config",
    "Stage 0 pre-flight: AI provider",
    "**STOP**",
    # Decision Log as primary deliverable
    "Decision Log",
    "decision sync-index",
    "decision new --materiality",
    # Per-domain exit checklist (Stage 3)
    "Per-domain exit checklist",
    "no material decision, mechanical authoring only",
    # Upfront domain mapping (Stage 2→3 boundary)
    "Upfront domain mapping",
    "domain-coverage --owns",
    "term_owner_ambiguous",
    # Guardrails
    "DD-088",
    "escalates",
    # Transparency report
    "transparency report",
]


def _skill(root: Path, name: str) -> str:
    return (root / name / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("root", SKILL_ROOTS, ids=["github", "scaffold"])
@pytest.mark.parametrize("anchor", AUTOPILOT_ANCHORS)
def test_autopilot_skill_preserves_key_anchors(root, anchor):
    assert anchor in _skill(root, "kairos-flow-autopilot")


@pytest.mark.parametrize("root", SKILL_ROOTS, ids=["github", "scaffold"])
def test_autopilot_skill_files_are_byte_identical(root):
    """The .github/ master and scaffold copy must be byte-identical."""
    master = (REPO_ROOT / ".github" / "skills" / "kairos-flow-autopilot" / "SKILL.md").read_bytes()
    scaffold = (root / "kairos-flow-autopilot" / "SKILL.md").read_bytes()
    assert master == scaffold
