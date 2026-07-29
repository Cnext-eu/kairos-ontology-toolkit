# Historical: synchronized dbt contract identity

> **V4 historical record.** Contract-identity evidence, virtual-source synchronization,
> readiness checks, and their commands were retired by DD-133/DD-135/DD-136. This document
> is not active v5 guidance.

V4 materialized a separate contract-identity resource and persisted dbt run evidence. That
authority was removed because it duplicated planning and could drift from emitted artifacts.

In v5, an ordinary dbt SQL model and its authoritative model-contract YAML are referenced
directly by `EntityBinding.source.dbtModel`. The compiler validates the source contract and
incorporates it into one immutable `CompilePlan`. Runtime dbt results remain ordinary
dataplatform tests; Kairos does not persist a release/readiness evidence registry.
