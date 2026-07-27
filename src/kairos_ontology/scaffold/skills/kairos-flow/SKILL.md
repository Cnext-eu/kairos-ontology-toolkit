---
name: kairos-flow
description: >
  Stateless entry point for inspecting an ontology hub and routing the next design,
  binding, validation, or compile action. Uses source inventory and CompilePlan
  diagnostics; it does not persist lifecycle state.
---

# Kairos Flow

Inspect the hub without creating lifecycle state or inferring a release verdict.

1. Inventory `integration/sources/`, `model/ontologies/`, reference models,
   `model/bindings/`, and generated output. Do not remove or replace source analysis,
   ontology/reference inventory, update/version diagnostics, or compile diagnostics.
2. Discover domains from `model/bindings/*.yaml`. Before design, run
   `kairos-ontology check-inventory --domains <domains> --explain-scope`. This is the
   only freshness authority for the installed/current local reference-model version. Missing
   optional modules are non-blocking, but never silently update them; hand explicit updates to
   `kairos-toolkit-ops`.
3. For every bound domain run:

   ```powershell
   $env:KAIROS_SKILL_CONTEXT=1
   kairos-ontology compile <domain> --check --format json
   ```

4. Report CompilePlan diagnostics exactly, grouped by domain. A successful check means
   the current binding can compile; it is not a persisted lifecycle or release state.
5. Route to the earliest applicable skill: source evidence → `kairos-design-source`,
   ontology → `kairos-design-domain`, bindings → `kairos-design-mapping`, validation →
   `kairos-execute-validate`, compile/emit → `kairos-execute-project`.

Do not create `.kairos-state`, phase logs, readiness reports, or release baselines.
Design handoffs remain interactive unless the active design skill explicitly enables fleet mode.
