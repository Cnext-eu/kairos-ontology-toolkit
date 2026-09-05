# DD-190: The anchors artifact is a reviewable design sheet with sticky human decisions

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `anchor-tables` (prompt, schema, artifact v2), `propose-alignment` (anchor application)
**Implementation:** `core/anchor_tables.py`, `core/propose_alignment.py` (`resolve_global_anchor`)

### Context

The global anchor call (DD-185) already decides the whole design skeleton's
hardest question — what each table IS — but returned only the anchor half.
Relationships, embedded secondary entities, and extension flags were
re-derived later, stage by stage, from partial views. And nothing an operator
decided survived a re-run: every `anchor-tables` invocation re-litigated
every table, so a human correction lasted exactly one pipeline pass.
Validated on the signal-first experiment corpus (runs 1–9): the same global
call also returns relationships at 0.95 recall against hand-authored FK sets,
id-keyed secondary entities, and 6/6 correct extension-candidate flags on
catalog-gap tables — and a sticky-status sheet converged to the human-ruled
answer on every contested table with collateral movement confined to
known-unstable rows.

### Decision

`table-anchors.yaml` (schema_version 2) grows into the **design sheet**:

1. **Three new per-table model outputs**, each validated deterministically
   after the call — the model proposes, the estate/catalog decide what is
   representable: `relationships` (`to_table` must exist in the estate and
   differ from the table itself; `local_column` must be a real column),
   `secondary_entities` (class must resolve in the catalog; grain must
   DIFFER from the primary grain — a same-grain cluster is properties of the
   primary, dropped and counted), and `flags` (closed set:
   `unowned-anchor`, `extension-candidate`, `code-list`, `no-data-evidence`,
   `versioned`). Every drop is counted and echoed, never silent.
2. **Sticky review statuses.** Entries carry `status` (`proposed` machine;
   `confirmed`/`edited` human — both pin; `rejected` re-anchors) and a
   `schema_hash` of the sorted raw column names. A pinned entry with an
   unchanged hash is preserved verbatim and **excluded from the model call**
   (true delta mode — re-runs cost only the unpinned tables). A pinned entry
   whose hash changed releases its pin to `stale-confirmed`: the fresh
   proposal is recorded, the human's values are kept under `previous` (or as
   the entry itself when the re-proposal is unanchored), and the row
   re-enters review. Stickiness is bounded by evidence identity — never by
   table name alone.
3. **A human decision is not a model score.** `propose-alignment` applies a
   `confirmed`/`edited` sheet anchor without the DD-185 confidence floor
   (`resolve_global_anchor`, status `sheet-confirmed`). An out-of-pool anchor
   is still never applied, human-confirmed or not: alignment has no
   properties to offer for a class outside the domain pool, and forcing it
   would produce exactly the plausible-empty mapping DD-159 exists to
   prevent.

### Consequences

One call now yields the full design skeleton — anchor, grain, identity,
relationships, secondary entities, flags — and review effort concentrates
where it belongs: an operator confirms rows once, and re-runs stop asking.
`fk?` profile evidence (DD-189) feeds the relationship output directly.
Secondary entities give binding generation its multi-entity worklist without
a separate discovery pass. The `previous` block on `stale-confirmed` entries
means a human decision can be superseded by schema drift but never silently
lost. Consumers of the v1 artifact are unaffected: all new fields are
additive, and entries without `status` behave exactly as before.
