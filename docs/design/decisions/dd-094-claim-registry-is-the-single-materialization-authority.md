# DD-094: Claim Registry is the single materialization authority

**Status:** Accepted

**Date:** 2026-07-21

**Affects:** `model/claims/{domain}-claims.yaml`, `{domain}-alignment.yaml`
(retired), `src/kairos_ontology/core/claim_registry.py`,
`src/kairos_ontology/core/completeness_model.py`,
`src/kairos_ontology/core/claim_coverage.py`,
`src/kairos_ontology/core/source_coverage.py`,
`src/kairos_ontology/core/propose_alignment.py`, silver/dbt projectors,
`check-claims` / `check-source-coverage`, evidence-led design skills

**Implementation:** Claim Registry schema v1 → migration → projector authority.
Canonicalized from the archived evidence-led decision log
(`docs/archive/evidence-led-modeling/decision-log.md` §DD-EL-1); see also
`docs/archive/evidence-led-modeling/0b-claim-registry-schema-v1.md`.

### Context

The evidence-led, accelerator-first methodology needs a single governed artifact
recording *which concepts are approved to materialize*, with evidence, ownership,
dispositions, and silver-contract impact. The legacy `{domain}-alignment.yaml`
carried proposal data but was an AI-output artifact with no approval lifecycle.
Keeping both an alignment file and a registry would create a dual source of truth.

### Decision

Introduce a per-domain **Claim Registry** at `model/claims/{domain}-claims.yaml`
(schema v1) as the single hand-governed source of truth for materialization.
**Retire** `{domain}-alignment.yaml` via a one-way deterministic migration; once a
domain has a claims file, a leftover alignment file is a hard error (no dual path).
Each claim carries an explicit `status` lifecycle (`proposed → approved → …`) and a
`disposition` vocabulary (`claim` / `specialize` / `passthrough` / `skip` / `gap`).
Approved `claim`/`specialize` claims — and only those — authorize silver/dbt
materialization; the projector consumes the registry rather than namespace
selection alone. The retired coverage gates unify into a single **`check-claims`**
command. A canonical per-table completeness snapshot is computed once from committed
affinity, registry, source, mapping, contract, and Silver-extension inputs; the
claim and source gate reports are views over that snapshot.
`migrate_claims.py` is the sole legacy alignment-YAML reader, used only by the
one-shot migration; no runtime completeness evaluator reads alignment YAML.

### Rationale

One governed file with a reviewable, GitHub-PR-based lifecycle gives auditable
governance. A single deterministic completeness model preserves coverage,
freshness, anchor/reference-class, and governed-replacement guarantees while
eliminating duplicate table reconstruction. Golden, parity, and negative-migration
tests enforce fidelity.

### Consequences

- The registry is the authority for what materializes; probabilistic evidence never
  auto-approves a claim.
- `propose-alignment` output becomes migration input, not a parallel artifact.
- Custom-column triage maps: `model`→`specialize`/`claim`,
  `silver-passthrough`→`passthrough`, `skip`→`skip`.
- Claim ids are stable and never reused; deletions become `deprecated`.
- `check-claims` blocks on missing/invalid/incomplete/stale/duplicate-approved and
  (unless `--no-source-coverage`) unmapped tables; `--strict` also blocks undecided
  (`proposed`) claims; leftover `*-alignment.yaml` is always a hard error.
- Conformance-derived proposals remain Claim Registry evidence only: they cannot
  satisfy direct mapping coverage without a committed SKOS mapping or complete
  governed-replacement evidence.
