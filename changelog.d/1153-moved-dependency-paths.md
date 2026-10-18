### Fixed
- **Moving a seed or contracted dbt model to another folder no longer breaks
  `compile --all --emit` (#1153).** DD-260 recommends organising seeds into
  `seeds/reference/`, `extensions/`, `crosswalks/` and `hub-lists/`. But after a move, every
  other domain's recorded dependency state still named the old path, and a whole-hub emit
  failed with `ArtifactCollisionError: contracted dbt model name ... resolves to both ...`.
  The only way out was to emit into an empty publish folder. A whole-hub emit now retires
  the old path for the domains it is about to re-emit and removes the old published file.
  A single-domain emit still refuses, because the other domains have not re-emitted yet,
  and its message now says to run `compile --all --emit --confirm-emit`.

### Documentation
- **The seed layout (DD-260) is in the hub's `integration/transforms/dbt/README.md`,
  the `kairos-develop-dbt-transformation` skill and the user guide.** They showed a flat
  `seeds/<name>.csv` and used `country_codes.csv` as the example. They now show the four
  folders, who edits each, and the whole-hub emit to run after moving seeds.
