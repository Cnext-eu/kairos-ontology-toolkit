# Business Glossary

This folder holds the **company business glossary** — a SKOS vocabulary that
captures the alternative / business-specific names the company uses for things,
**without modifying the domain ontology**.

It is produced by the **kairos-design-discovery** skill (Phase 2) and consumed by
the **kairos-design-mapping** skill to improve source-column → domain-property
matching.

## Why a separate glossary?

In many sectors — especially freight forwarding and logistics — a company reuses
industry terms with a *different* meaning, or has its own in-house names for
standard concepts. These alternative names are valuable when mapping source data,
but they must **not** pollute the canonical domain ontology.

The glossary is therefore an **overlay**: it links a business term to the existing
domain class/property *by IRI reference only* (`rdfs:seeAlso` / `skos:relatedMatch`).
The domain `.ttl` files are never edited.

## File convention

```
businessdiscovery/{company}-glossary.ttl
```

Each entry is a `skos:Concept`:

| Predicate | Meaning |
|-----------|---------|
| `skos:prefLabel` | The canonical / domain-aligned term |
| `skos:altLabel` | The company's alternative name(s) — one triple per synonym |
| `skos:definition` | What the business means by it (esp. when it differs from the industry meaning) |
| `rdfs:seeAlso` | IRI of the related domain class or property (reference only) |
| `skos:relatedMatch` | Optional cross-reference to a reference-model concept |

See `glossary-template.ttl` for a worked logistics example.

## How mapping uses it

When a source column name (or description) matches a concept's `skos:altLabel`,
the mapping skill surfaces the concept's linked domain property as a **candidate**
mapping. Candidates are always confirmed with the user before any mapping TTL is
written — the glossary is advisory, never authoritative.
