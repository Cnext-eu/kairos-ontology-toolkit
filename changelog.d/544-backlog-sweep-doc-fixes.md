### Fixed
- **The langfuse install command in `.env.example` now works (issue #544).** It said
  `uv sync --group langfuse`, but the hub scaffold declares no `[dependency-groups]` table
  at all — the extra lives under `[project.optional-dependencies]`, so the documented
  command simply failed. Every sibling line in the same file already said `--extra`. This
  was the last of the issue's three causes still standing; the extra itself and the
  silent-skip warning were fixed earlier.
- **The Gold insight example no longer references a column the calendar never emits.**
  `kairos-design-gold` and the how-to guide both used `dim_date.week` in a `dimensions:`
  list. The emitted calendar has no `week` column, so the example could not pass insight
  coverage — copying it produced a "not answerable" status with no obvious cause.
- **`import-tmdl --help` describes what it actually writes.** It claimed "only the two
  generated artifacts are written" and listed the Engineering Pack and Concept Mapping,
  omitting the per-report usage pack — which on a client estate is the most useful thing
  the command produces, and was findable only by reading the source.
