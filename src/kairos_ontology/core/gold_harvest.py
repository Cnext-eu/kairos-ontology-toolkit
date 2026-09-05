# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Bring Power BI Desktop and Fabric edits back into authored hub inputs (issue #744).

A BI engineer opens the generated PBIP, hides a column, adds three measures, renames a
field — and the next `emit-gold` overwrites all of it. The engineer's only defences were
to stop editing or to stop re-emitting, and both defeat the point of generating the model.

The rule this implements is that **Desktop is a proposal tool and the hub stays the source
of truth** (DD-206 §8). Rather than merging edits into the emitted artifacts, or carrying
an overlay file that quietly diverges from what anyone authored, this reads the edited
model, diffs it against a fresh in-memory emit, and writes two things a human reviews:

* a Markdown report of everything that changed, including what cannot be harvested, and
* a Turtle snippet of the changes that *do* have authoring vocabulary, ready to paste into
  the owning domain's Gold extension.

Nothing is written into `model/extensions/`. Auto-merging an edit into authored input
would make the hub's own inputs a downstream artifact of a report, which is exactly the
ownership inversion the whole design avoids.

Matching
--------
Tables match on the `Kairos_SilverBinding` annotation the emitter already writes, falling
back to `lineageTag`. Columns and measures match on `lineageTag`, which Desktop preserves
across a rename — so a renamed column is reported as a rename rather than as one deletion
and one addition. A measure with no `Kairos_Lifecycle` annotation was not emitted by the
hub, so it is new: that is how a hand-added measure is told from a governed one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .tmdl_parser import TmdlModel, TmdlTable, parse_model_folder

#: Where the review artifacts land. Alongside the other planning documents a human reads
#: before deciding, never inside `model/extensions/`.
HARVEST_RELDIR = Path("model") / "planning" / "gold-harvest"

_KAIROS_LIFECYCLE = "Kairos_Lifecycle"
_KAIROS_SILVER_BINDING = "Kairos_SilverBinding"

#: Desktop re-indents and re-wraps DAX, and writes multi-line expressions inside triple
#: backticks. Comparing raw text would report every governed measure as changed.
_FENCE = re.compile(r"^```|```$", re.MULTILINE)

#: Desktop pads brackets and commas; the hub does not.
_PUNCTUATION_SPACING = re.compile(r"\s*([(),\[\]])\s*")


@dataclass
class MeasureChange:
    """One measure a report author added or altered in Desktop."""

    name: str
    table: str
    expression: str
    description: str = ""
    format_string: str = ""
    display_folder: str = ""
    is_new: bool = True
    changed_fields: tuple[str, ...] = ()


@dataclass
class HarvestResult:
    """Everything the diff found, grouped by what can be done about it."""

    product: str
    new_measures: list[MeasureChange] = field(default_factory=list)
    changed_measures: list[MeasureChange] = field(default_factory=list)
    hidden_columns: list[tuple[str, str]] = field(default_factory=list)
    shown_columns: list[tuple[str, str]] = field(default_factory=list)
    renamed_columns: list[tuple[str, str, str]] = field(default_factory=list)
    unmatched_tables: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (
            self.new_measures
            or self.changed_measures
            or self.hidden_columns
            or self.shown_columns
            or self.renamed_columns
        )


def normalize_dax(expression: str) -> str:
    """Collapse formatting differences Desktop introduces but nobody authored.

    Whitespace runs become single spaces, then spacing around brackets and commas is
    removed -- Desktop writes `COUNTROWS( 'x' )` where the hub wrote `COUNTROWS('x')`.
    Spacing elsewhere is preserved, so `VAR a = 1` never collapses into `VARa=1` and two
    genuinely different expressions cannot compare equal.
    """
    text = " ".join(_FENCE.sub("", expression).split())
    return _PUNCTUATION_SPACING.sub(r"\1", text)


def _tables_by_key(model: TmdlModel) -> dict[str, TmdlTable]:
    keyed: dict[str, TmdlTable] = {}
    for table in model.tables:
        binding = table.annotations.get(_KAIROS_SILVER_BINDING)
        keyed[f"binding:{binding}" if binding else f"tag:{table.lineage_tag or table.name}"] = table
        keyed.setdefault(f"name:{table.name}", table)
    return keyed


def diff_models(emitted: TmdlModel, edited: TmdlModel, *, product: str) -> HarvestResult:
    """Diff an edited semantic model against the model the hub would emit now."""
    result = HarvestResult(product=product)
    emitted_tables = _tables_by_key(emitted)

    for table in edited.tables:
        binding = table.annotations.get(_KAIROS_SILVER_BINDING)
        original = (
            emitted_tables.get(f"binding:{binding}")
            if binding
            else emitted_tables.get(f"tag:{table.lineage_tag}")
        ) or emitted_tables.get(f"name:{table.name}")
        if original is None:
            # A table the hub never emitted -- typically a Desktop calculated table. It
            # has no Silver binding, so there is nothing in the hub to author it as.
            result.unmatched_tables.append(table.name)
            continue

        original_columns = {
            column.lineage_tag: column for column in original.columns if column.lineage_tag
        }
        original_by_name = {column.name: column for column in original.columns}
        for column in table.columns:
            source = original_columns.get(column.lineage_tag) or original_by_name.get(column.name)
            if source is None:
                continue
            if source.name != column.name:
                result.renamed_columns.append((original.name, source.name, column.name))
            if column.is_hidden and not source.is_hidden:
                result.hidden_columns.append((original.name, source.name))
            elif source.is_hidden and not column.is_hidden:
                result.shown_columns.append((original.name, source.name))

        original_measures = {measure.name: measure for measure in original.measures}
        for measure in table.measures:
            governed = _KAIROS_LIFECYCLE in measure.annotations
            source = original_measures.get(measure.name)
            change = MeasureChange(
                name=measure.name,
                table=original.name,
                expression=measure.expression,
                description=measure.description,
                format_string=measure.format_string,
                display_folder=measure.display_folder,
            )
            if source is None and not governed:
                result.new_measures.append(change)
                continue
            if source is None:
                # Governed by annotation but absent from the current emit: the hub's own
                # authoring changed since this model was deployed. Report as new so the
                # author decides, rather than guessing which side is stale.
                result.new_measures.append(change)
                continue
            changed = [
                name
                for name, before, after in (
                    (
                        "expression",
                        normalize_dax(source.expression),
                        normalize_dax(measure.expression),
                    ),
                    ("formatString", source.format_string, measure.format_string),
                    ("displayFolder", source.display_folder, measure.display_folder),
                    ("description", source.description, measure.description),
                )
                if after and before != after
            ]
            if changed:
                change.is_new = False
                change.changed_fields = tuple(changed)
                result.changed_measures.append(change)
    return result


def _turtle_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def render_proposal(result: HarvestResult, *, domain_of_table: dict[str, str]) -> str:
    """Render the Turtle a human merges into the owning domain's Gold extension.

    Grouped by owning domain, because a multi-domain product's tables are authored in
    several extension files and pasting a `dim_customer` measure into the fact's domain
    would not compile.
    """
    lines = [
        "# Proposed authoring, harvested from an edited semantic model (#744).",
        "#",
        "# NOT applied automatically. Review each item, then paste it into the owning",
        "# domain's model/extensions/<domain>-gold-ext.ttl and re-emit. Measures arrive at",
        "# DD-113 lifecycle 'provisional': they are authored but not yet validated, and",
        "# `measureDefinition` needs a real business definition before that changes.",
        "",
        "@prefix kairos-ext: <https://kairos.cnext.eu/ext#> .",
        "",
    ]
    by_domain: dict[str, list[str]] = {}

    for change in result.new_measures:
        domain = domain_of_table.get(change.table, "")
        # A `///` doc comment in the edited model is the author's own description, and
        # is a far better starting definition than a placeholder. Only fall back to the
        # TODO when the measure carries none.
        definition = (
            _turtle_literal(change.description)
            if change.description
            else "TODO: what does this number mean to the business?"
        )
        body = [
            f"<urn:kairos:harvested:measure:{_slug(change.name)}> a kairos-ext:Measure ;",
            f'  kairos-ext:measureId "{_turtle_literal(change.name)}" ;',
            f'  kairos-ext:measureDefinition "{definition}" ;',
            f'  kairos-ext:measureExpression "{_turtle_literal(change.expression)}" ;',
            '  kairos-ext:measureLifecycleState "provisional" ;',
        ]
        if change.format_string:
            body.append(
                f'  kairos-ext:measureFormatString "{_turtle_literal(change.format_string)}" ;'
            )
        if change.display_folder:
            body.append(f'  kairos-ext:measureFolder "{_turtle_literal(change.display_folder)}" ;')
        # TMDL carries no result type, so this is a guess the author must confirm --
        # DD-113 requires a real one before the measure can leave `provisional`.
        body.append('  kairos-ext:measureDataType "decimal" .  # CHECK: guessed')
        body.append("")
        by_domain.setdefault(domain, []).extend(body)

    for table, column in result.hidden_columns:
        domain = domain_of_table.get(table, "")
        by_domain.setdefault(domain, []).append(
            f'# on the owl:Ontology resource: kairos-ext:goldHideColumn "{table}.{column}" ;'
        )

    for domain in sorted(by_domain):
        lines.append(f"# ---- {domain or 'unknown domain'} ----")
        lines.extend(by_domain[domain])
        lines.append("")
    if not by_domain:
        lines.append("# Nothing harvestable was found.")
        lines.append("")
    return "\n".join(lines)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-") or "measure"


def render_report(result: HarvestResult) -> str:
    """Render the human-readable diff, including what cannot be harvested."""
    lines = [
        f"# {result.product} — harvested Desktop edits",
        "",
        "Compared an edited semantic model against what this hub would emit now.",
        "Nothing here has been applied: review, then merge the companion `-proposal.ttl`",
        "into the owning domain's Gold extension and re-emit.",
        "",
    ]
    if result.empty and not result.unmatched_tables:
        lines.append("No differences found. The deployed model matches the hub.")
        lines.append("")
        return "\n".join(lines)

    if result.new_measures:
        lines.append("## New measures")
        lines.append("")
        for change in result.new_measures:
            lines.append(f"- `{change.name}` on `{change.table}`")
        lines.append("")
    if result.changed_measures:
        lines.append("## Changed measures")
        lines.append("")
        for change in result.changed_measures:
            lines.append(
                f"- `{change.name}` on `{change.table}` ({', '.join(change.changed_fields)} differ)"
            )
        lines.append("")
    if result.hidden_columns:
        lines.append("## Columns hidden in Desktop")
        lines.append("")
        lines.append("Author these as `kairos-ext:goldHideColumn` values.")
        lines.append("")
        for table, column in result.hidden_columns:
            lines.append(f"- `{table}.{column}`")
        lines.append("")
    if result.shown_columns:
        lines.append("## Columns un-hidden in Desktop")
        lines.append("")
        lines.append(
            "The hub hides these by their Silver column role (DD-221). If a report author "
            "needs one visible, that is a signal the role is wrong, or that the column "
            "belongs in the model as business data — worth a conversation, not an "
            "annotation."
        )
        lines.append("")
        for table, column in result.shown_columns:
            lines.append(f"- `{table}.{column}`")
        lines.append("")

    unharvestable = []
    if result.renamed_columns:
        unharvestable.append(
            "**Renamed columns.** The hub names columns after the Silver identifier, and "
            "every authored DAX expression and `measureColumnDependency` references that "
            "name. Renaming is a modelling decision, not a presentation one: change the "
            "property's label in the ontology, or raise it as a change request."
        )
        for table, before, after in result.renamed_columns:
            unharvestable.append(f"  - `{table}`: `{before}` → `{after}`")
    if result.unmatched_tables:
        unharvestable.append(
            "**Tables the hub does not emit.** Typically Desktop calculated tables. They "
            "have no Silver binding, so there is nothing in the hub to author them as — "
            "model the underlying data, or keep them in a downstream composite model."
        )
        for name in result.unmatched_tables:
            unharvestable.append(f"  - `{name}`")
    unharvestable.append(
        "**Pages, visuals, bookmarks and themes.** Report design belongs to the BI "
        "engineer and lives in a report item of its own, not in the generated "
        "`<Product>.Report` stub, which every release republishes."
    )
    lines.append("## Not harvestable")
    lines.append("")
    lines.extend(unharvestable)
    lines.append("")
    return "\n".join(lines)


def load_edited_model(path: Path) -> TmdlModel:
    """Load an edited semantic model from a `definition/`, `.SemanticModel` or export."""
    from .import_tmdl import find_definition_dirs

    if (path / "model.tmdl").is_file():
        return parse_model_folder(path)
    definition_dirs = find_definition_dirs(path)
    if not definition_dirs:
        raise FileNotFoundError(
            f"no SemanticModel definition/ found under {path} — point --from at the "
            "exported PBIP folder, the .SemanticModel folder, or its definition/ folder"
        )
    return parse_model_folder(definition_dirs[0])
