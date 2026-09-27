# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Column-level bound state derived from EntityBindings (DD-250, #1062).

A ``source.relation`` binding that names a column decides it for the DD-169 gate; a
``source.dbtModel`` chain that reads its table is evidence the decision sheet carries.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from kairos_ontology.core import bound_columns as module
from kairos_ontology.core.alignment_report import undecided_gap_columns
from kairos_ontology.core.bound_columns import (
    BoundColumns,
    is_gap_column_decided,
    load_bound_columns,
    reads_star,
    sql_identifiers,
)
from kairos_ontology.core.gap_decisions import (
    accept_proposals,
    apply_decision_sheet,
    build_decision_sheet,
    write_decision_sheet,
)
from kairos_ontology.core.source_disposition import load_dispositions, record_disposition

RELATION_BINDING = textwrap.dedent("""
    apiVersion: kairos.eu/v5
    kind: EntityBinding
    metadata:
      name: app-customer
      domain: party
    source:
      relation: app.customers
    target:
      class: party:Customer
    grain:
      columns: [customer_id, region_code]
    identity:
      strategy: source-natural
      sourceKey: [customer_id]
    load:
      mode: incremental
      scd: 2
      incremental:
        mergeIdentity: [customer_id]
        canonicalHashInputs: [customer_id, customer_name]
        cdcOperation:
          column: operation
          insertValues: [I]
          updateValues: [U]
          deleteValues: [D]
        sourceUpdatedAt: source_updated_at
        businessEffectiveAt: source_updated_at
        ingestedAt: source_updated_at
        totalOrder: [source_updated_at]
        lookback: {value: 1, unit: days}
        delete: soft-delete
        lateArrival: accept
        correction: new-version
        replay: idempotent
        backfill: merge
        schemaEvolution: fail
    fields:
      - property: party:customerId
        expression: customer_id
      - property: party:customerName
        expression: upper(Customer_Name)
    technicalFields:
      - name: internal_note
        expression: internal_note
        type: string
        nullable: true
        purpose: relationship
    relationships:
      - property: party:hasParent
        target: party:Customer
        join: [{ local: parent_customer_id, foreign: customer_id }]
        cardinality: many-to-one
        mode: non-temporal
        missingParent: error
        ambiguousParent: error
    quality:
      - kind: not-null
        columns: [check_col]
    """).strip()


def _bindings(hub: Path) -> Path:
    directory = hub / "integration" / "bindings"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _write_relation_binding(hub: Path, text: str = RELATION_BINDING) -> Path:
    path = _bindings(hub) / "app-customer.binding.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _write_model(hub: Path, relpath: str, sql: str) -> Path:
    path = hub / "integration" / "transforms" / "dbt" / "models" / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(sql).strip() + "\n", encoding="utf-8")
    return path


def _write_dbt_binding(hub: Path, name: str, sql_relpath: str) -> None:
    payload = {
        "apiVersion": "kairos.eu/v5",
        "kind": "EntityBinding",
        "metadata": {"name": name, "domain": "consignment"},
        "source": {
            "dbtModel": {
                "name": Path(sql_relpath).stem,
                "sqlPath": f"integration/transforms/dbt/models/{sql_relpath}",
                "contractPath": "integration/transforms/dbt/models/schema.yml",
            }
        },
        "target": {"class": "https://example.com/ont/consignment#Shipment"},
    }
    (_bindings(hub) / f"{name}.binding.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")


def _three_layer_hub(hub: Path, *, stage_sql: str | None = None) -> Path:
    """The #949 shape: merge -> int_ -> stg_ -> source(), with the stage reading ``*``."""
    _write_model(
        hub, "merged/int_merged__shipment.sql",
        "select * from {{ ref('int_tms__shipment') }}",
    )
    _write_model(
        hub, "intermediate/int_tms__shipment.sql",
        """
        select s.id, s.sailing_date as SailingDate, upper(s.mode_code) as mode
        from {{ ref('stg_tms__shipment') }} s
        where s.status = 'eta'
        """,
    )
    _write_model(
        hub, "staging/stg_tms__shipment.sql",
        stage_sql or "select * from {{ source('tms', 'shipment') }}",
    )
    _write_dbt_binding(hub, "shipment", "merged/int_merged__shipment.sql")
    return hub


def _load(hub: Path) -> BoundColumns:
    return load_bound_columns(hub / "integration" / "bindings", hub)


def _write_alignment(hub: Path, domain: str, system: str, table: str, columns: list[str]) -> None:
    analysis = hub / "integration" / "sources" / "_analysis"
    analysis.mkdir(parents=True, exist_ok=True)
    (analysis / f"{domain}-alignment.yaml").write_text(
        yaml.safe_dump(
            {
                "domain": domain,
                "tables": [
                    {
                        "system": system,
                        "table": table,
                        "ref_class": "C",
                        "columns": [],
                        "custom_columns": [
                            {"column": c, "data_type": "varchar", "example_values": ["x"]}
                            for c in columns
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# The SQL scanner
# ---------------------------------------------------------------------------


class TestScanner:
    def test_identifiers_skip_jinja_literals_keywords_and_numbers(self) -> None:
        sql = """
        {{ config(materialized='view') }}
        -- eta is mentioned in a comment only
        select s.id, s.sailing_date as SailingDate, "Quoted Col", [bracketed], 1e5 as n
        from {{ source('tms', 'shipment') }} s
        where s.status = 'eta' and s.kind not in ('order', 'x')
        """
        names = sql_identifiers(sql)
        assert {"id", "sailing_date", "sailingdate", "quoted col", "bracketed", "status", "kind"} <= names
        assert "shipment" not in names  # the source() call, not a column
        assert "eta" not in names  # a string literal
        assert "order" not in names  # a keyword
        assert "e5" not in names  # the tail of a number
        assert "config" not in names  # inside a Jinja block

    @pytest.mark.parametrize(
        ("sql", "star"),
        [
            ("select * from {{ ref('x') }}", True),
            ("select distinct * from t", True),
            ("select s.* from t s", True),
            ("select {{ dbt_utils.star(ref('x')) }} from t", True),
            ("select count(*) from t", False),
            ("-- select *\nselect a from t", False),
            ("select a, b from t", False),
        ],
    )
    def test_reads_star(self, sql: str, star: bool) -> None:
        assert reads_star(sql) is star


# ---------------------------------------------------------------------------
# Relation bindings decide
# ---------------------------------------------------------------------------


class TestRelationBinding:
    def test_every_referenced_column_is_named_by_the_binding(self, tmp_path: Path) -> None:
        _write_relation_binding(tmp_path)
        bound = _load(tmp_path)
        for column in (
            "customer_id", "customer_name", "internal_note", "region_code",
            "parent_customer_id", "check_col", "source_updated_at", "operation",
        ):
            assert bound.decided_by_binding("app", "customers", column) == {
                "app-customer.binding.yaml"
            }, column
        assert bound.decided_by_binding("app", "customers", "Customer_Name")  # case-folded
        assert not bound.decided_by_binding("app", "customers", "real_orphan_col")
        assert not bound.decided_by_binding("other", "customers", "customer_id")

    def test_a_binding_the_compiler_rejects_decides_nothing(self, tmp_path: Path) -> None:
        """Fail toward reporting: a half-authored binding must not retire columns."""
        _write_relation_binding(
            tmp_path,
            "apiVersion: kairos.eu/v5\nkind: EntityBinding\nsource:\n  relation: app.customers\n",
        )
        assert _load(tmp_path).empty

    def test_no_bindings_directory_is_empty(self, tmp_path: Path) -> None:
        assert _load(tmp_path).empty


# ---------------------------------------------------------------------------
# dbtModel chains are evidence
# ---------------------------------------------------------------------------


class TestDbtModelChain:
    def test_a_downstream_model_naming_the_column_is_read_by(self, tmp_path: Path) -> None:
        bound = _load(_three_layer_hub(tmp_path))
        assert bound.read_by_models("tms", "shipment", "sailing_date") == {"int_tms__shipment"}
        assert bound.read_by_models("tms", "shipment", "SAILING_DATE") == {"int_tms__shipment"}
        assert bound.read_by_models("tms", "shipment", "mode_code") == {"int_tms__shipment"}
        # Evidence, never a decision.
        assert not bound.decided_by_binding("tms", "shipment", "sailing_date")

    def test_a_select_star_stage_leaves_unnamed_columns_unconfirmed(self, tmp_path: Path) -> None:
        bound = _load(_three_layer_hub(tmp_path))
        assert bound.unconfirmed_readers("tms", "shipment", "eta") == {"stg_tms__shipment"}
        # A named column is not unconfirmed: the downstream name is the stronger evidence.
        assert bound.unconfirmed_readers("tms", "shipment", "sailing_date") == frozenset()

    def test_an_explicit_stage_select_list_confirms_the_lineage(self, tmp_path: Path) -> None:
        bound = _load(
            _three_layer_hub(
                tmp_path,
                stage_sql="select id, sailing_date, mode_code from {{ source('tms', 'shipment') }}",
            )
        )
        assert bound.read_by_models("tms", "shipment", "sailing_date") == {
            "stg_tms__shipment", "int_tms__shipment"
        }
        assert bound.unconfirmed_readers("tms", "shipment", "eta") == frozenset()
        assert bound.read_by_models("tms", "shipment", "eta") == frozenset()

    def test_a_star_macro_is_unconfirmed(self, tmp_path: Path) -> None:
        _write_model(
            tmp_path, "staging/stg_a.sql",
            "select {{ dbt_utils.star(source('tms', 'shipment')) }} from {{ source('tms', 'shipment') }}",
        )
        _write_dbt_binding(tmp_path, "a", "staging/stg_a.sql")
        assert _load(tmp_path).unconfirmed_readers("tms", "shipment", "anything") == {"stg_a"}

    def test_an_ambiguous_ref_ends_the_branch(self, tmp_path: Path) -> None:
        _write_model(tmp_path, "merged/int_top.sql", "select * from {{ ref('stg_dup') }}")
        _write_model(tmp_path, "staging/stg_dup.sql", "select a from {{ source('tms', 'x') }}")
        _write_model(tmp_path, "legacy/stg_dup.sql", "select b from {{ source('tms', 'y') }}")
        _write_dbt_binding(tmp_path, "top", "merged/int_top.sql")
        assert _load(tmp_path).empty

    def test_a_binding_with_an_unreadable_sql_path_is_skipped(self, tmp_path: Path) -> None:
        _write_dbt_binding(tmp_path, "ghost", "merged/does_not_exist.sql")
        assert _load(tmp_path).empty


# ---------------------------------------------------------------------------
# The one predicate
# ---------------------------------------------------------------------------


class TestIsGapColumnDecided:
    def test_ledger_then_binding_then_undecided(self, tmp_path: Path) -> None:
        _write_relation_binding(tmp_path)
        _three_layer_hub(tmp_path)
        record_disposition(
            hub_root=tmp_path, system="app", table="customers", column="real_orphan_col",
            disposition="deferred", rationale="later",
        )
        recorded = load_dispositions(tmp_path)
        bound = _load(tmp_path)
        assert is_gap_column_decided(recorded, bound, "app", "customers", "real_orphan_col") == "ledger"
        assert is_gap_column_decided(recorded, bound, "app", "customers", "customer_id") == "binding"
        assert is_gap_column_decided(recorded, bound, "app", "customers", "unknown") == ""
        # A dbtModel chain naming the column is evidence, not a decision.
        assert is_gap_column_decided(recorded, bound, "tms", "shipment", "sailing_date") == ""


# ---------------------------------------------------------------------------
# Memo
# ---------------------------------------------------------------------------


class TestMemo:
    def test_a_repeat_call_does_not_reparse(self, tmp_path: Path, monkeypatch) -> None:
        _write_relation_binding(tmp_path)
        first = _load(tmp_path)
        parsed: list[str] = []
        original = yaml.safe_load
        monkeypatch.setattr(module.yaml, "safe_load", lambda t: parsed.append(t) or original(t))
        assert _load(tmp_path) is first
        assert parsed == []

    def test_an_edited_model_sql_is_a_miss(self, tmp_path: Path) -> None:
        _three_layer_hub(tmp_path)
        assert _load(tmp_path).unconfirmed_readers("tms", "shipment", "eta") == {"stg_tms__shipment"}
        _write_model(
            tmp_path, "staging/stg_tms__shipment.sql",
            "select id, eta from {{ source('tms', 'shipment') }}",
        )
        bound = _load(tmp_path)
        assert bound.unconfirmed_readers("tms", "shipment", "eta") == frozenset()
        assert bound.read_by_models("tms", "shipment", "eta") == {"stg_tms__shipment"}

    def test_a_new_binding_is_a_miss(self, tmp_path: Path) -> None:
        _three_layer_hub(tmp_path)
        assert not _load(tmp_path).decided_by_binding("app", "customers", "customer_id")
        _write_relation_binding(tmp_path)
        assert _load(tmp_path).decided_by_binding("app", "customers", "customer_id")

    def test_cache_disabled_bypasses_the_memo(self, tmp_path: Path, monkeypatch) -> None:
        from kairos_ontology.core import ontology_loader

        _write_relation_binding(tmp_path)
        first = _load(tmp_path)
        monkeypatch.setattr(ontology_loader, "CACHE_ENABLED", False)
        assert _load(tmp_path) is not first


# ---------------------------------------------------------------------------
# The DD-169 gate and the decision sheet
# ---------------------------------------------------------------------------


class TestGate:
    def test_a_relation_binding_clears_the_columns_it_names(self, tmp_path: Path) -> None:
        _write_relation_binding(tmp_path)
        _write_alignment(tmp_path, "party", "app", "customers", ["customer_name", "real_orphan_col"])
        assert [c.column for c in undecided_gap_columns(tmp_path)] == ["real_orphan_col"]

    def test_a_dbt_chain_annotates_but_never_clears(self, tmp_path: Path) -> None:
        _three_layer_hub(tmp_path)
        _write_alignment(tmp_path, "consignment", "tms", "shipment", ["sailing_date", "eta", "notes"])
        by_name = {c.column: c for c in undecided_gap_columns(tmp_path)}
        assert set(by_name) == {"sailing_date", "eta", "notes"}
        named = by_name["sailing_date"]
        assert named.read_by == ("int_tms__shipment",)
        assert named.lineage_unconfirmed is False
        assert named.read_by_note() == "named by int_tms__shipment"
        assert named.to_dict()["read_by"] == ["int_tms__shipment"]
        assert "lineage_unconfirmed" not in named.to_dict()
        star = by_name["eta"]
        assert star.read_by == ("stg_tms__shipment",)
        assert star.lineage_unconfirmed is True
        assert star.to_dict()["lineage_unconfirmed"] is True
        assert "select *" in star.read_by_note()
        # Every column of a star-read table is unconfirmed, not only the ones named.
        assert by_name["notes"].lineage_unconfirmed is True

    def test_a_table_no_chain_reads_carries_nothing_extra(self, tmp_path: Path) -> None:
        _three_layer_hub(tmp_path)
        _write_alignment(tmp_path, "booking", "tms", "booking", ["remarks"])
        (column,) = undecided_gap_columns(tmp_path, domains=["booking"])
        assert column.read_by == ()
        assert "read_by" not in column.to_dict()
        assert column.read_by_note() == ""

    def test_the_gate_names_the_binding_route(self) -> None:
        from kairos_ontology.core.alignment_report import GAP_RESOLUTIONS

        assert any("EntityBinding" in r and "DD-250" in r for r in GAP_RESOLUTIONS)


class TestSheet:
    def _hub(self, tmp_path: Path) -> Path:
        _three_layer_hub(tmp_path)
        _write_relation_binding(tmp_path)
        _write_alignment(tmp_path, "party", "app", "customers", ["customer_name", "real_orphan_col"])
        _write_alignment(
            tmp_path, "consignment", "tms", "shipment", ["sailing_date", "custom_fields", "notes"]
        )
        return tmp_path

    def _entry(self, sheet: dict, column: str) -> dict:
        return next(e for e in sheet["decisions"] if e["column"] == column)

    def test_a_named_column_is_proposed_bound(self, tmp_path: Path) -> None:
        sheet = build_decision_sheet(self._hub(tmp_path))
        entry = self._entry(sheet, "sailing_date")
        assert entry["proposed_disposition"] == "bound"
        assert entry["confidence"] == "high"
        assert entry["read_by"] == ["int_tms__shipment"]
        assert "int_tms__shipment" in entry["reasoning"]
        assert sheet["summary"]["with_binding_read"] == 1

    def test_a_star_read_withdraws_a_rule_that_would_rule_it_out(self, tmp_path: Path) -> None:
        """``custom_fields`` is a JSON-blob name the rule drafts ``deferred`` for."""
        sheet = build_decision_sheet(self._hub(tmp_path))
        entry = self._entry(sheet, "custom_fields")
        assert entry["lineage_unconfirmed"] is True
        assert entry["read_by"] == ["stg_tms__shipment"]
        assert entry["proposed_disposition"] == ""
        assert "would have drafted 'deferred'" in entry["reasoning"]
        assert sheet["summary"]["with_lineage_unconfirmed"] >= 1

    def test_a_relation_bound_column_never_reaches_the_sheet(self, tmp_path: Path) -> None:
        sheet = build_decision_sheet(self._hub(tmp_path))
        names = {e["column"] for e in sheet["decisions"]}
        assert "customer_name" not in names
        assert "real_orphan_col" in names
        assert sheet["summary"]["source_columns_covered"] == len(undecided_gap_columns(tmp_path))

    def test_accept_proposals_takes_bound_and_holds_unconfirmed(self, tmp_path: Path) -> None:
        hub = self._hub(tmp_path)
        sheet = build_decision_sheet(hub)
        counts = accept_proposals(sheet)
        assert counts["bound"] == 1
        assert counts["held-for-binding-read"] >= 1
        assert self._entry(sheet, "sailing_date")["decision"] == "bound"
        assert self._entry(sheet, "custom_fields")["decision"] == ""

        stats = apply_decision_sheet(hub, decided_by="autopilot", sheet=sheet)
        assert stats["columns_written"] >= 1
        row = load_dispositions(hub)[("tms", "shipment", "sailing_date")]
        assert row["disposition"] == "bound"
        assert row["decided_by"] == "autopilot"
        assert "read-by:int_tms__shipment" in row["evidence"]
        # Recorded bound: the gate no longer lists it, the sheet no longer drafts it.
        assert "sailing_date" not in {c.column for c in undecided_gap_columns(hub)}

    def test_apply_counts_columns_a_binding_decided(self, tmp_path: Path) -> None:
        hub = self._hub(tmp_path)
        sheet = build_decision_sheet(hub)
        # A family or name decision typed for a column a relation binding already names
        # can only come from an older sheet; it is left alone and counted.
        sheet["decisions"].append(
            {"column": "customer_name", "domain": "party", "decision": "deferred", "reasoning": "x"}
        )
        write_decision_sheet(hub, sheet)
        stats = apply_decision_sheet(hub, dry_run=True)
        assert stats["skipped_bound_by_binding"] == 1
        assert stats["columns_written"] == 0
