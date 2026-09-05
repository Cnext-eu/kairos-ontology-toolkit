# DD-093: Governed contracted-source replacement in source coverage

**Status:** Accepted

**Date:** 2026-07-18

**Affects:** `src/kairos_ontology/core/dbt_contracts.py`,
`src/kairos_ontology/core/dbt_contract_sync.py`,
`src/kairos_ontology/core/source_coverage.py`,
`src/kairos_ontology/core/projections/medallion_dbt_projector.py`,
`src/kairos_ontology/cli/main.py`, advanced dbt/mapping/Silver skills

**Implementation:** `meta.kairos.replaces_sources`,
`kairos-dbt:replacesSource`, `sync-dbt-contracts --bronze-sources`,
`check-claims` source coverage

### Context

A wrong-grain, duplicate-prone, or structurally unsuitable Bronze table may need a
contracted dbt transformation before it is safe as a Silver source. DD-061 previously
required the original table or one of its columns to be a SKOS mapping subject. Adding
that mapping only to satisfy coverage creates a second source-authority path and can
route projection around the governed transformation.

Calling manually declared metadata "lineage" would overstate what the toolkit proves:
Kairos does not parse arbitrary SQL into verified row- or column-level lineage.

### Decision

- A contract may declare `meta.kairos.replaces_sources`, containing canonical absolute
  HTTP(S) Bronze `SourceTable` IRIs. Names, labels, and filenames are not authority.
- The declaration is a governed replacement assertion, not verified SQL lineage.
- `sync-dbt-contracts` validates each IRI against a separate non-generated Bronze input
  root and emits `kairos-dbt:replacesSource` in the managed virtual vocabulary.
- Replacement coverage requires agreement across the canonical source IRI, one approved
  source-table class/reference-data claim, the contract `target_class`, a table-level
  `skos:exactMatch`, synchronized managed RDF, and `silverSourceRef`.
- Direct and replacement mappings for the same domain/source are a blocking conflict.
  Multiple replacement contracts for the same authority path are also blocking.
- Contract replacement inputs are included in generated dbt `_sources.yml` independently
  of SKOS mappings, so executable SQL can use `source()` without granting direct semantic
  mapping authority.
- Hubs and contracts without replacement metadata keep the existing direct-coverage path
  and do not acquire replacement-specific source resolution.

### Rationale

The invariant closes the coverage false negative without weakening the gate or inventing
a second transformation DSL. Canonical IRIs avoid ambiguous source identity. Claims own
semantic approval, SKOS owns virtual-source meaning, Silver extensions own routing, dbt
SQL remains executable truth, and tests verify behavior. Requiring all surfaces to agree
prevents metadata alone from laundering an unrelated joined table into coverage.

### Consequences

- Authors must copy stable Bronze table IRIs into contracts and synchronize before
  mapping or projection.
- `skos:closeMatch`, broader/narrower/related mappings, column-only mappings, and stale
  generated vocabularies cannot authorize replacement.
- A deliberate direct/replacement overlap must be resolved rather than hidden by
  precedence.
- SQL-internal lineage remains deferred; the replacement assertion is reviewable but not
  a mechanical proof of which rows or columns the SQL consumes.
- Source discovery reconciles equivalent monolithic/split RDF views by canonical table
  IRI and exact table/column subgraph equality. Divergent definitions and cross-system
  duplicate authority remain blocking.
- Generated dbt-contract tables are excluded from LLM affinity analysis and active
  affinity obligations. Their contract target and governed replacement evidence already
  form the authority chain; legacy generated affinity reports are archived.
- Split vocabulary files share their top-level source-system identity. Legacy
  filename-derived affinity reports are excluded from gates and archived when source
  analysis is refreshed, preventing stale duplicate obligations.
- Affinity schema v2 remains unchanged. Removing generated virtual systems resolves the
  observed filename/folder mismatch without forcing claim-registry hash churn for
  ordinary sources. Canonical table IRI remains mandatory at the contract boundary; an
  IRI-first affinity schema is deferred until a real-source identity case requires it.
