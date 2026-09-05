# DD-189: Sources are profiled deterministically before any model call

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `profile-sources` (new), `anchor-tables` (consumption), `kairos.yaml` (`data_maturity`)
**Implementation:** `core/profile_sources.py`, `cli/sources.py` (`profile-sources`), `core/anchor_tables.py` (outline annotation)

### Context

Anchoring and grain decisions leaned on column names and declared types — the
weakest evidence class. Measured on the qargo corpus (signal-first validation,
2026-08-19, experiment branch `experiment/signal-first-two-pass`): with
deterministic profile tags in the anchoring outline the model reproduced the
hand-confirmed grain on 9/9 golden tables; without them it keyed **every**
table on the SaaS tenant discriminator (0/9) — the same live DD-185 failure
that previously required a hand-maintained disposition-ledger exclusion.
Separately, 204 always-empty columns (~12% of the estate) and 178 constant
columns were feeding model context as pure name-bait, and two tables with no
sample evidence participated in semantic analysis indistinguishably from
populated ones.

### Decision

A new deterministic, LLM-free stage profiles raw `.import/` extracts
(Parquet/CSV) per system and writes `integration/sources/<system>/
<system>.profile.yaml`: per-column null/empty ratio (blank strings count),
cardinality (`unique` / `const` / `low-card(n)`), value shape (`id-like`,
`code-like`, `date-like`, `measure-like`, `free-text`, `json`), sampled
cross-table inclusion (`fk?->table.col` against proven-unique columns), and
table tags (`empty-table`, `versioned?`, `code-list?`). **Statistics only —
no data value is ever written**, which also means profile signal may reach a
model even where raw values must not.

Every artifact records its evidence **basis** (`import-extract(full)` now; a
later dataplatform re-profile writes `platform` and diffs as a release
verification gate — two-phase per the signal-first proposal §4.4).

`anchor-tables` consumes the profile automatically when present: outline
columns gain `[tag,…]` annotations plus a legend, and always-empty columns are
omitted from model context — **only** when the profile was computed under a
declared `data_maturity: production` (`kairos.yaml`, overridable per run).
Under `test`/unspecified maturity every tag is advisory and nothing is
excluded: absence of data in a test extract is not evidence of absence of
meaning. Exclusions are never silent — the artifact carries the counts and
consumers echo them. The annotated outline feeds the prompt only; anchor
resolution (`column_property_overlap`, copy choice) keeps raw column names so
tag text cannot pollute word matching.

### Consequences

Grain quality stops depending on a manually maintained tenant-discriminator
exclusion: `const`/`low-card` detection finds that column class from the data.
The `fk?` inclusion tags are new deterministic join evidence available to
relationship proposal (a tier-2 matcher where name equality fails — measured:
`goods.consignment_id ⊆ consignments.consignment_id` was known to profiling
while the name matcher returned `<CONFIRM_JOIN_COLUMN>`). Systems without a
profile are untouched — the stage is additive, not a new gate. Unsupported
extract types are listed as `not_profiled`, never silently skipped.

Full validation evidence: `experiments/signal-first/README.md` runs 1–9 on
the experiment branch (ablation, kernel-compile verification, convergence).
