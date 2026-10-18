# DD-260: A generated seed lives in the reference seed folder and is regenerated where it lives

**Status:** Accepted
**Date:** 2026-10-18
**Affects:** `cli/reference_lists.py` (`export-reference-list`, `--dir`),
`core/dbt_contract_lint.py` (`dbt-contract.seed-duplicate-name`), `core/dbt_bundle.py`, the
how-to [Use reference data and code lists](../../guide/how-to/use-reference-data.md)
(section 8). Extends DD-257 and DD-258.
**Issue:** #1145

### Context

After [DD-257](dd-257-a-reference-list-is-shipped-loaded-by-the-hub-or-owned-by-a-source-and-its-extensions.md)
and [DD-258](dd-258-a-shipped-reference-lists-seed-carries-every-fact-its-members-state.md),
a hub's `integration/transforms/dbt/seeds/` holds four kinds of seed, each owned by someone
different:
- seeds generated from the reference models;
- extensions to a shipped list;
- crosswalks from source codes to canonical codes;
- the hub's own code lists.

A production logistics hub had 26 of them in one flat folder. Nothing showed which files
must never be edited by hand.

dbt names a seed by its file name, whatever its folder, so subfolders are safe for dbt.
The compiler's seed index, the dbt bundle, contract lint and `dbt_validation` already scan
subfolders. Two things did not hold up:
- `export-reference-list` always wrote to, and `--check` always compared against, the seeds
  root. A generated seed moved to a subfolder failed `--all --check` in `pr-validate`, and
  `--all` wrote a second copy at the root.
- Nothing rejected two seeds of one name in different folders. The bundle's duplicate check
  compares paths, which differ, so both CSVs were emitted, and dbt refused to parse the
  project.

### Decision

**A seed `export-reference-list` generates goes to `seeds/reference/`, and an existing
generated seed is always regenerated in the folder it is in. Two seeds of one name, in any
folders, are an error.**

1. **Regenerate in place.** Both `--all` and the single-class form find a seed by name
   anywhere under `seeds/` and write, or with `--check` compare, it there. A seed found in
   more than one folder is refused.
2. **New seeds go to `seeds/reference/`.** `--dir` chooses another folder under `seeds/`. A
   hub that already keeps generated seeds at the seeds root keeps writing new ones there,
   so it does not split; moving the files to `reference/` is its migration, and `--all`
   then follows them. `--dir` that disagrees with where a seed already is, is refused.
3. **One name, one seed.** `validate-dbt-contracts` reports
   `dbt-contract.seed-duplicate-name` as an error, and the dbt bundle fails on it. Lint
   findings name the seed's real path, not `seeds/<name>.csv`.
4. **Only `reference/` is a convention the toolkit relies on.** The toolkit owns those
   files. `extensions/`, `crosswalks/` and `hub-lists/` are recommended in the how-to,
   with a `CODEOWNERS` example, and nothing checks them.

### Consequences

- A hub can route each kind of seed to its owner with `CODEOWNERS`, and a reviewer sees
  that `reference/` is generated.
- No `ref()` changes: the seed's name is its file name, so moving it changes no SQL and no
  `relationships` test.
- An existing hub sees no change until it moves its generated seeds.
- The emitted `dbt_project.yml` still gives every hub seed one config block. Per-folder
  config would make the folder names part of the generator's contract; nobody has named a
  config that should differ by kind.

### Alternatives rejected

- **A prefix per kind (`ref_currency_code`) instead of folders.** A prefix renames the dbt
  resource. Every `ref()`, every crosswalk `relationships` test and every downstream model
  in the dataplatform that names the seed would break. The names already carry the kind as
  a suffix (`_local`, `_map`).
- **A `kairos.yaml` setting for the folder.** A second source of truth beside `--dir` and
  the folder the seed is in. Nothing needs it yet.
- **Lint for all four folders.** A seed's kind is not machine-decidable for the three
  hand-authored ones. Only the generated marker is, and the tool already owns that folder.
- **Keep generated seeds at the root.** It leaves ownership invisible, which is the
  problem #1145 reports.
