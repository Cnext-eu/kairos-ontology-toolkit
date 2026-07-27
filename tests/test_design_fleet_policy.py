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
        REPO_ROOT / ".github" / "skills",
        REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "skills",
    ],
    ids=["github", "scaffold"],
)
def test_discovery_offers_invocation_scoped_mode_choice(root):
    text = " ".join(
        (root / "kairos-design-discovery" / "SKILL.md").read_text(encoding="utf-8").split()
    )

    assert "Default is interactive" in text
    assert "applies only to this skill invocation" in text
    assert "never inherited" in text
    assert "AI-approved choice" in text
