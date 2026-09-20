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
    DISPOSITIONS_RELPATH,
    audit_source_dispositions,
    load_bound_relations,
    load_dispositions,
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


#: `bound` is excluded because it is no longer recordable at table grain (#881): the
#: DD-164 audit reads it from integration/bindings/ before it consults the ledger, so a
#: row claiming it was a statement no binding had to back.
_RECORDABLE_AT_TABLE_GRAIN = sorted(set(DISPOSITIONS) - {"bound"})


@pytest.mark.parametrize("disposition", _RECORDABLE_AT_TABLE_GRAIN)
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


def test_bound_is_not_recordable_at_table_grain(tmp_path: Path) -> None:
    """Authoring the EntityBinding is what states it (#881).

    A ledger row saying `bound` satisfied DD-164 with no binding anywhere — a claim
    nothing had to back — and, until the cascade was restricted, silenced every one of
    the table's columns in the DD-169 gate as a side effect.
    """
    with pytest.raises(ValueError, match="not recorded in the ledger"):
        record_disposition(
            hub_root=tmp_path,
            system="qargo",
            table="comments",
            disposition="bound",
            rationale="an EntityBinding covers it",
        )


def test_bound_is_still_recordable_for_a_single_column(tmp_path: Path) -> None:
    """The guard is about the table-grain claim, not the word."""
    record_disposition(
        hub_root=tmp_path,
        system="qargo",
        table="comments",
        column="note_text",
        disposition="bound",
        rationale="mapped by the binding",
    )

    assert (tmp_path / DISPOSITIONS_RELPATH).is_file()


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


class TestColumnGrainIsNotClobbered:
    """A column-grain write must not delete the table's other columns.

    The replace filter matched on (system, table) only, so each column-grain
    record wiped the previous ones — a run recording 224 column dispositions
    kept about one per table and lost the rest silently. load_dispositions
    already keyed on (system, table, column); the writer did not.
    """

    def test_several_columns_on_one_table_all_persist(self, tmp_path):
        from kairos_ontology.core.source_disposition import (
            load_dispositions,
            record_disposition,
        )

        for column in ("created_at", "updated_at", "row_hash"):
            record_disposition(
                hub_root=tmp_path, system="qargo", table="stops", column=column,
                disposition="not-business-data", rationale="audit column",
            )
        recorded = load_dispositions(tmp_path)
        assert {k[2] for k in recorded} == {"created_at", "updated_at", "row_hash"}

    def test_rewriting_one_column_replaces_only_that_column(self, tmp_path):
        from kairos_ontology.core.source_disposition import (
            load_dispositions,
            record_disposition,
        )

        for column in ("a", "b"):
            record_disposition(
                hub_root=tmp_path, system="s", table="t", column=column,
                disposition="deferred", rationale="first pass",
            )
        record_disposition(
            hub_root=tmp_path, system="s", table="t", column="a",
            disposition="not-business-data", rationale="revised",
        )
        recorded = load_dispositions(tmp_path)
        assert recorded[("s", "t", "a")]["disposition"] == "not-business-data"
        assert recorded[("s", "t", "b")]["disposition"] == "deferred"

    def test_table_grain_and_column_grain_coexist(self, tmp_path):
        """A table-level scope decision and a column note are different grains."""
        from kairos_ontology.core.source_disposition import (
            load_dispositions,
            record_disposition,
        )

        record_disposition(
            hub_root=tmp_path, system="s", table="t",
            disposition="not-business-data", rationale="staging table",
        )
        record_disposition(
            hub_root=tmp_path, system="s", table="t", column="c",
            disposition="deferred", rationale="column note",
        )
        recorded = load_dispositions(tmp_path)
        assert ("s", "t", "") in recorded
        assert ("s", "t", "c") in recorded


# ---------------------------------------------------------------------------
# The drafted property survives into the ledger, structured (issue #883)
# ---------------------------------------------------------------------------


PROPERTY = {
    "name": "vesselClass",
    "range": "xsd:string",
    "on_class": "Vessel",
    "why": "Hull class, absent from the reference model.",
}


class TestProposedPropertyReachesTheLedger:
    """A registered-extension decision commits to authoring a property; say which."""

    def test_the_property_is_recorded_as_structure_not_prose(self, tmp_path):
        record_disposition(
            hub_root=tmp_path,
            system="src",
            table="ships",
            column="VESSELCLASS",
            disposition="registered-extension",
            rationale="real business data with no reference property",
            proposed_property=PROPERTY,
        )

        entry = load_dispositions(tmp_path)[("src", "ships", "VESSELCLASS")]

        assert entry["proposed_property"] == PROPERTY

    def test_absent_when_nothing_was_drafted(self, tmp_path):
        record_disposition(
            hub_root=tmp_path,
            system="src",
            table="ships",
            column="MYSTERY",
            disposition="deferred",
            rationale="opaque legacy code",
        )

        entry = load_dispositions(tmp_path)[("src", "ships", "MYSTERY")]

        assert "proposed_property" not in entry

    def test_a_nameless_draft_is_not_recorded(self, tmp_path):
        record_disposition(
            hub_root=tmp_path,
            system="src",
            table="ships",
            column="MYSTERY",
            disposition="deferred",
            rationale="opaque legacy code",
            proposed_property={"range": "xsd:string"},
        )

        entry = load_dispositions(tmp_path)[("src", "ships", "MYSTERY")]

        assert "proposed_property" not in entry

    def test_only_the_four_known_keys_survive(self, tmp_path):
        record_disposition(
            hub_root=tmp_path,
            system="src",
            table="ships",
            column="VESSELCLASS",
            disposition="registered-extension",
            rationale="real business data",
            proposed_property={**PROPERTY, "confidence": 0.8, "junk": None},
        )

        entry = load_dispositions(tmp_path)[("src", "ships", "VESSELCLASS")]

        assert sorted(entry["proposed_property"]) == ["name", "on_class", "range", "why"]
