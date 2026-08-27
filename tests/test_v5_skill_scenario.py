# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""V5 skill workflow and privacy-boundary contracts."""

from __future__ import annotations

from pathlib import Path

from kairos_ontology.core.source_privacy import (
    find_samples_document_privacy_issues,
    sanitize_samples_document,
)

_ROOT = Path(__file__).resolve().parents[1]
_SKILL_ROOTS = (
    _ROOT / ".claude" / "skills",
    _ROOT / "src" / "kairos_ontology" / "scaffold" / "skills",
)


def test_v5_lifecycle_skill_copies_are_managed_and_identical():
    names = (
        "kairos-flow",
        "kairos-design-domain",
        "kairos-design-mapping",
        "kairos-design-silver",
        "kairos-develop-dbt-transformation",
        "kairos-execute-project",
        "kairos-diagnose-status",
    )
    for name in names:
        copies = [(root / name / "SKILL.md").read_bytes() for root in _SKILL_ROOTS]
        assert copies[0] == copies[1]
        assert b"kairos-ontology-toolkit:managed" in copies[0]


def test_mapping_skill_uses_only_binding_compile_feedback():
    text = (_SKILL_ROOTS[0] / "kairos-design-mapping" / "SKILL.md").read_text(encoding="utf-8")
    assert "integration/bindings/" in text
    assert "compile <domain> --check" in text
    assert "compile <domain> --explain" in text
    assert "An unredacted sample blocks the workflow" in text
    for legacy in ("model/mappings/", "integration/preparation/", "virtual-source registry"):
        assert legacy not in text


def test_v5_lifecycle_surface_routes_through_binding_and_compile():
    flow = (_SKILL_ROOTS[0] / "kairos-flow" / "SKILL.md").read_text(encoding="utf-8")
    silver = (_SKILL_ROOTS[0] / "kairos-design-silver" / "SKILL.md").read_text(encoding="utf-8")
    transform = (_SKILL_ROOTS[0] / "kairos-develop-dbt-transformation" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    mapping = (_SKILL_ROOTS[0] / "kairos-design-mapping" / "SKILL.md").read_text(encoding="utf-8")
    execute = (_SKILL_ROOTS[0] / "kairos-execute-project" / "SKILL.md").read_text(encoding="utf-8")
    diagnose = (_SKILL_ROOTS[0] / "kairos-diagnose-status" / "SKILL.md").read_text(encoding="utf-8")

    assert all(
        route in flow for route in ("## Inspect", "**Design:**", "**Bind:**", "**Compile:**")
    )
    assert "has no v5 authoring surface" in silver
    assert "closed `EntityBinding`" in silver
    assert "ordinary dbt SQL and properties YAML" in transform
    assert "source.dbtModel.name" in transform
    assert "identifies the contracted model output only" in transform
    assert "not another authored source or execution" in mapping
    assert "Use `compile` directly" in execute
    assert "## Authored input inventory" in diagnose
    assert "## Current compiler diagnostics" in diagnose


def test_v5_lifecycle_surface_omits_deleted_commands():
    deleted_commands = (
        "check-transformation-readiness",
        "scaffold-silver-ext",
        "validate-silver-ext",
        "sync-dbt-contracts",
        "audit-silver-samples",
        "compile check --scope",
    )
    for root in _SKILL_ROOTS:
        for name in (
            "kairos-flow",
            "kairos-design-domain",
            "kairos-design-mapping",
            "kairos-design-silver",
            "kairos-develop-dbt-transformation",
            "kairos-execute-project",
            "kairos-diagnose-status",
        ):
            text = (root / name / "SKILL.md").read_text(encoding="utf-8")
            assert all(command not in text for command in deleted_commands)


def test_sample_evidence_is_redacted_before_skill_exposure():
    raw = {
        "table": "customers",
        "rows": [{"customer_id": "C-1", "email": "person@example.test"}],
    }
    assert find_samples_document_privacy_issues(raw, table="customers")
    safe, findings = sanitize_samples_document(raw, table="customers")
    assert findings
    assert "person@example.test" not in repr(safe)
    assert not find_samples_document_privacy_issues(safe, table="customers")
