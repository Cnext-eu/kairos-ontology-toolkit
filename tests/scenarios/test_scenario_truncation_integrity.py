# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Scenario coverage for F6 (toolkit-optimizations) — truncation integrity.

A wide source table (>80 columns, beyond ``MAX_COLUMNS_PER_PROMPT``) must never
produce a Claim Registry that looks *complete* while columns were silently dropped
before they reached the registry. This exercises the persisted governance path
end-to-end:

* a fully-reconciled alignment (every source column accounted for) writes a
  registry whose per-table column count matches the affinity source count, so
  ``check-claims`` passes;
* a truncated alignment (columns dropped before the registry) is caught by the
  column-omission gate and blocks; and
* a table whose class anchor is deliberately unresolved (DD-124) — zero emitted
  columns *by design* — is classified as a pending anchor decision, never as a
  truncation (DD-128).
"""

from __future__ import annotations

import yaml

from kairos_ontology.core.claim_coverage import check_claims_coverage
from kairos_ontology.core.claim_registry import load_registry, registry_path
from kairos_ontology.core.propose_alignment import (
    ColumnAlignment,
    DomainAlignment,
    TableAlignment,
    write_claims_output,
)

SYSTEM = "adminpulse"
DOMAIN = "logistics"
TABLE = "tblConsignment"
SOURCE_COLUMN_COUNT = 120


def _wide_alignment(mapped: int, custom: int) -> DomainAlignment:
    """A logistics alignment whose wide table maps ``mapped`` + ``custom`` columns."""
    columns = [
        ColumnAlignment(
            column=f"col_{i:03d}", data_type="varchar", ref_class="Consignment",
            ref_property="consignmentReference", alignment="semantic", confidence=0.7,
        )
        for i in range(mapped)
    ]
    custom_columns = [
        {"column": f"extra_{i:03d}", "data_type": "varchar",
         "suggested_property": None, "disposition": None}
        for i in range(custom)
    ]
    ta = TableAlignment(
        system=SYSTEM,
        table=TABLE,
        ref_class="Consignment",
        ref_class_confidence=0.9,
        columns=columns,
        custom_columns=custom_columns,
        source_column_count=SOURCE_COLUMN_COUNT,
        source_column_sha256="deadbeef" * 8,
    )
    return DomainAlignment(
        domain=DOMAIN,
        domain_uris=["https://kairos.cnext.eu/ref/logistics#"],
        generated_at="2026-06-20T00:00:00Z",
        model_used="test",
        tables=[ta],
    )


def _write_affinity(analysis_dir, total_columns: int) -> None:
    analysis_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "system": SYSTEM,
        "schema_version": 2,
        "tables": [
            {"table": TABLE, "domain": DOMAIN, "total_columns": total_columns},
        ],
    }
    with open(analysis_dir / f"{SYSTEM}-affinity.yaml", "w", encoding="utf-8") as f:
        yaml.dump(data, f, sort_keys=False)


class TestTruncationIntegrityScenario:
    def test_full_reconciliation_persists_true_column_count(self, tmp_path):
        # Every one of the 120 source columns reached the registry (80 mapped + 40
        # reconciled passthrough) — the wide table is complete.
        write_claims_output(_wide_alignment(mapped=80, custom=40), tmp_path)
        registry = load_registry(registry_path(tmp_path, DOMAIN))
        tbl = registry.coverage[0].tables[0]
        assert tbl.total_columns == SOURCE_COLUMN_COUNT
        assert tbl.source_column_count == SOURCE_COLUMN_COUNT

    def test_gate_passes_when_complete(self, tmp_path):
        claims = tmp_path / "claims"
        analysis = tmp_path / "_analysis"
        write_claims_output(_wide_alignment(mapped=80, custom=40), claims)
        _write_affinity(analysis, SOURCE_COLUMN_COUNT)
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert not report.column_omissions
        assert DOMAIN not in report.column_omissions

    def test_gate_blocks_on_truncated_registry(self, tmp_path):
        claims = tmp_path / "claims"
        analysis = tmp_path / "_analysis"
        # Only 80 of 120 source columns reached the registry (truncation, no
        # reconciliation) — the affinity report still records the true 120.
        write_claims_output(_wide_alignment(mapped=80, custom=0), claims)
        _write_affinity(analysis, SOURCE_COLUMN_COUNT)
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.is_blocking
        assert DOMAIN in report.column_omissions
        assert "80 of 120" in report.column_omissions[DOMAIN][0]


class TestUnresolvedAnchorIsNotTruncationScenario:
    """DD-128: an unresolved class anchor emits zero columns *by design*
    (DD-124), so the truncation gate must not read it as dropped columns."""

    def _unresolved_alignment(self) -> DomainAlignment:
        ta = TableAlignment(
            system=SYSTEM,
            table=TABLE,
            ref_class="",
            ref_class_confidence=0.0,
            columns=[],
            custom_columns=[],
            ref_class_status="unresolved",
            source_column_count=SOURCE_COLUMN_COUNT,
            source_column_sha256="deadbeef" * 8,
            anchor_candidate_uris=[
                "https://kairos.cnext.eu/ref/logistics#Consignment",
                "https://kairos.cnext.eu/ref/logistics#Shipment",
            ],
        )
        return DomainAlignment(
            domain=DOMAIN,
            domain_uris=["https://kairos.cnext.eu/ref/logistics#"],
            generated_at="2026-06-20T00:00:00Z",
            model_used="test",
            tables=[ta],
        )

    def test_registry_records_the_unresolved_anchor_state(self, tmp_path):
        write_claims_output(self._unresolved_alignment(), tmp_path)
        registry = load_registry(registry_path(tmp_path, DOMAIN))
        tbl = registry.coverage[0].tables[0]
        assert tbl.anchor_state == "unresolved"
        assert tbl.total_columns == 0
        assert tbl.source_column_count == SOURCE_COLUMN_COUNT

    def test_gate_reports_pending_anchor_not_column_omission(self, tmp_path):
        claims = tmp_path / "claims"
        analysis = tmp_path / "_analysis"
        write_claims_output(self._unresolved_alignment(), claims)
        _write_affinity(analysis, SOURCE_COLUMN_COUNT)
        report = check_claims_coverage(claims_dir=claims, analysis_dir=analysis)
        assert report.column_omissions == {}
        assert not report.is_blocking
        assert report.has_warnings
        entry = report.unresolved_anchor_tables[DOMAIN][0]
        assert entry.startswith(f"{SYSTEM}.{TABLE}")
        assert "class anchor unresolved" in entry
