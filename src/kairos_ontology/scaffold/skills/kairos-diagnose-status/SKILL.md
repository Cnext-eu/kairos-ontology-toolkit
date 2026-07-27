---
name: kairos-diagnose-status
description: >
  Read-only v5 report of authored hub inputs and current compile diagnostics.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# Diagnose Hub Inputs

Produce a stateless report from the hub as it exists now. Do not write or repair
files during diagnosis.

## Authored input inventory

Report only:

1. `kairos.yaml` and the resolved hub root;
2. confirmed discovery context under `integration/discovery/`;
3. source vocabularies and redacted sample availability under
   `integration/sources/`;
4. ordinary dbt SQL/properties YAML under `integration/transforms/dbt/`;
5. canonical ontologies and optional SHACL under `model/`;
6. `integration/bindings/*.binding.yaml`, grouped by `metadata.domain`.

Distinguish missing, unreadable, and present inputs. Do not treat output files as
proof about authored inputs.

## Current compiler diagnostics

For each discovered binding domain run:

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology compile <domain> --check --format json
```

Report the returned ordered diagnostics exactly, including code, message, source
location, and affected entity. If no binding selects a domain, report that fact
without inventing a compiler result.

End with the smallest next action: source design, canonical design, dbt contract,
EntityBinding revision, validation, or compile emission. A clean report means only
that current authored inputs pass the compiler check.
