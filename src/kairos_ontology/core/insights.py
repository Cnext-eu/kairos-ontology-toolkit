# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Personas, business questions and the KPIs that answer them (issue #744).

The toolkit could describe a Gold product completely -- tables, grains, relationships,
measures -- without ever recording *what anyone wanted to know*. Report design then
started from the data that happened to be modelled rather than from the decision someone
needs to make, which is the wrong end of the problem and the reason a generated report is
a blank page.

An insight is one persona's question, the KPI that answers it, and the canonical measures
and dimensions the answer needs. It is authored evidence, not derived: only a human (or an
agent talking to one) can say that the operations manager cares about on-time departures
by terminal. What the toolkit contributes is the check -- does the product actually carry
the measures and columns a confirmed insight names? -- and the brief that hands the answer
to whoever builds the report.

Lives beside the harvested legacy usage under `integration/discovery/bi/` because the two
are read together: usage says which numbers the business already looks at, insights say
which ones it has decided to keep looking at.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

#: Repo-relative location, shared with the harvested TMDL/report evidence (DD-147).
INSIGHTS_RELPATH = Path("integration") / "discovery" / "bi" / "insights.yaml"

#: `draft` is a proposal nobody has agreed to yet -- typically what an agent wrote after
#: reading the legacy usage. Only `confirmed` insights are checked against a product,
#: because failing a build over a machine's guess would be absurd.
_STATUSES = frozenset({"draft", "confirmed"})


class InsightsError(ValueError):
    """The authored insights file cannot be used."""


@dataclass(frozen=True, slots=True)
class Insight:
    """One question a named persona needs answered, and what answers it."""

    id: str
    persona: str
    question: str
    kpi: str
    product: str
    measures: tuple[str, ...]
    dimensions: tuple[str, ...]
    status: str
    comparison: str = ""

    @property
    def confirmed(self) -> bool:
        return self.status == "confirmed"


@dataclass(frozen=True, slots=True)
class InsightSet:
    """Every authored persona and insight in one hub."""

    personas: tuple[tuple[str, str], ...] = ()
    insights: tuple[Insight, ...] = ()

    def for_product(self, product: str) -> tuple[Insight, ...]:
        return tuple(item for item in self.insights if item.product == product)

    def persona_label(self, persona_id: str) -> str:
        return next((desc for pid, desc in self.personas if pid == persona_id), "")


def _string_list(raw: object, *, where: str, key: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise InsightsError(f"{where}: {key!r} must be a list of non-empty strings")
    return tuple(raw)


def parse_insights(document: object) -> InsightSet:
    """Parse the authored insights document, failing closed on a malformed one."""
    if document is None:
        return InsightSet()
    if not isinstance(document, dict):
        raise InsightsError("insights.yaml must be a mapping")

    personas: list[tuple[str, str]] = []
    seen_personas: set[str] = set()
    for entry in document.get("personas") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise InsightsError("each persona needs a string 'id'")
        if entry["id"] in seen_personas:
            raise InsightsError(f"duplicate persona id {entry['id']!r}")
        seen_personas.add(entry["id"])
        description = entry.get("description", "")
        personas.append((entry["id"], description if isinstance(description, str) else ""))

    insights: list[Insight] = []
    seen_ids: set[str] = set()
    for entry in document.get("insights") or []:
        if not isinstance(entry, dict):
            raise InsightsError("each insight must be a mapping")
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise InsightsError("each insight needs a non-empty string 'id'")
        if identifier in seen_ids:
            raise InsightsError(f"duplicate insight id {identifier!r}")
        seen_ids.add(identifier)
        where = f"insight {identifier!r}"
        status = entry.get("status", "draft")
        if status not in _STATUSES:
            raise InsightsError(f"{where}: status must be one of {', '.join(sorted(_STATUSES))}")
        persona = entry.get("persona", "")
        if not isinstance(persona, str):
            raise InsightsError(f"{where}: 'persona' must be a string")
        if persona and seen_personas and persona not in seen_personas:
            raise InsightsError(f"{where}: persona {persona!r} is not declared")
        product = entry.get("product", "")
        if not isinstance(product, str) or not product:
            raise InsightsError(f"{where}: 'product' must name the Gold product it belongs to")
        for key in ("question", "kpi"):
            if not isinstance(entry.get(key, ""), str):
                raise InsightsError(f"{where}: {key!r} must be a string")
        insights.append(
            Insight(
                id=identifier,
                persona=persona,
                question=entry.get("question", ""),
                kpi=entry.get("kpi", ""),
                product=product,
                measures=_string_list(entry.get("measures"), where=where, key="measures"),
                dimensions=_string_list(entry.get("dimensions"), where=where, key="dimensions"),
                status=status,
                comparison=entry.get("comparison", "") or "",
            )
        )
    return InsightSet(personas=tuple(personas), insights=tuple(insights))


def load_insights(hub_root: Path | None) -> InsightSet:
    """Load the hub's authored insights, or an empty set when none are authored."""
    if hub_root is None:
        return InsightSet()
    path = Path(hub_root) / INSIGHTS_RELPATH
    if not path.is_file():
        return InsightSet()
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise InsightsError(f"{path} could not be read ({exc})") from exc
    return parse_insights(document)


@dataclass(frozen=True, slots=True)
class InsightCoverage:
    """What a product does and does not carry for one insight."""

    insight: Insight
    missing_measures: tuple[str, ...]
    missing_dimensions: tuple[str, ...]

    @property
    def covered(self) -> bool:
        return not self.missing_measures and not self.missing_dimensions


def check_coverage(insights: tuple[Insight, ...], spec) -> tuple[InsightCoverage, ...]:
    """Check each insight against an emitted Gold product spec.

    A measure counts only when it is actually *emitted*: a measure still at DD-113
    lifecycle `intent` is authored but deliberately not rendered into the model, so an
    insight depending on it is not yet answerable, which is exactly what the author needs
    to be told.
    """
    emitted = {item.measure_id.casefold() for item in spec.measures if item.emitted}
    columns = {
        f"{table.name}.{column.name}".casefold()
        for table in spec.tables
        for column in table.columns
    }
    if spec.calendar is not None and spec.calendar.approved:
        # `dim_date` is generated rather than shaped from Silver, so its columns are not
        # in `spec.tables`; an insight may legitimately slice by it.
        columns.update({"dim_date.date_key", "dim_date.full_date"})
    results: list[InsightCoverage] = []
    for insight in insights:
        results.append(
            InsightCoverage(
                insight=insight,
                missing_measures=tuple(
                    item for item in insight.measures if item.casefold() not in emitted
                ),
                missing_dimensions=tuple(
                    item for item in insight.dimensions if item.casefold() not in columns
                ),
            )
        )
    return tuple(results)


def render_insight_brief(
    product_name: str,
    insight_set: InsightSet,
    coverage: tuple[InsightCoverage, ...],
) -> str:
    """Render the hand-off document for whoever builds the report.

    Deliberately a brief and not a report: the toolkit governs the model, and page layout,
    visual choice and look and feel belong to the BI engineer (or to Fabric Copilot given
    this document). What the hub can state authoritatively is which question each measure
    answers, for whom, and whether the model can answer it at all.
    """
    lines = [
        f"# {product_name} — insight brief",
        "",
        "Generated from `integration/discovery/bi/insights.yaml` and the emitted Gold",
        "product. Each entry is a question someone needs answered and the governed",
        "measures that answer it.",
        "",
        "This is a brief, not a specification: the hub governs the semantic model, and",
        "page layout and visual design belong to whoever builds the report.",
        "",
    ]
    by_persona: dict[str, list[InsightCoverage]] = {}
    for item in coverage:
        by_persona.setdefault(item.insight.persona or "(unassigned)", []).append(item)

    for persona in sorted(by_persona):
        label = insight_set.persona_label(persona)
        lines.append(f"## {persona}" + (f" — {label}" if label else ""))
        lines.append("")
        for item in sorted(by_persona[persona], key=lambda entry: entry.insight.id):
            insight = item.insight
            status = "✅ covered" if item.covered else "⚠ not answerable yet"
            lines.append(f"### {insight.kpi or insight.id}")
            lines.append("")
            if insight.question:
                lines.append(f"**Question.** {insight.question}")
                lines.append("")
            if insight.comparison:
                # A KPI alone is a number; against a comparison it is information.
                lines.append(f"**Compared against.** {insight.comparison}")
                lines.append("")
            if insight.measures:
                lines.append("**Measures.** " + ", ".join(f"`{item}`" for item in insight.measures))
                lines.append("")
            if insight.dimensions:
                lines.append(
                    "**Sliced by.** " + ", ".join(f"`{item}`" for item in insight.dimensions)
                )
                lines.append("")
            lines.append(f"**Status.** {status} ({insight.status})")
            if item.missing_measures:
                lines.append("")
                lines.append(
                    "Missing measures (author them, or move them past DD-113 `intent`): "
                    + ", ".join(f"`{name}`" for name in item.missing_measures)
                )
            if item.missing_dimensions:
                lines.append("")
                lines.append(
                    "Missing columns: " + ", ".join(f"`{name}`" for name in item.missing_dimensions)
                )
            lines.append("")
    if not coverage:
        lines.append("No insights are authored for this product yet.")
        lines.append("")
    return "\n".join(lines)
