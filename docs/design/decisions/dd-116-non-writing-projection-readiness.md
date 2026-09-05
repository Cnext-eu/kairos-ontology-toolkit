# DD-116: Non-Writing Projection Readiness

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** scoped closure/loading, projection CLI/orchestration, dbt and Gold physical
planning, lifecycle status, design validators/scaffolds, and readiness reports
**Implementation:** `core/projection_readiness.py`, projector check-only execution, and
`check-projection`; `core/reference_modules.py`; `core/design_validation.py`;
`core/authoring_scaffolds.py`; `core/status.py`

### Context

Projection was the first point where scoped ontology closure, synchronized contracts,
bindings, normalized policy, adapter feasibility, and physical plans were evaluated
together. Running it for diagnosis also rendered and wrote generated output.

### Decision

`check-projection` runs the same scope discovery and projection pipeline through physical
artifact planning, then stops before render and every filesystem write. Preparation, mapping, DD-108 identity, incremental runtime, temporal/FK, adapter feasibility,
data quality, and Gold evaluation use the shared `COLLECT` model for dbt, Silver, and Power BI
readiness. Each subsystem is evaluated once; the orchestrator never catches and retries a
whole projection. Stages return partial or unavailable typed results, preserve fail-fast first-
diagnostic parity, and mechanically mark dependent checks `not_evaluated` with prerequisite
diagnostic IDs while unrelated roots continue. Real projection keeps `FAIL_FAST` as its
default. The command returns a schema-versioned text or stable JSON report and exits
nonzero for blockers. The evaluator itself remains non-writing. Callers may preserve its exact
versioned JSON under `.kairos-state/reports/`; status consumes but never fabricates that evidence.

Scope is derived from the selected ontology/import closure plus the explicitly selected
accelerator/module profile. Validation, inventory, claim synchronization, readiness, and
projection share that domain-scoped closure authority: unresolved modules inside the requested
closure fail closed, while unrelated installed accelerator modules are neither instantiated nor
allowed to affect the exit code. `check-inventory --domains ... --explain-scope` remains the sole
reference-inventory freshness authority and reference-model updates are always explicit.

Source, mapping, transformation, and Silver completion gates are scoped views of this same
non-writing evaluation. Scope filters diagnostics only after the shared bind/normalize
authorities have produced them; it does not reimplement their rules. Reports identify the owner
skill and prerequisite phases. Local Turtle/SHACL/design validity remains distinct from bound
readiness.

Lifecycle status is an additive v3 compatibility layer over the legacy phase view. It derives the
monotonic chain `authored`, `design-valid`, `bound-valid`, `projection-ready`, `generated`,
`compile-valid`, `runtime-valid`, and `release-eligible` from authored artifacts and known
versioned reports. A later artifact cannot promote the effective state across an unknown or
blocked predecessor. Missing, stale, malformed, or unknown-schema reports are `unknown` warnings,
not migration failures. Legacy `done` remains readable as legacy/unknown input and is never
interpreted as a failed gate or richer readiness evidence.

Silver is split into logical intent (SCD, identity/grain, FK/temporal, PII and DQ choices) and a
later bound confirmation. Bound confirmation consumes only the Silver-scoped non-writing
evaluator after final transformation and mapping. Complex routing is logical Silver → contracted
dbt transformation → mapping → bound Silver → full readiness → projection; simple direct/scalar
mapping omits only the transformation checkpoint. Flow and project skills never route to
generation while the full readiness report has blockers.

Focused, read-only `validate-mapping` and `validate-silver-ext` commands establish local design
validity without loading unrelated accelerator closure. Evidence-grounded `scaffold-mapping` and
`scaffold-silver-ext` output proposed-only RDF by default and write only when an output is
explicitly requested; existing outputs require `--overwrite`. Scaffolds never authorize business
semantics and must pass the focused validator before review. Class/property lookup uses the shared
semantic index, including inherited properties and ranges.

Regeneration is non-destructive. Managed authorities update only their delimited managed blocks
and preserve authored triples outside those blocks. Operations that must rewrite RDF provide a
non-writing plan first. In particular, legacy whole-graph managed-surface migration stages durable
backups, and column-IRI migration requires explicit apply, validates all collisions first, and
creates a new backup before writing. The lifecycle scanner validates phase-log xrefs and declared
deliverables, reports disagreement with deterministic filesystem state as drift, ignores archived
logs, and never treats a phase-log checkbox as artifact evidence.

### Rationale

Sharing the existing bind, `normalize_contract`, shape, adapter, and materialization
functions preserves first-error parity and avoids a second simulation of projection rules.

### Consequences

- The command cannot detect rendering, output-filesystem, SVG, compile, or runtime failures.
- Existing projection behavior and legacy exception contracts remain unchanged.
- Reports expose stable ordered diagnostics plus the backward-compatible first `blocker`.
  Remediation is dependency ordered and deduplicated by owning skill and root cause; impacted
  FKs share one task when they depend on the same missing target semantic key.
- A collected blocker is valid only when it is reachable through normal `FAIL_FAST` projection
  after its prerequisites are repaired; blockers need not be simultaneously reachable.
- Existing v1/v2 status keys and legacy phase readers remain intact; v3 adds the lifecycle object.
- Readiness blockers participate in the composed release gate, while absent/stale/unknown evidence
  remains advisory for compatibility.
- Authoring scaffolds reduce mechanical TTL work but leave naming, mapping, identity, runtime, and
  governance decisions proposed until their owning design skill confirms them.
