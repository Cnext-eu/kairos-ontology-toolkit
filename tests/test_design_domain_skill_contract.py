# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""DD-133 contracts for the thin v5 canonical-design and EntityBinding loops."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

SKILL_ROOTS = [
    REPO_ROOT / ".github" / "skills",
    REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "skills",
]

DOMAIN_ANCHORS = [
    "DD-133 v5 clean break",
    "smallest useful canonical slice",
    "### Gate 1: Source completeness",
    "including the first",
    "whether additional or newer sources",
    "Business authority",
    "Industry inspiration",
    "Source feasibility",
    "Downstream demand",
    "PII-safe",
    "reviewable unified diff",
    "model/ontologies/<domain>.ttl",
    "kairos-ontology validate --syntax",
    "guard-scope",
    "Source keys",
    "**kairos-design-mapping**",
    "kairos-ontology list-patterns --format json",
    # Pattern guidance must reach beyond the naming table (#276 Q1/Q2): the structural
    # anti-patterns, the per-mode binding decision, and the grain boundaries are the
    # expensive half of what the library encodes.
    "structure as well as names",
    "`mode_bindings`",
    "do not invent a class",
    "`grain_collisions`",
]

MAPPING_ANCHORS = [
    "DD-133 v5 clean break",
    "source-to-canonical execution authority",
    "apiVersion: kairos.eu/v5",
    "kind: EntityBinding",
    "integration/bindings/",
    "source.dbtModel",
    "compile <domain> --check --format text",
    "Compiler check after every batch",
    "compile <domain> --explain --format text",
    "normalized fields",
    "blocked behavior",
    "Do not call `compile --emit`",
    "PII-safe",
    "authoritative YAML output contract",
    "persist only accepted binding",
]

LEGACY_ACTIVE_PATHS = [
    "check-transformation-readiness",
    "scaffold-mapping",
    "skos:exactMatch",
    "model/mappings/",
    "integration/preparation/",
    "phases/domain/",
    "phases/mapping/",
    "mapping-plan.yaml",
]


def _skill(root: Path, name: str) -> str:
    return (root / name / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("root", SKILL_ROOTS, ids=["github", "scaffold"])
@pytest.mark.parametrize("anchor", DOMAIN_ANCHORS)
def test_domain_skill_implements_bounded_v5_canonical_loop(root, anchor):
    assert anchor in _skill(root, "kairos-design-domain")


@pytest.mark.parametrize("root", SKILL_ROOTS, ids=["github", "scaffold"])
@pytest.mark.parametrize("anchor", MAPPING_ANCHORS)
def test_mapping_skill_implements_v5_compile_feedback_loop(root, anchor):
    assert anchor in _skill(root, "kairos-design-mapping")


@pytest.mark.parametrize("root", SKILL_ROOTS, ids=["github", "scaffold"])
@pytest.mark.parametrize("skill", ["kairos-design-domain", "kairos-design-mapping"])
def test_v5_skills_do_not_reintroduce_legacy_active_paths(root, skill):
    text = _skill(root, skill)
    for legacy_path in LEGACY_ACTIVE_PATHS:
        assert legacy_path not in text


@pytest.mark.parametrize("skill", ["kairos-design-domain", "kairos-design-mapping"])
def test_v5_skill_copies_are_byte_identical(skill):
    github = SKILL_ROOTS[0] / skill / "SKILL.md"
    scaffold = SKILL_ROOTS[1] / skill / "SKILL.md"
    assert github.read_bytes() == scaffold.read_bytes()
