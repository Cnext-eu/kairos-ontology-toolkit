---
name: kairos-execute-report
description: Review authored EntityBindings and canonical compiler explanations.
---

# Binding Review Report

Produce an on-demand, read-only review from authored inputs and canonical compiler output.

1. Inventory `integration/sources/`, `model/ontologies/`, and
   `integration/bindings/*.binding.yaml`.
2. For each bound domain run
   `kairos-ontology compile <domain> --explain --format json` with
   `KAIROS_SKILL_CONTEXT=1`.
3. Report source relation or contracted dbt model, target class, grain, identity, load mode,
   field expressions, relationships, adapter selection, planned artifacts, provenance, and ordered
   diagnostics.
4. Show unmapped source columns or ontology properties only as review observations; neither changes
   the closed binding contract automatically.
5. Link each finding to its source location and owning design skill.

Do not regenerate execution logic, infer missing bindings, or persist operational state. The
CompilePlan explanation is the authority for what will be emitted; the report is only a human view.
