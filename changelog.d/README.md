# Changelog fragments

One file per change, merged into `CHANGELOG.md`'s `## [Unreleased]` section when a release
is cut.

## Why

Every PR used to edit the same few lines directly under `## [Unreleased]`. Two PRs open at
once therefore conflicted on it — not semantically, just textually, because both inserted at
the same anchor. Four parallel PRs meant three rebases that changed nothing about the code
under review. A fragment is its own file, so two PRs never touch the same path.

## Writing one

Add `changelog.d/<issue-or-pr-number>-<short-slug>.md`:

```markdown
### Fixed
- **One-line summary of what changed for a user.** Then the detail: what was wrong, why it
  mattered, and what is different now. Same voice as the existing `CHANGELOG.md` entries —
  written for someone upgrading, not for someone reviewing the diff.
```

- The `###` heading is required, and is any section this changelog already uses: `Added`,
  `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`, `Performance`, `Documentation`,
  `Decisions`, `Notes`, `Known issues`. A qualifier is fine — `### Removed (BREAKING)`
  sorts with `Removed`.
- One file may carry more than one section.
- Not every PR needs one. A `chore:`/`docs:` PR with no user-visible effect can skip it;
  this is a convention, not a CI gate.

## Cutting a release

```bash
python scripts/collect_changelog.py            # preview, changes nothing
python scripts/collect_changelog.py --apply    # merge into CHANGELOG.md, delete fragments
```

Then promote `## [Unreleased]` to `## [X.Y.Z] — YYYY-MM-DD` as usual — see
[`docs/dev/RELEASING.md`](../docs/dev/RELEASING.md).

## Editing `CHANGELOG.md` directly

Still correct for release commits, and for a hotfix that has to land a note on a released
line. Just avoid it in an ordinary feature or fix PR, which is where the conflicts come from.
