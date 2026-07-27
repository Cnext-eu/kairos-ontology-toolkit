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
    _ROOT / ".github" / "skills",
    _ROOT / "src" / "kairos_ontology" / "scaffold" / "skills",
)


def test_v5_skill_copies_are_managed_and_identical():
    for name in ("kairos-design-domain", "kairos-design-mapping"):
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
