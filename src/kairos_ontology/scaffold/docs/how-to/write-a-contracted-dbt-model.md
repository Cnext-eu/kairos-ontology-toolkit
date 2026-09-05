# Write a contracted dbt model

**Skill:** `kairos-develop-dbt-transformation`

A binding maps one relation to one entity. When the input needs a join, a deduplication or
a change of grain, author ordinary dbt SQL in the hub and bind to *that* instead.

## 1. Write the model

Put the SQL and its properties YAML under `integration/transforms/dbt/models/`. It is
ordinary dbt; nothing about the SQL is Kairos-specific. Give it an explicit contract in
the properties YAML — the compiler treats a contracted model as a verified source
identity, which is what lets a binding reference it safely.

## 2. Point a binding at it

Use `source.dbtModel` in the binding instead of a source relation. Everything else about
the binding is unchanged.

## 3. Validate

```bash
kairos-ontology validate-dbt-contracts
kairos-ontology compile billing --check
```

`validate-dbt-contracts` checks the declared contract against the model; `compile --check`
then resolves the binding against it. They answer different questions — see
[CLI behaviour notes](https://github.com/Cnext-eu/kairos-ontology-toolkit/blob/main/docs/design/cli-behaviour-notes.md) for why both exist.

## Promoting an existing model

If the SQL already lives in the dataplatform repo and belongs in the hub:

```bash
kairos-ontology promote-transform path/to/model.sql --domain billing --dry-run
```

Drop `--dry-run` to write. `--properties` points at the accompanying YAML.

## Boundary

Downstream-only logic stays in the dataplatform repo. Move it into the hub only when a
binding needs it. Compiler-owned output is never edited by hand — change the input and
regenerate.
