# Consuming CompilePlan Artifacts

`CompilePlan` is the single immutable planning seam for v5 Silver/dbt output and optional
Gold/MDM consumers. Consumers receive plan views or emitted artifacts; they do not
re-resolve TTL, source vocabularies, bindings, or policies.

## Dataplatform

1. Compile each domain and publish emitted artifacts at an immutable Git revision or
   versioned artifact location.
2. Pin that immutable revision in `packages.yml`.
3. Run `dbt deps`, `dbt parse`, `dbt build`, and `dbt test` with the matching adapter.
4. Reference generated models with package-qualified `ref()`.
5. Put downstream-only logic in ordinary dbt models and never edit compiler-owned output.

Compiler adapters are `fabric` and `databricks`. Dataplatform scaffolding exposes
`fabric-lakehouse`, `fabric-warehouse`, and `databricks` deployment profiles, both Fabric
profiles consuming Fabric compiler SQL.

## Gold and MDM

Gold semantic-model and MDM profile generation consume the same plan as Silver/dbt. Their
toolchains validate TMDL/DAX, relationships, security, physical deployment, and runtime MDM
integration separately. Consumer configuration cannot alter canonical binding semantics.

## Ownership

- Ontology, source, binding, and compile diagnostics: hub owner.
- Connections, deployments, adapter runtime, and data-test failures: dataplatform owner.
- Missing semantics: submit a focused ontology/binding change with a synthetic regression
  test, then regenerate.

Compile success is not proof that a release was published or a deployment completed.
