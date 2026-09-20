### Fixed
- **The whole business glossary now reaches a prompt.** Three defects compounded: the
  `limit` check broke out of the *file* loop, so a hub with two glossary files could have
  the second never read at all; the survivors were then chosen alphabetically rather than
  by relevance; and the default cap of 120 was set when a glossary was a few dozen
  hand-written terms. On a hub whose discovery produced 201 concepts, **120 reached
  alignment and 74 reached anchoring**. Every file is now read before the cap is applied,
  the cap is a single named `GLOSSARY_PROMPT_LIMIT = 500`, and `propose-alignment` reports
  `N of M ... in scope` when it truncates, so a hub that outgrows it can see that it has.

  Measured after: **201 terms at alignment, 125 at anchoring** — the whole glossary, and
  every concept carrying a linked class. The fingerprint that detects glossary drift is
  unaffected: it already passed its own high limit.

- **`import-tmdl` finds flat-layout exports in a directory.** The recursive scan required
  a directory literally named `definition`, which is the assumption #874 removed one call
  downstream. A flat export was found when named directly and invisible to a directory
  scan, so pointing at a staging folder imported nothing and exited 0 while telling the
  operator to check a path that was correct. `.import/powerbi/` is a scaffolded location,
  so a hub routinely has several exports in one directory.

  A `.pbip` pointer whose artifact folders are absent no longer reaches the operator as a
  raw traceback. `run_import_tmdl` still raises — a programmatic caller has to know the
  import did not happen, and a test already pinned that — but the CLI renders it as a
  clean failure, which is where the handling was missing.

- **`scaffold-extensions` refuses to render a property onto a class the domain cannot
  resolve.** Global anchoring (DD-185) picks from the whole class catalog and a domain's
  imports are scoped by its blueprint, so the two can disagree. When they did, the result
  was silent: 33 properties rendered, merged into the ontology, passed `validate` — syntax
  and SHACL both accept an `rdfs:domain` pointing anywhere — and were invisible to
  `generate-bindings`, which resolves through the domain's own closure. The skip names
  both ways out, because adding the import and re-anchoring the table are different
  decisions.
