# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""audit-column-coverage keys tables by (system, table) and reads dbtModel chains (#1065).

Before #1065 the audit keyed every binding by table name alone, so two systems' tables of
the same name shared one bucket, and a ``source.dbtModel`` binding (``relation == ""``)
was attached to a table named ``""`` while every table its chain reads was reported
unbound, with all its columns as orphans.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.column_coverage_audit import run_column_coverage_audit
from kairos_ontology.core.domain_coverage import (
    load_source_affinity_by_table,
    load_source_affinity_tables,
)
from tests.test_bound_columns import _three_layer_hub
from tests.test_column_coverage_audit import BINDING_YAML, VOCAB_TTL

_COLUMN = """
    src:{name} a kb:SourceColumn ; kb:sourceTable src:{table} ;
      kb:columnName "{name}" ; kb:dataType "varchar(50)" ;
      kb:nullable true ; kb:distinctCount 20 ; kb:sampleValues "v-1 | v-2" .
"""


def _vocab(system_label: str, table: str, columns: list[str], ns: str) -> str:
    body = textwrap.dedent(f"""
        @prefix src: <https://example.test/{ns}#> .
        @prefix kb: <https://kairos.cnext.eu/bronze#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        src:sys a kb:SourceSystem ; rdfs:label "{system_label}" .
        src:{table} a kb:SourceTable ; kb:sourceSystem src:sys ;
          kb:tableName "{table}" ; kb:rowCount 50 .
    """)
    for name in columns:
        body += textwrap.dedent(_COLUMN.format(name=name, table=table))
    return body


def _write_vocab(hub: Path, system_dir: str, text: str) -> None:
    directory = hub / "integration" / "sources" / system_dir
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{system_dir}.vocabulary.ttl").write_text(text, encoding="utf-8")


def _audit(hub: Path, *, analysis: bool = False):
    return run_column_coverage_audit(
        sources_dir=hub / "integration" / "sources",
        bindings_dir=hub / "integration" / "bindings",
        analysis_dir=(hub / "integration" / "sources" / "_analysis") if analysis else None,
    )


def _relation_hub(hub: Path) -> Path:
    """app.customers bound by a relation binding; crm.customers not bound at all."""
    _write_vocab(hub, "app", VOCAB_TTL)
    _write_vocab(hub, "crm", _vocab("crm", "customers", ["crm_segment", "crm_score"], "crm"))
    bindings = hub / "integration" / "bindings"
    bindings.mkdir(parents=True, exist_ok=True)
    (bindings / "app-customer.binding.yaml").write_text(BINDING_YAML, encoding="utf-8")
    return hub


class TestSystemKey:
    def test_a_same_named_table_in_another_system_is_not_bound(self, tmp_path: Path) -> None:
        report = _audit(_relation_hub(tmp_path))
        unbound = {(f.system, f.table) for f in report.unbound_tables}
        assert ("crm", "customers") in unbound
        assert ("app", "customers") not in unbound
        # The crm columns are not orphans of the app binding.
        assert not any(f.column.startswith("crm_") for f in report.orphan_columns)
        orphan = next(f for f in report.orphan_columns if f.column == "real_orphan_col")
        assert (orphan.system, orphan.table) == ("app", "customers")

    def test_the_source_directory_is_the_system_not_the_vocabulary_label(
        self, tmp_path: Path
    ) -> None:
        # The vocabulary labels its system "APP"; the directory and the relation say "app".
        _write_vocab(tmp_path, "app", VOCAB_TTL.replace('rdfs:label "app"', 'rdfs:label "APP"'))
        bindings = tmp_path / "integration" / "bindings"
        bindings.mkdir(parents=True)
        (bindings / "app-customer.binding.yaml").write_text(BINDING_YAML, encoding="utf-8")
        report = _audit(tmp_path)
        assert ("app", "customers") not in {(f.system, f.table) for f in report.unbound_tables}
        assert {f.column for f in report.orphan_columns} == {"real_orphan_col"}

    def test_json_carries_the_system(self, tmp_path: Path) -> None:
        payload = json.loads(json.dumps(_audit(_relation_hub(tmp_path)).to_dict()))
        assert payload["schema_version"] == 2
        assert ("crm", "customers") in {
            (item["system"], item["table"]) for item in payload["unbound_tables"]
        }
        assert all("system" in item for item in payload["orphan_columns"])
        assert payload["lineage_unconfirmed"] == []


_SHIPMENT_COLUMNS = ["id", "sailing_date", "mode_code", "status", "remarks", "vessel_note"]


class TestDbtModelChains:
    def _hub(self, tmp_path: Path, *, stage_sql: str | None = None) -> Path:
        _write_vocab(tmp_path, "tms", _vocab("tms", "shipment", _SHIPMENT_COLUMNS, "tms"))
        _three_layer_hub(tmp_path, stage_sql=stage_sql)
        return tmp_path

    def test_a_chain_binds_the_table_it_reads(self, tmp_path: Path) -> None:
        report = _audit(self._hub(tmp_path))
        assert report.unbound_tables == []
        assert "" not in {f.table for f in report.orphan_columns}

    def test_a_star_read_makes_the_rest_unconfirmed_not_orphaned(self, tmp_path: Path) -> None:
        report = _audit(self._hub(tmp_path))
        assert report.orphan_columns == []
        [finding] = report.lineage_unconfirmed
        assert (finding.system, finding.table) == ("tms", "shipment")
        assert finding.models == ("stg_tms__shipment",)
        # id, sailing_date, mode_code and status are named downstream; the rest are unproven.
        assert finding.column_count == 2

    def test_an_explicit_chain_leaves_real_orphans(self, tmp_path: Path) -> None:
        hub = self._hub(
            tmp_path,
            stage_sql=(
                "select id, sailing_date, mode_code, status "
                "from {{ source('tms', 'shipment') }}"
            ),
        )
        report = _audit(hub)
        assert report.lineage_unconfirmed == []
        orphans = {f.column: f for f in report.orphan_columns}
        assert set(orphans) == {"remarks", "vessel_note"}
        assert orphans["remarks"].binding_names == ()
        assert "stg_tms__shipment" in orphans["remarks"].read_by_models

    def test_the_cli_names_chain_readers_and_unconfirmed_tables(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        hub = self._hub(tmp_path)
        monkeypatch.chdir(hub)
        result = CliRunner().invoke(
            cli,
            [
                "audit-column-coverage",
                "--sources", str(hub / "integration" / "sources"),
                "--bindings", str(hub / "integration" / "bindings"),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "tms.shipment (2 column(s), read by: stg_tms__shipment)" in result.output


_AFFINITY = textwrap.dedent("""
    system: {system}
    schema_version: 2
    tables:
      - table: customers
        domain: party
        likely_entity: {entity}
        secondary_domains:
          - domain: {secondary}
""").strip()


class TestAffinityBySystem:
    def _write(self, hub: Path) -> Path:
        analysis = hub / "integration" / "sources" / "_analysis"
        analysis.mkdir(parents=True, exist_ok=True)
        (analysis / "app-affinity.yaml").write_text(
            _AFFINITY.format(system="app", entity="Customer", secondary="commercial"),
            encoding="utf-8",
        )
        (analysis / "crm-affinity.yaml").write_text(
            _AFFINITY.format(system="crm", entity="Lead", secondary="marketing"),
            encoding="utf-8",
        )
        return analysis

    def test_two_systems_keep_their_own_row(self, tmp_path: Path) -> None:
        tables = load_source_affinity_by_table(self._write(tmp_path))
        assert tables[("app", "customers")]["likely_entity"] == "Customer"
        assert tables[("crm", "customers")]["likely_entity"] == "Lead"
        # The name-keyed view still exists for its callers, last file winning.
        assert load_source_affinity_tables(tmp_path / "integration" / "sources" / "_analysis")[
            "customers"
        ]["system"] == "crm"

    def test_cross_domain_reads_the_bound_systems_affinity(self, tmp_path: Path) -> None:
        hub = _relation_hub(tmp_path)
        self._write(hub)
        report = _audit(hub, analysis=True)
        found = {(f.system, f.table, f.candidate_domain) for f in report.cross_domain_columns}
        assert found == {("app", "customers", "commercial")}
