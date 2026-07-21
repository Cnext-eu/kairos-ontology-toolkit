# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Contract tests for the proposed-only conformance → stub lifecycle guidance.

These guard the *instruction* layer that wires the data-engineer flow across the
lifecycle skills (impl-flow-integration):

    ingest → analyse/conformance → deterministic derive proposals → batch human
    approval → claims-to-silver-ext sync → optional aspirational stub

Key invariants enforced here:
  - Core Concepts Conformance feeds ``derive-claims`` as a *proposed-only*,
    AI-free stream (DD-090 → DD-095); it never authorizes approval or
    materialization (Claim Registry stays the authority, DD-094).
  - Skills distinguish AI-free proposal generation from user-confirmed /
    AI-approved design decisions.
  - ``kairos-flow`` resume guidance surfaces proposals-awaiting-approval and
    approved-but-unbound stubs as *intent*, without duplicating machine truth.
  - ``kairos-flow``, ``kairos-diagnose-status``, and ``kairos-execute-project``
    consume the deterministic ``status``/``check-release`` machine-readable
    facts (DD-101) rather than hand-deriving proposed/approved/bound/
    aspirational/release-eligible state themselves.

Both the ``.github`` master and the scaffold copy are checked so the contract is
self-contained; byte-parity itself is guarded by ``tests/test_scaffold_sync.py``.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

ROOTS = [
    REPO_ROOT / ".github" / "skills",
    REPO_ROOT / "src" / "kairos_ontology" / "scaffold" / "skills",
]
ROOT_IDS = ["github", "scaffold"]

# skill dir -> anchors that must appear in its SKILL.md
SKILL_ANCHORS = {
    "kairos-design-discovery": [
        # conformance is warn-only and proposed-only downstream
        "Consumption remains **warn-only**",
        "`not-applicable` → **no proposal**",
        "single approval/materialization authority (DD-094)",
        # AI-free proposal vs user-confirmed / AI-approved decision
        "**AI-free proposal generation**",
    ],
    "kairos-design-source": [
        "**six evidence",
        "Core Concepts Conformance outcomes",
        "DD-090 outcome policy",
        "AI-free proposal ≠ approved design decision",
        # the ordered data-engineer flow
        "Deterministically derive proposals",
        "Batch human approval",
        "Claims-to-Silver-ext sync",
        "Optional aspirational stub",
    ],
    "kairos-flow": [
        "surface intent, not machine truth",
        "Proposals awaiting approval",
        "Approved-but-unbound stubs",
        "awaiting batch approval",
        # DD-101: composed lifecycle gate + machine-readable status facts
        "check-release",
        "facts.aspirational_classes",
        "facts.proposed",
    ],
    "kairos-diagnose-status": [
        "Do not hand-classify this yourself",
        "facts",
        "check-release",
    ],
    "kairos-execute-project": [
        "kairos-ontology check-release",
        "without generating any output",
    ],
}


@pytest.mark.parametrize("root", ROOTS, ids=ROOT_IDS)
@pytest.mark.parametrize(
    "skill,anchor",
    [(skill, anchor) for skill, anchors in SKILL_ANCHORS.items() for anchor in anchors],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_flow_integration_anchor_present(root, skill, anchor):
    path = root / skill / "SKILL.md"
    text = path.read_text(encoding="utf-8")
    assert anchor in text, (
        f"Flow-integration anchor {anchor!r} missing from {path} — the "
        f"proposed-only conformance / stub-first lifecycle guidance may have "
        f"regressed."
    )


@pytest.mark.parametrize("root", ROOTS, ids=ROOT_IDS)
def test_conformance_stream_never_authorizes_materialization(root):
    """Discovery + source must state conformance produces proposed-only claims."""
    discovery = (root / "kairos-design-discovery" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    source = (root / "kairos-design-source" / "SKILL.md").read_text(encoding="utf-8")

    # proposed-only, never materialization
    assert "`status: proposed` only" in discovery
    assert "does **not** approve the derived claim" in discovery
    # source names conformance as an explicitly deterministic / AI-free stream
    assert "proposed-only" in source
    assert "deterministic" in source


@pytest.mark.parametrize("root", ROOTS, ids=ROOT_IDS)
def test_fleet_consent_is_skill_scoped_and_not_inherited(root):
    """AI-free derivation must not be confused with skill-scoped AI-approval."""
    for skill in ("kairos-design-discovery", "kairos-design-source"):
        text = (root / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "only to this skill invocation" in text
        assert "never inherited" in text


@pytest.mark.parametrize("root", ROOTS, ids=ROOT_IDS)
def test_lifecycle_gate_skills_defer_to_machine_readable_facts(root):
    """DD-101: kairos-flow/diagnose-status/execute-project consume `status`/
    `check-release` facts instead of re-deriving proposed/approved/bound/
    aspirational/release-eligible state themselves."""
    flow = (root / "kairos-flow" / "SKILL.md").read_text(encoding="utf-8")
    diagnose = (root / "kairos-diagnose-status" / "SKILL.md").read_text(encoding="utf-8")
    project = (root / "kairos-execute-project" / "SKILL.md").read_text(encoding="utf-8")

    assert "kairos-ontology check-release" in flow
    assert "DD-101" in flow
    assert "facts.proposed" in flow
    assert "facts.aspirational_classes" in flow

    assert "Do not hand-classify this yourself" in diagnose
    assert "check-release" in diagnose

    assert "kairos-ontology check-release" in project
    assert "without generating any output" in project
