# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
from pathlib import Path

import pytest
from click.testing import CliRunner

from kairos_ontology.core.claim_registry import (
    Claim,
    ClaimRegistry,
    EvidenceSource,
    load_registry,
    registry_path,
    validate_registry,
    validation_errors,
    write_registry,
)
from kairos_ontology.cli.main import cli
from kairos_ontology.core.decide_claims import (
    ClaimSelector,
    apply_decisions,
    parse_by_disposition,
    select_claims,
    validate_filter_values,
)


def _registry() -> ClaimRegistry:
    return ClaimRegistry(
        domain="party",
        claims=[
            Claim(
                id="party-trade-party",
                type="class",
                status="proposed",
                disposition="claim",
                origin="imported",
                class_uri="https://example.org/ref/party#TradeParty",
                evidence_sources=[
                    EvidenceSource(type="source_table", system="crm", table="account")
                ],
            ),
            Claim(
                id="party-custom-note",
                type="property",
                status="proposed",
                disposition="passthrough",
                origin="authored",
                evidence_sources=[
                    EvidenceSource(
                        type="source_column", system="crm", table="account", column="NOTE_TXT"
                    )
                ],
            ),
            Claim(
                id="party-legacy-id",
                type="property",
                status="proposed",
                disposition="skip",
                origin="authored",
                evidence_sources=[
                    EvidenceSource(
                        type="source_column", system="crm", table="account", column="LEGACY_ID"
                    )
                ],
            ),
        ],
    )


# --------------------------------------------------------------------------- #
# select_claims / ClaimSelector
# --------------------------------------------------------------------------- #


def test_select_by_disposition():
    reg = _registry()
    matches = select_claims(reg, ClaimSelector(disposition=["claim"]))
    assert [c.id for c in matches] == ["party-trade-party"]


def test_select_by_type_and_origin():
    reg = _registry()
    matches = select_claims(reg, ClaimSelector(type=["property"], origin=["authored"]))
    assert {c.id for c in matches} == {"party-custom-note", "party-legacy-id"}


def test_select_by_id_glob():
    reg = _registry()
    matches = select_claims(reg, ClaimSelector(id_globs=["party-custom-*"]))
    assert [c.id for c in matches] == ["party-custom-note"]


def test_select_by_column_glob_case_insensitive():
    reg = _registry()
    matches = select_claims(reg, ClaimSelector(column_globs=["*_id"]))
    assert [c.id for c in matches] == ["party-legacy-id"]


def test_empty_selector_matches_all():
    reg = _registry()
    sel = ClaimSelector()
    assert sel.is_empty
    assert len(select_claims(reg, sel)) == 3


# --------------------------------------------------------------------------- #
# parse_by_disposition
# --------------------------------------------------------------------------- #


def test_parse_by_disposition_ok():
    assert parse_by_disposition("claim=approved,skip=rejected") == {
        "claim": "approved",
        "skip": "rejected",
    }


@pytest.mark.parametrize("spec", ["", "claim", "bogus=approved", "claim=bogus"])
def test_parse_by_disposition_rejects_bad_input(spec):
    with pytest.raises(ValueError):
        parse_by_disposition(spec)


def test_validate_filter_values_rejects_unknown():
    with pytest.raises(ValueError):
        validate_filter_values(
            status=["nope"], disposition=None, type_=None, origin=None
        )


# --------------------------------------------------------------------------- #
# apply_decisions
# --------------------------------------------------------------------------- #


def test_apply_set_status_with_selector():
    reg = _registry()
    summary = apply_decisions(
        reg, selector=ClaimSelector(disposition=["claim"]), set_status="approved"
    )
    assert len(summary.applied) == 1
    assert reg.claims[0].status == "approved"
    # untouched claims keep their status
    assert reg.claims[1].status == "proposed"


def test_apply_by_disposition_bulk():
    reg = _registry()
    summary = apply_decisions(
        reg,
        selector=ClaimSelector(),
        by_disposition={"claim": "approved", "passthrough": "approved", "skip": "rejected"},
    )
    assert len(summary.applied) == 3
    assert reg.claims[0].status == "approved"
    assert reg.claims[1].status == "approved"
    assert reg.claims[2].status == "rejected"


def test_apply_blocks_approval_when_required_uri_missing():
    reg = _registry()
    reg.claims[0].class_uri = None

    summary = apply_decisions(
        reg,
        selector=ClaimSelector(),
        by_disposition={"claim": "approved", "passthrough": "approved", "skip": "rejected"},
    )

    assert len(summary.blocked) == 1
    assert "requires 'class_uri'" in summary.blocked[0].reason
    assert [c.status for c in reg.claims] == ["proposed", "proposed", "proposed"]


def test_passthrough_approval_does_not_require_uri():
    reg = _registry()
    summary = apply_decisions(
        reg,
        selector=ClaimSelector(disposition=["passthrough"]),
        set_status="approved",
    )

    assert summary.blocked == []
    assert reg.claims[1].status == "approved"


def test_apply_skips_invalid_transition():
    reg = _registry()
    reg.claims[0].status = "rejected"  # terminal
    summary = apply_decisions(
        reg, selector=ClaimSelector(id_globs=["party-trade-party"]), set_status="approved"
    )
    assert summary.applied == []
    assert len(summary.skipped) == 1
    assert "invalid transition" in summary.skipped[0].reason
    assert reg.claims[0].status == "rejected"


def test_apply_skips_same_status():
    reg = _registry()
    summary = apply_decisions(
        reg, selector=ClaimSelector(id_globs=["party-trade-party"]), set_status="proposed"
    )
    assert summary.applied == []
    assert "already" in summary.skipped[0].reason


def test_dry_run_does_not_mutate():
    reg = _registry()
    summary = apply_decisions(
        reg, selector=ClaimSelector(), set_status="approved", dry_run=True
    )
    # results report intent, but no claim is changed
    assert len(summary.applied) == 3
    assert all(c.status == "proposed" for c in reg.claims)


def test_apply_requires_exactly_one_mode():
    reg = _registry()
    with pytest.raises(ValueError):
        apply_decisions(reg, selector=ClaimSelector())
    with pytest.raises(ValueError):
        apply_decisions(
            reg, selector=ClaimSelector(), set_status="approved",
            by_disposition={"claim": "approved"},
        )


# --------------------------------------------------------------------------- #
# Minimal-diff round-trip (issue #190 item 3)
# --------------------------------------------------------------------------- #


def test_decision_yields_minimal_diff(tmp_path):
    reg = _registry()
    path = registry_path(tmp_path, "party")
    write_registry(reg, path)
    before = path.read_text(encoding="utf-8").splitlines()

    loaded = load_registry(path)
    apply_decisions(
        loaded, selector=ClaimSelector(disposition=["claim"]), set_status="approved"
    )
    write_registry(loaded, path)
    after = path.read_text(encoding="utf-8").splitlines()

    diff = [
        (b, a) for b, a in zip(before, after, strict=False) if b != a
    ]
    # Exactly one logical line changed: the status of the single 'claim' claim.
    assert len(before) == len(after)
    assert len(diff) == 1
    assert diff[0][0].strip() == "status: proposed"
    assert diff[0][1].strip() == "status: approved"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _seed_claims_dir(tmp_path: Path) -> Path:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    write_registry(_registry(), registry_path(claims_dir, "party"))
    return claims_dir


def test_cli_list(tmp_path):
    claims_dir = _seed_claims_dir(tmp_path)
    result = CliRunner().invoke(
        cli,
        ["decide-claims", "--claims-dir", str(claims_dir), "--domains", "party",
         "--list", "--disposition", "claim"],
    )
    assert result.exit_code == 0, result.output
    assert "party-trade-party" in result.output
    assert "party-custom-note" not in result.output


def test_cli_by_disposition_writes(tmp_path):
    claims_dir = _seed_claims_dir(tmp_path)
    result = CliRunner().invoke(
        cli,
        ["decide-claims", "--claims-dir", str(claims_dir), "--domains", "party",
         "--by-disposition", "claim=approved,passthrough=approved,skip=rejected"],
    )
    assert result.exit_code == 0, result.output
    reg = load_registry(registry_path(claims_dir, "party"))
    statuses = {c.id: c.status for c in reg.claims}
    assert statuses == {
        "party-trade-party": "approved",
        "party-custom-note": "approved",
        "party-legacy-id": "rejected",
    }
    assert validation_errors(validate_registry(reg)) == []


def test_cli_blocks_invalid_approval_without_writing(tmp_path):
    claims_dir = _seed_claims_dir(tmp_path)
    path = registry_path(claims_dir, "party")
    reg = load_registry(path)
    reg.claims[0].class_uri = None
    write_registry(reg, path)
    before = path.read_text(encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        ["decide-claims", "--claims-dir", str(claims_dir), "--domains", "party",
         "--by-disposition", "claim=approved,passthrough=approved,skip=rejected"],
    )

    assert result.exit_code == 1
    assert "Approval blocked" in result.output
    assert "requires 'class_uri'" in result.output
    assert path.read_text(encoding="utf-8") == before


def test_cli_blocks_command_wide_without_partial_writes(tmp_path):
    claims_dir = _seed_claims_dir(tmp_path)
    other = _registry()
    other.domain = "billing"
    other.claims[0].id = "billing-trade-party"
    other.claims[1].id = "billing-custom-note"
    other.claims[2].id = "billing-legacy-id"
    other.claims[0].class_uri = None
    write_registry(other, registry_path(claims_dir, "billing"))

    party_path = registry_path(claims_dir, "party")
    billing_path = registry_path(claims_dir, "billing")
    party_before = party_path.read_text(encoding="utf-8")
    billing_before = billing_path.read_text(encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        ["decide-claims", "--claims-dir", str(claims_dir),
         "--by-disposition", "claim=approved,passthrough=approved,skip=rejected"],
    )

    assert result.exit_code == 1
    assert party_path.read_text(encoding="utf-8") == party_before
    assert billing_path.read_text(encoding="utf-8") == billing_before


def test_cli_dry_run_writes_nothing(tmp_path):
    claims_dir = _seed_claims_dir(tmp_path)
    path = registry_path(claims_dir, "party")
    before = path.read_text(encoding="utf-8")
    result = CliRunner().invoke(
        cli,
        ["decide-claims", "--claims-dir", str(claims_dir), "--domains", "party",
         "--set-status", "approved", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert "Dry run" in result.output
    assert path.read_text(encoding="utf-8") == before


def test_cli_requires_action(tmp_path):
    claims_dir = _seed_claims_dir(tmp_path)
    result = CliRunner().invoke(
        cli,
        ["decide-claims", "--claims-dir", str(claims_dir), "--domains", "party"],
    )
    assert result.exit_code == 2
    assert "Nothing to do" in result.output


def test_cli_unknown_domain_errors(tmp_path):
    claims_dir = _seed_claims_dir(tmp_path)
    result = CliRunner().invoke(
        cli,
        ["decide-claims", "--claims-dir", str(claims_dir), "--domains", "ghost",
         "--list"],
    )
    assert result.exit_code == 1
    assert "No claims file" in result.output
