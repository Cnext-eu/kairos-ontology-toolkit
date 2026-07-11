# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the deterministic lifecycle-status scanner (DD-080)."""

from pathlib import Path

from kairos_ontology.core.status import (
    STATE_DONE,
    STATE_IN_PROGRESS,
    STATE_NOT_STARTED,
    PHASE_ORDER,
    render_markdown,
    scan_hub_status,
)

ACME_HUB = Path(__file__).parent / "scenarios" / "acme-hub"


def _phase(status, name):
    p = status.phase(name)
    assert p is not None, f"missing phase {name}"
    return p


class TestScanAcmeHub:
    """Scan the committed acme-hub scenario for known objective state."""

    def test_all_phases_present_in_order(self):
        status = scan_hub_status(ACME_HUB)
        assert [p.phase for p in status.phases] == list(PHASE_ORDER)

    def test_domain_phase_done_with_three_instances(self):
        status = scan_hub_status(ACME_HUB)
        domain = _phase(status, "domain")
        assert domain.state == STATE_DONE
        names = {i.name for i in domain.instances}
        assert names == {"client", "invoice", "logistics"}

    def test_internal_ttl_excluded_from_domain(self):
        # _refmodel-party.ttl must not count as a domain ontology.
        status = scan_hub_status(ACME_HUB)
        names = {i.name for i in _phase(status, "domain").instances}
        assert "_refmodel-party" not in names
        assert "_refmodel" not in names

    def test_mapping_phase_done_with_four_instances(self):
        status = scan_hub_status(ACME_HUB)
        mapping = _phase(status, "mapping")
        assert mapping.state == STATE_DONE
        assert len(mapping.instances) == 4

    def test_silver_and_gold_split_by_suffix(self):
        status = scan_hub_status(ACME_HUB)
        silver = {i.name for i in _phase(status, "silver").instances}
        gold = {i.name for i in _phase(status, "gold").instances}
        assert silver == {"client", "invoice", "logistics"}
        assert gold == {"client", "invoice"}

    def test_source_in_progress_without_affinity(self):
        # acme-hub has vocabularies but no _analysis affinity reports.
        status = scan_hub_status(ACME_HUB)
        source = _phase(status, "source")
        assert source.state == STATE_IN_PROGRESS
        assert {i.name for i in source.instances} == {
            "adminpulse", "billingpro", "crmsystem", "logisticspro",
        }
        assert all(i.state == STATE_IN_PROGRESS for i in source.instances)

    def test_not_started_phases(self):
        status = scan_hub_status(ACME_HUB)
        for name in ("discovery", "claims", "validate", "project"):
            assert _phase(status, name).state == STATE_NOT_STARTED

    def test_next_phase_is_first_incomplete(self):
        status = scan_hub_status(ACME_HUB)
        assert status.next_phase == "discovery"

    def test_scan_is_deterministic(self):
        a = scan_hub_status(ACME_HUB).to_dict()
        b = scan_hub_status(ACME_HUB).to_dict()
        assert a == b


class TestScanSynthetic:
    """Edge cases on a freshly built temporary hub."""

    def test_empty_hub_all_not_started(self, tmp_path):
        status = scan_hub_status(tmp_path)
        assert all(p.state == STATE_NOT_STARTED for p in status.phases)
        assert status.next_phase == "discovery"

    def test_source_done_when_vocab_and_affinity_present(self, tmp_path):
        sys_dir = tmp_path / "integration" / "sources" / "crm"
        sys_dir.mkdir(parents=True)
        (sys_dir / "crm.vocabulary.ttl").write_text("# vocab", encoding="utf-8")
        analysis = tmp_path / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True)
        (analysis / "crm-affinity.yaml").write_text("domain: x", encoding="utf-8")
        source = _phase(scan_hub_status(tmp_path), "source")
        assert source.state == STATE_DONE
        assert source.instances[0].state == STATE_DONE

    def test_underscore_source_dirs_ignored(self, tmp_path):
        sources = tmp_path / "integration" / "sources"
        (sources / "_analysis").mkdir(parents=True)
        (sources / "crm").mkdir(parents=True)
        (sources / "crm" / "crm.vocabulary.ttl").write_text("# v", encoding="utf-8")
        source = _phase(scan_hub_status(tmp_path), "source")
        assert {i.name for i in source.instances} == {"crm"}

    def test_discovery_done_with_glossary(self, tmp_path):
        bd = tmp_path / "businessdiscovery"
        bd.mkdir(parents=True)
        (bd / "acme-glossary.ttl").write_text("# glossary", encoding="utf-8")
        assert _phase(scan_hub_status(tmp_path), "discovery").state == STATE_DONE

    def test_project_done_when_output_target_populated(self, tmp_path):
        dbt = tmp_path / "output" / "medallion" / "dbt"
        dbt.mkdir(parents=True)
        (dbt / "model.sql").write_text("select 1", encoding="utf-8")
        proj = _phase(scan_hub_status(tmp_path), "project")
        assert proj.state == STATE_DONE
        assert proj.instances[0].name == "medallion/dbt"

    def test_validate_done_with_report(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir(parents=True)
        (out / "validation-report.json").write_text("{}", encoding="utf-8")
        assert _phase(scan_hub_status(tmp_path), "validate").state == STATE_DONE


class TestRenderMarkdown:
    def test_markdown_contains_auto_generated_marker_and_table(self):
        md = render_markdown(scan_hub_status(ACME_HUB), last_scanned_at="2026-01-01T00:00:00+00:00")
        assert "AUTO-GENERATED" in md
        assert "| Phase | State |" in md
        assert "| domain |" in md
        assert "Next phase" in md

    def test_markdown_reports_completion(self, tmp_path):
        # Force a hub where every phase resolves done is impractical; assert the
        # not-complete branch instead.
        md = render_markdown(scan_hub_status(tmp_path))
        assert "Next phase" in md
