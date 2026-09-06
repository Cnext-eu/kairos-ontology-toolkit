# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Harvesting Desktop and Fabric edits back into authored hub inputs (issue #744).

A BI engineer opened the generated PBIP, hid a column, added measures -- and the next
`emit-gold` overwrote all of it. The only defences were to stop editing or to stop
re-emitting, and both defeat the point of generating the model.

Desktop is a proposal tool; the hub stays the source of truth (DD-206 §8). `harvest-gold`
reads the edited model, diffs it against a fresh in-memory emit, and writes a review
document plus a Turtle snippet. It applies nothing: merging an edit into
`model/extensions/` would make the hub's authored inputs a downstream artifact of a
report.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from click.testing import CliRunner

from kairos_ontology.cli.main import cli
from kairos_ontology.core.gold_harvest import diff_models, normalize_dax
from kairos_ontology.core.hub_utils import publish_root
from kairos_ontology.core.tmdl_parser import TmdlModel, parse_tmdl_content

_PRODUCT_HUB = Path(__file__).parent / "scenarios" / "v5-product-hub"

_PARTY_GOLD = """
@prefix party: <https://example.test/ontology/party#> .
@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .

<https://example.test/ontology/party>
  kairos-ext:goldSchema "gold_party" ;
  kairos-ext:goldProductProfile "dimensional-powerbi-v1" .

party:Customer
  kairos-ext:goldTableType "dimension" ;
  kairos-ext:goldTableName "dim_customer" ;
  kairos-ext:goldSourceModel "customer" ;
  kairos-ext:goldSourceVersion "1.0.0" ;
  kairos-ext:dimensionExposure "current-only" ;
  kairos-ext:dimensionVersionBinding "current" .
"""


def _hub(tmp_path: Path) -> Path:
    hub = tmp_path / "hub"
    shutil.copytree(_PRODUCT_HUB, hub)
    extensions = hub / "model" / "extensions"
    extensions.mkdir(parents=True, exist_ok=True)
    (extensions / "party-gold-ext.ttl").write_text(_PARTY_GOLD, encoding="utf-8")
    return hub


def _run(hub: Path, monkeypatch, *args: str):
    monkeypatch.chdir(hub)
    return CliRunner().invoke(cli, list(args))


def _model(*tmdl: str) -> TmdlModel:
    model = TmdlModel(name="test")
    for content in tmdl:
        for item in parse_tmdl_content(content):
            if hasattr(item, "columns"):
                model.tables.append(item)
    return model


_EMITTED = """table dim_customer
\tlineageTag: table-1
\tannotation Kairos_TableRole = "dimension"
\tannotation Kairos_SilverBinding = "customer@1.0.0"

\t/// Governed by the hub.
\tmeasure 'Customer Count' = COUNTROWS('dim_customer')
\t\tformatString: #,0
\t\tdisplayFolder: Volume
\t\tlineageTag: m-1
\t\tannotation Kairos_Lifecycle = "provisional"

\tcolumn customer_name
\t\tdataType: String
\t\tlineageTag: col-1
\t\tsourceColumn: customer_name
\t\tsummarizeBy: none

\tcolumn city
\t\tdataType: String
\t\tlineageTag: col-2
\t\tsourceColumn: city
\t\tsummarizeBy: none
"""


class TestDiff:
    def test_a_hand_added_measure_is_new(self):
        edited = (
            _EMITTED
            + """
\tmeasure 'Revenue' = SUM('dim_customer'[amount])
\t\tformatString: #,0.00
\t\tlineageTag: m-2
"""
        )
        result = diff_models(_model(_EMITTED), _model(edited), product="party")
        assert [item.name for item in result.new_measures] == ["Revenue"]
        assert result.new_measures[0].table == "dim_customer"

    def test_a_governed_measure_is_not_reported_as_new(self):
        """The `Kairos_Lifecycle` annotation is how a hub measure is told from a hand one."""
        result = diff_models(_model(_EMITTED), _model(_EMITTED), product="party")
        assert result.new_measures == []
        assert result.empty

    def test_reformatted_dax_is_not_a_change(self):
        """Desktop re-indents and fences DAX; comparing raw text flags everything."""
        edited = _EMITTED.replace(
            "measure 'Customer Count' = COUNTROWS('dim_customer')",
            "measure 'Customer Count' = ```\n\t\t\tCOUNTROWS( 'dim_customer' )\n\t\t\t```",
        )
        result = diff_models(_model(_EMITTED), _model(edited), product="party")
        assert result.changed_measures == []

    def test_a_real_expression_change_is_reported(self):
        edited = _EMITTED.replace(
            "COUNTROWS('dim_customer')", "DISTINCTCOUNT('dim_customer'[customer_name])"
        )
        result = diff_models(_model(_EMITTED), _model(edited), product="party")
        assert [item.name for item in result.changed_measures] == ["Customer Count"]
        assert "expression" in result.changed_measures[0].changed_fields

    def test_a_column_hidden_in_desktop_is_harvestable(self):
        edited = _EMITTED.replace(
            "\tcolumn city\n\t\tdataType: String",
            "\tcolumn city\n\t\tdataType: String\n\t\tisHidden",
        )
        result = diff_models(_model(_EMITTED), _model(edited), product="party")
        assert result.hidden_columns == [("dim_customer", "city")]

    def test_a_rename_is_matched_by_lineage_tag(self):
        """Desktop preserves lineageTag across a rename, so this is one change not two."""
        edited = _EMITTED.replace("\tcolumn city\n", "\tcolumn City\n")
        result = diff_models(_model(_EMITTED), _model(edited), product="party")
        assert result.renamed_columns == [("dim_customer", "city", "City")]

    def test_normalize_dax_collapses_formatting_only(self):
        assert normalize_dax("```\n  SUM( x )\n```") == normalize_dax("SUM( x )")
        assert normalize_dax("SUM(x)") != normalize_dax("SUM(y)")


class TestCommand:
    def test_it_writes_a_report_and_a_proposal_without_touching_extensions(
        self, tmp_path, monkeypatch
    ):
        hub = _hub(tmp_path)
        _run(hub, monkeypatch, "emit-gold", "party", "--confirm-emit")
        model_dir = publish_root(hub) / "powerbi" / "party" / "Party.SemanticModel"
        edited = tmp_path / "edited"
        shutil.copytree(model_dir, edited)
        table = edited / "definition" / "tables" / "dim_customer.tmdl"
        before = (hub / "model" / "extensions" / "party-gold-ext.ttl").read_text(encoding="utf-8")
        table.write_text(
            table.read_text(encoding="utf-8")
            + "\n\tmeasure 'Customer Count' = COUNTROWS('dim_customer')\n"
            "\t\tformatString: #,0\n\t\tlineageTag: hand-1\n",
            encoding="utf-8",
        )

        result = _run(hub, monkeypatch, "harvest-gold", "party", "--from", str(edited))

        assert result.exit_code == 0, result.output
        report = (hub / "model" / "planning" / "gold-harvest" / "party.md").read_text(
            encoding="utf-8"
        )
        proposal = (hub / "model" / "planning" / "gold-harvest" / "party-proposal.ttl").read_text(
            encoding="utf-8"
        )
        assert "Customer Count" in report
        assert "kairos-ext:measureId" in proposal
        assert 'kairos-ext:measureLifecycleState "provisional"' in proposal
        # The whole point: authored inputs are never rewritten behind the author's back.
        assert (hub / "model" / "extensions" / "party-gold-ext.ttl").read_text(
            encoding="utf-8"
        ) == before

    def test_an_unedited_model_reports_no_differences(self, tmp_path, monkeypatch):
        hub = _hub(tmp_path)
        _run(hub, monkeypatch, "emit-gold", "party", "--confirm-emit")
        model_dir = publish_root(hub) / "powerbi" / "party" / "Party.SemanticModel"

        result = _run(hub, monkeypatch, "harvest-gold", "party", "--from", str(model_dir))

        assert result.exit_code == 0, result.output
        assert "nothing to author" in result.output
        report = (hub / "model" / "planning" / "gold-harvest" / "party.md").read_text(
            encoding="utf-8"
        )
        assert "No differences found" in report

    def test_a_missing_model_fails_clearly(self, tmp_path, monkeypatch):
        hub = _hub(tmp_path)
        empty = tmp_path / "empty"
        empty.mkdir()

        result = _run(hub, monkeypatch, "harvest-gold", "party", "--from", str(empty))

        assert result.exit_code != 0
        assert "no SemanticModel definition/ found" in result.output
