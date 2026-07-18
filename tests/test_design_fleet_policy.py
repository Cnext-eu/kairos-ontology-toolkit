# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Contract tests for skill-scoped design fleet mode guidance."""

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
    "kairos-design-mdm",
    "kairos-develop-dbt-transformation",
]


@pytest.mark.parametrize("path", INSTRUCTION_PATHS, ids=lambda p: p.parent.name)
def test_global_instructions_scope_design_fleet_mode_to_one_invocation(path):
    text = path.read_text(encoding="utf-8")

    assert "### Design mode policy (MANDATORY)" in text
    assert "Design skills are **interactive by default**" in text
    assert "**Skill-scoped fleet override:**" in text
    assert "applies only to that skill invocation" in text
    assert "MUST NOT carry into another skill" in text
    assert "Record each AI-made checkpoint decision" in text


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
    assert "record rationale" in text.lower()
    assert "stop for" in text.lower()
    assert "only to this skill invocation" in text
    assert "never inherited" in text


@pytest.mark.parametrize(
    "root",
    [
        REPO_ROOT / ".github" / "skills",
        REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "skills",
    ],
    ids=["github", "scaffold"],
)
def test_discovery_offers_invocation_scoped_mode_choice(root):
    text = (root / "kairos-design-discovery" / "SKILL.md").read_text(encoding="utf-8")

    assert "Choose the mode for this invocation" in text
    assert "**Interactive (Recommended)**" in text
    assert "**Design fleet**" in text
    assert "ask again after any pause/resume" in text
    assert "never pass the mode" in text
    assert "another skill" in text
