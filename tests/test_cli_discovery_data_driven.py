# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI surface for source-evidence-aware discovery judgments (issue #507)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from archetype_fixtures import build_refmodels_root
from kairos_ontology.cli.main import cli

_GHOST = "https://example.org/ont/booking#GhostConcept"


@pytest.fixture()
def refroot(tmp_path):
    return build_refmodels_root(tmp_path)


@pytest.fixture(autouse=True)
def _skill_context(monkeypatch):
    monkeypatch.setenv("KAIROS_SKILL_CONTEXT", "1")


def _hub(tmp_path: Path, *, with_evidence: bool = True) -> Path:
    hub = tmp_path / "hub"
    (hub / "integration" / "discovery").mkdir(parents=True)
    # model/ontologies/ is what makes find_hub_root recognise cwd as the hub root; without it
    # every command falls back to cwd and never looks for source analysis at all.
    (hub / "model" / "ontologies").mkdir(parents=True)
    if with_evidence:
        analysis = hub / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (analysis / "logistics-alignment.yaml").write_text(
            yaml.safe_dump(
                {
                    "domain": "logistics",
                    "tables": [
                        {"system": "qargo", "table": "ghost_charges", "ref_class": "GhostConcept"}
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    return hub


def _run(args):
    return CliRunner().invoke(cli, args)


def _outcomes(ghost_outcome: str, *, ghost_rationale: str = "") -> list[dict]:
    return [
        {
            "uri": "https://example.org/ont/booking#Booking",
            "label": "Booking",
            "tier": "required",
            "outcome": "conforms",
            "decided_by": "user",
            "confidence": 0.9,
        },
        {
            "uri": "https://example.org/ont/booking#CargoItem",
            "label": "Cargo Item",
            "tier": "required",
            "outcome": "conforms",
            "decided_by": "user",
            "confidence": 0.9,
        },
        {
            "uri": "https://example.org/ont/party#BookingParty",
            "label": "Booking Party",
            "tier": "recommended",
            "outcome": "conforms",
            "decided_by": "user",
            "confidence": 0.9,
        },
        {
            "uri": _GHOST,
            "label": "Ghost",
            "tier": "optional",
            "outcome": ghost_outcome,
            "decided_by": "user",
            "confidence": 0.9,
            "rationale": ghost_rationale,
        },
    ]


def _write_judgments(path: Path, outcomes: list[dict]) -> Path:
    path.write_text(
        yaml.safe_dump(
            {
                "mode": "interactive",
                "archetype_confirmed_by": "human",
                "core_concepts": outcomes,
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _build(judgments: Path, refroot: Path):
    return _run(
        [
            "discovery-conformance",
            "build",
            "--archetype",
            "test-carrier",
            "--judgments-file",
            str(judgments),
            "--refmodels-root",
            str(refroot),
        ]
    )


# ---------------------------------------------------------------------------
# judgments-template
# ---------------------------------------------------------------------------


def test_template_prefills_conforms_for_an_optional_concept_with_source_data(
    tmp_path, refroot, monkeypatch
):
    """"If data exists and the concept is optional, model it" -- the whole point of #507."""
    monkeypatch.chdir(_hub(tmp_path))

    res = _run(
        ["discovery-conformance", "judgments-template", "--archetype", "test-carrier",
         "--refmodels-root", str(refroot)]
    )

    assert res.exit_code == 0, res.output
    entries = {c["uri"]: c for c in json.loads(res.stdout)["core_concepts"]}
    ghost = entries[_GHOST]
    assert ghost["outcome"] == "conforms"
    assert "qargo.ghost_charges" in ghost["rationale"]
    assert ghost["source_evidence"]["kind"] == "alignment"
    assert ghost["source_evidence"]["tables"] == ["qargo.ghost_charges"]


def test_template_leaves_required_and_recommended_concepts_as_sentinels(
    tmp_path, refroot, monkeypatch
):
    """Required concepts are in scope regardless of sources; pre-filling them says nothing."""
    monkeypatch.chdir(_hub(tmp_path))

    res = _run(
        ["discovery-conformance", "judgments-template", "--archetype", "test-carrier",
         "--refmodels-root", str(refroot)]
    )

    entries = {c["uri"]: c for c in json.loads(res.stdout)["core_concepts"]}
    for uri, entry in entries.items():
        if uri == _GHOST:
            continue
        assert entry["outcome"].startswith("<CONFIRM_OUTCOME:")
        assert "source_evidence" not in entry


def test_template_without_evidence_is_unchanged_from_the_pre_507_shape(
    tmp_path, refroot, monkeypatch
):
    monkeypatch.chdir(_hub(tmp_path, with_evidence=False))

    res = _run(
        ["discovery-conformance", "judgments-template", "--archetype", "test-carrier",
         "--refmodels-root", str(refroot)]
    )

    for entry in json.loads(res.stdout)["core_concepts"]:
        assert entry["outcome"].startswith("<CONFIRM_OUTCOME:")
        assert entry["rationale"] == "<CONFIRM_RATIONALE>"
        assert "source_evidence" not in entry


def test_no_source_evidence_flag_opts_out(tmp_path, refroot, monkeypatch):
    monkeypatch.chdir(_hub(tmp_path))

    res = _run(
        ["discovery-conformance", "judgments-template", "--archetype", "test-carrier",
         "--no-source-evidence", "--refmodels-root", str(refroot)]
    )

    entries = {c["uri"]: c for c in json.loads(res.stdout)["core_concepts"]}
    assert entries[_GHOST]["outcome"].startswith("<CONFIRM_OUTCOME:")


def test_template_round_trips_into_build(tmp_path, refroot, monkeypatch):
    """The pre-filled template must be directly buildable, not merely readable."""
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    res = _run(
        ["discovery-conformance", "judgments-template", "--archetype", "test-carrier",
         "--refmodels-root", str(refroot)]
    )
    payload = json.loads(res.stdout)
    for entry in payload["core_concepts"]:
        entry["decided_by"] = "user"
        entry["confidence"] = 0.9
        if entry["outcome"].startswith("<CONFIRM_OUTCOME:"):
            entry["outcome"] = "conforms"
        if entry["rationale"] == "<CONFIRM_RATIONALE>":
            entry["rationale"] = "Confirmed in interview."
    payload["archetype_confirmed_by"] = "human"
    judgments = tmp_path / "judgments.yaml"
    judgments.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    assert _build(judgments, refroot).exit_code == 0, _build(judgments, refroot).output


# ---------------------------------------------------------------------------
# build gate
# ---------------------------------------------------------------------------


def test_build_rejects_a_source_contradicted_not_applicable(tmp_path, refroot, monkeypatch):
    monkeypatch.chdir(_hub(tmp_path))
    judgments = _write_judgments(tmp_path / "judgments.yaml", _outcomes("not-applicable"))

    res = _build(judgments, refroot)

    assert res.exit_code == 1
    assert "contradict the hub's own source evidence" in res.stderr
    assert "qargo.ghost_charges" in res.stderr
    # The artifact must not have been written -- this is an authoring gate, not a post-check.
    assert not (
        tmp_path / "hub" / "integration" / "discovery" / "core-concepts-conformance.yaml"
    ).exists()


def test_build_accepts_the_override_when_a_real_rationale_is_recorded(
    tmp_path, refroot, monkeypatch
):
    """The SME keeps authority -- it just has to be an explained decision."""
    monkeypatch.chdir(_hub(tmp_path))
    judgments = _write_judgments(
        tmp_path / "judgments.yaml",
        _outcomes("not-applicable", ghost_rationale="Those charges are a legacy feed, retired."),
    )

    res = _build(judgments, refroot)

    assert res.exit_code == 0, res.output
    # Still advisory-flagged afterwards, so a reviewer sees the tension.
    assert "⚠" in res.stderr and "Ghost" in res.stderr


def test_build_is_unaffected_when_the_hub_has_no_source_analysis(tmp_path, refroot, monkeypatch):
    monkeypatch.chdir(_hub(tmp_path, with_evidence=False))
    judgments = _write_judgments(tmp_path / "judgments.yaml", _outcomes("not-applicable"))

    assert _build(judgments, refroot).exit_code == 0


def test_build_does_not_persist_source_evidence_into_the_artifact(tmp_path, refroot, monkeypatch):
    """#507 changes no artifact schema: source_evidence is template-only, recomputed live."""
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    outcomes = _outcomes("conforms")
    outcomes[3]["source_evidence"] = {"kind": "alignment", "tables": ["qargo.ghost_charges"]}
    judgments = _write_judgments(tmp_path / "judgments.yaml", outcomes)

    assert _build(judgments, refroot).exit_code == 0
    artifact = yaml.safe_load(
        (hub / "integration" / "discovery" / "core-concepts-conformance.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert artifact["schema_version"] == 2


# ---------------------------------------------------------------------------
# validate advisories + summarize
# ---------------------------------------------------------------------------


def test_validate_only_warns_and_never_fails_an_existing_artifact(tmp_path, refroot, monkeypatch):
    """Re-validating work already done must not become unconvergeable (CLdN has 22 of these)."""
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    judgments = _write_judgments(
        tmp_path / "judgments.yaml", _outcomes("not-applicable", ghost_rationale="Legacy feed.")
    )
    assert _build(judgments, refroot).exit_code == 0

    res = _run(["discovery-conformance", "validate", "--refmodels-root", str(refroot)])

    assert res.exit_code == 0, res.output
    assert "⚠" in res.stderr and "qargo.ghost_charges" in res.stderr


def test_summarize_splits_blueprint_from_data_driven(tmp_path, refroot, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    judgments = _write_judgments(tmp_path / "judgments.yaml", _outcomes("conforms"))
    assert _build(judgments, refroot).exit_code == 0

    res = _run(["discovery-conformance", "summarize"])

    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["by_evidence"] == {"blueprint": 3, "data-driven": 1}
    # The in-artifact scorecard is untouched, so existing artifacts still validate.
    assert set(payload["scorecard"]) == {"total", "by_outcome", "by_tier"}


def test_summarize_outside_a_hub_reports_zeroes_not_a_crash(tmp_path, refroot, monkeypatch):
    hub = _hub(tmp_path, with_evidence=False)
    monkeypatch.chdir(hub)
    judgments = _write_judgments(tmp_path / "judgments.yaml", _outcomes("conforms"))
    assert _build(judgments, refroot).exit_code == 0

    payload = json.loads(_run(["discovery-conformance", "summarize"]).stdout)

    assert payload["by_evidence"] == {"blueprint": 4, "data-driven": 0}
