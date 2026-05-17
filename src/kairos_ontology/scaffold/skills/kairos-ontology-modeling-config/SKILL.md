---
name: kairos-ontology-modeling-config
description: >
  Interactive ontology modeling configurator with business alignment checkpoints,
  session persistence, and naming guidance. Extends the core modeling skill with
  pause/resume capability and structured validation gates.
---

# Ontology Modeling Configurator

This skill extends `kairos-ontology-modeling` with an interactive, business-aligned
modeling workflow. It ensures naming decisions and design choices are validated
with stakeholders before generating TTL files.

## When to invoke this skill

Invoke this skill **instead of** `kairos-ontology-modeling` when:
- Modeling a new domain from scratch
- Refactoring or renaming existing classes
- The user wants to review/approve design decisions step by step

## Session Management (Configurator Pattern)

### On start — Check for existing session

At the beginning of every modeling session, look for saved configuration files:

```
ontology-hub/.modeling-sessions/
  └── {domain}-config-{YYYY-MM-DD-HHmm}.md    # Saved session state
```

**Ask the user:**

> "I found a saved modeling session for `{domain}` from `{date}`.
> Would you like to:
> 1. **Continue** from that session (pick up where we left off)
> 2. **Start fresh** (new session, previous one archived)
> 3. **Review** the saved session first"

If no session exists, start fresh and create one immediately.

### Session file format

Save progress to `ontology-hub/.modeling-sessions/{domain}-config-{timestamp}.md`:

```markdown
# Modeling Session: {Domain Name}

**Started:** {datetime}
**Last updated:** {datetime}
**Status:** IN_PROGRESS | PAUSED | COMPLETED

## Domain Scope

| Decision | Choice | Confirmed? |
|----------|--------|-----------|
| Domain name | {value} | ✅/❓ |
| Namespace | {value} | ✅/❓ |
| Reference model imports | {list} | ✅/❓ |
| Subclass vs extend strategy | {choice} | ✅/❓ |

## Classes Confirmed

| # | Class Name | Business Term | Subclass of | Status |
|---|-----------|---------------|-------------|--------|
| 1 | {OWL name} | {what users call it} | {parent or none} | ✅ Confirmed / ❓ Open |

## Properties Confirmed

| # | Property | Domain | Range | Business Term | Status |
|---|----------|--------|-------|---------------|--------|
| 1 | {name} | {class} | {type} | {what users call it} | ✅/❓ |

## Open Questions

- [ ] {question 1}
- [ ] {question 2}

## Design Decisions Log

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | {question} | {choice made} | {why} |
```

### Saving and pausing

- **Auto-save** the session file after each confirmed decision
- When the user says "pause", "stop", "save", or "continue later":
  1. Update the session file with current state
  2. List remaining open questions
  3. Confirm: "Session saved. You have N open questions remaining."

---

## Business Alignment Checkpoints

### Checkpoint 1: Naming Alignment (MANDATORY before creating any class)

For every new class, **explicitly ask**:

> "I'm proposing the OWL class name `:{ProposedName}`.
>
> **Business context check:**
> - What do your users/business call this? (e.g., 'cargo line', 'shipment item', 'goods entry')
> - Will this name be clear on a Power BI dashboard or report?
> - Does any source system already use a term for this?
>
> **Reference model context:**
> - The reference model calls this `{refmodel:ClassName}` — our class will extend it via `rdfs:subClassOf`.
> - Inherited properties from the reference model: {list key ones}
>
> Proposed name: `:{ProposedName}` — would you like to keep this or rename?"

**Naming decision table** (present for each class):

| Consideration | Guideline |
|---|---|
| **Matches business language?** | Use the term people say in meetings |
| **Distinct from reference model parent?** | Only subclass if there's real semantic difference |
| **Clear in BI/reports?** | Would a business user understand `dim_{snake_case_name}`? |
| **Consistent across domains?** | Same pattern as other domain classes |

### Checkpoint 2: Subclass Justification (MANDATORY when extending reference model)

Before creating any `rdfs:subClassOf` relationship, validate:

> "You want `:{YourClass} rdfs:subClassOf {ref:ParentClass}`.
>
> **Subclass vs. direct use — which applies?**
>
> | Create subclass when... | Use parent class directly when... |
> |---|---|
> | You need a discriminator in silver | It's the same concept, just with more properties |
> | Multiple variants exist (e.g., AirCargo, SeaCargo) | Only one kind in practice |
> | Different lifecycle or natural key | Same lifecycle as parent |
> | Business has a distinct name for it | Just adding fields to the standard class |
>
> **Does `:{YourClass}` pass at least one 'create subclass' criterion?**"

If the user cannot justify the subclass, suggest:
```turtle
# Instead of subclassing, extend the parent directly:
:myNewProperty rdfs:domain ref:ParentClass ;
    rdfs:range xsd:string .
```

### Checkpoint 3: Property Design — Flat vs. Structured

When a property could be modeled as either flat columns or a structured object:

> "The reference model uses a **structured** pattern:
> ```
> CargoItem → hasWeight → Weight (weightValue + weightUnit)
> ```
>
> For your use case, I can model this as:
>
> | Option | Pattern | Silver result | Pros | Cons |
> |---|---|---|---|---|
> | A: Flat | `grossWeightKg : xsd:decimal` | Single column, unit in name | Simple, no joins | Loses unit flexibility |
> | B: Structured | `hasWeight → Weight` | Extra table or inlined | Flexible, multi-unit | More complex |
> | C: Hybrid | Flat + `originalWeightUnit` | Two columns | Audit trail + simple | Slight redundancy |
>
> Which approach fits your business needs?"

### Checkpoint 4: Domain Boundary Verification

Before modeling any class, verify it belongs to this domain:

> "Before I add `:{ClassName}` to `{domain}.ttl`:
> - ✅ This domain's `owns` boundary includes: _{list from data-domains.yaml}_
> - 🚫 This domain's `does_not_own` excludes: _{list from data-domains.yaml}_
>
> Does `:{ClassName}` fall within the `owns` scope?"

### Checkpoint 5: Inheritance Impact Review

After every 3-5 classes are confirmed, pause and show:

> "**Inheritance summary so far:**
>
> ```
> ref:ParentA
>   └── your:ChildA (inherits: prop1, prop2, prop3)
>       └── adds: newProp1, newProp2
>
> ref:ParentB
>   └── your:ChildB (inherits: propX, propY)
>       └── adds: newPropZ
> ```
>
> **Silver projection preview:**
> These will become tables: `silver_{domain}.{table1}`, `silver_{domain}.{table2}`
>
> Does this structure make sense from a data warehouse perspective?"

---

## Completion: Final Configuration Report

When the user confirms all classes and properties, generate a final report:

Save to `ontology-hub/.modeling-sessions/{domain}-config-FINAL-{timestamp}.md`:

```markdown
# Modeling Configuration Report: {Domain Name}

**Completed:** {datetime}
**Domain file:** `model/ontologies/{domain}/{domain}.ttl`
**Ontology version:** 1.0.0

## Summary

| Metric | Count |
|--------|-------|
| Classes defined | N |
| Properties defined | N |
| Reference model imports | N |
| Subclass relationships | N |
| Design decisions made | N |

## Naming Map (Business ↔ Technical)

| Business Term | OWL Class/Property | Reference Parent | Silver Table/Column |
|---|---|---|---|
| {what users say} | :{TechnicalName} | ref:{Parent} | silver_{domain}.{table} |

## Inheritance Tree

```
{full tree showing all classes and their parents}
```

## Design Decisions Audit Trail

| # | Decision | Choice | Rationale | Stakeholder |
|---|----------|--------|-----------|-------------|
| 1 | {question} | {choice} | {reason} | {who confirmed} |

## Open Items for Follow-up

- {any deferred decisions}
- {any items that need silver extension work}

## Next Steps

- [ ] Create silver extension (`model/extensions/{domain}-silver-ext.ttl`)
- [ ] Create source mappings (`model/mappings/{source}/{source}-to-{domain}.ttl`)
- [ ] Run `python -m kairos_ontology validate`
- [ ] Run `python -m kairos_ontology project --target silver`
```

---

## Anti-patterns this skill prevents

| Problem | How this skill prevents it |
|---|---|
| Naming mismatch (CargoLine vs GoodsItem vs CargoItem) | Checkpoint 1 forces explicit naming discussion |
| Unnecessary subclassing | Checkpoint 2 requires justification |
| Flat vs structured confusion | Checkpoint 3 shows trade-offs explicitly |
| Modeling concepts outside domain boundary | Checkpoint 4 verifies ownership |
| Silver layer surprises | Checkpoint 5 previews projection impact |
| Lost context between sessions | Session files persist all decisions |
| No audit trail for design choices | Final report captures everything |
