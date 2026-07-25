---
name: kairos-design-gold
description: >
  Expert guide for designing governed Gold data-product profiles, including the
  dimensional Power BI v1 profile, measures, calendars, security, and release evidence.
---

# Kairos Gold Product Design

Gold is a consumption-oriented data-product layer. It is not universally dimensional.
Every product must name a registered profile; the only implemented profile is
`dimensional-powerbi-v1`. Unknown or missing profiles fail closed.

## Design fleet mode (DD-088)

Default is interactive design. Confirm table roles, grains, version bindings, measures,
calendar assumptions, and security with stakeholders. A fleet override
applies only to this skill invocation and is never inherited by another skill or a later resume.

In fleet mode, mark decisions as **AI-approved**, record rationale, confidence, and
evidence for every checkpoint, and stop for ambiguous measures, security policy,
PII/proprietary risk, destructive choices, or low-confidence business semantics.

Read and update `ontology-hub/.kairos-state/phases/gold/<product>.md`. Record decisions,
evidence, confidence, unresolved questions, and whether approval was user-confirmed or
AI-approved. Do not edit the lifecycle-wide `status.md`.

## Mandatory pre-flight

1. Read accepted DD-112/DD-113 and the hub's frozen policy profile.
2. Verify Silver projection and parity are green. Gold consumes the actual generated
   Silver model/column registry; it cannot invent a model or select a missing column.
3. Identify the exact Silver model name and version for every proposed Gold table.
4. Confirm the adapter: Fabric, or Databricks with approved downstream-Power-BI
   deviations for every deviated Gold capability.
5. Check the phase log for unresolved governance decisions.

## Product declaration

The ontology resource must declare:

```turtle
<https://example.com/ontology/sales>
    kairos-ext:goldSchema "gold_sales" ;
    kairos-ext:goldProductProfile "dimensional-powerbi-v1" .
```

Do not use a fallback profile. Adding a future profile requires its own accepted design
decision, registry record, typed shaper, capability contract, renderers, and tests.

## Explicit table contracts

Only resources with `goldTableType` are Gold tables. Never infer roles from FK counts,
references, classifications, or defaults.

Every table declares:

- `goldTableType`: `fact`, `dimension`, or `bridge`;
- `goldTableName`;
- exact `goldSourceModel`; and
- exact `goldSourceVersion`.

Facts additionally declare:

- `factGrain`;
- `factType`: `transaction`, `periodic-snapshot`, or `accumulating-snapshot`;
- `dimensionVersionBinding`;
- `incrementalPolicy`, whose governed runtime contract contains correction and
  late-arrival behavior.

Zero-dimension facts are valid.

Dimensions additionally declare:

- `dimensionExposure`: `current-only`, `history-only`, or `dual`; and
- explicit `dimensionVersionBinding`.

History and dual exposure require an SCD2 Silver authority. Gold must not manufacture
history columns or current-row filters.

Bridges additionally declare:

- `bridgeGrain`;
- exactly two `bridgeEndpoint` resources;
- exactly two `bridgeEndpointBinding` values using `Endpoint=emitted_column`;
- `bridgeCardinality`;
- optional `bridgeWeightColumn`; and
- explicit `bridgeAllocationSemantics`, including an approved no-allocation policy.

## First-class measures

A measure is a `kairos-ext:Measure` resource linked from the product with
`kairos-ext:measure`. A datatype property annotated with `measureExpression` is not a
measure and never removes its physical column.

Each measure has a stable ID, business definition, lifecycle, declared column/measure
dependencies, result type, format, folder, and governance metadata.

| Lifecycle | Required | Generated |
|---|---|---|
| `intent` | Stable ID + definition | Review metadata only; no DAX/TMDL measure |
| `provisional` | Expression, dependencies, type, format, folder | DAX/TMDL scaffold |
| `validated` | Provisional fields + tests + imported evidence | DAX/TMDL; no claim that projection performed data validation |
| `approved` | Validated fields + abstract owner role | Release-eligible when all other gates pass |

Missing dependencies, unavailable columns, undeclared DAX references, duplicate IDs, and
measure cycles block projection. Base Silver/Gold columns are always retained.

## Governed calendar

No date table or time intelligence is generated without a linked calendar profile.
Production time intelligence requires:

- inclusive start/end bounds;
- fiscal-year start month and week pattern;
- locale, holiday source, and IANA time zone;
- period-closure policy;
- role-playing date bindings to emitted date/timestamp columns; and
- `calendarApprovalStatus "approved"`.

A draft calendar remains reportable but produces no date table or calculation group and
blocks calendar release readiness.

## Fail-closed security

RLS/OLS output is allowed only from a complete linked `SecurityPolicy` containing:

- governed entitlement source;
- identity mapping;
- roles and filter direction;
- table/column bindings using `Table.column=Role:RLS|OLS`;
- positive and negative tests;
- imported test evidence; and
- `failClosed true`.

Bindings must resolve to emitted columns. Generated RLS starts from a deny-all scaffold;
downstream entitlement wiring and runtime enforcement remain downstream facts.
Perspectives are navigation metadata only and are never security boundaries.

## Adapter and release gates

Fabric emits DirectLake TMDL. Databricks emits downstream-Power-BI DirectQuery scaffolding
only when approved, scoped deviations authorize TMDL and security differences.

Strict Gold release consumes:

- passing Silver parity;
- exact table source/version bindings;
- approved measure lifecycle, dependencies, tests, and evidence;
- approved calendar state when present;
- complete security bindings and positive/negative test evidence when present;
- supported capabilities or approved non-expired deviations;
- matching adapter/TMDL compile evidence; and
- deterministic artifact completeness/hashes.

Projection-time syntax never proves business correctness, deployment success, data
validation, entitlement provisioning, or runtime enforcement.

## Handoff

After stakeholder review, invoke `kairos-execute-validate`, then
`kairos-execute-project` for `powerbi` (and `dbt` when dimensional models are consumed as
a dbt package). Review DDL, dbt, TMDL, DAX, ERD, product report, Silver parity, adapter
deviations, and strict-release findings together.
