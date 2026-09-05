# DD-092: Contracted custom dbt transformation boundary

**Status:** Accepted

**Date:** 2026-07-18

**Affects:** `src/kairos_ontology/core/dbt_contracts.py`,
`src/kairos_ontology/core/dbt_contract_sync.py`,
`src/kairos_ontology/core/dbt_validation.py`,
`src/kairos_ontology/core/projections/medallion_dbt_projector.py`,
`src/kairos_ontology/core/projector.py`, `src/kairos_ontology/cli/main.py`,
hub scaffold and `kairos-develop-dbt-transformation` skill

**Implementation:** `sync-dbt-contracts`, `project --platform`,
`validate-dbt`

### Context

Some Bronze-to-Silver entities require joins, windows, ranking, aggregation,
JSON expansion, fallback rules, source union, or grain changes beyond normal
SKOS column expressions. Encoding an arbitrary execution graph in RDF would
duplicate dbt, while replacing the generated Silver model entirely would lose
ontology-driven keys, relationships, SCD policy, tests, and documentation.

The existing `silverSourceRef` (DD-039) already routes a generated Silver model
through `ref()`, but it does not package user-owned transformations, define and
synchronize their output contract, or validate the assembled dbt graph.

### Decision

Introduce a contracted custom dbt boundary:

- Handwritten dbt SQL under `integration/transforms/dbt/` owns executable
  relational logic.
- dbt model properties YAML is the single physical authority for output column
  names/types, the physical grain assertion, physical key columns, adapter
  support, dependencies, decision provenance, and tests.
- Kairos deterministically generates a managed, committed Bronze-compatible
  virtual-source vocabulary from the contract. `sync-dbt-contracts` is the only
  writer; projection performs a semantic freshness check and never rewrites
  source artifacts.
- Existing SKOS mappings map virtual output columns to ontology properties.
  Existing `kairos-ext:silverSourceRef` selects the bundled dbt model; no second
  routing annotation or output-binding vocabulary is introduced.
- The ontology and Silver extension remain authoritative for business meaning,
  semantic natural-key properties, SK/IRI/FK/SCD policy. Kairos validates their
  alignment with physical key columns through mappings.
- Custom models, schema/unit-test YAML, singular tests, and namespaced macros
  are bundled. Paths, names, collisions, references, and a toolkit-owned package
  allow-list are validated before dbt target files are written.
- Domain-scoped projection assembles only active contracts for the selected
  ontology plus their transitive custom-model `ref()` dependency closure. Model
  properties, verifying tests, required macro files, and governed packages follow
  that closure; unreachable contracts from another domain are not copied.
- `project --platform fabric|databricks` generates one adapter-specific package
  per invocation at the backward-compatible `output/medallion/dbt/` path.
  Dual-adapter CI uses separate temporary output roots.
- `validate-dbt --platform` requires dependency installation and parse, inspects
  manifest edges, and attempts compile. Connection-dependent compile failures
  are environment-blocked; SQL/Jinja/contract/graph failures remain blocking.
- `meta.kairos.decisions` records descriptive rationale, evidence, confidence,
  approval, implementing model, and verifying tests. It is never interpreted as
  executable transformation configuration.
- `kairos-develop-dbt-transformation` provides the interactive authoring
  workflow. It requires grain/identity and contract checkpoints and routes
  ontology, mapping, and Silver changes through their existing design skills.

### Rationale

This creates one explicit semantic boundary without making Kairos a general SQL
compiler. Each concern has one authority, existing mapping and routing machinery
is reused, and the generated Silver wrapper retains governance Kairos can
actually enforce. Adapter-specific generation acknowledges that Fabric and
Databricks types and constraints are not interchangeable. Explicit
synchronization keeps committed mapping inputs reviewable without allowing a
second hand-authored physical schema.

### Consequences

- Advanced transformation authoring is optional; hubs without custom contracts
  retain existing output and Fabric defaults.
- A contract change requires `sync-dbt-contracts` before projection.
- Full-hub projection assembles the union of every active domain contract, while
  `project --ontology` produces a self-contained package without unrelated models.
- Runtime data/grain guarantees still require warehouse-backed tests before
  production publication; toolkit CI supplies hooks but no live credentials.
- Atomic directory replacement and verified internal SQL column lineage remain
  deferred.
- Contracted Silver interface breaks require an explicit downstream migration,
  independent of the toolkit's own release version.
