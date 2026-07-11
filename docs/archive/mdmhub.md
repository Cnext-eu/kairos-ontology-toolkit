# Advisory: Adding a Master Data Management (MDM) Hub to the Kairos Framework

_Draft · advisory only (no code, no DD entry yet) · prepared for the MDM add-on discussion_

> **Source input:** `Fracht-GDWH/.project/deliverables/discovery/D06/refinement/MDM Deepdive.md`
> — a phased MDM strategy (Phase 1 analytical MDM / MDMAD → Phase 2 operational MDM
> with governance and sync-back).

---

## 1. Executive summary

**Recommendation in one line:** the MDM Hub is **not** a new toolkit/engine repo. It is a
**new capability layered onto the existing Kairos Ontology Toolkit** — the ontology hub
already holds everything MDM needs to be *driven from the model*:

- the **master-data entities** (Party/Organisation, Location, etc.),
- the **authoritative identifiers** (VAT, KBO/BCE, LEI, EORI) that become match keys,
- the **reference code-lists** (UN/LOCODE, Incoterms, currency…), and
- the **source→domain crosswalk** already expressed as SKOS mappings.

So MDM fits Kairos' shift-left philosophy exactly: **annotate the ontology, then project
the MDM artifacts** — instead of hand-building an MDM tool.

The chosen shape (per discussion) is **option 3 — "both"**:

1. **MDM annotations live in the ontology hub** (`kairos-mdm:` vocabulary + a new
   `mdm` projection target), and
2. a **downstream MDM-Hub repo is scaffolded** from the ontology hub via a new
   `init-mdm-hub` command — analogous to today's `init-dataplatform`.

The **data-steward UI and reference-list management** are kept **open-source and
Fabric-independent** as far as possible (Directus over the hub warehouse for stewardship;
Zingg for match/merge). Fabric/Power BI remains only the *analytical consumer* (the DWH),
consistent with the deep-dive's "DWH consumes, never authors" rule.

> ⚠️ **Read §9 first.** A critical-review pass added essential constraints: **MDM is
> stateful, not stateless codegen** — the projector generates **contracts/migrations**, not
> the live store, and **never re-mints `MDM_PARTY_ID` or overwrites stewarded data**. It
> also concludes **Phase 1 likely needs none of the new machinery** — do it with the
> existing silver/dbt projection first (§9.5). The vocabulary/target/scaffold below (§4–§8)
> describe the **full Phase-2 ambition**, gated on a committed operational Phase 2.

---

## 2. How MDM relates to the ontology (the conceptual anchor)

The deep-dive's vocabulary maps almost 1:1 onto concepts Kairos already models. MDM does
not introduce a parallel model — it **adds a governance/identity lens** on top of the
existing domain ontology.

| MDM concept (deep-dive) | Already in the ontology as… | What MDM adds |
|---|---|---|
| **Master data** (Party, Location, Vessel…) | `owl:Class` domain entities | A flag marking a class as *mastered* + which attributes are dimension fields |
| **Reference data** (UN/LOCODE, Incoterms…) | Reference-model code-lists / conformed dimensions | A flag marking a class as a *governed reference list* + effective-dating |
| **`MDM_PARTY_ID`** (crosswalk key) | *(new)* the surrogate identity minted by the hub | The crosswalk table: `MDM_*_ID ↔ (sourceSystem, sourceKey)` |
| **Authoritative identifier** (VAT/KBO/LEI/EORI) | Existing identifier properties on the class | Marked as *match keys* with priority + validation pattern |
| **Golden record** (Phase 2) | The full set of class properties | Survivorship rules: which source wins per attribute |
| **SoE / SoR** | Source systems in `integration/sources/` + mappings | Per-attribute ownership (which system is authoritative) |
| **Dimension fields (Phase 1)** | Properties already used by gold/Power BI DIMs | The *minimal* subset surfaced by the crosswalk |
| **Global vs local register** (no-hierarchy rule) | Two separate classes (e.g. `GlobalLocation` vs `LocalAddress`) | Enforced non-overlap; no parent/child modeling |

**Key insight:** MDM is the *identity + governance* projection of the same ontology that
already drives silver/gold/dbt. Phase 1 needs only a **thin slice** (crosswalk + a few
dimension fields for Party); Phase 2 grows it to full golden records — but both come from
the **same annotated model**.

---

## 3. Where MDM sits structurally — the "both" architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  kairos-ontology-toolkit  (this repo — the engine, unchanged     │
│  in spirit; gains an `mdm` projector + `init-mdm-hub` scaffold)  │
└─────────────────────────────────────────────────────────────────┘
        │ scaffolds / projects
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  <client>-ontology-hub   (existing)                              │
│  model/                                                          │
│    ontologies/          domain classes (Party, Location…)        │
│    extensions/                                                   │
│      *-silver-ext.ttl   *-gold-ext.ttl                           │
│      *-mdm-ext.ttl      ← NEW: kairos-mdm: annotations           │
│    mappings/            SKOS source→domain (feeds crosswalk)     │
│  integration/sources/   CargoWise · Intris · Carlo bronze vocab  │
│  output/                                                          │
│    medallion/           silver + gold (existing)                 │
│    mdm/                 ← NEW: crosswalk DDL, match rules,        │
│                            steward-UI config, reference-list DDL │
└─────────────────────────────────────────────────────────────────┘
        │ init-mdm-hub  (like init-dataplatform)
        ▼
┌─────────────────────────────────────────────────────────────────┐
│  <client>-mdm-hub   (NEW downstream repo, generated)             │
│  ├─ crosswalk/        MDM_PARTY_ID store + source-key links      │
│  ├─ matching/         Zingg config (match/merge/survivorship)    │
│  ├─ steward-ui/       Directus config (RBAC, TODO queue, audit)  │
│  ├─ reference/        versioned/effective-dated code lists       │
│  └─ integration/      (Phase 2) event sync-back, loop-guard      │
└─────────────────────────────────────────────────────────────────┘
        │ read-only crosswalk + dimension fields
        ▼
   DWH / Power BI (Fracht360 · MyFracht)   ← consumes, never authors
```

### Why "both" (annotations in hub + downstream repo)

- **Annotations in the ontology hub** keep MDM *shift-left*: identity, match keys,
  survivorship and reference-list governance are **model decisions**, versioned with the
  ontology, validated by SHACL, and regenerable. This mirrors how silver/gold work today.
- **A downstream MDM-Hub repo** keeps *operational* concerns (a running steward UI, the
  crosswalk data store, matching jobs, sync-back integration) **out of the model repo** —
  exactly the separation already established for `dataplatform` (DD-017).

### Why NOT a separate toolkit/engine repo

A standalone MDM builder would duplicate the ontology loader, catalog resolution,
extension-merge, projection engine, scaffold system and CI already in this toolkit. MDM is
another **projection target + scaffold**, not a new engine. Reuse > fork.

---

## 4. Proposed additions to the toolkit (advisory spec, no code)

### 4.1 New annotation vocabulary — `kairos-mdm:`

A new namespace file (`scaffold/kairos-mdm.ttl`) alongside `kairos-ext.ttl` /
`kairos-map.ttl`. Annotations live in `*-mdm-ext.ttl` extension files (discovered by the
same glob mechanism as silver/gold — see projection-loading memory).

**Class-level (identity & governance):**

| Annotation | Purpose | Phase |
|---|---|---|
| `kairos-mdm:mastered true` | Marks a class as a mastered entity (mints an `MDM_*_ID`) | 1 |
| `kairos-mdm:crosswalkIdName "MDM_PARTY_ID"` | Name of the minted crosswalk key | 1 |
| `kairos-mdm:baselineSource "CargoWise"` | Which source seeds the baseline | 1 |
| `kairos-mdm:referenceList true` | Marks a class as a governed reference/code list | 1 |
| `kairos-mdm:effectiveDated true` | Reference list is versioned/effective-dated | 2 |
| `kairos-mdm:register "global" | "local"` | No-hierarchy register assignment | 2 |

**Property-level (match keys, dimension fields, survivorship):**

| Annotation | Purpose | Phase |
|---|---|---|
| `kairos-mdm:matchKey true` | Property is an identity match key (VAT, KBO, LEI…) | 1 |
| `kairos-mdm:matchPriority 1` | Ordering / authority of match keys | 1 |
| `kairos-mdm:matchValidationPattern "..."` | Regex/validation for the identifier | 1 |
| `kairos-mdm:dimensionField true` | Minimal field surfaced in the Phase-1 crosswalk (e.g. NAME) | 1 |
| `kairos-mdm:survivorship "sourcePriority" | "mostRecent" | "mostComplete"` | Golden-record rule | 2 |
| `kairos-mdm:authoritativeSource "CargoWise"` | Per-attribute SoR (ownership) | 2 |

### 4.2 New projection target — `mdm` (generates **contracts**, never owns state)

Add `mdm` to the projection targets (joining `silver`, `powerbi`, `dbt`, …). Given an
annotated ontology it emits into `output/mdm/`. **Critical framing (see §9):** unlike
silver/gold — which regenerate *disposable* artifacts — the MDM runtime holds **durable,
mutable business state** (crosswalk IDs, steward edits, merge history, audit). The
projector therefore emits **contracts and idempotent, non-destructive migrations**, *not*
the live store. It never re-mints IDs and never overwrites stewarded data. Read §9 before
treating `mdm` like any other target.

**Phase 1 (analytical):**
- **Crosswalk contract + migration** — `MDM_PARTY_ID` table + `(MDM_PARTY_ID, sourceSystem,
  sourceKey)` link table, generated from the `mastered` class + its `matchKey` properties.
  ID allocation is **append-only and owned by the runtime**, not the projector.
- **Match ruleset (versioned)** — a declarative deterministic match spec (on `matchKey` +
  validation pattern), stamped with a rule version so re-runs never silently re-cluster
  existing IDs.
- **Reporting-DIM contract** — the `dimensionField` subset the DWH may read.
- **Missing-data / TODO queue schema** — the exception table backing the steward UI's
  "registration nr missing" loop (§2.4 of the deep-dive).

**Phase 2 (operational) — additive:**
- **Golden-record schema + migration** (full attributes) + **survivorship rules** table.
- **Reference-list management schema** (versioned, effective-dated) — schema/seed only;
  values are runtime-governed, not overwritten on re-projection.
- **Steward-UI baseline config** (Directus collections + roles + permissions, generated as
  a **bootstrap + idempotent migration** — not a repeated overwrite; see §5.1 and §9).
- **Sync-back integration contract** (event schema + `originSystem` loop-guard) — **spec
  only**; actual connectors, failure/retry/rollback design live in the downstream repo.

> The projector reuses existing infrastructure: catalog resolution, extension-merge
> (`merge_ext_graph`), and the `rdflib.Graph` discipline (no string-built RDF/SQL).
> It emits **migrations with create/alter semantics + drift detection**, never `DROP` of a
> table holding minted IDs or stewarded values.


### 4.3 New scaffold command — `init-mdm-hub`

Mirrors `init-dataplatform` (see `cli/main.py` `init_dataplatform`, DD-017). Scaffolds a
downstream `<client>-mdm-hub` repo pre-wired to consume the ontology hub's `output/mdm/`:
crosswalk store, Zingg matching config, Directus steward-UI config, reference-list store,
and (Phase 2) sync-back integration. Ships with its own README, CI, `.env.example`, and
MDM-specific skills.

### 4.4 New skills (following the existing skill-routing pattern)

| Skill | Purpose |
|---|---|
| `kairos-design-mdm` | Interactive: annotate classes as mastered/reference, pick match keys, dimension fields, survivorship (design-mode interactive by default) |
| `kairos-execute-mdm` | Run the `mdm` projection (the skill-first wrapper for `project --target mdm`) |
| `kairos-setup-mdm-hub` | Scaffold the downstream MDM-Hub repo via `init-mdm-hub` |
| `kairos-package-mdm-hub` | Consume/operate the downstream MDM Hub |

Lifecycle placement — **MDM is a peer projection of the model, not a downstream of the
medallion layer.** It depends only on `domain` (classes + identifier properties) and
`mapping` (source→domain crosswalk). Silver, gold and mdm are **siblings**: three
independent projections that all read the same ontology hub model.

```
discovery → source → domain → mapping ─┬─→ silver → gold   (medallion / BI branch)
                                       ├─→ mdm            (identity / governance branch)
                                       └─→ neo4j / prompt / … (other projections)
                                                 ↓
                                          validate → project
```

MDM can run **immediately after `mapping`** with **no silver/gold present at all**.

### 4.5 MDM's *contract* has zero projection dependency — its *execution* needs source data

Precise claim (corrected — see §9): the **MDM contract generation** (schema, crosswalk
shape, match ruleset, DIM contract) depends **only** on the model — domain + mappings — and
reads none of `output/medallion/`, silver DDL, gold TMDL, or dbt. But the **MDM execution
pipeline** (actually resolving parties) depends on **source data + identifier
normalization** (VAT/KBO punctuation, country prefixes, missing/invalid formats), which is
non-trivial and overlaps with silver cleansing.

**What the `mdm` contract reads:**

| Input | Lives in | Why MDM needs it |
|---|---|---|
| Domain classes + **identifier properties** | `model/ontologies/*.ttl` | Defines the mastered entity and its match keys (VAT/KBO/LEI) |
| `kairos-mdm:` annotations | `model/extensions/*-mdm-ext.ttl` | Marks mastered/reference classes, match keys, dimension fields, survivorship |
| **SKOS source→domain mappings** | `integration/` mappings | Tells the crosswalk which source column carries the registration number per system |
| Source vocabulary (optional) | `integration/sources/*.vocabulary.ttl` | Source-key column names for the crosswalk links |

The `kairos-mdm:dimensionField` flag is a **model annotation read directly from the
ontology** — gold surfaces the *same* fields only because it reads the *same* model; MDM
never depends on gold having run. A hub can do `domain → mapping → mdm` with no medallion.

> **But normalization must not be duplicated.** Because match keys need the *same* cleansing
> silver would apply, the execution pipeline should **reuse silver's normalization logic**
> (or generate equivalent SQL) rather than re-implement it. So: *contract* is
> medallion-independent; *execution* shares source-normalization concerns with silver.

> **Why this matters for Fracht Phase 1:** the deep-dive's MDMAD scope is *"just enough
> consolidation to build the crosswalk + a few dimension fields"* — deliberately **narrow**.
> But narrow does **not** automatically mean "new hub" — §9.5 argues Phase 1 may be
> deliverable with the *existing* silver/gold/dbt projection and **no new `mdm` target,
> Postgres, or services at all**.

---

## 5. Platform evaluation — steward UI & reference-list management

**Constraint (per discussion):** keep the **data-steward UI open-source and
Fabric-independent** as far as possible. Fabric/Power BI stays the *analytical consumer*
only.

### 5.1 Data-steward UI (TODO queue → Phase 2 workbench)

| Option | RBAC | Approval workflow | Audit trail | DB fit | Verdict |
|---|---|---|---|---|---|
| **Directus** (OSS) | Field-level, policy rules | Native flows/automations | Built-in revisions + activity log | Introspects any SQL DB (Postgres, MSSQL, Fabric WH via SQL endpoint) | ✅ **Recommended** — model-driven collections, strong audit, self-hosted |
| NocoDB (OSS) | Project/table level | Custom only | Full audit in self-host | Broad SQL | Good lightweight alt; weaker workflows |
| Baserow (OSS) | Project/table level | Limited | History (pro) | Postgres only | Simplest; Postgres-only limits Fabric reuse |
| Appsmith / Budibase (OSS) | App-level | Custom | App-level only | Any/API | Better as custom panel builders, not stewardship-native |

**Recommendation:** **Directus** as the steward UI. It gives granular RBAC (global vs
local scope from the deep-dive), native approval workflows (the TODO/exception queue and
Phase-2 approval gates), and a built-in audit trail (required by §8 governance) — all
open-source and self-hostable over any SQL store. Because Directus introspects the schema,
we can **generate its collection/role config from the ontology**, keeping the UI
shift-left and Fabric-independent. It can point at Postgres in Phase 1 and, if desired,
at a Fabric Warehouse SQL endpoint later — the UI itself never depends on Fabric.

### 5.2 Mastering engine (match / merge / survivorship)

| Option | Focus | Verdict |
|---|---|---|
| **Zingg** (OSS, Spark/Docker) | Entity resolution: match, merge, survivorship, ML + deterministic | ✅ **Recommended** for the mastering engine |
| OpenRefine (OSS) | Cleaning + basic clustering | Useful for one-off dedupe, not a service |
| Talend Open Studio (OSS) | ETL with basic dedupe | Advanced survivorship is paid |

**Recommendation:** **Zingg** for match/merge/survivorship. Phase 1 needs only
**deterministic matching on the validated registration number** (VAT/KBO), which Zingg (or
even plain SQL from the generated match ruleset) handles trivially; Zingg's probabilistic
matching is held in reserve for Phase 2 scale. Self-hosted, no cloud dependency.

### 5.3 Reference-list management

Reference lists are **governed data, not code** — manage them in the **same open-source
stack**: author/version them in Directus (effective-dated collections generated from
`kairos-mdm:referenceList` classes), publish read-only to the DWH, and (Phase 2) sync to
the TMS. No separate tool needed; the ontology defines the lists, Directus governs edits,
the `mdm` projector emits the versioned schema.

### 5.4 Net platform picture

```
Steward UI + reference authoring : Directus        (OSS, self-hosted, DB-agnostic)
Match / merge / survivorship     : Zingg           (OSS, self-hosted)
Crosswalk + golden-record store  : Postgres (P1) → optionally Fabric WH (P2)
Analytical consumption           : Power BI / Fabric (unchanged, read-only)
Integration / sync-back (P2)     : event bus + originSystem loop-guard (spec)
```

Only the **analytical consumer** touches Fabric; the MDM operational core stays open-source
and portable.

### 5.5 Build vs adopt — what Directus and Zingg actually buy us

**The honest framing:** every OSS component is a dependency, and "full support"
(enterprise/paid tiers, or our own maintenance effort) has a real cost. The question is
not "OSS vs free" — it's **"reuse a mature commodity vs build and own a bespoke one."**
Neither Directus nor Zingg is core Kairos IP; both solve *generic, well-trodden* problems.

#### Directus (steward UI) — what it saves us building

A data-steward UI is deceptively large. To hand-build the equivalent we'd have to write and
then **maintain forever**:

| Capability | Effort if we build it | Directus gives it |
|---|---|---|
| CRUD screens over the crosswalk/golden-record tables | Forms, grids, validation, pagination per entity | Auto-generated from schema introspection |
| **Granular RBAC** (global vs local scope, per-field) | Custom permission model + enforcement | Built-in, field-level policies |
| **Approval workflows** (the TODO/exception queue, Phase-2 gates) | State machine + assignment + notifications | Native flows/automations |
| **Audit trail** (who changed what, when — required by §8) | Change-capture + revision storage + diff UI | Built-in revisions + activity log |
| Auth, SSO, sessions, i18n, accessibility | Ongoing security surface we'd own | Maintained upstream |

**Value:** Directus collapses *months* of undifferentiated UI/plumbing into
**generated config** we drive from the ontology. It is **not** where Kairos adds value —
so building it ourselves means owning a large, security-sensitive surface with no
competitive upside.

#### Zingg (mastering engine) — what it saves us building

Entity resolution at scale is a specialist problem (blocking, similarity, transitive
clustering, survivorship). Zingg brings ML-assisted **probabilistic** matching, scalable
Spark execution, and merge/survivorship primitives that are genuinely hard to get right.

**But note the phasing:** Fracht **Phase 1 needs only deterministic matching** on a
*validated registration number* (VAT/KBO). That is a **SQL/`GROUP BY` join** our own `mdm`
projector can emit — **no Zingg dependency at all in Phase 1**. Zingg earns its keep only
in **Phase 2**, when fuzzy matching, multi-attribute survivorship and scale appear.

| Aspect | Build ourselves | Adopt Zingg |
|---|---|---|
| Phase 1 deterministic match | ✅ trivial — projector emits SQL | (overkill) |
| Phase 2 probabilistic match / ML | ❌ specialist, high-risk to build | ✅ mature, proven |
| Survivorship at scale | ❌ significant effort | ✅ built-in |

#### Recommendation — minimize dependencies, adopt only where it's not our value-add

1. **Phase 1:** take **zero runtime OSS dependency for matching** — the `mdm` projector
   emits deterministic **SQL**. Optionally stand up **Directus** for the steward TODO queue
   *if* a UI is needed on day one; otherwise even that can wait until there are exceptions
   to steward.
2. **Phase 2:** adopt **Directus** (steward workbench + governance) and **Zingg** (fuzzy
   match/merge/survivorship) — precisely the two areas that are **generic, hard, and not
   Kairos differentiators**. Building them ourselves would add cost *and* risk with no
   strategic return.
3. **Cost containment:** both are self-hostable OSS — **no paid tier is required** for the
   Phase-1/2 scope described here. "Full support" (enterprise SLAs) is an **optional
   later** choice, not a prerequisite. The dependency we take is a **container we run**,
   not a vendor we're locked to; because the UI/match config is **generated from the
   ontology**, either tool is **replaceable** without touching the model.

**Bottom line:** Kairos' value is the **ontology-driven generation** of the crosswalk,
match rules, dimension contract and governance config — *not* re-implementing a form
builder or an entity-resolution engine. Adopt the commodity, own the model.

---

## 6. Where golden records live and how apps consult them

This is the "system-of-reference" question: **the golden record physically lives in the
MDM-Hub's own operational store, and that store *is* the authoritative serving layer.**
The answer differs sharply by phase.

### 6.1 The store

- **The golden-record store is a self-hosted OLTP database (Postgres) inside the
  downstream `<client>-mdm-hub` repo** — the same store Directus governs and Zingg writes
  merged records into. It holds:
  - the **crosswalk** — `MDM_PARTY_ID ↔ (sourceSystem, sourceKey)` for every TMS copy;
  - the **golden record** — the surviving mastered attributes (Phase 2);
  - the **reference lists** — versioned/effective-dated code lists.
- It is **Fabric-independent and open-source** (consistent with §5): the operational SoR
  never depends on Fabric. Fabric/Power BI is only a downstream *reader*.
- Schema is **generated by the `mdm` projector** from the ontology, so the store is
  model-driven and regenerable — not hand-modeled.

> **Not the DWH.** The Fabric Warehouse / medallion is an **analytical replica**, never the
> master. The DWH *consumes* the crosswalk; it must not become the place master data is
> authored or the SoR — that would violate the deep-dive's "a DWH never creates master
> data" rule.

### 6.2 How consumers reach it — four access patterns

| Consumer | Pattern | Phase |
|---|---|---|
| **DWH / Power BI** (Fracht360, MyFracht) | **Read-only published copy** — the crosswalk + dimension fields are replicated into the Fabric Warehouse; reports join their facts to `MDM_PARTY_ID` | 1 & 2 |
| **Operational apps needing master data** | **API on demand** — Directus auto-exposes a **REST + GraphQL API** over the golden-record store; apps look up a party/golden record by `MDM_PARTY_ID` or by source key via the crosswalk | 2 |
| **The TMS** (CargoWise, Intris, Carlo) | **Event-based sync-back** — approved golden attributes are published back to the TMS (where Fracht Global supports it), with `originSystem` loop-guard | 2 |
| **Enterprise processes** (onboarding/KYC, external validation) | **API + events** — Fracht-Digital processes read/enrich via the same Directus API (hub *enables*, does not *own*) | 2 |

**The crosswalk is the universal join key.** Any consumer that has a *source* key (a
CargoWise party number) resolves it to the group-wide `MDM_PARTY_ID` through the crosswalk,
then reads either the DWH copy (analytics) or the hub API (operational).

### 6.3 Phase 1 vs Phase 2 — a critical distinction

- **Phase 1 (MDMAD): there is no operational golden record to consult.** The hub holds
  **only the crosswalk + a few dimension fields**, and the **only consumer is the DWH**
  (read-only). Operational apps and the TMS **do not** call the hub in Phase 1 — detail
  still lives in the TMS. This is exactly the deep-dive's narrow, no-operational-impact
  scope.
- **Phase 2 (operational): the hub store becomes the authoritative SoR** for mastered
  attributes. *Now* other apps consult it — via the Directus API (on-demand reads),
  sync-back (push to TMS), and the DWH copy (analytics). The golden record "lives" in the
  hub store and is served through those three channels.

```
                        ┌───────────────────────────────────────────┐
                        │  <client>-mdm-hub  (self-hosted, OSS)      │
   TMS feeds ──events──▶│  Postgres golden-record store  (the SoR)   │
   (CW·Intris·Carlo)    │   • crosswalk  MDM_PARTY_ID ↔ source keys  │
                        │   • golden attributes (P2)                 │
                        │   • reference lists (versioned)            │
                        │  Directus  ── governs + REST/GraphQL API ──┼──▶ operational apps (P2)
                        └───────┬───────────────────────┬───────────┘
                     read-only  │                        │ event sync-back (P2, where supported)
                     published  ▼                        ▼
                 Fabric DWH / Power BI            TMS (CW·Intris·Carlo)
                 (analytics, P1 & P2)             (writes approved data back)
```

**One-line answer:** golden records live in the **MDM-Hub's own self-hosted Postgres
store (the SoR), governed by Directus**; apps consult them through **Directus' REST/GraphQL
API** (operational), a **read-only replica in the Fabric DWH** (analytics), and **event
sync-back to the TMS** (Phase 2) — all keyed on the `MDM_PARTY_ID` crosswalk. In Phase 1
only the DWH reads, and only the crosswalk + dimension fields exist.

---

## 7. Phasing — mapped to the deep-dive

| Phase | Deep-dive scope | Toolkit deliverables |
|---|---|---|
| **Phase 1 — MDMAD** | Crosswalk `MDM_PARTY_ID` + dimension fields, read-only, no TMS impact | `kairos-mdm:` (identity subset), `mdm` projector (crosswalk + DIM contract + TODO schema), Directus TODO-queue config, deterministic match ruleset |
| **Phase 2 — Operational** | Golden records, match/merge, governance/ODQ, sync-back, simple Party Groups | Full `kairos-mdm:` (survivorship, ownership, reference-list, register), golden-record + reference schemas, Directus workbench + RBAC + audit, Zingg probabilistic matching, sync-back contract, `init-mdm-hub` operational wiring |

**No-hierarchy rule (deep-dive §3.3)** is honored by modeling **global vs local as two
separate classes** (never parent/child), enforced via `kairos-mdm:register` +
(optionally) a SHACL shape that rejects overlap.

---

## 8. Governance & functionality coverage vs the deep-dive

Cross-check of the advisory against the deep-dive's two authoritative lists — **§3.1
(operational MDM feature set)** and **§7.2 (functional building blocks ①–⑦)**. Legend:
✅ covered · 🟡 partial · ❌ gap (now closed below).

| # | Deep-dive capability | Status before | How Kairos covers it |
|---|---|:--:|---|
| ① | UX & stewardship (authoring, workbench, TODO queue) | ✅ | Directus + generated collections; TODO/exception schema from `mdm` projector |
| ② | Mastering engine (match/merge/survivorship/crosswalk) | ✅ | Deterministic SQL (P1) → Zingg (P2); `kairos-mdm:matchKey/survivorship` |
| ③ | Golden records (full detail, lifecycle, groups) | 🟡 | Golden-record schema ✅; **lifecycle states + merge/split were missing** (see G4) |
| ④ | Reference data management (versioned, effective-dated) | ✅ | `kairos-mdm:referenceList/effectiveDated`; Directus authoring |
| ⑤ | Governance & ODQ (roles, permissions, **KPIs**, **screening**, audit) | 🟡 | RBAC + audit ✅; **ODQ/KPIs (G1) and DPS screening (G2) were missing** |
| ⑥ | Integration & sync-back (events, loop-guard, retry, rollback) | ✅ | Sync-back contract spec (P2), `originSystem` loop-guard |
| ⑦ | Enablement for global processes (onboarding/KYC, external validation) | ❌ | **Was missing — enrichment/enablement hooks (G5)** |
| §3.1 | Party Groups & hierarchies (simple, P2) | ✅ | `kairos-mdm:register`; out of P1 |
| §3.1 | Roles & operating model (Controllers, Stewards, federated) | ❌ | **Was missing — operating-model roles (G3)** |
| §3.1 | Per-attribute ownership (SoR per attribute) | ✅ | `kairos-mdm:authoritativeSource` |

### Closing the gaps — additional `kairos-mdm:` annotations & outputs

All five gaps are closed the **Kairos way**: express the governance rule as a **model
annotation**, then **project** the runtime artifact (DQ check, screening hook, Directus
role, lifecycle state machine). Governance stays shift-left, not hand-built in the UI.

**G1 — ODQ (data quality) & KPIs.** *This is the biggest gap and has an elegant
ontology-driven answer:* completeness / validity / accuracy criteria are **already
expressible as SHACL shapes** (`sh:minCount`, `sh:pattern`, value ranges). The `mdm`
projector emits, per mastered entity:
- **DQ rules** derived from SHACL (completeness = required fields present; validity =
  pattern/range pass) — reusing the toolkit's existing SHACL pipeline;
- a **KPI/scorecard schema** (per-attribute pass-rate, freshness/timeliness from load
  timestamps) that Directus surfaces as a **steward dashboard** and the DWH can report on;
- a **corrective-workflow queue** (records failing DQ → steward TODO), the same mechanism
  as the missing-registration-nr loop.
- New annotations: `kairos-mdm:dqDimension "completeness"|"validity"|"timeliness"`,
  `kairos-mdm:dqThreshold 0.95`, `kairos-mdm:freshnessSlaHours 24`.

**G2 — DPS / sanctions screening.** Screening is an **external hook**, not core Kairos —
but the *trigger points* are model-driven. Mark which entities/attributes are screened and
where the result lands:
- `kairos-mdm:screened true` (class), `kairos-mdm:screeningList "DPS"|"sanctions"`,
  `kairos-mdm:screeningProvider "…"`;
- projector emits the **screening-status columns + a governance-gate** (a record cannot be
  approved to golden while screening is pending/failed — enforced in the Directus flow).
  Actual list connectors live in the downstream MDM-Hub repo (integration layer).

**G3 — Roles & operating model (federated governance).** Model the operating model so the
**Directus role/permission config is generated**, not hand-drawn:
- `kairos-mdm:stewardRole "DataController"|"CompanyDataSteward"|"Operations"|"Compliance"`,
  `kairos-mdm:governanceScope "global"|"local"` on classes/attributes;
- projector emits **Directus roles + field-level policies** implementing *global direction
  / local execution* (global attrs editable only by global roles; local attrs by local
  stewards). This directly realizes the deep-dive's federated model and the global-vs-local
  register split.

**G4 — Full lifecycle authoring (deactivate / merge / split / unmerge).** Golden records
need governed state transitions, not just create/edit:
- `kairos-mdm:lifecycleState` enum (`draft → active → deactivated`; plus `merged`/`split`
  provenance), `kairos-mdm:mergeable true`;
- projector emits the **lifecycle state column + audited transition rules** (merge keeps a
  crosswalk survivor + tombstones the loser; split reverses it) wired into Directus flows
  with the built-in audit trail. Match/merge stays in the mastering engine; **governed
  approval of the merge** stays in the steward workbench.

**G5 — Enablement for global processes (onboarding/KYC, external validation).** The hub
**supplies and governs** the data these processes need; it does **not own** the process
(deep-dive §3.2). Model the enablement surface:
- `kairos-mdm:enrichmentProvider "Creditsafe"|"D&B"` on attributes that can be
  externally validated/enriched; `kairos-mdm:kycRelevant true` to flag attributes the
  onboarding/KYC process consumes;
- projector emits **enrichment-input columns + a provenance/lineage stamp** (which provider
  supplied/validated a value) and exposes them via the Directus API for the Fracht-Digital
  onboarding process — connectors live downstream, ownership stays with Fracht Digital.

### Net result

With G1–G5 added, the advisory now covers **all seven §7.2 building blocks and every §3.1
capability area**. The consistent pattern holds: **annotate in the model → project the
governance artifact → operate it in Directus/Zingg**. Governance is not bolted on in the
UI; it is **generated from the ontology**, keeping the full MDM surface shift-left and
regenerable.

> **Scope reminder:** G1–G5 are **Phase 2 (operational)** capabilities. **Phase 1 (MDMAD)**
> still needs only the crosswalk + dimension fields + the missing-data TODO loop — the
> governance depth above is deliberately deferred until the hub becomes authoritative.

---

## 9. Critical review & architectural corrections (rubber-duck pass)

A hard review surfaced one **framing flaw** that the rest of this doc must be read through,
plus several corrections. They do not overturn the direction — they **constrain** it.

### 9.1 The core correction — MDM is *stateful*, not stateless codegen

Every existing Kairos projection (dbt, silver, gold, TMDL, Neo4j, prompt) emits
**disposable** artifacts: delete and re-project, nothing is lost. **MDM is fundamentally
different** — it owns **durable, mutable business state**: minted `MDM_PARTY_ID`s,
source-key links, steward decisions, merge/split history, lifecycle state, resolved
exceptions, golden-record edits, audit trail, reference-data values. **None of that is
regenerable.** Treating the MDM hub "like silver/gold" is the single biggest risk in this
advisory, and it strains the toolkit's *"never edit generated output"* principle — because
here the runtime store **is** the authoritative, human-edited source.

**Architectural invariant (adopt explicitly):**
> **Generated MDM artifacts are disposable; MDM data is not.** The `mdm` projector generates
> **contracts + idempotent migrations**, never the live state. It may `CREATE`/`ALTER` via
> migration; it may **never** `DROP`/overwrite a table holding minted IDs or stewarded
> values, and **never re-mints an ID**.

### 9.2 `MDM_PARTY_ID` identity contract (must be defined before any build)

`MDM_PARTY_ID` is a durable enterprise identifier, not a projected column. Required policy:
- **Append-only, never reused.** Re-projection may change schema; it must **never re-mint**.
- **Matching proposes links; it does not auto-rewrite existing IDs** without governed approval.
- **Merge** → survivor + loser→survivor mapping + tombstone (no destructive update);
  **split** → provenance-preserving replacement mappings; **unmerge** supported.
- **Match-rule changes are versioned**; improved rules never silently re-cluster live IDs.
- **Historical DWH facts stay resolvable** to the ID valid at load time (crosswalk versioning).

Without this contract the architecture is unsafe — a rule change could break every
historical Power BI join.

### 9.3 Ownership matrix — who owns what, and is destructive regen allowed

| Asset | Ontology-owned | Generated | Runtime-owned | Destructive regen? |
|---|:--:|:--:|:--:|:--:|
| Table/collection shape | ✅ | ✅ | — | migration only |
| `MDM_PARTY_ID` + crosswalk links | — | — | ✅ | **never** |
| Golden-record values | — | — | ✅ | **never** |
| Match ruleset (template) | ✅ | ✅ | tuned | versioned only |
| Reference-list **schema** | ✅ | ✅ | — | migration only |
| Reference-list **values** | seed once | seed once | ✅ | **never** |
| Directus roles/permissions (baseline) | ✅ | ✅ | tuned | migration + drift-detect |
| Directus flows / audit / runtime tuning | — | — | ✅ | **never** |

The doc's earlier "generate config from the ontology" (esp. §5.1, §8-G3/G4) is **too
strong for ongoing operation**: Directus generation must be **bootstrap + idempotent
migration with drift detection**, not repeated overwrite, or it clobbers steward-tuned
permissions, flows and dashboards.

### 9.4 Runtime is an operational platform, not a projection side-effect

Postgres + Directus + Zingg/Spark (+ possible event bus + sync-back connectors) bring
**operational ownership** the toolkit does not otherwise carry: who patches Directus, runs
Spark, owns backup/restore/DR, manages SSO, validates sync-back safety, handles incidents.
Kairos should **generate contracts and starter scaffolds** and stop there — it must **not
imply ownership of the running platform**. An explicit *operational responsibility model*
(client/ops-owned) is a prerequisite before recommending these services as default.

### 9.5 Phase 1 may need **none** of this — the minimal-viable option

The near-term client need is **analytical only**: deterministic crosswalk + minimal
dimension fields, read-only into the DWH, no operational impact. That is very likely
deliverable with the **existing toolkit** — no new target, no hub, no services:

| Option A — **Minimal Phase 1 (recommended to evaluate first)** | Option B — Strategic MDM platform |
|---|---|
| Existing `silver`/`dbt` projection emits `party_crosswalk` + `dim_party_mdm` into Fabric/DWH | New `mdm` target + `init-mdm-hub` + Postgres + Directus + Zingg |
| Deterministic SQL match on validated VAT/KBO | Full mastering engine |
| Exception rows as a dbt model/table; stewarding deferred | Directus steward workbench |
| **Zero new services, zero new runtime** | New operational platform to run |
| Stable-ID allocation still required (append-only surrogate) | Same |

**Recommendation:** justify Option B only if there is a **committed Phase 2 path** needing
stable operational IDs, human stewardship, and sync-back. Otherwise **do Phase 1 as Option
A** and prove value first. The full `mdm` target / `init-mdm-hub` is likely **premature for
Phase 1**. (Even Option A must honor §9.2's append-only ID rule.)

### 9.6 Other corrections folded in

- **Deterministic match is not trivial** — the complexity is in *exceptions*: one reg-nr
  shared by several parties, one party with several IDs, malformed/obsolete/missing numbers,
  branch-vs-global confusion. Phase 1 must **auto-link only high-confidence exact validated
  identifiers**, route everything else to the exception queue, and **never auto-merge
  conflicting authoritative IDs**.
- **Deployment/migration model needed** — create/alter/drop semantics, ordering, backfill,
  destructive-change approval, drift detection, rollback, environment promotion. "Project
  MDM artifacts" is unsafe without it.
- **Governance annotations risk becoming an app-config DSL** (§8-G1–G5). Keep the ontology
  to **stable semantic intent** (mastered entities, identifiers, ownership hints,
  validation); push provider/threshold/workflow/runtime details into downstream hub config
  that *references* ontology concepts. Annotating `screeningProvider "D&B"` does not solve
  contracts, retries, licensing, retention or legal compliance.
- **Directus API ≠ operational MDM API** — it's a generic table API. For operational
  consumers, expose **versioned domain views / a thin contract layer**, not raw tables, so
  schema migrations don't break consumers. Treat Directus API as steward/admin by default.
- **Sync-back is underspecified** — `originSystem` loop-guard is nowhere near enough
  (partial failure, idempotency, field-ownership conflicts, source rejection, rollback,
  legal accountability). Keep it a **conceptual contract only** until a dedicated
  integration architecture exists.

### 9.7 Net effect on the recommendation

The direction (ontology-driven MDM, OSS/Fabric-independent runtime) still holds, **but**:
1. reframe the projector as **contract/migration generation**, not runtime ownership
   (rename to `mdm-contract` / `mdm-bootstrap` to signal this);
2. make the **append-only identity contract** (§9.2) a hard prerequisite;
3. adopt the **ownership matrix** (§9.3) and treat Directus gen as bootstrap+migration;
4. **default Phase 1 to Option A** (§9.5) — existing projections, no new services — and
   gate Option B on a committed Phase 2;
5. keep **sync-back and heavy governance annotations out of scope** until Phase 2 is real.

---

## 10. Open questions for you

1. **Phase 1 shape — the big one (§9.5):** deliver Phase 1 as **Option A** (existing
   silver/dbt projection emits `party_crosswalk` + `dim_party_mdm` into the DWH, deterministic
   SQL, **zero new services**) — or commit now to **Option B** (new `mdm` target +
   `init-mdm-hub` + Postgres/Directus/Zingg)? My lean: **Option A first**, gate Option B on a
   committed Phase 2.
2. **Is there a committed Phase 2?** — the answer to (1) hinges on this. Real near-term need
   for stable operational IDs + human stewardship + sync-back, or analytical-only for now?
3. **Identity contract (§9.2):** accept `MDM_PARTY_ID` as **append-only, never re-minted,
   match-rule-versioned** as a hard prerequisite — even for Option A?
4. **Match execution in Phase 1** — start with **plain-SQL deterministic match** on validated
   VAT/KBO (auto-link only high-confidence, everything else → exception queue), deferring
   **Zingg** to Phase 2? (Recommended per §9.6.)
5. **Party Groups** — confirm they stay **out of Phase 1** entirely (deep-dive C5).
6. **Reference-list authority** — confirm CargoWise as the harmonization baseline for Phase 1
   reference lists (UN/LOCODE etc.).

---

## 11. Suggested next steps (once questions are settled)

1. Draft the `kairos-mdm:` vocabulary (`scaffold/kairos-mdm.ttl`) — Phase-1 subset first.
2. Add `mdm` to the projection targets; implement the Phase-1 crosswalk + DIM-contract +
   TODO-schema projector (reusing catalog/extension-merge infra), with scenario tests in
   `tests/scenarios/acme-hub` (add an `*-mdm-ext.ttl` + `test_scenario_mdm.py`).
3. Add the `kairos-design-mdm` + `kairos-execute-mdm` skills (+ scaffold copies under
   `src/kairos_ontology/scaffold/skills/`).
4. Prototype the Directus steward-UI config generation from the annotated ontology.
5. Later increment: `init-mdm-hub` downstream scaffold + `kairos-setup-mdm-hub` /
   `kairos-package-mdm-hub` skills; Zingg + sync-back for Phase 2.
6. Record the decision as **DD-092** (MDM Hub architecture) once the approach is agreed.

---

_Advisory only — no toolkit code changed and no DD entry created. This document proposes
how an MDM Hub add-on fits the Kairos framework and how to stand up a client MDM Hub._
