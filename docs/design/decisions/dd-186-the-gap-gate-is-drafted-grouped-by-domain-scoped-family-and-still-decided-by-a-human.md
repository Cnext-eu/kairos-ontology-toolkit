# DD-186: The gap gate is drafted, grouped by domain-scoped family, and still decided by a human

**Status:** Accepted
**Date:** 2026-08-17
**Affects:** `draft-gap-decisions` (new), `source-disposition`, `alignment-report`, kairos-design-source
**Implementation:** `core/gap_decisions.py`, `cli/sources.py`, `core/source_disposition.py`

### Context

The DD-169 gate is correct and expensive: on the live hub 1,286 source columns
carry real signal with no canonical home, and none may reach entity binding
undecided. Reviewing 1,286 rows is not review, it is attrition — and attrition is
how a gate stops being read and starts being bypassed.

Three observations make it tractable:

1. Two reason codes were never judgment calls. `operational` (audit/system
   columns) and `vendor-slot` (`Column1`, `Field3`) are already classified
   deterministically by `classify_unmapped` before a human sees them.
2. The remainder collapses by name: the same `OrderNo` in nineteen tables is one
   decision, not nineteen.
3. It collapses again by family: `pickup_location_city`, `pickup_location_country`
   and eighteen siblings are one concept. Measured: 58 families covered 434 of 596
   undecided names.

### Decision

`draft-gap-decisions --auto` records the rule-decidable dispositions and nothing
else. `draft-gap-decisions` drafts everything remaining into `gap-decisions.yaml`
— one entry per family or single name, with occurrence counts, tables, types and
a proposed disposition where a rule applies — for a human to fill in and apply
with `--apply`, which fans one decision out to every column it covers.

**A family is a decision unit, so two constraints follow.** It cannot cross a
domain boundary: a disposition is domain-scoped, and the same column name can be
a modelled fact in one domain and a genuine gap in another. And a shared prefix is
not a shared concept — `is_approved`, `is_external_resource` and
`is_delivery_stop` share a token and are three unrelated booleans, the DD-179 trap
one level up. Structural and temporal prefixes are excluded, and a member must be
a *qualified* form of the token rather than the bare entity.

**`--suggest` adds one model call over the families**, filling `reasoning` and
`proposed_disposition` and flagging families whose members do not belong together.
The split of labour is deliberate: forming families is deterministic (free,
instant, reproducible, and already solved), while naming the concept a family
represents is judgement. The model never fills `decision`.

Nothing writes `blueprint-gap`, `deferred` or `registered-extension` on its own.
`blueprint-gap` in particular asserts *a reference-model defect to file upstream*
— it is not the neutral default, and the prompt says so; on the live corpus the
model proposed it zero times, choosing `deferred` (45) and `registered-extension`
(18) instead.

### Consequences

On the live hub: 224 columns auto-dispositioned, and the remaining 1,286 reduced
to **526 decisions** (63 families + 463 single names) — a 59% reduction, with the
63 families carrying a drafted concept description apiece ("*a supplier/vendor
billing-party snapshot with legal, tax, address and blocking/status
information*").

Building this surfaced a **pre-existing data-loss bug** in `record_disposition`:
its replace filter matched `(system, table)` and ignored the column, so every
column-grain write deleted the table's previously recorded columns. A run
recording 224 dispositions kept 37. The writer now matches the same
`(system, table, column)` grain `load_dispositions` already keyed on. This is the
argument for keeping the drafting deterministic in miniature — a silent
deterministic loss was recoverable by re-running; 596 plausible model judgments
would not have been.

The `--suggest` schema keys on `domain::family` because domain-scoping made the
bare token non-unique — caught by a provider 400 on the first live run.
