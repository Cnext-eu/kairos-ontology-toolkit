---
name: kairos-help
description: Orientation to Kairos v5 authored inputs, canonical compilation, commands, and skills.
---

# Kairos Help

Kairos v5 turns authored source schemas, OWL meaning, and closed EntityBinding YAML into one
immutable CompilePlan and deterministic downstream artifacts.

## Authoritative inputs

- `model/ontologies/<domain>.ttl`: canonical OWL meaning
- `model/shapes/`: optional SHACL
- `integration/sources/<source>/*.ttl`: physical source schema and redacted samples
- `integration/bindings/*.binding.yaml`: sole source-to-canonical execution authority
- `integration/transforms/dbt/models/`: ordinary contracted dbt SQL/YAML for complex logic
- `decisions/` (`ontology-hub/decisions/`): OKF Decision Log for durable rationale of
  material ontology choices
- `kairos.yaml`: namespace, catalog, adapters, and selected roots
- `../ontology-hub-publish/`: derived artifacts only (sibling of the hub)

## Canonical commands

```powershell
kairos-ontology compile <domain> --check --format json
kairos-ontology compile <domain> --explain --format json
kairos-ontology compile <domain> --emit <directory>
kairos-ontology decision new
kairos-ontology validate
```

Use `kairos-design-source`, `kairos-design-domain`, and `kairos-design-mapping` to author inputs;
`kairos-develop-dbt-transformation` for ordinary contracted dbt models; `kairos-design-gold` and
`kairos-design-mdm` for optional consumers; `kairos-execute-validate` for validation; and
`kairos-toolkit-ops` for managed files, versions, and reference models. Use
`kairos-ontology decision new` for material ontology-decision rationale; `validate` lints an
existing Decision Log bundle.

A successful compile means the selected inputs can produce a CompilePlan. Run downstream dbt,
adapter, deployment, and data tests separately.
