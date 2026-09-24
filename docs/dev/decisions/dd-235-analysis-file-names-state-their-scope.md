# DD-235: Analysis file names state their scope

**Status:** Accepted
**Date:** 2026-09-24
**Affects:** new `core/analysis_paths.py`; every reader and writer of
`integration/sources/_analysis/` (`analyse_sources`, `anchor_tables`, `propose_alignment`,
`unresolved_anchors`, `gap_decisions`, `alignment_report`, `alignment_closure`,
`design_landscape`, `domain_coverage`, `evidence_loaders`, `source_analysis`,
`conformance_judge`, `conformance_evidence`, `scaffold_binding`, `scaffold_system`,
`fit_report`, `hub_inspection`, `cli/sources.py`); `core/gates.py` (`requires` globs);
`cli/operations.py` (`update` renames); four design/flow skills
**Related:** DD-160 (source affinity), DD-164 (disposition ledger), DD-185 (global
anchoring), DD-186 (gap decisions), #943 (ledger split, which builds on this)

### Context

`integration/sources/_analysis/` is one flat directory holding artifacts keyed three
different ways:

| file | keyed by |
|---|---|
| `tms-affinity.yaml` | a **source system** |
| `booking-alignment.yaml`, `booking-unresolved-anchors.yaml` | an **ontology domain**; an alignment mixes tables from several systems |
| `table-anchors.yaml`, `gap-decisions.yaml`, `affinity-matrix.yaml`, `table-dispositions.yaml` | the **whole hub** |

The name did not say which. `booking-…` could be a source or a domain, and on a hub
whose source systems and domains share vocabulary (a `billing` system feeding a
`billing` domain) there is no way to tell without opening the file. The names were also
not centralised. Twelve readers hard-coded the globs, and seven took the system or domain
from the file name by stripping a suffix, each in its own way.

### Decision

1. **The scope is part of the name:**

   ```
   src-<system>.<kind>.yaml     affinity, table-dispositions
   dom-<domain>.<kind>.yaml     alignment, unresolved-anchors
   hub.<kind>.yaml              table-anchors, gap-decisions, affinity-matrix
   ```

   The directory stays flat. Each kind is still matched by one glob
   (`src-*.affinity.yaml`). The key is read back by stripping a fixed prefix and suffix,
   so system and domain names containing dashes round-trip.

2. **One module owns the names.** `core/analysis_paths.py` builds every path, parses
   every key (`key_of`) and enumerates every kind (`iter_keyed`). No other module globs
   `_analysis/` or strips a suffix.

3. **Writers write the new name; readers accept the old one for one minor release.**
   Where a key exists under both names, the new one wins. A writer removes the old twin
   of the file it has just written, so regeneration never leaves a copy behind for a glob
   to find. This follows the `evidence_loaders` precedent of reading both locations.

4. **`update` renames in place.** It works like the DD-206 `models/custom/` migration:
   - a silent no-op once migrated;
   - `--check` reports only;
   - `git mv`, falling back to a plain move;
   - where both names exist, it reports the pair and changes neither.

5. **The legacy-name notice is logged at info, not warning.** The files are read
   correctly and `update` renames them. A warning on every command, including those whose
   stdout is a JSON document, would be noise about a solved problem.

### Consequences

- The two name families cannot collide. A new name ends `.<kind>.yaml` (a dot before the
  kind) and an old one ends `-<kind>.yaml` (a dash), so neither glob matches the other's
  files. A test pins this.
- `table-dispositions.yaml` is not renamed here. #943 splits it into one
  `src-<system>.table-dispositions.yaml` per system, which is a content change and is
  handled by `source_disposition`.
- The old-name fallback is removed in the release after 5.22. By then every hub that has
  run `update` holds only new names.
- Historical decision records keep the names they were written with.
