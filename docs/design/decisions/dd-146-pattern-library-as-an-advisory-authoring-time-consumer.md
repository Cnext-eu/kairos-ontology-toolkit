# DD-146: Pattern library as an advisory, authoring-time consumer

**Status:** Accepted
**Date:** 2026-08-10
**Context:** #262 §3 (reference-models lueprints/patterns/ gap)

### Context

kairos-ontology-referencemodels ships a sector-neutral **pattern library** under
`blueprints/patterns/<id>/pattern.yaml` — naming conventions and anti-patterns for
recurring modelling shapes (temporal quartets, qualified role assignments, governed code
lists, deferred relationships). Its README states there is *no toolkit consumer yet*.
Issue #262 §3 proposed surfacing patterns through the `discovery-conformance` flow, with
an Option B that would bundle `patterns:` into archetypes behind a `schema_version: 2`
bump.

### Decision

Patterns are consumed as **advisory, authoring-time craft owned by
`kairos-design-domain`**, not by `discovery-conformance`:

- A lenient, offline, best-effort `core/pattern_loader.py` reads the library
  (`yaml.safe_load` only, never over the network), tolerating the `v0.1`
  markdown-first shape (unknown keys preserved) and **skipping a malformed pattern with a
  warning** rather than raising — advisory surfacing must never break the design loop.
- A top-level `kairos-ontology list-patterns` command emits the library (or one pattern)
  as clean machine output for the skill; it is deliberately **not** a
  `discovery-conformance` subcommand, because patterns bite at property-naming time, not
  during the SME concept interview.
- The `kairos-design-domain` skill consults it when reviewing naming: prefer a matching
  pattern's **normative** `naming_conventions`, reject its `anti_patterns` (citing the
  `id` + `rejection_reason`), and treat structural guidance as advisory per each
  pattern's `normativity` block.

### Rejected alternatives

- **Surface patterns via `discovery-conformance`** — wrong phase; discovery drives concept
  coverage, not property naming. Rejected.
- **Option B: `schema_version: 2` + archetype-bundled `patterns:`** — freezes a per-class
  decision at archetype-authoring time behind a MAJOR breaking bump, premature while the
  library is `v0.1`. Rejected.

### Consequences

- Additive and backward-compatible: a checkout with no `blueprints/patterns/` library is a
  silent no-op.
- The reference-models README's trigger condition ("the toolkit gains a consumer for
  patterns") is now met, so a **follow-up in the reference-models repo** should add
  `blueprints/patterns/_schema/pattern.schema.json` and a structural validation. This is
  out of scope for the toolkit change; the lenient loader does not require it.
- **Finding:** the real `temporal-quartet/pattern.yaml` currently has invalid YAML (a list
  and a mapping key as siblings under `naming_conventions`); the lenient loader skips it
  with a warning, which is exactly why the consumer is lenient — but that most-important
  pattern is unusable until the reference-models repo fixes the file. Tracked on #262.
