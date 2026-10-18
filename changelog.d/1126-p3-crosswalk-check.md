### Added
- **`validate-dbt-contracts` checks crosswalk seeds against the reference list they map to
  (#1126 P3, DD-257).** A crosswalk seed declares its target in its docs with dbt's own
  `relationships` test (`to: "ref('transport_mode_code')"`, `field: code`).
  - **What it checks.** When the target is an authored seed, a code it lacks is now an
    error (`dbt-contract.crosswalk-unknown-code`) naming the value and its line. Before,
    such a typo only showed up as an empty link after the build.
  - **What it allows.** An empty cell is a code left unmapped on purpose. A target that is a
    model is left to dbt, which runs the same test after the build.
  - **Warnings.** A target that names nothing, or a column either CSV lacks, is
    `dbt-contract.crosswalk-unresolved`.
