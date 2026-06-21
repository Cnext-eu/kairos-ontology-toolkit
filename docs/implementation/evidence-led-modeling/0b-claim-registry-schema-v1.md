# Slice 0B — Claim Registry schema v1 + migration + projector authority

**Status:** 🟡 draft for confirmation · **Depends on:** 0A (findings recorded) ·
**Gates:** Slice 1 (migration), Slice 2 (projector authority)

This is the **irreversible design gate**. It fixes the Claim Registry file format,
the one-way migration from `{domain}-alignment.yaml`, and the projector-authority
policy. It also resolves the two conceptual forks (A1, A2) and the Slice 0A
**Finding 3** (local-class gating). Nothing here materializes data.

---

## 1. Fork decisions (recommended — pending owner confirmation)

### A1 — claims drive imports ✅ **recommended: ADOPT A1**

Each domain's `owl:imports` (or accelerator sub-pack selection) is **generated
from approved claims**, not hand-maintained as "import the whole pack and police
it with a no-bypass projector."

**Grounding (Slice 0A):** the acme-hub spike proved claim-driven suppression of
unclaimed *imported* classes leaks no FKs (correctness PASS), but acme-hub
structurally **cannot** measure catalog full-closure import-resolution or scale
perf — so C2's motivating risk is unresolved. A1 dissolves that risk entirely:
if only claimed closures are imported, there is no large unclaimed surface to
police, no perf cliff, and no "access-control-over-`owl:imports`" smell.

**Consequence:** C2 (import-all + no-bypass projector) is **deferred**, adopted
only if a future real large-closure spike (catalog-resolved, fibo/CLdN-scale,
many shared ranges) clears both perf and FK-leak. Slice 2 simplifies to
*generate imports* rather than *suppress them*.

### A2 — collapse authored surfaces ⚠️ **recommended: PARTIAL (A2-lite)**

Do **not** make the Claim Registry the *only* authored artifact in v1. Keep the
registry as the single **governance** source of truth, and **generate** the
derived surfaces from approved claims:

- generate each domain's `owl:imports` set (A1),
- generate / refresh the silver-ext `silverInclude` claims,
- generate thin-ontology **specialization stubs** for `disposition: specialize`.

But keep the thin client ontology and silver/gold extension files as **first-class
review artifacts** (generated, then human-reviewable in the PR), not hidden
intermediates. Rationale: full collapse (registry → everything, no reviewable
TTL) removes the ontology diff reviewers rely on and over-couples the registry
schema to projector internals. A2-lite keeps one authored source with reviewable
generated outputs — the GitHub-PR governance the owner asked for.

### Finding 3 — are local domain classes claim-gated? ✅ **recommended: implicit-claim-with-record**

A class authored **in the thin client ontology** (the domain namespace) is
**implicitly approved** — authoring *is* claiming. But the registry MUST still
carry a claim entry for it (auto-generated, `status: approved`,
`disposition: specialize|claim`, `source: authored`) so coverage/parity and the
silver contract stay governed in one place. Only **imported** (accelerator/
reference-model namespace) classes require an *explicit* claim to materialize.

This matches the DD-021 mechanic observed in 0A (claim gate governs imports;
local classes materialize) while closing the governance gap: every materialized
table — local or imported — has a registry row.

---

## 2. Claim Registry schema v1

Location (one file per domain):

```text
model/claims/{domain}-claims.yaml
```

### 2.1 Top-level (domain) fields

```yaml
schema_version: 1
domain: party
generated_at: 2026-06-15T19:30:00Z
algorithm_version: 3            # prompt/algorithm contract that produced proposals
freshness:
  affinity_sha256: "…"         # digest of the affinity (system,table) set seen
  alignment_params_sha256: "…" # cross-module/accelerator/pool params signature
coverage:                       # per-(system, table, column) snapshot — parity item
  systems:
    - system: crm
      tables:
        - table: account
          total_columns: 24
          mapped_columns: 21
          custom_columns: 3
          anchor_state: matched      # matched | fallback | rejected | unmatched
          ref_class: TradeParty
claims:
  - …                            # see 2.2
```

### 2.2 Claim (entry) fields

```yaml
- id: party-trade-party          # STABLE id (never reused, never renumbered)
  type: class                    # class | property | relationship | reference_data | measure
  class_uri: https://example.org/accelerator/logistics#TradeParty
  # property_uri / relationship endpoints used for the corresponding types
  origin: imported               # imported | authored   (Finding 3)
  status: approved               # proposed | approved | rejected | deferred | deprecated
  disposition: claim             # claim | specialize | passthrough | skip | gap
  owner: data-domain-party
  evidence_sources:              # table/column-granular — parity item
    - {type: source_table,  system: crm, table: account}
    - {type: source_column, system: erp, table: customer, column: credit_limit}
    - {type: powerbi_table, model: commercial-report, table: Customer}
    - {type: stakeholder_confirmation, note: "…"}
  silver_impact:
    table: dim_party
    column: credit_limit         # for property/passthrough claims
    change_type: additive        # additive | breaking
  rationale: >
    …
  # optional — populated by tooling, preserved across edits:
  proposed_confidence: 0.86
  superseded_by: party-legal-entity   # set when status: deprecated
```

### 2.3 Parity-appendix coverage map

| Parity requirement (index appendix) | Schema v1 home |
|---|---|
| per-(system,table,column) coverage snapshot | `coverage.systems[].tables[]` |
| `source_sha256`-equiv freshness hash | `freshness.affinity_sha256` (+ `alignment_params_sha256`) |
| algorithm / prompt-contract version | top-level `algorithm_version` |
| custom-column triage (`model`/`silver-passthrough`/`skip`) | claim `disposition` (`claim`/`specialize`/`passthrough`/`skip`) + migration map (§3.2) |
| anchor / ref-class validation state | `coverage…anchor_state` (matched/fallback/rejected/unmatched) |
| evidence at table/column granularity | `evidence_sources[]` typed entries |
| deterministic conversion + golden tests | migration (§3) |
| old alignment files error, no dual path | migration (§3.3) |

### 2.4 Contract semantics (minimal)

- **id stability:** `id` is permanent; deleting a concept ⇒ `status: deprecated`
  (+ optional `superseded_by`), never silent removal or id reuse.
- **status transitions:** `proposed → {approved, rejected, deferred}`;
  `approved → deprecated`; `deferred → {proposed, approved}`. `rejected` and
  `deprecated` are terminal (re-open ⇒ new id).
- **deprecated behavior:** excluded from generated imports/materialization but
  retained in the file for lineage; projector emits an informational note.
- **breaking vs additive:** `silver_impact.change_type: breaking` requires a
  contract-version bump (Slice 6) and explicit owner approval in the PR.

---

## 3. One-way migration design (alignment YAML → claims)

### 3.1 Principle

Deterministic, AI-free, single-pass. `{domain}-alignment.yaml` →
`{domain}-claims.yaml`. **No dual path:** once a domain has a claims file, the
alignment file for that domain is rejected.

### 3.2 Field mapping

| alignment YAML | claims v1 |
|---|---|
| `domain`, `domain_uris` | `domain`, (uris dropped — derived from claims) |
| `TableAlignment.ref_class` + `ref_class_status` | `coverage…ref_class` + `anchor_state`; class claim `status: proposed` |
| `ColumnAlignment` (`alignment`, `ref_property`) | property claim (`disposition: claim`/`specialize`) + evidence `source_column` |
| `custom_columns[].disposition` = `model` | property claim `disposition: specialize`, `status: proposed` |
| `custom_columns[].disposition` = `silver-passthrough` | claim `disposition: passthrough` |
| `custom_columns[].disposition` = `skip` | claim `disposition: skip` |
| `affinity_sha256` | `freshness.affinity_sha256` |
| `alignment_params_sha256` | `freshness.alignment_params_sha256` |
| `algorithm_version` | top-level `algorithm_version` |
| per-table column counts | `coverage…{total,mapped,custom}_columns` |

All migrated class/property claims land as `status: proposed` (migration never
fabricates `approved` — approval is a human/PR act).

### 3.3 Old-file rejection

`check-*`/projection paths detect a `{domain}-alignment.yaml` and **error** with:
> `alignment.yaml is retired; run the one-shot migration to model/claims/{domain}-claims.yaml`
No silent fallback, no reading both.

### 3.4 Tests (Slice 1 gate)

- Golden test: a fixed `acme` alignment fixture → byte-stable claims YAML.
- Parity test: every parity-appendix field is populated by the converter.
- Negative test: presence of a legacy alignment file raises the migration error.

---

## 4. Projector-authority policy (scope reduced by A1)

With A1, the projector does **not** police a large unclaimed import surface.
Policy reduces to:

1. **Imports are generated** from `approved` class claims (`origin: imported`)
   plus their required closure; nothing else is imported.
2. **Materialization requires an `approved` claim row** — local (`origin:
   authored`) classes are auto-claimed (Finding 3) so they pass; imported classes
   without an approved claim are not imported, hence cannot materialize.
3. `silverInclude` / `silverIncludeImports` become **generated** artifacts derived
   from approved claims, not hand-authored bypasses. A hand-edit that includes a
   class with no approved claim is flagged by a deterministic check (Slice 2).
4. `proposed` / `deferred` / `rejected` / `deprecated` never materialize.

(The full DD-021 "no-bypass over import-all" mechanism is retained in code but
dormant unless a future spike adopts C2.)

---

## 5. Acceptance criteria status

- [x] A1 decided and recorded (ADOPT A1) — grounded in 0A.
- [x] A2 decided and recorded (A2-lite: single governance source, generated +
      reviewable derived surfaces).
- [x] Finding 3 decided (implicit-claim-with-record).
- [x] Schema v1 documented; covers every parity-appendix item (§2.3).
- [x] Migration design documented (§3).
- [ ] **DD entry** added to `docs/design/toolkit-design-decisions.md`
      — **held pending owner confirmation of §1 decisions.**

## 6. Open confirmations before the DD is written

1. **A1** — generate imports from claims (defer import-all/C2)? 
2. **A2-lite** — registry = single governance source, but keep generated thin
   ontology + extension files as reviewable PR artifacts (not fully collapsed)?
3. **Finding 3** — local thin-ontology classes are implicitly approved but still
   recorded as `origin: authored` claims for parity?
