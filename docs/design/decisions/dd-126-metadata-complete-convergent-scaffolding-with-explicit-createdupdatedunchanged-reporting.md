# DD-126: Metadata-Complete, Convergent Scaffolding with Explicit Created/Updated/Unchanged Reporting

**Status:** Accepted
**Date:** 2026-08-02
**Affects:** `core/claim_projection_sync.py`, `core/managed_text_block.py` (new),
`cli/main.py` (`claims-to-silver-ext`)
**Implementation:** `scaffold_missing_surfaces`, `ScaffoldSurfacesResult`,
`ScaffoldPartialFailureError`, `_validate_generated_metadata`,
`_sync_master_registration`, `_sync_readme_domain_table`,
`managed_text_block.split_managed_block` / `compose_managed_file` / `replace_managed_block`

### Context

DD-072 (`claims-to-silver-ext` bootstraps fresh domains) only ever wrote a bare
`rdf:type owl:Ontology` plus `rdfs:label` into a scaffolded `{domain}.ttl`, and an
even sparser `owl:Ontology` triple into `{domain}-silver-ext.ttl` — missing the
`rdfs:comment` and `owl:versionInfo` that `kairos-execute-validate`'s Level 3 checks
(and every hand-authored ontology) require, so a freshly scaffolded domain could
fail the same metadata gate a hand-authored one passes. The workflow also silently
left `_master.ttl`'s `owl:imports` registration and the scaffold README's "Domain
model overview" table unregistered for newly scaffolded domains, requiring a manual
follow-up step (documented in `kairos-help`'s "Adding a new domain" workflow) that
was easy to forget. Finally, the command reported success or failure only via exit
code and per-domain sync status — there was no explicit accounting of which paths
were created, updated, or left untouched, no git-status guidance for the new
untracked files, and no defined behavior (nor test coverage) for what happens when
one domain among several fails to scaffold.

### Decision

`_scaffold_ontology_skeleton` / `_scaffold_extension_skeleton` now emit
`rdfs:label`, `rdfs:comment`, `owl:versionInfo`, and correct `:`/`owl:`/`rdfs:`
(and `kairos-ext:` for extensions) prefix bindings, and every generated candidate
graph is validated by `_validate_generated_metadata` (required predicates present,
`https://` IRI, Turtle round-trip) **before** anything is written to disk — a
generated skeleton is held to the identical metadata bar as a hand-authored one.
Domain identifiers are validated against `_DOMAIN_SLUG_RE` up front.

`scaffold_missing_surfaces` now returns a frozen `ScaffoldSurfacesResult`
(`created` / `updated` / `unchanged` / `warnings` / `errors` path/str tuples, a
`.counts` property, and a `.describe()` method producing human-readable summary
lines: per-path buckets, a managed-vs-authored explanation, and a `git status`
hint for newly created — hence untracked — files). Each domain is scaffolded
independently inside a try/except: an invalid slug or a failed metadata check is
recorded in `errors` for that domain only and does **not** stop the others, nor
does it undo files already written for domains that succeeded — no rollback is
ever attempted or claimed. If any domain failed, `scaffold_missing_surfaces`
raises `ScaffoldPartialFailureError(message, result)` (mirroring the existing
`OntologyLoadError(message, result)` convention in `ontology_loader.py`) carrying
the full partial `ScaffoldSurfacesResult` so callers can report exactly what
happened.

After the per-domain loop, two best-effort convergence steps run for every
currently-ready domain (freshly scaffolded or pre-existing): `_sync_master_registration`
regenerates a new, generic sentinel-delimited managed block
(`# >>> kairos-managed (generated domain registration — do not edit)` /
`# <<< kairos-managed` — deliberately distinct marker text from the existing
Claim-Registry managed block so the two never collide) inside `_master.ttl`'s
`owl:imports`, and `_sync_readme_domain_table` inserts a row into the README's
"Domain model overview" table for any domain missing one, removing the sole
`*(add domains here)*` placeholder row on first real insertion. Both steps are
**convergence-only**: neither file is ever created by this workflow, only updated
if it already exists (a missing `_master.ttl` or README table is skipped with a
warning, not an error), and all authored content outside the owned region is
preserved untouched. A new generic module, `managed_text_block.py`
(`split_managed_block` / `compose_managed_file` / `replace_managed_block` /
`ManagedBlockError`), implements the same DD-083 splicing algorithm as the
existing private Claim-Registry implementation but is parametrized on marker text,
so the new master-registration feature reuses proven logic without touching or
risking regression of the well-tested, tightly-coupled original.

`ProjectionSyncReport` gained an optional `scaffold_result` field, populated by
`apply_projection_sync`. The `claims-to-silver-ext` CLI command prints
`scaffold_result.describe()` on success and, on `ScaffoldPartialFailureError`,
prints the same `describe()` output for the partial result plus an explicit
"No rollback is performed" statement, then exits non-zero. The CLI's
activation-inventory JSON write (previously unconditional) now compares existing
content before writing and folds into the same created/updated/unchanged summary.

### Rationale

Holding generated skeletons to the same validation function used to gate
hand-authored ontologies is the only way to guarantee they are indistinguishable
from authored ones for every downstream consumer (`kairos-execute-validate`,
projection, mapping). Per-domain isolation with no rollback was chosen over an
all-or-nothing transaction because file-system operations across independently
named domains have no natural transactional boundary in this codebase, and
silently discarding successfully-written sibling domains on one domain's failure
would be more surprising and harmful than reporting the failure precisely and
leaving good work in place — this mirrors the project's broader "never claim
atomicity you don't have" principle. A parallel generic managed-block module
(rather than generalizing the existing private one) was chosen to avoid
destabilizing the Claim-Registry sync path, which has broad existing test
coverage and different semantics (it drives a fully bulk-replaceable block from
claim data, not a registration list keyed by "currently known domains").
Wholesale convergence of *every* ready domain on each run (not just newly
scaffolded ones) avoids a subtler bug where a later run would inadvertently drop
a previously-registered domain from the managed block.

### Consequences

- `core/claim_projection_sync.py`: new `ScaffoldMetadataError`,
  `_validate_domain_slug` / `_DOMAIN_SLUG_RE`, `_validate_generated_metadata`,
  `_MASTER_IMPORT_BEGIN` / `_MASTER_IMPORT_END`, `_sync_master_registration`,
  `_README_TABLE_HEADER`, `_update_readme_domain_table_row`,
  `_sync_readme_domain_table`, `ScaffoldSurfacesResult`,
  `ScaffoldPartialFailureError`; `scaffold_missing_surfaces`'s return type changed
  from `None` to `ScaffoldSurfacesResult` (breaking change for any direct caller —
  none exist outside this module and its tests); `ProjectionSyncReport` gained
  `scaffold_result: ScaffoldSurfacesResult | None = None`.
- `core/managed_text_block.py` (new): generic, domain-agnostic managed-block
  splicing module, independent of the pre-existing Claim-Registry implementation.
- `cli/main.py`: `claims-to-silver-ext` catches `ScaffoldPartialFailureError`,
  prints the partial result and a no-rollback statement, and exits non-zero;
  prints `scaffold_result.describe()` on success; activation-inventory writes are
  now compared before writing and reported as created/updated/unchanged.
- `.github/skills/kairos-design-domain/SKILL.md` and `.github/skills/kairos-help/SKILL.md`
  (+ their `src/kairos_ontology/scaffold/skills/...` copies via
  `scripts/sync_dev_skills.py`) updated to describe the hardened metadata,
  master/README convergence, explicit reporting, and partial-failure behavior.
- New tests in `tests/test_claim_projection_sync.py`: metadata completeness on
  scaffolded skeletons, idempotence across repeated runs, partial-failure
  isolation (invalid domain slug does not block/rollback siblings), master/README
  convergence (including idempotence and graceful skip when absent), a direct
  `_validate_generated_metadata` error-message unit test, and CLI-level tests for
  the printed created/updated/unchanged summary (with git-status hint) and the
  partial-failure exit path.
