# Recommendation — Accelerator-First Ontology Modeling

> Review of `.drafts/accelerator-first-modeling-plan.md`.
> Status: **Conditional Go — spike first, commit later.** The mechanics are
> sound and exist in the toolkit today; the methodology shift carries real
> correctness and durability risk that must be retired with a measured POC
> *before* the doc is written and before 10 domains are migrated.

---

## 1. Verdict

| Dimension | Assessment |
|---|---|
| **Technical feasibility** | ✅ Confirmed. `silverInclude` (per-class) + `silverIncludeImports` (bulk) drive materialization; unclaimed imports are excluded with informational warnings. See `projector.py:_discover_whitelisted_imports` and `medallion_silver_projector.py:_warn_unclaimed_parents` (DD-021). |
| **Effort-reduction hypothesis** | ⚠️ Unproven. The plan optimizes *import-selection*, which is a small slice of the per-domain loop. Source analysis, `propose-alignment`, and column mapping remain per-domain. |
| **Correctness / philosophy** | ⚠️ High risk. Demoting Gate 6 (source evidence) from blocking to a non-blocking lint trades a guarantee for convenience. |
| **Durability** | ⚠️ Depends on an upstream skill change not owned by this hub. |
| **Performance at full-closure scale** | ⚠️ Under-weighted. Known FK/merge issues (#174/#175/#178) worsen exactly when many classes share ranges — which full-pack import produces. |

**Bottom line:** Don't migrate 10 domains on an unmeasured hypothesis. Run a
one-domain spike that *measures* the saving and *proves* the closure is safe,
then decide.

---

## 2. What to keep from the plan (unchanged)

These elements are well-judged and should survive intact:

1. **Foundation import layer** (`_foundation.ttl`) as a single shared import of
   the accelerator pack — eliminates per-domain import bookkeeping. Good.
2. **Thin per-domain ontologies hosting only CLdN specializations** — correct
   separation of concerns; keeps the diff per domain small.
3. **Claim-driven materialization** via `silverInclude` / `silverIncludeImports`
   — this is the real, supported mechanism (DD-021) and is the right lever.
4. **Worked example on a single domain (party)** before generalizing — keep
   this, but reframe it as the *gate* (see §4), not a documentation exercise.
5. **Upstream follow-up list** rather than editing scaffold-managed skill copies
   in the hub — correct boundary discipline.
6. **Lean specialization rule** (business custom columns default to
   silver-passthrough; promote only for true ref-model gaps) — consistent with
   established preference; keep as the default disposition.

---

## 3. Required changes before adoption

### 3.1 Resolve the evidence question explicitly (the crux)

The plan is ambiguous: it both keeps source evidence ("lightweight lint on
claims") and removes its teeth ("non-blocking"). Choose one and state it:

- **Recommended:** Keep evidence **blocking at the claim boundary, not the
  ontology boundary.** A class may be *imported* freely (zero gate), but
  *claiming* it via `silverInclude` requires passing `check-source-coverage` /
  `check-alignment` for that class's source. This preserves the data-first
  guarantee where it actually matters (materialized tables) while removing the
  per-domain ontology import friction. It is the honest version of the plan's
  intent.
- **Rejected:** Purely non-blocking lint. With 10 domains / 17 sources, lint
  fatigue makes silent over-claiming inevitable, and silver tables (not just the
  ontology) end up modeling fiction.

> Net effect: the gate **moves**, it does not **disappear**. That framing should
> replace "evidence gate → non-blocking lint" throughout the plan and doc.

### 3.2 Enforce ownership, don't just document it

`data-domains.yaml` (`owns` / `does_not_own`) is declared "authoritative," but
nothing prevents two domains from claiming the same class. Add a deterministic,
read-only checker (hub-local script or upstream CLI follow-up) that fails when:

- a class is claimed (`silverInclude`) in a domain whose `data-domains.yaml`
  entry does not `own` it, or
- the same class is claimed in two domains.

Until this exists, downgrade the registry's language from "authoritative
registry preventing double-claim" to "convention; not yet enforced."

### 3.3 Treat the closure-performance risk as a gate, not a caveat

Importing the full 8-pack accelerator into every domain's merged graph:

- inflates `validate` / projection time for *all* domains (per-domain closure
  cost; batch validation does not remove it), and
- amplifies #174/#175/#178 (FK leak / dbt merge), which get worse as more
  classes share ranges — precisely the full-pack situation.

This must be **measured and signed off in the spike** (§4), not deferred.

### 3.4 Split the deliverable

The current single stream (branch + foundation + catalog + party refactor +
ownership table + claim convention + evidence-lint recipe + methodology doc + DD
+ upstream list) is too large to review as one PR. Split into:

- **PR-A (spike / reference implementation):** foundation + catalog wiring +
  party refactor + measurements. Mergeable, reversible, no doc commitments.
- **PR-B (methodology):** doc + DD entry + conventions, written *after* PR-A
  confirms the numbers.
- **PR-C (upstream follow-ups):** issues filed against
  `kairos-ontology-toolkit` (skill routing, Gate 6 accelerator-first mode,
  scaffold foundation template).

### 3.5 Do not auto-populate claims from probabilistic alignment

`propose-alignment` output is confidence-scored, not ground truth.
Auto-filling `silverInclude` from it pushes unverified assumptions into
*materialized* silver tables. Use alignment output as a **suggested candidate
list for human confirmation only**, never as the claim source of record.

---

## 4. Gate 0 — the spike (do this first)

A single-domain proof that retires the three open risks (saving, correctness,
performance). **No methodology doc until this passes.**

**Scope:** party domain only.

**Steps**
1. Baseline measure: record current effort/time to stand up party the existing
   data-first way (or reconstruct from git history if already built).
2. Create `model/ontologies/_foundation.ttl` importing the accelerator pack;
   wire `catalog-v001.xml`; run `uv run kairos-ontology validate` and confirm
   the full import closure resolves with **zero** unresolved imports.
3. Refactor party to the thin pattern (import foundation + CLdN specializations
   only); claim the needed classes via `silverInclude` / `silverIncludeImports`.
4. Project party **silver + dbt** across the full closure.

**Pass criteria (all must hold)**
- [ ] Closure resolves cleanly; validate succeeds.
- [ ] Silver + dbt projection wall-time is acceptable at full-closure scale
      (record the number; compare to a single-module-import baseline).
- [ ] **No FK leak / phantom refs** from unclaimed imported classes — explicitly
      check against #174/#175/#178 symptoms. Unclaimed classes must be reliably
      skipped.
- [ ] Claimed-class set matches `data-domains.yaml` ownership for party.
- [ ] Measured end-to-end effort for party is **lower** than the data-first
      baseline by a margin that justifies migrating 9 more domains.

**If any criterion fails:** stop and reassess. A failed perf/FK criterion likely
means "import the relevant *sub-packs*, not the entire accelerator" — a smaller
inversion that keeps most of the benefit without the full-closure blast radius.

---

## 5. Recommended phased path

| Phase | Output | Gate |
|---|---|---|
| **0. Spike** | PR-A: foundation + catalog + party refactor + measurements | §4 pass criteria |
| **1. Decide** | Evidence model (§3.1) + ownership enforcement (§3.2) decisions recorded | Sign-off on numbers + correctness |
| **2. Methodology** | PR-B: `docs/methodology/accelerator-first-modeling.md` + DD entry | Reflects *measured* reality, not hypothesis |
| **3. Tooling** | Ownership/claim checker; reusable silver-ext claim template; blueprint scaffolding from `data-domains.yaml` | Checker green on party |
| **4. Roll-out** | Migrate remaining domains in small batches | Each batch re-runs §4 perf/FK checks |
| **5. Upstream** | PR-C: toolkit issues (skill Gate 6 mode, scaffold template, routing) | Filed; tracked for durability |

---

## 6. Open decisions for the user

1. **Evidence model:** blocking-at-claim (recommended) vs non-blocking lint?
2. **Closure scope:** full 8-pack import vs per-domain sub-pack import as the
   fallback if the spike shows perf/FK problems?
3. **Ownership enforcement:** build the checker now (hub-local) or defer to an
   upstream CLI follow-up and run on convention meanwhile?
4. **Off-skill tolerance:** is CLdN willing to run `kairos-design-domain`
   "against the grain" (it will keep steering to data-first) until the upstream
   skill change lands?

---

## 7. Risk register

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| R1 | Effort saving is marginal (import-selection ≠ the expensive step) | High | Gate-0 baseline measurement before commit |
| R2 | Silent over-claiming → silver tables model fiction | High | Blocking evidence at claim boundary (§3.1) |
| R3 | Full-closure FK leak / dbt merge (#174/#175/#178) | High | Gate-0 FK check; sub-pack fallback |
| R4 | Double-claim across domains | Medium | Ownership/claim checker (§3.2) |
| R5 | Methodology diverges from upstream skills indefinitely | Medium | PR-C upstream follow-ups; explicit off-skill decision |
| R6 | Auto-claims from alignment inject unverified assumptions | Medium | Human-confirm only; never auto-source-of-record |
| R7 | Unreviewable mega-PR | Low | Split A/B/C (§3.4) |

---

## 8. Leveraging existing customer assets (samples, mapping analyses, Power BIs)

Customers usually arrive with three asset types. Far from being side inputs,
these are the **strongest claim evidence** the revised approach needs (§3.1) —
they let us *pre-populate* claims and specializations from human-authored,
production-validated artifacts instead of hand-authoring or trusting
probabilistic alignment (§3.5). The toolkit already has an intake path for each.

### 8.1 Existing Power BI / TMDL — a gold model in reverse
`import-tmdl` parses a PBIP/SemanticModel/`.tmdl` and emits an **Engineering
Pack** (tables, columns, measures, relationships) plus a **Concept Mapping YAML**
with per-table disposition and relationships (`import_tmdl.py:98,195`). In
accelerator-first this is gold:

- **Claim list:** dimensions/facts that exist in a production report are
  prime `silverInclude` candidates — the business demonstrably uses them.
- **Gold-ext seed:** measures → DAX/measure definitions; hierarchies → dimension
  hierarchies; feeds `kairos-design-gold` with a head-start.
- **FK / junction hints:** TMDL relationships → silver FK declarations.
- **Glossary:** report-friendly names → business terminology
  (`kairos-design-discovery` / glossary overlay).

### 8.2 Samples (CSV / Excel) — claim evidence
Flatfile import → `analyse-sources` (affinity) → `propose-alignment`
(column→property), with PII masking via `_samples.py`. Samples provide real
cardinality, enums, formats, and FK shape, which:

- **satisfy the blocking-at-claim gate** (`check-source-coverage` /
  `check-alignment`) — evidence becomes a by-product of intake, not extra work;
- inform the **specialize-vs-silver-passthrough** decision (lean rule, §2 item 6).

### 8.3 Customer mapping analyses — candidate mappings
Pre-existing source→target spreadsheets seed the concept-mapping YAML / SKOS
mappings and pre-fill `propose-alignment`, confirming claims faster.

### 8.4 Proposed intake stage (front of the lifecycle)

| Asset | Command | Output | Feeds |
|---|---|---|---|
| Power BI / TMDL | `import-tmdl` | Engineering Pack + Concept Mapping YAML | claim candidates, gold-ext seed, FK hints, glossary |
| Samples | flatfile import → `analyse-sources` | affinity + masked samples | claim evidence, specialize/passthrough |
| Mapping analyses | concept-mapping YAML / SKOS | candidate mappings | pre-fill `propose-alignment`, confirm claims |

Run this **once per customer, up front**, then derive the claim list and gold
seed from the aggregate. This is the genuine effort win the original plan
reached for — grounded in customer-validated artifacts rather than LLM guesses.

### 8.5 Caveats (keep the critical lens)
- **A PBI is "as-is", not "to-be".** It is often denormalized, carries local
  hacks, orphan measures, and inconsistent naming. Use it as **claim and
  gold-design evidence only** — the accelerator stays the model authority. Do
  not cargo-cult a messy report into the ontology.
- **Mapping analyses are frequently stale/partial.** Treat as *candidate*
  evidence requiring human confirmation — never source-of-record (same rule as
  §3.5).
- **PII in samples** is masked by `_samples.py`; keep raw customer extracts out
  of the repo.

### 8.6 Upstream follow-ups this surfaces (add to PR-C)
- A `derive-claims` helper: aggregate `import-tmdl` dispositions +
  `analyse-sources` affinity + `propose-alignment` into a suggested
  `silverInclude` candidate set (human-confirmed, not auto-applied).
- A `tmdl → gold-ext` seed generator (measures + hierarchies) to bootstrap
  `kairos-design-gold` from an existing report.

---

## 9. When an accelerator concept doesn't fit the client

Guiding principle: **the accelerator is authoritative but not immutable, and a
bad-fit concept costs nothing if it is never claimed.** Because the model is
import-all / materialize-on-claim (DD-021), "too far off" is a routing decision,
not a blocker. Apply the cheapest fitting rung of this ladder:

| # | Mismatch | Approach | Mechanism |
|---|---|---|---|
| 1 | **Terminology only** (concept right, label foreign) | Relabel, don't fork | SKOS `altLabel` / glossary overlay (`kairos-design-discovery`) + business naming in gold/Power BI |
| 2 | **Concept irrelevant** | Don't claim it | Leave unclaimed — projector skips unclaimed imports (zero cost) |
| 3 | **Granularity / extra attributes** (too broad/narrow, missing fields) | Specialize | Subclass in the thin per-domain ontology (e.g. carrier vs operator split) + CLdN data properties, or silver-passthrough extras (lean rule); silver discriminator folding handles subtypes |
| 4 | **Partial conceptual overlap** | Map loosely | `skos:closeMatch` / `relatedMatch` (not `exactMatch`) at lower confidence — keeps traceability without asserting identity |
| 5 | **Genuine semantic gap** (nothing fits) | Model CLdN-native | New class in the **CLdN namespace**; register an owner in `data-domains.yaml`; **do NOT fake `subClassOf`** onto the ill-fitting standard concept |
| 6 | **Recurring / systematic** (same gap across clients) | Escalate upstream | Accelerator gap request against the logistics pack — evolve the standard, don't patch per-hub |

### 9.1 Guardrails
- **Never subclass merely to reuse columns.** If semantics differ, model native
  (rung 5). A false `subClassOf` produces wrong inferences and pollutes the
  standard's hierarchy — this is the primary anti-pattern.
- **Keep client-native classes in the CLdN namespace**, clearly distinguishable
  from accelerator classes, so the standard stays clean and deviations are
  auditable.
- **Mismatch rate is a diagnostic.** A high proportion of "too far off" concepts
  usually means the *pack selection* is wrong, not the concepts — revisit the
  full-pack-vs-sub-pack decision (§3.3) before proliferating native classes.

### 9.2 Governance
Record each rung-5/rung-6 deviation (native class or upstream gap) in the hub
deviation log / DD entry, with: the accelerator concept it diverges from, the
reason it doesn't fit, and whether it is client-specific (stays) or a standard
gap (filed upstream). This keeps the "where lean-ness lives" question (§2)
answerable and prevents silent drift from the standard.

---

## 10. Silver-passthrough — rationale and when to use it

Silver-passthrough is one of three dispositions for a source column at
Checkpoint 3b: `model` / `silver-passthrough` / `skip`
(`alignment_coverage.py:113`). It means **carry the column into the silver table
but do not promote it to a domain ontology property** — recorded as a mapping
with no `owl:DatatypeProperty` behind it. It is the default for business custom
columns under the lean rule (§2 item 6) and is load-bearing in accelerator-first.

### 10.1 Why it exists
**The ontology and the warehouse answer different questions.**
- The **ontology** models *shared business meaning* — concepts reused across
  sources, mapped, queried conceptually, or governed.
- The **silver layer** is *data carriage* — it must physically land the columns
  the business uses.

Not every source column has shared meaning (a vendor slot like `CFSTRING33`, a
single-source local field). Passthrough lands it in silver without forcing it to
become a first-class concept.

### 10.2 The three dispositions (a value ladder)
| Disposition | Meaning | Outcome |
|---|---|---|
| `model` | Genuine business concept with shared/reused meaning | Becomes a domain property (or a specialization if the accelerator lacks it) |
| `silver-passthrough` | Real data worth keeping, no ontological value | Lands in silver, recorded in the mapping, **no** domain property |
| `skip` | Technical/audit noise (row hashes, ETL timestamps, internal surrogate keys) | Not modeled **and** not carried |

So passthrough is the "keep the data, skip the concept" middle option — it is
**not** data loss (that is `skip`).

### 10.3 Why it is the right default
- **Keeps the ontology lean.** Every modeled property carries fixed cost
  (`label`, `comment`, `domain`, `range`, SKOS mapping, possibly SHACL,
  projection wiring). Promoting every column inflates the model with low-value
  noise that is expensive to review and maintain.
- **Reversible / deferrable.** Passthrough is the safe default; if a column later
  proves to have shared meaning (appears in a second source, gets queried), you
  promote it to a property *then*. Promoting late is cheap; modeling prematurely
  and removing later is costly.

### 10.4 Why it matters more in accelerator-first
With a standard-fixed ontology, passthrough is the **pressure valve for
client-specific columns** that map to no accelerator concept but still must reach
silver. It is how you keep the standard clean while still carrying every client
field, complementing rungs 2–3 of the §9 fit ladder (don't claim / specialize).
Default rule: **business custom columns → silver-passthrough; promote to a
property only for a true reference-model gap** (e.g. IBAN/BIC/creditLimit on
party).

---

## 11. Do we still need affinity and proposal-fit?

Yes — but `analyse-sources` (affinity) and `propose-alignment` (proposal-fit)
are **repurposed**, not retired. Each has two sub-functions; accelerator-first
obsoletes one and elevates the other, making them the primary automation for
deriving claims and mappings rather than preliminary model-building steps.

### 11.1 `analyse-sources` (affinity)
| Sub-function | Data-first role | Accelerator-first |
|---|---|---|
| **Import selection** ("which reference modules to import?") | Core driver | ❌ Obsolete — the whole pack is imported once; no per-domain import decision remains |
| **Table → entity/domain routing** ("which class does this table map to, in which domain?") | Secondary | ✅ Elevated to primary — drives the **claim list** (`silverInclude`) and **ownership routing** (which domain claims it); feeds the under-coverage side of `check-source-coverage` |

### 11.2 `propose-alignment` (proposal-fit)
| Sub-function | Data-first role | Accelerator-first |
|---|---|---|
| **Discover ref-model gaps to model** (bottom-up ontology construction) | Core driver | ⬇️ Shrinks — accelerator is fixed; specialize only for §9 rung-5 gaps |
| **Column → property mapping + disposition** (`model`/`passthrough`/`skip`) | Secondary | ✅ Elevated to primary — produces SKOS mappings, justifies each claim (over-claim check: claimed class with no mapped columns), drives passthrough/skip triage |

### 11.3 Net effect
Both shift from *"inputs that construct the model"* to *"inputs that select
claims, build mappings, and satisfy the evidence-at-claim gate (§3.1)."* They are
the bridge between the fixed accelerator and the customer's data, and they are
exactly what the §8.6 `derive-claims` helper would consume to **auto-suggest
claims instead of hand-authoring them**. In a claim-driven world they are the
primary automation, not a preliminary.

### 11.4 Interaction with customer assets (§8)
When the customer supplies a **mapping analysis** or an **existing Power BI**,
that is already human-authored affinity/alignment evidence. In that case run
these tools to **fill gaps and confirm**, not from scratch — reducing (not
eliminating) reliance on them.

---

## 12. One-line summary

**Keep the inversion's mechanics, move (don't delete) the evidence gate to the
claim boundary, enforce ownership in code, and prove perf + FK safety on party
before writing the doc or migrating the other nine domains.**
