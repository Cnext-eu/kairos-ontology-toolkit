---
name: kairos-setup-config
description: Configure the stateless v5 ontology-hub layout and authored inputs.
---

# Hub Configuration

Use `kairos-ontology init` through this skill; do not hand-create toolkit-managed files.
Set `KAIROS_SKILL_CONTEXT=1` before CLI calls.

## V5 layout

```text
model/ontologies/<domain>.ttl
model/shapes/
integration/discovery/
integration/sources/<source>/
integration/bindings/<source>-to-<domain>.binding.yaml
integration/transforms/dbt/models/
kairos.yaml
../ontology-hub-publish/
```

`integration/bindings/` contains closed EntityBinding YAML and is the sole source-to-canonical
execution authority. Complex joins, windows, aggregations, JSON expansion, fallback logic, or grain
changes belong in ordinary contracted dbt SQL and properties YAML, then are referenced by
`source.dbtModel`. `../ontology-hub-publish/` (a sibling of the hub) is derived and safe to regenerate.

Configure namespace, catalog, adapters, and selected roots in `kairos.yaml`. Keep each domain in an
OWL ontology with labels/comments and explicit imports. Add optional SHACL in `model/shapes/`.
Validate ontology inputs, then run `compile --check` before emission.
