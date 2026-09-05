# DD-191: First-draft bindings are generated from the design sheet and validated before they exist

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `generate-bindings` (new)
**Implementation:** `core/generate_bindings.py`, `cli/sources.py` (`generate-bindings`)

### Context

DD-185 deferred "the binding-draft generator", and the gap shaped the whole
authoring economy: every binding was a hand-authoring session even when the
design sheet (DD-190), the alignment output, and the source profile (DD-189)
already contained every fact the draft needs. Validated on the signal-first
corpus: drafts assembled deterministically from those three artifacts passed
`compile --check` clean on four domains — after exactly two rules were
learned from kernel diagnostics (object properties must not be scalar
fields; property URIs must resolve in the anchor copy's own module).

### Decision

`generate-bindings` assembles one first-draft EntityBinding per anchored,
non-`rejected` sheet row that has a `propose-alignment` result — **zero model
calls**:

- `target.class` = the sheet's `anchor_uri` directly (reuse-first, DD-144;
  no local class is authored here);
- `fields:` from the alignment's scalar property mappings, resolved ONLY in
  the anchor copy's module inventory — an unresolvable property is a
  reported gap, never a cross-module guess; duplicate property claims keep
  the highest-confidence column and report the rest;
- object-property mappings and sheet-relationship columns become
  `technicalFields purpose: relationship` FK carriers (the DD-139 interim
  pattern `propose-relationships` upgrades as parents get bound);
- sheet grain/natural-key columns are materialized `purpose: identity`,
  typed from the profile (or the alignment's SQL type, normalized to the
  closed canonical enum);
- `quality:` tests only where the profile measured them (`unique`/
  `not-null` on the grain);
- every draft is validated through the compiler's own `load_entity_binding`
  **before** writing — an invalid draft is reported and never lands on disk;
- an existing binding is never overwritten without `--force`; review is the
  git diff, per the scaffold-binding convention.

Secondary entities from the sheet are echoed as a worklist (separate
bindings at their own grain), never auto-generated. Everything generation
cannot decide is on the report: unresolved properties, dropped duplicate
claims, skipped tables.

### Consequences

The mechanical majority of bindings becomes generate → review-diff → confirm,
and hand-authoring (kairos-design-mapping) concentrates on what genuinely
needs judgment: merges, survivorship, grain changes, conformance groups.
`scaffold-binding` remains the single-table archetype path; this is the
sheet-driven batch path. The generated draft is deliberately conservative —
`full-refresh`, FK carriers instead of authored joins — so nothing a human
did not confirm ever reaches execution semantics silently.
