# Toolkit Fix: Booking Projection Scope Defects

## Context

Kairos Toolkit `v4.7.0rc8` blocks a Booking-scoped Fabric dbt projection even
though the hub's Booking claims, managed projection surfaces, source identities,
and mappings are current.

The CLdN hub reproduces two independent toolkit defects:

1. strict readiness reports BSP Documents and BSP Party as missing direct imports;
2. degraded readiness classifies unselected Booking object properties as
   materialized Silver foreign keys.

These are toolkit defects. The hub must not add transitive imports or invent
foreign-key policies merely to satisfy the current evaluator.

## Defect 1: transitive imports become direct scope evidence

### Symptom

Booking-scoped readiness fails with:

```text
Claim/projection drift for domain 'booking':
missing owl:imports https://www.kairosflow.ai/ont/bsp/documents
missing owl:imports https://www.kairosflow.ai/ont/bsp/party
```

The Claim Registry sync evaluator reports the same Booking surfaces as in sync.

### Root cause

`src/kairos_ontology/core/projector.py` builds the reference-module context from
`ontology_graphs[*]["graph"]`. Those graphs contain the recursively loaded
ontology closure. Consequently, `imported_ontology_iris` contains both authored
direct imports and imports declared by transitive reference modules.

The projection authority gate then treats those transitive imports as direct
module-selection evidence and requires the hub domain ontology to import them
itself.

`claim_projection_sync._module_scope_evidence()` does not have this problem: it
parses the scoped hub ontology files directly and therefore sees only authored
direct imports. This difference explains why `check-claims` reports in-sync while
`check-projection` reports drift.

### Proposed fix

Make projector reference-module context construction use the same direct,
domain-scoped evidence collector as Claim Registry synchronization:

- collect requested domain names from the selected ontology files;
- collect approved imported claim terms from their registries;
- collect imports by parsing the selected hub ontology files directly;
- never derive direct module activation from recursively merged closure graphs.

Prefer exposing a public equivalent of `_module_scope_evidence()` rather than
maintaining another projector-specific implementation.

### Regression test

Add an end-to-end projector test with:

- a hub domain that directly imports reference module A;
- module A that transitively imports module B;
- both modules represented by accelerator profiles;
- synchronized managed surfaces containing only direct import A.

Assert that a domain-scoped strict projection:

- does not require direct import B;
- agrees with `evaluate_projection_sync`;
- still blocks when direct import A is genuinely absent.

## Defect 2: every complete object property becomes a Silver FK

### Symptom

After using explicit degraded mode to pass the import-scope defect, readiness
fails with `temporal-fk.policy-missing` for 12 Booking relationships that were
not selected for Silver materialization.

Examples include:

```text
booking:hasCustomsPreNotificationLocation
booking:hasTransportOrderAssociation
dcsa:hasBookingParty
dcsa:hasCargoItem
dcsa:hasLocation
dcsa:hasPlaceOfDelivery
dcsa:hasPlaceOfReceipt
dcsa:hasPortOfDischarge
dcsa:hasPortOfLoading
dcsa:hasRequestedEquipment
dcsa:hasShippingInstruction
dcsa:hasTransshipmentPort
```

### Root cause

`normalize_foreign_key_facts()` intentionally preserves a descriptor for every
complete `owl:ObjectProperty`, including unqualified relationships. This is
useful for graph-free Gold analysis.

`policy_normalize._silver_authorities()` then groups all descriptors by source
class and requires a DD-109 temporal policy for every descriptor. It does not
first apply the descriptor's canonical Silver qualification rules.

The canonical rules already exist on
`core.projections.shared.ForeignKeyDescriptor.qualifies_silver()`:

- `silverForeignKeyOn`;
- `silverForeignKey`;
- `silverColumnName`;
- `owl:FunctionalProperty`;
- a max-cardinality-one restriction that applies to the source class.

Plain object properties with only domain and range do not qualify.

### Proposed fix

Preserve the complete descriptor set for Gold, but derive an effective Silver FK
policy before Silver normalization:

1. add the canonical `qualifies_silver(class_uri)` behavior to
   `ForeignKeyDescriptorSpec`, or carry the normalized qualification result into
   the graph-free spec;
2. retain only descriptors whose source class is a materialized Silver candidate
   and whose Silver qualification is true;
3. use this filtered policy for:
   - temporal-policy completeness;
   - Silver FK capability requirements;
   - Silver DQ property-scope resolution;
   - Silver authority generation;
4. keep the unfiltered policy available to Gold relationship shaping.

Do not change `normalize_foreign_key_facts()` to discard unqualified descriptors,
because existing Gold behavior and tests intentionally retain them.

### Regression tests

Add tests covering:

- a complete but unqualified object property on a materialized class does not
  require temporal FK policy;
- `silverForeignKey`, `silverForeignKeyOn`, `silverColumnName`, functional, and
  applicable cardinality-one relationships still require complete policy;
- a cardinality restriction on another class does not qualify the relationship
  for the current class;
- unqualified descriptors remain available to Gold normalization;
- the CLdN Booking fixture reaches the next readiness stage without invented FK
  policies.

## Acceptance criteria

Using the patched toolkit against the CLdN hub:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
kairos-ontology check-claims --domains booking --require-mapping --accelerator logistics
kairos-ontology check-projection `
  --ontology model\ontologies\booking.ttl `
  --target dbt `
  --platform fabric `
  --accelerator logistics `
  --catalog catalog-v001.xml
```

must produce consistent claim/sync results and must not report temporal-policy
findings for unselected object properties.

If readiness becomes green, the same scoped options may be used for projection.
The generated package must then pass Booking parity and skill-managed offline dbt
validation without adding direct transitive imports or fake Silver FK annotations
to the hub.

