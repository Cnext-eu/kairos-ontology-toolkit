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
- `kairos-ontology update-refmodels --git-ref <ref>`: update the committed reference-model set.

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
