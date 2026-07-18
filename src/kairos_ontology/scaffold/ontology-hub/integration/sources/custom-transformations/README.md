# Managed Custom-Transformation Vocabularies

This directory contains virtual-source Turtle vocabularies generated from contracted dbt
models.

Do not edit these files by hand. The dbt model contract under
`integration/transforms/dbt/models/` is authoritative. Regenerate with:

```text
kairos-ontology sync-dbt-contracts
```

Projection checks semantic freshness and fails when a required vocabulary is missing or
stale. Provenance timestamp or toolkit-version changes alone do not count as semantic
drift.
