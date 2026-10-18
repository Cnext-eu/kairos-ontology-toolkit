# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""A source table another binding replaced is `superseded` (DD-259, #1136).

A hub that moves a binding from an imported Bronze table to a shipped reference list's
seed leaves the table with real business data and no binding. No other disposition
describes that truthfully, so the hub used to retire the table by hand across nine files,
and the next import of the source brought it back.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.alignment_report import undecided_gap_columns
from kairos_ontology.core.source_disposition import (
    CASCADING_DISPOSITIONS,
    NON_GENERATING_DISPOSITIONS,
    audit_source_dispositions,
    load_binding_names,
    load_dispositions,
    record_disposition,
)

SYSTEM = "reference_data"
TABLE = "transport_mode"
REPLACEMENT = "reference-data-transport-mode-code"


def _source_table(hub: Path, table: str = TABLE) -> None:
    directory = hub / "integration" / "sources" / SYSTEM
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{table}.ttl").write_text(
        "@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .\n"
        "@prefix sys: <https://example.com/src/reference_data#> .\n"
        "sys:TransportMode a kairos-bronze:SourceTable ;\n"
        "    kairos-bronze:rowCount 1000 ;\n"
        f'    kairos-bronze:tableName "{table}" .\n',
        encoding="utf-8",
    )


def _binding(hub: Path, name: str, source: dict) -> Path:
    directory = hub / "integration" / "bindings"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.binding.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "apiVersion": "kairos.eu/v5",
                "kind": "EntityBinding",
                "metadata": {"name": name, "domain": "reference-data"},
                "source": source,
                "target": {"class": "https://example.com/ont/reference-data#TransportModeCode"},
            }
        ),
        encoding="utf-8",
    )
    return path


def _seed_binding(hub: Path) -> Path:
    """The replacement: a contracted model over the generated seed, reading no source."""
    sql = "integration/transforms/dbt/models/intermediate/int_reference__transport_mode_code.sql"
    (hub / sql).parent.mkdir(parents=True, exist_ok=True)
    (hub / sql).write_text("select * from {{ ref('transport_mode_code') }}\n", encoding="utf-8")
    return _binding(
        hub,
        REPLACEMENT,
        {"dbtModel": {"name": "int_reference__transport_mode_code", "sqlPath": sql}},
    )


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    _source_table(tmp_path)
    _seed_binding(tmp_path)
    return tmp_path


def _supersede(hub: Path, **overrides) -> Path:
    arguments = {
        "hub_root": hub,
        "system": SYSTEM,
        "table": TABLE,
        "disposition": "superseded",
        "superseded_by": REPLACEMENT,
        "rationale": "Rec 19 now comes from the shipped list's seed.",
    }
    arguments.update(overrides)
    return record_disposition(**arguments)


class TestRecording:
    def test_a_replaced_table_is_recorded_with_its_replacement(self, hub):
        _supersede(hub)
        entry = load_dispositions(hub)[(SYSTEM, TABLE, "")]
        assert entry["disposition"] == "superseded"
        assert entry["superseded_by"] == REPLACEMENT

    def test_it_decides_the_table(self, hub):
        _supersede(hub)
        report = audit_source_dispositions(hub_root=hub)
        assert report.is_blocking is False
        assert report.tables_disposed == 1

    def test_it_needs_a_replacement(self, hub):
        with pytest.raises(ValueError, match="needs --superseded-by"):
            _supersede(hub, superseded_by="")

    def test_it_needs_a_rationale(self, hub):
        with pytest.raises(ValueError, match="requires a rationale"):
            _supersede(hub, rationale="")

    def test_a_column_cannot_be_superseded(self, hub):
        with pytest.raises(ValueError, match="table-grain decision"):
            _supersede(hub, column="name")

    def test_a_replacement_goes_only_with_superseded(self, hub):
        with pytest.raises(ValueError, match="only with the 'superseded'"):
            _supersede(hub, disposition="not-business-data")

    def test_the_replacement_must_be_a_binding_that_exists(self, hub):
        with pytest.raises(ValueError, match="No EntityBinding is named 'nope'") as raised:
            _supersede(hub, superseded_by="nope")
        assert REPLACEMENT in str(raised.value)
        assert not load_dispositions(hub)

    def test_a_table_a_binding_still_reads_is_not_replaced(self, hub):
        _binding(hub, "old-transport-mode", {"relation": f"{SYSTEM}.{TABLE}"})
        with pytest.raises(ValueError, match="still read by a binding"):
            _supersede(hub)
        assert not load_dispositions(hub)


class TestAudit:
    def test_a_replacement_that_disappears_blocks(self, hub):
        _supersede(hub)
        (hub / "integration" / "bindings" / f"{REPLACEMENT}.binding.yaml").unlink()
        report = audit_source_dispositions(hub_root=hub)
        assert report.is_blocking
        (error,) = report.errors
        assert error.code == "disposition.superseded-by-unknown-binding"
        assert REPLACEMENT in error.message

    def test_a_hand_written_row_without_a_replacement_blocks(self, hub):
        ledger = hub / "integration" / "sources" / "_analysis"
        ledger.mkdir(parents=True)
        (ledger / f"src-{SYSTEM}.table-dispositions.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "tables": [
                        {
                            "system": SYSTEM,
                            "table": TABLE,
                            "disposition": "superseded",
                            "rationale": "replaced",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (error,) = audit_source_dispositions(hub_root=hub).errors
        assert error.code == "disposition.superseded-by-unknown-binding"
        assert "(nothing)" in error.message

    def test_a_superseded_table_bound_again_is_a_conflict(self, hub):
        _supersede(hub)
        _binding(hub, "old-transport-mode", {"relation": f"{SYSTEM}.{TABLE}"})
        (error,) = audit_source_dispositions(hub_root=hub).errors
        assert error.code == "disposition.bound-and-ruled-out"


class TestWhatItMeans:
    def test_it_answers_for_the_columns_and_drafts_no_binding(self):
        assert "superseded" in CASCADING_DISPOSITIONS
        assert "superseded" in NON_GENERATING_DISPOSITIONS

    def test_the_gap_columns_are_decided(self, hub):
        analysis = hub / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True, exist_ok=True)
        (analysis / "dom-reference-data.alignment.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "domain": "reference-data",
                    "tables": [
                        {
                            "system": SYSTEM,
                            "table": TABLE,
                            "ref_class": "TransportModeCode",
                            "source_column_count": 1,
                            "columns": [],
                            "custom_columns": [
                                {
                                    "column": "name",
                                    "data_type": "varchar(8000)",
                                    "suggested_property": None,
                                    "rationale": "no property fits",
                                }
                            ],
                        }
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        assert [c.column for c in undecided_gap_columns(hub)] == ["name"]
        _supersede(hub)
        assert undecided_gap_columns(hub) == []

    def test_binding_names_come_from_metadata(self, hub):
        names = load_binding_names(hub / "integration" / "bindings")
        assert list(names) == [REPLACEMENT]

    def test_no_bindings_directory_has_no_names(self, tmp_path):
        assert load_binding_names(tmp_path / "missing") == {}


class TestCli:
    def _set(self, hub: Path, monkeypatch, *extra: str):
        monkeypatch.chdir(hub)
        (hub / "kairos.yaml").write_text("adapter: fabric-warehouse\n", encoding="utf-8")
        (hub / "model" / "ontologies").mkdir(parents=True, exist_ok=True)
        return CliRunner().invoke(
            cli,
            [
                "source-disposition",
                "set",
                "--system",
                SYSTEM,
                "--table",
                TABLE,
                "--disposition",
                "superseded",
                "--rationale",
                "Rec 19 now comes from the shipped list's seed.",
                *extra,
            ],
        )

    def test_set_records_the_replacement(self, hub, monkeypatch):
        result = self._set(hub, monkeypatch, "--superseded-by", REPLACEMENT)
        assert result.exit_code == 0, result.output
        assert "recorded as 'superseded'" in result.output
        assert load_dispositions(hub)[(SYSTEM, TABLE, "")]["superseded_by"] == REPLACEMENT

    def test_set_without_a_replacement_fails(self, hub, monkeypatch):
        result = self._set(hub, monkeypatch)
        assert result.exit_code != 0
        assert "needs --superseded-by" in result.output
