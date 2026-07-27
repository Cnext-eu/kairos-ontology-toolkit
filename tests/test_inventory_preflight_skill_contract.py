# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Contracts for the scoped pre-design reference-inventory gate."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOTS = [
    REPO_ROOT / ".github" / "skills",
    REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "skills",
]


@pytest.mark.parametrize("root", SKILL_ROOTS, ids=["github", "scaffold"])
@pytest.mark.parametrize("skill", ["kairos-flow", "kairos-design-domain"])
def test_pre_design_skills_use_scoped_inventory_authority(root, skill):
    text = (root / skill / "SKILL.md").read_text(encoding="utf-8")

    assert "check-inventory --domains" in text
    assert "--explain-scope" in text
    assert "only freshness authority" in text
    assert "installed/current local reference-model version" in text
    assert "non-blocking" in text
    assert "kairos-toolkit-ops" in text
    assert "silently" in text


@pytest.mark.parametrize("root", SKILL_ROOTS, ids=["github", "scaffold"])
def test_domain_gate_is_blocking_before_design(root):
    text = (root / "kairos-design-domain" / "SKILL.md").read_text(encoding="utf-8")

    gate = text.index("### Gate 0: Scoped reference-inventory freshness")
    first_design_gate = text.index("### Gate 1: Source completeness")
    assert gate < first_design_gate
    assert "Missing\nor stale" in text[gate:first_design_gate]
    assert "STOP" in text[gate:first_design_gate]


@pytest.mark.parametrize("root", SKILL_ROOTS, ids=["github", "scaffold"])
def test_ops_owns_explicit_reference_model_updates(root):
    text = (root / "kairos-toolkit-ops" / "SKILL.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "Pre-design freshness hand-off" in text
    assert "ontology-reference-models/VERSION" in text
    assert "Do not reinterpret" in text
    assert "do not update automatically" in normalized
    assert "explicit approval" in normalized
