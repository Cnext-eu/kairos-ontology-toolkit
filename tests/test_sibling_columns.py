# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deferred columns that complete a field their table already binds (#1068).

The DD-251 backlog was flat. These pin that a deferred column next to a bound field it
completes is detected, ranked first, and surfaced in ``alignment-report``, ``next`` and
``draft-gap-decisions --include-deferred``, and that the detection never becomes a
decision.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kairos_ontology.core import analysis_paths
from kairos_ontology.core.alignment_report import build_alignment_report, render_markdown
from kairos_ontology.core.deferred_backlog import decision_overlay, load_deferred_columns
from kairos_ontology.core.gap_decisions import build_decision_sheet
from kairos_ontology.core.hub_inspection import _deferred_column_status
from kairos_ontology.core.next_actions import DeferredColumnObservation, propose_next_actions
from kairos_ontology.core.sibling_columns import detect_sibling, sinks, tokens
from tests.test_bound_columns import RELATION_BINDING, _write_relation_binding
from tests.test_deferred_backlog import _defer, _snapshot, _write_anchors, _write_source_table

# ---------------------------------------------------------------------------
# The detector
# ---------------------------------------------------------------------------


def test_tokens_split_vendor_prefixes_and_camel_case() -> None:
    assert tokens("JZ_WeightUQ") == ("jz", "weight", "uq")
    assert tokens("JR_RX_NKSellInvoiceCurrency") == ("jr", "rx", "nk", "sell", "invoice", "currency")
    assert tokens("LOCAL_TOTAL_CURRENCY") == ("local", "total", "currency")


@pytest.mark.parametrize(
    ("column", "bound", "profile", "expected"),
    [
        ("JZ_WeightUQ", {"JZ_Weight": {"c:w"}}, None, ("unit", "JZ_Weight")),
        ("JZ_VolumeUQ", {"JZ_Weight": {"c:w"}, "JZ_Volume": {"c:v"}}, None, ("unit", "JZ_Volume")),
        ("LOCAL_TOTAL_CURRENCY", {"LOCAL_TOTAL": {"f:t"}}, None, ("currency", "LOCAL_TOTAL")),
        # No exact stem: pairs only because the table binds exactly one amount.
        ("JR_RX_NKSellInvoiceCurrency", {"JR_RX_NKSellInvoiceAmount": {"f:a"}}, None,
         ("currency", "JR_RX_NKSellInvoiceAmount")),
        ("JR_Desc", {"JR_Code": {"f:c"}}, None, ("description", "JR_Code")),
        ("JI_Volume", {"JI_Weight": {"c:w"}}, {"tags": ["measure-like"]}, ("measure", "JI_Weight")),
        ("JI_NetWeight", {"JI_Weight": {"c:w"}}, None, ("measure", "JI_Weight")),
        ("AH_OutstandingAmount", {"AH_InvoiceTotal": {"f:t"}}, {"tags": ["measure-like"]},
         ("amount", "AH_InvoiceTotal")),
        ("AH_PostDate", {"AH_InvoiceDate": {"f:d"}}, None, ("date", "AH_InvoiceDate")),
    ],
)
def test_a_sibling_is_found(column, bound, profile, expected) -> None:
    sibling = detect_sibling(column, bound, profile=profile)
    assert sibling is not None
    assert (sibling.kind, sibling.of_column) == expected


@pytest.mark.parametrize(
    ("column", "bound", "profile"),
    [
        # The issue's own false positive: a VAT class is a code, not an amount.
        ("JR_A9_CostVATClass", {"JR_A9_Cost": {"f:c"}}, {"tags": ["code-like"]}),
        # The profile vetoes a measure that is shaped like a code.
        ("JI_Volume", {"JI_Weight": {"c:w"}}, {"tags": ["code-like"]}),
        # A unit that is itself a decimal is not a unit.
        ("JZ_WeightUQ", {"JZ_Weight": {"c:w"}}, {"tags": ["measure-like"]}),
        # Two bound amounts and no stem: the currency is ambiguous (the measured
        # "four currency foreign keys collapsing onto currency" error).
        ("CURRENCY", {"A_Amount": {"a"}, "B_Amount": {"b"}}, None),
        # Two bound codes that read the same: no unique pair.
        ("KM_GoodsDescription", {"KM_GoodsCode": {"x"}, "KM_Goods_Code": {"y"}}, None),
        ("Remarks", {"JI_Weight": {"c:w"}}, None),
        # The column is itself bound, whatever its casing.
        ("jz_weight", {"JZ_Weight": {"c:w"}}, None),
        # A table with no bound field has no siblings.
        ("JZ_WeightUQ", {}, None),
    ],
)
def test_no_sibling(column, bound, profile) -> None:
    assert detect_sibling(column, bound, profile=profile) is None


def test_empty_and_constant_columns_sink() -> None:
    assert sinks({"tags": ["empty"]}) and sinks({"tags": ["const"]})
    assert not sinks({"tags": ["code-like"]}) and not sinks(None)


# ---------------------------------------------------------------------------
# End to end on a hub
# ---------------------------------------------------------------------------


def _write_profile(hub: Path) -> None:
    directory = hub / "integration" / "sources" / "tms"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "tms.profile.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "system": "tms",
                "tables": {
                    "shipment": {
                        "rows": 1200,
                        "columns": {
                            "JZ_WeightUQ": {"tags": ["code-like"]},
                            "JZ_Volume": {"tags": ["measure-like", "empty"]},
                            "JZ_Remarks": {"tags": ["free-text"]},
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _write_alignment(hub: Path) -> None:
    analysis = analysis_paths.analysis_dir(hub)
    analysis.mkdir(parents=True, exist_ok=True)
    (analysis / "consignment-alignment.yaml").write_text(
        yaml.safe_dump(
            {
                "domain": "consignment",
                "tables": [
                    {
                        "system": "tms",
                        "table": "shipment",
                        "ref_class": "C",
                        "columns": [],
                        "custom_columns": [
                            {
                                "column": "JZ_WeightUQ",
                                "data_type": "varchar",
                                "example_values": ["KG"],
                                "closure_candidates": [
                                    {"uri": "https://example.test/cargo#weightUnit",
                                     "name": "weightUnit", "score": 0.9}
                                ],
                            },
                            {"column": "JZ_Volume", "data_type": "decimal",
                             "example_values": ["1.0"]},
                            {"column": "JZ_Remarks", "data_type": "varchar",
                             "example_values": ["x"]},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    _write_source_table(tmp_path, "tms", "shipment", 1200)
    _write_anchors(tmp_path, {("tms", "shipment"): "consignment"})
    _write_relation_binding(
        tmp_path,
        RELATION_BINDING.replace("relation: app.customers", "relation: tms.shipment")
        .replace("upper(Customer_Name)", "JZ_Weight"),
    )
    _write_profile(tmp_path)
    _write_alignment(tmp_path)
    for column in ("JZ_WeightUQ", "JZ_Volume", "JZ_Remarks"):
        _defer(tmp_path, "tms", "shipment", column)
    return tmp_path


def test_the_backlog_carries_siblings_and_ranks_them(hub: Path) -> None:
    backlog = load_deferred_columns(hub)
    by_name = {c.column: c for c in backlog.columns}
    unit = by_name["JZ_WeightUQ"].sibling
    assert unit is not None
    assert (unit.kind, unit.of_column, unit.of_property) == (
        "unit", "JZ_Weight", "party:customerName",
    )
    # JZ_Volume is a measure sibling, but the profile found it empty.
    assert by_name["JZ_Volume"].sibling is not None and by_name["JZ_Volume"].sunk
    assert by_name["JZ_Remarks"].sibling is None
    ranked = [c.column for c in backlog.by_domain()["consignment"]]
    assert ranked == ["JZ_WeightUQ", "JZ_Remarks", "JZ_Volume"]
    assert backlog.with_siblings == 2
    assert backlog.to_dict()["with_siblings"] == 2
    # Without an alignment report in hand there is no closure suggestion.
    assert by_name["JZ_WeightUQ"].suggested_property == ""


def test_the_report_lists_sibling_candidates_with_a_suggestion(hub: Path) -> None:
    report = build_alignment_report(analysis_paths.analysis_dir(hub), hub_root=hub)
    overlay = decision_overlay(report, hub)
    unit = next(c for c in overlay.backlog.columns if c.column == "JZ_WeightUQ")
    assert unit.suggested_property == "weightUnit"
    rendered = render_markdown(report, overlay=overlay)
    section = rendered.split("### Sibling candidates")[1].split("### consignment")[0]
    assert "**2 deferred column(s)**" in section
    assert (
        "| tms.shipment | `JZ_WeightUQ` | `JZ_Weight` (party:customerName) | unit "
        "| weightUnit | 1,200 |"
    ) in section
    assert "`JZ_Remarks`" not in section


def test_next_says_where_to_start(hub: Path) -> None:
    observation = _deferred_column_status(hub)
    assert observation.with_siblings == 2
    assert observation.sibling_tables == (("tms.shipment", 2),)
    proposal = propose_next_actions(_snapshot(deferred_columns=observation))
    action = next(a for a in proposal.actions if a.kind == "review-deferred-columns")
    assert "2 complete a field their table already binds" in action.rationale
    assert "tms.shipment 2" in action.rationale


def test_next_without_siblings_is_unchanged() -> None:
    observation = DeferredColumnObservation(columns_total=3, by_domain=(("party", 3),))
    proposal = propose_next_actions(_snapshot(deferred_columns=observation))
    action = next(a for a in proposal.actions if a.kind == "review-deferred-columns")
    assert "already binds" not in action.rationale


def test_the_relisted_sheet_marks_siblings_and_never_proposes_bound(hub: Path) -> None:
    sheet = build_decision_sheet(hub, include_deferred=True)
    # The three JZ_ names share a prefix, so they are one family on the sheet.
    [family] = sheet["families"]
    assert family["sibling_members"]["JZ_WeightUQ"] == [
        {"table": "tms.shipment", "kind": "unit", "of_column": "JZ_Weight",
         "of_property": "party:customerName"},
    ]
    assert set(family["sibling_members"]) == {"JZ_WeightUQ", "JZ_Volume"}
    assert sheet["summary"]["previously_deferred_siblings"] == 2
    entries = [*sheet["decisions"], *sheet["families"]]
    assert all(e.get("proposed_disposition") != "bound" for e in entries)


def test_a_loose_relisted_name_carries_its_siblings(hub: Path) -> None:
    # One name alone forms no family, so it is a loose decision with the key on it.
    from kairos_ontology.core import source_disposition as ledger

    for column in ("JZ_Volume", "JZ_Remarks"):
        ledger.record_disposition(
            hub_root=hub, system="tms", table="shipment", column=column,
            disposition="not-business-data", rationale="scratch",
        )
    sheet = build_decision_sheet(hub, include_deferred=True)
    by_name = {e["column"]: e for e in sheet["decisions"]}
    assert by_name["JZ_WeightUQ"]["siblings"][0]["kind"] == "unit"


def test_the_sheet_without_the_flag_carries_no_siblings(hub: Path) -> None:
    sheet = build_decision_sheet(hub)
    assert sheet["summary"]["previously_deferred_siblings"] == 0
    assert all("siblings" not in e for e in sheet["decisions"])
