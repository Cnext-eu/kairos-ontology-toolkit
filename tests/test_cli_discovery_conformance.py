# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI tests for `kairos-ontology discovery-conformance` (DD-090).

Asserts machine output on stdout is parseable (clean) and diagnostics go to stderr.
"""

from __future__ import annotations

import json

import pytest
import yaml
from click.testing import CliRunner

from archetype_fixtures import build_refmodels_root
from kairos_ontology.core.archetype_loader import load_archetype
from kairos_ontology.cli.main import cli
from kairos_ontology.core.conformance_artifact import build_artifact, write_artifact


@pytest.fixture()
def refroot(tmp_path):
    return build_refmodels_root(tmp_path)


@pytest.fixture(autouse=True)
def _skill_context(monkeypatch):
    # Silence the soft skill-gate so it never pollutes captured output.
    monkeypatch.setenv("KAIROS_SKILL_CONTEXT", "1")


def _run(args):
    return CliRunner().invoke(cli, args)


def test_list_archetypes_emits_clean_json(refroot):
    res = _run(["discovery-conformance", "list-archetypes", "--refmodels-root", str(refroot)])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)  # must parse — no diagnostics mixed in
    assert payload["archetypes"] == ["test-carrier"]
    assert "conforms" in payload["outcome_codes"]
    # The "Reference-models root" progress line is on stderr, not stdout.
    assert "Reference-models root" in res.stderr


def test_load_emits_clean_json_with_topology(refroot):
    res = _run(["discovery-conformance", "load", "--archetype", "test-carrier",
                "--refmodels-root", str(refroot)])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["archetype"]["id"] == "test-carrier"
    assert len(payload["ref_model_modules"]) == 2
    assert len(payload["topology"]["edges"]) == 2
    assert payload["discovery_doc"].endswith("test-carrier.md")
    # Missing GhostConcept warning surfaces on stderr only.
    assert "GhostConcept" in res.stderr


def test_load_yaml_format(refroot):
    res = _run(["discovery-conformance", "load", "--archetype", "test-carrier",
                "--format", "yaml", "--refmodels-root", str(refroot)])
    assert res.exit_code == 0, res.output
    payload = yaml.safe_load(res.stdout)
    assert payload["archetype"]["id"] == "test-carrier"


def test_load_unknown_archetype_exits_nonzero(refroot):
    res = _run(["discovery-conformance", "load", "--archetype", "ghost",
                "--refmodels-root", str(refroot)])
    assert res.exit_code == 2
    assert res.stdout.strip() == ""  # no machine output on failure


def test_validate_valid_artifact(tmp_path, refroot):
    archetype = load_archetype(refroot, "test-carrier")
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0",
        outcomes=[{"uri": "https://example.org/ont/booking#Booking", "label": "Booking",
                   "tier": "required", "outcome": "conforms"}],
    )
    hub = tmp_path / "hub"
    path = write_artifact(hub, art)
    res = _run(["discovery-conformance", "validate", "--file", str(path),
                "--refmodels-root", str(refroot)])
    assert res.exit_code == 0, res.output
    assert "valid" in res.stderr


def test_validate_invalid_artifact_exits_one(tmp_path, refroot):
    archetype = load_archetype(refroot, "test-carrier")
    art = build_artifact(
        archetype=archetype, refmodels_version="1.11.0",
        outcomes=[{"uri": "u", "tier": "required", "outcome": "bogus"}],
    )
    hub = tmp_path / "hub"
    path = write_artifact(hub, art)
    res = _run(["discovery-conformance", "validate", "--file", str(path),
                "--refmodels-root", str(refroot)])
    assert res.exit_code == 1
    assert "invalid" in res.stderr
