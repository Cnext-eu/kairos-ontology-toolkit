---
name: kairos-package-dataplatform
description: Consume deterministic v5 compiler artifacts in a downstream dataplatform.
---

# Dataplatform Consumption

Treat the ontology hub as the producer and the dataplatform as the runtime consumer.

## dbt

1. Compile each selected domain and publish the emitted dbt project at an immutable Git revision or
   versioned artifact location.
2. Pin that revision in downstream `packages.yml` as a full 40-character commit SHA — run
   `kairos-ontology bump-hub <ref>` from the dataplatform root to resolve a hub branch, tag, or SHA
   to that pin and rewrite `packages.yml` in place; never consume a moving branch in production.
3. Run `kairos-ontology validate-source-bindings` (after `dbt deps`) to fail closed on missing,
   unknown, duplicate, or stale physical source bindings before any warehouse execution — a binding
   is stale once `bump-hub` moves the pin and its `meta.kairos.verified_hub_sha` no longer matches.
   After reviewing bindings against the new commit, run `validate-source-bindings --confirm` to stamp
   them verified for that SHA. Both checks belong in the same `bump/hub-*` PR that adopts the new SHA,
   alongside `dbt parse`, `dbt compile`, and the isolated `dbt build --target ci` — see `CICD.md`.
4. Run `dbt deps`, `dbt parse`, `dbt build`, and `dbt test` with the target adapter.
   Include `dbt build --empty` on every `bump/hub-*` PR. It runs each model at `limit 0`,
   so the warehouse parses and binds the real SQL for essentially no compute — and it is
   the **only** check anywhere in the pipeline that catches SQL-dialect errors. dbt hands
   a model body to the engine verbatim, so `dbt parse` and `dbt compile` never inspect it
   and no offline gate in the hub can. A T-SQL dialect error in newly emitted SQL reaches
   production without this step (DD-215).
5. Reference emitted models with package-qualified `ref()` and keep downstream-only business logic
   in ordinary contracted dbt models.
6. Report compiler errors to the binding owner and runtime/data-test errors to the dataplatform
   owner.

## Gold and MDM

Consume optional Gold semantic-model and MDM profile artifacts from the same CompilePlan build. The
generated `deploy-powerbi-semantic-model.yml` workflow already verifies the hub release tag resolves
to the expected hub SHA and that the downloaded `powerbi-semantic-model.zip` matches its recorded
SHA-256 before extraction — never bypass or work around that verification, and never hand-edit or
regenerate its TMDL/PBIR/report JSON downstream. Validate TMDL/DAX, relationships, security, adapter
behavior, and MDM runtime integration in their own toolchains. Consumer configuration must not
change canonical EntityBinding semantics.

When a concept is missing, open a focused ontology/binding change request with domain, affected
class/property, source relation, expected semantics, and downstream test. Regenerate rather than
editing compiler-owned output.
