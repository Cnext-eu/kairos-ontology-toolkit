# DD-238: Kairos owns a curated BPA profile, and the semantic model is best practice by design

**Status:** Accepted
**Date:** 2026-09-24
**Affects:** new `core/projections/dbt/bpa_profile.py` and vendored
`core/projections/dbt/bpa_rules/BPARules.json`, new `scripts/generate_bpa_profile.py` and
generated `docs/guide/BPA_PROFILE.md`, `core/projections/dbt/gold_{shape,specs,render,assert}.py`,
`core/projections/dbt/calendar_columns.py`, `core/projections/dbt/policy_{specs,bind,normalize}.py`,
`core/compiler/provenance.py`, `cli/emit_gold.py`, `scaffold/kairos-ext.ttl` (new
`kairos-ext:bpaIgnoreRule`, `kairos-ext:goldRelationshipCrossFilter`,
`kairos-ext:measureDisplayName`), the dataplatform deploy workflow, the `kairos-design-gold`,
`kairos-package-dataplatform`, `kairos-setup-dataplatform` and `kairos-toolkit-ops` skills
**Issue:** #976 (children #977, #978, #979, #980, #981, #982)

### Context

A hub designs Gold and publishes a Power BI semantic model, but nothing checked that model
against the Best Practice Analyzer (BPA) rules the BI community uses. #744 (Part 5) proposed
running Tabular Editor BPA in `package-powerbi-release`, and DD-224 left it undecided.

Running BPA wholesale in hub CI does not hold up:

- **No suitable runner.** Tabular Editor 2's CLI runs only on Windows (.NET Framework) while
  hub CI runs on `ubuntu-latest`. The cross-platform `te` CLI is a limited preview that
  becomes paid after 2026-09-30 and is not recommended for production CI. Semantic Link Labs'
  `run_model_bpa` only reads a *deployed* model. pbiplint is AGPL at 0.1.x. DD-237 also says
  a missing .NET tool is reported and never blocks.
- **The standard rule set does not fit.** About a third of Microsoft's 71 rules do not apply
  to Direct Lake or DirectQuery, or need VertiPaq statistics a generator cannot see. Several
  contradict decisions already made: column names stay Silver identifiers (DD-221), inactive
  relationships are deliberate (DD-226), and the formatting rules impose a US date format and
  a house number style. A gate built on all of them would cry wolf (DD-163).
- **A free-form suppression list conflicts with DD-234.** A gate's escapes are registered
  claims, not a suppression list.

Three emitter defects surfaced while triaging the rules. `_relationships_tmdl` rendered no
cross-filter direction, so a filter on the far side of a many-to-many bridge never reached the
fact and the model returned wrong numbers for that path. Measures shipped without `dataType`,
named by their `measureId`, with multi-line DAX written inline and unfenced. And `dim_date`
put `isKey` on the Int64 `date_key` while every relationship joined `full_date`, so the table
was never recognised as a date table.

### Decision

**Kairos owns a curated profile.** Every rule ID in Microsoft's `BPARules.json` has exactly
one disposition per target, each with a reason, in `bpa_profile.PROFILE`:

| Disposition | Meaning |
|---|---|
| `by-construction` | The emitter cannot produce a violation; `gold_assert` re-checks the rendered text where that is cheap. |
| `compile-diagnostic` | `compile --check` reports it with a stable code. |
| `render-assert` | `emit-gold` and `package-powerbi-release` refuse to emit a model that breaks it. |
| `post-deploy-advisory` | Only a deployed model with data can answer it; reported by the dataplatform's advisory run, never blocking. |
| `not-applicable:<target>` | Cannot fire on that storage mode. |
| `rejected:<DD>` | Contradicts a recorded decision. |

The profile is Python in the toolkit, with no Tabular Editor dependency. Three Kairos-owned
rules sit beside Microsoft's: the Direct Lake guardrails, Direct Lake fallback to DirectQuery,
and `relyOnReferentialIntegrity`.

**Two targets, one profile entry each.** A semantic model is always hosted in a Power BI or
Fabric workspace. `fabric` is Direct Lake over OneLake; `databricks` is the same TMDL with
DirectQuery partitions over `Databricks.Catalogs`. Direct Lake guardrails and fallback do not
apply to DirectQuery; aggregation and time-intelligence cost apply only to DirectQuery.

**Only high-precision rules block** (DD-163). Blocking: unqualified column references and
qualified measure references in measure DAX (exact for declared dependencies), a
relationship between columns of different types, and a calendar that is not marked as a date
table. Everything else warns or is advisory.

**Exceptions are authored in TTL.** `kairos-ext:bpaIgnoreRule`, on the `owl:Ontology`
resource, reads `"<RULE_ID> on <model|table|column|measure|relationship> [<target>]: <reason>"`.
The reason is mandatory. It is fail-closed on an unknown rule, on a rule whose scope cannot
cover that kind of object, and at product level on a target the product does not emit (on a
single-domain compile the target may belong to another domain, as a bridge endpoint may,
#763). The emitter writes each exception on its object as the standard
`BestPracticeAnalyzer_IgnoreRules` annotation, which Tabular Editor honours, and lists it in
`gold_product_report` under `bpa_exceptions`. A blocking compile check honours an exception for
the object it names. Semantic Link Labs does not read the annotation (verified against 0.17.1):
it evaluates its own rule set, keyed by rule name. So the post-deploy notebook carries the
profile with it, maps each finding to its Microsoft rule ID and this target's disposition, and
applies the model's own ignore annotations itself.

**The rule set is a pinned snapshot, refreshed by hand.** `BPARules.json` is vendored at a
recorded upstream commit, the same pattern as `fabric_schema/`, so compile stays offline and
deterministic (DD-133). Upstream is not a versioned package -- it lives on `master` with no
releases -- so re-vendoring, and bumping the `semantic-link-labs` pin the dataplatform uses,
are manual steps in the `kairos-toolkit-ops` release checklist. Each rule's digest is
recorded, so a rule Microsoft *changes* fails `tests/test_bpa_profile.py` exactly like a rule
it adds, until it has been re-triaged. The profile version and upstream commit are stamped
into the Gold lane's provenance sidecar (DD-218) under `bpaProfile`.

**Checks that need data run after deploy, in Fabric, and never block the deploy.** The
dataplatform scaffolds a notebook, `fabric/KairosModelBpa.Notebook`, that runs
`sempy_labs.run_model_bpa(extended=True)` and, for Direct Lake, the guardrail and fallback
checks, and appends its classified findings to a `kairos_bpa_findings` lakehouse table when
one is attached. The deploy workflow publishes it and runs it through the Fabric job API in a
`continue-on-error` step, which skips cleanly without the notebook or without Fabric, Premium
or PPU capacity. The notebook is refreshed by `update --refresh-workflows`, not by the
managed-file marker, which would break Fabric's notebook format on line 1. Findings go back to the hub as authoring; nothing is fixed
in the deployed model (DD-206, DD-224).

**The skill advises; the compiler enforces** (DD-163, DD-155).

#### Relationships (#977)

- **`GoldRelationshipSpec.cardinality` is the edge's cardinality, not the bridge's.** A bridge
  is two edges, bridge to endpoint, and each is genuinely many-to-one: many bridge rows per
  endpoint key, one endpoint row per key. `bridgeCardinality` describes the business relation
  *between the endpoints* and stays a table property. Rendering it onto the edges, as the
  shaper used to set it, would declare a unique key non-unique. `fromCardinality` and
  `toCardinality` are rendered only when an edge differs from many-to-one, which no edge does
  today, so relationship bytes do not change for it.
- **A many-to-many bridge filters through its fact side by default.** For a filter on the far
  endpoint to reach the fact, the bridge's edge to the fact-side endpoint must filter both
  ways. An endpoint is fact-side when it is a fact, or the target of a relationship from a
  fact. When exactly one endpoint is fact-side, that edge is emitted
  `crossFilteringBehavior: bothDirections`. Otherwise it stays single and is reported under
  `undecided_bridge_filters`, because guessing a direction changes the numbers.
- **The author overrides with `kairos-ext:goldRelationshipCrossFilter`**,
  `"Table.column -> Table.column = both|single"`, on the `owl:Ontology` resource, fail-closed on
  a value naming no emitted relationship -- the `goldPrimaryRelationship` pattern (DD-226).
- **Every bidirectional edge carries the ignore annotation** for
  `CHECK_IF_BI-DIRECTIONAL_AND_MANY-TO-MANY_RELATIONSHIPS_ARE_VALID`: it has been checked.
- **`relyOnReferentialIntegrity` is not emitted.** It turns a DirectQuery join into an inner
  join. A declared unique key (DD-227) proves the one side, not that every many-side key
  resolves, and Silver leaves an unmatched foreign key null, so an inner join would silently
  drop those fact rows from every total. It needs evidence Silver does not yet carry.
- Models without bridges stay byte-identical.

#### Measures (#978)

- `dataType` is emitted from `measureDataType`: `currency` and `decimal` render as `decimal`,
  `percentage` and `double` as `double`, the rest by name.
- **`kairos-ext:measureDisplayName` names the measure in the model**; `measureId` stays the
  stable key. `rdfs:label` is deliberately not used: a label already present on a hub's
  measure resources would silently rename every measure on upgrade. The lineageTag stays
  derived from the ID, so Fabric treats a rename as an edit, not a new object. Without a
  display name the measure keeps its ID as its name, byte-identical. A display name must not
  contain control characters, brackets or leading/trailing whitespace, and must be unique in
  the model (`gold.measure-display-name-invalid`, `gold.measure-display-name-collision`).
- **DAX references a measure by the name the model carries.** When a dependency has a display
  name, a reference to it by `measureId` would not resolve in Power BI, so it fails
  (`gold.dax-measure-reference-by-id`) and names the reference to write. The renderer never
  rewrites DAX.
- A multi-line expression is emitted as a TMDL triple-backtick block.
- Columns keep their Silver snake_case names (DD-221).

#### Calendar (#979)

- **`full_date` carries `isKey`**, because BPA and the engine both recognise a date table by a
  DateTime key column, and every role relationship already joins `full_date`. `date_key`
  stays as an ordinary Int64 column.
- Every calendar column carries `summarizeBy: none` and a deterministic lineageTag seeded
  `dim_date.<column>`, the same scheme as every other table.
- `month_name` sorts by `month_number`. The calendar has no day-name column, so there is no
  second pair.
- Output changes only for hubs with an approved calendar, and it is a model change: the key
  moves.

#### Diagnostics (#980)

`compile --check` reports, from Gold shaping, with stable codes:

| Code | Severity | BPA rule |
|---|---|---|
| `gold.dax-column-unqualified` | blocking | `DAX_COLUMNS_FULLY_QUALIFIED` |
| `gold.dax-measure-qualified` | blocking | `DAX_MEASURES_UNQUALIFIED` |
| `gold.description-missing` | warning | `OBJECTS_WITH_NO_DESCRIPTION` |
| `gold.float-column` | warning | `AVOID_FLOATING_POINT_DATA_TYPES` |
| `gold.dax-division-operator` | warning | `USE_THE_DIVIDE_FUNCTION_FOR_DIVISION` |

Measures always carry `measureDefinition`, which is mandatory, so the description warning
fires for visible columns without an ontology `rdfs:comment`. `gold_assert` asserts the
`by-construction` and `render-assert` rules on the rendered text.

### Consequences

- Blocking DAX checks newly fail a hub whose measures reference columns unqualified, which
  is what the scaffold template taught. The fix is one table prefix per reference, or an
  authored `bpaIgnoreRule` with its reason. The scaffold and the acme scenario now use the
  qualified form.
- A hub with a many-to-many bridge gets a model whose bridge actually filters the fact.
  Numbers through that path change, from wrong to right.
- A hub with an approved calendar gets a re-keyed `dim_date`.
- The profile is never a claim that a model passes BPA. It records which rules the toolkit
  guarantees, which it checks, which it cannot see, and which it disagrees with, and says so
  for each rule.
- **Acceptance is one manual Tabular Editor 2 run** (`TabularEditor.exe <definition folder>
  -A BPARules.json`) against the acme scenario model. It is manual by design and not part of
  CI. Its findings may only be rules marked `rejected`, `not-applicable` or
  `post-deploy-advisory`, or *non-blocking* `compile-diagnostic` rules. A warning reports a
  finding without removing it, so Tabular Editor sees it too. A finding on a
  `by-construction`, `render-assert` or blocking rule contradicts the profile and is a defect.
- The 2026-09-24 run (Tabular Editor 2.29.0, vendored commit `50e8ce50`) found two such
  defects, both fixed. Perspectives were emitted with no members (`PERSPECTIVES_WITH_NO_OBJECTS`)
  and now list their tables' columns and measures. A #794 unproven-key relationship joined an
  int64 to a string (`RELATIONSHIP_COLUMNS_SAME_DATA_TYPE`). The shaper now drops such a
  relationship and reports it under `dropped_relationships`, and the render assertion covers
  inactive relationships too. The rerun's 37 findings are all `rejected`,
  `post-deploy-advisory`, or the `OBJECTS_WITH_NO_DESCRIPTION` warning.
