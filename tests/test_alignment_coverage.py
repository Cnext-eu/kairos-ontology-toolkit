# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Tests for the reused affinity/freshness primitives and triage heuristics.

The alignment-coverage *gate* is retired (DD-EL-1) — its replacement is the
``check-claims`` gate, covered by ``tests/test_claim_coverage.py``. What remains
in :mod:`kairos_ontology.alignment_coverage` are the deterministic primitives the
new gate and ``propose-alignment`` reuse, exercised here.
"""

from pathlib import Path

import yaml

from kairos_ontology.alignment_coverage import (
    auto_disposition,
    compute_affinity_hash,
    is_generic_vendor_slot,
    load_affinity_domain_tables,
    recommend_disposition,
)


def _write_affinity(analysis_dir: Path, system: str, tables: list[tuple[str, str]]) -> None:
    """Write a schema_version 2 affinity report. tables = [(table, domain), ...]."""
    analysis_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "system": system,
        "schema_version": 2,
        "tables": [
            {"table": tbl, "domain": dom, "total_columns": 3}
            for tbl, dom in tables
        ],
    }
    with open(analysis_dir / f"{system}-affinity.yaml", "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False)


class TestComputeAffinityHash:

    def test_order_and_duplicate_insensitive(self):
        a = compute_affinity_hash([("sys", "t1"), ("sys", "t2")])
        b = compute_affinity_hash([("sys", "t2"), ("sys", "t1"), ("sys", "t1")])
        assert a == b

    def test_changes_with_new_table(self):
        a = compute_affinity_hash([("sys", "t1")])
        b = compute_affinity_hash([("sys", "t1"), ("sys", "t2")])
        assert a != b


class TestLoadAffinityDomainTables:

    def test_groups_by_domain(self, tmp_path):
        _write_affinity(tmp_path, "adminpulse", [("tblA", "party"), ("tblB", "commercial")])
        _write_affinity(tmp_path, "erp", [("tblC", "party")])
        result = load_affinity_domain_tables(tmp_path)
        assert result["party"] == {("adminpulse", "tblA"), ("erp", "tblC")}
        assert result["commercial"] == {("adminpulse", "tblB")}

    def test_ignores_unclassified_and_v1(self, tmp_path):
        _write_affinity(tmp_path, "adminpulse", [("tblA", "party"), ("tblB", "")])
        # schema_version 1 file ignored
        with open(tmp_path / "old-affinity.yaml", "w", encoding="utf-8") as f:
            yaml.dump({"system": "old", "schema_version": 1, "tables": [
                {"table": "tblX", "domain": "party"}]}, f)
        result = load_affinity_domain_tables(tmp_path)
        assert result == {"party": {("adminpulse", "tblA")}}


class TestDispositionHeuristics:
    def test_generic_vendor_slot_detection(self):
        assert is_generic_vendor_slot("CFSTRING33")
        assert is_generic_vendor_slot("CFENUMERATION54")
        assert is_generic_vendor_slot("CF12")
        assert not is_generic_vendor_slot("credit_limit")
        assert not is_generic_vendor_slot("CFWASTESURCHAMOUNT")

    def test_recommend_disposition(self):
        assert recommend_disposition("CFSTRING33") == "silver-passthrough"
        assert recommend_disposition("created_on") == "skip"
        assert recommend_disposition("tenant_id") == "skip"
        assert recommend_disposition("credit_limit") == ""

    def test_auto_disposition_narrow(self):
        assert auto_disposition("CREATEDON") == "skip"
        assert auto_disposition("tenant_id") == "skip"
        # A generic vendor slot is NOT auto-disposed (stays a conscious decision).
        assert auto_disposition("CFSTRING33") is None
        # A business column is never auto-disposed.
        assert auto_disposition("credit_limit") is None
