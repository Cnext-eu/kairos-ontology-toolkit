# Authored Power BI reports

The reports people actually read live here (DD-253). The hub ships only the semantic models and
a blank stub report per product. The stub is republished on every hub release, so a report is
never built by editing it (DD-236). Each report you build is its own Fabric item, saved here
and deployed by `deploy-powerbi-semantic-model.yml` after the models it reads.

## Layout

```
powerbi/reports/
  reports.yml                       # every report, the model it reads, what it answers
  theme/<brand>.json                # optional: the one theme every report shares
  <Product>.<Report>.Report/        # saved from Power BI Desktop as a PBIR project
    .platform
    definition.pbir
    definition/...
    StaticResources/RegisteredResources/...
  parameter.yml                     # optional: fabric-cicd find_replace for other values
```

## Adding a report

1. In Power BI Desktop, connect live to the deployed semantic model (**Get data → Power BI
   semantic models**), build the report, and save it as a Power BI project (PBIR) into
   `powerbi/reports/<Product>.<Report>.Report/`. Keep only the `.Report` folder.
2. Give it its own name in `.platform` (`displayName`). **Never use a semantic model's name**:
   the hub's stub report carries that name and would overwrite yours on the next release.
3. List it in `reports.yml`:

   ```yaml
   reports:
     - folder: Finance.JobProfitability.Report
       model: Finance                 # the semantic model's display name in Fabric
       product: finance               # optional: the hub's Gold product
       insights: [ins-001, ins-004]   # optional: the confirmed insights it answers
   ```

4. Run `kairos-ontology check-authored-reports`. `pr-validate` runs it too.

## How it binds to the right model in each workspace

A report binds to its model by ID (`definition.pbir` → `byConnection.pbiModelDatabaseName`), and
every workspace's copy of the model has a different ID. Commit the report as Desktop saved it;
the ID it carries is only the one you built against. At deploy time the workflow looks up
`model:` by display name in the target workspace, and `kairos-ontology stage-authored-reports`
writes that ID into a staged copy of `definition.pbir`, in the long `byConnection` form that
Fabric's import requires. The staged copy is what gets published. Nothing per-environment is
committed.

A `parameter.yml` that only swapped the model ID per environment is no longer needed. Delete it.
Keep one only for other values that differ per environment.

To publish the reports to a workspace other than the models' one, set the
`FABRIC_REPORTS_WORKSPACE_ID` Environment variable. See `CICD.md`, "Authored reports".

## One theme for every report

Put the theme file in `theme/` and declare it once:

```yaml
theme: theme/brand.json
```

Then run `kairos-ontology apply-report-theme` and commit what it changes. It copies the theme into
each report's `StaticResources/RegisteredResources/` and makes it the report's custom theme,
exactly as importing it in Desktop would. After you change the theme, run it again:
`check-authored-reports` fails any report still carrying an older copy. A report that needs its
own look opts out with `theme: false` in its entry. Other resources, such as a logo, stay as
Desktop saved them.
