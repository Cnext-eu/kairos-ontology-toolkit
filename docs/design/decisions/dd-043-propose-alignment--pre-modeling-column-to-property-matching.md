# DD-043: Propose-alignment — pre-modeling column-to-property matching

**Status:** Accepted
**Date:** 2026-06-05
**Affects:** `propose_alignment.py`, `cli/main.py`, `kairos-design-domain` skill
**Implementation:** `src/kairos_ontology/propose_alignment.py`

### Context

After DD-042 (table-centric classification), each source table is assigned to a data
domain. But the classification is domain-level — it doesn't tell you which source
*columns* map to which reference model *properties*. The modeling skill
(`kairos-design-domain`) had to do this matching manually during the Source Evidence
Table step, often without the reference model's property inventory in context. This
led to:
- Custom local classes being created when reference model classes already covered the
  concept
- Property naming that diverged from reference model property names
- No machine-readable alignment proposal for the modeling skill to consume

### Decision

Add a new `propose-alignment` CLI command that performs **LLM-powered, per-table
column-to-property alignment** against the reference model. The command:

1. Reads affinity reports (`*-affinity.yaml`) to scope tables by domain
2. Resolves `domain_uris` via the OASIS XML catalog to local reference model TTLs
3. For each table: sends ONE LLM call with the table's columns + the domain's
   reference model classes+properties → gets back per-column alignment
4. Produces per-domain `*-alignment.yaml` files (table-centric schema) plus a
   reference class rollup

Design choices:
- **One call per table** (not per domain) — avoids context window overflow for
  domains with many tables/columns, adopted from rubber-duck critique
- **Two-stage in a single prompt** — first table→class, then column→property,
  using the `likely_entity` hint from affinity reports
- **Table-centric output** with reference rollup — consistent with affinity report
  structure and easier to consume alongside it
- **Affinity reports required** — must run `analyse-sources` first; alignment
  reports go into the same `_analysis/` directory

### Rationale

- Bridges the gap between domain-level classification (DD-042) and property-level
  modeling — the missing "middle layer" in the analysis→modeling pipeline
- Pre-computed alignment removes the need for the modeling skill (an LLM itself) to
  do property-level matching in real-time, which can exceed context windows
- Table-centric schema mirrors affinity reports for consistency and easy consumption
- Reuses existing infrastructure: `parse_reference_model`, `parse_source_vocabulary`,
  `CatalogResolver`, `ai_provider`

### Consequences

- The `kairos-design-domain` skill's Step 0a now checks for `*-alignment.yaml` and
  uses it to pre-populate the Source Evidence Table's Ref Match column
- The `reference_rollup` section shows per-class coverage gaps, helping the modeler
  focus on unmatched areas
- `custom_columns` entries (alignment=custom) identify source columns that will need
  new local properties — the modeling skill can focus review there
- Output is additive: does not modify or replace affinity reports
