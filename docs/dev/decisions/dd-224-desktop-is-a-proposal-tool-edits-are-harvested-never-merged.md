# DD-224: Desktop is a proposal tool; edits are harvested, never merged

**Status:** Accepted
**Date:** 2026-09-06
**Affects:** new `core/gold_harvest.py`, `core/tmdl_parser.py`, `cli/emit_gold.py`
(`harvest-gold`), `cli/main.py`, `.claude/skills/kairos-design-gold/SKILL.md`,
new `tests/test_gold_harvest.py`
**Issue:** #744 (part 5)

### Context

A BI engineer opens the generated PBIP, hides a column, adds three measures, renames a
field — and the next `emit-gold` overwrites all of it. `emit_artifacts` removes every file
its manifest owns before writing, so a hand edit inside the owned tree is either silently
replaced or blocks the emit outright.

The engineer's only two defences were to stop editing or to stop re-emitting. Both defeat
the point of generating the model: the first makes the toolkit an obstacle to the people it
serves, the second makes the hub stop being the source of truth in practice while still
claiming to be one in principle.

### Decision

**Desktop is a proposal tool. The hub stays the source of truth** (DD-206 §8). Edits are
read back, diffed, and *proposed* as authoring — never merged into emitted artifacts, and
never written into `model/extensions/`.

`harvest-gold <product> --from <exported model>` regenerates the product in memory, diffs
the edited model against it, and writes two documents under `model/planning/gold-harvest/`:
a Markdown report of everything that changed, and a Turtle snippet of the changes that have
authoring vocabulary, grouped by owning domain because a multi-domain product's tables are
authored across several extension files.

**Nothing is applied automatically.** Two alternatives were rejected:

- *An overlay file the emitter merges and never overwrites* is simple, but it invites drift
  and hides authorship: the model's behaviour would depend on a file nobody reviewed
  alongside the ontology, and the hub could no longer answer "why is this measure here?"
  from its authored inputs alone.
- *Auto-merging into the Gold extension* would make the hub's authored inputs a downstream
  artifact of a report. That is precisely the ownership inversion the design exists to
  prevent, and it would let a Desktop session silently change what a domain means.

**Matching uses what the emitter already writes.** Tables match on the
`Kairos_SilverBinding` annotation, falling back to `lineageTag`. Columns and measures match
on `lineageTag`, which Desktop preserves across a rename — so a rename is reported as a
rename rather than as one deletion and one addition. A measure carrying no
`Kairos_Lifecycle` annotation was not emitted by the hub, which is how a hand-added measure
is told from a governed one. No heuristics, no name matching except as a last resort.

**DAX is compared after normalisation.** Desktop re-indents, pads brackets and wraps
multi-line expressions in triple backticks. Comparing raw text would report every governed
measure as changed on the first harvest and train the operator to ignore the report.
Normalisation collapses whitespace runs and spacing around brackets and commas only —
`VAR a = 1` never becomes `VARa=1`, so two genuinely different expressions cannot compare
equal.

**Some edits are reported as un-harvestable, on purpose.** A renamed column is not
proposed: the hub names columns after the Silver identifier, and every authored DAX
expression and `measureColumnDependency` references that name, so renaming is a modelling
decision. A column *un-hidden* in Desktop is not proposed either — the hub hides by Silver
column role (DD-221), so a report author needing one visible is evidence that the role is
wrong or the column is really business data, which is a conversation rather than an
annotation. Pages, visuals, bookmarks and themes are listed as belonging to the BI
engineer's own report item.

### Consequences

The loop closes and converges: emit, edit in Desktop, harvest, review, merge, re-emit — and
a second harvest of the re-emitted model reports no differences. Desktop becomes a usable
authoring surface without the hub giving up ownership of the model.

This required teaching `core/tmdl_parser.py` to read what it had always skipped: bare
`isKey` and `isHidden` flags (written with no value, invisible to a `key: value` reader),
`annotation X = "..."` lines (no colon, skipped entirely), `///` doc comments (which is how
TMDL actually carries a description), and `lineageTag` on measures. An `annotation`
following a multi-line measure was also being swallowed into the DAX expression. Those gaps
made a round trip impossible, and fixing them benefits `import-tmdl` too.

Harvested measures arrive at `provisional` with the author's own `///` description as the
starting `measureDefinition` and a guessed `measureDataType` marked `CHECK`: TMDL carries
no result type, and DD-113 requires a real one before a measure leaves `provisional`.

Deliberately not decided: harvesting relationships, perspectives, calculation groups or RLS
role membership; and the Tabular Editor best-practice rules the issue also proposes.
