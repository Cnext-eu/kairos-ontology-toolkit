# DD-206: Branching and Collaboration Guide for Hub and Dataplatform Repositories

**Status:** Accepted design; implementation required
**Date:** 2026-08-27
**Affects:** hub and dataplatform `CONTRIBUTING.md` and `CICD.md` scaffolds, hub publish tracking
and release automation, dataplatform dependency pins and locks, source-binding validation, PR CI,
promotion, rollback, hotfix workflows, and related Kairos skills
**Issue:** #590
**Implementation:** `docs/design/dd-206-branching-collaboration-guide.md`

### Context

Hub and dataplatform repositories need one collaboration model that separates Git history from
runtime environments and preserves the exact code validated while it moves through DEV, UAT, and
PROD. The model must be safe for a small team without making large-team release orchestration part
of the default scaffold.

### Decision

Both repositories use protected `main` and short-lived branches. dbt targets, never branches,
select environments.

The hub repository contains authored `ontology-hub/` and compiler-owned
`ontology-hub-publish/` sibling directories. Release-relevant generated output is tracked and
reviewed in the same PR as authored changes. A release validates those existing bytes at an exact
commit; it does not generate new unreviewed bytes after tagging.

The dataplatform pins the hub package by full 40-character commit SHA and commits dependency locks.
PR CI uses a full isolated dbt build. GitHub Environments promote the exact dataplatform SHA through
DEV, UAT, and PROD and retain the initial audit history. Rollback redeploys a previous successful
SHA. A PROD-based hotfix is created from the deployed SHA, then the fix and regression test are
forward-ported through a normal PR to current `main`.

dbt's deprecated `overrides:` source mechanism is transitional, not the final boundary. The hub
ships a versioned source-binding contract; dataplatform validation requires an exact physical
binding for every used source and rejects missing, unknown, duplicate, or stale entries before
warehouse execution.

### Consequences

The default design has no environment-branch drift, promotes exact code, reviews generated output,
and fails closed on missing source bindings without requiring custom release infrastructure. Slim
CI state management, custom release ledgers, serialized candidate queues, and maintenance branches
are a short annex for very large teams only.

Both repository types receive a separate managed root `CICD.md`; `CONTRIBUTING.md` explains how to
contribute, while `CICD.md` explains validation, releases, promotion, rollback, and hotfixes. The
setup, execution, package-consumption, operations, merge, toolkit-development, and help skills must
be reviewed as specified in the companion document. Existing client repositories adopt the managed
guide with `update` or `update --upgrade`, then review repository-specific environments, workflows,
bindings, publish tracking, and protections in a dedicated migration PR. Current scaffolds do not
yet fully comply.

When Gold Power BI output is configured, the hub release also carries one verified
`powerbi-semantic-model.zip` containing the first generated `SemanticModel` and `Report` versions.
The hub release records the archive hash; dataplatform infrastructure verifies that hash and the hub
SHA, then deploys both item types after dbt succeeds in each environment. This stays a separate
deployment lane from dbt while sharing the same hub release source.
