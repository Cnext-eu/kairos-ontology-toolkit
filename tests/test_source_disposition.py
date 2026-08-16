# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Source-table disposition ledger (DD-164)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kairos_ontology.core.source_disposition import (
    DEFAULT_ROW_THRESHOLD,
    DISPOSITIONS,
    audit_source_dispositions,
    load_bound_relations,
    load_source_tables,
    record_disposition,
)

_VOCAB_HEADER = """\
@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sys: <https://example.com/src/{system}#> .
"""


def _write_source_table(hub: Path, system: str, table: str, row_count: int | None = 1000) -> None:
    directory = hub / "integration" / "sources" / system
    directory.mkdir(parents=True, exist_ok=True)
    body = _VOCAB_HEADER.format(system=system)
    body += f"\nsys:{table.title().replace('_', '')} a kairos-bronze:SourceTable ;\n"
    body += f'    rdfs:label "{table}" ;\n'
    if row_count is not None:
        body += f"    kairos-bronze:rowCount {row_count} ;\n"
    body += f'    kairos-bronze:tableName "{table}" .\n'
    (directory / f"{table}.ttl").write_text(body, encoding="utf-8")


def _write_binding(hub: Path, system: str, table: str) -> None:
    directory = hub / "integration" / "bindings"
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "apiVersion": "kairos.eu/v5",
        "kind": "EntityBinding",
        "metadata": {"name": f"{system}-{table}", "domain": "party"},
        "source": {"relation": f"{system}.{table}"},
        "target": {"class": "https://example.com/ont/party#Company"},
    }
    (directory / f"{system}-{table}.binding.yaml").write_text(
        yaml.safe_dump(payload), encoding="utf-8"
    )


def test_load_source_tables_reads_table_name_and_row_count(tmp_path: Path) -> None:
    _write_source_table(tmp_path, "qargo", "companies", row_count=2293)
    assert load_source_tables(tmp_path / "integration" / "sources") == {
        ("qargo", "companies"): 2293
    }


def test_missing_row_count_is_unknown_not_zero(tmp_path: Path) -> None:
    """A table with no recorded count still warrants a decision."""
    _write_source_table(tmp_path, "qargo", "goods_scans", row_count=None)
    assert load_source_tables(tmp_path / "integration" / "sources") == {
        ("qargo", "goods_scans"): -1
    }
    report = audit_source_dispositions(hub_root=tmp_path)
    assert report.is_blocking


def test_toolkit_managed_directories_are_not_source_systems(tmp_path: Path) -> None:
    _write_source_table(tmp_path, "qargo", "companies")
    analysis = tmp_path / "integration" / "sources" / "_analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    (analysis / "noise.ttl").write_text("not a vocabulary", encoding="utf-8")
    assert set(load_source_tables(tmp_path / "integration" / "sources")) == {("qargo", "companies")}


def test_load_bound_relations_reads_source_relation(tmp_path: Path) -> None:
    _write_binding(tmp_path, "qargo", "companies")
    assert load_bound_relations(tmp_path / "integration" / "bindings") == {("qargo", "companies")}


def test_bound_table_needs_no_disposition(tmp_path: Path) -> None:
    _write_source_table(tmp_path, "qargo", "companies")
    _write_binding(tmp_path, "qargo", "companies")

    report = audit_source_dispositions(hub_root=tmp_path)

    assert report.is_blocking is False
    assert report.tables_bound == 1
    assert report.coverage() == 1.0


def test_unbound_significant_table_blocks(tmp_path: Path) -> None:
    _write_source_table(tmp_path, "qargo", "stops", row_count=72633)

    report = audit_source_dispositions(hub_root=tmp_path)

    assert report.is_blocking
    assert report.errors[0].code == "disposition.undecided-source-table"
    assert "72,633 rows" in report.errors[0].message
    # The remediation must name the register-concept path, not just "skip it".
    assert "register-concept" in report.errors[0].remediation


def test_small_unbound_table_warns_but_does_not_block(tmp_path: Path) -> None:
    _write_source_table(tmp_path, "qargo", "tiny", row_count=DEFAULT_ROW_THRESHOLD - 1)

    report = audit_source_dispositions(hub_root=tmp_path)

    assert report.is_blocking is False
    assert len(report.warnings) == 1


@pytest.mark.parametrize("disposition", sorted(DISPOSITIONS))
def test_every_disposition_value_clears_the_gate(tmp_path: Path, disposition: str) -> None:
    _write_source_table(tmp_path, "qargo", "comments", row_count=3149)
    record_disposition(
        hub_root=tmp_path,
        system="qargo",
        table="comments",
        disposition=disposition,
        rationale="Generic notes table with no canonical meaning.",
    )
    report = audit_source_dispositions(hub_root=tmp_path)
    assert report.is_blocking is False
    assert report.tables_disposed == 1


def test_disposition_requiring_a_reason_is_rejected_without_one(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires a rationale"):
        record_disposition(
            hub_root=tmp_path,
            system="qargo",
            table="comments",
            disposition="not-business-data",
        )


def test_unknown_disposition_value_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown disposition"):
        record_disposition(hub_root=tmp_path, system="qargo", table="x", disposition="ignore-it")


def test_hand_edited_unknown_disposition_is_flagged_not_trusted(tmp_path: Path) -> None:
    """The ledger is a file; a bad value written by hand must still be caught."""
    _write_source_table(tmp_path, "qargo", "comments", row_count=3149)
    ledger = tmp_path / "integration" / "sources" / "_analysis" / "table-dispositions.yaml"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        yaml.safe_dump(
            {"tables": [{"system": "qargo", "table": "comments", "disposition": "meh"}]}
        ),
        encoding="utf-8",
    )
    report = audit_source_dispositions(hub_root=tmp_path)
    assert [d.code for d in report.errors] == ["disposition.unknown-value"]


def test_recorded_disposition_without_required_rationale_is_flagged(tmp_path: Path) -> None:
    _write_source_table(tmp_path, "qargo", "comments", row_count=3149)
    ledger = tmp_path / "integration" / "sources" / "_analysis" / "table-dispositions.yaml"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        yaml.safe_dump(
            {"tables": [{"system": "qargo", "table": "comments", "disposition": "deferred"}]}
        ),
        encoding="utf-8",
    )
    report = audit_source_dispositions(hub_root=tmp_path)
    assert [d.code for d in report.errors] == ["disposition.missing-rationale"]


def test_record_disposition_replaces_rather_than_duplicates(tmp_path: Path) -> None:
    for disposition in ("deferred", "not-business-data"):
        path = record_disposition(
            hub_root=tmp_path,
            system="qargo",
            table="comments",
            disposition=disposition,
            rationale="Reviewed again.",
        )
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert len(payload["tables"]) == 1
    assert payload["tables"][0]["disposition"] == "not-business-data"


def test_hub_without_sources_is_not_blocking(tmp_path: Path) -> None:
    report = audit_source_dispositions(hub_root=tmp_path)
    assert report.is_blocking is False
    assert report.notices
