# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Harvest *usage* from a legacy Power BI report's PBIR definition (issue #744).

`import-tmdl` already turns the `.SemanticModel` half of a PBIP export into an
Engineering Pack and a Concept Mapping (DD-147). It reads nothing from the `.Report`
half, which is where the reporting patterns actually live: which measures are placed on
visuals rather than merely defined, which attributes people filter on, how pages are
named. A client estate of hand-built reports is the strongest available evidence of what
the business wants to know, and it was being thrown away.

What this reads and what it deliberately does not
-------------------------------------------------
It reads the PBIR JSON tree and derives counts. It stores **no report content**: no visual
JSON, no positions, no filter values, no titles, no images, no theme files, no connection
strings. Only names already present in the semantic model, plus how often each was used,
and page display names. That keeps DD-147's discipline -- the export folder stays
git-ignored, only derived summaries reach the hub -- while making the evidence useful.

Robustness over precision
-------------------------
The PBIR `visualContainer` schema is versioned and unvendored, and a client estate spans
years of Desktop versions. So field references are found by walking the JSON for the
shapes Power BI has always used (`{"Column": {"Expression": {"SourceRef": {"Entity":
...}}, "Property": ...}}`, and its `Measure` and `Aggregation` siblings) rather than by
assuming a fixed path through `queryState`. A visual whose shape yields nothing is counted under
`unreadable_visuals` instead of failing the import: partial evidence is still evidence, and
one unreadable visual out of 2,000 must not cost the operator the other 1,999. A visual that
parses but projects nothing -- a text box, a shape -- is counted separately under
`visuals_without_fields`, because that is expected rather than a parser failure.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

#: Suffix of a Fabric/PBIP report item folder.
REPORT_SUFFIX = ".Report"

#: Any visual whose type contains this is a filter control -- `slicer`,
#: `advancedSlicerVisual`, `textSlicer`. Matched as a substring because the family has
#: grown over the years and a fixed list would silently miss the newest member.
_SLICER_MARKER = "slicer"


@dataclass
class FieldUsage:
    """One `Entity.Property` reference and where it was used."""

    ref: str
    visual_count: int = 0
    slicer_count: int = 0
    is_measure: bool = False


@dataclass
class ReportUsage:
    """Derived usage counts for one report. Carries no report content."""

    name: str
    page_count: int = 0
    visual_count: int = 0
    #: A visual whose JSON could not be read at all. The robustness signal.
    unreadable_visuals: int = 0
    #: A visual that parsed but projects no field -- a text box, shape or image. Expected,
    #: and counted apart from `unreadable_visuals` so a report full of annotations does not
    #: read as a parser failure.
    visuals_without_fields: int = 0
    pages: list[tuple[str, int]] = field(default_factory=list)
    visual_types: Counter = field(default_factory=Counter)
    fields: dict[str, FieldUsage] = field(default_factory=dict)

    def _touch(self, ref: str, *, is_measure: bool, is_slicer: bool) -> None:
        usage = self.fields.setdefault(ref, FieldUsage(ref=ref))
        usage.visual_count += 1
        usage.is_measure = usage.is_measure or is_measure
        if is_slicer:
            usage.slicer_count += 1


def find_report_dirs(base: Path) -> list[Path]:
    """Return every `*.Report` folder under *base* that has a `definition/pages` tree."""
    if not base.is_dir():
        return []
    candidates = [base] if base.name.endswith(REPORT_SUFFIX) else []
    candidates.extend(path for path in base.rglob(f"*{REPORT_SUFFIX}") if path.is_dir())
    return sorted({path for path in candidates if (path / "definition" / "pages").is_dir()})


def _walk_field_refs(node: object, found: list[tuple[str, bool]]) -> None:
    """Collect `(ref, is_measure)` for every field reference anywhere under *node*.

    Recursive rather than path-based on purpose: `queryState` role names are arbitrary
    (`Category`, `Y`, `Values`, `Rows`, a custom visual's own names), and the same field
    shape appears in sort specifications, conditional formatting and drill definitions.
    """
    if isinstance(node, list):
        for item in node:
            _walk_field_refs(item, found)
        return
    if not isinstance(node, dict):
        return
    for kind, is_measure in (("Measure", True), ("Column", False), ("Aggregation", False)):
        spec = node.get(kind)
        if not isinstance(spec, dict):
            continue
        entity = (
            spec.get("Expression", {}).get("SourceRef", {}).get("Entity")
            if isinstance(spec.get("Expression"), dict)
            else None
        )
        prop = spec.get("Property")
        if isinstance(entity, str) and isinstance(prop, str):
            found.append((f"{entity}.{prop}", is_measure))
    for value in node.values():
        _walk_field_refs(value, found)


def _visual_type(visual: dict) -> str:
    inner = visual.get("visual")
    if isinstance(inner, dict) and isinstance(inner.get("visualType"), str):
        return inner["visualType"]
    if isinstance(visual.get("visualType"), str):
        return visual["visualType"]
    # A group or a shape has no visualType; both are layout, not analysis.
    return "" if "visualGroup" not in visual else "visualGroup"


def parse_report_folder(report_dir: Path) -> ReportUsage:
    """Derive usage counts from one `*.Report` folder."""
    usage = ReportUsage(name=report_dir.name.removesuffix(REPORT_SUFFIX))
    pages_dir = report_dir / "definition" / "pages"
    for page_json in sorted(pages_dir.glob("*/page.json")):
        try:
            page = json.loads(page_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Unreadable page definition, skipped: %s", page_json)
            continue
        display = page.get("displayName")
        page_visuals = 0
        for visual_json in sorted(page_json.parent.glob("visuals/*/visual.json")):
            try:
                visual = json.loads(visual_json.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                usage.unreadable_visuals += 1
                continue
            page_visuals += 1
            usage.visual_count += 1
            visual_type = _visual_type(visual)
            usage.visual_types[visual_type or "unknown"] += 1
            is_slicer = _SLICER_MARKER in visual_type.casefold()
            found: list[tuple[str, bool]] = []
            _walk_field_refs(visual, found)
            if not found:
                usage.visuals_without_fields += 1
                continue
            # De-duplicated per visual: a field on both the axis and the sort spec is
            # one use of that field, not two.
            for ref, is_measure in sorted(set(found)):
                usage._touch(ref, is_measure=is_measure, is_slicer=is_slicer)
        usage.page_count += 1
        usage.pages.append(
            (display if isinstance(display, str) else page_json.parent.name, page_visuals)
        )
    return usage


def render_report_usage(usage: ReportUsage, *, source_label: str = "") -> str:
    """Render the derived usage as the YAML artifact written into the hub."""
    measures = sorted(
        (item for item in usage.fields.values() if item.is_measure),
        key=lambda item: (-item.visual_count, item.ref),
    )
    columns = sorted(
        (item for item in usage.fields.values() if not item.is_measure),
        key=lambda item: (-item.slicer_count, -item.visual_count, item.ref),
    )
    document = {
        "schema_version": "1",
        "model_name": usage.name,
        "totals": {
            "pages": usage.page_count,
            "visuals": usage.visual_count,
            "unreadable_visuals": usage.unreadable_visuals,
            "visuals_without_fields": usage.visuals_without_fields,
        },
        "visual_types": dict(usage.visual_types.most_common()),
        "pages": [{"display_name": name, "visuals": count} for name, count in usage.pages],
        "measures": [
            {"ref": item.ref, "placed_on_visuals": item.visual_count} for item in measures
        ],
        "fields": [
            {
                "ref": item.ref,
                "on_visuals": item.visual_count,
                "on_slicers": item.slicer_count,
            }
            for item in columns
        ],
    }
    header = (
        "# Power BI report USAGE evidence (issue #744, DD-147 discipline).\n"
        "#\n"
        "# Derived counts only. No visual definitions, positions, filter values, titles,\n"
        "# images, themes or connection strings are stored here -- only names already\n"
        "# present in the semantic model, and how often each was used.\n"
        "#\n"
        "# This is downstream DEMAND evidence, never business authority. A measure placed\n"
        "# on 40 visuals is strong evidence that someone needs that number; it is not\n"
        "# evidence that the number is currently correct.\n"
        "#\n"
        "# `measures` ranks by how often a measure is actually placed on a visual, which is\n"
        "# the signal a legacy model's measure list cannot give: most models define far\n"
        "# more measures than any report uses. `fields` ranks by slicer use, which is what\n"
        "# identifies the attributes people actually filter on.\n"
    )
    if source_label:
        header += f"# Source: {source_label}\n"
    return header + yaml.dump(document, default_flow_style=False, sort_keys=False, width=100)
