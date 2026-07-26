# Toolkit issues encountered during the Party design phase

**Date:** 2026-07-26
**Hub:** cldn-ontology-hub (branch `petervk/4.7/rc5`)
**Toolkit:** kairos-ontology-toolkit v4.7.0rc5
**Context:** Reference-model update (logistics 1.5.0 → 1.6.0) + Party domain
regeneration (`party.ttl`, `party-silver-ext.ttl`, curated `party-claims.yaml`).

> Status: **DRAFT** — raised for triage with the toolkit maintainers. Severity /
> confidence are the author's assessment, not a formal classification.

---

## 1. `claims-to-silver-ext` hard-fails on unrelated `legacy-fibo-*` modules (BLOCKER)

**Severity:** High · **Confidence:** High · **Type:** Toolkit robustness / scoping

### What happened
Running the sanctioned managed-block sync for a single domain:

```bash
kairos-ontology claims-to-silver-ext --domains party
```

fails with `❌ party: drift remains`, followed by ~75 errors of the form:

```
Module 'legacy-fibo-actus-contract-terms' failed to load: Ontology closure is
incomplete; rerun with degraded=True only when partial semantics are explicitly
acceptable.
Module 'legacy-fibo-be-legal-persons' failed to load: ...
Module 'legacy-fibo-fnd-parties' failed to load: ...
... (every legacy-fibo-* module in the financial-services accelerator)
```

### Why it's a problem
- The Party domain imports **only** `bsp/party` (+ hub `_foundation`). It has
  **nothing to do with FIBO / the financial-services accelerator**, yet the sync
  is blocked by those modules.
- The command appears to **unconditionally load the entire reference-model module
  registry** rather than only the modules reachable from the domain being synced.
  No accelerator is pinned in the hub config, so there is no reason to load the
  financial-services modules at all for a `party` sync.
- Because this is the **only sanctioned path** to produce the
  `# >>> kairos-managed` import/`silverInclude` block, the whole domain is stuck:
  the block cannot be generated, and the same failure will block **projection
  preflight hub-wide** (any target that runs the managed-import planner).

### Key distinction (narrows the fix)
The **read/check** path is unaffected: `check-claims` sync
(`evaluate_domain_projection_sync`) runs Registry-only (`module_context = None`)
and reported no FIBO errors — only a layout nudge. It is specifically the
**write/sync** command (`claims-to-silver-ext`) that force-loads every module.

### Suggested fixes (any one would unblock)
1. **Scope module loading to the domain/accelerator being synced** — only load
   modules reachable from the domain's approved import closure, not the full
   registry.
2. **Degrade gracefully on unrelated module load failures** — a module that is
   not part of the target domain's closure should produce a warning, not abort
   the sync (the error text itself hints at a `degraded=True` option that is not
   surfaced on the CLI).
3. **Add a CLI escape hatch** (e.g. `--degraded` / `--skip-unresolved-modules`)
   so an operator can proceed when unrelated modules are broken.

### Workaround used
Authored `party.ttl` + the `silverInclude` managed block **by hand** with rdflib
(per DD-072, no string concatenation), placing the Registry-controlled triples in
canonical `# >>> kairos-managed … # <<< kairos-managed` blocks. After this,
`check-claims --domains party --strict` reports:
- `✓ party: valid, complete, and up to date`
- `✓ party: claims/imports/includes in sync`

This proves the Party artifacts are correct — the blocker is purely the sync
command's global module loading.

---

## 2. Two `legacy-fibo-*` modules are unresolvable through the catalog

**Severity:** Medium · **Confidence:** High · **Type:** Reference-model packaging / catalog defect

Within the same failure, three modules fail not on closure but on **catalog
resolution**:

```
Module 'legacy-fibo-loan-mortgage-loans' cannot be resolved through the catalog
Module 'legacy-fibo-md-derivatives-pricing' cannot be resolved through the catalog
Module 'legacy-fibo-md-security-temporal' cannot be resolved through the catalog
```

This looks like a **reference-model packaging defect** (module declared/referenced
but missing a `catalog-v001.xml` mapping or the backing TTL), independent of the
"incomplete closure" errors. It arrived with the upstream update to `main`
(commit `c432b993`, logistics accelerator 1.6.0) — worth verifying against the
`Cnext-eu/kairos-ontology-referencemodels` repo and fixing upstream.

---

## 3. `check-inventory` fails on the same FIBO modules after a refmodel update

**Severity:** Medium · **Confidence:** Medium · **Type:** Same root cause as #1/#2

After `update-refmodels` + `generate-inventory`, `check-inventory` still reports
failures for `financial-services-accelerator`, `ACTUS-examples`, and `scaffolding`
— all traceable to the same legacy-FIBO closure/catalog problem. All
**Party-relevant** inventories (`bsp-party`, `imo-party`, `dcsa-party`, `mmt-*`,
`tic-*`, `wco-*`) are fresh and green, so Party was not blocked — but the global
`check-inventory` exit code is red because of unrelated accelerators. Consider
whether inventory/health checks should be **scopeable** (per accelerator/domain)
so an unrelated broken accelerator doesn't fail the whole check.

---

## 4. `propose-alignment` produced a few semantically wrong suggestions (quality)

**Severity:** Low · **Confidence:** Medium · **Type:** LLM alignment quality (advisory)

During curation of `party-claims.yaml`, several proposed column→property mappings
were semantically off and had to be re-dispositioned by hand, e.g.:

- `companies.is_customer` → `partyIdentifier` (should be a local boolean role flag)
- `companies.billing_country` → `registrationCountry` (different concept)
- `companies.reference_numbers` → `partyIdentifier`

Conversely, some obvious anchors (name/code/`company_id` FK) were initially not
proposed as claims. This is inherent LLM variance rather than a hard bug, but two
product-level improvements would reduce manual curation:
- Bias boolean/`is_*`/`has_*` source columns away from identifier properties.
- Flag low-confidence identifier matches for review instead of silently emitting
  them as `claim` disposition.

Not blocking — the strict claim-decision gate (`check-claims --strict`) correctly
forced every claim to be decided, which surfaced these.

---

# Additions — mapping design session (2026-07-26)

_Raised while mapping the Qargo sources to Party (`qargo companies → bsp:TradeParty`,
and the two contracted virtual sources `int_qargo_contact_conformed → bsp:Contact` /
`int_qargo_billing_address_conformed → bsp-reference-data:Address`). These are on top of
issues #1–#4 above._

## 5. Phase logs / status drift from the real artifacts — "done" logs referenced a deleted deliverable (HIGH VALUE)

**Severity:** High · **Confidence:** High · **Type:** Lifecycle-state integrity

### What happened
The 2026-07-18 dbt-transformation phase logs both marked their SKOS mapping step
**done**:
- `qargo-contact-conformed.md`: `[x] Map the managed Contact virtual source through SKOS`
- `qargo-billing-address-conformed.md`: `[x] Mapped the managed virtual Address source
  through SKOS in model/mappings/custom-transformations-to-party.ttl`

…but `model/mappings/custom-transformations-to-party.ttl` **did not exist on disk**. A
2026-07-26 reset had regenerated `party.ttl` / `party-silver-ext.ttl` as fresh scaffolds
and (apparently) dropped the mapping file and the Address domain scaffolding, while the
phase logs and their `[x]` checkboxes still claimed the work was complete.

### Why it's a problem
- The lifecycle state (`status.md` + phase logs) can assert "done" for work whose
  deliverable file is gone. Nothing cross-checks a log's claimed deliverable against the
  filesystem, so the drift is silent and only found by manual inspection.
- The `kairos-ontology status` scan is filesystem-derived (good), but the human-facing
  phase logs are not reconciled against it — the two can disagree indefinitely.

### Suggested fixes
1. **Deliverable-existence check:** a `status` / lint pass should verify that every
   phase-log `xref` (and any file path referenced in a `[x]` "done" item) exists, and
   flag `done`-but-missing as a drift error.
2. **Reconcile logs against the scan:** when the deterministic scan disagrees with a
   phase log's `status:`, surface it (e.g. "log says mapping done, scan says
   not-started").
3. **Guard destructive regeneration** (see #6) so this drift is far less likely to occur
   in the first place.

---

## 6. Domain/scaffold regeneration is destructive to hand-authored local properties (HIGH VALUE)

**Severity:** High · **Confidence:** Medium · **Type:** Toolkit robustness / idempotence

### What happened
The 2026-07-26 regeneration of `party.ttl` stripped the previously-approved,
hand-authored Address scaffolding (the `bsp/reference-data` import and the local
`addressCountryCode` / `addressIdentifier` / `billingAddressOfParty` properties recorded
in the 2026-07-18 billing-address dbt log). I had to re-add them by hand to restore the
Address mapping target.

### Why it's a problem
- The managed-block convention (`# >>> kairos-managed … # <<< kairos-managed`) is
  supposed to let the toolkit own only its block and preserve authored content verbatim.
  Here the regeneration behaved as a full-file rewrite, losing local properties that live
  *outside* the managed block.
- Combined with #5, this is how approved design silently disappears: regenerate → local
  work lost → logs still say "done".

### Suggested fixes
1. Regeneration must be **strictly additive outside the managed block** — never rewrite
   or drop hand-authored triples; only replace content inside `# >>> kairos-managed`.
2. If a full rebuild is unavoidable, **archive the prior file** (like DD-071 does for
   phase logs) instead of overwriting, and diff-report what changed.

---

## 7. Turtle `/` in source-column IRIs breaks prefixed names in mapping files (PAPER-CUT)

**Severity:** Low · **Confidence:** High · **Type:** Vocabulary IRI convention / DX

### What happened
The generated virtual-source vocabulary mints column IRIs as
`…#qargoContactConformed/name` (a `/` inside the URI fragment). Writing the mapping with
a prefixed name — `ctf:qargoContactConformed/name` — is **invalid Turtle** (`PN_LOCAL`
disallows `/`), so `rdflib` failed with a `BadSyntax` error and I had to rewrite every
column subject/object as a full `<…>` IRI. That cost a full write-validate round-trip.

### Why it's a problem
- The generator's own IRI shape is not expressible as a prefixed name, so every mapping
  file that references these columns must use verbose full IRIs — easy to get wrong, and
  a silent trap (the `#table/column` form *looks* prefixable).

### Suggested fixes
1. **Mint column IRIs with a prefixable separator** (e.g. `#qargoContactConformed__name`
   or `#qargoContactConformed.name` — both valid in `PN_LOCAL`) instead of `/`.
2. Or have the mapping scaffolder (see efficiency section) emit full-IRI column references
   automatically and document the pitfall in the mapping skill.

---

## 8. No built-in mapping-resolution validator — had to hand-write rdflib (DX)

**Severity:** Medium · **Confidence:** High · **Type:** Missing tooling

### What happened
To confirm a mapping TTL is correct I wanted to check that every
`kairos-map:sourceColumn` resolves to a column in the source vocabulary and every
`kairos-map:targetProperty` resolves to a property in the domain closure. There is no CLI
for this, so I hand-wrote an ad-hoc rdflib script (parse domain + `_foundation` + both
vocabularies + BSP party + reference-data + the mapping, then set-check the IRIs). It's
the single most valuable check for a mapping and it isn't a first-class command.

### Suggested fixes
1. Add `kairos-ontology validate-mapping <file>` (or fold into `validate`) that
   deterministically checks: source columns exist in the referenced vocabulary, target
   properties/classes exist in the domain import closure, and each `ColumnMapping` /
   `TableMapping` is well-formed. Report unresolved IRIs with file+line.

---

## 9. `show-class-inventory` failed; no reliable class-property lookup for mapping (DX)

**Severity:** Medium · **Confidence:** Medium · **Type:** CLI reliability

### What happened
To get the properties of `bsp:Contact` and `bsp-reference-data:Address` (the mapping
targets, incl. inherited), I first tried
`kairos-ontology show-class-inventory --domain party --profile kairos-design` — it exited
**1** with no usable output. I fell back to parsing
`referencemodels-unpacked/*-inventory.yaml` directly with python.

### Why it's a problem
- Looking up "what properties can I map onto class X" is the most common mapping-time
  question; the sanctioned CLI for it failed, forcing manual YAML spelunking.

### Suggested fixes
1. Fix / harden `show-class-inventory` (it should not exit non-zero when the materialized
   inventory is present and green).
2. Provide a focused `list-class-properties <ClassIRI>` that prints direct + inherited
   properties with ranges — the exact table a mapper needs.

---

## 10. `next_phase: source` is a persistent false signal for contract-governed virtual sources

**Severity:** Low · **Confidence:** High · **Type:** Status heuristic

### What happened
Every `status` scan reports `source 🟡 in-progress (1/3)` and therefore
`Next phase: source`, because the two contracted virtual vocabularies under
`custom-transformations/` are intentionally *not* affinity-analysed (their dbt contracts
are the semantic authority) and the `powerbi/` folder is planning-only. So the "next
phase" is permanently wrong and has to be re-explained every session.

### Suggested fixes
1. Let a source instance be marked **intentionally-complete / contract-governed** (e.g. a
   marker file or a status-config entry) so it counts as done for `next_phase` and doesn't
   drag `source` to in-progress forever.
2. Or teach the scan that a `custom-transformations` vocabulary with a valid dbt contract
   is "analysed by contract" and not an incomplete source.

---

# Design-session efficiency analysis (how to make the mapping phase faster)

The Party mapping across both sessions was correct but slower than it needed to be. Below
is what the flow actually cost and where the toolkit could compress it.

### Steps taken this session (and the friction in each)

| # | Step | Time sink | Avoidable? |
|---|------|-----------|-----------|
| 1 | Discover the reset (read 3 phase logs + vocab + silver-ext + party.ttl to find the missing mapping file) | Pure manual archaeology because logs said "done" but the file was gone (#5) | Yes — deliverable-existence check |
| 2 | Re-add Address scaffolding to `party.ttl` by hand | Lost to destructive regeneration (#6) | Yes — non-destructive regen |
| 3 | Look up `Contact` / `Address` properties | `show-class-inventory` failed → parsed inventory YAML by hand (#9) | Yes — fix CLI |
| 4 | Hand-author the mapping TTL | Near-mechanical for exact-name matches (name→contactName, city→city, …) | Mostly — auto-propose |
| 5 | Triage 13 `company_*` columns as out-of-scope | Manual reasoning that they're denormalized TradeParty attrs already mapped elsewhere | Yes — auto-detect duplicate/denormalized columns |
| 6 | First TTL failed to parse (`/` in prefixed names) | Full rewrite to full IRIs (#7) | Yes — scaffolder / IRI convention |
| 7 | Validate IRIs resolve | Ad-hoc rdflib script (#8) | Yes — `validate-mapping` |
| 8 | Update phase logs + fold into `status.md` | Manual, multi-file | Partly — a `close-phase` helper |

### Highest-leverage speedups

1. **`propose-mapping` for virtual sources (biggest win).** A conformed source already
   declares `kairos-dbt:targetClass`, and its columns carry rich `rdfs:label`
   descriptions. A deterministic + optional-LLM `propose-mapping` (sibling of
   `propose-alignment`) could pre-fill exact-name and label-similar column→property
   matches, so the human only *confirms* instead of typing TTL. Steps 3–4 collapse to a
   review.
2. **Auto-exclude denormalized / already-mapped columns.** The 13 `company_*` columns on
   the Contact source are TradeParty attributes already mapped via
   `qargo companies → TradeParty`. The tool can detect "this column's semantics belong to
   another table already mapped to a different class" and pre-mark them out-of-scope
   (step 5).
3. **Mapping scaffolder that emits correct full-IRI skeletons.** Generate the
   `TableMapping` + one `ColumnMapping` stub per source column (with valid full IRIs),
   pre-classified into *proposed / silver-key / passthrough / out-of-scope*. Removes the
   `/`-in-prefix trap (#7) and the boilerplate of step 4.
4. **`validate-mapping` as a first-class command** (#8) — replaces the ad-hoc rdflib
   check and makes step 7 a one-liner.
5. **Deliverable-integrity + non-destructive regen** (#5/#6) — eliminates the entire
   "archaeology + re-author" cost of steps 1–2, which was the single biggest time sink
   this session and was pure rework, not design.

Net: with #1–#3 the mapper's job becomes *confirm a pre-filled table* rather than
*author TTL from scratch*, and with #5/#6 the reset-recovery work (roughly half this
session) simply wouldn't have been necessary.

---

## Summary

| # | Issue | Severity | Type | Blocks Party? |
|---|-------|----------|------|---------------|
| 1 | `claims-to-silver-ext` loads full module registry, hard-fails on unrelated `legacy-fibo-*` | High | Toolkit robustness | Yes (worked around) |
| 2 | 3 `legacy-fibo-*` modules unresolvable through catalog | Medium | Refmodel packaging | No |
| 3 | `check-inventory` red on unrelated FIBO accelerators | Medium | Same root cause | No |
| 4 | A few wrong `propose-alignment` suggestions | Low | LLM quality | No |
| 5 | Phase logs marked "done" for a deleted deliverable; state drifts from disk | High | Lifecycle-state integrity | Recovery cost |
| 6 | Regeneration destroyed hand-authored local properties (outside managed block) | High | Toolkit idempotence | Recovery cost |
| 7 | `/` in generated column IRIs is not a valid Turtle prefixed name | Low | Vocab IRI convention | No (paper-cut) |
| 8 | No built-in mapping-resolution validator | Medium | Missing tooling | No |
| 9 | `show-class-inventory` exits non-zero; no class-property lookup | Medium | CLI reliability | No |
| 10 | `next_phase: source` permanently wrong for contract-governed virtual sources | Low | Status heuristic | No |
| CR | **Split silver design from projection; insert an interactive LLM dbt-mapping session that consumes the silver contract** | High | Skill scoping / lifecycle | N/A (process) |
| 11 | `validate --syntax` blocked by ambiguous-accelerator (no hub `pyproject.toml`) | High | CLI reliability / config | Design-validation |
| 12 | No DD-108/109 silver-ext scaffolder/template/validator — ~130 lines hand-authored | High | Missing tooling / DX | No (worked around) |
| 13 | `show-class-inventory --domain party` fails again (FIBO closure, recurrence of #9) | Medium | CLI reliability | No |
| 14 | `check-claims` sync blocks projection — two real causes (mid-file managed block + `bsp-rd:Address` `silverInclude` with no backing claim); **not** the FIBO catch-22 first assumed; error text misleadingly points at FIBO-blocked `claims-to-silver-ext` | High | DX / layout + claim consistency | **Projection** |
| 15 | Rebuilding a reset-lost dbt transform requires reverse-engineering the contract schema from toolkit source | Medium | Missing tooling / docs | No (worked around) |
| 16 | Closure-loading commands (`claims-to-silver-ext`/`migrate`) pull the whole accelerator incl. broken financial→FIBO chain for a BSP-only domain; user directive: do not use FIBO | High | Toolkit scoping (#1 family) | Was blocking `claims-to-silver-ext`/`migrate` (worked around via FIBO-independent path) |

**Primary ask:** fix #1 (scope or degrade module loading in the sync/projection
preflight) — it is the one true blocker and will otherwise affect every domain's
projection path in this hub, not just Party. #2/#3 are the reference-model
packaging side of the same FIBO problem.

**Efficiency ask:** #5 and #6 together caused ~half of this mapping session to be
reset-recovery rather than design; fixing them (deliverable-integrity check +
non-destructive regeneration) plus adding `propose-mapping` / a mapping scaffolder
(#7/#8) would make the mapping phase substantially faster.

---

# Additions — silver design session (2026-07-26)

_Raised while designing the Party silver layer (`bsp:TradeParty`, `bsp:Contact`,
`bsp-reference-data:Address`) — DD-108 identity, DD-109 incremental policy, temporal
FKs, Address claim, `silverSourceRef`, PII policy. On top of issues #1–#10 above._

## ⭐ CHANGE REQUEST (PRIMARY) — split silver **design** from **projection**; insert an interactive LLM dbt-transformation/mapping session in between

**Severity:** High · **Confidence:** High · **Type:** Skill scoping / lifecycle architecture

### The problem
The **kairos-design-silver** skill currently drives the designer straight into
**Phase 4 (projection handoff)** and **Phase 5 (review outputs)** — i.e. it treats
"run the silver/dbt projection" as the natural end of a silver session. But projection
**cannot** run from a silver design alone: it requires the conformed-source **dbt
transforms + mappings** to exist and be contracted. In this hub those transforms are
reset-lost (see #5/#6), so "finish silver → project" is a dead end, and the skill's own
Phase 4/5 point at a step the user explicitly does **not** want to take yet.

### What the user actually wants (the intended flow)
> **Silver design should END at a validated silver contract.** Projection is a
> *separate, later* step. Between silver design and projection there must be an
> **interactive, LLM-assisted dbt-transformation / mapping session that consumes the
> silver contract** (the DD-108/109 identity + incremental + FK annotations) as its
> input specification.

Desired lifecycle:

```
silver design  ──►  (produces the silver contract: *-silver-ext.ttl, validated)
     │
     ▼
interactive LLM dbt-transformation + mapping session
   (uses the silver contract to drive Bronze→Silver SQL, keys, FKs, tests)
     │
     ▼
projection (kairos-execute-project)
```

### Concrete asks
1. **Descope projection from kairos-design-silver.** Silver design "done" = a
   syntactically valid, DD-108/109-SHACL-conformant `*-silver-ext.ttl` **plus** the
   phase log — *not* a generated projection. Move Phase 4/5 out of the skill (or gate
   them behind an explicit "and you already have the dbt transforms" precondition).
2. **Make the silver contract a first-class input to the dbt phase.** The
   dbt-transformation / mapping skill should read the silver-ext (natural/merge keys,
   `silverSourceRef`, FK direction & temporal mode, PII flags, SCD type) and use it to
   drive the interactive Bronze→Silver SQL/mapping session — closing the loop the user
   describes.
3. **Update kairos-flow routing** so that after silver `done` the recommended next
   phase is the **dbt-transformation/mapping session**, *then* project — not straight to
   `kairos-execute-project`. Silver being `done` must not imply "ready to project".

This is the single most important request from this session: **a completed silver
design should be a hand-off artifact for an LLM dbt-mapping session, not a trigger for
projection.**

---

## 11. Sanctioned `validate --syntax` is blocked by an ambiguous-accelerator error (BLOCKER for the design-validation step)

**Severity:** High · **Confidence:** High · **Type:** CLI reliability / hub config

### What happened
The silver skill's own completeness step (`kairos-ontology validate --syntax`) exits **1**:

```
Error: Accelerator selection is ambiguous. Available: financial-services, logistics.
Pass --accelerator or set [tool.kairos].accelerator in the hub pyproject.toml.
```

The hub has **no `pyproject.toml`** at its root, so there is nowhere the documented
`[tool.kairos].accelerator` key can live, and the command gives no domain-scoped escape.

### Why it's a problem
- The **only sanctioned** way to validate the authored silver-ext is blocked, for a
  reason (accelerator ambiguity) that is irrelevant to validating a Party silver file
  that imports only `bsp/party` + `bsp/reference-data`.
- Same family as #1: the tool insists on resolving the full accelerator set instead of
  the domain's actual import closure.

### Workaround used
Hand-ran validation without the CLI: `rdflib` parse (syntax) + `pyshacl` against the
scaffold's `kairos-ext-shapes.shacl.ttl` + `kairos-ext.ttl` (DD-108/109). Both passed —
so the design is provably valid, but the sanctioned command couldn't confirm it.

### Suggested fixes
1. Infer the accelerator from the domain's `owl:imports` closure when unambiguous.
2. Accept a `--accelerator` flag **and** a hub-level config that doesn't require a
   `pyproject.toml` (e.g. the existing hub config file), and say which files are searched.
3. For `validate --syntax` specifically, don't require accelerator resolution at all —
   syntax validation shouldn't need the full module registry.

---

## 12. No scaffolder/validator for DD-108/109 silver-ext — authored ~130 lines by hand from source-only vocab (HIGH VALUE)

**Severity:** High · **Confidence:** High · **Type:** Missing tooling / DX

### What happened
DD-109/DD-108 require, **per materialized class**, a complete identity block (~8
predicates), a linked `IncrementalPolicy` resource (**15** predicates with strict enum
vocabularies), and — per FK — a temporal-FK block (~7 predicates). For 3 classes that is
~130 lines of exacting TTL. There is:
- **no template** with the DD-108/109 stubs (the scaffold `silver-ext.ttl.template` used
  here contained only `silverInclude` in a managed block — no identity/incremental/FK),
- **no `propose-silver-ext`** to pre-fill from evidence, and
- **no CLI to validate just the silver-ext against the DD shapes** (blocked anyway by #11).

To author it correctly I had to reverse-engineer the exact predicate names and allowed
values from `site-packages/.../scaffold/kairos-ext.ttl` and
`kairos-ext-shapes.shacl.ttl`, and verify projector semantics (naturalKey
`camel_to_snake`, source-scoped identity via `_source_record_key`, FK parent-key
resolution) by grepping the projector source. That reverse-engineering was the single
biggest time sink of the session.

### Why it's a problem
- The information needed to pre-fill most of it is **already in the hub deterministically**:
  merge/natural keys = the source vocab `primaryKeyColumns`; `sourceIdentity` = the source
  table IRI; FK object properties + direction = the domain import closure; PII columns =
  source column labels. The human is retyping machine-derivable facts.
- Getting a single enum wrong fails closed at projection with no early feedback (no
  in-hub validator), so the loop is slow.

### Suggested fixes
1. **`propose-silver-ext --domain <d>`** — emit per-class DD-108/109 skeletons with the
   correct predicates and enum placeholders, pre-filled from the source vocab + domain
   closure (keys, source IRIs, FK candidates+direction, PII flags). Designer *confirms*
   enums instead of authoring TTL. Biggest win.
2. **Ship a DD-108/109 template** (update `silver-ext.ttl.template`) with a fully
   commented identity + incremental-policy + temporal-FK block per class.
3. **`validate-silver-ext <file>`** (or `validate --shapes`) that runs the DD-108/109
   SHACL against just the ext file + shapes graph — **without** full accelerator closure
   (see #11). This is exactly the hand-written pyshacl I had to run.
4. **In-hub DD-108/109 reference** (docs page or example) so predicates/enums aren't
   reverse-engineered from `site-packages`.

---

## 13. `show-class-inventory --domain party` fails again (recurrence of #9)

**Severity:** Medium · **Confidence:** High · **Type:** CLI reliability

`kairos-ontology show-class-inventory --domain party --profile kairos-design` exited **1**
with `OntologyLoadError: Ontology closure is incomplete; rerun with degraded=True …` —
the same FIBO-closure root cause as #1/#9. For silver design this is the command that
would enumerate the classes-to-annotate and their FK object properties; it is unusable, so
the class/property inventory was assembled by reading `party.ttl` + the reference model +
mappings by hand. Fix is the same as #1/#9: scope loading to the domain closure or degrade
gracefully, and surface `degraded=True` on the CLI.

---

# Silver-design efficiency analysis (how to make a silver session faster)

The Party silver design was correct and validated, but a large fraction of the time was
spent reverse-engineering the DD-108/109 contract and working around blocked CLIs rather
than making design decisions.

### Steps taken this session (and the friction in each)

| # | Step | Time sink | Avoidable? |
|---|------|-----------|-----------|
| 1 | Pre-flight reads (status, phase logs, silver-ext, party.ttl, mappings, conformed vocabs) | Necessary, but many sequential CLI calls each with venv/version warnings | Partly |
| 2 | Enumerate classes + their properties/FK object props | `show-class-inventory` failed (#13) → read party.ttl + BSP model + mappings by hand | Yes — fix CLI |
| 3 | Reverse-engineer DD-108/109 predicates + enums from `site-packages` (`kairos-ext.ttl`, SHACL shapes) | No in-hub template/reference (#12) | Yes — template + docs |
| 4 | Verify projector semantics (naturalKey `camel_to_snake`, source-scoped identity, FK parent-key resolution) by grepping projector source | Needed to avoid authoring an invalid design; deep and slow | Yes — `propose-silver-ext` + validator would remove the need |
| 5 | Hand-author ~130 lines of DD-108/109 TTL (3 identity + 3 incremental policies + 2 FKs) | Mechanical retyping of machine-derivable facts (#12) | Mostly — scaffolder |
| 6 | Validate the design | `validate --syntax` blocked by ambiguous accelerator (#11) → hand-ran rdflib + pyshacl | Yes — fix #11 / add `validate-silver-ext` |
| 7 | Write phase log | Manual | Partly — a `close-phase` helper |

### Highest-leverage speedups

1. **`propose-silver-ext` (biggest win).** Pre-fill per-class DD-108/109 skeletons from
   the source vocab + domain closure (keys, source IRIs, FK candidates+direction, PII
   flags). Collapses steps 3–5 to *confirm enums*. This is the silver analogue of the
   `propose-mapping` ask in the mapping section.
2. **`validate-silver-ext` that doesn't need accelerator closure** (#11/#12). Turns step
   6 from a hand-written pyshacl script into a one-liner and gives early enum feedback.
3. **Fix the ambiguous-accelerator block on `validate`** (#11) — unblocks the sanctioned
   design-validation step entirely.
4. **Fix `show-class-inventory`** (#13) — restores the one command that enumerates the
   classes + FK object properties a silver designer needs (step 2).
5. **Ship a DD-108/109 template + in-hub reference** (#12) — removes the reverse-engineering
   of steps 3–4.
6. **Descope projection (the CHANGE REQUEST)** — the skill stops at a validated contract,
   so the session doesn't chase a projection that can't run; the dbt-mapping session that
   *can* proceed becomes the explicit next step.

Net: with #1–#2 the silver designer's job becomes *confirm a pre-filled DD-108/109
contract* rather than *reverse-engineer and hand-author it*, and with the CHANGE REQUEST
the silver session ends cleanly on a hand-off artifact instead of a blocked projection.

---

# Additions — dbt-transformation session (2026-07-26)

_Raised while rebuilding the reset-lost conformed dbt transforms
(`int_qargo_contact_conformed` → `bsp:Contact`, `int_qargo_billing_address_conformed`
→ `bsp-rd:Address`) via kairos-develop-dbt-transformation, consuming the silver
contract. The rebuild itself went well: `sync-dbt-contracts` regenerated **byte-identical**
vocabularies (0 written, 2 unchanged), mapping coverage passed 2/2 (1 governed
replacement), and both `check-transformation-readiness` gates are green._

## ✅ What worked well (positive signal)

- **Contract-first reverse build is well-supported.** Because the managed output
  vocabulary survived the reset, the surviving vocab + mappings + silver-ext fully
  pinned the required output columns, and `dbt_contracts.py` / `dbt_contract_sync.py`
  gave a precise, checkable schema. Rebuilding the `.sql`/`.yml`/tests reproduced the
  exact vocabulary (`0 written, 2 unchanged`). The governed-replacement contract
  (`replaces_sources` → `qargo:contacts`) was recognized by `check-claims` without a
  direct/replacement conflict.

## 14. `check-claims` claim↔projection sync blocks projection — two real layout/consistency causes, **not** the FIBO catch-22 first assumed (BLOCKER for projection)

**Severity:** High · **Confidence:** High · **Type:** DX / skill output layout + claim/silver-ext consistency

> **Correction (2026-07-26):** this issue was first logged as a "FIBO catch-22"
> (the sync check demanding `claims-to-silver-ext`, which is FIBO-blocked by #1).
> After reading `core/claim_projection_sync.py` that framing is **wrong**. The
> sync check parses only the silver-ext + ontology TTL with rdflib
> (`_inspect_managed_surface`, `_is_managed_include`); it never loads the
> financial-services accelerator, so **issue #1 does not cause this failure**. The
> real causes are two concrete layout/consistency rules, both fixable without any
> FIBO closure.

### What the check actually enforces
`claim_projection_sync.py` treats a triple as **Claim-Registry-controlled** when it is
`kairos-ext:silverInclude` on a **non-local (imported/claimed) class**
(`_is_managed_include`, lines 243-249). It then requires (`_split_managed_block` +
`_require_current_managed_surface`):
1. **Layout:** exactly one `# >>> kairos-managed … # <<< kairos-managed` block, and it
   must be the **final content** of the file — any authored content *after* it →
   `content after the managed block cannot be preserved safely`.
2. **Completeness:** **every** controlled `silverInclude` (i.e. on an imported class)
   must live **inside** that block — a stray one in the authored section →
   `Claim Registry-controlled triples appear outside the managed block`.

### What was actually wrong in this hub
The hand-authored `party-silver-ext.ttl` violated **both** rules:
1. The managed block (Contact + TradeParty) sat **mid-file**, with the authored
   DD-108/109 policy *after* it. → **fixed by reordering** the managed block to the end
   (authored policy first, managed block last). This alone flipped the error from
   "content after the managed block…" to the second message.
2. It asserts `bsp-rd:Address kairos-ext:silverInclude "true"` in the authored section,
   but the **Claim Registry (`party-claims.yaml`) has no `bsp-rd:Address` class claim** —
   it only claims `bsp:Contact` and `bsp:TradeParty`. So `Address` is a controlled
   triple with **no backing claim** and outside the block. This is a genuine
   **silver-ext ⇄ Claim Registry inconsistency**, not a toolkit bug: the governed
   replacement introduced `bsp-rd:Address` as a reference-data target, but it was never
   registered/approved as a claim (this is also what the `mdm_anchor` advisory hinted at).

### Why it's still worth logging
The **failure was self-inflicted-by-tooling in two avoidable ways**:
- **Misleading remediation text.** The error says *"Run `kairos-ontology claims-to-silver-ext`"* —
  the one command that IS FIBO-blocked (#1) — which is what sent the first analysis down
  the catch-22 dead-end. It should instead say "run `migrate` to relocate the block" and,
  for cause #2, "no approved claim exists for `<class>`; register it via the claims/domain
  skill". The remediation must not point at a command it knows is degraded in this hub.
- **kairos-design-silver emitted a non-canonical layout.** Because the silver-ext was
  hand-authored (a downstream effect of #1), the design skill placed the managed block
  mid-file and let an unclaimed `silverInclude` through. The skill should emit the
  canonical layout (managed block last, only claimed classes get `silverInclude`) and
  should **validate** the silver-ext against the Claim Registry at design time, so this
  is caught in the silver session — not three phases later at projection.

### Impact / scope
- Blocks the Party **projection** phase (not the transform rebuild, which is complete
  and gate-green).
- Cause #1 (mid-file block) will recur for any hand-authored silver-ext.
- Cause #2 (unclaimed projected class) will recur whenever a governed replacement targets
  a reference-data class that was never added to the Claim Registry.

### Suggested fixes
1. **Fix the remediation message** to stop recommending FIBO-blocked
   `claims-to-silver-ext`; recommend `migrate` (layout) and claim registration (missing
   claim), and name the offending class/triple.
2. **kairos-design-silver: emit canonical layout + validate against claims.** Managed
   block last; reject/route any `silverInclude` on a class that has no approved claim
   (offer to register it) — moving both failures to design time.
3. **Provide a closure-independent `migrate` / managed-block writer** so a hand-authored
   silver-ext can be normalized to the accepted layout without loading the full
   accelerator (shared root fix with #1/#11 — scope loading to the domain closure).
4. **Register `bsp-rd:Address` as an approved reference-data claim** (hub-side follow-up,
   owned by claims/domain design) so its `silverInclude` legitimately belongs in the
   managed block.

### ✅ Resolution (2026-07-26) — projection unblocked, FIBO-independent
Fixed entirely on the closure-independent `check-claims` path (no `claims-to-silver-ext`,
no `migrate`, no FIBO load):
1. **Layout** — moved the `# >>> kairos-managed` block to the **end** of
   `party-silver-ext.ttl` (authored DD-108/109 policy now precedes it).
2. **Missing claim** — added an approved imported **`type: class`** claim for
   `bsp-rd:Address` to `party-claims.yaml` (NOT `reference_data`+`mdm_anchor`, to stay
   consistent with the silver-ext's `isReferenceData "false"`), removed the now-redundant
   `silverInclude` from the authored Address block, and added the Address `silverInclude`
   line into the managed block.
3. **Ontology imports** — adding the Address claim promoted `owl:imports <bsp/reference-data>`
   to a controlled import, so it was relocated from the inline `owl:Ontology` list into
   `party.ttl`'s managed import block (alongside `bsp/party`).

Result: `check-claims --domains party` → **`✓ party: claims/imports/includes in sync`,
exit 0** (only the non-blocking `mdm_anchor` advisory remains, intentionally not
satisfied). Both TTLs parse. This confirms the FIBO framing was wrong and the two managed
surfaces just needed canonical layout + a backing claim.

## 16. Closure-loading commands pull the **whole accelerator** (incl. a broken financial→FIBO chain) even for a BSP-only domain — user directive: do **not** use FIBO

**Severity:** High · **Confidence:** High · **Type:** Toolkit scoping (issue #1 family)

### What happened
`claims-to-silver-ext --domains party` (and `migrate`) hard-fail loading ~70
`legacy-fibo-*` modules ("Ontology closure is incomplete… rerun with degraded=True";
several "cannot be resolved through the catalog"). The party domain only claims
`bsp:TradeParty`, `bsp:Contact`, `bsp-rd:Address` — **none of which need FIBO**. FIBO is
imported by the BSP **financial** module, which the accelerator module-context loads
wholesale regardless of the `--domains party` scope.

### User directive
> "we do not use fibo, pls disregard it everywhere."

The hub does not model financial and does not use FIBO. Loading (and failing on) the
financial→FIBO chain is pure, avoidable breakage.

### Why it's a problem
- Any command that builds the full accelerator module-context (`claims-to-silver-ext`,
  `migrate`, and likely `project`/`validate` closure preflight) is blocked by a broken
  sub-tree the domain never references.
- The deterministic `check-claims` sync path does **not** load the closure and works
  fine — proving the closure load is unnecessary for this operation.

### Suggested fixes
1. **Scope module loading to the claimed-domain closure** (shared root with #1/#11):
   for `--domains party`, load only the modules the approved party claims import
   (`bsp/party`, `bsp/reference-data`), never the financial/FIBO sub-tree.
2. **Allow excluding modules / accelerator domains** the hub doesn't use (e.g. a hub
   config `exclude_modules` / `disabled_domains: [financial]`), so FIBO is never pulled.
3. **Degrade, don't hard-fail, on unrelated incomplete closures** — a broken module
   outside the requested domain's closure should warn, not block.

Until fixed, the FIBO-independent `check-claims` + canonical managed-block layout is the
working path (see #14 resolution); avoid `claims-to-silver-ext`/`migrate` on this hub.


## 15. Rebuilding a reset-lost transform means reverse-engineering the exact contract schema from toolkit source (DX)

**Severity:** Medium · **Confidence:** High · **Type:** Missing tooling / docs

### What happened
To rebuild the two transforms so `sync-dbt-contracts` would regenerate an **identical**
vocabulary, the precise contract YAML schema had to be reverse-engineered from
`core/dbt_contracts.py` (required `meta.kairos` keys, `data_type` must be the canonical
`string`/`boolean`, `grain_key` drives `primaryKeyColumns` + the sole non-nullable
column, decision `evidence`/`approval`/`verified_by` rules) and `core/dbt_contract_sync.py`
(how each field maps into the vocabulary graph).

### Why it's a problem
- There is no **`scaffold-dbt-transformation` / template** that emits a
  contract `.yml` + `.sql` skeleton **from an existing (or surviving) vocabulary**.
  For a reset-recovery this is exactly what's needed — the output contract is already
  known, only the implementation is missing.
- No concise "contract YAML reference" in the skill; the authoritative source is Python.

### Suggested fixes
1. **`scaffold-dbt-transformation --from-vocabulary <file>`** — emit a contract `.yml`
   (columns/types/descriptions/grain_key/target_class/virtual_source_iri pre-filled from
   the surviving vocabulary) + a stub `.sql`, so a reset-lost transform is a fill-in
   rather than a reverse-engineer.
2. **Publish a compact contract-schema reference** (fields, enums, canonical data types,
   decision requirements) in the kairos-develop-dbt-transformation skill.
