### Fixed
- **A table bound through a contracted dbt model no longer reports as undecided.** The
  DD-164 audit read one authored source form, `source.relation`, so a binding using
  `source.dbtModel` — DD-133 §3d's documented mechanism when the grain needs relational
  work first — contributed nothing to the set of bound tables. `compile --all --emit` was
  clean and the source tables were read, mapped and emitted to Silver, while `validate`
  called each of them `disposition.undecided-source-table`. The only two ways to silence
  it were both wrong: a table-grain disposition for a table that *is* bound, which the
  ledger documents against, or an explicit `bound` row, which it calls redundant. The
  audit now scans the selected model's SQL with the compiler's own extraction authority,
  so the tables it reads count as bound — which also restores the `#925`
  `disposition.bound-and-ruled-out` conflict for them, computed from the same set and,
  until now, lost for `dbtModel` bindings. A source table reached only through an
  upstream `ref()`ed model is still reported as undecided.
- **A SQL comment that mentions `source()` no longer fails compilation.** Call sites were
  counted against text from which only *Jinja* comments had been stripped, so the line
  `-- The two source() calls are written out rather than generated.` was counted as a
  call whose arguments could not be resolved statically. One comment rejected a model
  whose calls were both literal and both resolved, with `dbt-source.source-unparsed`
  naming a defect it did not have and a remedy — rewrite the calls — that could not have
  helped. SQL line and block comments are now stripped before counting, sparing `--`
  inside a string literal. Only the *count* changes: dbt renders Jinja before SQL is
  parsed, so a `{{ source() }}` written inside a SQL comment is still a real dependency
  and is still declared in the emitted project.
