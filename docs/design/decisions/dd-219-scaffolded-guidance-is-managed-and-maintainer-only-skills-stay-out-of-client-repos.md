# DD-219: Scaffolded guidance is managed, and maintainer-only skills stay out of client repos

**Status:** Accepted
**Date:** 2026-09-05
**Affects:** `_managed_scaffold_map()`, the stamping pass in `init` and `new-repo`,
`scripts/sync_dev_skills.py`'s exclusion set, and what a scaffolded hub or dataplatform
receives.
**Implementation:** `cli/shared.py`, `cli/setup.py`, `tests/test_scaffold_doc_surface.py`

### Context

An audit of everything the scaffold ships found 27 documents totalling 1,444 lines, split
across two update regimes and no test covering either.

**Half of it could never be corrected.** Managed files carry
`<!-- kairos-ontology-toolkit:managed vX.Y.Z -->` and are replaced when the client runs
`kairos-ontology update`; a release pushes nothing, the client pulls. Everything else was
written at `init` and frozen forever. That write-once half was 16 files and 725 lines --
including every per-directory `README.md` under `ontology-hub/`. A wrong instruction in
`model/ontologies/README.md` could only ever reach hubs created after the fix, and nothing
reported the gap. This is the same silence `_git_hygiene_gaps` was written to end for
`.gitignore`, where one real hub sat 36 lines against a 52-line template and tracked 3,617
files under `.import/` as a result.

The split was also inverted where it mattered: `ontology-hub/decisions/README.md` was
managed while the hub's root `README.md` was not.

**Maintainer skills shipped to clients.** `kairos-toolkit-dev` and
`kairos-toolkit-dogfood` -- 314 lines aimed at *this* repository, dogfood explicitly
adversarial and hunting toolkit gaps using a client's data -- were installed into every
scaffolded hub, and were selectable by an agent working there.

### Decision

The eleven per-directory guides become managed. They carry no substitution tokens (the
`{company}` / `{slug}` braces in the discovery ones are filename examples in prose), so
the existing verbatim-copy path handles them unchanged.

Two files stay deliberately unmanaged: `ontology-hub/decisions/index.md` and
`.import/modeling/feedback/index.md` are regenerated from the hub's *own* records by
`kairos-ontology decision` and `... feedback`. Managing either would have `update`
overwrite an accumulated log with the scaffold's empty table.

`init` and `new-repo` gain a stamping pass, because the bulk `ontology-hub/` copy does not
stamp. Without it a brand-new hub reported ten files as `unmanaged` and one missing, and
failed the `update --check` that `managed-check.yml` runs on every pull request -- a fresh
hub would have been red on its first PR. The pass is narrow: it skips a file already
stamped, and skips one whose content differs from the scaffold's, so an operator-authored
`CICD.md` survives and `--force` remains the only way over it.

`kairos-toolkit-dev` and `kairos-toolkit-dogfood` join `_UNMANAGED_SKILL_DIRS`, and so do
`SC-merge-pr` and `SC-document`. `SC-merge-pr` documents *this* repository's release
process -- `scripts/finish_pr.py`, bumping `src/kairos_ontology/__init__.py` -- neither of
which exists in a scaffolded repo, and it shipped carrying a paragraph telling the reader
not to apply it there, which is a caveat working around a packaging mistake rather than a
design. `SC-document` drives a Cnext Outline workspace behind `OUTLINE_API_KEY`. Both leave
`_DATAPLATFORM_SKILLS` too; a scaffolded hub now receives 22 skills instead of 26.
`kairos-toolkit-ops` deliberately does not: clients use it to move their toolkit pin, and
it is in the dataplatform subset already. Existing hubs lose the two automatically -- the
stale-skill sweep deletes a marker-carrying skill whose directory the scaffold no longer
ships.

### Consequences

Newly managed files are overwritten on the next `update`, so a client who edited one of
those READMEs loses that edit. That is the standing managed-file bargain, now stated in
both `CICD.md` and the `update` docstring, which had understated the managed set even
before this change.

The write-once surface drops from 725 lines to 274, and 245 of what remains is the three
`README.md.template` files that carry real substitution tokens. `_copy_managed` does no
substitution, so those cannot be managed without extending the mechanism -- left as is,
and the reason is recorded here rather than rediscovered.

Rejected: deleting the per-directory READMEs to shrink the surface. Reading them showed
task-focused help sitting beside the thing it explains -- `compile --check` next to the
bindings, import commands next to `.input/`. The defect was that they could not be fixed,
not that they existed.

Found and fixed alongside: the dataplatform's `CICD.md` is written by `_copy_managed`, so
its `{ORG}` was never substituted and clients read a literal
`https://github.com/{ORG}/kairos-ontology-toolkit`. A test now asserts no verbatim-copied
document contains a known substitution token.
