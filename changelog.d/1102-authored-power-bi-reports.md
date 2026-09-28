### Added
- **Authored Power BI reports get a home, a deploy step and per-environment binding in the
  dataplatform (DD-253).** The reports your BI engineers build now live in `powerbi/reports/`,
  one PBIR folder per report. Each is listed in `powerbi/reports/reports.yml` by the display
  name of the semantic model it reads, optionally with the hub product and the confirmed
  insights it answers. `init-dataplatform` scaffolds the folder, and `update` adds its
  `README.md` to existing dataplatforms.
  - **The deploy workflow publishes them in a second pass after the models are framed.** It
    looks up each model's ID in the target workspace, writes it into a staged copy of the
    report's `definition.pbir` (`kairos-ontology stage-authored-reports`) in the long
    `byConnection` form Fabric's import requires, and never touches the hub archive. There are
    no model IDs to commit per environment, and a hand-kept `parameter.yml` of them can be
    deleted. Set `FABRIC_REPORTS_WORKSPACE_ID` to publish the reports to their own workspace.
  - **`pr-validate` runs `kairos-ontology check-authored-reports`.** It fails when a report is
    unlisted, is unbound, is named after a semantic model (the hub's stub report would
    overwrite it) or carries an outdated copy of the shared theme.
  - **One theme for every report.** Declare it as `theme:` in `reports.yml`, run
    `kairos-ontology apply-report-theme` and commit the result.
  - Refresh the two workflows with `kairos-ontology update --refresh-workflows`. If you already
    have report folders, add a `reports.yml` entry for each one, or `pr-validate` fails.

### Changed
- **The dataplatform `CICD.md` no longer reads as if authored reports were forbidden.** Its
  "never hand-edit PBIR or report JSON" rule now names the hub archive. A new "Authored reports"
  section covers the folder, the deploy pass and the theme.
