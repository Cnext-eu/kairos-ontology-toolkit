# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the one-way alignment → Claim Registry migration."""

from __future__ import annotations

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.core.claim_registry import (
    ClaimRegistry,
    dump_registry,
    load_registry,
    validate_registry,
    validation_errors,
)
from kairos_ontology.cli.main import cli
from kairos_ontology.core.migrate_claims import (
    alignment_to_registry,
    build_uri_index,
    find_legacy_alignment_files,
    legacy_alignment_error,
    load_inventory_uri_index,
    migrate_alignment_file,
)

SAMPLE_ALIGNMENT: dict = {
    "schema_version": 2,
    "algorithm_version": 2,
    "domain": "party",
    "domain_uris": ["https://ex.org/ont/party#"],
    "generated_at": "2026-06-15T10:00:00Z",
    "model_used": "gpt-x",
    "source_sha256": "AFFINITYHASH",
    "alignment_params_sha256": "PARAMHASH",
    "tables": [
        {
            "system": "crm",
            "table": "account",
            "ref_class": "TradeParty",
            "ref_class_confidence": 0.9,
            "columns": [
                {"column": "name", "data_type": "str", "ref_class": "TradeParty",
                 "ref_property": "legalName", "alignment": "exact", "confidence": 0.95,
                 "rationale": ""},
                {"column": "noise_id", "data_type": "str", "ref_class": "TradeParty",
                 "ref_property": "", "alignment": "custom", "confidence": 0.1,
                 "rationale": ""},
            ],
            "custom_columns": [
                {"column": "credit_limit", "data_type": "num", "disposition": "model",
                 "rationale": "finance concept"},
                {"column": "scratch", "data_type": "str", "disposition": "skip"},
                {"column": "legacy_note", "data_type": "str", "disposition": None},
            ],
        },
        {
            "system": "erp",
            "table": "customer",
            "ref_class": "TradeParty",
            "ref_class_confidence": 0.8,
            "ref_class_status": "fallback",
            "columns": [
                {"column": "cust_name", "data_type": "str", "ref_class": "TradeParty",
                 "ref_property": "legalName", "alignment": "semantic", "confidence": 0.8,
                 "rationale": ""},
            ],
            "custom_columns": [],
        },
    ],
}


class TestConversion:
    def test_produces_valid_registry(self):
        reg = alignment_to_registry(SAMPLE_ALIGNMENT)
        assert isinstance(reg, ClaimRegistry)
        assert validation_errors(validate_registry(reg)) == []

    def test_domain_and_freshness(self):
        reg = alignment_to_registry(SAMPLE_ALIGNMENT)
        assert reg.domain == "party"
        assert reg.algorithm_version == 2
        assert reg.generated_at == "2026-06-15T10:00:00Z"
        assert reg.freshness.affinity_sha256 == "AFFINITYHASH"
        assert reg.freshness.alignment_params_sha256 == "PARAMHASH"

    def test_class_claim_deduped_with_aggregated_evidence(self):
        reg = alignment_to_registry(SAMPLE_ALIGNMENT)
        cls = [c for c in reg.claims if c.type == "class"]
        assert len(cls) == 1  # TradeParty appears in two tables → one claim
        ev_tables = {(e.system, e.table) for e in cls[0].evidence_sources}
        assert ev_tables == {("crm", "account"), ("erp", "customer")}
        assert cls[0].status == "proposed"
        assert cls[0].origin == "imported"
        assert cls[0].class_uri is None  # unresolved until approval

    def test_property_claim_deduped(self):
        reg = alignment_to_registry(SAMPLE_ALIGNMENT)
        props = [c for c in reg.claims if c.type == "property"
                 and c.disposition == "claim"]
        # legalName appears in two tables → single property claim
        assert len(props) == 1
        assert len(props[0].evidence_sources) == 2

    def test_unmatched_column_makes_no_property_claim(self):
        reg = alignment_to_registry(SAMPLE_ALIGNMENT)
        # noise_id has empty ref_property → no claim referencing it
        assert all("noise" not in c.id for c in reg.claims)

    def test_custom_column_triage_mapping(self):
        reg = alignment_to_registry(SAMPLE_ALIGNMENT)
        by_disp = {}
        for c in reg.claims:
            if c.origin == "authored":
                by_disp.setdefault(c.disposition, []).append(c)
        # model → specialize, skip → skip, untriaged → passthrough
        assert any("credit-limit" in c.id for c in by_disp.get("specialize", []))
        assert any("scratch" in c.id for c in by_disp.get("skip", []))
        passthrough = by_disp.get("passthrough", [])
        assert any("legacy-note" in c.id for c in passthrough)
        # untriaged flagged in rationale
        legacy = next(c for c in passthrough if "legacy-note" in c.id)
        assert "Untriaged" in (legacy.rationale or "")

    def test_coverage_snapshot(self):
        reg = alignment_to_registry(SAMPLE_ALIGNMENT)
        systems = {s.system: s for s in reg.coverage}
        assert set(systems) == {"crm", "erp"}
        acct = systems["crm"].tables[0]
        assert acct.table == "account"
        assert acct.total_columns == 5  # 2 columns + 3 custom
        assert acct.mapped_columns == 2
        assert acct.custom_columns == 3
        assert acct.ref_class == "TradeParty"
        # ref_class_status fallback preserved
        assert systems["erp"].tables[0].anchor_state == "fallback"


class TestDeterminism:
    def test_byte_stable_output(self):
        a = dump_registry(alignment_to_registry(SAMPLE_ALIGNMENT))
        b = dump_registry(alignment_to_registry(SAMPLE_ALIGNMENT))
        assert a == b

    def test_round_trip_through_yaml(self):
        reg = alignment_to_registry(SAMPLE_ALIGNMENT)
        text = dump_registry(reg)
        reloaded = ClaimRegistry.from_dict(yaml.safe_load(text))
        assert reloaded.to_dict() == reg.to_dict()

    def test_claims_sorted_by_id(self):
        reg = alignment_to_registry(SAMPLE_ALIGNMENT)
        ids = [c.id for c in reg.claims]
        assert ids == sorted(ids)


class TestFileApi:
    def test_migrate_alignment_file(self, tmp_path):
        path = tmp_path / "party-alignment.yaml"
        path.write_text(yaml.safe_dump(SAMPLE_ALIGNMENT), encoding="utf-8")
        reg = migrate_alignment_file(path)
        assert reg.domain == "party"

    def test_migrate_rejects_non_mapping(self, tmp_path):
        path = tmp_path / "bad-alignment.yaml"
        path.write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ValueError):
            migrate_alignment_file(path)


class TestLegacyDetection:
    def test_find_legacy_files(self, tmp_path):
        (tmp_path / "party-alignment.yaml").write_text("x: 1", encoding="utf-8")
        (tmp_path / "invoice-alignment.yaml").write_text("x: 1", encoding="utf-8")
        (tmp_path / "party-claims.yaml").write_text("x: 1", encoding="utf-8")
        found = [p.name for p in find_legacy_alignment_files(tmp_path)]
        assert found == ["invoice-alignment.yaml", "party-alignment.yaml"]

    def test_legacy_error_message(self, tmp_path):
        msg = legacy_alignment_error(tmp_path / "party-alignment.yaml")
        assert "retired" in msg
        assert "migrate-claims" in msg
        assert "party-claims.yaml" in msg

    def test_find_in_missing_dir(self, tmp_path):
        assert find_legacy_alignment_files(tmp_path / "nope") == []


def test_empty_alignment_yields_empty_registry():
    reg = alignment_to_registry({"domain": "d"})
    assert reg.domain == "d"
    assert reg.claims == []
    assert validation_errors(validate_registry(reg)) == []


def test_golden_snapshot():
    """Lock the exact serialized shape so accidental format drift is caught."""
    reg = alignment_to_registry(SAMPLE_ALIGNMENT)
    text = dump_registry(reg)
    # spot-check stable, human-meaningful anchors rather than the whole blob
    assert "schema_version: 1" in text
    assert "domain: party" in text
    assert "affinity_sha256: AFFINITYHASH" in text
    assert "id: party-tradeparty" in text
    assert "id: party-custom-crm-account-credit-limit" in text
    # everything proposed, nothing pre-approved
    assert "status: approved" not in text


class TestMigrateCli:
    def _setup(self, root):
        analysis = root / "_analysis"
        analysis.mkdir(parents=True, exist_ok=True)
        (analysis / "party-alignment.yaml").write_text(
            yaml.safe_dump(SAMPLE_ALIGNMENT), encoding="utf-8"
        )
        return analysis

    def test_migrate_writes_claims(self, tmp_path):
        analysis = self._setup(tmp_path)
        out = tmp_path / "claims"
        result = CliRunner().invoke(
            cli, ["migrate-claims", "--analysis-dir", str(analysis),
                  "--output", str(out)]
        )
        assert result.exit_code == 0, result.output
        target = out / "party-claims.yaml"
        assert target.exists()
        reg = load_registry(target)
        assert reg.domain == "party"
        assert validation_errors(validate_registry(reg)) == []

    def test_existing_file_not_overwritten_without_force(self, tmp_path):
        analysis = self._setup(tmp_path)
        out = tmp_path / "claims"
        out.mkdir()
        (out / "party-claims.yaml").write_text("schema_version: 1\n", encoding="utf-8")
        result = CliRunner().invoke(
            cli, ["migrate-claims", "--analysis-dir", str(analysis),
                  "--output", str(out)]
        )
        assert result.exit_code == 1
        assert "use --force" in result.output

    def test_force_overwrites(self, tmp_path):
        analysis = self._setup(tmp_path)
        out = tmp_path / "claims"
        out.mkdir()
        (out / "party-claims.yaml").write_text("schema_version: 1\n", encoding="utf-8")
        result = CliRunner().invoke(
            cli, ["migrate-claims", "--analysis-dir", str(analysis),
                  "--output", str(out), "--force"]
        )
        assert result.exit_code == 0, result.output
        assert load_registry(out / "party-claims.yaml").domain == "party"

    def test_domain_filter_no_match(self, tmp_path):
        analysis = self._setup(tmp_path)
        result = CliRunner().invoke(
            cli, ["migrate-claims", "--analysis-dir", str(analysis),
                  "--output", str(tmp_path / "claims"), "--domain", "nope"]
        )
        assert result.exit_code == 1
        assert "No matching" in result.output


# --------------------------------------------------------------------------- #
# URI back-fill from inventory (issue #190 item 4)
# --------------------------------------------------------------------------- #

_INVENTORY_CLASSES = [
    {
        "uri": "https://ex.org/ont/party#TradeParty",
        "name": "TradeParty",
        "properties": [{"name": "legalName"}, {"name": "taxId"}],
    },
    # Ambiguous name: same class name in two modules → must be dropped.
    {"uri": "https://ex.org/ont/imo/party#MaritimeParty", "name": "MaritimeParty",
     "properties": [{"name": "imoNumber"}]},
    {"uri": "https://ex.org/ont/mmt/party#MaritimeParty", "name": "MaritimeParty",
     "properties": [{"name": "imoNumber"}]},
]


class TestUriIndex:
    def test_build_index_resolves_unambiguous(self):
        class_uri, prop_uri = build_uri_index(_INVENTORY_CLASSES)
        assert class_uri["TradeParty"] == "https://ex.org/ont/party#TradeParty"
        assert prop_uri[("TradeParty", "legalName")] == "https://ex.org/ont/party#legalName"

    def test_ambiguous_name_dropped(self):
        class_uri, _ = build_uri_index(_INVENTORY_CLASSES)
        assert "MaritimeParty" not in class_uri

    def test_load_inventory_uri_index_from_dir(self, tmp_path):
        inv_dir = tmp_path / "referencemodels-unpacked"
        inv_dir.mkdir()
        (inv_dir / "party-inventory.yaml").write_text(
            yaml.safe_dump({"classes": _INVENTORY_CLASSES[:1]}), encoding="utf-8"
        )
        class_uri, prop_uri = load_inventory_uri_index(inv_dir)
        assert class_uri["TradeParty"] == "https://ex.org/ont/party#TradeParty"

    def test_missing_inventory_dir_is_empty(self, tmp_path):
        assert load_inventory_uri_index(tmp_path / "nope") == ({}, {})


class TestBackfillIntoClaims:
    def test_class_and_property_uris_populated(self):
        index = build_uri_index(_INVENTORY_CLASSES)
        reg = alignment_to_registry(SAMPLE_ALIGNMENT, uri_index=index)
        cls = next(c for c in reg.claims if c.id == "party-tradeparty")
        assert cls.class_uri == "https://ex.org/ont/party#TradeParty"
        prop = next(c for c in reg.claims if c.id == "party-tradeparty-legalname")
        assert prop.property_uri == "https://ex.org/ont/party#legalName"

    def test_backfilled_class_claim_is_approvable(self):
        index = build_uri_index(_INVENTORY_CLASSES)
        reg = alignment_to_registry(SAMPLE_ALIGNMENT, uri_index=index)
        for claim in reg.claims:
            if claim.disposition == "claim":
                claim.status = "approved"
        assert validation_errors(validate_registry(reg)) == []

    def test_without_index_uris_stay_null(self):
        reg = alignment_to_registry(SAMPLE_ALIGNMENT)
        cls = next(c for c in reg.claims if c.id == "party-tradeparty")
        assert cls.class_uri is None

    def test_migrate_alignment_file_with_inventory_dir(self, tmp_path):
        align = tmp_path / "party-alignment.yaml"
        align.write_text(yaml.safe_dump(SAMPLE_ALIGNMENT), encoding="utf-8")
        inv_dir = tmp_path / "referencemodels-unpacked"
        inv_dir.mkdir()
        (inv_dir / "party-inventory.yaml").write_text(
            yaml.safe_dump({"classes": _INVENTORY_CLASSES[:1]}), encoding="utf-8"
        )
        reg = migrate_alignment_file(align, inventory_dir=inv_dir)
        cls = next(c for c in reg.claims if c.id == "party-tradeparty")
        assert cls.class_uri == "https://ex.org/ont/party#TradeParty"
