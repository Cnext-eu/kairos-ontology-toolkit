# DD-129: Domain-Scoped Active Source Authority for Projection Readiness

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** dbt bind/normalize/materialize phases, projection readiness, source mappings,
preparation and identity evaluation
**Implementation:** `projections/dbt/context.py::ActiveSourceScope`,
`projections/dbt/bind.py::_active_source_inputs`

### Context

The dbt bind phase loaded every source vocabulary and mapping document for every selected
ontology. Downstream preparation and mapping checks then evaluated unrelated-domain mappings.
Generated vocabularies for contracted dbt outputs could also be present on disk but absent
from the effective source set used by a later stage.

### Decision

The bind phase still loads the complete registered source vocabulary before validation, then
derives one immutable active-source scope for the selected ontology. A source table enters
that scope through a selected-domain table mapping, an active contracted virtual source, a
contract replacement input, or an identity dependency required by the selected domain.
Every inclusion carries a deterministic reason.

The scoped systems, mappings, contracts, and preparation policies are the only source
authorities passed to normalization, identity, coverage, and physical planning. Contracted
virtual sources are registered relations but do not acquire physical preparation obligations.
Final custom dbt package assembly uses the union of those active contracts and their declared
custom-model dependency closure rather than re-scanning every hub transformation as selected.

### Rationale

Scoping after source discovery preserves conflict detection and contracted-vocabulary
recognition while preventing unrelated mappings from creating false policy obligations.
Deriving the scope once avoids separate stage-specific interpretations of which source tables
are active and makes readiness diagnostics explainable.

### Consequences

- Domain-scoped readiness ignores mappings that target another ontology.
- Cross-domain sources required by an actual identity/FK dependency remain active and state
  that dependency as their reason.
- Generated contracted dbt vocabularies participate in mapping and identity validation.
- Readiness JSON includes the active source inventory by domain.
- Preparation output is domain-scoped; unrelated array-child preparation models are no longer
  emitted for another domain's projection.
- Domain-scoped dbt output excludes unreachable contracted transformations owned by another
  ontology, while full-hub output remains the union of all selected domain closures.
