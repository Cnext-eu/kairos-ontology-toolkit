# DD-104: Reference-module activation, managed imports, and portable Silver contracts

**Status:** Accepted
**Date:** 2026-07-22
**Affects:** claim projection sync, accelerator data-domain parsing, ontology validation,
projection preflight, module activation inventories, and Silver/dbt contract generation
**Implementation:** `core/reference_modules.py`, `core/claim_projection_sync.py`,
`core/validator.py`, `core/projector.py`, `core/projections/medallion_dbt_projector.py`,
`core/projections/medallion_silver_projector.py`, and dbt templates

### Context

Claim-driven import synchronization inferred ontology IRIs by trimming class URIs and
ignored imported property/relationship claims and configured accelerator modules.
`data-domains.yaml` retained only parallel URI/label lists, so it could not enforce module
versions, roots, projection selection, or accepted transitive dependencies. The canonical
loader detects unresolved declared imports, but cannot diagnose a required import edge
that was never written.

### Decision

Reference modules use typed, version-pinned profiles. A profile declares the catalog and
ontology document IRIs, term namespaces, reviewed roots, descendant policy, exclusions,
an explicit projection allow-list, default-annotation sources, accepted transitive
dependencies, and the local-extension boundary. Legacy `imports[].uri/module` entries
remain readable through a compatibility profile.

One deterministic import plan unions approved imported class, property, and relationship
claims external to the domain namespace with data-domain module activation. Catalog
resolution and the ontology's declared
`owl:Ontology` identify document IRIs; term namespaces ending in `#` are never emitted as
managed imports. Claims remain the governed materialization authority, while module
profiles may provide an explicit source-neutral default allow-list.

Module-selection evidence is collected from selected hub ontology files and Claim
Registries before recursive ontology loading. Imports discovered only inside a
loaded reference-module closure are transitive implementation facts, not authored
direct-import evidence, and never force a duplicate direct import into the hub.

Managed synchronization owns only its final generated block and preserves authored Turtle
outside it. Validation and projection preflight report the external term, owning ontology
IRI, managed source, and claim where available. Missing required imports fail semantic
operations unless degraded mode is explicitly selected.

Activation inventories serialize closure/module hashes and available, selected, excluded,
inherited, and projected term states in URI order. They contain references and provenance,
not copied ontology definitions.

Accelerator defaults define semantic contracts, not source-specific SQL. Every bound Silver
model must supply the identity inputs required by its DD-108 strategy on every source branch;
natural keys are never invented. SCD2 validity uses timestamp precision and sequences multiple
source versions into contiguous validity windows; parent FK resolution declares `current` or
`as-of` semantics, and relationship changes participate in child change detection unless
explicitly disabled.
Current joins filter the parent to its current version; as-of joins require an explicitly
mapped parent effective-time column.

Every normal final Silver row carries `_source_system`, `_source_record_key`, and
`_loaded_at`. Source-record identity uses source/table scope plus the declared Bronze primary
key; a missing source primary key is blocking and never falls back to a business or generated
Silver key.
Generated contracts expose grain, lineage, SCD, relationship, accelerator/default-package,
toolkit-version, and hub-override provenance. Fabric and Databricks may render different SQL
and physical types, but must expose the same semantic columns, keys, relationships, and
tests.

### Rationale

Typed profiles remove namespace heuristics, make activation reproducible, and keep broad
semantic imports independent from narrow physical projection. A shared plan prevents the
domain-design workflow, CLI sync, validator, and projector from implementing divergent
import rules.

### Consequences

- New profiles require an exact version pin; legacy profiles remain unpinned for backward
  compatibility.
- Ambiguous ownership, profile term drift, ontology-IRI mismatch, and version mismatch are
  blocking structured diagnostics.
- Claim synchronization and projection preflight share the same direct,
  domain-scoped evidence collector, so closure loading cannot make their import
  expectations diverge.
- Imported definitions remain in their source modules. Self-contained deployment bundles,
  if ever required, must be separate derived output.
- Activation inventory output is deterministic and omits timestamps.
- Bound models without complete natural-key mappings are rejected instead of
  producing invalid incremental rows.
- Multi-source models implement their declared SCD lifecycle and preserve source identity
  before unioning conformed rows.
- Portable identifier validation may reject previously accepted warehouse-specific schema,
  table, column, or FK names.
- As-of FK resolution is unavailable without an explicit effective-time mapping; the
  projector fails rather than silently substituting load-time semantics.
