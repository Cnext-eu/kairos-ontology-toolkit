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
   field expressions, relationships, each focused data-quality check with the dbt test it emits
   (`quality[].kind`, `columns`, and `emittedTest`; `emittedTests` lists the singular test files),
   each class-attached DD-115 data-quality rule (`data_quality[].rule_id`, `kind`, `scope`, `action`,
   `severity`, `result_model`, `result_test`, and `quarantine` when the rule quarantines rows),
   adapter selection, planned artifacts, provenance, and ordered diagnostics.
4. Show unmapped source columns or ontology properties only as review observations; neither changes
   the closed binding contract automatically.
5. Link each finding to its source location and owning design skill.
6. For a stakeholder-facing view of the same bindings — one worksheet per domain, every declared
   scalar field alongside its mapped source column and a real sample value, for one source system
   at a time — generate the Excel workbook instead of restating the same review by hand:

   ```powershell
   $env:KAIROS_SKILL_CONTEXT = "1"
   uv run kairos-ontology field-mapping-report --source-system <system> [--domain <domain>]
   ```

   Written by default to `ontology-hub-publish/reports/field-mapping-<system>.xlsx`. Object
   properties/relationships are out of scope for this report (see its own `--help`); it only covers
   `fields:`-declared scalar mappings. Do not hand-build an equivalent workbook — this command
   already exists.

Do not regenerate execution logic, infer missing bindings, or persist operational state. The
CompilePlan explanation is the authority for what will be emitted; the report is only a human view.

Scope boundary: this skill is the per-binding policy and data-quality explanation. For a hub-wide
inventory of authored inputs, current diagnostics, and the recommended next action, use
`kairos-diagnose-status` instead of duplicating that inventory here.
