# DD-108: Identity, Lineage, Multi-Source Conformance, and MDM Boundary

**Status:** Accepted
**Date:** 2026-07-25
**Affects:** Silver extensions, mappings, dbt contracts, multi-source models, lineage,
MDM boundary and reports
**Implementation:** `EntityIdentitySpec`, `LineageSpec`, and `MultiSourcePolicySpec`
are normalized fail-closed from authored policy. Silver SQL/schema authority, release
metadata, Gold inputs, optional contribution-lineage and reconciliation relations use the
same immutable specs. Integration identity is emitted only for reviewed exact equivalence;
externally mastered identifiers produce routing metadata only.

### Context

“Warehouse identity” conflated business identity, source identity, physical join keys,
and ontology IRIs. Mandatory natural keys can force false identity, while current
multi-source `UNION ALL` can collapse overlapping identifiers without governed
equivalence. Composite rows retain only driving-row lineage.

### Decision

Every materialized entity declares grain, identity strategy, key scope, and
change-detection strategy. Supported identity strategies are:

- business key;
- source-scoped immutable key;
- deterministic integration key;
- externally mastered identifier; or
- surrogate-only identity with an explicit reconciliation limitation.

Prep emits `_source_record_key` from source/table scope and declared source PK; it never
asserts business equivalence. Silver may emit a physical surrogate/integration key only
from approved exact-equivalence rules. Surrogate keys are join keys, not business
identity or an incremental prerequisite.

Ontology document/term IRIs, optional entity-instance IRIs, source-record identity, and
physical SKs are separate fields. Source identity must never silently fall back to a
business SK. `_loaded_at`, `_ingested_at`, `_source_updated_at`, and
`_source_effective_at` remain distinct timestamps.

Multi-source entities declare disjoint/overlapping branches, normalization, exact
equivalence, source precedence, conflicts, deletion, late arrival, and reconciliation.
Contracted transformations expose every contributing source-record fact; the normalized
Silver contract owns the canonical contribution-lineage relation and the generated
Silver wrapper emits it. Probabilistic/fuzzy matching, persistent enterprise IDs,
merge/split, and survivorship remain exclusively in the MDM runtime and existing
`kairos-mdm` policy.

### Rationale

Identity roles have different scopes and lifecycles. Making them explicit prevents a
union, similar display identifier, or schema-level `skos:exactMatch` from becoming
unreviewed row-level equivalence.

### Consequences

- The identity-strategy deferral in DD-034 is superseded.
- DD-018, DD-026, DD-074, DD-092, DD-093, and DD-104 are amended.
- Multi-source schema alignment is no longer described as semantic conformance by
  itself.
- Every composite transformation exposes complete contribution lineage.

### Amendment (2026-07-28): identity keys are target OUTPUT columns; compile-time resolution uses the semantic index

Two coupled compile-time defects are corrected in the v5 `EntityBinding` compiler
(`core/compiler/adapter.py`, `core/compiler/kernel.py`).

**1. Business/natural identity is decoupled from source column names.** `identity.sourceKey`
and `identity.businessKey` enumerate **source** columns, but the identity fact (`naturalKey`,
which drives generated surrogate/integration keys, business grain, identity roles, and render)
previously baked those **source** names into the identity. That only compiled when
`camel_to_snake(source_column) == camel_to_snake(target_property_local_name)` — a coincidence
of the canonical fixture. The adapter now resolves each ordered identity key component to the
**target OUTPUT column** it is mapped to (via the field whose expression is exactly that source
column) *before* constructing `EntityIdentityFact`, so downstream consumers receive coherent
output-named identity. `identity.sourceKey` is unchanged for `_source_record_key` and
conformance. Emitted silver/dbt column names are now the snake-cased target property local name
(`camel_to_snake(...)`), matching the graph projection path and the `naturalKey` normalization;
this is idempotent for already-snake property names. An identity key component that maps to no
field, to more than one target output, or only inside a multi-column expression is a specific,
actionable diagnostic (`identity.authored-key-not-supplied`,
`identity.ambiguous-key-mapping`, `identity.key-column-in-expression`) rather than a silent
source-named key. The quality-column and `identity.authored-key-not-supplied` diagnostics are
made actionable (they name the source column, the mapped target/output, or state that none
maps).

**2. Compile-time binding resolution uses the DD-103 semantic index under a non-asserted
profile.** The kernel previously loaded the ontology under the default `ASSERTED` profile and
resolved a bound class's properties with the exact-domain / exact-namespace helpers in
`ontology_ops` (`list_classes`/`list_properties`), which do not walk `rdfs:subClassOf`. A hub
subclass therefore could not bind an inherited reference property whose `rdfs:domain` is an
ancestor class in an imported namespace without redeclaring it locally. The kernel now loads
with `SemanticProfile.RDFS` (the minimal profile that populates subclass-inherited properties)
and resolves each bound class's direct **and** inherited, cross-namespace properties through the
semantic index closure (`SemanticIndex.class_properties`). Each inherited resolved property is
made applicable to the bound subclass in the resolved-symbol layer (the bound class URI is added
to its `domain_uris`); the ontology graph is never rewritten. The exact-domain/namespace
`ontology_ops` helpers remain for inventory / non-binding uses only and must not be used for
structure-aware binding resolution. Consistent with **DD-103**, imported *semantic* breadth must
not silently widen *physical* projection breadth: inherited properties are materialized **only**
when explicitly bound in an `EntityBinding` field, never auto-emitted. Binding targets remain
hub-namespace classes; imported ancestor classes are not themselves binding targets. Because
inherited cross-namespace properties can share a local name, an authored field ref that resolves
to more than one distinct property URI is a compile diagnostic (`binding.ambiguous-property`);
callers qualify the field with the owning namespace (full URI or a bound prefix) to disambiguate.
Unambiguous resolution is unchanged.
