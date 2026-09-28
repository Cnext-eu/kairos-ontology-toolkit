# DD-253: Authored reports live in the dataplatform and bind to their model by name at deploy time

**Status:** Accepted
**Date:** 2026-09-28
**Affects:** `core/authored_reports.py`, `cli/authored_reports.py`
(`check-authored-reports`, `stage-authored-reports`, `apply-report-theme`), the dataplatform
scaffold (`powerbi/reports/`, `CICD.md`, `deploy-powerbi-semantic-model.yml`,
`pr-validate.yml`), the `kairos-package-dataplatform` skill
**Issue:** #1102 (follows DD-236 and DD-239; settles the theme DD-223 and DD-236 left open)

### Context

DD-236 settles who owns a report. The hub emits a blank `<Product>.Report` stub, and the report
anyone reads is a separate, named Fabric item the BI side builds against the deployed model. It
does not say where that report's source lives or how it deploys. The first client to build one
had to work out four things.

- **Where the source lives.** The scaffold had no folder for it. `CICD.md` said "never
  regenerate or hand-edit … PBIR, or report JSON in the dataplatform", a rule about the hub
  archive that reads as if authored reports do not belong there at all.
- **How it deploys.** The deploy workflow publishes the hub archive and nothing else.
- **How it binds per environment.** A report binds to its model by ID (`definition.pbir` →
  `byConnection.pbiModelDatabaseName`), and every workspace's copy of the model has its own ID.
  The client kept a `parameter.yml` with one `find_replace` per environment, holding IDs copied
  by hand. Fabric's REST import also rejects the short `byConnection.connectionString` form
  ("Required properties are missing: pbiServiceModelId, pbiModelVirtualServerName,
  pbiModelDatabaseName, name, connectionType"), so the long form is required.
- **How it looks.** DD-223 left the theme open, and the client copied a theme into each report
  by hand.

### Decision

**Authored reports live in the dataplatform under `powerbi/reports/`, one
`<Product>.<Report>.Report/` PBIR folder each, listed in `powerbi/reports/reports.yml`.**

```yaml
theme: theme/brand.json          # optional, relative to powerbi/reports/
reports:
  - folder: Finance.JobProfitability.Report
    model: Finance               # the semantic model's display name
    product: finance             # optional
    insights: [ins-001]          # optional; the confirmed insights it answers
    theme: false                 # optional opt-out of the shared theme
```

1. **The manifest names the model by display name, never by ID.** The display name is the same
   in every workspace; the ID is not. `check-authored-reports` (run by `pr-validate`) fails when
   any of these holds:
   - a report folder has no entry, or an entry has no folder;
   - a report has no `definition.pbir` or no binding;
   - a report is named after a semantic model, which the hub's stub would overwrite on the next
     release;
   - a report carries no copy, or an older one, of the shared theme.
2. **The model is bound at deploy time, in a staged copy.** After the archive's models are
   published and framed:
   - the workflow lists the workspace's semantic models (display name → ID);
   - `stage-authored-reports` copies `powerbi/reports/` and rewrites each staged
     `definition.pbir` to the long `byConnection` form, with `pbiModelDatabaseName` set to the
     model's ID;
   - a second fabric-cicd pass with `item_type_in_scope=["Report"]` publishes the staged copy.

   The committed reports are never rewritten, the pass never reads the hub archive, and a
   model the workspace lacks fails the deploy. A `parameter.yml` in `powerbi/reports/` is still
   applied, for anything else that varies per environment.
   `FABRIC_REPORTS_WORKSPACE_ID` publishes the reports to their own workspace. No orphan
   cleanup runs (DD-239).
3. **One theme per dataplatform, applied by a command and checked in CI.** `theme:` names a
   theme file. `apply-report-theme` copies it into each report's
   `StaticResources/RegisteredResources/` and makes it the report's `customTheme`, as importing
   it in Desktop does, and the result is committed. Theming is a content change, so the deploy
   never makes it: the only thing the deploy rewrites is the binding. The hub's stub stays blank
   (DD-236).
4. **`insights:` is recorded but not yet checked against the hub.** The manifest lives in the
   dataplatform, while `insights.yaml` and `emit-gold` live in the hub. Reporting the confirmed
   insights that no report answers needs the manifest to reach the hub, and is a follow-up.

### Consequences

- Nothing per-environment is committed, so promoting a report to UAT or PROD needs no edit. The
  client's hand-kept `parameter.yml` of model IDs becomes a harmless no-op and can be deleted:
  its `find_value` is the DEV ID, which the staged copy no longer contains.
- A dataplatform that already has report folders but no `reports.yml` fails `pr-validate` after
  the workflow refresh. That is deliberate: the deploy could not bind those reports. The
  finding names the entry to add.
- Renaming a semantic model in the hub (`gold.display_name`) now requires updating `model:` in
  the manifest. The deploy fails closed and lists the names the workspace has.
- `CICD.md`'s read-only rule now names the hub archive explicitly.
- Rejected: generating `parameter.yml` from the workspace's model IDs. It commits IDs that
  change whenever a model is recreated, and it needs a Fabric call wherever the file is
  regenerated.
- Rejected: applying the theme at deploy time. The report a BI engineer opens in Desktop would
  then differ from the one that ships.
- Verified offline against a real client's authored report (binding shape, theme wiring) and
  in tests. A live Fabric deploy is still owed, as it is for DD-239.
