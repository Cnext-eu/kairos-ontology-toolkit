# DD-192: Human design rulings are durable, transferable, and outrank model judgment

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `anchor-tables` (prompt + provenance), `integration/discovery/design-rulings.yaml` (new authored input)
**Implementation:** `core/design_rulings.py`, `core/anchor_tables.py`

### Context

The measured blind spot no detector closes: a well-fitting wrong sibling.
`shipments` anchored to `Shipment` maps enough properties to pass every
absolute check while the defensible answers sit one sibling over — three
hand-crafted artifacts gave three different answers. Only a human resolves
this, and before this DD the resolution lived in one conversation: the next
re-run, the next table with the same shape, and the next hub all re-litigated
it. DD-190's `confirmed` status pins one *table*; the ambiguity is a *rule*.

### Decision

`integration/discovery/design-rulings.yaml` is a third authored evidence
input, peer to business discovery and source vocabularies. One entry per
resolution: `kind` (`disambiguation` | `rejection` | `preference`), a `scope`
with `class_pair` and an **`applies_when` condition in data terms**, the
`ruling` target, `rationale`, and `decided_by`.

`anchor-tables` renders the applicable rulings into the global prompt as
accumulated human authority ("these OUTRANK your own reading of the catalog;
apply each ruling wherever its condition matches, and never re-litigate it")
and records `rulings_applied` in the artifact for provenance. Validated live:
the ruled table converged to the ruled answer at 0.91–0.95 with the rejected
candidate kept as alternate, and collateral movement confined to
already-unstable rows — the ruling applies **by condition, not by table
name**, which is what makes it transferable to future tables and hubs.

Three boundaries keep this from becoming a shadow ontology:

1. **Always human-decided.** An entry whose `decided_by` is not `user` is
   inert and reported — a model may propose a ruling, an unconfirmed
   proposal feeds nothing.
2. **A ruling never introduces a class.** A `disambiguation`/`preference`
   whose target the catalog cannot resolve is skipped and reported (it would
   steer the model toward a name post-validation must null). `rejection`
   rulings name a class to avoid and need no resolution.
3. **A ruling never maps columns.** Column-level decisions stay in
   alignment/bindings.

An absent file is a silent no-op. Skipped entries are echoed with reasons,
never dropped silently.

### Consequences

Contested-space resolutions are decided once and never re-litigated — per
table, per run, and (via the condition) per future hub. A disambiguation
ruling that recurs across hubs is a measured candidate for the shared
reference-models pattern library (the #262 harvesting route): the blind spot
becomes the mechanism by which the blueprint itself learns, with recorded,
evidenced rulings instead of anecdote. The `applies_when` conditions are
prose interpreted by the model, not predicates evaluated by code — which is
why `rulings_applied` provenance and the skipped-with-reason echo exist, and
why pattern-library promotion stays a human review, never automatic.
