# Slice 0B — Registry schema + migration + projector-authority gate

**Status:** 🟢 decided · schema + migration + forks recorded · **Depends on:** 0A · **Gates:** Slice 1

## Goal

Decision gate that fixes the **irreversible file formats and architecture** for
everything downstream. Nothing here ships code that materializes data — it
produces a schema, a migration design, a projector-authority policy, and resolves
the two conceptual forks.

## Conceptual forks to decide here

- **A1 — claims drive imports vs import-all-then-suppress.** Using the 0A spike
  result, decide whether each domain's `owl:imports` (or sub-pack selection) is
  *generated from approved claims*, or whether the full accelerator is imported
  and policed by a no-bypass projector. A1 dissolves C2's perf/FK risk and the
  "access-control-over-`owl:imports`" smell.
- **A2 — collapse authored surfaces.** Decide whether the Claim Registry is the
  **only** hand-authored artifact (generating both extension annotations and
  thin-ontology specialization stubs), or whether three surfaces coexist with
  generation + checks.

## Deliverables

1. **Claim Registry schema v1** (`model/claims/{domain}-claims.yaml`) covering:
   - claim `id` (stable), `type` (class / property / relationship /
     `reference_data` / measure), `class_uri` / `property_uri`,
   - `status` (proposed / approved / rejected / deferred / deprecated),
   - `disposition` (claim / specialize / passthrough / skip / gap),
   - `evidence_sources` (typed, table/column-granular),
   - `owner`, `rationale`, `silver_impact` (table/column + additive/breaking),
   - **parity fields** (see index appendix): coverage snapshot, freshness hash,
     algorithm/prompt-contract version, custom-column triage, anchor state,
   - minimal **contract semantics**: id stability, status-transition rules,
     `deprecated` behavior, breaking-vs-additive marking.
2. **One-way migration design** alignment YAML → claims (deterministic; old files
   error with migration guidance; no dual path).
3. **Projector no-bypass policy** (only relevant if A1 = import-all): projector
   rejects any annotation materializing a class not `approved`; bulk/default
   includes treated as proposals or disabled.

## Acceptance criteria

- [ ] A1 decided and recorded (with 0A evidence). → ✅ **DD-EL-2** (adopt A1).
- [ ] A2 decided and recorded. → ✅ **DD-EL-3** (A2-lite + Finding-3 local-class).
- [ ] Schema v1 documented and covers every parity-appendix item. → ✅ `0b-claim-registry-schema-v1.md` §2.
- [ ] Migration design documented. → ✅ §3 of the schema doc.
- [ ] DD entry added to `docs/design/toolkit-design-decisions.md`. → ✅ recorded in
  [`decision-log.md`](decision-log.md) (DD-EL-1/2/3); assign final DD-NNN and merge
  into the design log at feature-merge time.

## Outputs

- DD entry, schema draft (in this folder or `docs/design/`), migration design.

> **Draft delivered:** [`0b-claim-registry-schema-v1.md`](0b-claim-registry-schema-v1.md)
> contains schema v1, migration design, projector-authority policy, and
> recommended fork decisions (A1 adopt · A2-lite · Finding-3 implicit-claim).
> The DD entry is **held pending owner confirmation** of those three decisions.

## Risks / notes

- Schema choices here are expensive to reverse — this is the gate to slow down on.
- If A1 is chosen, much of the projector-authority / no-bypass work disappears and
  Slice 2 simplifies (generate imports, not suppress them).
