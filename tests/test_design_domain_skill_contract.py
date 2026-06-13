# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Contract tests for the design-domain skill's reference-model visibility guidance.

These tests guard the *instruction* layer that makes specialized reference-model
classes visible to the (LLM-driven) domain modeler:

  - **DD-046** — Step 0c.1b, Checkpoint 1, and Checkpoint 3b must instruct the
    modeler to surface subclasses and their subclass-specific properties so it
    reuses an existing specialization instead of creating a local duplicate.
  - **DD-047** — Step 0c.1b must open with the deterministic ``check-inventory``
    pre-flight gate that blocks modeling against a missing/stale inventory.

The other two layers of "the modeler can see specialized classes" are covered
elsewhere and intentionally not duplicated here:

  - The *data* the modeler reads (inventory YAML surfaces subclass properties) —
    ``tests/scenarios/test_scenario_specialization.py`` and ``tests/test_inventory.py``.
  - The freshness/pre-flight *behaviour* — ``tests/test_inventory_freshness.py``.

``.github`` ↔ scaffold parity is guarded by ``tests/test_scaffold_sync.py``; this
test still checks both copies so the modeler-facing contract is self-contained.

Anchors are matched against the whole-file text (not line-by-line) because the
guidance phrases wrap across lines.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SKILL_PATHS = [
    REPO_ROOT / ".github" / "skills" / "kairos-design-domain" / "SKILL.md",
    REPO_ROOT
    / "src"
    / "kairos_ontology"
    / "scaffold"
    / "skills"
    / "kairos-design-domain"
    / "SKILL.md",
]

# DD-046 — subclass / specialization visibility guidance.
DD046_ANCHORS = [
    "specialization tree",
    "subclass-specific properties",
    "(subclass)",
    "SUBCLASSES of the parent",
    "accidental local duplication",
    "DD-046",
]

# DD-047 — deterministic inventory freshness pre-flight gate.
DD047_ANCHORS = [
    "Pre-flight gate (DD-047)",
    "check-inventory",
    "generate-inventory",
    "STOP",
]


@pytest.mark.parametrize("skill_path", SKILL_PATHS, ids=lambda p: p.parent.parent.parent.name)
class TestDesignDomainSkillContract:
    """The design-domain skill must keep the modeler-facing visibility guidance."""

    def test_skill_file_exists(self, skill_path):
        assert skill_path.is_file(), f"Missing skill file: {skill_path}"

    @pytest.mark.parametrize("anchor", DD046_ANCHORS)
    def test_dd046_subclass_guidance_present(self, skill_path, anchor):
        text = skill_path.read_text(encoding="utf-8")
        assert anchor in text, (
            f"DD-046 anchor {anchor!r} missing from {skill_path} — the modeler may no "
            f"longer be instructed to surface reference-model subclasses."
        )

    @pytest.mark.parametrize("anchor", DD047_ANCHORS)
    def test_dd047_preflight_gate_present(self, skill_path, anchor):
        text = skill_path.read_text(encoding="utf-8")
        assert anchor in text, (
            f"DD-047 anchor {anchor!r} missing from {skill_path} — the inventory "
            f"freshness pre-flight gate may have been removed."
        )
