---
name: kairos-design-gold
description: Design optional Gold products that consume the canonical v5 CompilePlan.
---

# Kairos Gold Product Design

Gold is an optional consumer of the immutable CompilePlan. It must not resolve source inputs,
rebuild Silver planning, or override EntityBinding grain, identity, load, field, or relationship
facts. The registered implemented profile is `dimensional-powerbi-v1`; unknown profiles fail.

## Design fleet mode (DD-088)

Default is interactive. A fleet override applies only to this skill invocation and is never
inherited. Record rationale, confidence, and references for every AI-approved choice. Stop for
ambiguous measures, security, PII, proprietary data, destructive choices, or low-confidence
business semantics.

## Insights before measures

- Start from the decision, not the data: "what will someone do differently after reading
  this?" A product whose measures nobody asked for is a data dump with a star schema.
- Read `integration/discovery/bi/*-report-usage.yaml` first when the client has a legacy
  estate. It ranks measures by how often a report actually *places* them on a visual and
  fields by how often they are sliced on, which is the demand signal a model inventory
  cannot give — most legacy models define far more measures than any report uses.
- Propose personas and insights into `integration/discovery/bi/insights.yaml` with
  `status: draft`, then confirm them with the human. Only `confirmed` insights are checked
  against the product. One insight is one persona's question, the KPI that answers it, and
  the measures and dimensions it needs:

  ```yaml
  schema_version: "1"
  personas:
    - id: ops-manager
      description: Runs the terminal day to day
  insights:
    - id: on-time-departures
      persona: ops-manager
      question: How many departures left on time this week, by terminal?
      kpi: On-time departure rate
      comparison: prior week          # a KPI alone is a number; against a comparison
      product: bookings-overview      # it is information
      measures: [On Time Rate]
      dimensions: [dim_terminal.terminal_name, dim_date.full_date]
      status: draft
  ```

- Author the measures a confirmed insight needs in the owning domain's Gold extension, then
  re-run `emit-gold`: it reports which confirmed insights the product cannot answer yet and
  writes `<product>-insight-brief.md` beside the semantic model.
- That brief plus [`report-design-inspiration.md`](report-design-inspiration.md) is the
  hand-off to whoever builds the report. The hub governs the model; page layout and visual
  design are theirs.
- `report-design-inspiration.md` is **inspiration, not a gate**: nothing in it is validated
  by the toolkit or blocks an emit. Use it to shape the conversation about what a page
  should say — start from the decision, one message per page, every number against a
  comparison — and drop anything that does not fit this client.
- BI evidence is demand, never business authority (DD-147). A measure on 40 legacy visuals
  proves someone needs that number, not that the number is currently right.

## Where the hub stops and the report begins

- The hub owns everything governed: tables, relationships, measures, calendar, security,
  column visibility and descriptions. It also emits `<Product>.Report`, which is
  **intentionally blank** (DD-236): one empty page so the project opens. The report
  deliverable is `<product>-insight-brief.md`.
- The BI engineer owns look and feel: pages, visuals, bookmarks, theme, and the report's
  own layout. Build that as a **separate Fabric item with its own name**, bound to the
  deployed model — the generated stub is republished on every hub release, so edits to it
  are lost.
- If a report needs something the model lacks, that is a hub change. Author it, or run
  `harvest-gold` to turn what was built in Desktop into a reviewable proposal. Working
  around the model in the report layer is how one governed measure acquires three competing
  definitions.

## Harvest Desktop and Fabric edits

- Desktop is a proposal tool; the hub stays the source of truth (DD-206 §8). Never tell a
  BI engineer to stop editing, and never hand-edit the emitted TMDL: run
  `kairos-ontology harvest-gold <product> --from <exported model>` after they have worked.
- `--from` takes a PBIP export folder, a `<Name>.SemanticModel` folder, or its
  `definition/` folder. Power BI Desktop writes one with **Save as PBIP**. A Direct Lake
  model cannot be saved as a PBIP from Desktop — export it through Fabric git integration
  instead.
- It writes `model/planning/gold-harvest/<product>.md` (what changed, including what
  cannot be harvested) and `<product>-proposal.ttl` (the changes that have authoring
  vocabulary, grouped by owning domain). **It applies nothing.** Review the proposal, paste
  what you agree with into the owning domain's `<domain>-gold-ext.ttl`, and re-emit.
- Harvested measures arrive at DD-113 lifecycle `provisional` with the author's own `///`
  description as the starting `measureDefinition`, and a guessed `measureDataType` marked
  `CHECK`. Confirm both before promoting the measure.
- A column un-hidden in Desktop is *not* proposed as an annotation. The hub hides by Silver
  column role (DD-221), so a report author needing one visible is a signal that the role is
  wrong or the column is really business data — that is a conversation, not an annotation.
- A renamed column is reported and never patched: the hub names columns after the Silver
  identifier, and every authored DAX expression and `measureColumnDependency` references
  that name.

## Authored Gold contract

- Declare the Gold profile and schema explicitly.
- Decide the product's scope before its tables (DD-222). A product follows a business
  process, not a domain: a fact from one domain with conformed dimensions from others.
  Declare it in `kairos.yaml` under `gold.products` with a `name` and its `domains`, and
  emit it with `emit-gold <product>`. Each participating domain still authors its own
  `<domain>-gold-ext.ttl` for the tables it owns, and each may appear in only one product.
  A hub that declares no product keeps one product per Gold-configured domain.
- A cross-domain relationship needs a DD-138 `externalReference` in the child's
  EntityBinding; without one the compile blocks on `safety.relationship-endpoint` before
  Gold sees it. After emit, read the `unresolved_relationships` warning: it lists foreign
  keys whose join column is emitted but whose target table is not in the product, which is
  a dead column until the owning domain joins the product.
- Author the calendar and the security policy in exactly one participating domain. The
  product inherits them, which is how one calendar serves every product that includes that
  domain; two declarations fail closed.
- Declare each fact, dimension, or bridge role, emitted name, source entity, and grain explicitly.
- Keep history exposure consistent with the compiled entity's load contract.
- Define measures as first-class resources with stable IDs, definitions, dependencies, result
  types, formats, and folders. Projection does not prove business correctness.
- Generate calendars only from explicit bounds, fiscal settings, locale, time zone, and role-playing
  date bindings.
- Control column visibility with the right term of three (DD-221). Surrogate keys, generated
  foreign keys, source-identity, entity-IRI, audit and SCD history columns are hidden
  automatically by their Silver role, and the mapped column a join reads from stays visible.
  Author `kairos-ext:goldHideColumn "Table.column"` only for a business-looking column this
  product should not browse; it hides, and the column keeps its relationships and DAX.
  `kairos-ext:goldExcludeColumn` (DD-217) removes a column from the product entirely, and
  `kairos-ext:securityPolicy` is the access-control tool. Both column terms are fail-closed:
  a value naming no emitted column blocks the compile.
- Generate RLS/OLS only from complete fail-closed security policy and emitted-column bindings.
  Runtime identity provisioning and enforcement remain downstream responsibilities.
- Keep platform-specific behavior inside supported Fabric/Databricks capability contracts.
- On `databricks` the semantic model is `directQuery`, so declare `gold.databricks_connection`
  (`server_hostname`, `http_path` per environment) in `kairos.yaml`. Projection fails closed
  without it; the emitted fabric-cicd `parameter.yml` rewrites those two values per deployment
  environment. Fabric Direct Lake needs `gold.direct_lake_connection` instead
  (`workspace_id` + `item_id` per environment, where `item_id` is the Fabric Warehouse dbt
  writes Gold into); it is required, not optional.

## Best practice by design (DD-238)

The model is judged against Microsoft's Best Practice Analyzer rules through the Kairos
profile, which gives every rule one disposition per target. The full table is
`docs/toolkit/BPA_PROFILE.md` in a hub, generated from the toolkit's profile. **This skill advises; the compiler enforces** (DD-163). Ask
the questions below while designing, so `compile --check` has nothing to say.

For each measure, confirm:

- **A display name** (`kairos-ext:measureDisplayName`): what report users read in the field
  list. `measureId` stays the stable key. Other measures reference it by this name.
- **A description** (`measureDefinition`, mandatory) and **a format string**
  (`measureFormatString`, mandatory past `intent`).
- **Qualified column references**: `SUM(fact_sale[amount])`, never `SUM([amount])`.
  Reference measures unqualified by their display name, `[Total Sales]`. Prefer `DIVIDE()` to
  `/` wherever the denominator can be zero.

For each many-to-many bridge, decide **which way filters flow**. By default the bridge's edge
to its fact-side endpoint filters both ways, so a slicer on the far dimension reaches the
fact. When neither endpoint, or both, is on the fact side, the product report lists the bridge
under `undecided_bridge_filters` and it stays single-direction. Decide it with
`kairos-ext:goldRelationshipCrossFilter "bridge_x.a_sk -> dim_a.a_sk = both"`.

Per target:

- **Fabric (Direct Lake).** No calculated columns or tables; the emitter writes none, so model
  the value in Silver. A Delta source must be a table, not a SQL view: a view silently falls
  back to DirectQuery. Row counts are bounded by the capacity's Direct Lake guardrails.
  Fallback and guardrails are checked after deploy.
- **Databricks (DirectQuery).** The Time Intelligence calculation group costs a warehouse
  round trip per query, so weigh it against query volume. `relyOnReferentialIntegrity` is
  deliberately not emitted: Silver leaves an unmatched foreign key null, and the inner join it
  enables would drop those rows. The post-deploy check needs Premium, PPU or Fabric capacity.

What happens when a rule is broken:

| Where | Checks |
|---|---|
| `compile --check`, blocking | `gold.dax-column-unqualified`, `gold.dax-measure-qualified`, `gold.dax-measure-reference-by-id`, `gold.measure-display-name-invalid`, `gold.measure-display-name-collision` |
| `compile --check`, warning | `gold.description-missing`, `gold.float-column`, `gold.dax-division-operator` |
| `emit-gold`, blocking | date table marked, `month_name` sorted, numbers not summarized, active relationship types agree, every column sourced, every measure formatted |
| After deploy, advisory | the dataplatform's BPA notebook: cardinality, referential integrity, Direct Lake guardrails and fallback, and the remaining authored-DAX rules |

When a rule genuinely does not hold for one object, record it rather than working around it:
`kairos-ext:bpaIgnoreRule "DAX_COLUMNS_FULLY_QUALIFIED on measure sales.margin: <reason>"` on
the `owl:Ontology` resource. The reason is mandatory. An exception that excuses nothing fails
`compile --check`, so it cannot outlive its reason. Findings from the post-deploy run come back
here as authoring, never as edits to the deployed model (DD-206, DD-224).

Run `kairos-ontology compile <domain> --check --format json` before Gold generation. Gold consumes
the returned CompilePlan view through the registered projector; it never calls a legacy Silver/dbt
projection path. Review generated dbt/DDL, TMDL, DAX, relationships, and security scaffolding, then
validate them in the target toolchain.

Gold produces the first generated report and semantic-model version, packaged and checksummed as
part of the hub release. Target-workspace deployment, environment promotion, and business
acceptance of that report are downstream responsibilities — see `CICD.md`.
