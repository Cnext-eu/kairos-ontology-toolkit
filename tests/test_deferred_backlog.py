# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The deferred backlog stays visible (DD-251, #1062).

A column-grain ``deferred`` used to be terminal: the gate counted it decided, the sheet
dropped it, `next` never named it, and `alignment-report` never read the ledger. These
pin that the backlog is read, ranked, raised, rendered, re-listable and dated.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core import analysis_paths
from kairos_ontology.core import source_disposition as ledger
from kairos_ontology.core.alignment_report import build_alignment_report, render_markdown
from kairos_ontology.core.deferred_backlog import decision_overlay, load_deferred_columns
from kairos_ontology.core.gap_decisions import (
    accept_proposals,
    apply_decision_sheet,
    build_decision_sheet,
    write_decision_sheet,
)
from kairos_ontology.core.hub_inspection import _deferred_column_status
from kairos_ontology.core.next_actions import (
    ACTION_SKILLS,
    CompileStatus,
    DeferredColumnObservation,
    DomainSnapshot,
    HubInputSnapshot,
    InputStatus,
    propose_next_actions,
)
from kairos_ontology.core.source_disposition import load_dispositions, record_disposition

_VOCAB_HEADER = """@prefix kairos-bronze: <https://kairos.cnext.eu/bronze#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix sys: <https://example.com/source/{system}#> .
"""


def _write_source_table(hub: Path, system: str, table: str, row_count: int | None) -> None:
    directory = hub / "integration" / "sources" / system
    directory.mkdir(parents=True, exist_ok=True)
    body = _VOCAB_HEADER.format(system=system)
    body += f"\nsys:{table.title()} a kairos-bronze:SourceTable ;\n"
    if row_count is not None:
        body += f"    kairos-bronze:rowCount {row_count} ;\n"
    body += f'    kairos-bronze:tableName "{table}" .\n'
    (directory / f"{table}.ttl").write_text(body, encoding="utf-8")


def _write_anchors(hub: Path, rows: dict[tuple[str, str], str]) -> None:
    directory = analysis_paths.analysis_dir(hub)
    directory.mkdir(parents=True, exist_ok=True)
    analysis_paths.hub_path(directory, analysis_paths.TABLE_ANCHORS).write_text(
        yaml.safe_dump(
            {
                "tables": [
                    {"system": system, "table": table, "domain": domain}
                    for (system, table), domain in rows.items()
                ]
            }
        ),
        encoding="utf-8",
    )


def _write_bi_model(hub: Path, *columns: str) -> None:
    bi = hub / "integration" / "discovery" / "bi"
    bi.mkdir(parents=True, exist_ok=True)
    (bi / "Volumes-concept-mapping.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": "1",
                "model_name": "Volumes",
                "tables": [{"tmdl_name": "d_Sailing", "columns": list(columns), "measures": []}],
                "relationships": [],
            }
        ),
        encoding="utf-8",
    )


def _write_alignment(hub: Path, domain: str, system: str, table: str, columns: list[str]) -> None:
    analysis = analysis_paths.analysis_dir(hub)
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


def _defer(hub: Path, system: str, table: str, column: str, rationale: str = "later") -> None:
    record_disposition(
        hub_root=hub, system=system, table=table, column=column,
        disposition="deferred", rationale=rationale,
    )


def _backlog_hub(tmp_path: Path) -> Path:
    """Two domains, one BI-demanded column, one table without a row count."""
    _write_source_table(tmp_path, "tms", "shipment", 1200)
    _write_source_table(tmp_path, "tms", "booking", 50)
    _write_source_table(tmp_path, "crm", "party", None)
    _write_anchors(
        tmp_path,
        {("tms", "shipment"): "consignment", ("tms", "booking"): "consignment",
         ("crm", "party"): "party"},
    )
    _write_bi_model(tmp_path, "SailingDate")
    _defer(tmp_path, "tms", "shipment", "eta", "no leg model yet")
    _defer(tmp_path, "tms", "shipment", "sailing_date", "timestamp on a leg table")
    _defer(tmp_path, "tms", "booking", "remarks")
    _defer(tmp_path, "crm", "party", "qualifier")
    # Not backlog: a table-grain deferred, a ruled-out column, and an unanchored table.
    record_disposition(hub_root=tmp_path, system="tms", table="legacy",
                       disposition="deferred", rationale="whole table later")
    record_disposition(hub_root=tmp_path, system="tms", table="shipment", column="junk",
                       disposition="not-business-data", rationale="scratch")
    _defer(tmp_path, "tms", "orphan", "lost")
    return tmp_path


def _snapshot(**kw) -> HubInputSnapshot:
    base = dict(
        hub_root="/hub",
        discovery=InputStatus.PRESENT,
        sources=InputStatus.PRESENT,
        dbt_transforms=InputStatus.PRESENT,
        shapes=InputStatus.PRESENT,
        domains=(
            DomainSnapshot(
                domain="party", ontology=InputStatus.PRESENT, has_bindings=True,
                binding_count=1, compile_status=CompileStatus.PASSED,
            ),
        ),
    )
    base.update(kw)
    return HubInputSnapshot(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Reading and ranking the backlog
# ---------------------------------------------------------------------------


class TestBacklog:
    def test_only_column_grain_deferred_rows_are_backlog(self, tmp_path: Path) -> None:
        backlog = load_deferred_columns(_backlog_hub(tmp_path))
        assert backlog.total == 5
        names = {(c.system, c.table, c.column) for c in backlog.columns}
        assert ("tms", "legacy", "") not in names
        assert ("tms", "shipment", "junk") not in names

    def test_grouped_by_domain_and_ranked(self, tmp_path: Path) -> None:
        backlog = load_deferred_columns(_backlog_hub(tmp_path))
        by_domain = backlog.by_domain()
        assert list(by_domain) == ["consignment", "party", ""]  # domainless last
        consignment = [c.column for c in by_domain["consignment"]]
        # BI demand first, then the bigger table, then the smaller one.
        assert consignment == ["sailing_date", "eta", "remarks"]
        top = by_domain["consignment"][0]
        assert top.bi_demand and "Volumes" in top.bi_demand[0]
        assert top.row_count == 1200
        assert top.rationale == "timestamp on a leg table"
        assert top.recorded_on  # DD-251: every new row is dated
        assert by_domain["party"][0].row_count is None
        assert backlog.with_bi_demand == 1

    def test_by_table_and_to_dict(self, tmp_path: Path) -> None:
        backlog = load_deferred_columns(_backlog_hub(tmp_path))
        assert set(backlog.by_table("consignment")) == {"tms.shipment", "tms.booking"}
        payload = backlog.to_dict()
        assert payload["total"] == 5
        assert payload["domains"][0]["domain"] == "consignment"
        assert payload["domains"][0]["columns"][0]["column"] == "sailing_date"
        import json

        json.dumps(payload)  # JSON-serialisable for the report

    def test_a_hub_without_a_ledger_has_no_backlog(self, tmp_path: Path) -> None:
        assert load_deferred_columns(tmp_path).total == 0

    def test_an_unreadable_ledger_is_empty_not_fatal(self, tmp_path: Path) -> None:
        _defer(tmp_path, "tms", "shipment", "eta")
        path = ledger.ledger_path(tmp_path, "tms")
        path.write_text("tables: [\n", encoding="utf-8")
        assert load_deferred_columns(tmp_path).total == 0

    def test_domain_of_wins_over_the_anchors_sheet(self, tmp_path: Path) -> None:
        backlog = load_deferred_columns(
            _backlog_hub(tmp_path), domain_of=lambda s, t, c: "booking" if c == "eta" else ""
        )
        assert {c.column: c.domain for c in backlog.columns}["eta"] == "booking"
        assert {c.column: c.domain for c in backlog.columns}["remarks"] == "consignment"


# ---------------------------------------------------------------------------
# `next`
# ---------------------------------------------------------------------------


class TestNext:
    def test_the_observer_counts_per_domain(self, tmp_path: Path) -> None:
        observation = _deferred_column_status(_backlog_hub(tmp_path))
        assert observation.columns_total == 5
        assert observation.with_bi_demand == 1
        assert observation.by_domain == (("consignment", 3), ("party", 1), ("", 1))

    def test_the_observer_defaults_on_an_empty_hub(self, tmp_path: Path) -> None:
        assert _deferred_column_status(tmp_path) == DeferredColumnObservation()

    def test_an_optional_action_is_raised(self) -> None:
        proposal = propose_next_actions(
            _snapshot(
                deferred_columns=DeferredColumnObservation(
                    columns_total=7, with_bi_demand=2,
                    by_domain=(("consignment", 4), ("party", 2), ("", 1)),
                )
            )
        )
        (action,) = [a for a in proposal.actions if a.kind == "review-deferred-columns"]
        assert action.status.value == "optional"
        assert action.blocking is False
        assert action.skill == "kairos-design-domain"
        assert ACTION_SKILLS["review-deferred-columns"] == "kairos-design-domain"
        assert "7 source column(s)" in action.rationale
        assert "consignment 4" in action.rationale and "(no domain) 1" in action.rationale
        assert "2 of them are used by an imported Power BI model" in action.rationale
        assert "--include-deferred" in action.command

    def test_no_action_without_a_backlog(self) -> None:
        proposal = propose_next_actions(_snapshot())
        assert not [a for a in proposal.actions if a.kind == "review-deferred-columns"]


# ---------------------------------------------------------------------------
# alignment-report
# ---------------------------------------------------------------------------


class TestReport:
    def _hub(self, tmp_path: Path) -> Path:
        hub = _backlog_hub(tmp_path)
        _write_alignment(hub, "consignment", "tms", "shipment",
                         ["eta", "sailing_date", "junk", "notes"])
        return hub

    def test_the_overlay_tells_states_apart(self, tmp_path: Path) -> None:
        hub = self._hub(tmp_path)
        report = build_alignment_report(analysis_paths.analysis_dir(hub), hub_root=hub)
        overlay = decision_overlay(report, hub)
        assert [c.column for c in overlay.undecided(report)] == ["notes"]
        assert overlay.domain_totals(report)["consignment"] == {
            "deferred": 2, "ruled_out": 1, "extension": 0, "bound": 0, "undecided": 1,
        }
        # The backlog takes its domain from the alignment, not only the anchors.
        assert overlay.backlog.by_domain()["consignment"][0].column == "sailing_date"

    def test_markdown_with_overlay_lists_undecided_and_the_backlog(self, tmp_path: Path) -> None:
        hub = self._hub(tmp_path)
        report = build_alignment_report(analysis_paths.analysis_dir(hub), hub_root=hub)
        rendered = render_markdown(report, overlay=decision_overlay(report, hub))
        needing = rendered.split("## Columns needing a decision")[1].split("## Deferred backlog")[0]
        assert "`notes`" in needing
        assert "`eta`" not in needing and "`junk`" not in needing
        backlog = rendered.split("## Deferred backlog")[1]
        assert "### consignment — 3 deferred, 1 with BI demand" in backlog
        assert "`sailing_date`" in backlog and "timestamp on a leg table" in backlog
        assert "| 1,200 |" in backlog
        assert "| Undecided | Deferred | Ruled out | Extension | Bound |" in rendered

    def test_markdown_without_overlay_is_unchanged(self, tmp_path: Path) -> None:
        hub = self._hub(tmp_path)
        report = build_alignment_report(analysis_paths.analysis_dir(hub), hub_root=hub)
        rendered = render_markdown(report)
        assert "Deferred backlog" not in rendered
        assert "`eta`" in rendered.split("## Columns needing a decision")[1]

    def test_the_cli_carries_the_overlay_in_both_forms(self, tmp_path: Path, monkeypatch) -> None:
        hub = self._hub(tmp_path)
        (hub / "model" / "ontologies").mkdir(parents=True)
        monkeypatch.chdir(hub)
        text = CliRunner().invoke(cli, ["alignment-report"])
        assert text.exit_code == 0, text.output
        assert "## Deferred backlog" in text.output
        as_json = CliRunner().invoke(cli, ["alignment-report", "--format", "json"])
        assert as_json.exit_code == 0, as_json.output
        import json

        payload = json.loads(as_json.output)
        assert [c["column"] for c in payload["undecided_columns"]] == ["notes"]
        assert payload["deferred_backlog"]["total"] == 5
        assert payload["domains"][0]["decisions"]["deferred"] == 2


# ---------------------------------------------------------------------------
# draft-gap-decisions --include-deferred and --apply
# ---------------------------------------------------------------------------


class TestIncludeDeferred:
    def _hub(self, tmp_path: Path) -> Path:
        hub = _backlog_hub(tmp_path)
        _write_alignment(hub, "consignment", "tms", "shipment", ["eta", "sailing_date", "notes"])
        return hub

    def test_without_the_flag_deferred_names_stay_off_the_sheet(self, tmp_path: Path) -> None:
        sheet = build_decision_sheet(self._hub(tmp_path))
        assert {e["column"] for e in sheet["decisions"]} == {"notes"}
        assert sheet["summary"]["previously_deferred"] == 0

    def test_with_the_flag_they_are_relisted_with_their_history(self, tmp_path: Path) -> None:
        sheet = build_decision_sheet(self._hub(tmp_path), include_deferred=True)
        by_name = {e["column"]: e for e in sheet["decisions"]}
        assert set(by_name) == {"notes", "eta", "sailing_date"}
        eta = by_name["eta"]
        assert eta["previous_decision"] == "deferred"
        assert eta["previous_rationale"] == "no leg model yet"
        assert eta["previous_decided_by"] == "user"
        assert eta["recorded_on"]
        assert eta["previously_deferred_occurrences"] == 1
        assert eta["decision"] == ""
        assert "previous_decision" not in by_name["notes"]
        assert sheet["summary"]["previously_deferred"] == 2
        assert "previous_decision" in sheet["how_to_use"]

    def test_apply_overwrites_only_the_relisted_deferred_rows(self, tmp_path: Path) -> None:
        hub = self._hub(tmp_path)
        sheet = build_decision_sheet(hub, include_deferred=True)
        for entry in sheet["decisions"]:
            if entry["column"] == "eta":
                entry["decision"] = "registered-extension"
                entry["reasoning"] = "modelled now"
        write_decision_sheet(hub, sheet)
        stats = apply_decision_sheet(hub)
        assert stats["overwritten_deferred"] == 1
        assert stats["columns_written"] == 1
        rows = load_dispositions(hub)
        assert rows[("tms", "shipment", "eta")]["disposition"] == "registered-extension"
        assert rows[("tms", "shipment", "sailing_date")]["disposition"] == "deferred"
        assert rows[("tms", "shipment", "junk")]["disposition"] == "not-business-data"

    def test_a_sheet_claim_alone_never_overwrites_another_disposition(self, tmp_path: Path) -> None:
        """The guard reads the ledger: a forged 'previous_decision' changes nothing."""
        hub = self._hub(tmp_path)
        sheet = build_decision_sheet(hub)
        sheet["decisions"].append({
            "column": "junk", "domain": "consignment", "decision": "deferred",
            "previous_decision": "deferred", "reasoning": "x",
        })
        write_decision_sheet(hub, sheet)
        stats = apply_decision_sheet(hub)
        assert stats["overwritten_deferred"] == 0
        assert load_dispositions(hub)[("tms", "shipment", "junk")]["disposition"] == "not-business-data"

    def test_a_carried_decision_equal_to_the_previous_one_is_dropped(self, tmp_path: Path) -> None:
        hub = self._hub(tmp_path)
        first = build_decision_sheet(hub, include_deferred=True)
        for entry in first["decisions"]:
            if entry["column"] == "eta":
                entry["decision"] = "deferred"
        write_decision_sheet(hub, first)
        second = build_decision_sheet(hub, include_deferred=True)
        write_decision_sheet(hub, second)
        rebuilt = yaml.safe_load(
            analysis_paths.read_hub_path(
                analysis_paths.analysis_dir(hub), analysis_paths.GAP_DECISIONS
            ).read_text(encoding="utf-8")
        )
        eta = next(e for e in rebuilt["decisions"] if e["column"] == "eta")
        assert eta["decision"] == ""

    def test_accept_proposals_holds_relisted_names(self, tmp_path: Path) -> None:
        sheet = build_decision_sheet(self._hub(tmp_path), include_deferred=True)
        counts = accept_proposals(sheet)
        # `sailing_date` is held for its BI demand first; `eta` for being re-listed.
        assert counts["held-for-bi-demand"] == 1
        assert counts["held-previously-deferred"] == 1
        assert all(e["decision"] == "" for e in sheet["decisions"] if e.get("previous_decision"))

    def test_the_cli_refuses_the_flag_with_accept_proposals(self, tmp_path: Path, monkeypatch) -> None:
        hub = self._hub(tmp_path)
        (hub / "model" / "ontologies").mkdir(parents=True)
        monkeypatch.chdir(hub)
        result = CliRunner().invoke(
            cli, ["draft-gap-decisions", "--include-deferred", "--accept-proposals", "--dry-run"]
        )
        assert result.exit_code != 0
        assert "cannot be combined" in result.output

    def test_the_cli_drafts_and_reports_the_relisting(self, tmp_path: Path, monkeypatch) -> None:
        hub = self._hub(tmp_path)
        (hub / "model" / "ontologies").mkdir(parents=True)
        monkeypatch.chdir(hub)
        result = CliRunner().invoke(cli, ["draft-gap-decisions", "--include-deferred", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "2 name(s) re-listed from the deferred backlog" in result.output


# ---------------------------------------------------------------------------
# recorded_on and the BI-demand warnings on the manual path
# ---------------------------------------------------------------------------


class TestRecordedOn:
    def test_a_new_row_is_dated_and_an_old_one_keeps_its_shape(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(ledger, "_utc_today", lambda: "2026-09-27")
        _defer(tmp_path, "tms", "shipment", "eta")
        path = ledger.ledger_path(tmp_path, "tms")
        # An older row, written before the key existed.
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        doc["tables"].append({
            "system": "tms", "table": "shipment", "column": "old", "disposition": "deferred",
            "rationale": "then", "decided_by": "user",
        })
        path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        _defer(tmp_path, "tms", "shipment", "later")
        rows = load_dispositions(tmp_path)
        assert rows[("tms", "shipment", "eta")]["recorded_on"] == "2026-09-27"
        assert rows[("tms", "shipment", "later")]["recorded_on"] == "2026-09-27"
        assert "recorded_on" not in rows[("tms", "shipment", "old")]


class TestBiDemandWarnings:
    def _hub(self, tmp_path: Path) -> Path:
        _write_source_table(tmp_path, "tms", "shipment", 10)
        _write_bi_model(tmp_path, "SailingDate")
        _write_alignment(tmp_path, "consignment", "tms", "shipment", ["sailing_date", "notes"])
        (tmp_path / "model" / "ontologies").mkdir(parents=True)
        return tmp_path

    def test_apply_reports_a_demanded_name_ruled_out(self, tmp_path: Path) -> None:
        hub = self._hub(tmp_path)
        sheet = build_decision_sheet(hub)
        for entry in sheet["decisions"]:
            entry["decision"] = "deferred"
        write_decision_sheet(hub, sheet)
        stats = apply_decision_sheet(hub)
        assert stats["ruled_out_with_bi_demand"] == ["sailing_date"]

    def test_the_cli_warns_on_apply(self, tmp_path: Path, monkeypatch) -> None:
        hub = self._hub(tmp_path)
        sheet = build_decision_sheet(hub)
        for entry in sheet["decisions"]:
            entry["decision"] = "not-business-data"
        write_decision_sheet(hub, sheet)
        monkeypatch.chdir(hub)
        result = CliRunner().invoke(cli, ["draft-gap-decisions", "--apply"])
        assert result.exit_code == 0, result.output
        assert "a Power BI model uses were recorded" in result.output
        assert "sailing_date" in result.output

    def test_source_disposition_set_warns(self, tmp_path: Path, monkeypatch) -> None:
        hub = self._hub(tmp_path)
        monkeypatch.chdir(hub)
        result = CliRunner().invoke(
            cli,
            ["source-disposition", "set", "--system", "tms", "--table", "shipment",
             "--column", "sailing_date", "--disposition", "deferred", "--rationale", "x"],
        )
        assert result.exit_code == 0, result.output
        assert "is used by an imported Power BI model" in result.output
        quiet = CliRunner().invoke(
            cli,
            ["source-disposition", "set", "--system", "tms", "--table", "shipment",
             "--column", "notes", "--disposition", "deferred", "--rationale", "x"],
        )
        assert quiet.exit_code == 0, quiet.output
        assert "Power BI" not in quiet.output


# ---------------------------------------------------------------------------
# A binding retires a deferred column (#1069)
# ---------------------------------------------------------------------------


class TestRetiredByBinding:
    """DD-251 says a binding that names a deferred column retires it. Before #1069 the
    backlog read the ledger alone, so a deferred-then-bound column stayed "deferred"."""

    def _hub(self, tmp_path: Path) -> Path:
        from tests.test_bound_columns import RELATION_BINDING, _write_relation_binding

        hub = _backlog_hub(tmp_path)
        _write_alignment(hub, "consignment", "tms", "shipment", ["eta", "sailing_date", "notes"])
        _write_relation_binding(
            hub,
            RELATION_BINDING.replace("relation: app.customers", "relation: tms.shipment")
            .replace("upper(Customer_Name)", "eta"),
        )
        return hub

    def test_the_backlog_drops_a_bound_column_and_reports_it_retired(
        self, tmp_path: Path
    ) -> None:
        backlog = load_deferred_columns(self._hub(tmp_path))
        assert ("tms", "shipment", "eta") not in {
            (c.system, c.table, c.column) for c in backlog.columns
        }
        assert [(c.table, c.column) for c in backlog.retired] == [("shipment", "eta")]
        assert backlog.total == 4
        assert backlog.to_dict()["retired_by_binding"][0]["column"] == "eta"

    def test_next_no_longer_counts_it(self, tmp_path: Path) -> None:
        assert _deferred_column_status(self._hub(tmp_path)).columns_total == 4

    def test_the_overlay_reports_it_bound(self, tmp_path: Path) -> None:
        hub = self._hub(tmp_path)
        report = build_alignment_report(analysis_paths.analysis_dir(hub), hub_root=hub)
        overlay = decision_overlay(report, hub)
        assert overlay.domain_totals(report)["consignment"] == {
            "deferred": 1, "ruled_out": 0, "extension": 0, "bound": 1, "undecided": 1,
        }
        rendered = render_markdown(report, overlay=overlay)
        retired = rendered.split("## Deferred rows a binding has retired")[1]
        assert "tms.shipment `eta`" in retired
        assert "`eta`" not in rendered.split("## Deferred backlog")[1].split("## Deferred rows")[0]

    def test_include_deferred_does_not_relist_it(self, tmp_path: Path) -> None:
        sheet = build_decision_sheet(self._hub(tmp_path), include_deferred=True)
        assert {e["column"] for e in sheet["decisions"]} == {"notes", "sailing_date"}
        assert sheet["summary"]["previously_deferred"] == 1

    def test_only_deferred_gives_way_to_a_binding(self, tmp_path: Path) -> None:
        from kairos_ontology.core.bound_columns import is_gap_column_decided, load_bound_columns

        hub = self._hub(tmp_path)
        record_disposition(
            hub_root=hub, system="tms", table="shipment", column="customer_id",
            disposition="not-business-data", rationale="contradiction for a reviewer",
        )
        recorded = load_dispositions(hub)
        bound = load_bound_columns(hub / "integration" / "bindings", hub)
        assert is_gap_column_decided(recorded, bound, "tms", "shipment", "eta") == "binding"
        assert is_gap_column_decided(recorded, bound, "tms", "shipment", "customer_id") == "ledger"
        assert is_gap_column_decided(recorded, bound, "tms", "shipment", "sailing_date") == "ledger"

    def test_a_dbt_model_chain_reading_it_keeps_it_in_the_backlog(self, tmp_path: Path) -> None:
        from tests.test_bound_columns import _three_layer_hub

        hub = _backlog_hub(tmp_path)
        _three_layer_hub(hub)  # a dbtModel chain whose SQL names tms.shipment sailing_date
        backlog = load_deferred_columns(hub)
        assert "sailing_date" in {c.column for c in backlog.columns}
        assert backlog.retired == []
