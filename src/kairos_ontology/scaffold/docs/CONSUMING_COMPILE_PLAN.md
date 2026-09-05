# Consuming CompilePlan Artifacts

`CompilePlan` is the single immutable planning seam for v5 Silver/dbt output and optional
Gold/MDM consumers. Consumers receive plan views or emitted artifacts; they do not
re-resolve TTL, source vocabularies, bindings, or policies.

## Dataplatform

1. Compile each domain and publish emitted artifacts at an immutable Git revision or
   versioned artifact location.
2. Pin that immutable revision in `packages.yml`.
3. Run `dbt deps`, `dbt parse`, `dbt build`, and `dbt test` with the matching adapter.
   Add `dbt build --empty` to pull-request CI: it runs every model at `limit 0`, so the
   warehouse parses and binds the real SQL for essentially no compute. It is the only
   check that catches SQL-dialect errors — `dbt parse` and `dbt compile` never inspect a
   model body, and no offline gate in the hub can.
4. Reference generated models with package-qualified `ref()`.
5. Put downstream-only logic in ordinary dbt models and never edit compiler-owned output.

Compiler adapters are `fabric-warehouse` and `databricks`, and `init-dataplatform
--platform` now takes the same values — one vocabulary across both repositories. Use the
value the hub declares in its `kairos.yaml` unless this project deliberately writes
elsewhere; nothing verifies the two agree, and a mismatch surfaces only as an opaque SQL
error on the first real run.

## Gold and MDM

Gold semantic-model and MDM profile generation consume the same plan as Silver/dbt. Their
toolchains validate TMDL/DAX, relationships, security, physical deployment, and runtime MDM
integration separately. Consumer configuration cannot alter canonical binding semantics.

A `databricks` Gold product is emitted as a `directQuery` semantic model, so it also emits
`parameter.yml` at the root of the Gold artifact set. Keep it at the root of the directory
fabric-cicd is pointed at (`FabricWorkspace(repository_directory=...)`): its `find_replace`
entries rewrite the emitted warehouse hostname and HTTP path for the deployed
`environment`. The values come from `gold.databricks_connection` in the hub `kairos.yaml`,
and projection fails closed while that block is absent — a semantic model with an
unresolved connection is not a publishable artifact.

## Provenance

Every emit writes `metadata/<domain>.provenance.json` beside the models, and
`metadata/<domain>-gold.provenance.json` for a Gold product (DD-218). It records the
schema id `kairos.eu/compile-provenance/v1`, the domain, `apiVersion`, namespace, adapter,
toolkit version, the compile provenance hash, and one `{name, sha256}` entry for every
authored input that went into the build -- ontology closure, bindings, contracts,
templates and `kairos.yaml`.

Read it to answer "what produced these models?" without going back to the hub. Two
comparisons are worth automating on this side:

- **Same inputs, same output.** If `provenanceHash` matches the one recorded for the
  release you previously pinned, the authored inputs are identical and any behaviour
  change is yours, not the hub's.
- **Which input moved.** When the hash differs, the per-input digests say precisely which
  ontology or binding changed, which is usually faster than diffing generated SQL.

The document is deterministic and carries no timestamp or Git revision by design, so
re-emitting unchanged inputs produces byte-identical provenance. It is evidence, not a
gate: nothing in the toolkit yet compares a candidate release against its predecessor
(that is Gate B of DD-213, unbuilt).

## Ownership

- Ontology, source, binding, and compile diagnostics: hub owner.
- Connections, deployments, adapter runtime, and data-test failures: dataplatform owner.
- Missing semantics: submit a focused ontology/binding change with a synthetic regression
  test, then regenerate.

Compile success is not proof that a release was published or a deployment completed.
