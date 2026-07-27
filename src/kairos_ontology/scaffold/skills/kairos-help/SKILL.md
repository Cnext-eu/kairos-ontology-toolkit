---
name: kairos-help
description: Orientation to the Kairos Ontology Toolkit, its v5 lifecycle, commands, and skills.
---

# Kairos Help

Kairos shifts data-product design left: source evidence and OWL domain meaning are bound through
explicit v5 entity-binding YAML, compiled into an immutable typed CompilePlan, and rendered into
downstream artifacts.

## Stateless lifecycle

`discovery → source → domain → mapping/binding → silver/gold design → validate → compile → consume`

- Start/resume: `kairos-flow` inventories the hub and routes the next skill without persisted state.
- Detailed review: `kairos-diagnose-status` combines source/ontology/reference inventories,
  update/version facts, and CompilePlan diagnostics.
- Silver/dbt generation: `kairos-execute-project` runs `compile --check|--explain|--emit`.
- Validation: `kairos-execute-validate` covers syntax, SHACL, and compile diagnostics.

## Canonical compiler commands

```powershell
kairos-ontology compile <domain> --check --format json
kairos-ontology compile <domain> --explain --format json
kairos-ontology compile <domain> --emit <directory>
```

A CompilePlan contains resolved bindings, normalized contracts, shaped project, Silver registry,
materialization plan, planned artifacts, provenance, and ordered diagnostics. Passing compilation
does not certify runtime behavior or release eligibility.

Use `kairos-design-source`, `kairos-design-domain`, `kairos-design-mapping`,
`kairos-design-silver`, `kairos-design-gold`, and `kairos-design-mdm` for authored design changes.
Use `kairos-toolkit-ops` for update/version/reference-model operations. Never bypass skill-owned
preflight and stakeholder gates.
