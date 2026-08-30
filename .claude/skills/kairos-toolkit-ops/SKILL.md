---
name: kairos-toolkit-ops
description: Release the toolkit and update hub dependencies, managed files, and reference models.
---

# Toolkit Operations

Set `KAIROS_SKILL_CONTEXT=1` before skill-owned CLI calls. Keep a clean working tree and review all
generated diffs.

## Hub update and diagnostics

- `kairos-ontology update --check`: compare installed managed files.
- `kairos-ontology update`: refresh managed instructions, skills, workflows, and templates.
- `kairos-ontology update --upgrade`: resolve the configured stable, preview, or explicit-tag
  channel, update the dependency pin, lock, sync, and refresh managed files.
- `kairos-ontology update --test-ref <ref>`: transactionally test a toolkit Git ref.
- `kairos-ontology update --restore`: restore the dependency captured by `--test-ref`.
- `kairos-ontology update-refmodels`: update the reference-models package to the latest
  pinned release (or `--version <ver>` for a specific version).

After an update, inspect `git diff`, run managed/scaffold tests, and compile representative v5
bindings. Updating reference models is explicit: inspect ontology closure and compiler diagnostics
before accepting changed semantics.

## Toolkit release

1. Work from a clean feature branch and merge reviewed changes to `main`.
2. Update `src/kairos_ontology/__init__.py`, `CHANGELOG.md`, and `uv.lock` as required.
3. Run the full relevant tests plus `uv build`.
4. Commit with DCO sign-off, tag `vX.Y.Z`, and push the commit and tag.
5. Verify the release workflow and attached wheel/sdist with `gh`.

Use SemVer: fixes are patch, compatible features minor, and breaking contracts major. RC/beta/alpha
versions use PEP 440 in `__version__` and matching Git tags. Never publish when managed skill pairs,
reference assets, or package tests drift.

## Hub and dataplatform release operations

A separate, adjacent concern from the toolkit's own release above: releasing a **hub or
dataplatform repository** that this toolkit scaffolds. Keep the two apart — do not apply the
toolkit's own SemVer/tag/CHANGELOG rules to a hub or dataplatform repo.

- **Hub release:** tag the validated `main` commit (the same commit whose PR already regenerated
  and diff-checked the tracked publish output). When Gold is configured, `kairos-ontology
  package-powerbi-release` (`cli/package_powerbi_release.py`) packages and checksums
  `powerbi-semantic-model.zip`; the generated `release-projections.yml` then validates the
  already-tracked dbt bytes at that tag rather than regenerating them, and records the hub commit
  SHA and archive SHA-256 as release evidence.
- **Hotfix and forward-port:** the generated `CICD.md`'s hotfix section documents the exact-SHA
  hub/dataplatform hotfix and forward-port flow. Point users there rather than re-describing it in
  this skill.
- **Managed-guide updates:** `CICD.md` and `CONTRIBUTING.md` are managed files. The same
  `update`/`update --upgrade` mechanism documented above for the toolkit's own managed files now
  also carries these two guides into hub and dataplatform repositories.
