# Reference Model Inspired — Local Pattern Adoption from Reference Models

## Document Purpose

This document is the **detailed architectural specification** for the Reference Model
Inspired strategy in the Kairos Ontology Toolkit. It provides the pattern catalog,
decision flowcharts, naming conventions, migration paths, quality criteria, and mapping
implications that complement the formal decision in DD-032.

---

## 1. Overview

### The Two-Strategy Model

Kairos hubs use one of two strategies for reference model alignment:

| Strategy | Mechanism | When to use |
|----------|-----------|-------------|
| **Reference Model Inspired** (default) | Local pattern adoption + SKOS alignment file | All reference models; default strategy |
| **Reference Model Enforced** (override) | `owl:imports` + DD-021 whitelisting + DD-023 shared defaults | Small, projection-compatible Kairos reference model repos only |

Reference Model Inspired is a spectrum: from alignment-file-only (minimum) to full
structural pattern adoption (maximum). The **silver structural difference criterion**
determines how far along that spectrum a hub should go.

### Core Principles

1. **Local ownership** — All classes and properties live in the hub's own namespace.
   No `owl:imports` of external ontologies at runtime.
2. **Selective pattern adoption** — Cherry-pick only patterns that deliver business
   value. Zero adoption (alignment file only) is valid.
3. **Projection-first gate** — Only adopt a pattern as a local class when it produces
   a structurally different silver schema (new table or new relationship).
4. **Formal alignment** — A SKOS alignment file declares correspondence to the source
   vocabulary for machine-readable interoperability.
5. **Alignment file is never loaded by projectors** — It is documentation, not runtime input.
6. **Reference-model-inspired naming** — Use reference model class/property names where
   they are clear and domain-appropriate, documenting provenance in `rdfs:comment`.

---

## 2. Decision Flowchart

```
Is there a relevant reference model for this domain?
├── No → Pure local modeling (no alignment file needed)
└── Yes (default: use Reference Model Inspired)
    ├── Does user explicitly request Enforced AND model meets eligibility?
    │   └── Yes → Reference Model Enforced: owl:imports + DD-021 whitelist + DD-023 defaults
    └── Otherwise (default path)
        └── Reference Model Inspired: Local pattern adoption + alignment file
            │
            For EACH pattern in the reference model:
            ├── Does adopting it create a new silver table or FK relationship?
            │   └── Yes → Adopt as local class (structural adoption)
            ├── Does it improve ontology clarity without changing silver output?
            │   └── Yes → Adopt optionally (documentation benefit only)
            └── Does it have no projection target?
                └── Yes → Do NOT adopt
```

**Enforced eligibility criteria** (ALL must be true):
- Published in `ontology-reference-models/` central repo
- Small (< 50 classes), focused domain
- Ships `*-silver-defaults.ttl` (DD-023 compatible)
- Has `catalog-v001.xml` entry
- No transitive imports that pull in unrequested concepts
- No deep inheritance trees conflicting with S3 flattening

---

## 3. Pattern Catalog

### 3.1 Identifier Pattern

| Attribute | Value |
|-----------|-------|
| **Reference source** | FIBO FND/Arrangements/Identifiers |
| **Classes** | `Identifier`, `IdentificationScheme` |
| **Key properties** | `isIdentifiedBy`, `identifierValue`, `identifierScheme`, `validFrom`, `validTo` |
| **Silver target** | New entity table (`identifier`) + reference table (scheme, inlined via S4) |
| **Silver structural difference** | ✅ YES — creates new table with scheme + validity columns |
| **Business value** | Multi-identifier per party, validity tracking, eliminates flat property duplication |
| **Replaces** | Flat string properties (registrationNumber, vatNumber, nationalIdNumber, etc.) |
| **Adoption trigger** | Multi-source or multi-registration requirements (MDM use cases) |

**Example:**
```turtle
:Identifier a owl:Class ;
    rdfs:label "Identifier"@en ;
    rdfs:comment """A structured identifier issued by an authority.
    Pattern adopted from FIBO FND/Arrangements/Identifiers."""@en .

:isIdentifiedBy a owl:ObjectProperty ;
    rdfs:domain :Party ;
    rdfs:range :Identifier ;
    rdfs:label "is identified by"@en .
```

**Important: Reference data as seed, not TBox.**
Do NOT define scheme instances (`:KBO_Scheme`, `:VAT_Scheme`) as named individuals
in the ontology file. Load them as reference data via seed files or source system
configuration. This keeps the ontology clean (TBox only) and allows adding new schemes
without an ontology version bump.

### 3.2 Party-in-Role Pattern

| Attribute | Value |
|-----------|-------|
| **Reference source** | FIBO FND/Parties/Roles; also BSP TradeParty, TIC TerminalParty, DCSA ShippingParty |
| **Classes** | `PartyInRole` + domain-specific subclasses (Director, Shareholder, UBO, etc.) |
| **Key properties** | `roleHeldBy` (→ Party), `roleAtOrganisation` (→ LegalEntity) |
| **Silver target** | New S3-flattened table with `role_type` discriminator |
| **Silver structural difference** | ✅ YES — creates new table with role hierarchy |
| **Business value** | Same party in multiple roles, temporal role validity, fixes standalone role anti-pattern |
| **Replaces** | Flat link tables, standalone role classes (e.g., ContactPerson) |
| **Adoption trigger** | Any domain with party role relationships |

**Blueprint alignment note:** This pattern is directly used by ALL Kairos reference
models (BSP's TradeParty, TIC's TerminalParty, DCSA's ShippingParty, WCO's role classes).
It is the most blueprint-aligned Reference Model Inspired pattern.

### 3.3 Classification Pattern

| Attribute | Value |
|-----------|-------|
| **Reference source** | FIBO FND/Arrangements/ClassificationSchemes |
| **Classes** | `ClassificationScheme`, `Classifier` (or domain-specific: `LegalFormClassifier`) |
| **Key properties** | `hasClassification`, `classifierCode`, `classifierLabel` |
| **Silver target** | Reference table (inlined via S4 if ≤3 columns) |
| **Silver structural difference** | ⚠️ NO — S4 inlines to same flat column as a string property |
| **Business value** | Controlled vocabularies, multi-language labels, hierarchy (ontology clarity) |
| **Replaces** | Flat string code properties (`legalForm`, `addressType`) |
| **Adoption trigger** | ≥2 classification schemes needed in same domain (e.g., LegalForm + NACE) |

**Guidance:** Only adopt if you commit to multiple classification schemes that benefit
from a shared pattern. For a single code column, a flat `xsd:string` property with S4
inlining is simpler and produces identical silver output.

### 3.4 Quantity-with-Unit Pattern

| Attribute | Value |
|-----------|-------|
| **Reference source** | FIBO FND/Quantities/QuantitiesAndUnits; QUDT |
| **Classes** | `QuantityValue`, `UnitOfMeasure` |
| **Key properties** | `hasQuantityValue`, `hasMeasurementUnit`, `numericValue` |
| **Silver target** | Inlined (value + unit columns on parent table) |
| **Silver structural difference** | ⚠️ NO — inlines to same two columns as flat properties |
| **Business value** | Explicit units, unit conversion capability (ontology clarity) |
| **Replaces** | Bare numeric properties with implicit units |
| **Adoption trigger** | Domain has quantities in multiple units requiring conversion |

### 3.5 Patterns NOT Recommended for Adoption

| Pattern | Why not |
|---------|---------|
| **Temporal Qualification (DatePeriod)** | No projection target. SCD2 already handles temporal validity. Violates projection-first gate. |
| **Role-Qualified Address Sub-Properties** | No silver structural difference. `addressType` discriminator already handles this. Pure ontology aesthetics. |
| **Upper Ontology alignment (DOLCE, BFO)** | Too abstract. No projection target. Adds philosophical axioms without data platform benefit. |

---

## 4. File Layout

```
ontology-hub/
  model/
    ontologies/
      party/
        party.ttl                          # Runtime ontology (projection input)
    alignments/
      party-fibo-alignment.ttl             # Reference Model Inspired SKOS alignment (never loaded by projectors)
      invoice-schema-alignment.ttl         # Another domain's alignment
    extensions/
      party-silver-ext.ttl                 # Silver annotations (unchanged)
    mappings/
      adminpulse/
        adminpulse-to-party.ttl            # Source mapping (maps to local classes)
```

**Key rule:** The `model/alignments/` directory is purely documentation. Its files are
never loaded by `projector.py`. They exist for:
- Semantic interoperability with external tools
- FIBO compliance documentation
- Future MDM federation
- Alignment quality reporting

---

## 5. Alignment File Specification

### Naming convention

```
{domain}-{refmodel}-alignment.ttl
```

Examples: `party-fibo-alignment.ttl`, `product-gs1-alignment.ttl`, `patient-hl7-alignment.ttl`

### Required structure

```turtle
@prefix domain: <https://example.com/ont/party#> .
@prefix skos:   <http://www.w3.org/2004/02/skos/core#> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix fibo-x: <https://spec.edmcouncil.org/fibo/ontology/...> .

<https://example.com/ont/party/alignment/fibo> a owl:Ontology ;
    rdfs:label "Party → FIBO Alignment"@en ;
    rdfs:comment "Reference Model Inspired alignment. NOT loaded during projections."@en ;
    owl:versionInfo "1.0.0" .

# Class alignments
domain:Party        skos:exactMatch  fibo-x:Party .
domain:LegalEntity  skos:exactMatch  fibo-x:LegalPerson .
domain:Identifier   skos:exactMatch  fibo-x:Identifier .

# Property alignments
domain:isIdentifiedBy skos:exactMatch fibo-x:isIdentifiedBy .
domain:name           skos:exactMatch fibo-x:hasName .
```

### SKOS match type selection

| Relationship | When to use |
|--------------|-------------|
| `skos:exactMatch` | Same concept, same semantics, interchangeable |
| `skos:closeMatch` | Very similar but not identical (scope difference) |
| `skos:broadMatch` | Reference model concept is broader (generalization) |
| `skos:narrowMatch` | Reference model concept is narrower (specialization) |
| `skos:relatedMatch` | Associative/indirect relationship only |

---

## 6. Mapping Implications

**Critical:** Adopting Inspired patterns changes how source-to-domain mappings work.

### Flat → Structured mapping change

**Before (flat properties):**
```turtle
bronze-ap:Relation_businessNumber
    skos:closeMatch party:registrationNumber ;
    kairos-map:transform "source.business_number" .
```

**After (Identifier pattern):**
```turtle
bronze-ap:Relation_businessNumber
    skos:closeMatch party:identifierValue ;
    kairos-map:targetClass party:Identifier ;
    kairos-map:transform "source.business_number" ;
    kairos-map:contextValue "KBO" ;
    kairos-map:contextProperty party:identifierScheme .
```

The mapping now needs to express:
1. Which class the source value maps INTO (not just which property)
2. What context/scheme qualifier applies
3. How to construct the composite natural key (party NK + scheme)

**Recommendation:** When adopting Inspired patterns, update source mappings in the same
PR. Don't leave mappings pointing at deprecated flat properties.

---

## 7. Migration Paths

### Enforced → Inspired (downgrade for performance/simplicity)

1. Remove `owl:imports` from domain ontology
2. Copy adopted classes/properties into local namespace (keep same names)
3. Remove `rdfs:subClassOf` references to imported classes
4. Create alignment file with `skos:exactMatch` for copied concepts
5. Remove DD-021 `silverInclude` annotations (classes are now local = auto-projected)
6. Remove DD-023 shared defaults dependency (annotations now live in hub's own ext file)
7. Re-run projections — output should be equivalent

### Inspired → Enforced (upgrade for full reasoning)

1. Replace local class definitions with `owl:imports` + `rdfs:subClassOf`
2. Change alignment predicates to `owl:equivalentClass` (optional)
3. Add DD-021 `silverInclude` / `silverIncludeImports` to extension file
4. Verify DD-023 shared defaults are available for the reference model
5. Re-run projections and validate

### Adding a new pattern to existing Inspired hub

1. Identify pattern from catalog (§3) that passes silver structural difference test
2. Add local classes/properties to domain ontology
3. Add silver extension annotations for new classes
4. Update alignment file with new `skos:exactMatch` entries
5. Update source mappings to map into new structural classes
6. Re-run projections, verify new table/columns appear

---

## 8. Naming Conventions

### Class naming
- **PascalCase** (standard Kairos convention)
- **Prefer reference model names** when clear: `Identifier`, `PartyInRole`, `Classifier`
- **Adapt when jargon-heavy**: `LegalFormClassifier` (not FIBO's `IndustrySectorClassifier`)

### Property naming
- **camelCase** (standard Kairos convention)
- **Prefer reference model verb patterns**: `isIdentifiedBy`, `hasClassification`, `roleHeldBy`

### Provenance documentation
- Use `rdfs:comment` to note pattern source: "Pattern adopted from FIBO FND/..."
- The alignment file is the **authoritative** provenance source (not the comment)

---

## 9. Quality Criteria

A well-executed Reference Model Inspired implementation satisfies:

| # | Criterion | Verification |
|---|-----------|-------------|
| 1 | No `owl:imports` of reference model in runtime ontology | `grep "owl:imports" {domain}.ttl` = no external refs |
| 2 | Alignment file exists in `model/alignments/` | File exists with SKOS predicates |
| 3 | Adopted pattern classes have silver extension annotations | Every new class → scdType + naturalKey in ext file |
| 4 | Alignment file covers all adopted classes | Count local classes with ref model correspondence |
| 5 | Source mappings updated for structural patterns | No mappings pointing to deprecated flat properties |
| 6 | Projection output is additive (new tables, no lost columns) | Diff DDL before/after |
| 7 | No abstract classes without projection target | Every adopted class → table, ref, or inline |
| 8 | No named individuals for reference data in ontology TBox | Schemes/classifiers loaded as seed data |

---

## 10. Reference Models Suitable for the Inspired Strategy

| Reference Model | Domain | Recommended Patterns | Notes |
|---|---|---|---|
| **FIBO** (EDM Council) | Finance, Parties, Legal | Identifier, PartyInRole, Classification | Large (1000+ classes); Enforced impractical |
| **GS1** (EPCIS, CBV) | Supply Chain, Products | QuantityValue, Location, TradeItem | Medium; Enforced possible for subsets |
| **HL7 FHIR** | Healthcare | Identifier, CodeableConcept, Reference | Very large; profiling model = natural Inspired fit |
| **Schema.org** | General, Commerce | Organization, PostalAddress | Medium; flat properties don't benefit much from structural adoption |
| **PROV-O** (W3C) | Provenance | Activity, Entity, Agent | Small enough for Enforced if needed |
| **Dublin Core** | Metadata | — | Flat properties only; alignment file sufficient |

---

## 11. Relationship to Other Design Decisions

| DD | Relationship |
|----|--------------|
| DD-020 (Stable IRIs) | Inspired local classes use the hub's stable namespace (no version in IRI) |
| DD-021 (Extension-as-Whitelist) | Applies to Enforced only. Inspired classes are local = auto-projected |
| DD-022 (Simplified FK) | Applies to both strategies — FK annotations work identically on local or imported classes |
| DD-023 (Shared Defaults) | Applies to Enforced only. Inspired hubs define their own extension annotations |
| DD-014 (Silver reads Bronze) | Inspired patterns create new silver targets; Bronze→Silver mapping changes accordingly |
| DD-015 (Vocabulary as Contract) | Source vocabulary describes source shape; Inspired mapping transforms flat→structured |

---

## 12. Industry Best Practices Summary

| Principle | Source | Application in Kairos |
|-----------|--------|----------------------|
| Domain ownership / bounded context | Data Mesh (Dehghani), DDD (Evans) | Hub ontology = bounded context with own schema |
| Anti-Corruption Layer | DDD | SKOS alignment file = ACL at domain boundary |
| Profile cascade | HL7 FHIR | Reference Model Inspired = "profile" of ref model patterns |
| Lightweight core + optional modules | W3C SSN/SOSA (MOMo methodology) | Adopt core patterns; skip axiom-heavy modules |
| Conformance = what you use | W3C DCAT v2 | Align to patterns you USE, not all of ref model |
| CDM justified at N≥4 | EIP (Hohpe & Woolf) | Don't over-abstract for single-source scenarios |
| Annotation properties for platform metadata | SSN/SOSA | `kairos-ext:` stays separate from OWL axioms |
| Namespace stability | Schema.org, DD-020 | One namespace per domain; no version in IRI |

---

## Appendix A: Why OWL Punning and Selective Module Imports Are Rejected

- **OWL punning** (declaring local class with same URI as reference model class):
  Creates URI conflicts if reference model is ever loaded alongside hub ontology.
- **Selective module imports** (`owl:imports` of just one FIBO module):
  Still pulls in transitive dependencies (FIBO's Party imports Agents, which imports Relations...).
- **Neither** gives the hub full control over property definitions, cardinality, and naming.

Reference Model Inspired avoids all three by using distinct local URIs with formal SKOS alignment.

---

## Appendix B: Coexistence of Enforced and Inspired

A hub may use **both strategies simultaneously**:

```turtle
# Reference Model Enforced: import Kairos reference model (small, projection-ready)
<https://example.com/ont/party> owl:imports <https://referencemodels.kairos.cnext.eu/bsp/party> .

# Reference Model Inspired: local patterns inspired by FIBO (large, not imported)
:Identifier a owl:Class ;
    rdfs:comment "Pattern adopted from FIBO FND/Arrangements/Identifiers."@en .
```

**Precedence rule:** When an Enforced imported class and an Inspired local class model the
same concept differently, the **local class wins** for projection. The imported class
may still be used for taxonomy (as a superclass) but the local class defines the silver
schema. Document the relationship in the alignment file.
