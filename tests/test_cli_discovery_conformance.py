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
    res = _run(
        [
            "discovery-conformance",
            "load",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
        ]
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["archetype"]["id"] == "test-carrier"
    assert len(payload["ref_model_modules"]) == 2
    assert len(payload["topology"]["edges"]) == 2
    assert payload["discovery_doc"].endswith("test-carrier.md")
    # Missing GhostConcept warning surfaces on stderr only.
    assert "GhostConcept" in res.stderr


def test_load_reports_ontology_tier_alongside_conformance_tier(refroot):
    """Two different meanings of "tier" must stay under two different keys (#276 Q3).

    ``tier`` is the archetype's conformance obligation (required/recommended/optional);
    ``ontology_tier`` is which reference-models tier the module lives in.
    """
    res = _run(
        [
            "discovery-conformance",
            "load",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
        ]
    )
    assert res.exit_code == 0, res.output
    modules = json.loads(res.stdout)["ref_model_modules"]
    assert {m["tier"] for m in modules} == {"required", "recommended"}
    # The fixture stores modules outside any tier prefix, so 'unknown' is correct here.
    assert all(m["ontology_tier"] == "unknown" for m in modules)


def test_unpinned_blueprint_warning_never_reaches_stderr(refroot, monkeypatch):
    """The blueprint warning is machine-only: a hub designer cannot act on it.

    It stays in the payload ``warnings`` array so CI and skills can see it, but must not print
    on every load — reference-models owns the fix, and until they publish the pin it would be a
    permanent console warning.
    """
    monkeypatch.setattr(
        "kairos_ontology.core.archetype_topology.unpinned_blueprint_modules",
        lambda *_: ["Blueprint-tier module <x> is declared but not pinned"],
    )
    res = _run(
        [
            "discovery-conformance",
            "load",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
        ]
    )
    assert res.exit_code == 0, res.output
    assert any("Blueprint-tier" in w for w in json.loads(res.stdout)["warnings"])
    assert "Blueprint-tier" not in res.stderr


def test_load_yaml_format(refroot):
    res = _run(
        [
            "discovery-conformance",
            "load",
            "--archetype",
            "test-carrier",
            "--format",
            "yaml",
            "--refmodels-root",
            str(refroot),
        ]
    )
    assert res.exit_code == 0, res.output
    payload = yaml.safe_load(res.stdout)
    assert payload["archetype"]["id"] == "test-carrier"


def test_load_unknown_archetype_exits_nonzero(refroot):
    res = _run(
        ["discovery-conformance", "load", "--archetype", "ghost", "--refmodels-root", str(refroot)]
    )
    assert res.exit_code == 2
    assert res.stdout.strip() == ""  # no machine output on failure


def _full_test_carrier_outcomes():
    """Cover all four ``test-carrier`` archetype concepts (issue #308 hole 1: the CLI's
    ``validate`` now resolves and checks coverage against the artifact's own
    ``archetype.id``, so a partial-coverage artifact would fail)."""
    return [
        {
            "uri": "https://example.org/ont/booking#Booking",
            "label": "Booking",
            "tier": "required",
            "outcome": "conforms",
        },
        {
            "uri": "https://example.org/ont/booking#CargoItem",
            "label": "Cargo Item",
            "tier": "required",
            "outcome": "conforms",
        },
        {
            "uri": "https://example.org/ont/party#BookingParty",
            "label": "Booking Party",
            "tier": "recommended",
            "outcome": "conforms",
        },
        {
            "uri": "https://example.org/ont/booking#GhostConcept",
            "label": "Ghost",
            "tier": "optional",
            "outcome": "not-applicable",
        },
    ]


def test_validate_valid_artifact(tmp_path, refroot):
    archetype = load_archetype(refroot, "test-carrier")
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=_full_test_carrier_outcomes(),
        mode="interactive",
    )
    hub = tmp_path / "hub"
    path = write_artifact(hub, art)
    res = _run(
        ["discovery-conformance", "validate", "--file", str(path), "--refmodels-root", str(refroot)]
    )
    assert res.exit_code == 0, res.output
    assert "valid" in res.stderr


def test_validate_rejects_incomplete_concept_coverage_via_artifacts_own_archetype_id(
    tmp_path, refroot
):
    """#308 hole 1, wired end-to-end: validate resolves archetype.id from the artifact
    itself (no --archetype flag) and checks coverage against it."""
    archetype = load_archetype(refroot, "test-carrier")
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=[
            {
                "uri": "https://example.org/ont/booking#Booking",
                "label": "Booking",
                "tier": "required",
                "outcome": "conforms",
            }
        ],
        mode="interactive",
    )
    hub = tmp_path / "hub"
    path = write_artifact(hub, art)
    res = _run(
        ["discovery-conformance", "validate", "--file", str(path), "--refmodels-root", str(refroot)]
    )
    assert res.exit_code == 1
    assert "missing archetype concept" in res.stderr


def test_validate_rejects_stale_hash_via_artifacts_own_archetype_id(tmp_path, refroot):
    """#308 hole 2, wired end-to-end: validate calls is_stale() against the resolved archetype."""
    archetype = load_archetype(refroot, "test-carrier")
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=_full_test_carrier_outcomes(),
        mode="interactive",
    )
    art["archetype"]["concept_set_hash"] = "deadbeef"
    hub = tmp_path / "hub"
    path = write_artifact(hub, art)
    res = _run(
        ["discovery-conformance", "validate", "--file", str(path), "--refmodels-root", str(refroot)]
    )
    assert res.exit_code == 1
    assert "stale" in res.stderr.lower()


def test_validate_invalid_artifact_exits_one(tmp_path, refroot):
    archetype = load_archetype(refroot, "test-carrier")
    art = build_artifact(
        archetype=archetype,
        refmodels_version="1.11.0",
        outcomes=[{"uri": "u", "tier": "required", "outcome": "bogus"}],
        mode="interactive",
    )
    hub = tmp_path / "hub"
    path = write_artifact(hub, art)
    res = _run(
        ["discovery-conformance", "validate", "--file", str(path), "--refmodels-root", str(refroot)]
    )
    assert res.exit_code == 1
    assert "invalid" in res.stderr


# --- discovery-conformance build (issue #311) ---------------------------------------------


def _write_judgments(path, outcomes, *, mode="interactive"):
    path.write_text(
        yaml.safe_dump({"mode": mode, "core_concepts": outcomes}, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _default_artifact_path(hub):
    return hub / "integration" / "discovery" / "core-concepts-conformance.yaml"


def test_build_happy_path_writes_valid_artifact(tmp_path, refroot, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    judgments = _write_judgments(tmp_path / "judgments.yaml", _full_test_carrier_outcomes())

    res = _run(
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
    assert res.exit_code == 0, res.output
    out_path = _default_artifact_path(hub)
    assert out_path.is_file()
    artifact = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == 2
    assert artifact["scorecard"]["total"] == 4
    assert artifact["archetype"]["catalog_hash"]
    assert artifact["archetype"]["concept_set_hash"]
    assert "Wrote conformance artifact" in res.stderr
    assert "valid" in res.stderr


def test_build_malformed_judgments_missing_core_concepts_exits_two(tmp_path, refroot, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    judgments = tmp_path / "judgments.yaml"
    judgments.write_text(yaml.safe_dump({"mode": "interactive"}), encoding="utf-8")

    res = _run(
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
    assert res.exit_code == 2
    assert "core_concepts" in res.stderr
    assert not _default_artifact_path(hub).exists()


def test_build_malformed_judgments_not_a_mapping_exits_two(tmp_path, refroot, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    judgments = tmp_path / "judgments.yaml"
    judgments.write_text(yaml.safe_dump(["not", "a", "mapping"]), encoding="utf-8")

    res = _run(
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
    assert res.exit_code == 2
    assert "mapping" in res.stderr
    assert not _default_artifact_path(hub).exists()


def test_build_default_validate_catches_incomplete_coverage(tmp_path, refroot, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    # Drop the last concept (GhostConcept) — incomplete coverage.
    incomplete = _full_test_carrier_outcomes()[:-1]
    judgments = _write_judgments(tmp_path / "judgments.yaml", incomplete)

    res = _run(
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
    assert res.exit_code == 1
    assert "missing archetype concept" in res.stderr
    # The artifact IS written (build writes before validating) but the command still fails.
    assert _default_artifact_path(hub).is_file()


def test_build_no_validate_decouples_write_from_validation(tmp_path, refroot, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    incomplete = _full_test_carrier_outcomes()[:-1]
    judgments = _write_judgments(tmp_path / "judgments.yaml", incomplete)

    res = _run(
        [
            "discovery-conformance",
            "build",
            "--archetype",
            "test-carrier",
            "--judgments-file",
            str(judgments),
            "--refmodels-root",
            str(refroot),
            "--no-validate",
        ]
    )
    assert res.exit_code == 0, res.output
    out_path = _default_artifact_path(hub)
    assert out_path.is_file()

    # A separate, subsequent validate call on that same file now fails.
    validate_res = _run(
        [
            "discovery-conformance",
            "validate",
            "--file",
            str(out_path),
            "--refmodels-root",
            str(refroot),
        ]
    )
    assert validate_res.exit_code == 1
    assert "missing archetype concept" in validate_res.stderr


def test_build_output_writes_to_explicit_path(tmp_path, refroot, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    judgments = _write_judgments(tmp_path / "judgments.yaml", _full_test_carrier_outcomes())
    explicit_output = tmp_path / "somewhere-else" / "artifact.yaml"

    res = _run(
        [
            "discovery-conformance",
            "build",
            "--archetype",
            "test-carrier",
            "--judgments-file",
            str(judgments),
            "--refmodels-root",
            str(refroot),
            "--output",
            str(explicit_output),
        ]
    )
    assert res.exit_code == 0, res.output
    assert explicit_output.is_file()
    assert not _default_artifact_path(hub).exists()
    artifact = yaml.safe_load(explicit_output.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == 2


def test_build_allow_unresolved_passthrough(tmp_path, refroot, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    outcomes = _full_test_carrier_outcomes()
    # Mark one concept as an unresolved AI-decided (fleet-mode) judgment.
    outcomes[0] = {
        **outcomes[0],
        "decided_by": "ai",
        "needs_confirmation": True,
    }
    judgments = _write_judgments(tmp_path / "judgments.yaml", outcomes, mode="fleet")

    args = [
        "discovery-conformance",
        "build",
        "--archetype",
        "test-carrier",
        "--judgments-file",
        str(judgments),
        "--refmodels-root",
        str(refroot),
    ]

    res_fail = _run(args)
    assert res_fail.exit_code == 1
    assert "unresolved" in res_fail.stderr

    res_pass = _run([*args, "--allow-unresolved"])
    assert res_pass.exit_code == 0, res_pass.output
    assert _default_artifact_path(hub).is_file()
