# Evidence-led modeling — decision log (to merge into `toolkit-design-decisions.md`)

These entries follow the standard `DD-NNN` template but live here while the
evidence-led / accelerator-first work is on a feature track. DD numbers are
**placeholders** (`DD-EL-N`); assign final sequential `DD-NNN` numbers and move
these into `docs/design/toolkit-design-decisions.md` (and its Index) at merge.

---

## DD-EL-1: Claim Registry replaces alignment YAML as the governance source of truth

**Status:** Accepted
**Date:** 2026-06-15
**Affects:** `model/claims/{domain}-claims.yaml` (new), `{domain}-alignment.yaml`
(retired), `propose_alignment.py`, `alignment_coverage.py`, silver/dbt projectors,
`check-alignment` / `check-source-coverage`, evidence-led design skills
**Implementation:** Slice 0B schema → Slice 1 migration → Slice 2 projector
authority. Spec: `docs/implementation/evidence-led-modeling/0b-claim-registry-schema-v1.md`

### Context

The evidence-led accelerator-first methodology needs a single governed artifact
that records *which concepts are approved to materialize*, with evidence,
ownership, dispositions, and silver-contract impact. The existing
`{domain}-alignment.yaml` carries the proposal data but is an AI-output artifact,
not a governance record, and there is no approval lifecycle. Maintaining both an
alignment file and a registry would create a dual source-of-truth.

### Decision

Introduce a per-domain **Claim Registry** at `model/claims/{domain}-claims.yaml`
(schema v1) as the single hand-governed source of truth. **Retire**
`{domain}-alignment.yaml` via a one-way deterministic migration; once a domain has
a claims file, the legacy alignment file is rejected with a migration message (no
dual path). The registry covers every guarantee the alignment path provided
(per-(system,table,column) coverage snapshot, freshness hashes, algorithm/prompt
version, anchor state, custom-column triage, table/column-granular evidence) — the
parity appendix in `00-index.md` gates Slice 1.

### Rationale

One governed file with an explicit `status` lifecycle (proposed → approved → …)
and `disposition` vocabulary (claim / specialize / passthrough / skip / gap) gives
reviewable, GitHub-PR-based governance. Reusing the alignment backend functions
(coverage, freshness, anchor state) preserves all existing guarantees while
avoiding double-path logic. Golden + parity + negative migration tests enforce
fidelity.

### Consequences

- Slice 1 cannot merge until parity tests prove the registry preserves every
  alignment guarantee.
- `propose-alignment` output becomes migration input, not a parallel artifact.
- Custom-column triage values map: `model`→`specialize`/`claim`,
  `silver-passthrough`→`passthrough`, `skip`→`skip`.
- Claim ids are stable and never reused; deletions become `deprecated`.

### Slice 1 implementation note (2026-06-15)

The cutover unified the two retired gates into a single **`check-claims`** command
(backend `claim_coverage.py`): bucket priority `missing > invalid > incomplete >
stale > unverifiable > ok`, blocking on missing/invalid/incomplete/stale/
duplicate-approved + (unless `--no-source-coverage`) unmapped tables, with
`--strict` additionally blocking on undecided (`proposed`) claims and `--warn-only`
overriding to exit 0. Leftover `*-alignment.yaml` files are a hard error regardless
of `--warn-only`. `alignment_coverage.py` was purged of all alignment-YAML reader
machinery and now exposes only the reused affinity/freshness primitives and triage
heuristics (still imported by `claim_coverage`, `source_coverage`, and
`propose_alignment`). The module keeps its name despite the narrowed role.

---

## DD-EL-2: A1 — generate `owl:imports` from approved claims (defer import-all / C2)

**Status:** Accepted
**Date:** 2026-06-15
**Affects:** domain `owl:imports`, generated `silverInclude` / `silverIncludeImports`,
silver/dbt projectors, catalog wiring
**Implementation:** Slice 2 (import generation). Evidence:
`docs/implementation/evidence-led-modeling/slice-0a-closure-spike.md`

### Context

The accelerator-first concept (C2) proposed importing the **full** accelerator
pack into every hub and policing the large unclaimed surface with a no-bypass
projector. The Slice 0A spike measured this against acme-hub.

### Decision

Adopt **A1**: each domain's `owl:imports` (and accelerator sub-pack selection) is
**generated from approved class claims** plus their required closure. The full
import-all-then-suppress design (C2) is **deferred**, to be reconsidered only if a
dedicated real large-closure spike (catalog-resolved, fibo/CLdN-scale, many shared
ranges) clears both projection wall-time and FK-leak.

### Rationale

Slice 0A confirmed claim-driven suppression of unclaimed **imported** classes
leaks no FKs (`refp:Address`, `refp:ShipOperator` clean — correctness PASS), but
acme-hub structurally cannot follow `owl:imports` without a catalog (logistics
parsed to 26 triples) and is too small for a perf signal — so C2's *motivating*
risk (full-closure load + leak at scale) is **unmeasured and unresolved**. A1
removes the risk by construction: importing only claimed closures means there is
no large unclaimed surface to police, no perf cliff, and no
"access-control-over-`owl:imports`" smell.

### Consequences

- Slice 2 simplifies to *generate imports*, not *suppress* them.
- The DD-021 no-bypass mechanism is retained in code but dormant.
- A future large-closure spike is the only gate that can revive C2.

---

## DD-EL-3: A2-lite + local-class governance (registry single source, surfaces generated & reviewable)

**Status:** Accepted
**Date:** 2026-06-15
**Affects:** thin client ontology TTL, silver/gold extension TTL, `model/claims/`,
projector generation
**Implementation:** Slices 2–4. Spec:
`docs/implementation/evidence-led-modeling/0b-claim-registry-schema-v1.md` §1

### Context

Two coupled questions: (A2) should the Claim Registry be the *only* hand-authored
artifact, generating both extension annotations and thin-ontology stubs? And
(Slice 0A Finding 3) are **local** thin-ontology classes claim-gated, given DD-021
only governs *imported* classes (acme-hub materialized local `VesselCarrier` /
`ActiveMarker` regardless of claims)?

### Decision

- **A2-lite:** the Claim Registry is the single **governance** source of truth, and
  derived surfaces (domain `owl:imports`, `silverInclude` claims, thin-ontology
  `specialize` stubs) are **generated** from approved claims — but the thin
  ontology and silver/gold extension TTL files remain **first-class, reviewable PR
  artifacts**, not hidden intermediates. Full collapse is rejected for v1.
- **Finding 3 — implicit-claim-with-record:** a class authored in the thin client
  (domain-namespace) ontology is **implicitly approved** (authoring = claiming),
  but the registry still carries an auto-generated `origin: authored`,
  `status: approved` claim for it. Only **imported** (accelerator/reference-model)
  classes require an *explicit* claim to materialize.

### Rationale

Keeping reviewable TTL preserves the ontology diff reviewers rely on and avoids
over-coupling the registry schema to projector internals, while still giving a
single governance source and GitHub-PR-based change control. Implicit-claim-with-
record closes the governance gap surfaced in 0A: every materialized table — local
or imported — has exactly one registry row, so coverage/parity stay complete.

### Consequences

- Generators must (re)produce extension + thin-ontology files from claims and keep
  them in sync; a deterministic check flags hand-edits that materialize a class
  with no approved claim (Slice 2).
- The registry must auto-emit `origin: authored` claims for local classes so
  parity tooling sees them.
- Reviewers see both the registry change and the generated TTL diff in the PR.
