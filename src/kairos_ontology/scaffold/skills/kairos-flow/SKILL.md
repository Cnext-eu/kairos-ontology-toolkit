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

The deterministic next-action authority is the toolkit, not this skill. Recompute
the advisory proposal instead of inventorying or ordering inputs yourself
(DD-137):

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology next --format json
```

`next` reports authored inputs as present, missing, or unreadable, derives domains
from ontology filenames and binding `metadata.domain`, runs the canonical compile
check per bound domain, and returns ordered advisory actions. It is recomputed
every run and never stored. For a fuller read-only narration, invoke
**kairos-diagnose-status**. Never treat file presence as completeness; stages the
proposal marks `human_decision_required` need a human decision.

Reference-model freshness is separate; the only freshness authority for the
installed/current local reference-model version is:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology check-inventory --domains <active-domain> --explain-scope
```

Missing optional modules outside the selected scope are non-blocking. Never update
reference models silently; route explicit changes to **kairos-toolkit-ops**.

## Route

Do not re-derive the order. Take the proposal's actions in the order returned and
map each action `kind` (and its `skill` field) to the owning skill:

- **Design:** `design-discovery` → **kairos-design-discovery**; `design-source` →
  **kairos-design-source**; `design-domain` → **kairos-design-domain**;
  `develop-dbt` → **kairos-develop-dbt-transformation**.
- **Bind:** `author-binding` → create or revise a closed `EntityBinding` with
  **kairos-design-mapping**.
- **Validate:** `run-check`, `fix-diagnostic`, or `validate` →
  **kairos-execute-validate**.
- **Compile:** `compile-emit` → check, explain, or emit with
  **kairos-execute-project**.

Optional `review-gold`/`review-mdm` actions are non-recommended capabilities; act
on them only when a Gold or MDM product is explicitly requested.

When bindings exist, the compiler result inside the proposal is the only build
signal. A returned `compile-emit` action means only that the current authored
inputs compile — not a runtime or release guarantee. Report ordered diagnostics
without storing them.

Design handoffs are interactive by default. A fleet override belongs only to the
active design skill invocation and never transfers through this router.
