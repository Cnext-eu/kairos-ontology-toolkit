# DD-240: Modelling best practices live in one catalogue that the docs, the skills and the checks all read

**Status:** Accepted
**Date:** 2026-09-24
**Affects:** new `practices/` package (`semantic-model/rules.yaml`, `ddd/rules.yaml`,
`exceptions.py`), new `core/projections/dbt/gold_shape_checks.py`, new `core/ddd_practices.py`,
`core/projections/dbt/bpa_profile.py` (`parse_bpa_ignore`, `is_bpa_rule`),
`core/projections/dbt/gold_shape.py`, `gold_render.py` (`practice_exceptions`), `medallion_gold_projector.py` (bus matrix), `policy_bind.py`,
`policy_specs.py`, `policy_normalize.py`, `core/ddd.py` (`audit_ddd_practices`),
`core/projections/ddd_context_projector.py` (design-notes sections), `cli/compile.py` (the Gold
product pass), `cli/emit_gold.py`, `scaffold/kairos-ext.ttl` (`practiceException`),
`scaffold/kairos-ddd.ttl` 1.2.0 (`practiceException`), new `scripts/generate_practices.py`,
`docs/guide/practices/`, the `kairos-design-gold` and `kairos-design-architecture` skills
**Issue:** #996 (extends DD-238 and DD-091, amends DD-238 and DD-226)

### Context

The toolkit checked modelling best practice in several places, each next to the code that
happened to run it: `bpa_profile.py` and `gold_bpa_checks.py` for the Power BI Best Practice
Analyzer (DD-238), four hard-coded `ddd.*` codes in `core/ddd.py` (DD-229), and prose in the
design skills. A hub could not see the whole rule set, could not tell what was enforced from
what was only advised, and had an exception mechanism only for BPA rules.

BPA rules judge objects one at a time, so nothing judged the *shape* of a model. On the Fracht
hub (5.22.0rc5), `emit-gold fracht-operations` deactivated 22 of 51 relationships as
`ambiguous-path`, listed only under `deactivated_relationships` in the product report. About 13
were ordinary role-playing dimensions. About 9 were design faults: facts pointing at facts, a
dimension chain next to a direct edge to the same dimension. `fact_consignment -> dim_job` was
inactive, so "consignments by job type" showed the grand total on every row. `compile --check`
and `emit-gold` both passed.

`compile --check` could not have caught it even with a check in place. It shapes each domain
alone (`_shape_dimensional`, `defer_bridges=True`), so a path between two domains' tables does
not exist there; only `emit-gold` shaped the product.

### Decision

**One catalogue.** `src/kairos_ontology/practices/` holds one folder per area, each with a
`rules.yaml`. Every rule carries `id`, `statement`, `rationale`, `enforcement` (`blocking`,
`warning`, `advisory`, `post-deploy`, `none`), `stage`, `check` (the diagnostic code, or
`none`), `source`, `excusable` and the objects an exception may name. The checks stay next to
the code they inspect and name their entry by code; tests fail when a catalogued code is
emitted nowhere, or a `ddd.*` code or shape code has no entry.

**The BPA profile is projected in, not moved.** Its dispositions stay in `bpa_profile.py`,
where the vendored upstream file is triaged (DD-238); the loader turns each `RuleProfile` into
a catalogue entry, with the strictest of its two targets deciding the row. `BPA_PROFILE.md`
keeps the per-target detail. Moving ~560 lines of reviewed dispositions into YAML would have
changed no behaviour and put the upstream triage in two places.

**Generated pages, pointed at by the skills.** `scripts/generate_practices.py` writes
`docs/guide/practices/<area>.md`, shipped to hubs as `docs/toolkit/practices/`. The two design
skills point at those pages instead of restating the rules.

**One exception mechanism.** An exception reads `"<RULE> on <object> [<target>]: <reason>"` in
every area. The reason is mandatory; the rule must exist, be excusable and apply to that kind
of object; an exception that excuses nothing fails.

- Semantic model: `kairos-ext:practiceException` in the Gold extension. `kairos-ext:bpaIgnoreRule`
  is the same mechanism under its original name and keeps working; both feed one list. Only BPA
  rules become the `BestPracticeAnalyzer_IgnoreRules` TMDL annotation. The product report lists
  BPA exceptions under `bpa_exceptions` as before and practice exceptions under
  `practice_exceptions`.
- DDD: `kairos-ddd:practiceException` on an overlay or the strategic file, not in `kairos-ext`,
  so the DD-091 firewall and the overlay leak scan are unchanged.

**The semantic model prefers a Kimball star.** The shape rules in `gold_shape_checks.py`
judge the product against a dimensional design, on the whole product only:

| Rule | Code | Level |
|---|---|---|
| deactivated edge no measure activates, with the active route it lost to | `gold.ambiguous-path` | warning |
| a fact references a fact | `gold.fact-to-fact` | warning |
| a dimension chain the fact also reaches directly | `gold.snowflake-chain` | warning |
| a fact with no calendar role | `gold.fact-without-date` | warning |
| a periodic snapshot with no calendar, an accumulating snapshot with fewer than two date roles | `gold.snapshot-shape` | warning |
| a declared bridge weight no measure reads | `gold.bridge-weight-unused` | warning |
| two dimensions from one class or one Silver model | `gold.duplicate-dimension` | warning |
| a fact with no relationships, a dimension that reaches no fact | `gold.unconnected-table` | warning |
| an inactive role of a dimension whose other role is active | `gold.role-playing-dimension` | info |
| any other dimension-to-dimension edge (an outrigger) | `gold.star-schema` | info |
| a `SUM` over a periodic snapshot that takes no single date's value | `gold.semi-additive-sum` | info |
| a non-count measure homed on a dimension | `gold.measure-on-dimension` | info |
| a many-to-many bridge with no weight | `gold.bridge-unweighted` | info |
| facts that share no dimension besides the calendar | `gold.product-spans-processes` | info |
| a `dim_`/`fact_`/`bridge_` prefix that contradicts the role | `gold.table-name-role` | info |

The existing blocking `gold.incompatible-dimension-version` is catalogued as
`semantic-model.version-binding-matches-exposure`. Three BPA dispositions change, so the
profile is version 2. `SNOWFLAKE_SCHEMA_ARCHITECTURE` was rejected by DD-238 and is now
checked by `gold.star-schema`. `INACTIVE_RELATIONSHIPS_THAT_ARE_NEVER_ACTIVATED` was rejected
by DD-226 and is now checked by `gold.ambiguous-path`: an edge a measure activates is
intended and no longer reported. `ENSURE_TABLES_HAVE_RELATIONSHIPS` was a post-deploy check
and is now `gold.unconnected-table`. `emit-gold` also writes `<product>/<product>-bus-matrix.md`,
Kimball's fact-by-dimension grid, as the review artifact for these rules.

None of these rules blocks. `compile --check` gains a **Gold product pass**: after the domains
compile, every product whose member domains all compiled in the run is shaped from the plans
just built, and only the shape findings are reported (the BPA ones were already reported per
domain). A product with a member missing from the run, or one that does not shape at product
level, gets a one-line note and never fails the compile; `emit-gold` fails such a product with
the same error, and prints the shape findings too.

**DDD rules** in `ddd_practices.py`: `ddd.one-root-per-aggregate`,
`ddd.cross-context-relationship-on-map` and `ddd.aggregate-reference-by-identity`. They run in
`validate --ddd` over the hub-wide model the context diagrams already use, which loads the
domain ontologies, and are listed in `contexts/design-notes.md` under "Practice findings" with
the recorded exceptions. They are warnings only (DD-091): documentation, never Silver. A root
that is itself a member of a larger aggregate is allowed, as the projector already supports.

### Consequences

- The `ddd.*` consistency codes keep their levels. `ddd.tactical-in-strategic-file`, defined but
  never printed before, now appears in the output it described.
- Amends DD-238 and DD-226 (both carry the note). DD-238 left snowflaking to the ontology.
  It still is the ontology's decision -- flattening is authored, never done by the renderer --
  but the toolkit now states a preference, as an advisory an outrigger can be excused from.
  The deactivation of surplus paths (DD-226) is unchanged; only what gets reported about it
  changes.
- Every existing product gets `<product>-bus-matrix.md` on its next `emit-gold`, a new file
  in the Gold output. That is deliberate: a review artifact that exists only for some products
  would not be looked for.
- The `USERELATIONSHIP` match is on the two bracketed column references a measure names. A
  measure that builds the reference indirectly, through a variable say, is not recognised,
  and its edge is still reported. That errs toward reporting.
- A shape exception is only proven stale at product level. A single-domain compile cannot tell
  whether it excuses something in another domain, exactly as for `bpaIgnoreRule` targets.
- `compile --check` on a domain of a multi-domain product checks the product only when every
  member domain is in the same run; `--all` checks them all. The JSON payload of the run's first
  domain carries a `gold_products` list, so neither output shape changes.
- A design-notes file whose design breaks no practice, and records no exception, keeps its bytes.
- Rejected: moving the BPA dispositions into YAML (see above); shape checks inside the
  per-domain compile (half the model is absent there, so a route can look ambiguous or not for
  that reason alone); blocking shape rules (every finding has a legitimate "deliberately"
  answer, so blocking would train authors to write exceptions without reading them, DD-163);
  hub-authored practices (`ontology-hub/practices/`, the issue's open question), left to a
  follow-up once the catalogue format has settled.
