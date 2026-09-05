# DD-097: Multi-domain dbt projection — shared-artifact reconciliation and peer-import authority (issue #220)

**Status:** Accepted
**Date:** 2026-07-21
**Affects:** `src/kairos_ontology/core/projector.py`,
`src/kairos_ontology/core/projections/medallion_dbt_projector.py`
**Implementation:** issue #220

### Context

A multi-domain hub with cross-domain FKs could not project a governed dbt package in
either supported scope:

1. **Full-hub projection** merged each domain's dbt artifacts with a blunt
   identical-bytes check (`_merge_identical_artifacts`). Several artifacts are
   package-level or shared, not domain-owned, and legitimately differ per domain:
   `dbt_project.yml`/`README.md`/`packages.yml` (per-domain fallback config),
   `models/gold/shared/dim_date.sql` and `_shared__gold_models.yml` (embedded the
   current domain's name/IRI/version), and per-source `models/silver/_{sys}__sources.yml`
   (filtered to *that* domain's mapped tables). Any second domain tripped a collision and
   no dbt artifacts were written.
2. **Domain-only projection** (`project --ontology consignment.ttl`) built the
   `hub_domain_namespaces` whitelist only from the *loaded* domains, so peer-domain
   `owl:imports` (booking/party/reference-data) were absent from the whitelist and the
   claim-authority gate reported them as `extra owl:imports` drift — even though they are
   required intra-hub imports, not claim-driven external reference models.

### Decision

- **Shared/package artifacts are orchestrator-reconciled, not collided.** A new
  `_merge_dbt_artifacts` classifier replaces the identical-bytes merge at the dbt
  per-domain merge site: package-level config is accepted last-wins (the orchestrator
  regenerates the definitive version once after the loop); per-source `_sources.yml`
  files are reconciled via a deterministic stable-sorted **union of their `tables`**
  (`_union_sources_yaml`); all other artifacts keep the strict identical-bytes check.
- **Conformed/shared gold is domain-neutral.** `dim_date.sql` and
  `_shared__gold_models.yml` render with a stable `domain_name="shared"` and a stable
  `gold_shared` schema, omitting per-domain IRI/version, so every domain emits identical
  bytes (the shared artifact is emitted once).
- **Peer-domain bases are always known to the authority gate.** `run_projections`
  collects `hub_domain_namespaces` from *every* on-disk hub domain ontology (via
  `_collect_hub_domain_bases` over the full `model/ontologies/` directory), independent
  of `--ontology` scoping, so required local peer imports are recognised as intra-hub and
  never flagged as drift.

### Rationale

Reconciling at the orchestrator (package-owning) layer preserves per-domain generation for
standalone/test callers while producing a single deterministic package. Making the
conformed dimension domain-neutral is also semantically correct — a shared dimension does
not belong to any one domain's gold schema. Sourcing the hub-domain whitelist from disk
(not from the loaded subset) mirrors the CLI sync path (`evaluate_projection_sync`), which
already scanned the full directory, closing the divergence between the two code paths.

### Consequences

- Full-hub and domain-scoped dbt projection both succeed on a multi-domain hub without
  weakening claim governance or hand-editing output.
- The conformed `dim_date` now materializes to `gold_shared` instead of the first domain's
  gold schema — a deliberate, more-correct placement for a conformed dimension.
- Regression coverage: `tests/scenarios/test_scenario_issue220.py` (full-hub no-collision,
  domain-neutral shared gold, domain-only peer-import gate) and
  `tests/test_dbt_artifact_merge.py` (merge/union helpers).
