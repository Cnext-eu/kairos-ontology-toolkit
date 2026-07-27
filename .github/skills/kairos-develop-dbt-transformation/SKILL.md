# Develop dbt Transformation

Create or update an ordinary contracted dbt model used by a v5
`source.dbtModel` binding.

## Workflow

1. Read the binding, relevant ontology/source inputs, and existing dbt SQL/YAML.
2. Confirm the output row grain and physical key columns before editing.
3. Keep executable relational logic in SQL and the physical output contract in dbt
   properties YAML.
4. Place model files below `integration/transforms/dbt/models/`; use `source()` and
   `ref()` instead of physical relation names.
5. Require `version: 2`, `config.contract.enforced: true`, output column names and
   types, and `meta.kairos` values for grain, grain key, target class, virtual source
   IRI, and supported adapters.
6. Keep `source.dbtModel.name`, `sqlPath`, and `contractPath` explicit in the entity
   binding. The binding grain and source key must exactly match the contract grain key.
7. Add focused dbt tests for transformation behavior and run the compiler tests for
   the bound model.

Do not generate RDF virtual sources or treat dbt metadata as ontology authority.

## Design fleet mode (DD-088)

Default is interactive. An explicit AI-approved fleet override must be requested.
It applies only to this skill invocation and is never inherited. Record rationale and confidence
for every AI-approved choice, and stop for ambiguity, low confidence, sensitive data, or
destructive changes.
