# Consume from a dataplatform

**Skills:** `kairos-setup-dataplatform` to create one, `kairos-package-dataplatform` to
consume from it

The dataplatform is a separate repository with a different owner. It holds the warehouse
connections and runs dbt; it never re-resolves ontology, bindings or policy.

## Create one

```bash
kairos-ontology init-dataplatform acme-dataplatform --platform fabric-warehouse --org acme
```

Use the same platform value the hub declares in `kairos.yaml`. **Nothing verifies that the
two agree**, and a mismatch surfaces only as an opaque SQL error on the first real run.

## Consume a release

1. Publish the hub's emitted artifacts at an immutable revision.
2. Pin that revision:

   ```bash
   kairos-ontology bump-hub <full-commit-sha>
   ```

   Pin by full commit SHA, not by tag — a tag is a label and can move.
3. Build:

   ```bash
   dbt deps && dbt parse && dbt build && dbt test
   ```
4. Reference generated models with package-qualified `ref()`.

## In pull-request CI

Add `dbt build --empty`. It runs every model at `limit 0`, so the warehouse parses and
binds the real SQL for essentially no compute. It is the **only** check that catches
SQL-dialect errors: `dbt parse` and `dbt compile` never inspect a model body, and no
offline gate in the hub can.

## Rules of the boundary

- Never edit compiler-owned output. Downstream-only logic goes in ordinary dbt models
  marked `meta.kairos.scope: downstream-only`.
- Missing semantics are a hub change: submit a focused ontology or binding change with a
  synthetic regression test, then regenerate. Do not patch the generated model.
- The hub owner owns ontology, sources, bindings and compile diagnostics. The dataplatform
  owner owns connections, deployment, adapter runtime and data-test failures.

## Know what you are running

Read `metadata/<domain>.provenance.json` in the package: toolkit version, adapter, and a
sha256 per authored input. It tells you whether a behaviour change came from the hub or
from your side without going back to the hub repository.
