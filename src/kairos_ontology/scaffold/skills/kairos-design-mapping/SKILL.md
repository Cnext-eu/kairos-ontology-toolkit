---
name: kairos-design-mapping
description: >
  Structured, interactive workflow for creating SKOS source-to-domain column
  mappings with validation gates. Guides table alignment, column mapping with
  confidence levels, and coverage validation. NOT for running projections —
  use kairos-execute-project for that.
---

# Source-to-Domain Mapping Skill

You guide the user through creating SKOS mapping files that link source system
columns to domain ontology properties. This is a **structured, interactive**
process — never guess mappings without evidence and user confirmation.

---

## Hard Gates (BLOCKING — must not be bypassed)

### Gate 1: Session file prerequisite

> **You MUST create a `ontology-hub/.sessions-design/mapping-{source}-to-{domain}-{date}.md`
> file BEFORE writing any mapping TTL.**

If no session file exists for the source→domain pair being mapped, you are NOT
permitted to create or modify mapping `.ttl` files.

### Gate 2: No TTL without confirmed table mapping

> **You MUST NOT write a `skos:exactMatch` (or any mapping triple) until the user
> has explicitly confirmed which source table maps to which domain entity.**

### Gate 3: One source system per session

> **Never mix multiple source systems in one mapping session.**

You may map multiple tables from the same source in one session, but never
interleave tables from different sources.

### Gate 4: Source-grounded proposals (data-first)

> **You MUST read the bronze vocabulary AND domain ontology BEFORE proposing
> any mappings. Present evidence (column names, types) with every proposal.**

### Gate 5: Explicit user confirmation required

> **Every table→entity and column→property decision requires explicit user
> approval before writing TTL.**

Exception: **Auto-approve fast-track** — mappings that meet ALL criteria below
may be presented as "auto-approved" (still shown, but not blocking):
- Exact column name match (case-insensitive) to property localName
- Compatible data types (string→string, integer→integer, etc.)
- High confidence rating

The user can override any auto-approved mapping.

---

## Phased Workflow

### Phase 0 — Discover & Scope

1. List source systems in `integration/sources/` that have a `*.vocabulary.ttl`
2. Ask user which source system to map
3. Ask user which domain(s) to target (list available from `model/ontologies/`)
4. Create session file: `ontology-hub/.sessions-design/mapping-{source}-to-{domain}-{YYYY-MM-DD}.md`

### Phase 1 — Table-to-Entity Alignment

1. Read the bronze vocabulary for the selected source
2. Read the target domain ontology (classes + properties)
3. Present a **Table Alignment Proposal**:

| Source Table | Proposed Entity | Confidence | Reasoning |
|---|---|---|---|
| `customers` | Client | High | Column names match client properties |
| `invoices` | Invoice | High | Invoice-specific columns present |
| `audit_log` | *(out of scope)* | — | Operational, not master data |

4. Wait for user confirmation/correction for EACH row
5. Record decisions in session file
6. Classify non-mapped tables:
   - `operational` — audit/ETL/system tables
   - `deprecated` — known dead tables
   - `out-of-scope` — valid data, not in current domain model
   - `gap` — should be in domain → feed back to modeling skill

### Phase 2 — Column-to-Property Mapping (per confirmed table)

For each confirmed table→entity pair:

1. Read all columns from the bronze vocabulary
2. Read all properties from the target entity (including inherited)
3. Present columns in **chunks of max 15**, grouped by prefix or data type
4. For each chunk, show a **Column Mapping Proposal**:

| Source Column | Target Property | Match Type | Transform | Confidence |
|---|---|---|---|---|
| `customer_name` | `name` | exact | — | High ✓ |
| `cust_email` | `email` | exact | — | High ✓ |
| `WEIGHT_KG` | `weight` | close | `CAST(... AS DECIMAL)` | Medium |
| `INTERNAL_FLAG` | — | operational | — | — |
| `LEGACY_CODE` | — | deprecated | — | — |

5. Rows marked ✓ are auto-approved (exact name + type match)
6. Wait for user to confirm/correct remaining rows
7. Only generate TTL after full chunk confirmation
8. Proceed to next chunk

### Phase 3 — Validation & Report

1. Present coverage summary:
   - Source columns mapped: X/Y (Z%)
   - Domain properties covered: A/B (C%)
   - Unmapped classification breakdown
2. **Coverage threshold gate**: if domain property coverage < 50%, warn:
   > "Only {C}% of domain properties are covered. Consider whether the domain
   > ontology needs additional properties (invoke kairos-design-domain) or
   > if another source system covers the remaining properties."
3. Offer next actions:
   - Generate mapping report (`--target report`) for full HTML view
   - Map another table from same source
   - Start new mapping session for different source
   - Proceed to projection (`kairos-execute-project`)

---

## Match Type Decision Tree

Use the right SKOS predicate based on the relationship:

| Condition | SKOS Predicate | When to use |
|-----------|---------------|-------------|
| Exact name + same semantics | `skos:exactMatch` | Column directly represents the property |
| Similar concept, needs transform | `skos:closeMatch` | Column value needs casting/reformatting |
| Source column is broader (1→many) | `skos:broadMatch` | One source column splits into multiple properties |
| Source column is narrower (many→1) | `skos:narrowMatch` | Multiple source columns combine into one property |
| Loosely related | `skos:relatedMatch` | Informational link, not used in dbt generation |

> **Rule:** Default to `skos:exactMatch` for direct 1:1 mappings. Only use
> others when the semantic relationship genuinely differs.

---

## Transform Vocabulary

When a column needs transformation, use `kairos-map:transform` with these
supported expressions (used in dbt SQL generation):

| Pattern | Example | Meaning |
|---------|---------|---------|
| `source.{col}` | `source.customer_name` | Passthrough (default) |
| `CAST({expr} AS {type})` | `CAST(source.weight AS DECIMAL(18,4))` | Type conversion |
| `CASE WHEN {cond} THEN {val} ...` | `CASE WHEN source.status = 'A' THEN 'Active'...` | Conditional |
| `COALESCE({col1}, {col2}, ...)` | `COALESCE(source.email, source.alt_email)` | Null fallback |
| `UPPER/LOWER/TRIM({col})` | `TRIM(source.name)` | String normalization |
| `CONCAT({col1}, ' ', {col2})` | `CONCAT(source.first, ' ', source.last)` | String concatenation |
| `LEFT/RIGHT({col}, N)` | `LEFT(source.postal_code, 4)` | Substring |

For composite mappings (multiple source columns → one property), use
`kairos-map:sourceColumns` with space-separated column names.

---

## Session File Format

```markdown
# Mapping Session: {Source} → {Domain}

**Started:** {ISO-8601}
**Source:** {system_name} ({label})
**Target domain(s):** {domain1}, {domain2}
**Status:** In Progress | Complete

## Table Alignment Decisions

| Source Table | Target Entity | Decision | Classification | Confirmed |
|---|---|---|---|---|
| customers | client:Client | Map | — | ✅ {date} |
| invoices | invoice:Invoice | Map | — | ✅ {date} |
| audit_log | — | Skip | operational | ✅ {date} |
| legacy_orders | — | Skip | deprecated | ✅ {date} |
| shipments | — | Skip | gap | ✅ {date} |

## Column Mapping Decisions

### customers → Client

| Source Column | Target Property | Match | Transform | Confirmed |
|---|---|---|---|---|
| customer_name | name | exact | — | ✅ |
| cust_email | email | exact | — | ✅ (auto) |
| WEIGHT_KG | weight | close | CAST | ✅ |
| INTERNAL_FLAG | — | skipped | — | ✅ (operational) |

## Coverage Summary

- Source columns mapped: 28/42 (67%)
- Domain properties covered: 15/18 (83%)
- Unmapped: 8 operational, 4 deprecated, 2 out-of-scope
```

### Saving and pausing

- **Auto-save** the session file after each confirmed decision (fill tables immediately)
- Mark resolved Open Questions as `[x]` with the decision outcome
- Never mark a session "Complete" while Column Mapping Decisions tables are still empty
- When the user says "pause", "stop", or "continue later":
  1. Update the session file with all confirmed decisions so far
  2. List remaining tables/columns not yet mapped
  3. Confirm: "Session saved. N tables remaining."

---

## Mapping TTL Output Format

After confirmation, generate files in `model/mappings/{source}-to-{domain}.ttl`:

```turtle
@prefix skos:      <http://www.w3.org/2004/02/skos/core#> .
@prefix kairos-map: <https://kairos.cnext.eu/mapping#> .
@prefix bronze:    <https://kairos.cnext.eu/source/{system}#> .
@prefix domain:    <https://ontology.example.com/{domain}#> .

# Table-level mapping
bronze:{SourceTable}
    skos:exactMatch domain:{Entity} ;
    kairos-map:mappingType "direct" .

# Column-level mappings
bronze:{sourceColumn}
    skos:exactMatch domain:{property} .

bronze:{transformedColumn}
    skos:closeMatch domain:{property} ;
    kairos-map:transform "CAST(source.{col} AS DECIMAL(18,4))" .
```

---

## Relationship to Other Skills

| Skill | Relationship |
|---|---|
| `kairos-design-source` | **Upstream** — creates bronze vocabulary (input to this skill) |
| `kairos-design-domain` | **Upstream** — creates domain ontology (target for mappings) |
| **`kairos-design-mapping`** (this) | Creates SKOS mapping files interactively |
| `kairos-execute-report` | **Downstream** — generates HTML coverage reports from mappings |
| `kairos-design-silver` | **Downstream** — uses mappings for extension annotations |
| `kairos-execute-project` | **Downstream** — generates dbt models from mappings |

### Typical pipeline order

```
1. kairos-design-domain        → domain ontology (.ttl)
2. kairos-design-source → bronze vocabulary (.vocabulary.ttl)
3. kairos-design-mapping          → SKOS mapping files (model/mappings/)
4. kairos-design-silver → silver extension annotations
5. kairos-execute-project       → dbt/silver/powerbi output
```

---

## Anti-patterns to avoid

- ❌ Writing mapping TTL without reading the bronze vocabulary first
- ❌ Assuming column names directly correspond to property names without checking
- ❌ Using `skos:exactMatch` for everything (use closeMatch when transforms are needed)
- ❌ Mapping operational columns (created_by, updated_at) to domain properties
- ❌ Skipping the session file "because it's just one table"
- ❌ Presenting 50+ columns in one wall of text (chunk to 15 max)

---

## Related skills

| When you need | Invoke |
|---|---|
| Design/modify domain ontology classes and properties | **kairos-design-domain** |
| Generate HTML mapping report for stakeholders | **kairos-execute-report** |
| Design silver layer (DDL, SCD, FK annotations) | **kairos-design-silver** |
| Create bronze vocabulary from source docs | **kairos-design-source** |
| Run projections (generate dbt models from mappings) | **kairos-execute-project** |
