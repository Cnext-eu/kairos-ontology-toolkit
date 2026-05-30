# Extension Vocabulary Consistency Review & CR-3 Challenge

**Date:** 2026-05-30  
**Status:** Open — design review  
**Scope:** `kairos-ext:` vocabulary consistency, over-engineering assessment, CR-3 challenge  

---

> **Verification note (2026-05-30):** Every claim below was re-checked against the
> projector source. Verdicts: ✅ verified accurate · ⚠️ partially correct ·
> ❌ inaccurate (corrected inline). See the Verification Log appendix for the full
> claim → verdict → citation mapping.

## 1. Consistency Issues

### A. Undeclared annotations (used in code, NOT in `kairos-ext.ttl`) — ✅ verified

| Annotation | Used in | Test coverage | Severity | Verdict |
|---|---|---|---|---|
| `kairos-ext:perspective` | gold projector L473 | ✅ test_gold_projector.py | HIGH — vocabulary gap | ✅ confirmed absent from `kairos-ext.ttl` |
| `kairos-ext:generateTimeIntelligence` | gold projector L643, L772 | ✅ test_gold_projector.py | HIGH — vocabulary gap | ✅ confirmed absent |
| `kairos-ext:olsRestricted` | gold projector L1035 | ✅ test_gold_projector.py | HIGH — vocabulary gap | ✅ confirmed absent |
| `kairos-ext:incrementalColumn` | gold projector L435 | ❌ no rendering, see below | HIGH — **dead annotation** | ⚠️ corrected — see note |

**Impact:** Hub authors using `perspective`, `generateTimeIntelligence`, and
`olsRestricted` get no SHACL validation, no IDE autocompletion from the vocabulary
file, and no documentation via `rdfs:comment`. These three work silently but
users can't discover them from the vocabulary alone.

> **⚠️ Correction — `incrementalColumn` is two different annotations.** The original
> review treated this as a single functional-but-undeclared item. In fact:
>
> - **`kairos-ext:incrementalColumn`** (gold) is read at `medallion_gold_projector.py`
>   L434-435 into `GoldTableDef.incremental_column` (init L189) but is **never
>   rendered** anywhere in the gold output — there is no other reference to
>   `incremental_column` in the projector. It is therefore a **dead annotation**,
>   not merely undeclared. (The acme-hub fixture
>   `tests/scenarios/acme-hub/model/extensions/invoice-gold-ext.ttl` already sets
>   it to `"invoice_date"`, but nothing consumes the value.)
> - **`kairos-bronze:incrementalColumn`** is a *different*, fully-functional
>   annotation: declared in `kairos-bronze.ttl` and consumed by the dbt projector
>   at `medallion_dbt_projector.py` L264. It drives incremental dbt materialization.
>
> Reusing the same local name (`incrementalColumn`) across two namespaces with two
> different behaviours is itself a naming hazard — see §6.

### B. Declared but unused / partially used annotations

| Annotation | Declared in TTL | Actually consumed? | Verdict |
|---|---|---|---|
| `kairos-ext:rolePlayingAs` | ✅ declared (L258) | ❌ commented out in gold projector (L1125) | ✅ confirmed unused |
| `kairos-ext:surrogateKeyStrategy` | ✅ declared (L35) | ❌ **not read by any projector** | ❌ corrected — see note |

> **❌ Correction — `surrogateKeyStrategy` is fully unconsumed, not "partially used".**
> The original review said it is "read but never branches (hard-coded uuid)". A grep
> for `surrogateKeyStrategy` across `src/kairos_ontology/projections/*.py` returns
> **zero matches** — no projector reads it at all. It appears only in the vocabulary
> declaration (`kairos-ext.ttl` L35), the `silver-ext.ttl.template`, and
> `docs/USER_GUIDE.md`. It therefore belongs in the **same "declared but entirely
> unused" bucket as `rolePlayingAs`** — the SK strategy is effectively hard-coded in
> code with no annotation lookup whatsoever.

### C. Inconsistent access patterns — ⚠️ corrected

The original review stated "the dbt projector uses `KAIROS_EXT.term("silverColumnName")`
style while silver/gold projectors use `KAIROS_EXT.silverColumnName` directly." This
is **oversimplified**. The real inconsistency is **inside the dbt projector itself**,
which mixes both styles:

- `KAIROS_EXT.term("silverColumnName")` (L1396, L1412), `KAIROS_EXT.term("naturalKey")`
  (L1734), `KAIROS_EXT.term("inheritanceStrategy")` (L827)
- vs. direct attribute access: `KAIROS_EXT.isReferenceData` (L988),
  `KAIROS_EXT.populationRequirement` (L1220), `KAIROS_EXT.silverForeignKey` (L1399),
  `KAIROS_EXT.derivationFormula` (L1266)

Both forms are equivalent (rdflib `Namespace` supports either), so this is a
cosmetic code-style issue — but it lives within a single file, not across projectors.

---

## 2. Over-Engineering Assessment

### Vocabulary size: 40+ annotations across 4 layers

| Layer | Count | Complexity |
|---|---|---|
| Silver ontology-level | 5 | Low — schema/naming/audit config |
| Silver class-level | 9 | Medium — identity, SCD, inheritance, GDPR, partition |
| Silver property-level | 8 | Medium — column overrides, nullability, population |
| Gold ontology-level | 3 (+2 undeclared) | Low |
| Gold class-level | 4 (+1 undeclared) | Low |
| Gold property-level | 8 (+1 undeclared) | Medium |
| Import whitelisting | 4 | Low |
| FK annotations | 2 | Low |

### Annotations with overlapping concerns

1. **`naturalKey` + `surrogateKeyStrategy` + (proposed) `identityStrategy`** — three
   annotations for "how do we identify this entity?" Could be simplified.
2. **`populationRequirement` + `nullable`** — overlap: `required` implies NOT NULL,
   `unmapped` implies nullable. But they answer different questions (intent vs physical
   constraint), so justified.
3. **`silverColumnName` + `goldColumnName`** — duplication across layers. But gold may
   legitimately need different names. Justified.

### Verdict: NOT over-engineered (but contains dead weight)

The vocabulary follows "one annotation = one question answered." Most annotations have
clear, non-overlapping responsibilities. The **real problems** are not excess
complexity but:

1. The **3 undeclared-but-live** annotations (`perspective`,
   `generateTimeIntelligence`, `olsRestricted`) — a discoverability/validation gap.
2. **2 declared-or-used-but-dead** annotations (`surrogateKeyStrategy` — declared,
   never read; `kairos-ext:incrementalColumn` — read into a field, never rendered)
   plus the commented-out `rolePlayingAs`. These should be either wired up or removed.

---

## 3. CR-3 Challenge: `identityStrategy` Proposal

### What CR-3 proposes

Add `kairos-ext:identityStrategy` with values: `standalone` / `composite` / `embedded`,
plus `kairos-ext:identityParent` to declare the parent relationship.

### Challenge points

| # | Challenge | Reasoning |
|---|---|---|
| 1 | **"composite" is redundant** | If a class has `silverForeignKeyOn` pointing at it AND has a `naturalKey`, the projector already has enough info to generate a composite SK. No new annotation needed. |
| 2 | **"embedded" has no projector consumer** | Neither silver nor dbt projector has code to skip table generation. This would require significant new logic with no current use case. |
| 3 | **`identityParent` duplicates existing topology** | `silverForeignKeyOn` already points at the child class FROM a property — the parent relationship is encoded in the graph. Adding `identityParent` re-declares what the graph already expresses. |
| 4 | **Option 4 (better warnings) is sufficient** | The real problem is a confusing WARNING, not a missing annotation. Improved messages explaining FK-child context resolve the user's pain. |
| 5 | **Composite SK is a projector logic question** | When `silverForeignKeyOn` targets a class, the projector could auto-include `parent_sk` in the composite key. This is a code change in `_get_natural_key()`, not a new annotation. |

### Where CR-3 has valid points

| # | Valid point | Response |
|---|---|---|
| 1 | "Can't distinguish forgot vs intentional" | True for `embedded`. But how common is true embedding? In practice, FK-child entities almost always get their own table. |
| 2 | Parallel to `inheritanceStrategy` | Fair — both capture designer intent. But `inheritanceStrategy` has 2 clear projector code paths. `identityStrategy` would need new ones built first. |

### Recommendation

**Defer `identityStrategy` — implement Option 4 (better warnings) first.**

Rationale:
- Fix the undeclared annotations gap FIRST (immediate consistency win)
- Improve the naturalKey warning to mention FK-child context
- If users still struggle after better warnings, THEN add `identityStrategy`
- Don't add vocabulary that has no projector consumer yet

---

## 4. Proposed Action Items

> **Implementation status (2026-05-30):** items 1, 2, 3, 6, 7 implemented in
> `kairos-ext.ttl` plus a new guard test `tests/test_ext_vocabulary_coverage.py`.
> Items 4, 5, 8 remain open (UX / code-style / separate CR-3 doc).

| # | Action | Priority | Type | Status |
|---|---|---|---|---|
| 1 | Add `perspective`, `generateTimeIntelligence`, `olsRestricted` to `kairos-ext.ttl` (these are live but undeclared) | HIGH | Fix | ✅ done |
| 2 | Mark `rolePlayingAs` as reserved/planned (comment in TTL) | LOW | Hygiene | ✅ done |
| 3 | Decide on `surrogateKeyStrategy`: wire it into the silver projector or mark reserved — it is currently declared but never read | MEDIUM | Hygiene | ✅ done (marked RESERVED) |
| 4 | Improve naturalKey WARNING — detect FK-child context, explain options | MEDIUM | UX | ⬜ open |
| 5 | Standardize `KAIROS_EXT.term("...")` → `KAIROS_EXT.x` **within the dbt projector** | LOW | Style | ⬜ open |
| 6 | Resolve `kairos-ext:incrementalColumn` (gold): either render it in gold output or remove it — the acme-hub gold ext already declares it but nothing consumes the value. Do NOT add a scenario test until it renders. | MEDIUM | Fix / dead-code | ✅ declared + marked RESERVED (defer render decision) |
| 7 | Disambiguate the two `incrementalColumn` annotations (`kairos-ext:` vs `kairos-bronze:`) — see §6 naming recommendations | MEDIUM | Naming | ✅ done (TTL comment + header convention) |
| 8 | Update CR-3 doc: record challenge, recommend deferral | LOW | Documentation | ⬜ open |

**New invariant guard:** `tests/test_ext_vocabulary_coverage.py` greps the projector
source for every `KAIROS_EXT.<x>` / `KAIROS_EXT.term("<x>")` usage and asserts each is
declared in `kairos-ext.ttl` (implements recommendation §6.4).

---

## 5. References

- Extension vocabulary: `src/kairos_ontology/scaffold/kairos-ext.ttl`
- Bronze vocabulary: `src/kairos_ontology/scaffold/kairos-bronze.ttl`
- Gold projector: `src/kairos_ontology/projections/medallion_gold_projector.py`
- Dbt projector: `src/kairos_ontology/projections/medallion_dbt_projector.py`
- Silver projector: `src/kairos_ontology/projections/medallion_silver_projector.py`
- CR-3 document: `docs/draft/CR3-naturalKey-identity-strategy-2026-05-30.md`
- Design decisions: `docs/design/toolkit-design-decisions.md`

---

## 6. Naming Clarity Recommendations

Advice for making the `kairos-ext:` vocabulary easier for hub authors to use
correctly. These are recommendations, not yet implemented.

### 6.1 Inconsistent layer-prefixing

Some annotations name their layer, others don't — even though they are layer-specific:

| Layer-prefixed (clear) | Layer-neutral name, but layer-specific (unclear) |
|---|---|
| `silverSchema`, `silverColumnName`, `silverTableName`, `silverDataType` | `scdType`, `naturalKey`, `partitionBy`, `clusterBy`, `discriminatorColumn` (all silver-only) |
| `goldSchema`, `goldColumnName`, `goldTableName`, `goldTableType` | `perspective`, `olsRestricted`, `generateTimeIntelligence`, `measureExpression`, `hierarchyName` (all gold-only) |

A reader cannot tell from `scdType` or `perspective` which layer it drives.

**Recommendation:** adopt one rule — *layer-specific annotations are always
layer-prefixed* (`silver*` / `gold* `/ `bronze*`), and bare names are reserved for
genuinely cross-layer concepts (e.g. `naturalKey`, which both silver and dbt read).
Document the convention in the `kairos-ext.ttl` header.

### 6.2 Same local name across two namespaces

`kairos-ext:incrementalColumn` (gold, currently dead) and
`kairos-bronze:incrementalColumn` (bronze, live, drives dbt incremental loads) share
an identical local name but have unrelated meanings and owners. An author who copies
one into the wrong extension file gets silent no-ops.

**Recommendation:** rename one of them (e.g. gold → `goldIncrementalColumn`, or drop
it entirely per action item #6). Never reuse a local name across the `kairos-ext`,
`kairos-bronze`, `kairos-map` vocabularies.

### 6.3 Stale vocabulary file header

`kairos-ext.ttl` opens with *"Silver Layer Projection Extension Vocabulary"* and
*"Rules R1-R15"*, yet the file now also contains **Gold (G1-G8)**, **Import
Whitelisting (DD-021)**, and **Foreign Key (DD-022)** sections. The title misleads
anyone skimming the file to understand its scope.

**Recommendation:** retitle to *"Kairos Projection Extension Vocabulary (silver +
gold + imports + FK)"* and list the rule families it covers.

### 6.4 Declare every consumed annotation

The 3 live-but-undeclared annotations (§1.A) mean the vocabulary file is not the
single source of truth — authors must read projector source to discover them, and
they get no `rdfs:comment` or SHACL.

**Recommendation:** treat "every annotation the projectors read must be declared in a
vocabulary file" as an invariant, ideally enforced by a test that greps projector
source for `KAIROS_EXT.<x>` / `KAIROS_EXT.term("<x>")` and asserts each is declared.

---

## 7. Verification Log (claim → verdict → citation)

Each original claim re-checked against projector source on 2026-05-30.

| # | Original claim | Verdict | Evidence |
|---|---|---|---|
| A1 | `perspective` used (gold L473), undeclared | ✅ accurate | `medallion_gold_projector.py` L473; no match in `kairos-ext.ttl` |
| A2 | `generateTimeIntelligence` used (gold L643), undeclared | ✅ accurate | L643, L772; no match in TTL |
| A3 | `olsRestricted` used (gold L1035), undeclared | ✅ accurate | L1035; no match in TTL |
| A4 | `incrementalColumn` used (gold L435), undeclared, untested | ⚠️ corrected | Read L434-435 but **never rendered** (dead); also a *separate* live `kairos-bronze:incrementalColumn` exists (`kairos-bronze.ttl`, dbt L264) |
| B1 | `rolePlayingAs` declared, commented out (gold L1125) | ✅ accurate | TTL L258; gold L1125 commented |
| B2 | `surrogateKeyStrategy` "read but never branches" | ❌ inaccurate | **Zero** matches in `projections/*.py`; declared TTL L35 only |
| C | dbt uses `.term()`, silver/gold use direct | ❌ inaccurate | dbt mixes both: `.term()` L827/L1396/L1412/L1734 vs direct L988/L1220/L1266/L1399 |
| 4#5 | "Add `incrementalColumn` test coverage (acme-hub gold ext + scenario test)" | ❌ inaccurate | acme-hub gold ext already declares it (`invoice-gold-ext.ttl`); untestable until rendered |

