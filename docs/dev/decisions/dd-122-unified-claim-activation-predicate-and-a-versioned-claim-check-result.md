# DD-122: Unified Claim-Activation Predicate and a Versioned Claim-Check Result

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** `core/binding_analysis.py`, `core/reference_modules.py`,
`core/claim_projection_sync.py`, `core/source_coverage.py`,
`core/lifecycle_gate.py`, `core/claim_check_result.py` (new), `cli/main.py`
**Implementation:** `claim_activates_projecting_import`,
`is_decided_non_activating`, `DECIDED_NON_ACTIVATING_STATUSES`,
`DisputedClaimModule`, `ManagedImportPlan.disputed_claims`,
`DomainProjectionSync.disputed_claims`, `ProjectionSyncReport.disputed_claims`/
`.owner_skill`, `SourceCoverageReport.owner_skill`,
`ClaimCheckResult`/`SemanticGenerationSummary`/`SemanticGenerationFact`,
`build_claim_check_result`, `check-claims --format json`, `check-claims --require-mapping`

### Context

Whether a decided claim (`approved`/`deferred`/`rejected`) activates a projecting
reference-module import was checked three separate times — in managed-import
planning (`approved_imported_class_uris`/`approved_imported_term_refs`), in
claims↔projection sync, and in activation-inventory reporting — each re-deriving
the same `status == "approved" and origin == "imported" and disposition in
{"claim", "gap"}`-shaped condition independently. A `deferred` or `rejected`
claim was correctly excluded from *activating* an import everywhere it was
checked, but nothing recorded when the same module stayed active anyway for an
unrelated reason (another claim, or an unconditional data-domain group
activation): a curator who deferred/rejected a claim had no signal that its
module was still present, which reads as a disagreement between the decision
and the generated projection surface.

Separately, `check-claims --strict` blocked on an OR of registry validity,
mapping coverage, and projection-sync drift, conflating three independently
owned concerns into one exit code: mapping gaps are `kairos-design-mapping`'s
concern and sync drift is `kairos-design-domain`'s (enforced by
`claims-to-silver-ext --check-only`), neither of which should fail the
curation-focused `check-claims` gate. There was also no single, versioned,
machine-readable result a skill or CI step could parse — only ad hoc text and
three separately-invoked evaluators.

### Decision

`binding_analysis.py` gains one shared predicate,
`claim_activates_projecting_import(claim) -> bool`, plus its complement
`is_decided_non_activating(claim)` (true for `DECIDED_NON_ACTIVATING_STATUSES =
{"deferred", "rejected"}`). `approved_imported_class_uris` and
`approved_imported_term_refs` now call this predicate instead of repeating the
status/origin/disposition check inline — behavior-preserving, but there is now
exactly one place that answers "does this claim activate a projecting import".

`reference_modules.py` adds `DisputedClaimModule` (`claim_id`, `claim_status`,
`term_uri`, `module_id`, `import_iri`, `reasons`) and a
`ManagedImportPlan.disputed_claims` tuple, populated by scanning the registry
for `is_decided_non_activating` claims whose term resolves to a module that
remains active for another reason (i.e. its import IRI is still present in the
plan's requirement data). `claim_projection_sync.py` threads this through
`DomainProjectionSync.disputed_claims` (each entry tagged with its `domain`)
and exposes a flattened `ProjectionSyncReport.disputed_claims` property, plus an
`owner_skill: str = "kairos-design-domain"` field. `source_coverage.py` gains
the analogous `SourceCoverageReport.owner_skill: str = "kairos-design-mapping"`.
Both `owner_skill` additions and the new `disputed_claims` fields are purely
additive dataclass fields; `lifecycle_gate.py`'s existing `_projection_sync_to_dict`/
`_source_coverage_to_dict` helpers gain the corresponding keys without a schema
version bump (additive-only, per that module's own versioning convention).

A new `core/claim_check_result.py` composes the existing, independently
governed evaluators into one versioned (`CLAIM_CHECK_RESULT_SCHEMA_VERSION = 1`)
`ClaimCheckResult`, with five facets each reported on its own: `registry`
(`ClaimCheckReport`, unchanged), `semantic_generation`
(`SemanticGenerationSummary`/`SemanticGenerationFact`, one per domain), `mapping`
(`SourceCoverageReport | None`), `projection_sync` (`ProjectionSyncReport`), and
the flattened `disputed_claims` list. `semantic_generation` deliberately
consumes DD-121's additive `ClaimCheckReport.incomplete_generation` metadata
(itself sourced from `ClaimRegistry.generation_outcomes`) rather than inventing
a second notion of "generated": a domain with no incomplete-generation entries
— because every table reached `semantic_success`, or because its registry
predates the `generation_outcomes` feature entirely (a legacy artifact) — is
vacuously complete for this facet, so old registries are never penalized.
`curation_complete` is the **only** composite/blocking signal this module
introduces, computed from the registry facet alone: `False` if
`registry.is_blocking`, or (only under `strict=True`) if
`registry.has_undecided_claims()`; otherwise `True`. `semantic_generation`,
`mapping`, and `projection_sync` never gate it — they stay independently
visible (mapping/sync additionally carry `owner_skill`) and block only within
their owning workflow.

`check-claims` (`cli/main.py`) now builds this one `ClaimCheckResult` instead of
invoking the registry/mapping/sync evaluators separately, gains `--format
json|text` (default `text`) to emit `result.to_dict()` verbatim, and its
`should_block` computation drops the previous `source_blocking`/`sync_blocking`
OR — the exit code is now `(report.is_blocking or strict_block or
mapping_block) and not warn_only`, where `mapping_block` is `False` unless the
caller passes the new, opt-in `--require-mapping` flag (see Consequences).
Mapping-gap and sync-drift text
sections remain printed (now with an explicit `owner_skill` line and non-error
`⚠` styling instead of `❌`/`err=True` when not required), and any `disputed_claims` entries are
printed per domain in both `check-claims` and `claims-to-silver-ext`'s existing
sync-reporting loop, so a curator sees exactly which claim IDs retain a
disputed module and why.

### Rationale

A single shared predicate is the only way to guarantee managed-import planning,
projection sync, and activation-inventory reporting can never silently diverge
on what "a decided claim activates an import" means — the original three
independent implementations happened to agree, but nothing enforced that.
Reporting disputes rather than silently dropping them keeps a
deferred/rejected decision from reading as ignored when the module is
legitimately still needed for another reason. Scoping `curation_complete` to
registry/freshness/semantic-policy/undecided-claims — and no further — keeps
each skill's enforcement boundary intact (DD-094's mapping ownership, this
document's projection-sync ownership) instead of one gate silently absorbing
every other gate's blocking behavior. Consuming DD-121's `generation_outcomes`
rather than re-deriving a second "semantic completeness" concept keeps exactly
one authority for that signal.

### Consequences

- `check-claims` (non-`--strict` and `--strict`) no longer exits non-zero on
  mapping gaps or projection-sync drift alone — only `claims-to-silver-ext
  --check-only` (sync) and mapping-owning workflows still block on those.
  Existing CI invocations that relied on `check-claims --strict` catching sync
  drift must instead run `claims-to-silver-ext --check-only`.
  `test_check_claims_blocks_on_sync_drift_and_passes_after_generation` was
  updated to assert the new exit-0 behavior.
- **`--require-mapping` (opt-in, added post-review)**: `kairos-execute-project`'s
  DD-094 pre-silver/dbt mapping gate had no standalone `check-source-coverage`
  command to fall back on — it depended entirely on `check-claims`'s own exit
  code to fail closed on unmapped affinity tables, which this DD's narrowing
  silently broke. Rather than re-widening the default `curation_complete`/exit
  code (which would reintroduce the original conflation), `check-claims` gained
  an explicit `--require-mapping` flag: when passed, `mapping_block =
  result.mapping.is_blocking` is folded into the exit-code OR (both `--format
  text` and `--format json`), without changing `curation_complete` itself or
  the default (no-flag) exit code. `kairos-execute-project`'s SKILL.md now
  documents `check-claims --require-mapping` for this gate; `kairos-design-mapping`
  (the mapping-authoring skill) can use the same flag, or its own review flow,
  as it prefers. `--strict` remains scoped to undecided-claims only, per this
  DD's original intent — `--require-mapping` is the dedicated, separately-named
  escape hatch for the one owning workflow that still needs `check-claims`
  itself to fail closed on mapping.
- `check-claims --format json` is new, additive CLI surface; the default text
  output keeps its existing structure with two additions: an `owner_skill` line
  on the mapping/sync sections and any `disputed_claims` entries.
- Old Claim Registries (no `generation_outcomes` key) and old callers of
  `approved_imported_class_uris`/`approved_imported_term_refs` are unaffected —
  both changes are read-only refactors/additive fields, not schema changes.
