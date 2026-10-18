### Added
- **Hub CI fails when a generated reference seed falls behind the reference models
  (#1126, DD-257).**
  - **What changed.** `export-reference-list` now records the class and domain in each
    generated seed's docs. `export-reference-list --all` regenerates every generated
    seed from that record, and `--all --check` fails when one is stale.
  - **Where it runs.** The hub `pr-validate` workflow runs `--all --check` next to
    `validate-dbt-contracts`. It passes with nothing to do in a hub that generated no
    seeds.
  - **After an upgrade.** `update --upgrade` now names `export-reference-list --all`
    first among the regeneration commands it prints.

  Hubs pick up the workflow change with `kairos-ontology update --refresh-workflows`. The
  previous generation is recorded, so it refreshes automatically. A seed generated before
  this change has no recorded origin; regenerate it once with
  `export-reference-list <class> --domain <domain>`.
