# DD-193: The profiling class catalog is scoped to the resolved accelerator

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `read_reference_terms` (new `module_scope` parameter), `build_class_catalog`
**Implementation:** `core/class_anchoring.py`, `core/anchor_tables.py`
**Issue:** #558

### Context

`read_reference_terms` seeded the anchoring class catalog from every module
URI the whole installed `kairos-ontology-referencemodels` package maps in the
catalog — not the modules the active accelerator pack actually declares. On a
logistics profiling run this put ~400 FIBO classes (`Contract`,
`LegalEntity`, `Organization`, …) in front of the model as `UNOWNED` anchor
candidates, alongside OMG Commons/LCC and every other vendor's models,
regardless of whether any logistics domain has ever imported them. Beyond
prompt bloat, the anchoring prompt's own fallback rule ("pick an UNOWNED
class only when no owned class fits") means a genuinely unrelated vendor
class could win a table that should have been flagged for review instead.

### Decision

`read_reference_terms` gains an optional `module_scope` parameter: when
given, only modules in the scope seed the walk. Each seed's own
`owl:imports` closure still resolves in full through the canonical loader
(unchanged) — scoping narrows *which modules seed the walk*, not how far one
seed's closure reaches, so a foundation module reached only via import from
an accelerator-declared module stays visible. `None` (the default) keeps
today's unrestricted behaviour; every existing caller (`alignment_report`,
`domain_coverage`, `ontology_integrity`, DD-165's local-class suggestion) is
unaffected.

`build_class_catalog` is the one caller that opts in: when an accelerator
resolves, the seed set is exactly the union of that accelerator's own
declared domain imports (`load_data_domains`'s `uris`) — the same set the
function already computes for ownership marks. A module the accelerator
never reaches, directly or transitively, is excluded from the catalog
outright rather than merely marked `UNOWNED`. An accelerator name that fails
to resolve (`load_data_domains` returns nothing) keeps the unrestricted
legacy behaviour rather than silently emptying the catalog — a scoping bug
must never look like "the accelerator has zero classes."

### Consequences

A module reachable only via a *different* accelerator's own domain (FIBO for
a future `financial-services` pack) is now invisible to a logistics
profiling run, which is the fix working as intended. The corollary the issue
also names: a module reachable **only** by explicit import from within the
accelerator's own package (IATA `onerecord.iata.org/ns/code-lists`, not
today transitively imported by the accelerator's declared `.../ns/cargo`
module) becomes invisible too, until that package adds the import — a data
change in the separate `kairos-ontology-referencemodels` repository, out of
this repository's scope, tracked on #558. Until it lands, code-list classes
like `ChargeCode`/`CurrencyCode` will not appear as anchor candidates for
logistics hubs; this is the honest state (a real accelerator gap, surfaced),
not a regression the scoping fix should paper over.

Also out of scope here, and left to the issue for a follow-up decision: a
`kairos.yaml` field making the accelerator a hub-level declared setting
rather than resolved from `pyproject.toml`/CLI/inference. That is a new
config-surface question, not a scoping bug, and wants its own decision.
