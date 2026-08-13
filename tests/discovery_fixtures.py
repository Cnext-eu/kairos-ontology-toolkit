# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Shared helper for satisfying the discovery hard gate (DD-148) in unrelated tests.

``kairos-ontology compile``/``validate`` now hard-fail when a hub has no discovery
conformance artifact. Tests that build a throwaway hub fixture to exercise compile or
validate — not discovery itself — call ``write_minimal_discovery_artifact()`` so they
keep testing what they were testing, rather than the gate.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from kairos_ontology.core.conformance_artifact import ARTIFACT_RELPATH, ARTIFACT_SCHEMA_VERSION


def write_minimal_discovery_artifact(hub_root: Path) -> Path:
    """Write a minimal, resolved (``mode: interactive``) discovery artifact.

    Passes ``check_discovery_gate()`` unconditionally: interactive-mode artifacts never
    have open questions, and no per-concept judgments are needed for the gate itself.
    """
    path = Path(hub_root) / ARTIFACT_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "generated_by": "test-fixture",
                "mode": "interactive",
                "archetype": {"id": "test-fixture", "confirmed_by": "human"},
                "core_concepts": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def write_discovery_artifact_with_unresolved_judgment(
    hub_root: Path, *, likely_domains: list[str] | None = None
) -> Path:
    """Write a discovery artifact with exactly one unresolved AI-decided judgment.

    The concept is ``decided_by: "ai"`` with ``needs_confirmation: true``, so it always
    fails ``open_questions()``/``check_discovery_gate()`` when in scope. Pass
    *likely_domains* to tag it to specific domain(s) (issue #389/#390); omit (the
    default) to leave it cross-cutting — matching every pre-existing artifact's implicit
    behavior, always in scope regardless of any ``--domain``/``domains=`` filter.
    """
    path = Path(hub_root) / ARTIFACT_RELPATH
    path.parent.mkdir(parents=True, exist_ok=True)
    concept: dict = {
        "uri": "https://example.org/ont/test#UnresolvedConcept",
        "label": "Unresolved Concept",
        "tier": "required",
        "outcome": "conforms",
        "decided_by": "ai",
        "needs_confirmation": True,
    }
    if likely_domains:
        concept["likely_domains"] = list(likely_domains)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": ARTIFACT_SCHEMA_VERSION,
                "generated_by": "test-fixture",
                "mode": "fleet",
                "archetype": {"id": "test-fixture", "confirmed_by": "human"},
                "core_concepts": [concept],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path
