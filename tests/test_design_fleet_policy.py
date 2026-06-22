# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Contract tests for opt-in design fleet mode guidance."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

INSTRUCTION_PATHS = [
    REPO_ROOT / ".github" / "copilot-instructions.md",
    REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "copilot-instructions.md",
]

DESIGN_SKILLS = [
    "kairos-design-discovery",
    "kairos-design-source",
    "kairos-design-domain",
    "kairos-design-mapping",
    "kairos-design-silver",
    "kairos-design-gold",
]


@pytest.mark.parametrize("path", INSTRUCTION_PATHS, ids=lambda p: p.parent.name)
def test_global_instructions_allow_explicit_design_fleet_mode(path):
    text = path.read_text(encoding="utf-8")

    assert "### Design mode policy (MANDATORY)" in text
    assert "Design skills are **interactive by default**" in text
    assert "**Opt-in design fleet mode:**" in text
    assert "Record each AI-made checkpoint decision" in text
    assert "MUST NEVER be run in autopilot or autopilot-fleet mode" not in text


@pytest.mark.parametrize("skill", DESIGN_SKILLS)
@pytest.mark.parametrize(
    "root",
    [
        REPO_ROOT / ".github" / "skills",
        REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "skills",
    ],
    ids=["github", "scaffold"],
)
def test_design_skills_include_fleet_mode_guardrails(root, skill):
    path = root / skill / "SKILL.md"
    text = path.read_text(encoding="utf-8")

    assert "## Design fleet mode (DD-088)" in text
    assert "Default is interactive" in text
    assert "AI-approved" in text
    assert "Record rationale" in text
    assert "stop for" in text.lower()
