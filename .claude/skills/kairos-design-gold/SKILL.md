---
name: kairos-design-gold
description: Design optional Gold products that consume the canonical v5 CompilePlan.
---

# Kairos Gold Product Design

Gold is an optional consumer of the immutable CompilePlan. It must not resolve source inputs,
rebuild Silver planning, or override EntityBinding grain, identity, load, field, or relationship
facts. The registered implemented profile is `dimensional-powerbi-v1`; unknown profiles fail.

## Design fleet mode (DD-088)

Default is interactive. A fleet override applies only to this skill invocation and is never
inherited. Record rationale, confidence, and references for every AI-approved choice. Stop for
ambiguous measures, security, PII, proprietary data, destructive choices, or low-confidence
business semantics.

## Authored Gold contract

- Declare the Gold profile and schema explicitly.
- Declare each fact, dimension, or bridge role, emitted name, source entity, and grain explicitly.
- Keep history exposure consistent with the compiled entity's load contract.
- Define measures as first-class resources with stable IDs, definitions, dependencies, result
  types, formats, and folders. Projection does not prove business correctness.
- Generate calendars only from explicit bounds, fiscal settings, locale, time zone, and role-playing
  date bindings.
- Generate RLS/OLS only from complete fail-closed security policy and emitted-column bindings.
  Runtime identity provisioning and enforcement remain downstream responsibilities.
- Keep platform-specific behavior inside supported Fabric/Databricks capability contracts.
- On `databricks` the semantic model is `directQuery`, so declare `gold.databricks_connection`
  (`server_hostname`, `http_path` per environment) in `kairos.yaml`. Projection fails closed
  without it; the emitted fabric-cicd `parameter.yml` rewrites those two values per deployment
  environment. Fabric Direct Lake needs `gold.direct_lake_connection` instead
  (`workspace_id` + `lakehouse_id` per environment); it is required, not optional.

Run `kairos-ontology compile <domain> --check --format json` before Gold generation. Gold consumes
the returned CompilePlan view through the registered projector; it never calls a legacy Silver/dbt
projection path. Review generated dbt/DDL, TMDL, DAX, relationships, and security scaffolding, then
validate them in the target toolchain.

Gold produces the first generated report and semantic-model version, packaged and checksummed as
part of the hub release. Target-workspace deployment, environment promotion, and business
acceptance of that report are downstream responsibilities — see `CICD.md`.
