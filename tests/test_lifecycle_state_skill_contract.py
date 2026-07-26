# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Contracts for monotonic lifecycle routing in managed skills."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
SKILLS = (
    "kairos-design-silver",
    "kairos-flow",
    "kairos-execute-project",
    "kairos-design-mapping",
    "kairos-develop-dbt-transformation",
    "kairos-help",
    "kairos-diagnose-status",
    "kairos-execute-validate",
)


def _skill(name: str) -> str:
    return (ROOT / ".github" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def test_lifecycle_skill_copies_are_identical():
    for name in SKILLS:
        repository = ROOT / ".github" / "skills" / name / "SKILL.md"
        scaffold = (
            ROOT / "src" / "kairos_ontology" / "scaffold" / "skills" / name / "SKILL.md"
        )
        assert repository.read_bytes() == scaffold.read_bytes(), name


def test_flow_routes_complex_and_simple_silver_without_skipping_readiness():
    content = _skill("kairos-flow")

    assert (
        "logical Silver → dbt transformation → mapping → bound Silver confirmation"
        in content
    )
    assert "logical Silver → mapping → bound Silver confirmation" in content
    assert "If it exits nonzero or reports any blocking diagnostic" in content
    assert "never invoke project" in content
    assert "legacy/unknown input" in content


def test_silver_stops_at_design_contract_and_uses_non_writing_bound_gate():
    content = _skill("kairos-design-silver")

    assert "Logical-intent completion" in content
    assert "Bound-confirmation completion" in content
    assert "check-projection --target silver --scope silver" in content
    assert "It never invokes generation" in content
    assert "kairos-ontology project" not in content
    assert "python -m kairos_ontology project" not in content


def test_project_skill_requires_full_readiness_before_generation():
    content = _skill("kairos-execute-project")

    assert "Projection-readiness gate (MANDATORY for every target)" in content
    assert "same ontology/domain" in content
    assert "Never generate merely because legacy phase status says `done`" in content
