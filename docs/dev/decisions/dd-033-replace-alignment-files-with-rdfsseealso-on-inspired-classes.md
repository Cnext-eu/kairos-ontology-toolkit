# DD-033: Replace Alignment Files with rdfs:seeAlso on Inspired Classes

**Status:** Accepted
**Date:** 2026-05-30
**Affects:** modeling workflow, skill guidance, scaffold, DD-032 alignment mechanism
**Supersedes:** DD-032 §4 (alignment file convention)
**Implementation:** Skill docs updated; `model/alignments/` removed from scaffold and scenario tests.

### Context

DD-032 introduced the Reference Model Inspired strategy with SKOS alignment files
(`model/alignments/{domain}-{standard}-alignment.ttl`) as the formal traceability mechanism.
In practice, these files:

- Were **never loaded** by any projector, validator, or design skill
- Required maintaining a **separate file** that could drift from the domain ontology
- Provided no **inline context** when editing silver/gold extensions for an inspired class
- Duplicated information already expressible with standard RDFS predicates

### Decision

**Replace alignment files with `rdfs:seeAlso` directly on inspired class definitions.**

```turtle
# BEFORE (separate file, not loaded, high maintenance)
# model/alignments/party-fibo-alignment.ttl:
:LegalEntity skos:exactMatch fibo-be:LegalPerson .

# AFTER (inline, machine-readable, zero overhead)
# model/ontologies/party.ttl:
:LegalEntity a owl:Class ;
    rdfs:label "Legal Entity"@en ;
    rdfs:comment "A legal entity / company."@en ;
    rdfs:seeAlso <https://spec.edmcouncil.org/fibo/ontology/BE/LegalEntities/LegalPersons/LegalPerson> .
```

**Why `rdfs:seeAlso`:**
- Part of core RDFS — no extra imports needed
- Non-committal — no logical entailments (unlike `owl:equivalentClass` or `rdfs:subClassOf`)
- Machine-readable — tooling can resolve the URI to check reference model alignment
- Loaded with the domain ontology — visible during silver/gold design sessions
- Already used for property-level references to standards (established pattern)

### Rationale

| Approach | Loaded by tooling? | Inline context? | Maintenance? |
|----------|---|---|---|
| Alignment file (DD-032 original) | ❌ Never loaded | ❌ Separate file | High |
| `rdfs:comment` provenance text | ✅ Loaded | ✅ Inline | Low but not machine-readable |
| **`rdfs:seeAlso` (this decision)** | ✅ Loaded | ✅ Inline | Low + machine-readable |

### Consequences

- `model/alignments/` folder is **removed** from scaffold and skill guidance
- Existing hubs with alignment files can migrate by adding `rdfs:seeAlso` to classes
  and deleting the alignment folder
- Design skills can now read `rdfs:seeAlso` to show reference model context
- Projectors continue to ignore `rdfs:seeAlso` (no code change needed)
- DD-032 principles 1-3 remain unchanged; principle 4 is replaced by this decision
