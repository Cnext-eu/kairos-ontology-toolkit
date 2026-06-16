# Evidence-Led, Accelerator-First Ontology Modeling

**Status:** Canonical (promoted from draft, 2026-06-16) ·
**Applies to:** Kairos Ontology Toolkit ≥ 4.0.0-rc1

This document is the canonical description of the **evidence-led,
accelerator-first** modeling methodology. It supersedes the working drafts under
[`../draft/`](../draft/) and reflects the **measured reality** of the
implementation (slices 0A–8), not the original hypothesis. Every architectural
choice below was validated by a vertical implementation slice and recorded as a
decision; see the [decision index](#10-decision-index) for traceability.

---

## 1. What "evidence-led, accelerator-first" means

Two ideas, combined:

- **Accelerator-first** — start from a curated *accelerator* (reference-model
  pack) rather than a blank ontology. A thin per-domain ontology hosts only the
  local specializations; the shared breadth lives in imported reference models.
- **Evidence-led** — a concept is only materialized into the data platform when
  there is **source evidence** for it. Approval is governed in a **Claim
  Registry**, not inferred from whatever an accelerator happens to contain.

The combination resolves the central tension of accelerator approaches: you get
the head-start of a rich reference model **without** dragging its entire surface
into every hub's silver/gold layer. Imports are **claim-driven** — the registry
decides what materializes.

## 2. The canonical lifecycle

```text
discovery → source → domain → mapping → silver → gold → validate → project → diagnose → consume
```

Modeling is a **mid-lifecycle** step that consumes imported, analysed source
evidence — it is not the starting point. The accelerator-first shift does **not**
remove the evidence requirement; it changes *where the breadth comes from*
(imported pack) and *how materialization is gated* (the registry).

## 3. The Claim Registry — single governed source of truth

The per-domain **Claim Registry** at `model/claims/{domain}-claims.yaml`
(schema v1) is the single hand-governed artifact that records *which concepts are
approved to materialize*, with evidence, ownership, disposition, and
silver-contract impact.

- It **replaced** the former `{domain}-alignment.yaml`. Once a domain has a claims
  file, the legacy alignment file is rejected with a migration message — there is
  **no dual path** (DD-EL-1).
- `propose-alignment` output is now **migration input**, not a parallel artifact.
- Each claim carries a `status` lifecycle (`proposed → approved → …`) and a
  `disposition` vocabulary: `claim` / `specialize` / `passthrough` / `skip` /
  `gap`. Custom-column triage maps onto these (`model`→`specialize`/`claim`,
  `silver-passthrough`→`passthrough`, `skip`→`skip`).
- Claim ids are **stable and never reused**; deletions become `deprecated`.

**Governance is deterministic.** A single read-only command, **`check-claims`**
(backend `claim_coverage.py`), enforces coverage with bucket priority
`missing > invalid > incomplete > stale > unverifiable > ok`. It blocks on
missing/invalid/incomplete/stale/duplicate-approved claims and (unless
`--no-source-coverage`) unmapped tables; `--strict` additionally blocks undecided
`proposed` claims; `--warn-only` overrides to exit 0. Leftover `*-alignment.yaml`
files are a hard error regardless of `--warn-only`.

## 4. Imports are claim-driven (A1, not import-all)

The original concept (C2) proposed importing the **full** accelerator pack into
every hub and policing the unclaimed surface with a no-bypass projector. The
**Slice 0A closure spike** measured that against acme-hub and we adopted **A1**
instead (DD-EL-2):

> Each domain's `owl:imports` (and accelerator sub-pack selection) is **generated
> deterministically from approved claims**. Unclaimed imports are simply not
> generated, so they never enter the closure.

- The spike confirmed claim-driven suppression of unclaimed *imports* leaks no FKs
  (correctness **PASS**).
- acme-hub structurally cannot test catalog full-closure resolution or scale
  performance, so C2's motivating perf risk is **deferred, not refuted**. Adopt
  C2 (import-all-then-suppress) only if a separate real large-closure spike clears
  both performance and FK-leak.

This keeps the per-domain diff small and avoids fighting OWL/closure semantics at
scale.

## 5. Three coherent authored surfaces (A2-lite)

Rather than collapsing everything into the registry (A2), we keep **three coherent
authored surfaces**, all generated-and-reviewable in PRs (DD-EL-3, DD-EL-4):

1. the **thin domain ontology** (local specializations);
2. the **extension files** (`{domain}-silver-ext.ttl`, `{domain}-gold-ext.ttl`);
3. the **Claim Registry** (governance).

Claims deterministically drive `owl:imports` + `silverInclude`, and silver / dbt /
powerbi projection is **gated on claim ↔ projection sync** (`check-claims`). The
generated TTL surfaces stay human-reviewable so changes are auditable in GitHub.

## 6. Evidence aggregation, MDM, and ownership

- **`derive-claims`** (DD-EL-5) deterministically aggregates multi-source evidence
  into candidate claims — no AI in the loop for the aggregation itself.
- **MDM / reference-data rules + ownership hardening** live in `check-claims`
  (DD-EL-6): reference/master-data anchors and ownership are validated
  deterministically rather than left to reviewer memory. Discovery now captures
  these master-data anchors **early** (see `kairos-design-discovery`).

## 7. Power BI / source fit-gap (evidence, not authority)

Existing Power BI models are treated as **evidence**, never as authority
(DD-EL-7). `pbi-source-fit-gap` simulates how a source covers an existing PBI
model and seeds gold design, but it cannot override the registry — this avoids the
"as-is → to-be gravity" failure mode where a legacy report dictates the model.

## 8. Change management & contract versioning

New evidence may **expand** silver, but must not **silently mutate** existing
silver (methodology §13 invariant, DD-EL-8).

- **`source-delta-report`** is an advisory, AI-free command that compares a source
  system's bronze vocabulary against the approved registry + SKOS mappings,
  classifies each delta, emits a markdown impact report, and suggests a
  silver/gold **contract version** bump with backward-compatibility tactics.
- `--fail-on-breaking` lets CI enforce the "no silent mutation" invariant.
- The registry carries an optional, byte-stable **contract-version** anchor
  preserved across regeneration. (Surfacing the contract version in projector
  *output* remains tracked future work.)

## 9. Skill interaction — thin-chat (presentation only)

The design skills are **orchestrators**: detail belongs in versioned artifacts,
chat carries only decisions (DD-EL-9). A shared thin-chat convention — four modes
(`guided`, `concise` *(default)*, `silent-artifact`, `review-only`) and a compact
**decision-packet** format — is defined canonically in `kairos-help` §11 and
referenced by every `kairos-design-*` skill.

> **C10 guard:** these modes are *presentation rules over existing checkpoints*,
> **not** a new orchestration engine. Real branching stays in deterministic CLI
> commands; never reimplement workflow logic in prose. The no-autopilot rule is
> preserved — `silent-artifact` never auto-confirms a blocking decision.

## 10. Decision index

| Area | Decision |
|---|---|
| Claim Registry replaces alignment YAML | DD-EL-1 |
| Claim-driven imports (A1; defer import-all/C2) | DD-EL-2 |
| Three reviewable surfaces (A2-lite) + local-class governance | DD-EL-3 |
| Claims drive `owl:imports`/`silverInclude`; projection sync gate | DD-EL-4 |
| `derive-claims` evidence aggregation | DD-EL-5 |
| MDM/reference-data rules + ownership in `check-claims` | DD-EL-6 |
| PBI/source fit-gap as evidence, not authority | DD-EL-7 |
| Change management: `source-delta-report` + contract version | DD-EL-8 |
| Thin-chat skill modes + decision packets (C10 guard) | DD-EL-9 |
| Methodology promotion + 4.0.0-rc1 consolidation, no cross-repo push | DD-EL-10 |

These per-slice decisions are recorded in
[`../implementation/evidence-led-modeling/decision-log.md`](../implementation/evidence-led-modeling/decision-log.md)
and consolidated as **DD-080** in
[`../design/toolkit-design-decisions.md`](../design/toolkit-design-decisions.md).

## 11. Rollout procedure (per-domain batches)

Within a downstream **hub** repository, migrate domains to the methodology in
**small batches**, never in one big-bang:

1. Pick one domain (start with a master-data / reference-anchored domain).
2. Run discovery (capturing MDM anchors) → source import + `analyse-sources`.
3. `propose-alignment` → migrate to the Claim Registry (`model/claims/`).
4. Run `check-claims` and resolve every blocking bucket.
5. For an existing source change, run `source-delta-report` (with
   `--fail-on-breaking` in CI) and review the impact report **before** projecting.
6. Re-run the Slice 0A perf/FK checks for the batch under the A1 import strategy.
7. Project (`silver` → `gold`), validate, and open the PR with the generated
   surfaces reviewable.

> This toolkit repository contains no production domains, so rollout here is
> **documented, not executed**. The acme-hub scenario fixtures exercise the
> pipeline end-to-end in tests.

## 12. Upstream follow-ups (tracked, not yet filed)

The following are intentionally **kept in this repo** as drafted follow-ups rather
than filed as cross-repo issues/PRs (per project direction, 2026-06-16). File them
as toolkit issues when the work is scheduled:

1. **Skill Gate-6 relaxation** — relax the modeling skills' source-evidence Gate 6
   from hard-blocking to accelerator-first claim-driven, so hubs adopting this
   methodology do not run "against the grain". *Durability depends on this
   landing.*
2. **Scaffold foundation template** — ship a `_foundation.ttl` accelerator-import
   template in the scaffold so new hubs get the single shared import layer by
   default.
3. **Routing updates** — update the skill routing guidance to reflect the
   registry-driven lifecycle (discovery MDM anchors, `derive-claims`,
   `check-claims`, `source-delta-report`).

## 13. Status & versioning

All evidence-led work (slices 0A–8) ships as a single release candidate
**`4.0.0-rc1`**. The interim `4.0.0`–`4.6.0` development bumps are folded into the
`4.0.0-rc1` CHANGELOG section; no further version bumps are made for this track.
Nothing in this work is pushed to other repositories.
