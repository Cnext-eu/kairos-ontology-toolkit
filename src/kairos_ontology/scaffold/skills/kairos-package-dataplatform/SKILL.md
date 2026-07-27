---
name: kairos-package-dataplatform
description: Consume deterministic v5 compiler artifacts in a downstream dataplatform.
---

# Dataplatform Consumption

Treat the ontology hub as the producer and the dataplatform as the runtime consumer.

## dbt

1. Compile each selected domain and publish the emitted dbt project at an immutable Git revision or
   versioned artifact location.
2. Pin that revision in downstream `packages.yml`; never consume a moving branch in production.
3. Run `dbt deps`, `dbt parse`, `dbt build`, and `dbt test` with the target adapter.
4. Reference emitted models with package-qualified `ref()` and keep downstream-only business logic
   in ordinary contracted dbt models.
5. Report compiler errors to the binding owner and runtime/data-test errors to the dataplatform
   owner.

## Gold and MDM

Consume optional Gold semantic-model and MDM profile artifacts from the same CompilePlan build.
Validate TMDL/DAX, relationships, security, adapter behavior, and MDM runtime integration in their
own toolchains. Consumer configuration must not change canonical EntityBinding semantics.

When a concept is missing, open a focused ontology/binding change request with domain, affected
class/property, source relation, expected semantics, and downstream test. Regenerate rather than
editing compiler-owned output.
