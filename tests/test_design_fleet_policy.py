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
    text = " ".join(path.read_text(encoding="utf-8").split())
    lowered = text.lower()

    assert "## Design interaction" in text
    assert "interactive by default" in lowered
    assert "applies only to the active skill invocation" in lowered
    assert "expires when it" in lowered
    assert "records each ai-approved choice" in lowered


CLAUDE_SKILLS = REPO_ROOT / ".claude" / "skills"
SCAFFOLD_SKILLS = REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "skills"


def _design_skill_cases() -> list[tuple[Path, str]]:
    """Every (root, design skill) pair that should exist.

    The scaffold ships a *subset*: skills for capabilities a client cannot use are
    deliberately withheld (DD-219 -- `kairos-design-mdm` while MDM is not live). Deriving
    the scaffold half from what is actually shipped keeps this test from failing whenever
    that subset changes, while `test_every_design_skill_exists_in_this_repository` below
    still catches an accidental deletion.
    """
    cases = [(CLAUDE_SKILLS, skill) for skill in DESIGN_SKILLS]
    cases += [
        (SCAFFOLD_SKILLS, skill)
        for skill in DESIGN_SKILLS
        if (SCAFFOLD_SKILLS / skill / "SKILL.md").is_file()
    ]
    return cases


@pytest.mark.parametrize("skill", DESIGN_SKILLS)
def test_every_design_skill_exists_in_this_repository(skill):
    """The scaffold subset may shrink; the authored set may not, unless deliberately."""
    assert (CLAUDE_SKILLS / skill / "SKILL.md").is_file()


@pytest.mark.parametrize(
    ("root", "skill"),
    _design_skill_cases(),
    ids=lambda value: value.parent.name if isinstance(value, Path) else value,
)
def test_design_skills_include_fleet_mode_guardrails(root, skill):
    path = root / skill / "SKILL.md"
    text = " ".join(path.read_text(encoding="utf-8").split())

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
        REPO_ROOT / ".claude" / "skills",
        REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "skills",
    ],
    ids=["claude", "scaffold"],
)
def test_discovery_offers_invocation_scoped_mode_choice(root):
    text = " ".join(
        (root / "kairos-design-discovery" / "SKILL.md").read_text(encoding="utf-8").split()
    )

    assert "Default is interactive" in text
    assert "applies only to this skill invocation" in text
    assert "never inherited" in text
    assert "AI-approved choice" in text
