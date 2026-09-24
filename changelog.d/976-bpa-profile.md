### Added
- **A Kairos-owned Power BI Best Practice Analyzer profile (DD-238).** Every rule in
  Microsoft's `BPARules.json` now has one recorded disposition per target (Fabric Direct
  Lake, Databricks DirectQuery): guaranteed by construction, checked at compile time,
  asserted at render, advisory after deploy, not applicable, or rejected with the decision it
  contradicts. The rules are vendored at a pinned upstream commit and refreshed by hand; a
  test fails until any new or changed upstream rule is triaged. The full table is in
  `docs/guide/BPA_PROFILE.md`.
- **`kairos-ext:bpaIgnoreRule` records an exception to one BPA rule for one object**, as
  `"<RULE_ID> on <model|table|column|measure|relationship> [<target>]: <reason>"` on the Gold
  extension's `owl:Ontology` resource. The reason is mandatory. The exception is emitted as
  the `BestPracticeAnalyzer_IgnoreRules` annotation Tabular Editor honours, and listed under `bpa_exceptions` in the product report. An unknown rule, a rule
  that cannot apply to that kind of object, or a target the product does not emit is
  rejected.
- The Gold provenance sidecar records the BPA profile version and upstream commit under
  `bpaProfile`.

### Decisions
- **DD-238** — Kairos owns a curated BPA profile rather than running Tabular Editor in CI,
  and the semantic model is best practice by design: the design skill advises, the compiler
  and emitter enforce what they can, and the dataplatform checks what needs data after
  deploy, without blocking it. DD-224's open question on best-practice rules now points here.
