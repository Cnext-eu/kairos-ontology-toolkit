# Silver-First Mapping — Simplified Design

**Status:** Draft plan (rev 5 — aspirational as *derived* state, authorities canonicalized)
**Date:** 2026-07-19
**Scope:** Reducing Bronze-to-Silver effort while keeping projection deterministic
**Baseline:** Kairos Ontology Toolkit v4.4.0

## 1. The idea in one sentence

**Silver is a set of dbt models. The industry reference model + discovery
conformance *auto-propose the claims* that the existing Silver projection already
requires, so a hub can reach a target-first Silver stub early, expands it
iteratively as more knowledge is encoded, and every regeneration stays a
deterministic, ontology-grounded projection of that encoded knowledge.**

> Day-one caveat: the "auto-propose from conformance" step depends on promoting
> conformance from warn-only (DD-090) to an auto-proposal driver — an **undecided
> status change (§11.1)**. Until that lands, auto-proposal is opt-in/manual and the
> "target-first on day one" framing is aspirational, not a shipped capability.

Key correction over earlier revisions: we do **not** introduce a second
materialization authority. The **Claim Registry stays the single source of truth
for what materializes (DD-EL-1)**. We change *how claims get populated* (auto,
forward-derived) and add a **derived** `aspirational` view of a claim so a claim can
project a **stub** before it is bound.

> Authority note: **DD-EL-1** and **DD-EL-5** currently live only in the provisional
> `docs/archive/evidence-led-modeling/decision-log.md` (whose own slice-0b note says
> "assign final DD-NNN and merge"). They are **not yet promoted** into the canonical
> `docs/design/toolkit-design-decisions.md` register. Promoting them to real DD-NNN
> entries is a prerequisite (§11.0) before this design's single-authority invariant
> can be considered settled.

## 2. Direction of derivation (important)

**Forward, not reverse.** We do not reverse-engineer claims from generated Silver.

```
industry model + conformance artifact ──► auto-propose ASPIRATIONAL claims
                                              │  (existing propose-alignment /
                                              │   derive-claims paths, DD-EL-5)
                                              ▼
                              existing claim-driven Silver projection
                                              │
                                              ▼
                          contract-first dbt stub  ──(bind mappings)──►  bound model
```

The projection generator's contract is unchanged: it reads claims + ontology +
silver-ext + mappings. We only (a) auto-fill the claims it consumes and (b) let an
`aspirational` claim emit a stub instead of being skipped.

## 3. The determinism invariant (corrected)

> Silver is a **deterministic projection of encoded knowledge**. Given the same
> inputs, regeneration is reproducible and every column has a declared provenance.

Provenance of a Silver column is one of:
- an ontology property / ObjectProperty (business meaning), **or**
- a `kairos-ext:` silver annotation (physical mechanics), **or**
- a **deterministic projector convention** (`{model}_sk`, `{model}_iri`, SCD/audit
  columns) — these come from conventions/defaults, not annotations.

Full input set of the projection (rev 3 under-stated this):
ontology · silver-ext · SKOS mappings · SHACL shapes (tests) · source vocabularies
(enum `accepted_values`) · conformance selection · claims · contracted dbt models
(DD-092) · reference-model version/closure · target platform · projection config.

**Known non-determinism to fix first:** generated SQL currently embeds a fresh
timestamp (`silver_model.sql.jinja2`). Byte-identical output requires making the
timestamp an input (or removing it). "Deterministic" in this doc means
*reproducible from encoded inputs*, not "identical regardless of tool version."

**Generated dbt is not hand-edited** — with the standing exception of handwritten
contracted transforms under `integration/transforms/dbt/` (DD-092). Knowledge is
encoded upstream (§7) and re-projected.

## 4. Target-first, bind-later

A dbt model has two parts with different inputs:

| Part | What it is | Primary inputs |
|---|---|---|
| `_models.yml` + column list (**schema stub**) | table, columns, types, tests, FK, grain | ontology + silver-ext + SHACL + platform types |
| `.sql` SELECT body (**transform**) | reads Bronze, casts, renames | mappings (+ contracted dbt) |

1. **Target-first.** An **aspirational claim** (see §4a — *derived*, not persisted)
   projects a **stub model** (`select cast(null as <type>) as <col> ... where false`)
   plus its schema YAML — from ontology + silver-ext, **no mappings needed**. This is
   the stable Silver *target*.
2. **Bind later.** As mappings arrive, the projector fills the SELECT body; the claim
   is no longer *derived* as aspirational once a mapping is bound.

> Column typability caveat: not every column is typable pre-binding. SK/audit/SCD
> convention columns and columns carrying an explicit `kairos-ext:silverDataType`
> **are** typable from ontology + silver-ext. Columns whose physical type is
> **source-derived** (resolved during mapping) are **not** typable until bound — the
> stub emits them as untyped placeholders (or omits their `data_type`), so they are
> *not* target-first. State this per-column rather than claiming a fully typed stub.

> Note: today `_models.yml` is **not** an enforced dbt contract
> (`contract.enforced` is not emitted; types live under `meta.data_type`).
> Whether to promote it to an enforced contract is an open decision (§11), not an
> existing capability.

### 4a. `aspirational` is a *derived* state, not a persisted flag

`aspirational` = a claim whose `status` is materialization-eligible (`approved`)
**and** which has **no bound mapping yet**. "Is a mapping bound?" is already
derivable from the mappings input, so we do **not** persist an `is_aspirational`
boolean on the claim / `SilverImpact` — persisting it would duplicate derivable
state and can drift (the anti-pattern §10 forbids). The existing `status`
(proposed/approved/rejected/deferred/deprecated) and `disposition`
(claim/specialize/passthrough/skip/gap) axes and their transition machine stay
**unchanged**; the projector computes `aspirational` at projection time.

## 5. The iterative enrichment loop

Silver grows by **encoding more knowledge and re-projecting** — never by editing
output:

```
  ┌─> encode into an authority (§7): a class, a property, a silver-ext annotation,
  │     a conformance outcome, a mapping, a claim decision, a drift resolution
  │
  │    project ─► deterministic Silver dbt models (stubs + bound bodies)
  │
  │    inspect ─► target view / tests / drift report show what is still
  │               aspirational, unbound, or deviating
  │
  └─── repeat
```

Iteration is **safe but not necessarily monotonic**: re-projection reflects the
current encoded state, so a changed mapping / conformance outcome / claim
disposition / reference-model version *can* reshape or remove output. Determinism
prevents *unexplained* drift; it does not promise "nothing is ever removed."

## 6. Selection & leanness (corrected)

**Claims select; conformance proposes.** The discovery **conformance artifact**
(DD-090) proposes candidates, but selection is not tier-only:

- Use **both** archetype tier (`required`/`recommended`/`optional`) **and** the
  per-concept **business outcome** (`conforms` / `partial` / `deviates` /
  `not-applicable`). A `required` concept marked `not-applicable` for this client
  is **not** emitted.
- Conformance is **warn-only today (DD-090)**; driving auto-proposal from it is a
  status change that must be decided explicitly (§11).
- **Pruning stays claim-side:** rejecting/deferring an aspirational claim removes
  the stub. "required-for-archetype ≠ required-for-this-client" — the claim
  decision is where a hub keeps Silver lean (respecting the lean-model
  convention).

## 7. Where knowledge is encoded (the only authorities)

Every iteration writes into one of these — never into generated output:

| Knowledge | Encoded in | Authority |
|---|---|---|
| Classes, properties, relationships, keys | ontology | OWL |
| Which concepts materialize (incl. `aspirational`) | Claim Registry | claims (DD-EL-1) |
| Physical: SK, SCD, audit, FK, materialization | `{domain}-silver-ext.ttl` | `kairos-ext` |
| Candidate selection evidence | conformance artifact | DD-090 (warn-only today) |
| Bronze → Silver binding + transforms | SKOS mappings (`kairos-map:`) | mappings |
| Complex joins/windows/grain | contracted dbt model | DD-092 |
| Tests / constraints | SHACL shapes | shapes |
| Deviations client-vs-industry (advisory) | `-drift.yaml` (§8) | warn-only |

## 8. Drift report (optional early-warning)

A deterministic, warn-only `integration/discovery/{archetype}-drift.yaml` compares
client evidence (affinity, samples, BI) against the industry model (archetype
topology) and flags where the industry contract won't fit — attribute-surplus,
cardinality-drift, granularity-drift, reference-data-drift, type-drift. It feeds
extensions and claim proposals but sits **off the critical path**. Full spec in a
companion note.

## 9. The real change set (not a "single change")

Rev 3 called this one code change; the rubber-duck review showed it ripples.
Honest scope:

1. **Derived `aspirational` computation** in the projector (§4a): a claim is
   aspirational when `status` is materialization-eligible **and** no mapping is
   bound. **No new persisted field** on the claim / `SilverImpact` model. Claims are
   auto-proposed by conformance-driven proposal (`propose-alignment` / `derive-claims`).
2. **Projector: emit a stub** for an aspirational claim instead of skipping
   it — this deliberately relaxes the current "no broken placeholders" rule
   (`medallion_dbt_projector.py`), **gated to aspirational claims + opt-in flag**.
   Emit typed columns where typable, untyped placeholders where source-derived (§4).
3. **`claim_projection_sync`** generates `silverInclude` for aspirational claims too,
   so `check-claims` does **not** flag them as drift.
4. **Folding review:** confirm `_nearest_claimed_ancestor` treats aspirational
   entities correctly (they enter the projected class set, so they can change
   inheritance/FK folding — DD-021). May need renaming to "materialized ancestor".
5. **Coverage & release gate:** aspirational stubs are **excluded** from DD-061/DD-093
   source coverage and are **not release-eligible** merely by existing. The gate owner
   is the release/`--strict` path (§11.4) — it must fail release while any required
   stub remains aspirational; "excluded from coverage" alone is not a gate.
6. **Determinism fix:** timestamp made an input (§3).
7. **Scenario tests:** `acme-hub` cases for stub emission, bind transition, and
   drift-free `check-claims`.

## 10. What we explicitly do NOT build

- No second materialization authority — claims stay authoritative (DD-EL-1).
- No new persisted claim state — `aspirational` is **derived** at projection time
  (§4a), never stored on the claim / `SilverImpact` model.
- No new "Silver target contract" artifact — it's `_models.yml` (+ possible
  future `contract.enforced` promotion).
- No new disposition ledger — reuse claim dispositions.
- No new versioning scheme — reuse `SilverImpact.change_type` + ref-model version.
- No hand-edited Silver (except DD-092 contracted transforms).
- No mandatory hand-authored claims — they are auto-proposed, then decided.

## 11. Open decisions

0. **Canonicalize the authorities.** Promote **DD-EL-1** (claim registry = single
   materialization authority) and **DD-EL-5** (`derive-claims`) from the provisional
   `docs/archive/evidence-led-modeling/decision-log.md` into real DD-NNN entries in
   `docs/design/toolkit-design-decisions.md`. **Prerequisite** — the single-authority
   invariant is un-anchored until this is done.
1. Promote conformance from warn-only to an accepted auto-proposal driver — which
   status/gate, and the tier×outcome selection matrix. (The §1 "target-first" value
   proposition depends on this decision.)
2. *(Resolved — see §4a.)* `aspirational` is a **derived** state, not a persisted
   flag, so no `_models.yml`/tag/config representation is needed. A read-only
   `meta.is_aspirational` **may** still be emitted for tooling visibility, but it is
   computed, never authored.
3. Does `_models.yml` become an enforced dbt contract (`contract.enforced` + typed
   columns), and if so when relative to binding? Note the typability caveat (§4):
   source-derived columns can't be typed pre-binding.
4. **(Required, not merely open.)** Empty-stub test semantics: standard tests pass
   vacuously on 0 rows, giving false-green CI. Define separate states — schema-valid
   vs bound vs data-valid vs release-eligible — and make `--strict` **block release**
   while any required stub is aspirational. This gate is part of the design (§9.5),
   not deferrable.
5. Rename `_nearest_claimed_ancestor` → "materialized ancestor" and confirm folding
   under aspirational membership.
6. Where the drift report plugs into the loop.

## 12. First concrete step

**Step 0 (ship alone first).** Fix the timestamp non-determinism (§3): make
`generated_at` a projection input (or drop it from generated SQL) and assert
byte-identical re-projection on `acme-hub`. This is independent, low-risk, and
valuable on its own — land it before any stub/claim work.

Then, behind an opt-in flag (feature-off output unchanged):

1. Add conformance-driven auto-proposal (reuse `propose-alignment` / `derive-claims`)
   and the **derived** aspirational computation (§4a) — no new persisted field.
2. Add stub emission for aspirational claims + `claim_projection_sync` handling.
3. Prove on `acme-hub`: select an archetype → auto-propose claims → project stubs
   with zero mappings → `check-claims` clean → bind one entity → re-project → assert
   reproducibility and per-column provenance.
4. Defer the drift report and any `contract.enforced` promotion until the
   stub→bind loop is validated. Canonicalize DD-EL-1/DD-EL-5 (§11.0) in parallel.
