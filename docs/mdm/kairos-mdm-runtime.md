# `kairos-mdm-runtime` Setup Guide

Status: **Repository boundary and setup guide**. This document prepares a future
implementation plan; it does not select an API framework, database, UI framework, hosting
platform or deployment technology.

## 1. Purpose

`Cnext-eu/kairos-mdm-runtime` is the private operational product that consumes reviewed,
immutable MDM profiles produced by `kairos-ontology-toolkit`. It provides reusable,
customer-neutral runtime capabilities without taking ownership of customer data,
infrastructure or governance decisions.

The repository is separate from the public Apache-2.0 toolkit from its first commit. Runtime
services and the Stewardship UI remain one versioned product and one repository initially;
per-service repositories are out of scope.

## 2. Product boundaries

| Concern | Owner |
|---|---|
| MDM vocabulary, policy validation and `mdm-profile` projection | `kairos-ontology-toolkit` |
| Design-time MDM authoring module | `kairos-ontology-navigator` |
| Runtime APIs, services, migrations and Stewardship UI | `kairos-mdm-runtime` |
| Live database, infrastructure, bindings, secrets and deployment | Customer dataplatform |
| Steward assignments and business-governance decisions | Data-governance organization |

### Runtime repository responsibilities

- Versioned domain API and event contracts.
- Identity resolution, mastering and survivorship.
- Reference-data authoring, mapping, approval and release.
- Governance cases, workflow, maker/checker and operational audit.
- One normalization implementation used by runtime and batch integrations.
- Baseline operational schema, forward migrations and supported extension points.
- Default Stewardship UI and supported UI extension points.
- Profile loading, digest pinning and runtime/profile compatibility checks.
- Deployable artifacts, migration bundles and conformance test fixtures.

### Explicit non-responsibilities

- Authoring ontology or `*-mdm-ext.ttl` policy.
- Mutating generated MDM profiles.
- Owning customer records, audit history, infrastructure or credentials.
- Customer-specific source connectors or analytical models.
- Direct UI access to the operational database.

## 3. Initial repository structure

```text
kairos-mdm-runtime/
|-- services/             # API, identity, mastering, reference and workflow
|-- normalization/        # shared identifier-normalization implementation
|-- apps/
|   `-- stewardship/      # operational data-steward web application
|-- database/
|   `-- migrations/      # versioned baseline operational schema
|-- deploy/               # supported deployment modules and packaging
|-- contracts/            # MDM-profile reader, API/events and compatibility rules
|-- tests/                # unit, integration, migration and conformance suites
|-- docs/                 # runtime architecture, operations and support policy
`-- .github/workflows/    # CI, security checks and release workflows
```

This is a responsibility map, not a prescribed workspace or framework layout. The future
implementation plan may refine it after technology choices are approved.

## 4. Contract with the ontology toolkit

The runtime consumes released
`output/mdm/{domain}-mdm-profile.json` artifacts; it never imports toolkit source.

The contract must provide:

1. Profile schema and schema-version compatibility rules.
2. A pinned `content_digest` for every deployed profile.
3. Ontology, profile and runtime version provenance on decisions and events.
4. Fail-closed behavior for unsupported profile schema versions or invalid digests.
5. Shared conformance examples for normalization and profile interpretation.
6. Evidence-pack output that can propose, but never directly apply, a design-time policy
   change.

The customer dataplatform pins compatible ontology-hub and runtime releases and promotes them
through reviewed deployment workflows.

## 5. Stewardship UI boundary

The Stewardship UI is an operational application shipped by this repository. It:

- calls only the versioned MDM API for search, proposals, approvals, merges, splits,
  reference-data changes and audit history;
- never reads or writes the operational database directly;
- enforces steward and approver capabilities through runtime authorization;
- consumes the private Kairos design system and shared auth/graph components through
  versioned dependencies;
- deep-links to design-time semantic definitions without becoming a policy-authoring tool;
- remains replaceable by another client that obeys the same API and authorization contract.

The MDM module in `kairos-ontology-navigator` is a different surface: it authors reviewed
design-time policy and does not operate live master data.

## 6. Repository setup gates

### Gate 1 — Repository governance

1. Create `Cnext-eu/kairos-mdm-runtime` as a private repository.
2. Protect `main`; require pull requests, review and passing CI.
3. Define code ownership for runtime, database, security and Stewardship UI areas.
4. Add contribution, security-reporting and proprietary-license notices before source code.
5. Prohibit secrets, customer data and production exports in source or fixtures.

### Gate 2 — Artifact and release model

1. Define one product version covering compatible service, UI and migration artifacts.
2. Define artifact names and registries for containers, UI bundles, migration bundles and
   deployment modules.
3. Define the supported-version and upgrade policy independently from toolkit releases.
4. Require release notes to state supported MDM-profile schema versions.
5. Make rollback and forward-only migration expectations explicit.

### Gate 3 — Contract bootstrap

1. Check in profile schemas and sanitized conformance fixtures.
2. Implement compatibility tests before business services.
3. Define digest verification and unsupported-version failure behavior.
4. Define API and event versioning rules.
5. Define the evidence-pack contract back to design time.

### Gate 4 — CI and quality

CI must eventually cover:

- service and UI formatting, linting, type checking and tests;
- API/event compatibility;
- profile and normalization conformance;
- migration upgrade, restart and drift scenarios;
- security and dependency scanning;
- artifact builds and provenance;
- architecture checks preventing UI-to-database access.

Exact tools are selected in the implementation plan.

### Gate 5 — Security and operations

Before a production slice, define:

- identity-provider integration and runtime RBAC mapping;
- secret and environment-configuration handling;
- audit, privacy, retention and access-log requirements;
- observability, backup, restore, RPO/RTO and incident ownership;
- tenancy and data-isolation model;
- vulnerability response and supported patch process.

## 7. Inputs required for the implementation plan

The future implementation plan must not begin until stakeholders decide:

1. First mastered domain and Phase 1 versus Phase 2 scope.
2. API/runtime language and framework.
3. Operational database and migration approach.
4. Stewardship UI framework and delivery model.
5. Hosting targets and portable deployment requirements.
6. Identity provider, tenancy and authorization model.
7. Initial MDM-profile schema version and compatibility window.
8. Release support, upgrade and rollback policy.
9. Required sync-back, event and warehouse publication integrations.
10. Security, privacy, audit, RPO/RTO and support ownership.

These choices belong in a dedicated implementation plan and subsequent runtime-repository
ADRs, not in the ontology toolkit's design-time implementation.
