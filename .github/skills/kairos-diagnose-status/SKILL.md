---
name: kairos-diagnose-status
description: >
  Read-only v5 report of authored hub inputs and current compile diagnostics.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# Diagnose Hub Inputs

Produce a stateless report from the hub as it exists now. Do not write or repair
files during diagnosis. The deterministic observations and the recommended next
action come from the toolkit; this skill narrates them, it does not re-derive
them (DD-137):

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology next --format json
```

## Authored input inventory

Render the proposal's input observations only:

1. the resolved hub root;
2. confirmed discovery context under `businessdiscovery/`;
3. source vocabularies and redacted sample availability under
   `integration/sources/`;
4. ordinary dbt SQL/properties YAML under `integration/transforms/dbt/`;
5. canonical ontologies and optional SHACL under `model/`;
6. `integration/bindings/*.binding.yaml`, grouped by `metadata.domain`.

Report each input as present, missing, or unreadable exactly as returned. Never
treat file presence as completeness, or output files as proof about authored
inputs.

## Current compiler diagnostics

The proposal already runs the canonical check per bound domain. Report its ordered
diagnostics exactly, including code, message, source location, and affected
entity. If no binding selects a domain, report that fact without inventing a
compiler result. To re-run a single domain directly:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology compile <domain> --check --format json
```

End with the proposal's recommended next action verbatim; do not compute your own.
A clean report means only that current authored inputs pass the compiler check.
