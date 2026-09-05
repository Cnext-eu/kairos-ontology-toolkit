# DD-021: Extension-as-Whitelist for Imported Class Projection

**Status:** Proposed
**Date:** 2026-05-01
**Affects:** silver projector, gold projector, `projector.py`, `kairos-ext:` annotation vocabulary
**Implementation:** `src/kairos_ontology/projections/projector.py`, extension annotation handling

### Context

The reference-model-first workflow encourages hub authors to build domain ontologies primarily via `owl:imports` of reference models (BSP, MMT, DCSA, FIBO). When a domain ontology imports a reference model, `load_graph_with_catalog()` resolves the import and loads all triples into the same rdflib.Graph. However, the silver and gold projectors filter classes by namespace — only classes whose URI starts with the domain's own namespace produce DDL output. This means imported classes are loaded but ignored.

This creates a gap: import-only domains (e.g., `party.ttl` that imports BSP/Party) generate no silver DDL at all, forcing hub authors to create extension files that duplicate what the projector could infer.

However, auto-including ALL imported classes is dangerous. Large ontologies like FIBO contain hundreds of classes; importing FIBO for a few concepts would pollute the silver layer with unwanted tables.

### Decision

Imported classes are only projected when **explicitly claimed** via extension annotations:

1. **Per-class claiming**: `kairos-ext:silverInclude true` (or `goldInclude`) on individual imported classes in the domain's extension file.
2. **Bulk claiming**: `kairos-ext:silverIncludeImports true` (or `goldIncludeImports`) on the `owl:Ontology` resource — includes all classes from first-level `owl:imports`, excluding peer hub domain imports.

Four new `kairos-ext:` annotation properties:

| Annotation | Level | Type | Purpose |
|------------|-------|------|---------|
| `silverInclude` | Class | boolean | Claim an imported class for silver projection |
| `silverIncludeImports` | Ontology | boolean | Bulk-claim all first-level imported classes for silver |
| `goldInclude` | Class | boolean | Claim an imported class for gold projection |
| `goldIncludeImports` | Ontology | boolean | Bulk-claim all first-level imported classes for gold |

Peer hub domain detection: `run_projections()` collects namespaces of all hub `.ttl` files into a `hub_domain_namespaces` set. The bulk flag excludes any import whose namespace matches a peer hub domain — preventing cross-domain table duplication.

### Rationale

| Approach | Pros | Cons |
|----------|------|------|
| Auto-include all imports | Zero config | FIBO pollution; no control over scope |
| Extension-as-whitelist | Explicit; prevents pollution; gradual adoption | Requires extension file for imports |
| Whitelist + bulk flag | Best of both: explicit per-class OR convenient bulk | Slightly more complex |

The whitelist + bulk flag approach was chosen because:
- It prevents pollution from large upstream ontologies
- It gives hub authors explicit control over their silver/gold scope
- The bulk flag provides convenience for import-only domains
- Peer hub exclusion prevents cross-domain table duplication
- It preserves backward compatibility — existing hubs with only local classes are unaffected

### Consequences

- Extension files become the control point for imported class projection
- Import-only domains need at minimum one extension annotation (bulk or per-class)
- Local classes (domain namespace) continue to be auto-projected (unchanged)
- The BUG-3/IMP-1 namespace filter moves from the silver/gold projectors to `_run_projection()` in projector.py
- New helper functions: `_discover_whitelisted_imports()`, `_get_reference_model_namespaces()`
- Schema for adopted imported classes comes from the hub domain name, not the reference model namespace

### Property Inheritance Clarification

The DD-021 notice is **informational only** — properties from unclaimed parents are
**always inherited automatically**. The projector's `_get_class_and_ancestors()` function
traverses the full `rdfs:subClassOf` chain and includes datatype + FK properties from
all ancestor classes that are NOT separately projected.

**Architectural decision matrix:**

| Scenario | Action required | Result |
|----------|----------------|--------|
| Want parent properties in child table | None — automatic | Child table includes all inherited properties via ancestor traversal |
| Want parent as its own separate table (S3) | Add `silverInclude "true"` on parent class | Parent gets own table; child is folded into it with discriminator column |
| Want all imported classes as separate tables | Add `silverIncludeImports "true"` on ontology | All first-level imports get tables (use sparingly) |

**Key insight:** `silverInclude` does NOT mean "inherit properties" — inheritance
always works. It means "project this class as its own table". When a parent IS
projected as its own table, S3 single-table inheritance kicks in: the child class
is folded into the parent table with a discriminator column (the child does NOT get
its own table).

**When to ignore the DD-021 notice:**
- Your domain class extends a reference model class
- You want your domain class as its own table with all inherited parent properties
- You do NOT want the reference model parent as a separate table
- → Properties already flow through; the notice is confirming this is intentional

### Examples

**Import-only domain (bulk):**
```turtle
# party-silver-ext.ttl
<https://acme.example/ont/party> kairos-ext:silverIncludeImports true .
```

**Selective claiming:**
```turtle
# party-silver-ext.ttl
bsp-party:TradeParty kairos-ext:silverInclude true .
bsp-party:Buyer      kairos-ext:silverInclude true .
```

**Mixed domain (local + imports):**
```turtle
# booking-silver-ext.ttl — only need claims for imported classes
bsp-party:TradeParty kairos-ext:silverInclude true ;
    kairos-ext:scdType "2" ;
    kairos-ext:naturalKey "partyCode" .
```
