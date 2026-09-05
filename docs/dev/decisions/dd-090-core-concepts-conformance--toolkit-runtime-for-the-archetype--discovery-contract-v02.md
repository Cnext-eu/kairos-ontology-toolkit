# DD-090: Core Concepts Conformance — toolkit runtime for the archetype + discovery contract (v0.2)

**Status:** Accepted
**Date:** 2026-06-22
**Affects:** `src/kairos_ontology/core/archetype_loader.py`,
`src/kairos_ontology/core/archetype_topology.py`,
`src/kairos_ontology/core/conformance_artifact.py`,
`src/kairos_ontology/core/derive_claims.py`, `src/kairos_ontology/cli/main.py`
(`discovery-conformance` group and `derive-claims`), scaffold dir lists,
`kairos-design-discovery` and `kairos-design-domain` skills
**Implementation:** `kairos-ontology discovery-conformance {list-archetypes,load,validate}`
and the proposed-only conformance stream in `kairos-ontology derive-claims`

### Context

Business discovery captured *what a company does* (business model + glossary) but
never asked *which industry-standard concepts MUST exist, and does the business
conform to them?* That gap surfaced mid-modeling as ad-hoc reference-model
selection debates and undocumented deviations. Reference-models **v1.11.0** ships
the **archetype + discovery contract (v0.2)**: a machine catalog per archetype
(`blueprints/archetypes/<id>.yaml`: ref-model modules + core concepts + tiers,
JSON-Schema validated), a shared outcome enum
(`_schema/outcome-codes.yaml`), and SME interview prose
(`accelerator-packs/*/discovery/<id>.md`, paired by filename stem). The toolkit
must implement the consuming runtime.

### Decision

Implement a Python loader/topology/artifact layer plus a skill-wrapped CLI
command group, consumed by a new `kairos-design-discovery` **Phase 2.5 — Core
Concepts Conformance**:

- **Loader** resolves the refmodels root (`--refmodels-root` →
  `KAIROS_REFMODELS_ROOT` env → existing `_resolve_ref_models_dir()` fallback; no
  net-new hub-config key), normalizes repo-root vs `ontology-reference-models/`
  child, validates the archetype YAML against the **shipped JSON Schema** via
  `jsonschema`, and loads the outcome enum from `outcome-codes.yaml` (not
  hardcoded).
- **Topology** parses each `ref_model_modules[].iri` **directly via
  `CatalogResolver`** — not umbrella `owl:imports` — because the latter only
  follows direct imports and yields 0 concepts; direct parsing yields the full
  concept set + domain/range edges with declared cardinality.
- **Artifact**: a validated, hashed
  `integration/discovery/core-concepts-conformance.yaml` (carrying resolved
  `ref_model_modules`, per-concept outcomes/tiers/reasons, scorecard, and a
  `concept_set_hash` for stale-detection).
- **Dual persistence** (DD-080): machine artifact + an OKF `phases/discovery.md`
  conformance section for continuation context.
- **Mode** (DD-088): interactive by default; AI pre-fill only in design fleet mode.
- **Single archetype per session**; multi-archetype companies run a second session.
- **`kairos-design-domain` consumption remains warn-only** (missing/stale artifact
  warns, never blocks).
- A committed, valid artifact may also drive **deterministic proposed-only class
  claims** through `derive-claims`. The outcome policy is:
  `conforms` → `claim`, `conforms-with-rename` → `claim`, `partial` →
  `specialize`, `deviates` → `gap`, and `not-applicable` → no proposal. Required,
  recommended, and optional tiers are all eligible.
- Conformance remains **non-authoritative for approval**: generated claims always
  start as `status: proposed`, never materialize by themselves, and prior human
  decisions survive regeneration through `merge_preserving_decisions()`. The Claim
  Registry remains the sole approval/materialization authority (DD-094).

### Rationale

Catalog-driven conformance shifts reference-model selection rationale left into
discovery, where the business context is freshest, and records it as a machine
artifact the modeling skill can pre-seed from. Loading the outcome enum and JSON
Schema from the shipped contract keeps the toolkit in lock-step with ref-models
versions. Direct module-IRI parsing is required for correctness. Env+fallback
root resolution avoids introducing a hub-config loader that does not exist today.

### Consequences

- New runtime dependency `jsonschema>=4.0.0`; new env var `KAIROS_REFMODELS_ROOT`;
  new scaffold dir `ontology-hub/integration/discovery/`.
- Counts (concepts/modules) are read dynamically from the loaded archetype, never
  hardcoded.
- Missing conformance remains a compatible no-op for claim derivation. A present
  malformed, unknown, or contradictory artifact is an explicit validation error;
  it is never silently ignored.
- A **blocking** design-domain gate is deferred to a future DD.
- CI/tests use a bundled minimal fixture refmodels root — no live checkout needed.
