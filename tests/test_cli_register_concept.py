# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI + integration surface for ``register-concept`` (issue #505, Layer B)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from archetype_fixtures import build_refmodels_root
from kairos_ontology.cli.main import cli
from kairos_ontology.cli.shared import _SKILL_COVERED_COMMANDS
from kairos_ontology.core.conformance_artifact import ARTIFACT_RELPATH, check_discovery_gate
from kairos_ontology.core.registered_concepts import REGISTERED_RELPATH

_URI = "https://acme.example/ont/logistics#PlanningZone"
_CATALOG_URI = "https://example.org/ont/booking#Booking"


@pytest.fixture()
def refroot(tmp_path):
    return build_refmodels_root(tmp_path)


@pytest.fixture(autouse=True)
def _skill_context(monkeypatch):
    monkeypatch.setenv("KAIROS_SKILL_CONTEXT", "1")


def _hub(tmp_path: Path) -> Path:
    hub = tmp_path / "hub"
    (hub / "model" / "ontologies").mkdir(parents=True)
    (hub / "integration" / "discovery").mkdir(parents=True)
    return hub


def _run(args):
    return CliRunner().invoke(cli, args)


def _register_args(refroot, **overrides) -> list[str]:
    args = [
        "register-concept",
        "--uri",
        overrides.get("uri", _URI),
        "--label",
        "Planning Zone",
        "--source-system",
        "qlik",
        "--source-evidence",
        "planning_zones",
        "--rationale",
        "Qlik reports scope capacity by zone; 1000 rows.",
        "--domain",
        "logistics",
        "--archetype",
        "test-carrier",
        "--refmodels-root",
        str(refroot),
    ]
    return args + list(overrides.get("extra", []))


def _outcomes() -> list[dict]:
    return [
        {"uri": "https://example.org/ont/booking#Booking", "outcome": "conforms",
         "decided_by": "user", "confidence": 0.9},
        {"uri": "https://example.org/ont/booking#CargoItem", "outcome": "conforms",
         "decided_by": "user", "confidence": 0.9},
        {"uri": "https://example.org/ont/party#BookingParty", "outcome": "conforms",
         "decided_by": "user", "confidence": 0.9},
        {"uri": "https://example.org/ont/booking#GhostConcept", "outcome": "partial",
         "decided_by": "user", "confidence": 0.9},
    ]


def _build(tmp_path: Path, refroot: Path):
    judgments = tmp_path / "judgments.yaml"
    judgments.write_text(
        yaml.safe_dump(
            {"mode": "interactive", "archetype_confirmed_by": "human",
             "core_concepts": _outcomes()},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return _run(
        ["discovery-conformance", "build", "--archetype", "test-carrier",
         "--judgments-file", str(judgments), "--refmodels-root", str(refroot)]
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_register_writes_the_artifact_and_emits_clean_json(tmp_path, refroot, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)

    res = _run(_register_args(refroot))

    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["concept"]["uri"] == _URI
    assert payload["concept"]["tier"] == "optional"
    assert (hub / REGISTERED_RELPATH).is_file()


def test_registering_a_catalog_concept_is_rejected(tmp_path, refroot, monkeypatch):
    monkeypatch.chdir(_hub(tmp_path))

    res = _run(_register_args(refroot, uri=_CATALOG_URI))

    assert res.exit_code == 1
    assert "already a core concept" in res.output


def test_outside_a_hub_fails_with_a_clear_message(tmp_path, refroot, monkeypatch):
    monkeypatch.chdir(tmp_path)

    res = _run(_register_args(refroot))

    assert res.exit_code == 1
    assert "Cannot locate an ontology hub" in res.output


def test_untagged_registration_warns_that_it_is_cross_cutting(tmp_path, refroot, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    args = [a for a in _register_args(refroot)]
    del args[args.index("--domain") : args.index("--domain") + 2]

    res = _run(args)

    assert res.exit_code == 0
    assert "cross-cutting" in res.stderr


def test_ai_registration_warns_that_it_will_block(tmp_path, refroot, monkeypatch):
    monkeypatch.chdir(_hub(tmp_path))

    res = _run(_register_args(refroot, extra=["--decided-by", "ai"]))

    assert res.exit_code == 0
    assert "block until" in res.stderr


def test_is_gated_to_the_source_skill(tmp_path):
    """A registration is proposed from analyse-sources' own output."""
    assert _SKILL_COVERED_COMMANDS["register-concept"] == "kairos-design-source"


# ---------------------------------------------------------------------------
# Integration: build mirrors, gate blocks, design-landscape surfaces
# ---------------------------------------------------------------------------


def test_build_mirrors_registrations_into_the_artifact_as_a_sibling(
    tmp_path, refroot, monkeypatch
):
    """Never merged into core_concepts -- that would fail the archetype coverage checks."""
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    assert _run(_register_args(refroot)).exit_code == 0

    res = _build(tmp_path, refroot)

    assert res.exit_code == 0, res.output
    artifact = yaml.safe_load((hub / ARTIFACT_RELPATH).read_text(encoding="utf-8"))
    assert [c["uri"] for c in artifact["registered_concepts"]] == [_URI]
    assert _URI not in [c["uri"] for c in artifact["core_concepts"]]
    # The archetype's own scorecard must stay comparable across hubs.
    assert artifact["scorecard"]["total"] == 4


def test_a_registration_does_not_make_the_archetype_look_stale_or_incomplete(
    tmp_path, refroot, monkeypatch
):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    assert _run(_register_args(refroot)).exit_code == 0
    assert _build(tmp_path, refroot).exit_code == 0

    res = _run(["discovery-conformance", "validate", "--refmodels-root", str(refroot)])

    assert res.exit_code == 0, res.output


def test_an_unresolved_ai_registration_blocks_the_discovery_gate(tmp_path, refroot, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    assert _run(_register_args(refroot, extra=["--decided-by", "ai"])).exit_code == 0
    assert _build(tmp_path, refroot).exit_code == 1  # build's own post-validation catches it

    errors = check_discovery_gate(hub)

    assert any("Planning Zone" in message for message in errors)


def test_a_confirmed_registration_does_not_block(tmp_path, refroot, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    assert _run(
        _register_args(refroot, extra=["--decided-by", "ai", "--confidence", "0.9"])
    ).exit_code == 0

    assert _build(tmp_path, refroot).exit_code == 0
    assert check_discovery_gate(hub) == []


def test_a_registration_recorded_in_core_concepts_too_is_rejected(tmp_path, refroot, monkeypatch):
    """A concept cannot be both judged against the catalog and registered outside it."""
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    assert _run(_register_args(refroot)).exit_code == 0
    assert _build(tmp_path, refroot).exit_code == 0
    artifact_path = hub / ARTIFACT_RELPATH
    artifact = yaml.safe_load(artifact_path.read_text(encoding="utf-8"))
    artifact["core_concepts"].append(
        {"uri": _URI, "label": "Planning Zone", "tier": "optional", "outcome": "conforms"}
    )
    artifact_path.write_text(yaml.safe_dump(artifact, sort_keys=False), encoding="utf-8")

    res = _run(["discovery-conformance", "validate", "--refmodels-root", str(refroot)])

    assert res.exit_code == 1
    assert "cannot be both judged and registered" in res.output


def test_next_surfaces_an_unbound_registration(tmp_path, refroot, monkeypatch):
    hub = _hub(tmp_path)
    monkeypatch.chdir(hub)
    assert _run(_register_args(refroot)).exit_code == 0

    res = _run(["next", "--format", "json"])

    assert res.exit_code == 0, res.output
    actions = json.loads(res.stdout)["actions"]
    assert "model-registered-concept" in [a["kind"] for a in actions]
