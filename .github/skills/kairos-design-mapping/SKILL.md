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
   > **Starting fresh — archive, don't overwrite (DD-071).** When the user chooses to
   > start a new session instead of resuming, first move any existing
   > `.sessions-design/mapping-{source}-to-{domain}-*.md` log(s) for this
   > source→domain pair into `ontology-hub/.sessions-design/_archive/` (create it if
   > missing; keep the original filename). Never delete a previous log. Then create
   > the new session log.
5. **Load the business glossary (if present):** check
   `ontology-hub/businessdiscovery/*.ttl` (produced by the **kairos-design-discovery**
   skill). Index each `skos:Concept`'s `skos:altLabel`s and the domain IRI it links
   to via `rdfs:seeAlso`. These are **advisory** alternative names used to match
   source columns whose names use the company's own vocabulary — see Phase 2.
6. **Check for mapping hints (DD-045):** if a `*-alignment.yaml` produced with
   `propose-alignment --include-mapping-hints` exists for the domain, load it. Its
   `transform_hint` / `structural_hints` fields give you a richer starting point.
   They are **advisory** — see "Consuming Mapping Hints (DD-045)" below. If no hint
   file exists, proceed exactly as before (hints are optional).

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

> **If DD-045 hints are loaded:** surface any table-level `structural_hints`
> (`split_candidate`, `dedup_candidate`, `merge_candidate`,
> `multi_target_candidate`) as *proposals* during alignment — e.g. a
> `split_candidate` on a `Type` discriminator suggests mapping one source table to
> several subclasses. These are candidates only; all carry
> `requires_human_confirmation: true` and MUST be confirmed before you encode any
> split/dedup/multi-target mapping.

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

> **If a business glossary is loaded (Phase 0, step 5):** when a source column name
> or description matches a concept's `skos:altLabel`, surface the concept's linked
> domain property (`rdfs:seeAlso` IRI) as a **candidate** target — this is how the
> company's own jargon (e.g. logistics terms) gets resolved to the canonical
> property. Glossary matches are **advisory only**: present them with the evidence
> ("matched altLabel 'House Bill'"), and require explicit user confirmation before
> writing TTL (never auto-approve a glossary-derived mapping). Record glossary-based
> decisions in the session file.

> **If DD-045 hints are loaded:** pre-fill the *Transform* column from each
> column's `transform_hint`, and mark the row's source as machine-suggested. A
> hint with `requires_human_confirmation: false` (exact-name + same-logical-type
> passthrough) may use the auto-approve fast-track; **every** hint with
> `requires_human_confirmation: true` MUST be confirmed by the user before TTL.
> Always derive the SKOS predicate yourself from the `alignment` category (hints do
> not carry a SKOS predicate — see below). Never paste a `CAST(...)` hint into TTL
> without confirming the encoding with the user.

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

## Consuming Mapping Hints (DD-045)

`propose-alignment --include-mapping-hints` can enrich `*-alignment.yaml` with
**advisory, non-authoritative hints**. They give you a richer starting point but
**never replace** your reasoning or the user-confirmation gates.

**What the hints contain:**

| Field (column-level) | Meaning | How to use |
|---|---|---|
| `transform_hint` | Suggested SQL transform (`source.Col` passthrough or `CAST(...)`) | Pre-fill the Transform column; confirm unless trivial passthrough |
| `transform_confidence` | 0.0–1.0 deterministic confidence | Show as evidence; do not treat as approval |
| `requires_human_confirmation` | `false` only for exact-name + same-logical-type passthrough | If `true`, you MUST confirm with the user before TTL |
| `transform_rationale` | Why the hint was generated | Show to the user as evidence |

| Field (table-level) | Meaning | How to use |
|---|---|---|
| `structural_hints[]` | `split_candidate` / `dedup_candidate` / `merge_candidate` / `multi_target_candidate` | Surface as proposals in Phase 1; all require confirmation |

**Rules when hints are present:**

1. **No SKOS predicate is provided.** Derive it yourself from the `alignment`
   category (`exact`→`exactMatch`, `semantic`/`partial`→`closeMatch`/`narrowMatch`,
   `custom`→needs a new property first). The hint generator deliberately omits the
   SKOS predicate because it is a trivial relabel of `alignment`.
2. **Hints accelerate, never decide.** Still read the bronze vocabulary and domain
   ontology independently (Gate 4). Still confirm every non-trivial transform and
   every structural hint (Gate 5).
3. **Honor `requires_human_confirmation`.** A polished `CAST(...)` hint is a
   *candidate* — confirm the source encoding/business policy before writing it.
4. **Hints are optional.** If no hint file exists, run the workflow exactly as
   before.

See `docs/instruction-guides/context-engineer-methodology-guide.md` for the
deterministic / promptable / judgment tiering behind this design.

---

## Review-flagged maps (DD-069, issues #167/#168)

`propose-alignment` runs a deterministic plausibility/address review pass. A
column in `*-alignment.yaml` that looks structurally implausible is **kept
mapped** but annotated:

| Field (column-level) | Meaning | How to use |
|---|---|---|
| `review` | `true` when a deterministic rule flagged this map | Treat the map as **unconfirmed** — re-read the bronze column and the domain property before accepting it |
| `review_reason` | Why it was flagged (address-part on a non-address scalar; boolean/financial → identity; no name-token overlap + low confidence) | Show to the user as evidence; correct the mapping or confirm it is intentional |

**Rules:**

1. **Review flags never block.** `check-alignment` lists them in a report-only
   "flagged for review" section; they are independent of the `--strict`
   custom-column gate (issue #164).
2. **Address-part columns** (`SHIPPER_STREET`, `billing_zip`, …) flagged onto a
   party scalar usually belong on a shared `Address` concept via an address
   relationship. With **cross-module alignment** (DD-070, see below) the shared
   `Address` class becomes a real candidate and these columns can be matched
   directly; otherwise model the relationship locally or confirm the scalar map
   deliberately.
3. **Always reconcile every `review: true` column** before completing the
   mapping — either fix the target property or note the confirmation in the
   Column Mapping Table.

---

## Cross-module candidates (DD-070, issue #166)

By default `propose-alignment` only considers the **home domain's** reference
classes, so a column whose true match lives in a sibling / shared accelerator
module (a shared `Address`, `PaymentTerms`, `currency`, …) gets force-fit onto an
unrelated home scalar. Run with `--cross-module --accelerator <name>` to widen the
**property** candidate pool to the whole accelerator while still classifying the
**table** against home classes only:

```bash
kairos-ontology propose-alignment --cross-module --accelerator logistics
```

When a column matches a sibling/shared-module class, its entry in
`*-alignment.yaml` gains:

| Field (column-level) | Meaning | How to use |
|---|---|---|
| `ref_module` | The owning module of the matched non-home class (e.g. `reference-data`) | Tells you **which module to `owl:imports`** to use this class |
| `ref_module_uri` | The module's namespace URI | Resolve/import the module |
| `belongs_to_domain` / `belongs_to_domains` | Data-domain(s) that import the module | Context only — prefer `ref_module` as the actionable signal |

A separate top-level **`cross_module_matches`** section rolls these up per
class, listing the `ref_module` and the contributing `source_columns` — your
checklist of which shared/sibling modules the domain needs to import. The home
`reference_rollup` is unchanged.

**Rules:**

- `--cross-module` **requires** `--accelerator`; without a resolvable accelerator
  it errors (no silent fallback — table-less shared modules are invisible to
  affinity reports).
- Default output (no `--cross-module`) is **byte-identical** — none of the new
  fields appear.
- A cross-module run is never skipped by the freshness cache after a prior
  home-only run (params are part of the freshness signature).

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
| `kairos-design-discovery` | **Upstream** — creates the business glossary of alternative names (consumed in Phase 0/2) |
| `kairos-design-source` | **Upstream** — creates bronze vocabulary (input to this skill) |
| `kairos-design-domain` | **Upstream** — creates domain ontology (target for mappings) |
| **`kairos-design-mapping`** (this) | Creates SKOS mapping files interactively |
| `kairos-execute-report` | **Downstream** — generates HTML coverage reports from mappings |
| `kairos-design-silver` | **Downstream** — uses mappings for extension annotations |
| `kairos-execute-project` | **Downstream** — generates dbt models from mappings |

### Typical pipeline order

```
0. kairos-design-discovery → company context + business glossary (businessdiscovery/)
1. kairos-design-source   → bronze vocabulary (.vocabulary.ttl)
2. kairos-design-domain   → domain ontology (.ttl)
3. kairos-design-mapping  → SKOS mapping files (model/mappings/)
4. kairos-design-silver   → silver extension annotations
5. kairos-design-gold     → gold extension annotations (for Power BI)
6. kairos-execute-project → dbt/silver/powerbi output
```

> This matches the canonical **Fresh Hub Lifecycle** in the **kairos-help** skill.

---

## JSON-Expanded Columns (DD-039)

When the bronze vocabulary contains columns with `kairos-bronze:derivedFromJson`
(created by `import-source` from `extract-schema` v1.1 output), these represent
flattened JSON fields available in the `bronze_expanded` schema.

### Mapping to expanded columns

Map domain properties to expanded column URIs the same way as regular columns:

```turtle
bronze-sys:tblOrders_details__firstName skos:exactMatch domain:firstName ;
    kairos-map:transform "source.firstName" .
```

### Recommending silverSourceRef

**After mapping** to any `derivedFromJson` column, suggest adding
`kairos-ext:silverSourceRef` to the silver extension file:

```turtle
domain:Order kairos-ext:silverSourceRef "stg_erp_orders_details" .
```

This tells the dbt projector to use `{{ ref('stg_erp_orders_details') }}`
instead of `{{ source('erp', 'tblOrders') }}`, routing the model through
the `bronze_expanded` staging layer that flattens JSON.

**Without this annotation**, the projector uses raw bronze — which won't have
the expanded columns available.

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
