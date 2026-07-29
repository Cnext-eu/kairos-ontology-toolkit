# OKF Decision Record worked example

The per-hub Decision Log now uses this OKF Markdown + YAML-frontmatter format. It is the
canonical format produced by `kairos-ontology decision new` under
`ontology-hub/decisions/` and linted by `kairos-ontology validate` when a bundle exists.

A real hub record for the Equipment decision would look like
`ontology-hub/decisions/HUB-DD-20260728-eqp001.md`:

````markdown
---
type: Decision Record
id: HUB-DD-20260728-eqp001
title: Equipment domain uses MMT/Equipment only (not DCSA/Equipment)
domain: equipment
status: stable
decision_state: Accepted
materiality: [intentional-standard-divergence, evidence-conflict]
confidence: High
generated: { by: kairos-ontology-toolkit/<version>, at: 2026-07-28T21:00:00Z }
sources:
  - { id: equipment-ttl, resource: ../model/ontologies/equipment.ttl }
  - { id: qargo-resources, resource: ../integration/sources/qargo/vocabulary/resources.vocabulary.ttl }
---

# Context / Finding

The logistics accelerator blueprint activates both `mmt/equipment` and `dcsa/equipment`
reference modules for the `equipment` domain. The activation-driven managed-import check
therefore expects an `owl:imports` for
`<https://www.kairosflow.ai/ont/dcsa/equipment>`, and its absence is reported as a
`missing_managed_import` diagnostic.

Source evidence contradicts a DCSA/Equipment alignment:

- **DCSA/Equipment** models ISO 6346 ocean containers only: `Container` plus dry, reefer,
  tank, flat-rack, open-top, and platform variants. It requires `containerNumber`
  cardinality 1 and includes ISO equipment code, seal number, SOLAS verified gross mass,
  and reefer temperature-setting concepts.
- **Qargo `resources`**, the source behind `equipment:Unit`, is a RoRo trailer/chassis
  fleet: `resource_type` includes `FULL_TRAILER`, `compatible_container_types` is `[]`,
  and there are no container-number, ISO-code, seal, VGM, or reefer-temperature columns.

A `FULL_TRAILER` or chassis is not an ISO ocean container.

# Decision

Keep `equipment:Unit` as a subclass of `mmt-eq:TransportEquipment` and import only
`mmt/equipment`. Do not import or subclass under `dcsa/equipment`.

Treat the resulting `missing_managed_import` as an accepted degraded warning. The clean
validation run for this hub is:

```powershell
uv run kairos-ontology validate --degraded
```

`compile --check` is unaffected because the managed-import finding is degradable, not a hard
compile error.

# Alternatives rejected

| Option | Why rejected |
|---|---|
| Subclass `Unit` under `dcsa-eq:Container` | Semantically wrong and source-infeasible: it would inherit mandatory `containerNumber` cardinality 1, which the RoRo source cannot populate. |
| Add a bare `owl:imports <dcsa/equipment>` without subclassing | Clears the check but creates a dead import and reintroduces DD-133 prefix ambiguity (`:`), requiring a compensating root `@prefix` declaration for no modeling benefit. |
| Change the accelerator blueprint | The blueprint is a managed reference-model asset; a hub-local model choice should not force a shared-asset change. Revisit only if the blueprint is corrected upstream through `kairos-toolkit-ops`. |

# Consequences

- Validation must be run with `--degraded` to pass cleanly; the non-degraded report will
  continue to list `missing_managed_import` for `dcsa/equipment`.
- The Equipment ontology remains aligned with the actual RoRo trailer/chassis source grain.
- If CLdN later handles genuine ISO ocean containers, revisit the decision with a scoped
  `Container` subclass grounded in new source evidence.

# Why future maintainers need this

Without this record, a maintainer could see the missing managed import and add DCSA/Equipment
only to silence validation. That would make the ontology appear standards-aligned while creating
an unpopulatable ISO-container model for a RoRo fleet. The decision preserves the evidence,
rejected alternatives, and accepted degraded-warning posture so future refreshes do not lose the
reasoning behind the TTL.
````
