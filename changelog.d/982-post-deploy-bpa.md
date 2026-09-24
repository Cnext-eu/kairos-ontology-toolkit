### Added
- **The dataplatform checks the deployed semantic model against Best Practice Analyzer
  rules, advisory and never blocking (DD-238).** Some rules need a live model with data:
  cardinality, referential-integrity violations, Direct Lake guardrails and fallback to
  DirectQuery. `init-dataplatform` now scaffolds `fabric/KairosModelBpa.Notebook`, which runs
  Semantic Link Labs' `run_model_bpa(extended=True)` and, on Direct Lake, the guardrail and
  fallback checks. It maps each finding to its Microsoft rule ID and the Kairos profile's
  disposition, and applies the model's own `BestPracticeAnalyzer_IgnoreRules` annotations,
  which Semantic Link Labs does not read. Findings are appended to a `kairos_bpa_findings`
  lakehouse table when the `FABRIC_BPA_LAKEHOUSE_ID`/`_NAME` repository variables are set.
- `deploy-powerbi-semantic-model.yml` gains a `run_bpa_advisory` input (default on) and a
  `continue-on-error` step after publishing that deploys and runs the notebook. It is
  read-only over the model and exits cleanly when the notebook is absent or the workspace has
  no Fabric, Premium or PPU capacity. That is typical for a Databricks DirectQuery model in a
  Pro workspace, which gets a manual check instead. Fix findings in the hub, never in the
  deployed model.
- The `semantic-link-labs` pin (0.17.1) is owned by the toolkit and moves only with a release.
  Existing dataplatforms receive the notebook and the updated workflow with
  `kairos-ontology update --refresh-workflows`.
