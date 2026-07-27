---
name: kairos-flow
description: >
  Stateless v5 router that inspects authored hub inputs and selects the next
  inspect, design, bind, validate, or compile action.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# Kairos Flow

Use this skill as the stateless entry point. Read the current hub; never create a
continuation record or infer progress from generated files.

## Inspect

1. Find the hub root from `kairos.yaml`.
2. Inventory only authored inputs relevant to the request:
   `integration/discovery/`, `integration/sources/`,
   `integration/transforms/dbt/`, `model/ontologies/`, optional `model/shapes/`,
   and `integration/bindings/*.binding.yaml`.
3. Derive domains from ontology filenames and binding `metadata.domain` values.
4. For a detailed read-only view, invoke **kairos-diagnose-status**.

Before canonical design, run:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology check-inventory --domains <active-domain> --explain-scope
```

This is the only freshness authority for the installed/current local
reference-model version. Missing optional modules outside the selected scope are
non-blocking. Never update reference models silently; route explicit changes to
**kairos-toolkit-ops**.

## Route

Choose the earliest action required by the current request:

- **Design:** business terms → **kairos-design-discovery**; source schema →
  **kairos-design-source**; canonical OWL → **kairos-design-domain**; relational
  SQL/YAML → **kairos-develop-dbt-transformation**.
- **Bind:** create or revise a closed `EntityBinding` with
  **kairos-design-mapping**.
- **Validate:** ontology/SHACL or compiler diagnostics →
  **kairos-execute-validate**.
- **Compile:** check, explain, or emit with **kairos-execute-project**.

When bindings exist, the current compiler result is the only build signal:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology compile <domain> --check --format json
```

Report ordered diagnostics without storing them. A successful check means only
that the current authored inputs compile.

Design handoffs are interactive by default. A fleet override belongs only to the
active design skill invocation and never transfers through this router.
