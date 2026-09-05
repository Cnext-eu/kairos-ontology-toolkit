# DD-201: A cross-domain class-name collision is resolved by richness, and the resolution travels downstream as a URI

**Status:** Accepted
**Date:** 2026-08-20
**Affects:** `choose_class_copy`, `ALLOWED_SHEET_FLAGS`/`PROPERTY_LESS_ANCHOR_FLAG`, `run_anchor_tables` (`core/anchor_tables.py`); `_process_table`, `TableAlignment.likely_entity_uri` (`core/propose_alignment.py`); `_resolve_alignment_class` (`core/design_landscape.py`)
**Issue:** #564

### Context

`choose_class_copy` hard-partitioned candidate copies of a colliding class
name into tiers — same-domain-owned, then any-domain-owned, then all —
*before* any richness scoring ran. When a name collided across copies owned
by two DIFFERENT domains (a bare IATA `Person` owned only by `party`, a
richer BSP `Person` owned only by `financial`), the hard filter discarded
the richer copy the moment the *other* domain happened to own it — the
domain a table's own catalog-read-order landed on decided the outcome,
never richness. This is the same "read order decides" defect class #519
already fixed one level up (which copy a *single* domain's own duplicate
resolves to); #564 is the sibling case one level further out.

Separately: the newer DD-185/190 global-anchor path already disambiguates
a table's class via `choose_class_copy` and records the resolved
`anchor_uri` in `table-anchors.yaml` — but `propose_alignment.py` never
carried that URI forward into `TableAlignment.likely_entity_uri`, even
though both of `likely_entity_uri`'s existing consumers
(`design_landscape._resolve_alignment_class`, `conformance_evidence.py`)
already prefer it over the bare `ref_class` local name when present. The
uri-anchor-contract's own "confirmed" path populated it; the global-anchor
path silently didn't, so a URI the toolkit had already resolved never
reached the consumers built to use it — producing exactly the "ambiguous
local name, skipped" gaps `design_landscape` reported on real data (12
tables on one hub run).

### Decision

`choose_class_copy` keeps only one tier — owned by *any* domain, over
unowned — ahead of scoring. Same-domain ownership moves from a hard
pre-filter into the last key of the ranking tuple, after column-property
overlap and property count: richness now always gets to compete, and
same-domain ownership only breaks a genuine tie. A deterministic (never
model-proposed) `property-less-anchor` sheet flag is added to a table's
`table-anchors.yaml` entry whenever its resolved anchor has zero
properties — the same condition that already produced a console-only
warning, now surviving into the reviewable artifact.

`_process_table` threads the global-anchor path's resolved `anchor_uri`
through its returned dict (`global_anchor_uri`) whenever that path applied
an override; the table-assembly step populates `likely_entity_uri` from it
when the uri-anchor-contract path didn't already set one. `design_landscape.py`
additionally gains a defensive fallback for hubs whose `*-alignment.yaml`
predates this fix (no `likely_entity_uri` recorded at all): when a
`ref_class` local name is ambiguous, it reads `table-anchors.yaml` directly
and uses that table's own `anchor_uri` — but *only* when the sheet's
`anchor` name matches the alignment's `ref_class` exactly, so a stale or
mismatched sheet entry can never silently substitute a different class
than the one the alignment artifact itself names.

### Consequences

A name collision across two different domains' modules is now resolved the
same way a same-domain collision already was: by richness first, ownership
only as a tie-break. Every future consumer of `likely_entity_uri` benefits
from the global-anchor path's disambiguation, not just the older
uri-anchor-contract path. `design_landscape` can now resolve some
previously-ambiguous `ref_class` entries even against an already-generated,
stale alignment artifact — narrowing, though not eliminating, the
"ambiguous local name, skipped" gap class; a table whose sheet anchor name
doesn't match its alignment's `ref_class` still correctly reports the gap
rather than guessing.
