### Added
- **A best-practice catalogue for Gold and DDD (DD-240).** Every modelling rule the toolkit
  knows is listed in one place, with why it matters, how it is enforced, which stage checks it,
  and whether a hub may excuse it. Hubs receive the generated pages as
  `docs/toolkit/practices/semantic-model.md` and `docs/toolkit/practices/ddd.md` on the next
  `kairos-ontology update`. The Power BI BPA rules are summarised there too;
  `docs/toolkit/BPA_PROFILE.md` keeps their per-target detail.
- **`compile --check` reports the shape of each Gold product.** After the domains compile,
  every product whose domains all compiled in the same run is checked, and these are
  reported, never blocking:
  - `gold.ambiguous-path`: a relationship the projector deactivated, and the active route it
    lost to. Before this, such edges were listed only in the product report, so a model could
    show the grand total on every row without any warning.
  - `gold.fact-to-fact`: a fact that references another fact.
  - `gold.snowflake-chain`: a dimension chain that the same fact also reaches directly.
  - `gold.role-playing-dimension` (info): an inactive second role of a dimension.

  Use `--all`, or name every domain of a product, to check it. `emit-gold` prints the same
  findings.
- **`validate --ddd` checks the design against three DDD practices:** an aggregate member
  with more than one root, or a root not tagged `AggregateRoot`; an object property that
  crosses two bounded contexts the context map does not connect; and a reference into another
  aggregate that bypasses its root. They are warnings, are listed in
  `contexts/design-notes.md`, and never change Silver.
- **One way to record an exception.** Use `kairos-ext:practiceException` in the Gold
  extension, or `kairos-ddd:practiceException` in a DDD overlay, with the same
  `"<rule> on <object> <target>: <reason>"` form. The reason is mandatory, and an exception
  that excuses nothing fails. `kairos-ext:bpaIgnoreRule` keeps working.

### Changed
- The `kairos-design-gold` and `kairos-design-architecture` skills point at the catalogue
  instead of restating its rules. The Gold skill now asks you to review
  `deactivated_relationships` after `emit-gold`.
- `validate --ddd` now prints the `ddd.tactical-in-strategic-file` code with its finding.
- The DDD vocabulary is now version 1.2.0: it adds `kairos-ddd:practiceException`.
