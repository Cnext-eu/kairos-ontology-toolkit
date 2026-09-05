# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Harvesting usage from a legacy report's PBIR definition (issue #744).

`import-tmdl` turned the `.SemanticModel` half of a PBIP export into demand evidence and
read nothing from the `.Report` half, where the reporting patterns actually live: which
measures are *placed on visuals* rather than merely defined, and which attributes people
filter on. On a real client estate that was 18 exports and roughly 2,000 visuals of
evidence going in the bin.

DD-147's discipline is unchanged: only derived counts reach the hub.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from kairos_ontology.core.report_usage import (
    find_report_dirs,
    parse_report_folder,
    render_report_usage,
)


def _column(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def _measure(entity: str, prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def _visual(visual_type: str, *fields: dict) -> dict:
    return {
        "name": "v1",
        "position": {"x": 0, "y": 0, "width": 100, "height": 100},
        "visual": {
            "visualType": visual_type,
            "query": {
                "queryState": {"Values": {"projections": [{"field": item} for item in fields]}}
            },
        },
    }


def _report(tmp_path: Path, pages: dict[str, list[dict]], *, name: str = "Sales") -> Path:
    root = tmp_path / f"{name}.Report"
    for index, (display, visuals) in enumerate(pages.items()):
        page_dir = root / "definition" / "pages" / f"page{index}"
        page_dir.mkdir(parents=True)
        (page_dir / "page.json").write_text(
            json.dumps({"name": f"page{index}", "displayName": display}), encoding="utf-8"
        )
        for position, visual in enumerate(visuals):
            visual_dir = page_dir / "visuals" / f"v{position}"
            visual_dir.mkdir(parents=True)
            (visual_dir / "visual.json").write_text(json.dumps(visual), encoding="utf-8")
    return root


class TestFindingReports:
    def test_a_report_folder_is_found(self, tmp_path):
        report = _report(tmp_path, {"Overview": []})
        assert find_report_dirs(tmp_path) == [report]

    def test_the_folder_itself_is_accepted(self, tmp_path):
        report = _report(tmp_path, {"Overview": []})
        assert find_report_dirs(report) == [report]

    def test_a_report_without_pages_is_ignored(self, tmp_path):
        """The shape the PBIP pointer fixtures use: a `.Report` with an empty definition."""
        (tmp_path / "Empty.Report" / "definition").mkdir(parents=True)
        assert find_report_dirs(tmp_path) == []


class TestUsageCounts:
    def test_measures_are_counted_by_placement(self, tmp_path):
        report = _report(
            tmp_path,
            {
                "Overview": [
                    _visual("card", _measure("fact_sales", "Revenue")),
                    _visual("clusteredBarChart", _measure("fact_sales", "Revenue")),
                    _visual("card", _measure("fact_sales", "Margin")),
                ]
            },
        )
        usage = parse_report_folder(report)
        assert usage.fields["fact_sales.Revenue"].visual_count == 2
        assert usage.fields["fact_sales.Margin"].visual_count == 1
        assert usage.fields["fact_sales.Revenue"].is_measure

    def test_slicer_use_is_counted_separately(self, tmp_path):
        """Slicer frequency is what identifies the attributes people filter on."""
        report = _report(
            tmp_path,
            {
                "Overview": [
                    _visual("slicer", _column("dim_customer", "country")),
                    _visual("advancedSlicerVisual", _column("dim_customer", "country")),
                    _visual("tableEx", _column("dim_customer", "country")),
                ]
            },
        )
        usage = parse_report_folder(report)
        country = usage.fields["dim_customer.country"]
        assert country.visual_count == 3
        assert country.slicer_count == 2

    def test_a_field_used_twice_in_one_visual_counts_once(self, tmp_path):
        """A field on both the axis and the sort spec is one use of that field."""
        visual = _visual("clusteredBarChart", _column("dim_customer", "country"))
        visual["visual"]["sort"] = [{"field": _column("dim_customer", "country")}]
        report = _report(tmp_path, {"Overview": [visual]})
        assert parse_report_folder(report).fields["dim_customer.country"].visual_count == 1

    def test_pages_and_types_are_summarised(self, tmp_path):
        report = _report(
            tmp_path,
            {
                "Home": [_visual("card", _measure("f", "M"))],
                "Detail": [
                    _visual("tableEx", _column("d", "c")),
                    _visual("slicer", _column("d", "c")),
                ],
            },
        )
        usage = parse_report_folder(report)
        assert usage.page_count == 2
        assert usage.visual_count == 3
        assert dict(usage.visual_types) == {"card": 1, "tableEx": 1, "slicer": 1}
        assert ("Home", 1) in usage.pages

    def test_an_unreadable_visual_does_not_lose_the_others(self, tmp_path):
        """One broken visual in 2,000 must not cost the operator the other 1,999."""
        report = _report(tmp_path, {"Overview": [_visual("card", _measure("f", "M"))]})
        broken = report / "definition" / "pages" / "page0" / "visuals" / "bad"
        broken.mkdir(parents=True)
        (broken / "visual.json").write_text("{not json", encoding="utf-8")

        usage = parse_report_folder(report)

        assert usage.unparsed_visuals == 1
        assert usage.fields["f.M"].visual_count == 1

    def test_a_visual_with_no_recognisable_field_is_counted_not_dropped(self, tmp_path):
        report = _report(tmp_path, {"Overview": [{"name": "v", "visual": {"visualType": "shape"}}]})
        usage = parse_report_folder(report)
        assert usage.unparsed_visuals == 1
        assert usage.visual_count == 1


class TestRenderedArtifact:
    def test_it_carries_counts_and_no_report_content(self, tmp_path):
        report = _report(
            tmp_path,
            {
                "Executive Overview": [
                    _visual("card", _measure("fact_sales", "Revenue")),
                    _visual("slicer", _column("dim_customer", "country")),
                ]
            },
        )
        rendered = render_report_usage(parse_report_folder(report))
        document = yaml.safe_load(rendered)

        assert document["model_name"] == "Sales"
        assert document["totals"] == {"pages": 1, "visuals": 2, "unparsed_visuals": 0}
        assert document["measures"] == [{"ref": "fact_sales.Revenue", "placed_on_visuals": 1}]
        assert document["fields"] == [
            {"ref": "dim_customer.country", "on_visuals": 1, "on_slicers": 1}
        ]
        # Names and counts only. Asserted on the parsed document, not the raw text: the
        # header comment names the things it refuses to store, so a substring check would
        # match its own explanation.
        body = yaml.dump(document)
        for leaked in ("position", "queryState", "visualType", "Expression", "SourceRef"):
            assert leaked not in body
        assert set(document) == {
            "schema_version",
            "model_name",
            "totals",
            "visual_types",
            "pages",
            "measures",
            "fields",
        }

    def test_measures_are_ranked_by_placement(self, tmp_path):
        report = _report(
            tmp_path,
            {
                "Overview": [
                    _visual("card", _measure("f", "Rare")),
                    _visual("card", _measure("f", "Common")),
                    _visual("card", _measure("f", "Common")),
                ]
            },
        )
        document = yaml.safe_load(render_report_usage(parse_report_folder(report)))
        assert [item["ref"] for item in document["measures"]] == ["f.Common", "f.Rare"]
