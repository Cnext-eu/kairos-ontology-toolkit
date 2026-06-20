# Slice 0A — Full-closure spike (perf/FK only)

**Status:** 🟢 spike run · findings recorded · **Depends on:** — · **Gates:** 0B and all downstream

> **Outcome in one line:** Claim-driven materialization correctly suppresses
> unclaimed **imported** classes with **no FK leak** (PASS), but acme-hub
> structurally **cannot** measure the full-closure *import-resolution* or *perf*
> risk that motivates C2 — that risk stays **unresolved** and must be cleared by a
> real large-closure spike before committing to import-all. This **strengthens the
> case for A1 (claims-drive-imports) as the Slice 0B default.**

## Goal

Prove (or disprove) that importing the full accelerator pack into a hub is
technically viable, before committing to the import-all concept (C2). This is a
measurement spike, **not** a file-format or schema exercise.

## Scope

- Create `model/ontologies/_foundation.ttl` importing the accelerator pack URI.
- Wire `catalog-v001.xml` so the accelerator + transitive imports resolve
  locally (chain to the `ontology-reference-models` catalog).
- Run `uv run kairos-ontology validate` — confirm the full import closure loads
  with zero unresolved imports.
- Refactor ONE domain (party) to import the foundation + claim a handful of
  classes via `silverInclude` / `silverIncludeImports`.
- Project party **silver + dbt** across the full closure.

## Measurements to capture

- `validate` wall-time on the full closure vs a single-module-import baseline.
- silver + dbt projection wall-time at full-closure scale.
- Whether unclaimed imported classes are reliably skipped.
- Whether unclaimed imports leak FK columns / phantom refs
  (issues #174 / #175 / #178), especially when many classes share ranges.
- Memory / graph size of the merged closure.

## Acceptance criteria

- [⚠️] Closure resolves cleanly; `validate` succeeds with zero unresolved imports.
  **Not validated in acme-hub** — see Finding 1 (no catalog; imports not
  followed). Deferred to the real large-closure spike.
- [~] silver + dbt projection wall-time is acceptable (number recorded, but
  **not at scale** — acme-hub is ~300 triples; see Finding 4).
- [x] No FK leak / phantom refs from unclaimed imported classes. **PASS** —
  `refp:Address`, `refp:ShipOperator` (see Finding 2).
- [x] Unclaimed (imported) classes reliably skipped. **PASS** (Finding 2).
- [x] Spike report written with go/no-go recommendation (below).

## Spike results (2026-06-15)

Harness: throwaway `spike_0a.py` (copies acme-hub → temp, projects silver+dbt,
times each, scans generated dbt for standalone tables / `*_id|_key|_sk` columns
referencing the unclaimed fixtures `Address`, `ShipOperator`, `VesselCarrier`).
Run via `run_projections()` with `KAIROS_SKILL_CONTEXT=1` (spike, not a managed
workflow). The harness is **not committed** (lives in the session workspace).

### Finding 1 — acme-hub does NOT exercise catalog full-closure import-resolution
Standalone parse sizes: `client=134`, `invoice=110`, **`logistics=26`** triples.
The logistics `owl:imports <https://refmodel.example/ontology/party>` is **not
followed** without a catalog (acme-hub ships none). The silver/dbt projectors
resolve reference models by **merging the `model/ontologies/` directory**, not by
following imports. ⇒ acme-hub validates *materialization/skip correctness*, **not**
the *catalog-resolved full-closure load* that C2 (import-the-whole-pack) is about.
**The C2 perf/closure risk is therefore unmeasured by this scenario.**

### Finding 2 — Imported + unclaimed classes do NOT leak (the key PASS)
`refp:Address` and `refp:ShipOperator` are imported via the reference model and
are **not** claimed via `silverInclude` in `logistics-silver-ext.ttl`. In the full
generated dbt output they produce **no standalone silver/dbt table** and **no
inbound FK column** (`address_*`, `ship_operator_*` absent everywhere). This is
direct evidence that DD-021 claim-driven materialization suppresses unclaimed
*imports* cleanly — the core correctness premise of the accelerator-foundation +
thin-ontology pattern holds (#174/#175/#178 do not reproduce here).

### Finding 3 — Local domain classes are materialized regardless of claims (governance gap)
`acme-log:VesselCarrier` and `logistics:ActiveMarker` are **local** (domain-
namespace) classes. They get ROOT tables in `silver_logistics` DDL **even though
they are not claimed** via `silverInclude`. The DD-021 claim gate governs
**imported** classes only — local classes are implicitly materialized. For *thin*
client ontologies (few local classes) this is bounded and arguably correct
("thin ontology = every local class is implicitly claimed"). But it is a real
decision for Slice 0B's **projector-authority / no-bypass policy**: decide
explicitly whether local domain classes are also claim-gated, or implicitly
claimed by virtue of being authored in the thin ontology.
(Note: the standalone silver *models* dir for logistics is empty because no bronze
mappings are bound; the ROOT tables appear in the **DDL analysis** artifact — a
second reason to make the policy explicit about which artifact is authoritative.)

### Finding 4 — Perf is not a meaningful signal at this scale
`silver≈5.5s` (dominated by cold-start import/warmup), `dbt≈0.34s` across 3 tiny
domains. No scale conclusion is possible; do **not** read these as a perf clear.

## Go / no-go

- **GO (correctness):** Claim-driven suppression of unclaimed **imports** works
  with no FK leak. The materialize-on-claim spine (C3) is validated on the
  dimension acme-hub can test.
- **NO-GO / UNRESOLVED (perf + closure):** acme-hub cannot test catalog full-
  closure import-resolution or scale perf (Findings 1, 4). The risk that
  motivates **C2 vs A1** is therefore **still open**.
- **Recommendation:** Treat **A1 (claims-drive-imports)** as the **default** in
  Slice 0B. Only adopt C2 (import-the-whole-pack + no-bypass projector) if a
  separate **real large-closure spike** (catalog-resolved, fibo/CLdN-scale, many
  shared ranges) clears both perf and FK-leak. Carry **Finding 3** into 0B as an
  explicit policy decision (are local domain classes claim-gated?).

## Follow-up spike still required (tracked into 0B)

A genuine C2 test needs: a hub **with a catalog** chaining to the accelerator's
reference-model catalog, a `_foundation.ttl` importing the full pack, and a
domain refactored to import the foundation. Measure catalog-resolved `validate`
closure load + projection wall-time at real scale, and re-run the FK-leak oracle
with many classes sharing ranges. acme-hub is unsuitable; use a real or
synthetic large closure.

## Outputs

- Spike report (numbers + pass/fail per criterion).
- Go/no-go recommendation that feeds the **A1 decision** in Slice 0B
  (if full-closure perf/FK fails, A1 "claims drive imports" becomes the default).

## Risks / notes

- This slice's failure is the trigger for the **sub-pack fallback** or
  adopting **A1** (claims-drive-imports) instead of import-all.
- No production file formats are defined here — keep it throwaway/measured.
