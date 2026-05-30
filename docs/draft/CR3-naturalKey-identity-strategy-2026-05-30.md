# CR-3 Discussion: naturalKey for FK-child Entities

**Date:** 2026-05-30  
**Status:** Resolved — Option 4 implemented, `identityStrategy` deferred  
**Context:** Part of CR-projection-warnings-2026-05-30 from PKF Bofidi hub team  
**Related:** kairos-ext:naturalKey, kairos-ext:silverForeignKeyOn  

---

## Original CR-3 Proposal

> Downgrade "no naturalKey" from WARNING → INFO for classes targeted by
> `silverForeignKeyOn`.

**Rationale from CR authors:** FK-child entities (Address, ContactPerson) are
attached via `silverForeignKeyOn` — their identity is the composite of parent FK
+ their own attributes. A standalone naturalKey may not exist.

---

## Challenge

FK-child entities still **need** identity for SK generation. The projector
generates `{class}_sk` using `naturalKey` columns. Without a naturalKey, the SK
is NULL — making any downstream FK relationship pointing to that entity
unresolvable.

Silently downgrading the warning masks a real data quality risk.

---

## The Identity Question

What is the identity model for entities targeted by `silverForeignKeyOn`?

| Option | Meaning | naturalKey needed? | Example |
|---|---|---|---|
| **A. Embedded** | No independent identity — value object accessed only through parent. | ❌ No SK generated; could be denormalized into parent | Address as columns on Party table |
| **B. Weak entity** | Identity derived from parent FK + own attributes (composite key). | ✅ Composite: `party_sk + address_type` | Address is separate table, FK-child |
| **C. Independent** | Has its own global identity from source system. | ✅ Standalone: `address_id` | Address exists independently of Party |

---

## Current Extension Vocabulary (Identity Layer)

| Annotation | Purpose | Complements? |
|---|---|---|
| `naturalKey` | Defines what makes an entity unique (business key) | Core identity |
| `inheritanceStrategy` | How subtypes are projected (discriminator/class-per-table) | Structural identity |
| `surrogateKeyStrategy` | How SK is generated (uuid) | Physical identity |
| `silverForeignKeyOn` | Which table receives the FK column | Relationship direction |
| `populationRequirement` | Whether a property must be populated (required/optional/derived/unmapped) | Column-level intent |

**Gap:** Nothing expresses *what kind of entity this is* — whether its identity
is standalone, composite with parent, or non-existent (embedded).

---

## Design Options

### Option 1: New annotation `kairos-ext:identityStrategy`

```turtle
:Address kairos-ext:identityStrategy "composite" ;
         kairos-ext:naturalKey "addressType" ;
         kairos-ext:identityParent :hasAddress .
```

Values:
- `"standalone"` (default) — entity has its own naturalKey
- `"composite"` — identity = parent SK + own naturalKey
- `"embedded"` — no separate table; properties projected onto parent table

**Pros:**
- Explicit and self-documenting
- Projector can generate correct composite keys
- Complementary with existing vocabulary (parallel to `inheritanceStrategy`)

**Cons:**
- New annotation adds complexity to design-silver workflow
- `identityParent` adds a second annotation to configure
- May need silver projector changes for composite key generation

### Option 2: Extend `naturalKey` semantics

```turtle
# Explicit "no identity" — suppress warning
:Address kairos-ext:naturalKey "none" .

# Composite identity — include parent FK in key
:Address kairos-ext:naturalKey "composite:addressType" .
```

**Pros:**
- Zero new annotations (reuses existing `naturalKey`)
- Follows pattern of `populationRequirement` (extend values on existing property)
- Lower learning curve

**Cons:**
- Overloads `naturalKey` semantics (currently: space-separated property names)
- "none" is a magic value that changes behavior (brittle)
- Harder to validate with SHACL

### Option 3: Infer from FK + naturalKey presence

- Has `silverForeignKeyOn` AND has naturalKey → weak entity (composite SK)
- Has `silverForeignKeyOn` AND no naturalKey → assume embedded, skip table
- Has no FK → standalone, require naturalKey

**Pros:**
- Zero new annotations, zero configuration
- "Convention over configuration"

**Cons:**
- Silent inference is brittle — "no naturalKey" could be a genuine gap OR intentional
- Can't distinguish between "I forgot" and "I intentionally omitted"
- Breaks the explicit-annotation philosophy of kairos-ext

### Option 4: Keep WARNING but improve message (minimal change)

Keep WARNING for ALL classes missing naturalKey, but differentiate guidance:

```
⚠️ Class 'Address' has no naturalKey — SK will be NULL.
   Context: FK-child of Party (via silverForeignKeyOn).
   Options: (a) Add naturalKey for composite identity
            (b) Add kairos-ext:identityStrategy "embedded" to suppress
   Resolve via: kairos-design-silver
```

**Pros:**
- No silent suppression of real problems
- User makes an explicit choice (design session captures it)
- Introduces `identityStrategy` only for users who need to suppress intentionally
- Aligns with "design first, then project" philosophy

**Cons:**
- More verbose warnings
- Still requires new annotation for suppression (Option 1 subset)

---

## Complementarity Analysis

The proposed `identityStrategy` would fit naturally in the identity layer:

```
Identity Layer (class-level):
  naturalKey ─────────── "What columns identify this entity?"
  identityStrategy ───── "How is identity determined?" (standalone/composite/embedded)
  inheritanceStrategy ── "How are subtypes projected?" (class-per-table/discriminator)
  surrogateKeyStrategy ─ "How is the SK generated?" (uuid)
```

Each answers a different question. They are complementary, not overlapping.

The pattern mirrors the existing `populationRequirement` annotation which also
captures *intent* rather than just *value* — it says "this column is intentionally
unmapped" rather than just being empty.

---

## Affected Entities (PKF Bofidi hub)

| Class | Current state | Likely intent |
|---|---|---|
| Address | FK-child of Party, no naturalKey | Weak entity (composite: party_sk + address_type) |
| ContactPerson | FK-child of Party, no naturalKey | Weak entity (composite: party_sk + contact_type) |
| PartyRole | No FK, no naturalKey | Independent — **genuine gap** (needs `naturalKey "link_id"`) |

---

## Open Questions

1. **Which option do we prefer?** (Recommendation: Option 1 or Option 4)
2. **For composite identity:** Should the projector auto-generate `parent_sk` as
   part of the composite key, or require it to be listed in `naturalKey`?
3. **For embedded entities:** Should the projector actually denormalize columns
   onto the parent, or just skip table generation entirely?
4. **SHACL validation:** If we add `identityStrategy`, should SHACL shapes
   enforce that `naturalKey` is present when strategy = "standalone"?

---

## Recommendation

**Option 4** (improved warning + Option 1 annotation available for suppression)
provides the best balance:

- Warnings remain actionable (not silently suppressed)
- Users who intentionally omit naturalKey have an explicit annotation to declare intent
- The design session captures the decision (visible in `.sessions-design/`)
- Aligns with the existing vocabulary philosophy (explicit > implicit)

**Implementation would be:**
1. Add `kairos-ext:identityStrategy` to `kairos-ext.ttl` vocabulary
2. Update silver projector: suppress WARNING when `identityStrategy = "embedded"`
3. Update dbt projector: generate composite SK when `identityStrategy = "composite"`
4. Update warning message to reference available options
5. Update `kairos-design-silver` skill to ask about identity strategy for FK-children

---

## References

- Extension vocabulary: `src/kairos_ontology/scaffold/kairos-ext.ttl`
- naturalKey logic: `src/kairos_ontology/projections/medallion_dbt_projector.py:1690`
- FK detection: `src/kairos_ontology/projections/medallion_dbt_projector.py:1359`
- Silver skill: `.github/skills/kairos-design-silver/SKILL.md`
- Original CR: `pkf-bofidi-ontology-hub/.docs/draft/CR-projection-warnings-2026-05-30.md`

---

## Resolution (2026-05-30)

Following the consistency review in `extension-vocabulary-review-2026-05-30.md` §3,
this CR was **challenged and resolved as follows**:

**Decision: implement Option 4 (improved warning) now; defer `identityStrategy`.**

Rationale (from the review challenge):
- The CR's "composite" case is already derivable: when `silverForeignKeyOn` targets
  a class that also has a `naturalKey`, the projector has enough information to build
  a composite key — no new annotation is required.
- The "embedded" case has **no projector consumer** today (neither silver nor dbt
  skips table generation), so adding `identityStrategy "embedded"` would introduce
  vocabulary with nothing to honour it. Per the "don't add vocabulary that has no
  projector consumer yet" principle, this is deferred.
- `identityParent` re-declares the parent relationship that `silverForeignKeyOn`
  already encodes in the graph.
- The user's real pain was a **confusing WARNING**, not a missing annotation.

**Implemented (Option 4):** the dbt projector's missing-`naturalKey` warning now
detects FK-child context via `_fk_child_parents()` and, when the class is targeted
by `silverForeignKeyOn`, names the parent(s) and explains the options (add a
composite/weak-entity key, add a source identity key, or denormalise onto the
parent). See `medallion_dbt_projector.py` (`_fk_child_parents` + the
missing-naturalKey branch) and `tests/test_dbt_projector.py::TestNaturalKeyWarning::test_warning_mentions_fk_child_context`.

**Deferred:** `kairos-ext:identityStrategy` / `identityParent`. Revisit only if hub
teams still struggle after the improved warnings — at which point the implementation
steps listed under "Recommendation" above apply. See design decision DD-034.
