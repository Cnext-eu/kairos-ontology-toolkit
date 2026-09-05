# DD-182: Per-table vocabulary is a projection of the aggregate, not a second derivation

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `import-source`, source catalog, every downstream stage
**Implementation:** `core/import_source.py` (`split_vocabulary_by_table`)

### Context

`import-source` writes each table's Bronze vocabulary twice: into the source's
aggregate `<system>.vocabulary.ttl` and into `vocabulary/<table>.vocabulary.ttl`.
Both were derived independently from the parsed source schema, and they were
maintained by *different* update paths — the aggregate by an in-place merge that
syncs a fixed list of managed predicates, the per-table files by wholesale
regeneration.

Any enrichment added to the generator but not to the merge's sync list therefore
landed in one and never the other. `formatHint` did exactly that. On the live hub,
38 columns carried it in their per-table file and not in the aggregate.

The consequence was out of all proportion to the cause. The source catalog reads
both files, found the same `SourceTable` IRI with two different signatures, and
reported 75 conflicts — one per table. It could not decide which definition was
authoritative, so it refused to load, and `analyse-sources` aborted. Affinity,
alignment and everything after them were blocked by a missing format annotation.

### Decision

The per-table files are produced by `split_vocabulary_by_table`, which projects
each `bronze:SourceTable` and its columns out of the finished aggregate graph. They
are a view of the aggregate, not a parallel derivation from the schema.

Whatever the aggregate says about a table is, verbatim, what its per-table file
says — so divergence is impossible by construction rather than policed by a sync
list that must be remembered. The split carries no allow-list of its own; it copies
every triple on the table and its columns, which is what keeps a future enrichment
from reintroducing the same defect.

### Consequences

Adding `formatHint` to the merge's sync list would have unblocked the hub in one
line and left the class of bug intact — the next predicate added to one path and
not the other would repeat it. This closes the class.

The existing hub was already divergent, so the fix needed a re-import of all four
sources through the corrected path. Afterwards the catalog loads 75 tables with 0
conflicts.

The guard that caught this stays exactly as strict: a test tampers with a per-table
file and confirms the catalog still reports the conflict. The problem was never that
the guard was wrong — it was that two writers were allowed to disagree.
