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

- The hub owns the semantic model; the BI engineer owns the report. Build a real report as a
  separate Fabric item with its own name, bound to the deployed model — never by editing the
  generated `<Product>.Report`, which every hub release republishes. Model edits made in
  Desktop or Fabric return to the hub through `kairos-ontology harvest-gold`, never into this
  repository.
- Authored reports live in `powerbi/reports/<Product>.<Report>.Report/`, each listed in
  `powerbi/reports/reports.yml` with the display name of the model it reads (DD-253; the
  folder's `README.md` has the steps). The deploy binds each one to that model's ID in the
  target workspace and publishes it in a second pass after framing. Never commit a per-environment
  model ID, and never name a report after a model. Run `kairos-ontology check-authored-reports`
  before a PR, and `apply-report-theme` after changing the shared theme.
- **Promotion is `promote.yml`, not a hand-dispatched deploy (DD-256).** Merging to `main`
  builds and deploys `dev`; approving the `uat` and then `prod` GitHub Environments promotes
  the same commit, each in one job that runs `dbt build --target <env>` and then the Power BI
  deploy. Walk the user through approving, not through dispatching the deploy workflow:
  dispatch is break-glass, one environment at a time. To roll back, run `promote.yml` with
  `ref` set to the last known-good commit; its `packages.yml` and `hub-release.lock` travel
  with it. The CICD.md "Promotion" and "Rollback and PROD hotfix" sections have the steps.
- **A hub release reaches the platform through `bump-hub <tag>`**, which pins `packages.yml`
  and writes `hub-release.lock` in one reviewed PR. Never type a hub SHA or archive checksum
  into a workflow input when the lock can carry it; `pr-validate` fails when the two disagree.
- **Environments are the dbt targets in the committed `profiles.yml` (DD-255).** Before a
  first promotion, or after adding an environment, run
  `kairos-ontology check-environments --github-repo <org>/<repo>` (add `--online` to resolve
  the Fabric IDs) and fix what it names. Follow CICD.md "Add an environment"; never add the
  environment to the hub.
- The deploy job runs in the GitHub Environment named by `target_environment` and refreshes
  (frames) every Direct Lake model after publishing; a model that cannot read its tables
  fails the deploy (DD-239). Run `kairos-ontology resolve-environment --target <env>` to see
  which Warehouse and workspaces it uses, and where each came from, before suspecting the hub.
- After publishing, the deploy workflow runs the advisory Best Practice Analyzer notebook
  (`fabric/KairosModelBpa.Notebook`, DD-238). It is read-only over the model and never blocks
  a deploy. On Fabric (Direct Lake) it also checks guardrails and fallback to DirectQuery. On a
  Databricks (DirectQuery) model it needs Premium, PPU or Fabric capacity for XMLA read access;
  in a Pro workspace it skips, and the check is the manual one in `CICD.md`. It classifies each
  finding against the Kairos profile. Anything left to review goes back to the hub as
  authoring (a measure, a `goldHideColumn`, a `bpaIgnoreRule` with its reason), never into the
  deployed model.
- The dataplatform-side TMDL sanitizer is gone. The hub emits `///` doc comments deliberately:
  they carry the ontology's descriptions into Desktop's field list. Do not reintroduce a
  script that strips them.

Consume optional Gold semantic-model and MDM profile artifacts from the same CompilePlan build. The
generated `deploy-powerbi-semantic-model.yml` workflow already verifies the hub release tag in
`hub-release.lock` resolves to the expected hub SHA and that the downloaded `powerbi-semantic-model.zip` matches its recorded
SHA-256 before extraction — never bypass or work around that verification, and never hand-edit or
regenerate the archive's TMDL/PBIR/report JSON downstream. Validate TMDL/DAX, relationships,
security, adapter behavior, and MDM runtime integration in their own toolchains. Consumer
configuration must not change canonical EntityBinding semantics.

When a concept is missing, open a focused ontology/binding change request with domain, affected
class/property, source relation, expected semantics, and downstream test. Regenerate rather than
editing compiler-owned output.
