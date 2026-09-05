# DD-100: Explicit one-shot migration for retired inventory & projection layouts

**Status:** Accepted
**Date:** 2026-07-21
**Affects:** `core/inventory.py`, `core/claim_projection_sync.py`,
`core/migrate_claims.py`, `core/propose_alignment.py`, `cli/main.py`
**Implementation:** the existing `kairos-ontology migrate` command

### Context

DD-054 introduced namespaced reference-model inventory names, while DD-083 introduced
Claim Registry-managed Turtle blocks. Their transitional runtime behavior still
self-healed old stem-named inventory files and relocated inline controlled Turtle triples
during ordinary reads/sync. That left two live formats, could silently discard ambiguous
collision content, and made routine projection sync a destructive migration path.

### Decision

Retired formats are converted only through the existing `migrate` command. It has an
idempotent `--check`/`--dry-run` plan, validates every input before publication, stages
writes in-place, and retains originals in
`.kairos-migrations/legacy-format-backups/` for rollback. Ambiguous stem collisions,
conflicting canonical files, malformed YAML, malformed managed markers, or Turtle that
cannot be surgically relocated abort the whole format migration without writing.

Canonical inventory readers require model-namespaced reference inventories. Canonical
projection sync requires Claim Registry-controlled imports/includes to be inside one final
managed block; it never converts or drops inline triples. The Claim Registry remains the
only authority for the generated block, while non-managed authored Turtle stays intact.
This supersedes only DD-083's automatic first-sync legacy-conversion clause, not its
managed-block ownership model.

### Consequences

- Existing hubs with retired state receive an actionable migration-required diagnostic
  instead of a best-effort repair. Run `kairos-ontology migrate --hub <hub>` and commit
  the reviewed result before normal inventory generation or claim projection sync.
- Rollback is explicit: restore files from `.kairos-migrations/legacy-format-backups/`
  and use the previous toolkit version if the retired runtime behavior is required.
  Forward correction remains preferred; a second migration run is a no-op.
- Backup creation and staged replacement ensure a failed multi-file conversion restores
  original files rather than leaving a partially migrated hub.
