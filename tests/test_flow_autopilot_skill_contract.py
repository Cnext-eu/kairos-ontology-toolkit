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
        # Archetype stop-condition (#465, DD-149)
        "Archetype selection always stops for human confirmation",
        # Per-domain validate-then-register (#475 item 3)
        "Per-domain validate-then-register",
        # suggest-shapes step (#475 item 4)
        "suggest-shapes",
        # Governance SHACL (#475 item 5)
        "Governance SHACL",
        # Transparency report
        "transparency report",
        "Source coverage metric",
        "Unbound tables over 1000 rows",
        "Conformance-risk list",
        "**BLOCKED**",
        "Zero-relationships flag",
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


# ---------------------------------------------------------------------------
# SHACL cross-reference anchors (#483)
# ---------------------------------------------------------------------------

DOMAIN_SHACL_ANCHOR = (
    "EntityBinding authoring (kairos-design-mapping) does **not** author SHACL shapes"
)

MAPPING_SHACL_ANCHOR = (
    "SHACL governance shapes are authored during domain design"
)


@pytest.mark.parametrize("root", SKILL_ROOTS, ids=["github", "scaffold"])
def test_domain_skill_has_shacl_mapping_anchor(root):
    """kairos-design-domain SKILL.md must cross-reference binding/SHACL (#483)."""
    assert DOMAIN_SHACL_ANCHOR in _skill(root, "kairos-design-domain")


@pytest.mark.parametrize("root", SKILL_ROOTS, ids=["github", "scaffold"])
def test_mapping_skill_has_shacl_domain_anchor(root):
    """kairos-design-mapping SKILL.md must cross-reference SHACL governance (#483)."""
    assert MAPPING_SHACL_ANCHOR in _skill(root, "kairos-design-mapping")


@pytest.mark.parametrize("skill_name", ["kairos-design-domain", "kairos-design-mapping"])
def test_skill_copies_are_byte_identical(skill_name):
    """The .github/ master and scaffold copy must be byte-identical."""
    master = (REPO_ROOT / ".github" / "skills" / skill_name / "SKILL.md").read_bytes()
    scaffold = (
        REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "skills" / skill_name / "SKILL.md"
    ).read_bytes()
    assert master == scaffold
