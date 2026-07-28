# CLI Reference

This is the exact retained v5 root command surface. `kairos-ontology --help` is the
executable authority.

## Canonical generation

| Command | Purpose |
|---|---|
| `compile DOMAIN --check` | Build and validate a `CompilePlan` without writing |
| `compile DOMAIN --explain [--format text\|json]` | Explain that plan without writing |
| `compile DOMAIN --emit [DIRECTORY]` | Atomically render manifest-owned dbt artifacts (default `output/medallion/dbt`) |

The modes are mutually exclusive. The compiler reads the adapter from `kairos.yaml`;
supported values are `fabric` and `databricks`.

`project` remains registered for retained non-compiler projections. Its `dbt`, `silver`,
`powerbi`/`gold`, and `mdm-profile` targets reject use and direct authors to `compile`;
Gold and MDM are typed downstream consumers of a compiler-produced immutable `CompilePlan`,
never graph-authority project targets. `project --target all` excludes them.
`scaffold-mapping`, `scaffold-silver-ext`, `validate-mapping`, and
`validate-silver-ext` remain only as explicitly legacy, non-authoritative utilities.

## Retained root commands

| Category | Commands |
|---|---|
| Compile/project | `compile`, `project`, `mdm-validate` |
| Validate | `validate`, `validate-dbt`, `catalog-test`, `validate-mapping`, `validate-silver-ext`, `suggest-shapes` |
| Source/discovery | `import-source`, `import-flatfile`, `import-tmdl`, `show-source-schema`, `source-privacy`, `analyse-sources`, `audit-silver-samples`, `propose-alignment`, `build-glossary`, `discovery-status`, `discovery-conformance` |
| Inspect/report | `resolve-ontology`, `show-class-inventory`, `list-class-properties`, `explain-term`, `coverage-report`, `generate-inventory`, `check-inventory`, `draft-model-report` |
| Legacy scaffold helpers | `scaffold-mapping`, `scaffold-silver-ext` |
| Setup/update | `init`, `new-repo`, `migrate`, `init-dataplatform`, `update`, `update-refmodels` |

`migrate` changes an older folder layout; it does **not** convert v4 authoring to v5.

## Removed commands

The following commands do not exist and must not appear in active procedures:

`status`, `lifecycle`, `check-projection`, `check-release`, `check-claims`,
`derive-claims`, `decide-claims`, `migrate-claims`, `claims-to-silver-ext`,
`capture-dbt-contract-evidence`, `check-transformation-readiness`,
`inventory-dbt-candidates`, `migrate-column-iris`, `reconstruct-dbt-transformation`,
and `sync-dbt-contracts`.

Use `compile --check` for compiler safety and `compile --explain` for plan diagnostics.
Neither is a runtime, deployment, or release-certification claim.

## Unreleased commit testing

`update --test-ref BRANCH-OR-SHA` resolves an immutable commit and saves the exact prior
dependency source. `update --restore` restores it. These options are mutually exclusive
with `--upgrade` and do not publish a release.
