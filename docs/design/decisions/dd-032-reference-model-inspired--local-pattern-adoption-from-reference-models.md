# DD-032: Reference Model Inspired — Local Pattern Adoption from Reference Models

**Status:** Accepted
**Date:** 2026-05-30
**Affects:** modeling workflow, skill guidance, scaffold, alignment file conventions
**Implementation:** No code changes required — Inspired classes are regular local classes already supported by all projectors. Guidance lives in skills and `docs/design/dd-032-reference-model-alignment.md`.

### Context

Kairos hubs face a tension when working with industry reference models (FIBO, HL7 FHIR,
GS1, Schema.org):

- **Reference Model Enforced** (`owl:imports` + `rdfs:subClassOf`): Full structural coupling.
  Works well for small, projection-compatible reference models (Kairos reference model repos
  like BSP, TIC). Fails for large, axiom-heavy models (FIBO imports 1000+ classes; DD-021
  whitelisting and DD-023 shared defaults exist specifically to manage this complexity).

- **SKOS alignment file only** (no structural adoption): Zero runtime cost,
  clean projections, but the alignment is *documentation only* — it never influences the
  silver schema. The alignment file says "we're like FIBO" but the silver tables don't
  benefit from FIBO's structural patterns (Identifier, PartyInRole, Classification).

**The gap:** There is no supported pattern for adopting the *structural intent* and
*semantic patterns* of a reference model while keeping a fully local, projection-optimized
ontology.

### Decision

> **⚠ AMENDED by DD-044 (2026-06-12):** The default strategy has been flipped.
> **Enforced** (`owl:imports` + `silverInclude`) is now the default for all reference
> models. **Inspired** is an opt-in override for cases where import is impossible or
> undesirable. See DD-044 for full rationale.

Introduce **Reference Model Inspired** as the ~~**default**~~ **opt-in** strategy for
reference model alignment. **Reference Model Enforced** (full `owl:imports`) is the
~~override~~ **default**, with `silverInclude` whitelisting (DD-021) ensuring only
claimed classes are projected.

**Reference Model Inspired definition:**

> Mirror reference model structural patterns as local classes (own namespace), with
> `rdfs:seeAlso` back-references (DD-033). No `owl:imports` at runtime.

**The simplified strategy model (2 strategies):**

| Strategy | When | What |
|----------|------|------|
| **Reference Model Enforced** (default — amended by DD-044) | All reference models; `silverInclude` whitelisting prevents projection noise | `owl:imports` + DD-021 whitelist |
| **Reference Model Inspired** (opt-in) | When import is impossible (proprietary model, no TTL); deliberate structural deviation | Local patterns + `rdfs:seeAlso` |

**Enforced eligibility** (ALL must be true):
- Published in `ontology-reference-models/` central repo
- Small (< 50 classes), focused domain
- Ships `*-silver-defaults.ttl` (DD-023 compatible)
- Has `catalog-v001.xml` entry
- No transitive imports pulling in unrequested concepts

**Core principles:**

1. **Local ownership** — All classes and properties are in the hub's own namespace.
   No `owl:imports` of external ontologies at runtime.
2. **Selective pattern adoption** — Cherry-pick only patterns that provide business
   value. Zero adoption is valid (no local class created).
3. **Projection-first gate** — Only adopt a pattern as a local class when it produces
   a **structurally different silver schema** (new table or new relationship).
4. **Inline traceability** — Use `rdfs:seeAlso <reference-model-class-URI>` on each
   inspired local class for machine-readable back-reference to the source pattern.
5. **rdfs:seeAlso is ignored by projectors** — It is documentation for
   designers revisiting extension properties, not a runtime input.

**Silver structural difference criterion** (the key decision gate):

| Question | Answer | Action |
|----------|--------|--------|
| Does adopting this pattern create a new silver table? | Yes | Adopt as local class ✅ |
| Does it create a new FK relationship? | Yes | Adopt as local class ✅ |
| Does it inline to the same flat columns (S4, embedded)? | Yes | Optional — ontology clarity only ⚠️ |
| Does it have no projection target at all? | Yes | Do NOT adopt ❌ |

**Practical examples:**

| Pattern | Silver impact | Adopt? |
|---------|--------------|--------|
| `Identifier` (replaces 6 flat string properties) | New `identifier` table with scheme + validity | ✅ Yes |
| `PartyInRole` (role hierarchy) | New `party_in_role` table with discriminator | ✅ Yes |
| `LegalFormClassifier` (replaces flat `legalForm`) | Inlined via S4 — same `legal_form` column | ⚠️ Optional |
| `QuantityValue` (value + unit) | Inlined as two columns on parent | ⚠️ Optional |
| `DatePeriod` (temporal qualification) | Handled by SCD2 — no separate table | ❌ Skip |

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Enforced for everything | Full OWL reasoning | FIBO imports 1000+ classes; DD-021 noise; slow |
| Alignment file only (no adoption) | Zero cost | Zero structural benefit; silver schema doesn't improve |
| **Reference Model Inspired (this)** | Selective structural benefit; clean projections; formal alignment | Requires judgment on which patterns to adopt |
| Domain-local subclasses of imported classes | OWL-correct | Property inheritance issues; namespace confusion |

**Industry best practices supporting this decision:**

| Pattern | Source | How it maps |
|---------|--------|-------------|
| FHIR Profiling | HL7 | Constrain/extend base spec without forking = adopt pattern, own namespace |
| DDD Anti-Corruption Layer | Evans | Alignment file = ACL at domain boundary |
| SSN/SOSA Modularization (MOMo) | W3C | Lightweight core + optional alignment modules |
| Canonical Data Model | EIP (Hohpe & Woolf) | Hub ontology = CDM; SKOS mappings = translators |
| "Conformance = what you use" | W3C DCAT v2 | Align to patterns you USE, not everything in ref model |
| Domain ownership | Data Mesh (Dehghani) | Hub domain owns its silver schema; aligns formally but doesn't couple |

**Why Inspired is the default (not Enforced):**

1. Inspired with zero patterns adopted = no local classes, just documentation (minimum case).
2. The silver structural difference criterion answers "how much to adopt?" on a
   per-pattern basis — no separate strategy needed.
3. Simplifies skill guidance and decision flowcharts.
4. Skills only need one question: "Does this pattern pass the silver structural
   difference test?" — if yes, adopt (with `rdfs:seeAlso`); if no, skip.

### Consequences

**Immediate (this PR):**
- Reference Model Inspired is the default approach for all reference models
- Reference Model Enforced is the override for Kairos-managed ref model repos only
- See `docs/design/dd-032-reference-model-alignment.md` for full specification

**Future work (separate PRs):**

| Component | Update needed |
|-----------|---------------|
| `kairos-design-domain` skill | Use Inspired/Enforced terminology; `rdfs:seeAlso` (DD-033) |
| `kairos-setup-config` skill | Scaffold guidance (no `model/alignments/` — see DD-033) |
| `kairos-diagnose-status` skill | Detect `rdfs:seeAlso` on inspired classes |
| `kairos-execute-project` skill | Clarify `rdfs:seeAlso` is never used in projections |
| `kairos-design-silver` skill | Present Inspired as alternative to imports + whitelisting |
| `kairos-design-gold` skill | Same |
| `kairos-execute-validate` skill | Optional: validate `rdfs:seeAlso` URIs resolve |
| `kairos-help` skill | Update conceptual overview with 2-strategy model |
| `kairos-design-mapping` skill | Document that Inspired patterns change mapping structure |

**No projector code changes required.** Inspired classes are regular local classes —
the projector already handles them identically to any hub-defined class. The alignment
file lives in `model/alignments/` and is never loaded during projection.

**Relationship to DD-021/DD-023:**
- DD-021 (extension-as-whitelist) applies to **Enforced** only — when you `owl:imports` a
  reference model, you whitelist which imported classes to project.
- DD-023 (shared extension defaults) applies to **Enforced** only — reference model repos
  ship `*-silver-defaults.ttl` for imported classes.
- DD-032 (this) applies when you do NOT import — you create local equivalents instead.
- A hub may use Enforced for Kairos reference models AND Inspired for industry standards
  simultaneously.
