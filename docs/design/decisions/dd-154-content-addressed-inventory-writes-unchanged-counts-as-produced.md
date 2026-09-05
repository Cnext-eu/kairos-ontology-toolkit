# DD-154: Content-addressed inventory writes; unchanged counts as produced

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** `write_inventory` and every caller — `generate-inventory`, `init` step 9b
**Implementation:** `src/kairos_ontology/core/inventory.py` (`write_inventory`),
`cli/inspection.py` (`generate_inventory_cmd`), `cli/setup.py` (init step 9b)

### Context

`init --domain` regenerated all 79 reference-model inventories on every run (#419). The envelope is a pure
function of the source TTLs — except `generated_at`, which `resolve_generated_at()` defaults to
`datetime.now()` — so every registration produced a 78-file diff in which *only* the timestamp line changed.
Two consequences: the prescribed `guard-scope --check-since` gate hard-failed on every registration (the
documented 3-glob footprint could never hold), and reviewers faced churn diffs carrying zero information.
`write_inventory` was the single write path and never looked at the existing file.

### Decision

`write_inventory` is content-addressed: it dumps the new envelope to text (same YAML kwargs as before),
reads the existing file text-mode when present, and compares the two after (a) newline normalisation —
a CRLF checkout on Windows (`core.autocrlf`) must compare equal to the LF text `yaml.dump` produces —
and (b) removing the single column-0 `generated_at:` line from both sides (anchored at line start; nested
keys are always indented, so no data line can be swallowed). Equal → no write, no mtime touch, return
`False`; different, missing, or **any** read/decode failure → write and return `True`. A compare failure
must never cause a skip.

Under DD-153, an unchanged file **counts as produced**: the artifact exists and is current, only the write
was elided. `generate-inventory` keeps unchanged files in the produced set (exit-code semantics untouched),
prints `⏭ {stem}: up to date` per file, and its summary separates the counters:
`{writes} generated, {unchanged} unchanged, {failed} failed, {skipped} skipped` — "generated" counts actual
writes only. `init` step 9b prints its existing "Generated N reference-model inventory file(s)" only when
N > 0 actual writes occurred, and an "already up to date" line otherwise.

Expected one-time full rewrites remain by design: after a toolkit upgrade that bumps `INVENTORY_VERSION`
(or otherwise changes envelope content), and after the #414 `generated_from` provenance migration, the next
run legitimately rewrites every inventory once. Run `generate-inventory` once after upgrading, before the
next registration, so that rewrite lands outside a registration diff.

### Rejected alternatives

- **Hash-only compare (`source_sha256`/`closure_hash`).** A toolkit version bump or a provenance-path change
  (`generated_from`, `INVENTORY_VERSION`) alters the envelope without moving `closure_hash` — the stale
  envelope would be skipped forever. Whole-content-minus-timestamp is the only compare that cannot go stale.
- **Report unchanged files as skipped (a `REASON_UNCHANGED` decline).** Any skip entry flips
  `CommandOutcome.has_warnings`, so every idempotent rerun would print `⚠` — a warning for the healthiest
  possible state. Unchanged is a produced artifact, not a declined one.
- **Timestamp pinning (`KAIROS_GENERATED_AT`/`SOURCE_DATE_EPOCH` in the workflow).** Pushes the fix onto
  every caller's environment, and a pinned timestamp makes `generated_at` a lie rather than making the write
  idempotent.

### Consequences

- Re-running `init --domain` or `generate-inventory` over unchanged sources produces a zero-file diff; the
  documented 3-glob `guard-scope` footprint for domain registration becomes true.
- `generated_at` in a committed inventory now means "when the content last changed", not "when the command
  last ran".
- mtimes of unchanged inventories no longer advance; nothing in the toolkit uses mtime freshness (DD-047
  chose content hashes), so this is observable only to external tooling.
