# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for the Slice 4 MDM / ownership governance gates.

These tests exercise the hardened, deterministic ``check-claims`` governance
scans (``src/kairos_ontology/claim_coverage.py``) against a synthetic,
acme-hub-style hub.  Slice 4 layered four new scans onto the gate:

* **MDM-anchor gate** — an approved broad (materializing) class claim requires
  its domain's declared ``mdm_anchor`` reference-data anchors to be decided;
  still-``proposed`` anchors block (``anchor_pending``) and broad claims with no
  declared anchors warn (``anchor_missing``).
* **deviation-log** — an approved ``gap`` (client-native) claim must carry a
  ``Deviation`` (owner + reason); missing → ``deviation_missing`` (blocking).
* **ownership-boundary** — an approved claim whose ``class_uri`` namespace is
  owned by a *different* data-domain (per ``data-domains.yaml``) blocks as an
  ``OwnershipConflict`` unless it carries a well-formed ``OwnershipOverride``.
* **passthrough-review** — a high-use passthrough claim not yet
  ``passthrough_reviewed`` → ``passthrough_review`` (warning, never blocking on
  its own).

**No-permanent-claims constraint (inherited from Slice 2/3):** the permanent
``tests/scenarios/acme-hub/`` fixture deliberately has **no** ``model/claims/``
directory, because the projector's claim-authority gate fires for *any* domain
that owns a permanent ``model/claims/{domain}-claims.yaml`` — which would break
the shared projection scenario tests.  Therefore every registry + affinity file
below is built under ``tmp_path`` and **nothing** is ever written into the real
acme-hub.  The governance scans are asserted on their specific report buckets
(``anchor_pending`` / ``deviation_missing`` / ``ownership_conflicts`` /
``passthrough_review``) so unrelated coverage/freshness state never confuses the
result.
"""

from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.alignment_coverage import (
    ALIGNMENT_ALGORITHM_VERSION,
    compute_affinity_hash,
)
from kairos_ontology.claim_coverage import check_claims_coverage
from kairos_ontology.claim_registry import (
    Claim,
    ClaimRegistry,
    CoverageSystem,
    CoverageTable,
    Deviation,
    EvidenceSource,
    Freshness,
    OwnershipOverride,
    ReferenceData,
    registry_path,
    write_registry,
)
from kairos_ontology.cli.main import cli

ACME_HUB = Path(__file__).resolve().parent / "acme-hub"

CLIENT_NS = "https://acme.example/ontology/client#"
FINANCE_NS = "https://finance.example/ref#"


def _write_affinity(analysis_dir: Path, system: str, tables: list[tuple[str, str]]) -> None:
    """Write a ``schema_version: 2`` affinity report. ``tables`` = [(table, domain), ...]."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "system": system,
        "schema_version": 2,
        "tables": [{"table": t, "domain": d} for t, d in tables],
    }
    with open(analysis_dir / f"{system}-affinity.yaml", "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False)


def _registry(
    domain: str,
    tables: list[tuple[str, str]],
    *,
    claims: list[Claim] | None = None,
) -> ClaimRegistry:
    """Build a valid, complete, fresh registry covering ``tables`` = [(system, table), ...].

    The freshness digest matches the covered table set so the registry never lands
    in the gate's ``incomplete`` / ``stale`` / ``unverifiable`` buckets, keeping the
    governance assertions isolated.
    """
    systems: dict[str, list[CoverageTable]] = {}
    for system, table in tables:
        systems.setdefault(system, []).append(CoverageTable(table=table))
    coverage = [CoverageSystem(system=s, tables=t) for s, t in systems.items()]
    return ClaimRegistry(
        domain=domain,
        generated_at="2026-06-15T00:00:00Z",
        algorithm_version=ALIGNMENT_ALGORITHM_VERSION,
        freshness=Freshness(affinity_sha256=compute_affinity_hash(tables)),
        coverage=coverage,
        claims=claims or [],
    )


def _broad_class_claim(cid: str, class_uri: str) -> Claim:
    """An approved broad (materializing) class claim — triggers the MDM-anchor gate."""
    return Claim(
        id=cid,
        type="class",
        status="approved",
        disposition="claim",
        class_uri=class_uri,
        evidence_sources=[EvidenceSource(type="source_sample", system="adminpulse")],
    )


def _anchor_claim(cid: str, *, status: str, class_uri: str | None = None) -> Claim:
    """A reference-data MDM anchor claim (``mdm_anchor=True``)."""
    return Claim(
        id=cid,
        type="reference_data",
        status=status,
        disposition="claim",
        class_uri=class_uri,
        mdm_anchor=True,
        reference_data=ReferenceData(
            authority_system="adminpulse",
            code_system="ISO-3166",
            key="code",
            scd_type=2,
        ),
        evidence_sources=(
            [EvidenceSource(type="source_sample", system="adminpulse")]
            if status == "approved"
            else []
        ),
    )


def test_acme_hub_has_no_permanent_claims_dir():
    """Guard the scenario invariant: the shared acme-hub owns no claims registry."""
    assert ACME_HUB.is_dir(), "acme-hub fixture must exist"
    assert not (ACME_HUB / "model" / "claims").exists(), (
        "acme-hub must NOT carry a permanent model/claims/ dir — it would trip the "
        "projector authority gate in the shared projection scenario tests"
    )


def test_mdm_anchor_gate_blocks_then_passes(tmp_path):
    """A proposed anchor blocks a broad claim; deciding the anchor clears the block."""
    analysis = tmp_path / "_analysis"
    claims = tmp_path / "claims"
    _write_affinity(analysis, "adminpulse", [("tblClient", "client")])

    pending = _registry(
        "client",
        [("adminpulse", "tblClient")],
        claims=[
            _broad_class_claim("client-CorporateClient", CLIENT_NS + "CorporateClient"),
            _anchor_claim("client-Country", status="proposed"),
        ],
    )
    write_registry(pending, registry_path(claims, "client"))

    report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
    assert report.anchor_pending.get("client") == ["client-Country"]
    assert report.is_blocking

    # Decide the anchor (approved + class_uri + evidence so it stays structurally valid).
    approved = _registry(
        "client",
        [("adminpulse", "tblClient")],
        claims=[
            _broad_class_claim("client-CorporateClient", CLIENT_NS + "CorporateClient"),
            _anchor_claim(
                "client-Country", status="approved", class_uri=CLIENT_NS + "Country"
            ),
        ],
    )
    write_registry(approved, registry_path(claims, "client"))

    report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
    assert "client" not in report.anchor_pending
    assert not report.anchor_pending


def test_broad_claims_without_anchor_warn(tmp_path):
    """A domain with broad claims but zero declared anchors warns (non-blocking)."""
    analysis = tmp_path / "_analysis"
    claims = tmp_path / "claims"
    _write_affinity(analysis, "adminpulse", [("tblClient", "client")])
    write_registry(
        _registry(
            "client",
            [("adminpulse", "tblClient")],
            claims=[
                _broad_class_claim(
                    "client-CorporateClient", CLIENT_NS + "CorporateClient"
                )
            ],
        ),
        registry_path(claims, "client"),
    )

    report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
    assert report.anchor_missing == ["client"]
    assert not report.anchor_pending
    # anchor_missing is a warning, not a block.
    assert not report.is_blocking
    assert report.has_warnings


def test_ownership_override_requires_owner_and_rationale(tmp_path):
    """A foreign-owned approved URI blocks until a well-formed override is attached."""
    analysis = tmp_path / "_analysis"
    claims = tmp_path / "claims"
    _write_affinity(analysis, "adminpulse", [("tblClient", "client")])
    data_domains = {
        "client": {"uris": [CLIENT_NS]},
        "finance": {"uris": [FINANCE_NS]},
    }

    # client approves a class whose URI namespace is owned by finance.
    foreign = _broad_class_claim("client-FxRate", FINANCE_NS + "FxRate")
    write_registry(
        _registry("client", [("adminpulse", "tblClient")], claims=[foreign]),
        registry_path(claims, "client"),
    )

    report = check_claims_coverage(
        claims_dir=claims, analysis_dir=analysis, data_domains=data_domains
    )
    assert len(report.ownership_conflicts) == 1
    conflict = report.ownership_conflicts[0]
    assert conflict.domain == "client"
    assert conflict.claim_id == "client-FxRate"
    assert conflict.uri == FINANCE_NS + "FxRate"
    assert conflict.owners == ["finance"]
    assert report.is_blocking

    # A documented override (owner + rationale) turns it into a reviewed decision.
    overridden = _broad_class_claim("client-FxRate", FINANCE_NS + "FxRate")
    overridden.ownership_override = OwnershipOverride(
        owner="data-stewardship", rationale="conformed FX dimension shared with finance"
    )
    write_registry(
        _registry("client", [("adminpulse", "tblClient")], claims=[overridden]),
        registry_path(claims, "client"),
    )

    report = check_claims_coverage(
        claims_dir=claims, analysis_dir=analysis, data_domains=data_domains
    )
    assert report.ownership_conflicts == []
    assert not report.is_blocking


def test_ownership_gate_disabled_via_flag(tmp_path):
    """``check_ownership=False`` suppresses the ownership-boundary scan."""
    analysis = tmp_path / "_analysis"
    claims = tmp_path / "claims"
    _write_affinity(analysis, "adminpulse", [("tblClient", "client")])
    data_domains = {"client": {"uris": [CLIENT_NS]}, "finance": {"uris": [FINANCE_NS]}}
    write_registry(
        _registry(
            "client",
            [("adminpulse", "tblClient")],
            claims=[_broad_class_claim("client-FxRate", FINANCE_NS + "FxRate")],
        ),
        registry_path(claims, "client"),
    )

    report = check_claims_coverage(
        claims_dir=claims,
        analysis_dir=analysis,
        data_domains=data_domains,
        check_ownership=False,
    )
    assert report.ownership_conflicts == []


def test_passthrough_review_flags_repeated_columns(tmp_path):
    """A multi-system passthrough column warns until it is reviewed."""
    analysis = tmp_path / "_analysis"
    claims = tmp_path / "claims"
    _write_affinity(analysis, "adminpulse", [("tblClient", "client")])

    passthrough = Claim(
        id="client-legacyCode",
        type="property",
        status="proposed",
        disposition="passthrough",
        evidence_sources=[
            EvidenceSource(type="source_column", system="adminpulse", column="LegacyCode"),
            EvidenceSource(type="source_column", system="teamleader", column="legacy_code"),
        ],
    )
    write_registry(
        _registry("client", [("adminpulse", "tblClient")], claims=[passthrough]),
        registry_path(claims, "client"),
    )

    report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
    assert report.passthrough_review.get("client") == ["client-legacyCode"]
    # passthrough-review is a warning — it must not block on its own.
    assert not report.is_blocking
    assert report.has_warnings

    # Marking it reviewed clears the warning.
    passthrough.passthrough_reviewed = True
    write_registry(
        _registry("client", [("adminpulse", "tblClient")], claims=[passthrough]),
        registry_path(claims, "client"),
    )
    report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
    assert "client" not in report.passthrough_review


def test_deviation_log_fails_on_undocumented_native_class(tmp_path):
    """An approved client-native (gap) claim must carry a deviation record."""
    analysis = tmp_path / "_analysis"
    claims = tmp_path / "claims"
    _write_affinity(analysis, "adminpulse", [("tblClient", "client")])

    native = Claim(
        id="client-LoyaltyTier",
        type="class",
        status="approved",
        disposition="gap",
        class_uri=CLIENT_NS + "LoyaltyTier",
        evidence_sources=[EvidenceSource(type="source_sample", system="adminpulse")],
    )
    write_registry(
        _registry("client", [("adminpulse", "tblClient")], claims=[native]),
        registry_path(claims, "client"),
    )

    report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
    assert report.deviation_missing.get("client") == ["client-LoyaltyTier"]
    assert report.is_blocking

    # Recording a deviation (owner + reason) clears the block.
    native.deviation = Deviation(
        owner="domain-architect",
        reason="No upstream accelerator concept; client-native loyalty tier.",
        gap_request="GAP-128",
    )
    write_registry(
        _registry("client", [("adminpulse", "tblClient")], claims=[native]),
        registry_path(claims, "client"),
    )
    report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
    assert "client" not in report.deviation_missing
    assert not report.deviation_missing


def test_check_claims_cli_round_trip(tmp_path):
    """The skill-gated ``check-claims`` CLI blocks on a pending anchor, then passes.

    Ownership is driven only by the backend tests: ``check-claims`` auto-detects
    ``data-domains.yaml`` from reference models, which this synthetic hub lacks, so
    only the registry-resident gates (MDM-anchor here) drive the CLI exit code.
    ``--no-source-coverage`` / ``--no-extension-sync`` isolate those gates.
    """
    analysis = tmp_path / "_analysis"
    claims = tmp_path / "claims"
    _write_affinity(analysis, "adminpulse", [("tblClient", "client")])
    runner = CliRunner()

    # Pending anchor → blocking → exit 1.
    write_registry(
        _registry(
            "client",
            [("adminpulse", "tblClient")],
            claims=[
                _broad_class_claim(
                    "client-CorporateClient", CLIENT_NS + "CorporateClient"
                ),
                _anchor_claim("client-Country", status="proposed"),
            ],
        ),
        registry_path(claims, "client"),
    )
    blocked = runner.invoke(
        cli,
        [
            "check-claims",
            "--analysis-dir",
            str(analysis),
            "--claims-dir",
            str(claims),
            "--no-source-coverage",
            "--no-extension-sync",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )
    assert blocked.exit_code == 1, blocked.output

    # --warn-only never blocks, even with the anchor still pending.
    warn = runner.invoke(
        cli,
        [
            "check-claims",
            "--analysis-dir",
            str(analysis),
            "--claims-dir",
            str(claims),
            "--no-source-coverage",
            "--no-extension-sync",
            "--warn-only",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )
    assert warn.exit_code == 0, warn.output

    # Decide the anchor → clean → exit 0.
    write_registry(
        _registry(
            "client",
            [("adminpulse", "tblClient")],
            claims=[
                _broad_class_claim(
                    "client-CorporateClient", CLIENT_NS + "CorporateClient"
                ),
                _anchor_claim(
                    "client-Country", status="approved", class_uri=CLIENT_NS + "Country"
                ),
            ],
        ),
        registry_path(claims, "client"),
    )
    clean = runner.invoke(
        cli,
        [
            "check-claims",
            "--analysis-dir",
            str(analysis),
            "--claims-dir",
            str(claims),
            "--no-source-coverage",
            "--no-extension-sync",
        ],
        env={"KAIROS_SKILL_CONTEXT": "1"},
    )
    assert clean.exit_code == 0, clean.output
