# DD-223: Report usage is harvested, and insights are authored evidence

**Status:** Accepted
**Date:** 2026-09-05
**Affects:** new `core/report_usage.py`, new `core/insights.py`, `core/import_tmdl.py`,
`core/conformance_judge.py`, `core/projections/medallion_gold_projector.py`,
`cli/emit_gold.py`, `scaffold/ontology-hub/integration/discovery/bi/README.md`,
`.claude/skills/kairos-design-gold/SKILL.md`, `.claude/skills/kairos-design-source/SKILL.md`,
new `tests/test_report_usage.py`, new `tests/test_insights.py`
**Issue:** #744 (part 3). **Amends DD-147.**

### Context

Two gaps, at opposite ends of the same problem.

`import-tmdl` (DD-147) turns the `.SemanticModel` half of a PBIP export into an
Engineering Pack and a Concept Mapping. It reads nothing from the `.Report` half. On a real
client estate that was 18 exports and roughly 2,000 visual containers of evidence going
straight in the bin — and the report half is where the reporting *patterns* live. A model
inventory says a legacy model defines ninety measures. It cannot say that four of them
appear on visuals and the rest are title and colour helpers, or that one dimension
attribute is filtered on across thirty pages. Placement is the signal; definition is not.

At the other end, a Gold product could be described completely — tables, grains,
relationships, measures — without anything in the hub recording *what anyone wanted to
know*. Report design then started from the data that happened to be modelled instead of
from the decision someone needs to make, which is the wrong end of the problem and the
reason `_blank_report` emits an empty page.

### Decision

**Usage is harvested; insights are authored.** The split is deliberate and follows who can
actually know the answer. A machine can count how often a measure is placed on a visual. Only
a human can say that the operations manager cares about on-time departures by terminal, and
that it must be read against the prior week to mean anything.

**`import-tmdl` writes one `<report>-report-usage.yaml` per report folder with pages**:
measures ranked by placement, fields ranked by slicer use, a visual-type histogram, and page
display names.

DD-147's privacy rule is unchanged and this amends only its inventory of outputs: derived
counts only, never visual definitions, positions, filter values, titles, images, themes or
connection strings — nothing but names already present in the semantic model plus how often
each was used. The archive still expands to a temporary directory, never into the hub.

**Field references are found by walking the JSON, not by a path through `queryState`.** The
PBIR `visualContainer` schema is versioned and unvendored, role names are arbitrary
(`Category`, `Y`, `Values`, whatever a custom visual invents), and a client estate spans
years of Desktop versions. A visual whose JSON cannot be read is counted under
`unreadable_visuals` rather than failing the import: one bad visual out of 2,000 must not
cost the operator the other 1,999. Partial evidence is still evidence. A visual that parses
but projects no field -- a text box, a shape -- is counted separately under
`visuals_without_fields`, because that is expected rather than a parser failure, and
merging the two would make a heavily annotated report look like a broken parse.

**`integration/discovery/bi/insights.yaml` records personas, questions, KPIs, and the
canonical measures and dimensions that answer each.** It sits beside the harvested usage
because the two are read together: usage says which numbers the business already looks at,
insights say which ones it has decided to keep looking at.

**`emit-gold` checks confirmed insights and writes a brief.** Only `confirmed` ones: a
`draft` is a proposal nobody has agreed to — typically what an agent wrote after reading
the usage — and warning about gaps in a machine's guess would train an operator to ignore
the warning. A measure at DD-113 lifecycle `intent` does not count as answering anything,
because it is authored but deliberately not rendered into the model.

**Coverage is a warning, never a gate.** The gap between what the business wants to know
and what the model answers is a backlog, not a build failure. A hub authoring no insights
gets no brief, no warnings and no new artifacts.

**A brief, not a report.** `<product>-insight-brief.md` states which question each measure
answers, for whom, against what comparison, and whether the model can answer it. Page
layout, visual choice and look and feel belong to whoever builds the report — the hub
governs the model. Generating PBIR pages is explicitly not decided here.

### Consequences

A BI engineer, or Fabric Copilot handed the brief, starts from the decision rather than
from the field list. `design-landscape` is untouched: BI evidence remains advisory demand
(DD-147, DD-157), and wiring insight demand into `bi_weight` is left for its own change
rather than smuggled in here.

One latent bug fixed on the way: `conformance_judge.bi_demand_terms` normalised each
measure with `_norm(measure)`, but `import-tmdl` writes measures as
`{name, expression, format_string}` mappings, so the dict was stringified and no measure
name could ever match a concept. The BI demand signal was silently empty for every
worksheet the toolkit itself produced.

Deliberately not decided: generating report pages from insights, a hub-wide theme, and
feeding insight demand back into `design-landscape`.
