# DD-046: Reference Model Specialization Visibility in Domain Modeling

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `kairos-design-domain` skill (both copies)
**Implementation:** `.github/skills/kairos-design-domain/SKILL.md` + `src/kairos_ontology/scaffold/skills/kairos-design-domain/SKILL.md`

### Context

Reference models now ship richer specialization trees: a parent class such as
`Party` has subclasses (`Organisation`, `Person`) that carry subclass-specific
properties (`registrationNumber` on `Organisation`; `firstName`/`lastName` on
`Person`). The `design-domain` skill, however, built its **Reference Model Class
Inventory** (Step 0c.1b) by manually reading module TTL and listing only classes
with properties whose `rdfs:domain` points **directly** at the class. It never
unpacked the subclass closure, nor referenced the DD-044 materialized inventories
(`model/inventory/*.yaml`) that already contain the full specialization tree with
subclass properties.

Result: during modeling, a parent class appears to have **none** of its subclasses'
properties. The only indirect path (the alignment YAML, Step 0a.2) surfaces a
subclass property **only if a source column happens to hit it**, so unused subclass
properties stay invisible. The modeler could therefore re-create a local class or
redefine a property that already exists on an imported subclass — silently
duplicating the reference model and undermining the reference-model-first principle
(DD-043).

### Decision

Make reference-model **subclasses and their subclass-specific properties** visible
at every point in the `design-domain` flow where the modeler could otherwise create
a local duplicate:

1. **Step 0c.1b — Reference Model Class Inventory**: prefer the DD-044 materialized
   inventory (`model/inventory/*.yaml`), which contains the specialization tree;
   fall back to raw TTL. List each class's subclasses as nested rows with their
   subclass-specific properties.
2. **Checkpoint 1 (anti-local-class)**: include specialization subclasses in the
   "available reference model classes" table so the modeler sees an existing
   subclass before inventing a similarly-named local class.
3. **Checkpoint 3b (property reuse, Step 2)**: list properties defined on existing
   **subclasses** of the parent, not just the direct `rdfs:domain` chain, and add a
   rule to subclass-and-reuse rather than create a local duplicate.

### Rationale

The fix lives entirely in the skill (documentation/guidance), reusing the inventory
artifacts DD-044 already produces — no new code, no new command, no runtime closure
resolution during modeling (the inventories are pre-materialized, per DD-044). This
keeps the deterministic tier doing the unpacking and the LLM-guided skill simply
presenting it, consistent with the three-tier methodology
(`docs/guide/practitioner/context-engineer-methodology-guide.md`).

### Consequences

- `design-domain` Step 0c.1b, Checkpoint 1, and Checkpoint 3b now surface
  subclass-defined properties; the modeler is steered to subclass-and-reuse.
- Depends on DD-044 materialized inventories being present; the skill falls back to
  raw TTL (without subclass closure) when they are absent.
- Documentation-only change to the skill (both copies kept in sync); no projector or
  CLI behavior changes.
