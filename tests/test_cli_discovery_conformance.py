# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""CLI tests for `kairos-ontology discovery-conformance` (DD-090).

Asserts machine output on stdout is parseable (clean) and diagnostics go to stderr.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from archetype_fixtures import build_refmodels_root
from kairos_ontology.core.archetype_loader import load_archetype
from kairos_ontology.cli.main import cli
from kairos_ontology.core.conformance_artifact import build_artifact, write_artifact
from kairos_ontology.core.hub_utils import is_scaffold_placeholder_text


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
    # #313: discovery_doc must be relative to the reference-models root, not an
    # absolute, machine-local path.
    assert not Path(payload["discovery_doc"]).is_absolute()
    assert payload["discovery_doc"] == "accelerator-packs/logistics/discovery/test-carrier.md"
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


# --- discovery-conformance build: 'label'/'tier' derivation (issue #410) ------------------


def test_build_derives_missing_label_from_catalog(tmp_path, refroot, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    outcomes = _full_test_carrier_outcomes()
    for outcome in outcomes:
        del outcome["label"]
    judgments = _write_judgments(tmp_path / "judgments.yaml", outcomes)

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
    artifact = yaml.safe_load(_default_artifact_path(hub).read_text(encoding="utf-8"))
    labels = {c["uri"]: c["label"] for c in artifact["core_concepts"]}
    assert labels["https://example.org/ont/booking#Booking"] == "Booking"
    assert labels["https://example.org/ont/booking#GhostConcept"] == "Ghost"


def test_build_derives_missing_tier_from_catalog(tmp_path, refroot, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    outcomes = _full_test_carrier_outcomes()
    for outcome in outcomes:
        del outcome["tier"]
    judgments = _write_judgments(tmp_path / "judgments.yaml", outcomes)

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
    artifact = yaml.safe_load(_default_artifact_path(hub).read_text(encoding="utf-8"))
    tiers = {c["uri"]: c["tier"] for c in artifact["core_concepts"]}
    assert tiers["https://example.org/ont/booking#Booking"] == "required"
    assert tiers["https://example.org/ont/party#BookingParty"] == "recommended"
    assert tiers["https://example.org/ont/booking#GhostConcept"] == "optional"


def test_build_wrong_label_still_fails_validation(tmp_path, refroot, monkeypatch):
    """Derivation must not swallow a genuinely wrong, hand-supplied 'label' (issue #410)."""
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    outcomes = _full_test_carrier_outcomes()
    outcomes[0]["label"] = "Totally Wrong Label"
    judgments = _write_judgments(tmp_path / "judgments.yaml", outcomes)

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
    assert "does not match the catalog label" in res.stderr
    # The artifact IS written (build writes before validating) with the wrong label intact --
    # derivation must not have silently overwritten it into a false "valid" result.
    artifact = yaml.safe_load(_default_artifact_path(hub).read_text(encoding="utf-8"))
    assert artifact["core_concepts"][0]["label"] == "Totally Wrong Label"


def test_build_wrong_tier_still_fails_validation(tmp_path, refroot, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    outcomes = _full_test_carrier_outcomes()
    outcomes[0]["tier"] = "optional"  # catalog says "required" for Booking
    judgments = _write_judgments(tmp_path / "judgments.yaml", outcomes)

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
    assert "does not match the catalog tier" in res.stderr


# --- discovery-conformance judgments-template (issue #410) -------------------------------


def test_judgments_template_no_output_writes_clean_json_to_stdout(refroot):
    res = _run(
        [
            "discovery-conformance",
            "judgments-template",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
        ]
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)  # must parse — no diagnostics mixed in
    assert payload["mode"] == "interactive"
    assert len(payload["core_concepts"]) == 4
    uris = {c["uri"] for c in payload["core_concepts"]}
    assert uris == {
        "https://example.org/ont/booking#Booking",
        "https://example.org/ont/booking#CargoItem",
        "https://example.org/ont/party#BookingParty",
        "https://example.org/ont/booking#GhostConcept",
    }


def test_judgments_template_prefills_label_and_tier_from_catalog(refroot):
    res = _run(
        [
            "discovery-conformance",
            "judgments-template",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
            "--format",
            "yaml",
        ]
    )
    assert res.exit_code == 0, res.output
    payload = yaml.safe_load(res.stdout)
    by_uri = {c["uri"]: c for c in payload["core_concepts"]}
    booking = by_uri["https://example.org/ont/booking#Booking"]
    assert booking["label"] == "Booking"
    assert booking["tier"] == "required"


def test_judgments_template_unfilled_fields_are_scaffold_placeholders(refroot):
    """The unedited template must actually compose with the #416 content lint: its sentinel
    fields are recognised by the shared ``is_scaffold_placeholder_text`` predicate, while the
    catalog-derived ``label``/``tier`` (never meant to be edited) are not."""
    res = _run(
        [
            "discovery-conformance",
            "judgments-template",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
        ]
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert len(payload["core_concepts"]) == 4
    for concept in payload["core_concepts"]:
        assert is_scaffold_placeholder_text(concept["outcome"])
        assert is_scaffold_placeholder_text(concept["rationale"])
        assert not is_scaffold_placeholder_text(concept["label"])
        assert not is_scaffold_placeholder_text(concept["tier"])


def test_judgments_template_output_refuses_to_clobber_without_overwrite(tmp_path, refroot):
    destination = tmp_path / "judgments.yaml"
    destination.write_text("pre-existing content\n", encoding="utf-8")

    res = _run(
        [
            "discovery-conformance",
            "judgments-template",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
            "--output",
            str(destination),
        ]
    )
    assert res.exit_code != 0
    assert destination.read_text(encoding="utf-8") == "pre-existing content\n"

    res_overwrite = _run(
        [
            "discovery-conformance",
            "judgments-template",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
            "--output",
            str(destination),
            "--overwrite",
        ]
    )
    assert res_overwrite.exit_code == 0, res_overwrite.output
    written = yaml.safe_load(destination.read_text(encoding="utf-8"))
    assert len(written["core_concepts"]) == 4


def test_judgments_template_infers_yaml_from_output_suffix(tmp_path, refroot):
    """No explicit --format: output suffix .yaml yields YAML content (issue #435)."""
    destination = tmp_path / "t.yaml"
    res = _run(
        [
            "discovery-conformance",
            "judgments-template",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
            "--output",
            str(destination),
        ]
    )
    assert res.exit_code == 0, res.output
    content = destination.read_text(encoding="utf-8")
    assert "core_concepts:" in content
    written = yaml.safe_load(content)
    assert len(written["core_concepts"]) == 4


def test_judgments_template_infers_json_from_output_suffix(tmp_path, refroot):
    """No explicit --format: output suffix .json yields JSON content (issue #435)."""
    destination = tmp_path / "t.json"
    res = _run(
        [
            "discovery-conformance",
            "judgments-template",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
            "--output",
            str(destination),
        ]
    )
    assert res.exit_code == 0, res.output
    content = destination.read_text(encoding="utf-8")
    assert content.lstrip().startswith("{")
    written = json.loads(content)
    assert len(written["core_concepts"]) == 4


def test_judgments_template_explicit_format_mismatch_warns_on_stderr(tmp_path, refroot):
    """--format json --output t.yaml writes JSON but warns on stderr (issue #435)."""
    destination = tmp_path / "t.yaml"
    res = _run(
        [
            "discovery-conformance",
            "judgments-template",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
            "--format",
            "json",
            "--output",
            str(destination),
        ]
    )
    assert res.exit_code == 0, res.output
    content = destination.read_text(encoding="utf-8")
    assert content.lstrip().startswith("{")
    json.loads(content)  # must be valid JSON despite .yaml suffix
    assert "does not match" in res.stderr


def test_judgments_template_explicit_yaml_mismatch_warns_on_stderr(tmp_path, refroot):
    """--format yaml --output t.json writes YAML but warns on stderr (issue #435)."""
    destination = tmp_path / "t.json"
    res = _run(
        [
            "discovery-conformance",
            "judgments-template",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
            "--format",
            "yaml",
            "--output",
            str(destination),
        ]
    )
    assert res.exit_code == 0, res.output
    content = destination.read_text(encoding="utf-8")
    assert "core_concepts:" in content
    yaml.safe_load(content)  # must be valid YAML despite .json suffix
    assert "does not match" in res.stderr


def test_judgments_template_roundtrip_build_succeeds(tmp_path, refroot, monkeypatch):
    """The prescribed path (issue #410): scaffold the template, fill in outcomes, `build`."""
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)

    template_res = _run(
        [
            "discovery-conformance",
            "judgments-template",
            "--archetype",
            "test-carrier",
            "--refmodels-root",
            str(refroot),
            "--format",
            "yaml",
        ]
    )
    assert template_res.exit_code == 0, template_res.output
    template = yaml.safe_load(template_res.stdout)
    assert len(template["core_concepts"]) == 4

    for concept in template["core_concepts"]:
        concept["outcome"] = "conforms"
        concept["confidence"] = 0.9
        concept["rationale"] = "Confirmed with the SME during the interview."
        concept["decided_by"] = "user"

    judgments_path = tmp_path / "judgments.yaml"
    judgments_path.write_text(yaml.safe_dump(template, sort_keys=False), encoding="utf-8")

    build_res = _run(
        [
            "discovery-conformance",
            "build",
            "--archetype",
            "test-carrier",
            "--judgments-file",
            str(judgments_path),
            "--refmodels-root",
            str(refroot),
        ]
    )
    assert build_res.exit_code == 0, build_res.output
    artifact = yaml.safe_load(_default_artifact_path(hub).read_text(encoding="utf-8"))
    assert artifact["scorecard"]["total"] == 4
    assert all(c["outcome"] == "conforms" for c in artifact["core_concepts"])


# --- discovery-conformance summarize (issue #438) ----------------------------------------

def test_summarize_happy_path_emits_scorecard_and_open_questions(tmp_path, refroot, monkeypatch):
    """Summarize on a real artifact emits scorecard, average confidence, needs_confirmation
    count, and open_questions in clean JSON on stdout."""
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    outcomes = _full_test_carrier_outcomes()
    outcomes[0]["confidence"] = 0.9
    outcomes[1]["confidence"] = 0.7
    outcomes[0]["decided_by"] = "user"
    outcomes[1]["decided_by"] = "user"
    outcomes[2]["decided_by"] = "user"
    outcomes[3]["decided_by"] = "user"
    judgments = _write_judgments(tmp_path / "judgments.yaml", outcomes)
    build_res = _run(
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
    assert build_res.exit_code == 0, build_res.output

    res = _run(["discovery-conformance", "summarize"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["scorecard"]["total"] == 4
    assert payload["scorecard"]["by_outcome"]["conforms"] == 3
    assert payload["scorecard"]["by_outcome"]["not-applicable"] == 1
    assert payload["average_confidence"] is not None
    assert payload["needs_confirmation_count"] == 0
    assert payload["open_questions"] == []
    assert payload["unfilled"] == []
    assert payload["unfilled_count"] == 0


def test_summarize_reports_average_confidence_and_needs_confirmation(tmp_path, refroot, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    outcomes = _full_test_carrier_outcomes()
    outcomes[0]["confidence"] = 0.8
    outcomes[1]["confidence"] = 0.6
    outcomes[0]["needs_confirmation"] = True
    outcomes[0]["decided_by"] = "ai"
    outcomes[1]["decided_by"] = "user"
    outcomes[2]["decided_by"] = "user"
    outcomes[3]["decided_by"] = "user"
    judgments = _write_judgments(tmp_path / "judgments.yaml", outcomes)
    build_res = _run(
        [
            "discovery-conformance",
            "build",
            "--archetype",
            "test-carrier",
            "--judgments-file",
            str(judgments),
            "--refmodels-root",
            str(refroot),
            "--allow-unresolved",
        ]
    )
    assert build_res.exit_code == 0, build_res.output

    res = _run(["discovery-conformance", "summarize"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["average_confidence"] is not None
    assert payload["needs_confirmation_count"] == 1
    # The AI-decided, needs_confirmation concept must appear in open_questions.
    assert len(payload["open_questions"]) == 1
    assert payload["open_questions"][0]["reason"] == "needs_confirmation"


def test_summarize_outcome_filter_restricts_scorecard(tmp_path, refroot, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    outcomes = _full_test_carrier_outcomes()
    for o in outcomes:
        o["decided_by"] = "user"
    judgments = _write_judgments(tmp_path / "judgments.yaml", outcomes)
    build_res = _run(
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
    assert build_res.exit_code == 0, build_res.output

    res = _run(
        ["discovery-conformance", "summarize", "--outcome", "conforms"]
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["scorecard"]["total"] == 3
    assert "not-applicable" not in payload["scorecard"]["by_outcome"]


def test_summarize_yaml_format(refroot, tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    outcomes = _full_test_carrier_outcomes()
    for o in outcomes:
        o["decided_by"] = "user"
    judgments = _write_judgments(tmp_path / "judgments.yaml", outcomes)
    build_res = _run(
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
    assert build_res.exit_code == 0, build_res.output

    res = _run(["discovery-conformance", "summarize", "--format", "yaml"])
    assert res.exit_code == 0, res.output
    payload = yaml.safe_load(res.stdout)
    assert payload["scorecard"]["total"] == 4


def test_summarize_judgments_file_tolerates_confirm_outcome_sentinels(tmp_path):
    """A judgments-file template still carrying <CONFIRM_OUTCOME:...> sentinels must not
    error — those entries are reported in the 'unfilled' bucket."""
    template = {
        "mode": "interactive",
        "core_concepts": [
            {
                "uri": "https://example.org/ont/booking#Booking",
                "label": "Booking",
                "tier": "required",
                "outcome": "<CONFIRM_OUTCOME:conforms|conforms-with-rename|partial|deviates|not-applicable>",
            },
            {
                "uri": "https://example.org/ont/booking#CargoItem",
                "label": "Cargo Item",
                "tier": "required",
                "outcome": "conforms",
                "confidence": 0.9,
                "decided_by": "user",
            },
        ],
    }
    jfile = tmp_path / "judgments.yaml"
    jfile.write_text(yaml.safe_dump(template, sort_keys=False), encoding="utf-8")

    res = _run(
        ["discovery-conformance", "summarize", "--judgments-file", str(jfile)]
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["scorecard"]["total"] == 1
    assert payload["unfilled_count"] == 1
    assert payload["unfilled"][0]["uri"] == "https://example.org/ont/booking#Booking"


def test_summarize_judgments_file_tolerates_missing_outcome(tmp_path):
    """An entry with no 'outcome' field at all is also unfilled, not an error."""
    template = {
        "mode": "interactive",
        "core_concepts": [
            {
                "uri": "https://example.org/ont/booking#Booking",
                "label": "Booking",
                "tier": "required",
            },
        ],
    }
    jfile = tmp_path / "judgments.yaml"
    jfile.write_text(yaml.safe_dump(template, sort_keys=False), encoding="utf-8")

    res = _run(
        ["discovery-conformance", "summarize", "--judgments-file", str(jfile)]
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["scorecard"]["total"] == 0
    assert payload["unfilled_count"] == 1


def test_summarize_judgments_file_tolerates_absent_label_and_tier(tmp_path):
    """Absent label/tier fields must not cause an error."""
    template = {
        "mode": "interactive",
        "core_concepts": [
            {"uri": "u1", "outcome": "conforms", "confidence": 0.5},
        ],
    }
    jfile = tmp_path / "judgments.yaml"
    jfile.write_text(yaml.safe_dump(template, sort_keys=False), encoding="utf-8")

    res = _run(
        ["discovery-conformance", "summarize", "--judgments-file", str(jfile)]
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["scorecard"]["total"] == 1


def test_summarize_missing_artifact_file_exits_two(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    monkeypatch.chdir(hub)
    res = _run(["discovery-conformance", "summarize"])
    assert res.exit_code == 2
    assert "not found" in res.stderr.lower()


def test_summarize_malformed_judgments_file_exits_two(tmp_path):
    jfile = tmp_path / "bad.yaml"
    jfile.write_text(yaml.safe_dump(["not", "a", "mapping"]), encoding="utf-8")
    res = _run(
        ["discovery-conformance", "summarize", "--judgments-file", str(jfile)]
    )
    assert res.exit_code == 2
    assert "mapping" in res.stderr
