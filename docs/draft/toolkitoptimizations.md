# Toolkit Optimizations

## Ontology-hub findings

### Cross-target Silver/dbt naming parity

- **Observed:** Silver honors `kairos-ext:silverSchema` and reference-data naming,
  while dbt hardcodes a derived schema and different table/key names.
- **Impact:** The same ontology produces incompatible physical contracts across targets.
- **Tracking:** [#219](https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/219).

### Preserve distinct source-table entity candidates during alignment

- **Observed:** Booking draft evidence correctly distinguished `qargo.bookings` as
  `Booking` and `qargo.orders` as `TransportOrder`, but `propose-alignment` merged both
  into one `Booking` class claim because both affinity rows resolved to that anchor.
- **Impact:** Distinct business grains can be conflated before the designer reaches the
  class-boundary checkpoint.
- **Improvement:** Preserve per-table candidate entities and emit an explicit
  multi-grain conflict when several tables with different draft/affinity entities would
  be collapsed into one class claim.

### Do not treat scalar location clusters as resolved object-property mappings

- **Observed:** Dozens of scalar address/location columns were directly attached as
  evidence for DCSA object properties such as `hasPlaceOfReceipt`, `hasPlaceOfDelivery`,
  and `hasLocation`. Because they were considered mapped, no
  `relationship_candidates` were emitted.
- **Impact:** The registry appears semantically covered without defining a target node,
  target class URI, relationship cardinality, or conformance to the hub's governed
  Location class.
- **Improvement:** Object-property alignment should require a resolvable target entity.
  Otherwise emit a relationship candidate and retain scalar columns as passthrough
  evidence.

### Resolve reference URIs in newly proposed claims

- **Observed:** `propose-alignment` generated imported Booking class/property claims
  without `class_uri`/`property_uri`, despite current materialized inventories and
  unambiguous DCSA names.
- **Impact:** `check-claims --strict` cannot approve anchored claims without a manual
  URI repair, even though URI backfilling is a documented Claim Registry requirement.
- **Improvement:** Apply the same deterministic inventory-based URI resolver used by
  `migrate-claims` when writing new registries.

### Support domain-scoped inventory readiness reporting

- **Observed:** Booking's reference inventory was current, but `check-inventory`
  blocked Booking because an unrelated hub-local Reference Data inventory was missing.
- **Impact:** Correct repository-wide integrity enforcement obscures which failure is
  relevant to the active domain and forces unrelated refresh work.
- **Improvement:** Keep repository-wide checking as the default, but add
  `--domains`/`--explain-scope` so skill workflows can report active-domain readiness
  separately while still showing the global failure.

### Never report complete claims after source-column truncation

- **Observed:** Consignment bronze vocabularies contain 88 Shipment, 109 Consignment,
  and 116 Stop columns. Affinity/alignment capped each at 80, omitted 73 columns from
  the Claim Registry, yet `check-claims` reported the registry complete and fresh.
- **Impact:** Source-evidenced identifiers, references, lifecycle fields, locations,
  goods measures, and resource fields can bypass mandatory custom-column triage while
  the hard governance gate is green.
- **Improvement:** Persist source vocabulary column counts/hashes independently of
  prompt truncation. `check-claims` must compare registry evidence against every bronze
  column and fail on omissions. If prompt limits require sampling, create deterministic
  passthrough candidates for unanalysed columns and mark the registry incomplete.

### Preserve distinct Consignment source grains

- **Observed:** `propose-alignment` merged Qargo `shipments` and `consignments` into
  MMT `Consignment`, despite the draft evidence and CLdN glossary defining Shipment/
  Trip as `mmt:TransportMovement`. It also collapsed `stops` and
  `resource_allocations` into generic `TransportServiceExecution`.
- **Impact:** Four distinct grains become two broad class claims, hiding the
  movement-vs-goods distinction and true local gaps for stop/allocation associations.
- **Improvement:** Treat affinity `likely_entity`, glossary matches, stable source IDs,
  and table-to-table cardinality as conflict evidence. Emit separate class candidates
  or a blocking grain-conflict checkpoint instead of merging by nearest anchor.
