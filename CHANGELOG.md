# Changelog

All notable changes to the Kairos Ontology Toolkit are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> **Release status.** **5.23.0** is the latest GA release (2026-09-25), superseding
> **5.22.0** (2026-09-24). It fixes how relationships are drawn and declared, and makes the
> hub PR gate faster:
>
> - ER diagrams draw real relationship cardinality instead of `||--o{` everywhere
>   (DD-241). Relationship cardinality is declared in OWL only; `compile` and `validate`
>   now warn when a binding or a SHACL shape disagrees with it.
> - The hub `pr-validate.yml` checks the architecture diagrams in their own parallel job,
>   so the compile job is no longer the critical path.
>
> **What to expect on the first run after upgrading from 5.22.0.**
>
> | you will see | why |
> |---|---|
> | **Diagram diffs in `model/contracts/diagrams/`** on the next `compile --all --emit`: `\|o--o{` where a foreign key is optional, `o\|` for a one-to-one binding | DD-241, #999. The ERDs used to draw every edge `\|\|--o{`. The dbt package is byte-identical unless a binding says `cardinality: one-to-one` |
> | **`validate` warns `cardinality.shacl-duplicates-owl`** (or `-contradicts-owl`, `-shacl-only`) | A SHACL `sh:minCount`/`sh:maxCount` on an object property restates OWL. Remove it; see `docs/toolkit/how-to/declare-relationship-cardinality.md`. Warnings only |
> | **`compile` warns `relationship.optional-but-ontology-requires`** or `relationship.one-to-one-not-in-ontology` | The binding's `missingParent`/`cardinality` contradicts the OWL bounds. Warnings only |
> | **`update --refresh-workflows` rewrites `pr-validate.yml`** with a third job, `architecture` | #998. A hub that requires the `validate` check keeps working; add `architecture` to branch protection if you want it required |
>
> **Upgrading from 5.21.0 or earlier?** 5.22.0's first-run notes still apply on top of the
> above:
>
> | you will see | why |
> |---|---|
> | **`update` renames `_analysis/` files** and splits `table-dispositions.yaml` into one file per source system | DD-235, #943. `update --check` lists the changes first; the old names are still read this release |
> | **`compile --check` fails with `gold.dax-column-unqualified`** | A measure references a column without its table, e.g. `SUM([total_amount])`. Write `SUM(fact_invoice[total_amount])`, or record a `kairos-ext:practiceException` with its reason |
> | **`compile --check` reports Gold product findings** — `gold.ambiguous-path`, `gold.fact-to-fact`, `gold.star-schema`, `gold.fact-without-date` and others | DD-240. They never block. Read `docs/toolkit/practices/semantic-model.md`; fix each one or excuse it. `--all` checks every product |
> | **`emit-gold` writes `<product>-bus-matrix.md`**, and the re-emitted model has a re-keyed `dim_date` and bidirectional bridge edges | DD-240, DD-238. Numbers through a many-to-many bridge change from wrong to right: republish the model |
> | **`import-tmdl` fails without the .NET 8 SDK** | DD-237. It reads models with the Microsoft TOM SDK and has no fallback |
> | **`validate --ddd` warns about aggregates and cross-context properties** | DD-240. Warnings only; never Silver |
>
> **Dataplatforms.** Run `kairos-ontology update --refresh-workflows`. The Power BI deploy job
> now runs in a GitHub Environment, so the Azure federated credential subject becomes
> `repo:<org>/<repo>:environment:<ENV>`: add one per Environment before the first deploy, or
> `azure/login` fails. The deploy also refreshes every Direct Lake model and fails when one
> cannot read its tables. `FABRIC_WORKSPACE_ID` and `FABRIC_ITEM_ID` may be Environment
> variables or secrets.
>
> **Upgrading from 5.20.0 or earlier?** Read 5.21.0's notes as well: re-run
> `propose-relationships` rather than pasting from a 5.20.0 run, and expect
> `disposition.bound-and-ruled-out` from `validate` for a binding of a ruled-out table.
>
> **Upgrading from 5.19.0 or earlier?** 5.20.0's first-run notes still apply on top of the
> above: re-anchoring drops operational columns from `grain_columns` (a **Silver grain
> change** — re-emit deliberately), `build-glossary` regroups concepts by label, and
> `generate-bindings` skips tables recorded `not-business-data`, `blueprint-gap` or
> `deferred`.
>
> Everything recorded under the `5.18.0rc*` headings below shipped as part of 5.18.0 —
> those are the per-change record of how it was built, not separate releases. The same
> holds for `5.15.0rc*`/`5.16.0rc*` under 5.17.0 and `5.13.0rc*` under 5.14.0.
>
> **Upgrading from 5.18.0 or earlier?** Read 5.19.0's notes as well — its five newly
> blocking gates, its `dbt_project.yml` rewrite and its `enforcement:` provenance all
> still apply on top of the above.
>
> Read **5.11.0** before upgrading: `propose-alignment` refuses to run without
> `table-anchors.yaml`, so a hub that never ran `anchor-tables` will stop.
> `--without-anchors` is the escape hatch and `anchor-tables` is the one-command fix.

## [Unreleased]

### Added
- **`kairos-ext:goldExcludeRelationship "Table.column -> Table.column"`** (#1012). Leaves
  one foreign-key or bridge edge out of a Gold product, keeping the Silver relationship and
  its column. It is the Gold term for "remove the redundant route", the remedy
  `gold.ambiguous-path` suggests. Before, that could only be done by deleting a true
  relationship from the binding: `goldExcludeColumn` on the key failed with
  `gold.relationship-column-not-emitted`. The two terms now compose.
  - Fail-closed: `gold.unknown-excluded-relationship`.
  - Listed as `excluded_relationships` in the product report.
  - Deferred per domain when it names another domain's table.

### Fixed
- **A calendar role or primary relationship can name another domain's table** (#1003,
  #1012). A product's one calendar is authored in one domain, but each domain's own
  `compile` shaped it against that domain's tables only. So a `kairos-ext:rolePlayingDate`
  on another domain's fact failed with `calendar.missing-role-column`, and a
  `goldPrimaryRelationship` to another domain's dimension, or to a bridge edge, failed with
  `gold.unknown-primary-relationship`. Both now follow the cross-domain bridge contract
  (#763):
  - the single-domain compile records the reference, prints it, and carries it as
    `deferred_references` in the JSON payload and the product report;
  - the product check (`compile --all --check`, `emit-gold`) enforces it fail-closed.

  A reference to a table that is in the domain's own shaping still fails there.
  `calendar.missing-role-column` now names every bad role, not only the first. The
  already-deferred `goldRelationshipCrossFilter` and `bpaIgnoreRule` targets are now
  reported in the same list instead of being skipped silently.

## [5.23.0] — 2026-09-25

Relationship cardinality (DD-241, #999) and a faster hub PR gate (#998).

### Added
- **`project --target` can be repeated.** `project --target erd --target ddd` runs both
  targets over one load of the ontologies, where two separate runs parsed every domain twice.
  CI and `full-validate.yml` now use the combined form.
- **`validate --jobs N`** sets how many domains SHACL checks at once. The default is still the
  CPU count, at most 8, and `KAIROS_VALIDATE_JOBS` still works. SHACL is CPU-bound, so more
  jobs than cores does not speed it up.
- **`compile` warns when a binding contradicts the ontology.**
  - `relationship.optional-but-ontology-requires`: OWL requires the parent, but the binding
    says `missingParent: null`.
  - `relationship.one-to-one-not-in-ontology`: the binding says one-to-one, but OWL lets a
    parent have many children.
- **`validate` warns about SHACL counts on relationships.** A hand-authored `sh:minCount` or
  `sh:maxCount` on an object property is reported as one of:
  - `cardinality.shacl-duplicates-owl`: it restates the OWL bound;
  - `cardinality.shacl-contradicts-owl`: it disagrees with the OWL bound;
  - `cardinality.shacl-only`: no OWL bound exists, so no diagram and no compile check sees it.

  All are warnings. Datatype-property counts are not affected.
- **A new how-to, "Declare relationship cardinality"**
  (`docs/toolkit/how-to/declare-relationship-cardinality.md`). Relationship cardinality is
  declared in OWL only. The how-to has worked examples and a table of which output reads which
  declaration. The `kairos-design-domain` and `kairos-design-mapping` skills and the managed
  `model/shapes/README.md` now say the same.

### Changed
- **The hub PR gate checks the architecture diagrams in their own parallel job.**
  `pr-validate.yml` used to regenerate and diff `ontology-hub-publish/architecture` inside the
  compile job, after the emit. Those two `project` runs were more than half that job on a
  15-domain hub. They read only authored inputs, so they now run in a third job, beside
  `validate` and `compile`, and the compile job is no longer the critical path. The gate still
  covers the same three paths. Receive the workflow with
  `kairos-ontology update --refresh-workflows`. A hub whose branch protection requires the
  `validate` check keeps working; add `architecture` to it if you want it required too.

### Fixed
- **ER diagrams draw relationship cardinality instead of `||--o{` everywhere (DD-241).**
  Every edge in the Silver, master, contract and Gold ERDs used to read "parent exactly one,
  child zero or more", so an optional foreign key looked mandatory and a one-to-one link could
  not be drawn. Each diagram now draws what its layer guarantees:
  - The Silver and master ERDs: `||` when the foreign key is NOT NULL (`missingParent: error`),
    `|o` when it is nullable, and `o|` on the child end for a `cardinality: one-to-one` binding.
  - The contract ERD: read from the ontology's OWL bounds.
  - The Gold ERD: from the fact's key column and the relationship's own cardinality.

  **Expect a diagram diff on the next `compile --all --emit`** wherever a foreign key is
  optional. The dbt package itself is byte-identical unless a binding says one-to-one.
- **The DDD context diagram draws both ends of an association**, not only the target end, from
  the same derivation as the class diagram.
- **A binding's `cardinality: one-to-one` now reaches Silver.** It was dropped before; it is
  recorded on the foreign-key constraint as `relationship_cardinality`.

## [5.22.0] — 2026-09-24

General availability of the 5.22 line. Everything under `5.22.0rc1` to `rc5` below is part
of this release. The entries in this section are what landed after rc5:
- the Fabric deploy fixes (DD-239);
- the best-practice catalogue with its Kimball model-shape and DDD checks (DD-240);
- the advisory BPA step running on every model.

### Added
- **A deploy is green only when the model can read its data.** After publishing, every Direct
  Lake model is refreshed (framed), and the deploy fails when one cannot read its tables: a
  wrong item ID, a missing `gold_*` table, or a missing Warehouse permission. Before this, all
  three surfaced only when a report user opened the report. DirectQuery models are skipped.
  The new `refresh_after_publish` input turns the check off, for diagnosing credentials only.
- `CICD.md` documents the Fabric deploy prerequisites: Environments, federated credentials,
  the "Service principals can use Fabric APIs" tenant setting, the workspace role, capacity,
  Warehouse read access for viewers under SSO, and how the RLS placeholder roles behave.
- **A best-practice catalogue for Gold and DDD (DD-240).** Every modelling rule the toolkit
  knows is listed in one place, with why it matters, how it is enforced, which stage checks it,
  and whether a hub may excuse it. Hubs receive the generated pages as
  `docs/toolkit/practices/semantic-model.md` and `docs/toolkit/practices/ddd.md` on the next
  `kairos-ontology update`. The Power BI BPA rules are summarised there too;
  `docs/toolkit/BPA_PROFILE.md` keeps their per-target detail.
- **`compile --check` reports the shape of each Gold product.** After the domains compile,
  every product whose domains all compiled in the same run is checked, and these are
  reported, never blocking:
  - `gold.ambiguous-path`: a relationship the projector deactivated and no measure activates
    with `USERELATIONSHIP`, and the active route it lost to. Before this, such edges were
    listed only in the product report, so a model could show the grand total on every row
    without any warning.
  - `gold.fact-to-fact`: a fact that references another fact.
  - `gold.snowflake-chain`: a dimension chain that the same fact also reaches directly.
  - `gold.fact-without-date` and `gold.snapshot-shape`: a fact with no calendar role, a
    periodic snapshot with no calendar, an accumulating snapshot with one date role.
  - `gold.duplicate-dimension`: two dimensions built from the same class or Silver model.
  - `gold.unconnected-table`: a fact with no relationships, or a dimension that reaches no
    fact.
  - `gold.bridge-weight-unused`: a bridge weight no measure reads.

  These are reported as info (Kimball design advice): `gold.star-schema` (every
  dimension-to-dimension edge), `gold.role-playing-dimension`, `gold.semi-additive-sum`,
  `gold.measure-on-dimension`, `gold.bridge-unweighted`, `gold.product-spans-processes`,
  `gold.table-name-role`.

  Use `--all`, or name every domain of a product, to check it. `emit-gold` prints the same
  findings.
- **`emit-gold` writes a bus matrix.** `<product>/<product>-bus-matrix.md` shows which facts
  share which dimensions, the roles of each, and which dimensions are conformed across
  facts.
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
- **`item_id` replaces `lakehouse_id`** in `gold.direct_lake_connection` and in the
  dataplatform's `gold-connections.yml`. dbt writes Gold into a Fabric **Warehouse**, and that
  Warehouse is the item Direct Lake reads through OneLake. The old name sent authors looking for
  a lakehouse that does not hold the tables. `lakehouse_id` still works, with a deprecation
  warning. Setting both is rejected. Emitted artifacts are unchanged.
- fabric-cicd is pinned (1.3.0) instead of installed unpinned, and bumped only with a toolkit
  release. `azure/login` allows a service principal with no Azure subscription.
- The `kairos-design-gold` and `kairos-design-architecture` skills point at the catalogue
  instead of restating its rules. The Gold skill now asks you to review
  `deactivated_relationships` after `emit-gold`.
- **The BPA profile is version 2 (DD-240 amends DD-238 and DD-226).** Three rules change:
  - `SNOWFLAKE_SCHEMA_ARCHITECTURE` is now checked by `gold.star-schema`: the toolkit
    prefers a Kimball star.
  - `INACTIVE_RELATIONSHIPS_THAT_ARE_NEVER_ACTIVATED` is now checked by
    `gold.ambiguous-path`.
  - `ENSURE_TABLES_HAVE_RELATIONSHIPS` is now checked at compile time by
    `gold.unconnected-table`.

  The Gold provenance sidecar records the new profile version.
- `validate --ddd` now prints the `ddd.tactical-in-strategic-file` code with its finding.
- The DDD vocabulary is now version 1.2.0: it adds `kairos-ddd:practiceException`.

### Changed (BREAKING for deploys that relied on the silent fallback)
- **`apply-gold-connection` fails closed** when the archive carries no `parameter.yml`, or
  when the target environment is declared neither by the hub nor by `gold-connections.yml`.
  Environment keys are case-sensitive. A `DEV`/`dev` mismatch used to deploy the default
  workspace without a word. A release packaged by an older toolkit has no `parameter.yml`:
  re-release the hub. Existing dataplatforms receive the fixed workflow and example with
  `kairos-ontology update --refresh-workflows`; update `gold-connections.yml` to the
  `${FABRIC_WORKSPACE_ID}` / `${FABRIC_ITEM_ID}` form.

### Changed (BREAKING for existing dataplatform Azure logins)
- **The Power BI deploy job runs in a GitHub Environment (DD-239).** Its `target_environment`
  input names the GitHub Environment, so each target has its own `FABRIC_WORKSPACE_ID`,
  `FABRIC_ITEM_ID`, Azure IDs and required reviewers. Before this, DEV, UAT and PROD shared one
  workspace secret and had no approvals. **Upgrade step:** the Azure federated credential
  subject changes to `repo:<org>/<repo>:environment:<ENV>`. Add one per Environment before the
  first deploy, or `azure/login` fails. Repository-level secrets still resolve inside an
  Environment. Receive the workflow with `kairos-ontology update --refresh-workflows`.

### Removed
- `.github/fabric/deployment-settings.json.example` is no longer scaffolded: nothing read it.
  Existing copies are harmless.

### Fixed
- **`FABRIC_WORKSPACE_ID` can be an Environment variable, not only a secret.** The Direct Lake
  override step read the variable first and fell back to the secret, but publish, refresh and
  the advisory BPA run read only the secret. A workspace ID stored as an Environment variable
  passed the override and then published nowhere. Every step now reads it the same way.
  Receive the workflow with `kairos-ontology update --refresh-workflows`.
- **The advisory BPA run analyses every semantic model in the release.** It used to analyse
  the first one only, and took the storage mode from any TMDL file in the whole package, so a
  mixed release could run the Direct Lake checks against a DirectQuery model. Each model now
  gets its own run in its own mode, and one model's failure does not skip the rest.
- A Direct Lake model published with `refresh_after_publish: false` has read no data, so its
  cardinality and VertiPaq rules find nothing. The BPA step now says so in a notice.
- The refresh step reports a published model that is missing from the workspace as an error
  naming the model, instead of failing with a Python traceback.
- **Promoting a Power BI release to another environment now actually repoints it.** The
  release archive left out `parameter.yml`, the file fabric-cicd uses to rewrite the model's
  OneLake URL (or Databricks warehouse) per environment. `apply-gold-connection` then reported
  "nothing to parameterise" and exited 0, and **every environment silently deployed the
  hub's default workspace and item**. The hub-wide `parameter.yml` now ships at the archive
  root, which is where fabric-cicd reads it. Products that render different
  parameterisations fail the packaging instead of shipping one of them. (#993)
- **`${VAR}` values in `.github/fabric/gold-connections.yml` resolve.** The deploy step passed
  only the target environment name, so the documented `${FABRIC_PROD_WORKSPACE_ID}` form
  always failed with "unset or empty". The step now passes `FABRIC_WORKSPACE_ID` and
  `FABRIC_ITEM_ID` (a repository variable, or secret, of that name). Only the *target*
  environment is resolved, so a DEV deploy no longer fails on PROD's unset variables.

## [5.22.0rc5] — 2026-09-24

Fifth release candidate for 5.22.0. It adds two things on top of rc4:

- Tables bound through `source.dbtModel` count as decided for the DD-180 gate (#973).
- The Power BI Best Practice Analyzer work (DD-238, #976 to #983): a Kairos-owned rule
  profile, bridge filter direction, measure display names and data types, a proper date
  table, BPA diagnostics in `compile --check`, and an advisory post-deploy check in the
  dataplatform.

**Upgrade notes.**

- A measure that references a column without its table, e.g. `SUM([total_amount])`, now
  fails `compile --check` with `gold.dax-column-unqualified`. Write
  `SUM(fact_invoice[total_amount])`, or record a `kairos-ext:bpaIgnoreRule` with its reason.
- Hubs with an approved calendar get a re-keyed `dim_date` (`isKey` moves to `full_date`).
  Hubs with a many-to-many bridge get a bidirectional edge on its fact side. Numbers through
  that bridge change, from wrong to right. Republish the model.
- Dataplatforms: run `kairos-ontology update --refresh-workflows` to receive the fixed deploy
  workflow and the advisory BPA notebook.

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
- **`kairos-ext:goldRelationshipCrossFilter "Table.column -> Table.column = both|single"`**
  decides one relationship's filter direction, fail-closed on an edge the product does not
  emit. Bidirectional edges and why are listed under `bidirectional_relationships` in the
  product report.
- **`kairos-ext:measureDisplayName` gives a measure the name report users see.** Measures
  were named by their `measureId` (e.g. `'invoice.total-amount'`) in the field list. The
  display name now names the measure in the model, while `measureId` stays the stable key
  and still seeds the lineageTag, so Fabric treats a rename as an edit. Without one the
  measure keeps its ID as its name, byte-identical. Another measure's DAX must reference it
  by the display name; a reference by ID fails with `gold.dax-measure-reference-by-id` and
  names the reference to write. Invalid or colliding names fail
  (`gold.measure-display-name-invalid`, `gold.measure-display-name-collision`).
- **`compile --check` now reports BPA findings in Gold measures and columns (DD-238).**
  Two block, because they are exact for the references a measure declares:
  `gold.dax-column-unqualified` (a column referenced as `[amount]` instead of
  `fact_sale[amount]`) and `gold.dax-measure-qualified` (a measure referenced with a table
  prefix). Three warn: `gold.description-missing` (visible columns without an ontology
  `rdfs:comment`, one warning per table), `gold.float-column` and
  `gold.dax-division-operator`. String literals and comments are never read as references.
  A `kairos-ext:bpaIgnoreRule` with its reason excuses one object; an exception excusing
  nothing fails with `gold.bpa-ignore-unused`.
- **`emit-gold` and `package-powerbi-release` assert the profile's guarantees on the
  rendered model**: a marked date table with a DateTime key, a sorted `month_name`, visible
  numbers never summarized, every column sourced, every measure with an expression and a
  format string, no control characters in descriptions, and no active relationship between
  columns of different types.
- **The dataplatform checks the deployed semantic model against Best Practice Analyzer
  rules, advisory and never blocking (DD-238).** Some rules need a live model with data:
  cardinality, referential-integrity violations, Direct Lake guardrails and fallback to
  DirectQuery. `init-dataplatform` now scaffolds `fabric/KairosModelBpa.Notebook`, which runs
  Semantic Link Labs' `run_model_bpa(extended=True)` and, on Direct Lake, the guardrail and
  fallback checks. It maps each finding to its Microsoft rule ID and the Kairos profile's
  disposition, and applies the model's own `BestPracticeAnalyzer_IgnoreRules` annotations,
  which Semantic Link Labs does not read. Findings are appended to a `kairos_bpa_findings`
  lakehouse table when the `FABRIC_BPA_LAKEHOUSE_ID`/`_NAME` repository variables are set.
- `deploy-powerbi-semantic-model.yml` gains a `run_bpa_advisory` input (default on) and a
  `continue-on-error` step after publishing that deploys and runs the notebook. It is
  read-only over the model and exits cleanly when the notebook is absent or the workspace has
  no Fabric, Premium or PPU capacity. That is typical for a Databricks DirectQuery model in a
  Pro workspace, which gets a manual check instead. Fix findings in the hub, never in the
  deployed model.
- The `semantic-link-labs` pin (0.17.1) is owned by the toolkit and moves only with a release.
  Existing dataplatforms receive the notebook and the updated workflow with
  `kairos-ontology update --refresh-workflows`.

### Changed (BREAKING for hubs whose measures reference columns unqualified)
- A measure written `SUM([total_amount])` -- the form the scaffold template used to teach --
  now fails `compile --check`. Qualify the reference (`SUM(fact_invoice[total_amount])`), or
  record a `bpaIgnoreRule` with the reason the rule does not hold.

### Changed (model change for hubs with an approved calendar)
- **`dim_date` is now keyed on `full_date`, so Power BI recognises it as a date table.** The
  semantic model put `isKey` on the Int64 `date_key` while every calendar role
  relationship joined `full_date`, so the table never counted as a date table (BPA
  `MODEL_SHOULD_HAVE_A_DATE_TABLE`). `isKey` now sits on the DateTime `full_date`. The
  warehouse is unchanged: the DDL, the ERD and the dbt tests still key on `date_key`. In
  Fabric this re-keys `dim_date`; republish the model after upgrading (DD-238).
- **Calendar columns render like every other table's.** Each now carries
  `summarizeBy: none`, so year and month numbers no longer default to Sum, and a
  deterministic lineageTag, so a calendar column is the same object across emits.
  `month_name` sorts by `month_number` instead of alphabetically. Hubs without an approved
  calendar are unaffected.

### Fixed
- **A table a binding reads no longer blocks `compile` as an undecided unanchored table
  (#973).** Since #948, the DD-180 gate counted only table-grain ledger rows as decisions.
  It never looked at bindings, so a table that is bound but has no reference-class
  anchor could not be cleared by any command:
  - `source-disposition set --disposition bound` is refused, because the binding is
    what states it.
  - `deferred` makes `validate` fail with `disposition.bound-and-ruled-out`.
  - `not-business-data` un-decides the bound join columns.

  The gate now uses `load_bound_relations`, the same check as the DD-164 audit, so
  `compile` and `validate` agree on which tables are bound. Hand-written table-grain
  `bound` rows added as a workaround are no longer needed and can be removed.
- **`source.dbtModel` bindings count the tables their whole `ref()` chain reads (#973).**
  Before, only the selected model's own SQL was scanned. Under the three-layer rule
  (#949), the `int_merged__` model a binding selects reads no `source()` itself; the
  `stg_` stages two `ref()` levels down do. Scanning one model therefore found none of
  the tables, and all of them were reported as unbound. The chain is now followed. A
  `ref()` that matches no model, or more than one, ends that branch without an error;
  `compile` still reports it.
- **A many-to-many bridge now lets a filter on its far endpoint reach the fact.** Every
  relationship was emitted single-direction, so in Fact -> DimA <- Bridge -> DimB a slicer
  on DimB stopped at the bridge and the model returned wrong numbers for that path. The
  bridge's edge towards its fact-side endpoint (a fact, or the dimension a fact joins) is
  now emitted `crossFilteringBehavior: bothDirections`, with the BPA annotation recording
  that it was checked. When no single endpoint is on the fact side the projector does not
  guess: it leaves the bridge single-direction and lists it under
  `undecided_bridge_filters` in the product report. Numbers through a bridge path change,
  from wrong to right; models without bridges are byte-identical (DD-238).
- **Measures carry their `dataType`.** `measureDataType` was mandatory past `intent` but only
  reached the product report. It now renders in the TMDL (`currency` as decimal,
  `percentage` as double).
- **A multi-line `measureExpression` no longer breaks the model.** It was written inline and
  unescaped, so its second line was read as a property. It is now emitted as a TMDL
  triple-backtick block, which TOM deserializes and `harvest-gold` reads back unchanged.
- The scaffold's example measure and the acme scenario now show the best-practice form: a
  display name and table-qualified column references (DD-238).
- **An authored-policy failure in Gold keeps its own code.** A provisional measure missing
  `measureDataType`, for example, surfaced as `safety.type-incompatible: projection
  normalization failed` at the hub root. It now reports
  `measure.incomplete-semantic-contract` with its rule, located at the domain's Gold
  extension.
- Descriptions drop control characters before they reach the TMDL.
- **Perspectives are no longer empty.** A perspective was emitted as bare `perspectiveTable`
  lines with no members, which Tabular Editor's Best Practice Analyzer, run against the acme
  model, reported as a perspective with no objects. Each perspective now lists every column and
  emitted measure of the tables it declares, as Desktop writes them.
- **A relationship whose columns have different types is dropped and reported, not
  emitted.** A fact with no surrogate key fell back to its first non-nullable column
  (`_source_system`, a string), and an integer foreign key was joined to it as an inactive
  relationship. Direct Lake refuses such a relationship, even inactive. It is now listed under
  `dropped_relationships` in the product report, and the render assertion covers inactive
  relationships too.
- **The dataplatform deploy workflow now installs uv before running `kairos-ontology`.**
  `deploy-powerbi-semantic-model.yml` ran `uv run kairos-ontology apply-gold-connection`
  in a job that never installed uv or synced the locked environment, so a deploy failed
  before publishing anything. The job now runs `astral-sh/setup-uv` (the same pinned
  version as `pr-validate.yml`) and `uv sync --locked` first. Existing dataplatforms
  receive the fix through `update`: the previous workflow generation is recorded, so an
  untouched copy refreshes automatically instead of reporting "customized". (#983)

### Documentation
- **The BPA profile reaches the people who design and ship the model (DD-238).**
  - `kairos-design-gold` gains a "best practice by design" section. For each measure it asks
    for a display name, a description, a format string and qualified DAX. For each bridge it
    asks which way filters flow. It gives the Direct Lake and DirectQuery differences, and
    says which checks block, which warn and which run after deploy.
  - `kairos-package-dataplatform`, `kairos-setup-dataplatform` and the dataplatform `CICD.md`
    describe the advisory post-deploy run, including the manual check for a Pro workspace. Its
    findings go back to the hub as authoring.
  - `kairos-toolkit-ops` adds the manual release-checklist step to refresh the vendored
    `BPARules.json` and the `semantic-link-labs` pin.
  - The CLI reference lists the new `compile --check` and `emit-gold` codes.
  - `BPA_PROFILE.md` now ships to hubs as `docs/toolkit/BPA_PROFILE.md`.

### Decisions
- **DD-238** — Kairos owns a curated BPA profile rather than running Tabular Editor in CI,
  and the semantic model is best practice by design: the design skill advises, the compiler
  and emitter enforce what they can, and the dataplatform checks what needs data after
  deploy, without blocking it. DD-224's open question on best-practice rules now points here.

### Notes
- Bridge edges keep TOM's many-to-one default. `bridgeCardinality` describes the relation
  between the two endpoints, not either edge, and rendering it onto an edge would declare the
  endpoint's unique key non-unique. `relyOnReferentialIntegrity` is deliberately not emitted
  on Databricks: a unique key does not prove every fact-side key resolves, and Silver leaves
  an unmatched key null, which an inner join would silently drop (DD-238).

## [5.22.0rc4] — 2026-09-24

Fourth release candidate for 5.22.0. It adds two things on top of rc3:

- `scaffold-staging` writes the per-source `int_<source>__<entity>` layer (#949).
- Gold fixes for products that share a domain (#859, #860), plus ISO week columns
  on `dim_date` (#833).

**Upgrade note.** `weekPattern` on a calendar profile must now be `iso-8601` or
`iso-8601-monday`. A hub that uses any other value fails `validate` and compile with
`calendar.unsupported-week-pattern` until the value is changed. The rc2 upgrade notes
still apply.

### Added
- **`dim_date` has `week_number` and `week_start_date` (#833).** Both follow ISO 8601:
  weeks start on Monday, and week 1 is the week that contains the year's first Thursday.
  On Databricks the week number comes from `weekofyear`; on Fabric it comes from
  `datepart(iso_week, …)`. `week_start_date` is that week's Monday. It sorts and groups
  weeks correctly across a year boundary, which a bare week number does not. Every
  surface that reads the calendar declaration picks both columns up: the dbt model, the
  DDL, the TMDL, `schema.yml`, the ERD and both allowlists. An insight that slices by
  `dim_date.week_number` now resolves.

### Changed
- **`weekPattern` must be `iso-8601` or `iso-8601-monday` (#833).** These are the two
  conventions the calendar implements, and both mean the same ISO weeks. Any other
  value is now rejected in two places:
  - `validate`, through SHACL `sh:in`;
  - compile, with `calendar.unsupported-week-pattern`.

  Before, the value was accepted and copied onto every row even though nothing acted on
  it.
- **Identical calendar profiles in one Gold product are one calendar (#859).** A shared
  conformed domain and a fact domain in the same product can now both declare a
  calendar profile. If every setting matches (bounds, fiscal start, week pattern, locale,
  holiday source, time zone, period closure and approval), the Gold product uses one
  calendar and combines both profiles' role-playing dates. The product report lists the
  other profiles under `calendar.contributing_profiles`.
  `gold.product-calendar-conflict` is now raised only when the settings really differ,
  and its message names the fields that differ.
- **`scaffold-staging` generates all three dbt layers (#949).** For each `--source` it
  now writes an `int_<source>__<entity>` model between the `stg_<source>__<entity>`
  stage and `int_merged__<entity>`. That model starts as a passthrough and is where the
  source's joins, filters, main-record rankings and code mapping go. The merge model now
  reads only the `int_<source>__` models, never a stage or `source()`. Adding a third
  source then means adding its own `int_` model, not editing the merge. What the
  scaffold writes passes the `validate-dbt-contracts` layering warnings added in
  5.22.0rc1. The `kairos-develop-dbt-transformation` skill and its examples follow the
  same rule.

### Fixed
- **Dropping a shared domain from one Gold product no longer deletes another product's
  provenance sidecar (#860).** `metadata/<domain>-gold.provenance.json` is listed in the
  manifest of every product that uses the domain. When one product stops writing it, the
  file leaves that product's manifest but stays on disk while another manifest in the
  same directory still lists it. The last product to drop the domain removes it, as
  before.

## [5.22.0rc3] — 2026-09-24

Third release candidate for 5.22.0. It adds one change on top of rc2: `compile --all` stops
re-reading unchanged inputs for every domain (#968). On a 15-domain hub, the check went
from 91 s to 57 s with byte-identical output. Nothing else changes, so the rc2 upgrade
notes still apply.

### Performance
- **`compile --all` no longer re-reads unchanged inputs for every domain (#968).** On a
  15-domain hub, `compile --all --check` went from 91 s to 57 s, with byte-identical
  output. The emit path, which runs the same analysis, benefits the same way.
  - The disposition ledger was parsed twice per domain. `load_dispositions` is now
    memoised per process, keyed on each ledger file's path, modification time and size,
    so a write in the same run is still seen.
  - The same bronze source `.ttl` files were parsed once per domain (187 times on that
    hub). They are now parsed once per process, with the same key.
  - The YAML reads on the compile path (bindings, contracts, dbt sources, the alignment
    report, the conformance artifact, the Silver projector) use PyYAML's C loader when it
    is available, as the ledger already did.

## [5.22.0rc2] — 2026-09-24

Second release candidate for 5.22.0. It closes the product decisions from the September
issue review and most of the remaining design issues: TMDL is read with the TOM SDK
(#879), document readers are shipped and `.import/drafts/` added (#907), the insight
brief is recorded as the report deliverable (#830), Power BI demand appears on the gap
sheet (#942), deprecated reference classes are warned about (#938), anchoring uses the
canonical class registry (#913, #927, #863), closure staleness is detected (#865), and
open feedback records are cross-checked (#695).

**What to expect on the first run after upgrading from 5.22.0rc1.**

| you will see | why |
|---|---|
| **`import-tmdl` fails without the .NET 8 SDK** | DD-237, #879: it now reads models with the Microsoft TOM SDK and has no fallback. Install .NET 8; the first run builds the reader once and needs NuGet access |
| **`import-tmdl` rejects an export it used to read** | The export is not valid TMDL, and Power BI Desktop would refuse it too. Re-export it complete. In a batch, only the refused model is skipped |
| **new warnings** for deprecated reference classes (`anchor-tables`, `compile`, `validate`) | #938: `owl:deprecated` on role subclasses is now read |
| **`bi_demand` and `governing_pattern` on gap-sheet rows**; some rows no longer drafted as `deferred` | #942, #938: a column a Power BI model uses is left for a human |
| **`anchor_copy_basis` in `hub.table-anchors.yaml`**, and occasionally a different copy of a duplicated class name | #913: the canonical class registry breaks ties the columns could not |

### Added
- **`analyse-sources` names the tables that open feedback records discuss (#695).**
  After a run, every table the run assigned that an open `HUB-FB-*` record under
  `.import/modeling/feedback/` names is listed with the domain it was just given, for
  example `HUB-FB-…: tms.partyaddress -> party`. A re-run used to contradict a recorded
  human review silently: on one hub it did so in five places. The records are prose, so
  judging whether each assignment agrees is left to the reviewer. The durable override
  remains `integration/discovery/design-rulings.yaml` (DD-192).
- **`kairos-ontology read-document <file>` prints a staged document's text (#907).**
  DD-233 fails `validate` until every file under `.import/businessdiscovery/` has an
  extraction. The toolkit could not open most of them, though: on one hub 20 of 31 were
  `.docx`/`.pptx`/`.xlsx`. `read-document` reads `.pdf`, `.docx`, `.pptx` (including
  speaker notes), `.xlsx`, `.md`, `.txt`, `.csv`, `.xml` and `.htm`, in reading order.
  - Headings are marked (`## Slide 3`, `## Sheet: Rates`) and tables come out as rows, so
    an extraction can cite where a term came from.
  - It says which pages or slides have no text and need reading visually.
  - Legacy `.doc`/`.ppt`/`.xls` get a clear "save as .docx/.pptx/.xlsx" message.
  - The Office readers are in a new `documents` extra: `uv sync --extra documents`. PDF
    needs nothing extra.
- **`.import/drafts/` for staged files that should not be extracted (#907).** Every file
  under `.import/businessdiscovery/` counts as a discovery document and needs an
  extraction. Put an outdated deck or a working copy in `drafts/` instead: nothing reads
  it, and `validate` does not report it. `init` creates the folder, and `update` adds it
  to existing hubs.
- **`owl:deprecated` in the reference models is now read, and reported where a hub builds
  on it (#938).** The reference models mark the role subclasses a normative pattern
  forbids (`Consignee`, `Carrier`, `NotifyParty`, … — 14 in one party module)
  `owl:deprecated true`, and name the replacement in the class comment. Until now the
  only protection was a hardcoded list of seven URIs, so a hub could anchor, subclass or
  bind to one of these classes and see no warning anywhere. Three warnings, all quoting
  the class's own comment:
  - `anchor-tables`: a `deprecated_anchor` note and a `deprecated-anchor` flag on the
    table.
  - `compile`: `binding.target-class-deprecated` when a binding targets a deprecated
    class or a subclass of one.
  - `validate`: `integrity.deprecated-reference-class` when a hub class subclasses, or a
    property's domain or range names, a deprecated class.

  Each points at `blueprints/patterns/qualified-role-assignment`: build on the durable
  identity class and assign the role instead. None of the three blocks.

### Changed
- **One definition of "business document" (#907).** The DD-233 "staged where nothing
  reads it" check now uses the same format list as the discovery readers, so `.xml` and
  `.htm` files staged outside a known folder are reported. They were processed by
  discovery but invisible to the gate. Loose `.txt`/`.csv` files stay unreported, as
  DD-233 intends.
- **Anchoring reads the accelerator's canonical class registry (#913).** When two
  reference classes share a name (`bsp/commercial#TransportLeg`,
  `mmt/consignment#TransportLeg`) and the table's columns do not separate them,
  `anchor-tables` now prefers the copy the pack's
  `current/blueprint/canonical-class-registry.yaml` names as canonical. On one hub the
  wrong copy was chosen, and 33 extension properties were then authored onto it.
  - A table's own columns still take precedence over the registry: they are direct
    evidence about this table.
  - For a duplicated name, the anchor file now records `anchor_copy_basis`, the rule that
    picked the copy.
  - The design skills now say to read the blueprint dossier (canonical registry, overlap
    register, source-shape stress cases) before re-deriving its judgement.
  - A pack without a dossier behaves exactly as before.
- **An abstract class shared by unrelated tables is named as such (#927).** Several code
  lists in one source can legitimately anchor to an abstract "code list element" class.
  The compile gate then demanded a conformance group, which would union unrelated lists
  at different grains. Now:
  - `anchor-tables` reports tables of one system on one class with different key arity,
    and suggests a hub-local subclass per table.
  - When the bindings' keys differ in arity, `conformance.group-required` says the same
    instead of pointing only at conformance.
- **`import-tmdl` proposes `reference_model_match` against the hub's activated modules
  (#863),** the same scope `design-landscape` resolves in. Names duplicated elsewhere in
  the catalog (Shipment, Terminal, Contact) are no longer withheld as ties when only one
  copy is activated. `design-landscape` also accepts `module:Class` in the worksheet
  (`consignment:TransportLeg`), so a genuine tie can be settled by the modeller.
- **Role groups reach the gap-decision sheet, with the governing pattern named (#938).**
  A table carrying three party roles as flattened columns (consignee, shipper, notify:
  name, street, city, zip, …) was ruled one column name at a time. On one hub 78 such
  columns ended up `deferred`, and no command mentioned that
  `blueprints/patterns/qualified-role-assignment` is normative for exactly that shape.
  - `propose-alignment` already detected the role groups for its prompt. It now keeps
    them: the alignment file records `role_groups` per table, and each unmapped member
    carries its `role_group`.
  - On the sheet, such a name or family carries `role_groups` and
    `governing_pattern: blueprints/patterns/qualified-role-assignment`, and its reasoning
    says to model the party once and link it through the module's role-assignment class,
    rather than deciding each attribute on its own.
  - Tables without role groups produce exactly the same files as before.
- **The gap-decision sheet shows which columns an imported Power BI model uses (#942).**
  The DD-169 gate decides which source columns reach Silver, but it never read the BI
  models `import-tmdl` had already recorded. On one hub a sailing date the headline
  weekly report is grained on was auto-deferred like any other timestamp, and the report
  became unbuildable, with no diagnostic anywhere. Now a column whose name a concept
  mapping uses (as a model column, a relationship key, or a column a measure's DAX
  reads) is handled as follows:
  - it carries `bi_demand` on its decision row, naming the model, table and use;
  - it is never drafted as `deferred` or `not-business-data` by a name rule. The rule's
    reading stays in the reasoning, so both are visible;
  - `--accept-proposals` leaves it for a human, counted as `held-for-bi-demand`;
  - `--auto` withholds it from `not-business-data`, through the existing conflict
    mechanism;
  - the AI suggestion prompts are told a report depends on it.

  Matching is by name, ignoring case and separators. It is evidence for a reviewer,
  never a decision.

### Changed (BREAKING for BI import)
- **`import-tmdl` reads Power BI models with the Microsoft TOM SDK, and needs the .NET 8
  SDK (DD-237, #879).** It used to read TMDL with a hand-rolled parser that got flat
  layouts (#874), fenced DAX (#875) and partial exports (#807) wrong. It now uses the
  engine Power BI Desktop and Fabric use. The engineering pack and concept mapping keep
  their shape.
  - **No .NET SDK:** `import-tmdl` fails with the install instruction. There is no
    fallback reader.
  - **An export the SDK refuses** is one Desktop would refuse too, so it is an error,
    not a thin reading. In a batch, a refused model is skipped with a warning and counted
    as partial: `--fail-on-partial` still decides the exit code, and the command fails
    only when every model is refused.
  - **Declared but missing tables** (`ref table` pointers to tables the export lacks)
    are still named, as before.
  - **The first run builds the bundled reader once**, which needs NuGet access.
  - **The parser-vs-SDK cross-check from #901 is removed:** with one reader there is
    nothing to compare. `harvest-gold` still reads the toolkit's own generated TMDL with
    the old parser.

### Fixed
- **Alignment staleness now covers the resolved import closure, not only the activated
  module list (#865).** `design-landscape` reported an alignment as stale only when the
  blueprint added or removed an activated module. Two changes slipped past it: a
  reference-models upgrade that adds an `owl:imports` inside a module, and new classes in
  a module already imported. Both change the class inventory the alignment was built
  from, and both left the file silently stale.
  - `propose-alignment` now also records `resolved_closure_sha256`, a fingerprint of the
    canonical loader's closure hashes for the inventory it aligned against.
  - `design-landscape` recomputes it when the catalog is available, and reports a
    mismatch as "stale against the domain's resolved import closure".
  - An alignment written before this release has no fingerprint, and a check without a
    catalog has nothing to compare, so neither is reported as stale.

### Decisions
- **The insight brief is the report deliverable; the emitted report stays blank (DD-236,
  #830).** `emit-gold` writes a `.Report` with one empty page, only so the project opens in
  Desktop. That is now a decision rather than an unfinished feature. The toolkit will not
  generate pages or visuals, and will not vendor Power BI's visual-container schemas.
  `<product>-insight-brief.md` is what a BI engineer, or Fabric Copilot, builds the report
  from. Build the report as a separate Fabric item bound to the deployed model. The
  `emit-gold` help, the `kairos-design-gold` skill and the Gold how-to now say so.

## [5.22.0rc1] — 2026-09-24

Release candidate for 5.22.0. It includes the 5.21.1rc1 fix (#948) plus the rest of the
September issue review: per-source ledgers, clearer `_analysis/` file names, gates that
passed silently or destroyed data, compile checks on Silver contract quality, and
`validate-dbt` working offline on every adapter.

**What to expect on the first run after upgrading.**

| you will see | why |
|---|---|
| **`update` renames `_analysis/` files** (`tms-affinity.yaml` → `src-tms.affinity.yaml`, `booking-alignment.yaml` → `dom-booking.alignment.yaml`, `table-anchors.yaml` → `hub.table-anchors.yaml`, …) and **splits `table-dispositions.yaml`** into one file per source system | DD-235 and #943. `update --check` lists the changes without making them. Old names are still read for this release, so nothing breaks if you run a command first |
| **`update` reports table-grain dispositions that no longer decide their columns** | #948. A table-grain `deferred` or `bound` stopped answering for its columns in #881, and the gate and `draft-gap-decisions` now agree about that. Decide the columns with `draft-gap-decisions --suggest`, then `--apply` |
| **`build-glossary` refuses to empty a glossary**, and keeps hand-written concepts on rebuild | #906. `--allow-empty` overrides the refusal |
| **`validate` fails on a hub with no ontology yet** if client evidence is staged where nothing reads it | #903. The DD-233 gate now covers that state; the gate was written for it |
| **new warnings**: cross-domain join keys the parent does not emit (`validate`), carried passthrough outnumbering canonical fields (`compile`), `int_merged__` models calling `source()` and `stg_` models joining (`validate-dbt-contracts`) | #934, #854, #949. All warnings, so none blocks an existing hub |

### Added
- **`validate` checks every cross-domain join key against the parent's binding (#934).**
  An `externalReference.key` must name a column the parent *emits*, not a source column
  of the child's binding. `compile` checks this only against the parent's Silver
  contract, and most hubs author none. So a join on a column the parent never emits
  passed `compile --check`, emitted SQL and cleared `audit-silver-samples`, and failed in
  the warehouse. `validate` now derives the parent's columns from its binding (a
  `technicalFields` name, or else the mapped property's snake_case name) and warns on a
  key that is not among them (`relationship.external-reference-key-not-emitted`). Where
  the parent has a Silver contract, `compile` stays the authority.
- **`compile` says when it could not check a join key.** A new info-level note,
  `relationship.external-reference-key-unverified`, replaces the silence when no Silver
  contract declares the parent class. It never blocks.
- **A warning when a Silver model is mostly raw passthrough (#854).**
  `binding.carried-outnumbers-canonical` fires, per binding, when there are more
  `technicalFields` of `purpose: carried` than ontology-backed `fields:`. On one hub the
  ratio was 89 to 82, with columns that looked canonical downstream and were not.
- **`validate-dbt-contracts` enforces the dbt layering rule, as warnings (#949).**
  - `dbt-contract.merge-model-reads-source`: an `int_merged__` model calls `source()`.
  - `dbt-contract.staging-model-joins`: a `stg_` model joins.

  The managed `transforms/dbt/README.md` and the `kairos-develop-dbt-transformation`
  skill now state the three layers as rules, with migration steps: move each source's
  logic into its own `int_<source>__` model and compare Silver row counts and keys
  before and after.

### Changed
- **A handled model-parameter rejection now says it was handled (#911).** When a model
  rejects a parameter such as `temperature`, the toolkit drops or weakens it and retries.
  The only visible output used to be the provider's bare `Error code: 400`, repeated once
  per parallel call, which read as four failures. Now one line per model and parameter
  says the rejection was handled.
- **The scaffolded `release-projections.yml` recognises every pre-release tag spelling
  (#864).** Its pattern missed a bare `…rc` and the PEP 440 forms (`1.0.0b1`, `1.0.0a1`),
  which were published as full releases. `update --refresh-workflows` delivers the fix.
  The previous generation is registered as superseded, so an unmodified copy is replaced.
- **The disposition ledger is one file per source system (#943).**
  `table-dispositions.yaml` held every system's table and column decisions in one file,
  799 KB on one hub. It is now `src-<system>.table-dispositions.yaml`, one per source,
  in the same directory and with the same entry format. Commands read all of them as
  one ledger. The old single file is still read, and the first command that records or
  clears a decision splits it per system. No entry is lost: where both copies hold the
  same key, the per-system one wins, because it was written after the upgrade.
- **`_analysis/` file names now say what they are about (DD-235).** Files under
  `integration/sources/_analysis/` put their scope in the name. Before, you could not
  tell whether `booking-alignment.yaml` was about a source system or an ontology domain.

  | before | after |
  |---|---|
  | `tms-affinity.yaml` | `src-tms.affinity.yaml` |
  | `booking-alignment.yaml` | `dom-booking.alignment.yaml` |
  | `booking-unresolved-anchors.yaml` | `dom-booking.unresolved-anchors.yaml` |
  | `table-anchors.yaml` | `hub.table-anchors.yaml` |
  | `gap-decisions.yaml` | `hub.gap-decisions.yaml` |
  | `affinity-matrix.yaml` | `hub.affinity-matrix.yaml` |

  Commands write the new names and still read the old ones for this minor release; where
  both exist, the new one wins.

### Fixed
- **`validate-dbt` passes offline on dbt-fabric 1.10.1 (#825).** The offline profile used
  service-principal authentication. dbt-fabric turns that into an `Authority Id`
  connection keyword, which the mssql-python driver in dbt-fabric 1.10.1+ rejects before
  connecting ("Unknown keyword 'authority id'"). So the gate could not pass on any
  current dbt-fabric, and hubs were pinned to exactly `dbt-fabric==1.10.0`. The profile
  now supplies an access token instead. Verified against dbt-fabric 1.10.0 and 1.10.1:
  both parse, then fail only at the connection attempt, which reads as
  `environment-blocked`, as the offline gate intends. The pin is now
  `dbt-fabric>=1.10.0,<1.11`; 1.11 needs dbt-core 1.11, which is outside the supported
  range.
- **`validate-dbt` no longer spends 120 s failing on databricks (#922).** dbt-databricks
  connects during `compile`, and its SQL connector retried name resolution 30 times, so
  the phase never finished and was reported as a timeout. The offline profile now makes
  one connection attempt with short timeouts, so compile reaches `environment-blocked`
  in seconds. The host is now a bare hostname: dbt-databricks adds `https://` itself, and
  the old value made its log blame a host named `https`.
- **`build-glossary` no longer destroys a hand-authored glossary (#906).** It used to
  overwrite the target file with whatever the extractions produced. With no extractions
  yet, that was an empty glossary, reported with a green check. With extractions, it
  replaced the file instead of merging: on one hub, 37 of 52 hand-written terms were
  lost. Now:
  - It refuses to write when the build yields no concepts and the file already holds
    some. `--allow-empty` overrides this; it is a registered gate escape, for humans only.
  - A concept a person wrote is carried over and marked (`dcterms:provenance`), so every
    later rebuild keeps it too.
  - Where a hand-written concept and a generated one share an IRI, the hand-written one
    wins.
  - The command reports how many hand-written concepts it kept.
- **`validate` reports staged business evidence on a hub with no domain ontology yet
  (#903).** The DD-233 check sat inside the ontology-validation block, so it said nothing
  in the one state it was written for: sources imported, nothing modelled yet. It now
  always runs.
- **The engineering pack's cross-check note no longer runs into the next heading
  (#905).**
- **The glossary gate declares the evidence it actually reads.** It listed
  `businessdiscovery/glossary/*.ttl`; the check reads `businessdiscovery/*.ttl`.

### Performance
- **Recording many decisions went from minutes to under a second (#943).**
  `draft-gap-decisions --apply` / `--auto` / `--accept-proposals` and
  `source-disposition set --all-tables` used to re-read and re-write the entire ledger
  once per column. 1,113 decisions took about 12 minutes, with no output, so the run
  looked like a hang. They now write each source system's file once per batch, and print
  one line per system as it is written. On a 1,127-entry ledger, 1,113 decisions take
  0.24 s.
- The ledger is parsed and written with PyYAML's C loader and dumper when available,
  about 5× faster for the same result. Output is byte-identical, which a test checks.
  This speeds up every `validate`, `compile` and `generate-bindings`, since each one
  reads the ledger.
- Writes are atomic (a temp file, then a replace), so an interrupted run cannot leave a
  half-written ledger. A ledger file that cannot be parsed is now refused instead of
  silently replaced.

### Notes
- Hubs scaffolded before this release pin `dbt-fabric==1.10.0` in their `pyproject.toml`.
  That keeps working, and they can widen it to `>=1.10.0,<1.11`.
- `update` splits an existing `table-dispositions.yaml` per source system, and
  `update --check` reports the split without doing it. An entry with no `system` cannot
  be placed, so it stays in the old file, which then holds only such entries.
- **`update` renames existing files.** It uses `git mv`, so history follows the file.
  `update --check` lists the renames without making them. If a file exists under both
  names, `update` reports the pair and leaves both alone. Delete the old one once you have
  checked it.
- Scripts or CI that reference the old file names need updating. The skills and the CLI
  reference already use the new names.

## [5.21.1rc1] — 2026-09-24

Release candidate for a 5.21.1 patch. It unblocks hubs upgraded past #881, where `compile` blocked on
columns that `draft-gap-decisions` said were already decided.

### Fixed
- **`draft-gap-decisions` reported nothing to decide while `compile` blocked (#948).**
  Since #881 only a table-grain `not-business-data` or `blueprint-gap` answers for the
  table's columns in the DD-169 gate. The decision sheet and `--auto` were not updated,
  so a hub with table-grain `deferred` or `bound` entries saw the gate block on thousands
  of columns while the one tool meant to clear it said "0 decision(s) to make". The gate,
  the sheet, `--auto` and `--apply` now use one shared rule (`column_decision`), so they
  cannot disagree again.
  - `--apply` writes only the occurrences the sheet listed. An occurrence that already has
    a column decision keeps it, reported as `skipped_already_decided`, where it used to be
    overwritten by the name-level decision.
  - The unanchored-table gate (DD-180) no longer counts a column-grain entry as deciding
    the whole table.
  - `source-disposition set --disposition deferred` on a table no longer says its gap
    columns "now count as DECIDED". That stopped being true in #881; the message now says
    they still need deciding one by one.
- **`source-disposition clear` exists.** Several messages told you to undo an entry with
  it, but the command was never wired up. It filters by `--system`/`--table`, `--column`
  or `--table-grain-only`, `--disposition` and `--decided-by`, supports `--dry-run`, and
  refuses to run with no filter.

### Notes
- `update` and `update --check` now report table-grain `deferred` / `bound` /
  `registered-extension` entries that no longer decide their tables' columns, with the
  number of gap columns affected. This is advisory only and never changes the exit code.
  Decide the columns with `draft-gap-decisions --suggest`, then `--apply`, or withdraw the
  stale entries with `source-disposition clear --table-grain-only --disposition deferred`.

## [5.21.0] — 2026-09-22

### Added
- **`propose-relationships` explains a relationship whose foreign key is on the other
  side.** When an object property runs container-to-contained — `rdfs:domain` on the
  container, `rdfs:range` on the contained side — the container becomes the child and
  there is nothing on it to join with. v5's `cardinality` enum has no `one-to-many`, so
  such an edge is not mis-cardinalitied but unauthorable on the side proposed; the only
  correct entry is the inverse property on the key-carrying binding. The command now
  tries the reverse direction and, when it resolves, names the binding that holds the key,
  the columns that join, and what stands between that and a usable entry:
  - no `owl:inverseOf` declared — declare one and re-run;
  - an inverse declared and usable — author it there, named;
  - an inverse declared whose own `rdfs:domain` excludes the class holding the key — which
    is reported rather than silently failing, because reading the assertion is not enough
    to know the endpoints fit. Observed on a real reference module whose inverse pair does
    not have its domain and range swapped.

  It stops short of emitting an entry for the other side: that needs a property URI, and
  DD-160 §3 is explicit that the object property is read, not guessed.

  Measured before building, as the issue asked: the reverse resolved for none of the
  unresolved proposals on the hub that reported this, and for 3 of 11 on a second hub —
  none of which could be turned into a proposal, for the two distinct reasons above.

  Reported in the text output, in `--format json` as `reverse_join`, and summarised in the
  run's notes.
- **A same-domain relationship may now join on a composite key.** The cross-domain shape
  always could — `externalReference.key` is a list and `target_columns` was built from all
  of it — but the same-domain branch truncated to `relationship.on[0]` and two guards
  rejected the shape before it got there, reporting
  `safety.adapter-unsupported: composite relationship joins are deferred beyond the v5
  first slice`.

  Nothing downstream needed changing: `JoinSpec` already carried a source column per entry
  in `relationship.on`, and the renderer already zipped those against `target_columns`
  with `strict=True` and joined them with `AND`. A two-column join now emits
  `on src.A = parent.A AND src.B = parent.B`, as the cross-domain form always did.

  This matters for any hub whose parent entity has a composite natural key. On the hub
  this was found against, the unit entity could not be related to the leg entity carrying
  its route and sailing date — the leg's key is three columns — so the Power BI volume
  model the hub exists to serve had every ingredient in Silver and no way to join them.

  The join's local columns must still be materialized on the child, by a `fields:` entry
  or a `technicalFields` carrier; that requirement is unchanged and the diagnostic already
  names it.
- **`propose-relationships` checks the target class against the child domain's import
  closure.** A relationship is authored in the child's binding and resolved through the
  child domain's `owl:imports`, so a proposal naming a class that domain cannot see fails
  `compile` with `safety.relationship-endpoint` the moment it is pasted. Such proposals
  are now flagged in the summary, carry `target_resolvable: false` in `--format json`, and
  render with a comment naming what has to be imported first.

### Changed
- **`relationship.unrealized-technical-field` no longer points at a command that may have
  nothing to offer.** The remedy read "Run `kairos-ontology propose-relationships` to
  derive the entry, or keep the carrier deliberately if the parent is not bound yet",
  which is true only when an object property links the two bound classes and a join key
  matches. Measured on two hubs, that is often not the case: of nine warnings on one, five
  named bindings that appear as a child in no proposal at all, and the single genuine hit
  rendered a `<CONFIRM_PROPERTY>` choice rather than a pasteable entry. The causes the
  command cannot resolve are structural — no object property exists between the two bound
  classes, the carrier is polymorphic and can never be one relationship, or the property
  is declared container-to-contained so the key sits on the parent — and none is fixed by
  running it again. The message now says what the command does derive, what it only
  reports, and that keeping the carrier is the right answer in those cases.
- **`generate-bindings` prints why each table was skipped.** Every skip already carried a
  written reason and the summary printed only the count, so a table vanishing between
  `anchor-tables` and `compile` could not be explained without reading the report object
  in a Python shell.
- **A table dropped because anchoring and alignment disagree now says so.** When every
  column the aligner matched sits on a class the anchor is not, the skip reason names the
  anchor, names the class alignment chose, and gives the two available decisions. It
  previously reported "no scalar fields mapped for this table (relationship wiring is
  deferred to propose-relationships)" — which sent one operator after
  `propose-relationships` for a sixty-column party and goods table that had nothing to do
  with relationships.

### Fixed
- **A table you disposition out no longer keeps shipping to Silver.** `generate-bindings`
  already skipped a table the ledger ruled out, but the binding written for it before the
  ruling stayed on disk — and `compile` reads the directory, so the table still compiled
  and still emitted a Silver model, with no warning anywhere. Measured on one hub: a
  generic application-settings table, recorded `not-business-data`, emitting a Silver
  model. `generate-bindings` now retracts that binding and says so; a dry run reports the
  retraction without performing it. `validate` gained
  `disposition.bound-and-ruled-out`, which catches the same contradiction whatever wrote
  the file — previously a bound table returned before the ledger was ever read, so the
  conflict counted as "bound" and passed silently.
- **`scaffold-extensions` no longer renders properties for tables that are out of scope.**
  It walked every anchored table in the domain with no disposition filter. On one hub, two
  ruled-out tables contributed three properties whose `rdfs:domain` pointed at a namespace
  the domain does not import, so `validate` failed an import rule on the strength of
  tables the operator had already removed — and deleting the properties by hand did not
  stick, because the next render produced them again.
- **`generate-bindings --force` no longer destroys an authored `relationships:` block.**
  `propose-relationships` writes nothing, so accepting a proposal means hand-editing a
  generated file — and `--force` is the documented way to pick up a corrected anchor. The
  two collided: regenerating any table in a domain silently discarded every relationship
  authored anywhere in it, and nothing failed afterwards, because a missing relationship
  only downgrades an error to the `relationship.unrealized-technical-field` warning. The
  block is now carried across, counted in the per-row output, and re-validated against the
  regenerated document.
- **`propose-relationships` no longer emits one proposal per property for a single join.**
  A reference model routinely declares a generic relationship and a set of typed
  specialisations of it — a consignment's generic "has party" alongside consignor,
  consignee, carrier, freight forwarder and notify party. All of them link the same two
  classes, so every one matched the same endpoint pair and the same derived join, and each
  was emitted as an independent, equally-confident proposal. They are mutually exclusive:
  one foreign key cannot be the carrier *and* the consignee. Proposals are now grouped by
  the join they share, a property that is an `rdfs:subPropertyOf` descendant of another in
  the group is folded into it, and what remains is reported as one decision. Measured on
  one hub: nine proposals with resolved joins were three distinct joins, and accepting
  them as printed would have asserted five mutually exclusive party roles on one key.
- **A genuine either/or is no longer pasteable as one of its arms.** When the competing
  properties stand in no hierarchy — two directional properties on one non-directional
  column, say — the rendered entry carries `<CONFIRM_PROPERTY>` and lists every candidate
  above it. Naming one would make an arbitrary pick look derived, and a paste that skipped
  the surrounding note would take it.
- **`propose-relationships` now joins on the column the parent actually emits.** The two
  sides of a relationship join are not in the same namespace: the emitted SQL reads the
  child from the raw source CTE (`src.<local>`) and the parent from the built model
  (`ref(parent).<foreign>`). `join.foreign` was derived from the parent's *source* key,
  so every proposal against a parent that renames its key on the way into Silver — the
  normal case, since a mapped field is emitted under the ontology property's name — named
  a column the parent model does not have. Measured on one hub: a proposal joining
  `parent.ACCOUNT_REF` where the parent emits `party_id` and no `ACCOUNT_REF`. It passed
  `compile --check`, emitted, and `audit-silver-samples` reported no errors, because that
  audit is offline and sample-based; it would have failed only when dbt ran.
- **A parent that does not expose its key at all no longer gets a guessed column name.**
  The fallback rendered the source column in snake_case, producing a plausible-looking
  name for a column that does not exist — in a module whose stated contract is to emit a
  sentinel rather than a guess. Such a match now reports `join_resolved: false` with the
  reason, and carries `<CONFIRM_JOIN_COLUMN>` in both `join.foreign` and the
  `externalReference` key.
- **A pasted proposal no longer fails the compiler's key-equality check.** The
  `externalReference` key and `join.foreign` are now derived from the same value, so they
  match exactly, as `safety.relationship-endpoint` requires. Previously the key was
  lowercased independently of the join, and a proposal pasted verbatim — as the command's
  own advisory instructs — could not compile.
- **A same-domain relationship proposal names the parent's source column again.** The
  join-column fix in 5.20.0 made `propose-relationships` emit the parent's *output* column
  for every proposal. That is right for a cross-domain join, where `join.foreign` must
  equal the `externalReference` key and the emitter uses it verbatim — and wrong for a
  same-domain one, where the compiler resolves `join.foreign` against the parent's
  *source* relation and rejects anything else with `safety.column-unresolved`, translating
  it to the output column itself. A same-domain proposal against a parent that renames its
  key on the way into Silver therefore could not be pasted: it named a column the compiler
  would not resolve. Measured on one hub, a proposal read `foreign: internal_location_id`
  where the only accepted value was `locid`.

  Both rules are now stated at the point of decision, each naming the diagnostic that
  enforces it, so the next reader does not have to rediscover that the two shapes differ.
  The existence check is unchanged and still applies to both: a parent key that reaches no
  output column at all is unjoinable whichever shape the join takes.
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

### Performance
- **`compile <domain>` is roughly 2.5x faster.** `_declared_prefixes` stats, reads and
  regex-scans a whole Turtle file on every call, and one domain's plan build called it
  13,464 times against 36 distinct files — each file read about 374 times, over the
  vendored reference-model corpus. That was the largest single entry in the profile,
  ~3.7s of self time in an 11.4s build. The parse is now cached on file identity, taking
  the same build from 8.6s to 3.3s. `compile --all` pays this per domain, so the saving
  multiplies by the domain count.

  Cached on `(path, mtime_ns, size)` rather than path alone, so a file rewritten in the
  same process is re-read and neither a test that edits a fixture nor a long-lived
  process can be served a stale answer. The `stat` that produces the key replaces the
  `is_file()` check the function already made.

## [5.20.0] — 2026-09-20

The output of taking one clean hub end to end — source import through discovery,
anchoring, alignment, the DD-169 gate, domain authoring, binding, and on to an emitted and
validated Silver contract. 5.19.0 fixed the plumbing between stages; this release fixes
what the stages decide.

Eleven defects, every one found by doing the work rather than by reading the code, and
every one measured on a real hub before it was fixed. The pattern they share is worth
naming: **a stage computing an answer its own downstream cannot use, and nothing
objecting.** A grain that changes what a row means. A glossary that loses two thirds of
itself by being linked. A binding generator that emits a type its own compiler rejects,
and another that resurrects tables the hub decided against. Three separate causes
producing one identical error message.

The Silver contract that came out the far end: 3 models, 68 columns, `validate-dbt` clean,
and an offline sample audit with zero errors.

### Added
- **`anchor-tables` reports tables of different grain anchored to one class.** The
  `likely_entity` field has always been persisted so a detector could "detect when tables
  with different candidate entities collapse onto one `ref_class`" — that detector was
  never written. Meanwhile the collapse happens: on one hub a unit-grain table and an
  item-grain table anchored to the same class, and a port-pair table and a multi-leg table
  to another. Nothing objected until `compile` raised `conformance.group-required`, a gate
  that asks the author to declare a **merge** — which for two different grains is exactly
  the wrong remedy and fans out silently once followed. The report says so explicitly.

  Two conditions are required and arity is the discriminator: differing *candidate
  entities* and a differing *number* of natural-key columns. Two systems spelling one key
  differently is not a grain difference, and a false "these are not the same entity"
  invites a re-anchor that is wrong.

- **`anchor-tables` reports replication lanes.** A CDC or data-factory copy exposes the
  same business table plus a watermark; both copies then anchor identically and present as
  a multi-source estate that does not exist. Measured on one hub: eight pairs, 21% of
  anchored tables and 25% of the alignment spend, each contributing a false conformance
  merge. Detection is on column sets, not names — a candidate whose columns are a superset
  of another's within the same system, adding at most three columns, all of them
  operational. The report deliberately does not recommend dropping the replica: a CDC lane
  is often the *more current* copy, so it is a choice, not a cleanup.

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
- **`build-glossary` no longer destroys business terms that share a canonical class.**
  Concepts were grouped by `linked_iri` where one was present (DD-063), which made the
  IRI the concept's *identity* rather than a reference. A glossary exists precisely
  because many business words map onto few canonical classes, so on a real hub sixteen
  party roles — cargo broker, freight forwarder, ship owner, ship manager, charterer and
  others, each with its own authored definition — all legitimately carried the same
  `TradeParty` IRI, collapsed into one concept labelled with whichever was processed
  last, and the other fifteen were discarded without even becoming `skos:altLabel`. The
  glossary went from **164 concepts to 82 by adding the links the
  `kairos-design-discovery` skill instructs**, so the safe action and the documented
  action were opposites.

  Grouping is now always by normalized `prefLabel`, and `linked_iri` is carried as the
  cross-reference it is — several concepts pointing at one class is what `rdfs:seeAlso`
  means. Synonyms remain `altLabel`'s job, and the same term recorded in two documents
  still merges. DD-063 is amended accordingly.

  **On your next `build-glossary` run** a hub will see more concepts wherever terms had
  been silently merged, and local names derived from the label rather than the IRI
  fragment. A hand-authored glossary was never affected — only the generator collapsed
  terms.
- **A system-versioning column no longer becomes part of an entity's identity.**
  `anchor-tables` put operational columns in `grain_columns` — on one real hub it proposed
  `natural_key: [KLMEMO, SETNR]` and `grain_columns: [KLMEMO, SETNR, ttSysStartTime]` —
  and `generate-bindings` turns every grain column into a `purpose: identity` technical
  field. Five of seven generated bindings carried a SQL Server row-validity timestamp as
  part of identity, which silently changes the Silver grain from *one row per consignment*
  to *one row per consignment per version*: counts become version counts, uniqueness tests
  pass that should fail, and a join on the entity fans out.

  The grain is now filtered with the toolkit's own `_is_operational_column` predicate,
  conservatively: a column the model itself placed in `natural_key` is never dropped, and
  the grain is never emptied — a table with no grain is not a safer answer than one with a
  questionable grain.

- **`generate-bindings` no longer emits bindings its own compiler rejects.** Identity
  technical fields were typed `string` unconditionally, because the alignment only carries
  a type for columns it *mapped* and an identity column is often one it did not. `compile`
  then failed with `technical-field.type-incompatible`. The physical type is now read from
  the source vocabulary — the same place the compiler reads it from — when neither the
  profile nor the alignment knows it.
- **`generate-bindings` honours table-grain dispositions.** It loaded the ledger and used
  only the column-grain half, so a table recorded as `not-business-data`, `blueprint-gap`
  or `deferred` had a binding generated for it anyway. Since `--force` is the documented
  way to pick up a corrected anchor, every legitimate regeneration silently undid every
  table-grain decision a hub had made — nine tables on one hub, eight of them replicas
  whose bindings had produced the false merge the dispositions were recorded to resolve.
  That made the decisions look ineffective rather than ignored.

  `bound` deliberately does not skip: it asserts a binding *exists*. An explicit `--table`
  still generates, so one dispositioned table can be regenerated without clearing the
  ledger.
- **A hub-local property can no longer be proposed with a type the compiler cannot emit.**
  `propose-alignment` asked the model for `"range": "<xsd type or class name>"` with no
  constraint, so it reasonably proposed `xsd:duration` for a duration column. That was
  accepted into the disposition ledger, rendered into the domain ontology by
  `scaffold-extensions`, passed `validate` clean, and failed three stages later at
  `compile` with `mapping.invalid-output-type` — after a human had already accepted it.

  The prompt now names the fifteen datatype ranges the compiler can emit and says to
  express a duration as a number with its unit in the rationale.

  `scaffold-extensions`' allow-list was hand-maintained beside the compiler's own XSD
  table and had drifted from it in both directions: it permitted `xsd:duration`, which has
  no canonical output type, and omitted `xsd:int`, `xsd:short`, `xsd:token` and
  `xsd:normalizedString`, which the compiler supports. It is now derived from that table,
  so the two cannot disagree, and a datatype the compiler cannot emit is reported as its
  own skip reason — distinct from a non-datatype range, and differently actionable: the
  modelling is fine, the type is not buildable.

## [5.19.0] — 2026-09-20

The output of one adversarial dogfood session against a real client hub, run end to end from
source import to a validated Silver contract. Sixteen defects found, fifteen fixed; the one
left open is a product decision about whether the Microsoft TOM SDK should replace the
hand-rolled TMDL parser, which would make the .NET SDK a prerequisite for BI import.

The session started from a complaint that a hub's Silver contract was far thinner than its source
system warranted, despite a large archetype ontology behind it. It was not a modelling failure.
It was five places where each stage computed the right answer and the next could not see it: the
BI import produced nothing usable, the gap sheet dropped the drafted property through one wrong
dictionary key, a table-grain `deferred` silently retired 1,643 columns from the pre-binding
gate, the disposition ledger flattened structured decisions into prose, and the binding generator
excluded every hub-local property from its candidate pool.

Measured on that hub after the fixes: **29 → 81 Silver columns**, **1 → 74 binding fields**, 701
column-grain gate decisions where there had been none, and `dbt deps` passing for the first time.

Two architectural decisions came out of it. **DD-233** makes staged client evidence that nothing
has consumed a `validate` failure — the input the pipeline cannot re-derive for itself is the one
it was silently ignoring. **DD-234** states what a gate *is*: it declares the evidence it reads,
absent evidence fails it rather than satisfying it, a gate that cannot run has not passed, and
every escape hatch is classified by which enforcement modes may use it and recorded in the
artifact it produced.

### Added
- **`anchor-tables` reports what moved since the last run.** Anchoring is not reproducible
  at the prompt size it operates at — DD-177 recorded that for a 23 KB alignment prompt,
  and this one is 121 KB. Measured back to back on a real hub, with the prompt
  byte-identical across processes and the same seed sent and honoured: the anchor class
  moved on 12 of 39 tables, the natural key on 13, two tables were given entirely disjoint
  keys, and one was anchored in one run and unanchored in the next. Provider-side
  determinism is not on offer at that size, so the defect was never the movement — it was
  that a re-run overwrote every unpinned row in silence. DD-190 built sticky review
  statuses on the premise that review effort concentrates where it belongs, without ever
  saying where that is. The diff now names it: which tables moved, in which fields, with
  both values, and a separate note for `natural_key`, which is not an advisory label but
  the binding's identity and the silver contract's uniqueness test. Written to the console
  and into the artifact, so it survives the terminal that produced it. A first run reports
  nothing; an unchanged re-run says so.
- **`import-tmdl` cross-checks its reading against the Microsoft TOM SDK.** The toolkit
  already bundled the real SDK, but only on the write path, where it checks that TMDL the
  toolkit *generated* will open. It now points the same engine — the one Power BI Desktop
  and Fabric use — at the export being imported, and reports where the two readings
  differ: tables the SDK reads and the import did not, measures or columns read short,
  and exports the SDK rejects outright.

  Advisory and automatic: it runs whenever `dotnet` is on PATH, is silently skipped
  otherwise, and never blocks an import. A disagreement is written into the engineering
  pack above the inventory it qualifies, not only logged, because the operator who needs
  it is the one opening the pack later and wondering why it is thinner than the report
  they remember.

  Measured against two real Power BI exports: one agreed exactly (7 tables, 48 columns,
  59 measures, 6 relationships), and one was rejected by the engine as unopenable —
  where the parser had reported a well-formed model with zero tables and thirty-three
  relationships, which nothing downstream can distinguish from a model that genuinely
  has none.

  This is option 3 of the three in the issue. It does not settle whether the SDK should
  *replace* the hand-rolled parser, which is a product call about making `dotnet` a
  prerequisite for BI import; it does start producing the evidence that call needs.

- **The bundled TMDL validator reports an inventory, not just a table count.** Table
  names with their column and measure counts, plus the relationship count, so a
  disagreement can name what is missing rather than only that something is.
- **A `registered-extension` decision now records *which* property it commits to.** The
  hub-local property `propose-alignment` drafts for an unmappable column — its name,
  range, owning class and rationale — reached the disposition ledger only as a sentence
  inside `rationale`, so the one stage that could act on it would have had to parse
  English. Ledger entries now carry a structured `proposed_property` alongside the prose.
  Where the aligner read one column name two different ways across tables, neither draft
  is recorded: the reviewer was asked to pick, and guessing on their behalf is the
  failure this avoids.
- **`scaffold-extensions` renders the accepted `registered-extension` decisions as draft
  OWL.** Closing the DD-169 gate honestly is expensive — on one hub, 701 column-grain
  decisions, 501 of them accepting a hub-local property the aligner had already drafted
  in full — and nothing consumed them. The disposition's own definition points at
  `register-concept`, which registers a *class* the archetype catalog lacks, while these
  are *columns* wanting *properties* on classes that already exist, so the properties had
  to be re-derived by hand from a second file. The new command writes what the ledger
  already records: name, range, owning class and rationale, one declaration per property,
  grouped by class. It makes no judgement of its own. Output is a DRAFT written outside
  `model/ontologies/` so the validator does not load it, the same contract
  `suggest-shapes` uses (DD-076). A non-datatype range, a non-camelCase name, or one name
  accepted with two different class or range readings is reported and skipped rather than
  guessed, and no source-system, table or column name reaches an `rdfs:comment`, which
  `validate --syntax` rejects.
- **Generated artifacts record which business glossary they were grounded in, and a
  changed glossary is reported.** `*-alignment.yaml` already fingerprinted its affinity
  input and its resolved import closure so either going stale was visible; the glossary
  was the one input nothing recorded — and it is the one a human maintains between runs,
  so it is the one most likely to move underneath an artifact built from it.
  `table-anchors.yaml` and `*-alignment.yaml` now carry `glossary_sha256`, digested over
  the `(prefLabel, definition)` pairs that actually reach a prompt, so adding a term or
  correcting a definition is drift while reformatting the Turtle is not. A literal
  `"none"` records a run that had no glossary in scope — the `--without-discovery`
  escape, previously visible only on the terminal that produced it.
  `kairos-ontology next` reports artifacts grounded in an older vocabulary.
- **The autopilot has a second Stage 0 pre-flight: business discovery.** It stops on a
  missing glossary, on DD-233 findings, and on glossary drift, and may never pass
  `--without-discovery` — that flag is a deliberate human escape. A run that proceeded
  without business discovery carries **BLOCKED** in its transparency report, for the same
  reason a skipped LLM judgment step does.
- **`kairos-ontology gates` lists every gate, the evidence it reads, and the flag that
  bypasses it (DD-234).** Until now the only way to find out what could block the
  pipeline, and what could get past it, was to read sixteen `click.option` declarations
  across eight CLI files. One of them — a fourth `--degraded`, on `resolve-ontology` —
  had no help text at all, and was found only by the AST scan written for this change.
- **Enforcement modes: `--mode interactive|autopilot|ci`, or `KAIROS_MODE`.** The modes
  differ in one thing — whether an escape flag that downgrades the result is accepted —
  and the difference is about who is watching, not about how important the check is. In
  `autopilot` and `ci` the flag is refused at parse time, before the command body runs,
  with a message naming the gate and the human decision it needs. `interactive` is the
  default and every current behaviour is unchanged.
- **Artifacts record how they were enforced.** `*-alignment.yaml` and `table-anchors.yaml`
  produced under an escape carry an `enforcement:` block naming the mode and the flags.
  A file written with `--without-discovery` was otherwise indistinguishable afterwards
  from a grounded one — the flag was printed to a terminal and written into nothing. The
  block is emitted only when there is something to say, so a clean run's output is
  byte-identical to what the previous version wrote.
- **`.import/powerbi/` is scaffolded, and staged business evidence nothing consumed now
  fails `validate` (DD-233).** `.import/` holds the two inputs the pipeline cannot
  re-derive for itself: the client's own documents and their Power BI models. Nothing
  checked that any of it was used. `discovery-status` reported on
  `.import/businessdiscovery/` alone and said "nothing to check" for an empty directory,
  which reads identically whether the client sent no documents or sent thirty to a
  directory no command looks in — and there was no scaffolded home for a Power BI export
  at all, so hubs invented one and every command then failed to find it. `init` and
  `new-repo` now create `.import/powerbi/` with a README covering both export shapes, and
  `validate` reports three kinds of unused evidence as blocking errors: a discovery
  document with no extraction, a Power BI export with no engineering pack, and a business
  document filed outside every directory a command reads. `--degraded` downgrades them to
  warnings.

### Changed
- **`draft-gap-decisions --suggest` now characterises the single names too, not only the
  families.** It read `sheet["families"]` and nothing else, and families are formed by
  shared name tokens — so a column whose name shares no token with another was a
  singleton forever and no model call ever considered it. On one real hub that was the
  overwhelming majority: 7 families covering 64 of 357 distinct names, and 293 singletons
  left with a deterministic reasoning line and no proposal. Those are also the harder
  ones, since token grouping had already solved the easy case. Only names with no
  rule-based proposal are sent, so a deterministic answer is never second-guessed; the
  aligner's drafted property is offered as evidence where one exists; large lists are
  batched rather than truncated; and an empty disposition remains a valid answer, because
  "this is an opaque legacy abbreviation" beats a guess. As with families, it fills
  `proposed_disposition` and `reasoning` and never `decision`.
- **`source-disposition set` now says what a table-grain decision just retired.** A
  disposition recorded against a whole table removes every one of its gap columns from
  the DD-169 pre-binding gate, permanently — and the command said only
  `✓ <table> recorded as 'deferred'`. The cascade appeared in one place, the help text
  for the `--column` flag, phrased as a convenience rather than a consequence, which
  nobody recording forty tables ever reads. Recording a disposition now reports the real
  column count: informational for `not-business-data` and `blueprint-gap`, where
  retiring the columns is the point, and a warning for the rest — `deferred` means "in
  scope, not modelled yet", which is precisely the state the gate exists to keep raising,
  and it had the widest blast radius of any option while sounding the mildest. Disposing
  of a table alignment has never covered warns too, because that decision answers for
  columns nothing has yet looked at. The `--disposition` help text spells out which
  values cascade and why.
- **`kairos-design-domain` now points at the gap decisions, not only at the alignment
  files.** The skill sent an author to `*-alignment.yaml` for drafted properties, which
  holds one for *every* unmappable column — including the ones a reviewer has since ruled
  out. Which were accepted lives in `gap-decisions.yaml` and the disposition ledger, and
  the skill never mentioned either, so a column dispositioned `deferred` or
  `not-business-data` could be modelled anyway, re-opening a decision someone had already
  made. The skill now names both files, says to design against the ledger, and points at
  `scaffold-extensions` for rendering the accepted ones as a reviewable diff.
- **`anchor-tables` now requires an authored business glossary, like `propose-alignment`
  already did.** Anchoring decides what every source table *is* — its class, domain,
  grain and natural key — in one global call that everything downstream inherits, and it
  ran with no business-discovery prerequisite at all. The check `propose-alignment` has
  carried for some time is now shared by both commands, with the same
  `--without-discovery` escape and the same warning when it is used: blocking rather than
  warning, because a warning about ungrounded input is read after the expensive call has
  already been paid for.
- **The gap gate's disposition evaluation now sees the business's own vocabulary.**
  `draft-gap-decisions --suggest` asks the model to name the concept a family of unmapped
  columns represents, and had no access to the authored glossary — so it named concepts
  from column spellings while the client's own term for the same thing sat unused in the
  same hub. The glossary now goes into that prompt with a definition per term, and a term
  that matches is treated as evidence the concept is real and in scope, favouring
  `registered-extension` over `deferred`. New `load_glossary_entries()` returns
  `(prefLabel, definition)` pairs: a label is enough to *reuse* a term, and only the
  definition is enough to *recognise* one.

### Fixed
- **`import-tmdl` now reads a flat TMDL export, and names each export after its own model.**
  A Power BI export saved without the `definition/` wrapper drops every `<table>.tmdl` flat
  beside `model.tmdl`. The parser only ever looked in `definition/tables/`, so it read zero
  tables and reported every table the model declares as "absent from this export" — advice
  that could not be followed, because the files were in the folder it was pointed at. The
  engineering pack and concept-mapping worksheet came out empty, and `design-landscape`'s
  `bi_weight` and `draft-model-report` consumed nothing. A second defect compounded it: a
  flat export was named after its *parent* directory, so every export staged in one folder
  produced `<staging>-engineering-pack.md` and `<staging>-concept-mapping.yaml` and each
  import silently overwrote the last. Both layouts are now read, and an export names itself.
  Exports that genuinely omit table definitions still report them, unchanged.
- **The Engineering Pack shows what a measure actually computes again.** TMDL wraps a
  multi-line DAX expression in a ``` fence, and the parser stored the fence markers as
  part of the expression. The pack previews a measure from the first line of its
  expression — which was the fence — so every multi-line measure rendered as an empty
  code fence and nothing else: on one real model, 53 of 59 measures listed a name and no
  definition. Fenced expressions are now read to their closing delimiter and dedented,
  so the DAX keeps its indentation and blank lines, and the concept-mapping worksheet no
  longer carries fence markers inside each `expression:` value. Reading to an explicit
  delimiter also removes a latent truncation, where a DAX line resembling a measure
  property would cut the expression short.
- **A structurally broken Power BI model now fails TMDL validation instead of reporting
  as unvalidatable.** The bundled TOM validator treated every exception except
  `TmdlFormatException` as "the SDK could not run here". But `TmdlSerializationException`
  is raised about the *content* — a relationship endpoint pointing at a table or column
  the model does not contain — and that is exactly the defect that makes Power BI Desktop
  refuse to open a PBIP. Because `emit-gold` only fails on `status == "fail"`, such a
  model emitted green with its diagnostic printed as a parenthetical aside worded
  identically to "you don't have the .NET SDK installed". Serialization failures are now
  reported as validation failures; genuine environment problems still report as
  unavailable.
- **`update` no longer uninstalls the optional extras the hub runs on.** Every
  `update --upgrade`, `--test-ref` and `--restore` ran a bare `uv sync`, which installs
  the default dependency set and removes everything outside it — so a hub configured
  against Azure Foundry lost its provider SDK on every upgrade and the next
  `anchor-tables` or `propose-alignment` died on a missing package nobody removed. The
  extras a hub is actually running on are now detected before the sync (an extra counts
  as active when every distribution it requires is installed, resolving
  `kairos-ontology-toolkit[foundry]` through the toolkit's own metadata) and re-passed as
  `--extra` flags. This covers the Windows path too, where the only sync that runs is the
  one in the scheduled background refresh.
- **Ingestion-framework columns are auto-dispositioned instead of reaching the gap gate
  as business data.** `_rescued_data`, `_corrupt_record`, `ts_ms`, a SQL Server temporal
  period's `ttSys…` bounds and a stray pandas `__index_level_0__` are written by the tool
  that loaded the table, never by the business — but nothing recognised them, so they
  arrived as undecided gap columns and the recurrence heuristic proposed `blueprint-gap`
  for one of them, the disposition that asserts a reference-model defect to file
  upstream. They are matched as adjacent token pairs, because "rescued", "record",
  "index" and "ts" all occur in real business names and this classification silences a
  column without review. The pairs are shared between the classification and the
  cross-check that guards it, so the invariant that every operational name is also
  audit-named now holds by construction.
- **The gap decision sheet now shows the extension property alignment already drafted,
  and proposes registering it.** `propose-alignment` drafts a full hub-local property —
  name, range, owning class and rationale — for every column it cannot map.
  `draft-gap-decisions` read those proposals under the wrong key (`suggested_property`,
  which belongs to a sibling field, rather than `name`), so the list came back empty for
  every group and the drafted property never reached the sheet. A reviewer therefore
  faced a blank `decision:` with no proposal, while the answer sat in the alignment file
  next door. On a five-domain hub slice that was 371 of 373 entries with no proposal at
  all; it is now 188, with 183 drafted as `registered-extension` and the property spelled
  out in the reasoning. Where the aligner read the same column name differently in
  different tables, both readings are shown and the entry says to pick one — never
  averaged. A proposal is still never a decision: `decision` stays empty, and the
  existing rule branches (JSON blob, free text, recurring identifier) keep precedence
  over the extension proposal while still showing what was drafted.
- **The gap gate groups `ADDRESS1..3` the way it already grouped `ADDRESS_1..3`.** Family
  grouping split column names on separators and camel boundaries but not on a
  letter-to-digit boundary, so a numbered repeating group collapsed into one decision
  only when the legacy schema happened to separate the index. On one hub that meant a
  14-slot repeating group arrived as fourteen separate decisions about one concept while
  an underscore-separated pair beside it arrived as one. A trailing digit run is now read
  as an index — narrowly, so that a standard's number (`ISO6346`), a short code (`A1`)
  and digits inside a name (`CO2EMISSIONS`) are left alone, and the existing coherence
  guards still apply.
- **A glossary term now reaches the prompts where it is relevant, not only where it
  happens to share a word.** Terms were filtered to those sharing a token with the
  table's own name or columns. That is self-defeating on the schemas that need it most: a
  glossary is written in business English and a legacy schema's columns are
  abbreviations, so the two share no tokens *by construction* — which is exactly the gap
  the glossary exists to bridge. Measured on one hub, 39 of 52 authored terms never
  reached a single prompt. A concept's `rdfs:seeAlso` names the reference class the
  business's term corresponds to, so a term whose class is in the table's candidate pool
  is now relevant however it is spelled; reach went from 13 to 35 of 52 terms, and a
  cargo table from 4 to 8. The audited noise case still holds — a vessel term stays out
  of a companies-table prompt, because its class is not in that pool.
- **`anchor-tables` sees the vocabulary at all.** It decides what every table *is* and
  everything downstream inherits that, while the one input naming which class each
  business concept corresponds to was never in its prompt. The 43 concepts carrying an
  `rdfs:seeAlso` are now rendered as evidence, explicitly not as an instruction. Terms
  with no class attached are left out: they are vocabulary for naming, not evidence for
  anchoring.
- **`discovery-status` no longer answers "nothing to check" when there is.** It read
  `.import/businessdiscovery/` alone, so on a hub holding thirty client documents filed
  one directory across it printed `(no discovery documents found — nothing to check)` —
  a sentence that sounded like an answer and stopped anyone looking further. When that
  directory is empty it now scans the rest of `.import/`, names the business documents
  staged where nothing reads them, and says where to move them. The DD-233 gate already
  blocked `validate` on this; the command a human runs to ask *what evidence do I have*
  should not have been the one saying "none".
- **`compile` no longer passes the DD-169 and DD-180 gates on evidence it could not
  read.** Both are built on `build_alignment_report`, which degrades gracefully by
  design — an unreadable file is skipped, an absent directory yields nothing — so "no
  findings" and "nothing was read" reached the gate indistinguishable. Measured on a real
  hub, varying only the readability of the input: healthy, 661 undecided columns; one
  `*-alignment.yaml` malformed, 405, with 256 columns silently gone; `_analysis/`
  deleted, **0, and the gate passed clean**. No exception was raised in any of the three.
  `compile` now reports `alignment.evidence-missing` and blocks. Scoped to hubs that have
  imported sources, so a hub with nothing to align is unaffected.
- **A gate that crashes no longer reports as a gate that passed.** The DD-169 and DD-180
  guards were wrapped in `except Exception: ... = []` so a broken guard could not break an
  unrelated compile. The intent was sound; the effect was that a gate whose failure mode
  is *pass* is an advisory with a strict-sounding name. Both now return
  `gate.evaluation-failed`, naming the gate and carrying the exception so a toolkit defect
  is distinguishable from a malformed hub file.
- **`resolve-ontology --degraded` is documented.** It had no help text, so the one
  undocumented escape in the CLI is now described where an operator meets it.
- **Hub-local extension properties reach the binding candidate pool again.**
  `hub_local_properties` read the property IRI from a `uri` key; `SemanticIndex` names it
  `property_uri`. The lookup therefore returned nothing at all, however correctly a hub
  had authored its properties — a 155-column table dropped from 74 mapped fields back to
  1, silently. Introduced when the function moved onto the DD-103 canonical loader, and
  invisible because every other test of the binding generator mocks it. Object properties
  are now excluded too: they need a relationship entry, not a scalar field.
- **A column the aligner put on another class is now reported as a decision, not counted
  as a missing property.** `generate-bindings` resolves properties against the anchor
  class's own inventory, so a column mapped to `Weight.weightValue` on a table anchored
  to `CargoItem` failed that lookup and was counted under "did not resolve in the anchor's
  module inventory" — the same bucket as a property that does not exist anywhere. On one
  real hub that was 18 of 25 mapped columns, silently absent from the binding and
  indistinguishable from a lookup failure. Binding them onto the anchor would have been
  worse: putting a weight value on a cargo-item row is a grain error dressed as coverage,
  and DD-190 is explicit that a same-grain cluster is properties of the primary. They now
  land on the secondary-entity worklist with the decision spelled out — a secondary entity
  at its own grain, or a hub-local property on the anchor — and the command says they are
  not in the binding.
- **`registered-extension`'s own documentation no longer points at a command that cannot
  serve it.** It named `register-concept`, which mints a *class* and rejects a URI the
  catalog already has; at column grain the decision is a hub-local *property* on an
  existing class, drafted by `scaffold-extensions`. Pointing at the wrong command is what
  left 501 such decisions with no consumer.
- **The emitted dbt project parses again.** `dbt_project.yml` carried
  `require-dbt-version: '>=1.10'`, which dbt's own semver rejects — it requires all three
  version components, so dbt refused the whole project file with `">=1.10" is not a valid
  semantic version` before reading anything else, and `dbt deps` failed on every emitted
  medallion project. A two-part specifier is valid for pip and not for dbt; the floor is
  now spelled `>=1.10.0`, which is the same range. Regression tests assert three-part
  spelling for both the emitted floor and the scaffolded requirement, and check them
  against dbt's parser where dbt is installed.
- **`draft-gap-decisions --suggest` no longer crashes on a hub whose gap gate is fully
  closed.** Its early-exit path returned a narrower dict than its success path, and the
  CLI read both keys, so the command raised `KeyError: 'flagged_incoherent'` exactly when
  there was nothing left to suggest — that is, when every gap column had been decided and
  the DD-169 gate was satisfied. It now reports "nothing left to describe — every gap
  column is decided".

### Fixed (BREAKING for hubs that used table-grain `deferred`)
- **A table-grain disposition now answers for the table's columns only when it says
  something about them.** Recording any disposition against a whole table used to retire
  every one of its gap columns from the DD-169 pre-binding gate, whatever the disposition
  said. That reasoning holds for `not-business-data` (the table is not business data, so
  neither are its columns) and `blueprint-gap` (a claim about the reference model is a
  claim about what the columns needed). It does not hold for the other three, and those
  were the damaging omissions: `deferred` means "in scope, not modelled yet" — precisely
  the state the gate exists to keep raising — while `bound` and `registered-extension`
  assert the table *is* being modelled, which is when the gate matters most. On one real
  hub, 40 table-grain `deferred` records retired 1,643 columns and the gate never fired.
- **`bound` is no longer recordable as a table-grain disposition.** The DD-164 audit
  reads it from `integration/bindings/` before it consults the ledger, so authoring the
  EntityBinding is what states it; a ledger row claiming it satisfied the audit with no
  binding anywhere. Still recordable for a single column.
- `next` no longer suggests "bound to a domain" as a ledger value — it says to author the
  binding, which satisfies DD-164 on its own.

  **Upgrading:** a hub that cleared the gate with table-grain `deferred`, `bound` or
  `registered-extension` will see those columns re-enter the DD-169 gate and `compile`
  will block until each is decided. That is the omission the gate existed to catch.
  `kairos-ontology draft-gap-decisions --suggest` drafts them in bulk.

## [5.18.0] — 2026-09-20

General availability of the 5.18 line. Everything under `5.18.0rc1`, `rc2` and `rc3` below is
part of this release; the entries in this section are what landed after rc3 — the DDD
architecture layer for the context engineer (DD-229 to DD-232) and the ELK diagram layout.

### Added
- **`project --target ddd` now draws bounded contexts hub-wide (DD-230, closes #846).** Under
  `ontology-hub-publish/architecture/ddd/contexts/`: `context-map.mmd` (every context and every
  relationship, whichever file declared it, border styled by subdomain type), `all-contexts.mmd`
  (one `classDiagram`, one `namespace` per context — the subject-area view), one `{context}.mmd`
  per non-empty context with neighbours as stubs, and `design-notes.md` (per context: subdomain,
  classes, Silver status, invariants, language, design notes; then every hub class no context
  claims). Membership is annotation-gated, so the import closure never floods a namespace;
  namespace ids come from the context IRI, never the label. Same target, same tracked lane, no
  workflow or gitignore change — a hub on rc3 gets the files on its next toolkit bump.
- **Silver status inside the architecture.** Each class in a context diagram and in
  `design-notes.md` is marked *in Silver contract*, *bound (no contract)* or *not in Silver*, read
  from the authored `model/contracts/*.contract.yaml` and `integration/bindings/*.yaml` — never from
  a CompilePlan. Silver is a subset of the architecture by construction; now it is visible.
- **One hub-wide strategic DDD file, `model/extensions/ddd-contexts-ext.ttl` (DD-229, #846).**
  Bounded contexts and the context map are declared once for the whole hub and referenced by
  IRI from the per-domain `{domain}-ddd-ext.ttl` overlays, which now carry tactical design only.
  `validate --ddd` validates the strategic file on its own, merges it into every overlay's
  validation graph, and adds a hub-wide consistency audit that per-domain SHACL could not do:
  `ddd.context-redeclared` (warning), `ddd.context-label-conflict`, `ddd.class-in-two-contexts`
  and `ddd.tactical-in-strategic-file` (errors). A hub that still declares its contexts inside
  each overlay validates as before and is told what to move.
- **`kairos-ddd` vocabulary 1.1.0.** `kairos-ddd:subdomainType` classifies a context as
  `CoreDomain`, `SupportingSubdomain` or `GenericSubdomain`; `kairos-ddd:invariant` records an
  aggregate's business rules as repeatable prose beside its class. Overlays may also carry
  `skos:scopeNote`, `skos:example` and `skos:altLabel` on class and property IRIs — the
  context-specific language, which never redefines the canonical `rdfs:label`/`rdfs:comment`.
- **Four new overlay shapes.** A `boundedContext` value must be a declared context (a typo used
  to render as a new unlabelled box); an element belongs to at most one context;
  `subdomainType` is closed; a context relationship joins two different contexts.
- **A class-level disposition ledger, `integration/discovery/class-dispositions.yaml` (DD-231,
  closes #847).** The class-side sibling of the source-table ledger: an `owl:Class` no
  EntityBinding targets never enters the plan — correct — but "not bound yet, deliberately,
  because X" had nowhere to live, so a context engineer's logical model in the ontology looked
  forgotten. `kairos-ontology class-disposition set --class <IRI or prefix:Local> --disposition
  deferred|architecture-only|abstract --rationale "..."` records the decision; `list
  [--undecided]`, `clear` and `init` complete the surface. `bound` and `bound-via-subclass` are
  derived from the bindings, never authored. **Adoption is opt-in, then binding:** until the hub
  creates the ledger (`init`, or the first `set`) `validate` reports undecided classes as
  warnings, so no existing hub goes red on upgrade; afterwards an undecided class is an error,
  degradable with `--degraded` like DD-164. A malformed ledger is itself the error, never read as
  empty; `decided_by` is closed in core; a disposition left behind on a class that a binding now
  targets is reported as `class-disposition.stale`.
- **The hub's ubiquitous language and concept guide, generated by `project --target ddd`
  (DD-232).** `architecture/ddd/ubiquitous-language.ttl` is a SKOS vocabulary with one concept per
  class the hub declares — `skos:exactMatch` to the class IRI, `skos:broadMatch` to its
  reference-model superclasses, the canonical label and definition, synonyms from the DDD overlay
  and the discovery glossary, context-specific scope notes and examples, source names as hidden
  labels, and the Silver status (and DD-231 disposition) as an editorial note — grouped in one
  `skos:Collection` per bounded context, or per domain for a hub without a DDD design.
  `architecture/ddd/concept-guide.md` is its human-readable counterpart: the "three names, one
  concept" rule, every concept described in its context, the relationship reference (*(realised)*
  where a binding realises the edge), the concept-mapping table, and the discovery-glossary links
  that have gone stale. Both are derived on every run, deterministic and timestamp-free, and are
  emitted for **every** hub with a class; `git add` them with the upgrade. Sample values are
  **off by default** — the import step's redacted `kairos-bronze:sampleValues` can still carry
  personal data and the lane is tracked — and are switched on per hub with
  `projections.concept_guide.samples: true` (`max_samples`, default 3) in `kairos.yaml`.
- **`kairos-design-architecture`, the context engineer's skill.** Author the strategic file and
  the per-domain overlays (contexts, context map, aggregates, invariants, scope notes, synonyms,
  examples), record why a class is deliberately not in Silver, validate with `--ddd`, regenerate
  the context diagrams, the ubiquitous language and the concept guide, and review them with the
  SMEs. Shipped to every hub. `kairos-ontology next` / `kairos-flow` route two new actions to it:
  `design-architecture` (optional, when an overlay or the strategic file exists) and
  `record-class-disposition` (a human call per undecided hub class; blocking once the class
  ledger is adopted). `next` schema version 8.

### Changed
- **The per-domain `{domain}-context-map.mmd` is retired.** It rendered only the edges its own
  overlay declared, so every other domain's map read as empty. The first `project --target ddd`
  after upgrading removes the old files and writes `contexts/**` plus a
  `.kairos-projection-manifest.json` that reconciles the `ddd` output directory to the run's files
  (a renamed context no longer leaves its diagram behind, #861 for `ddd`). **`git add` the new
  files with the upgrade**: the drift gate diffs tracked paths and does not see untracked
  additions. The manifest is written only for hubs with DDD output.
- **`project --target ddd` per-domain reports show the contexts a domain participates in**, with
  their subdomain type, the edges touching them, and a new `## Invariants` section, instead of
  whatever the one overlay happened to declare. The hub-wide map follows in DD-230.
- **Every generated Mermaid diagram now selects the ELK layout engine (#855).** Canonical and
  master class diagrams, DDD maps, declared-contract ERDs, and the bound Silver and Gold ERDs
  and their masters all open with four lines of frontmatter (`layout: elk`) ahead of the
  `%% Generated by kairos-ontology` stamp. ELK routes edges orthogonally and clusters the stub
  nodes every ERD family draws outside its main group, where Mermaid's default dagre scatters
  them across the canvas. Renderers without ELK registered (GitHub, Azure DevOps wikis) log a
  warning and draw the dagre layout they drew before; `mmdc` and the VS Code Mermaid Chart
  extension render ELK. Layout happens at render time, so the rest of every file is
  byte-identical: upgrading is one deterministic four-line diff per tracked diagram under
  `ontology-hub-publish/architecture/**` and `ontology-hub/model/contracts/diagrams/` —
  regenerate and commit them with the upgrade, or the drift gate reports the difference. A hub
  whose renderer predates Mermaid 10.5 (which rejects frontmatter outright) opts out hub-wide
  with `projections.mermaid_layout: none` in `kairos.yaml` and gets the previous bytes.

### Fixed
- **`validate --ddd` no longer parses an overlay into the ontology loader's cached graph.**
  `build_merged_graph` merged the overlay into the graph object `load_ontology` memoizes per
  path, so every overlay validated earlier in the process became part of the next one's
  merged graph — and of the domain graph the rest of `validate` then read. Symptoms were
  order-dependent: an `AggregateMember` without a root passed because an earlier overlay's
  `aggregateRoot` triple was still there. The domain graph is now copied before merging.
- **`compile --check` reports a deferred cross-domain bridge endpoint.** #763 deferred the
  endpoint check on the single-domain path and recorded the result on the plan, but
  nothing printed it: `compile party --check` was green and `emit-gold` on the product
  then failed on the same endpoint. The check output and the JSON payload
  (`unresolved_bridges`) now name the bridge and the endpoint the domain cannot see.
- **A declared workflow customization is honoured in every state.** #772 exempted a
  declared workflow from the `customized` failure, but one pinned to an older shipped
  generation (`outdated`) still failed `update --check` and was overwritten by
  `update --refresh-workflows`, contrary to what `CICD.md` promises. Declared workflows
  are now skipped by the refresh and excluded from the outdated count.
- **The master ERD headers carry the hub's declared name, not the checkout directory.**
  All three masters (canonical, Silver, Gold) stamped `hub_root.name`, so two clones of
  one hub under different directory names regenerated a one-line header difference and
  failed the drift gate on it. They read `name:` from `kairos.yaml` and fall back to the
  directory only when it is absent. **The headers change bytes once on your next run.**
- **`validation-report.json` anchors on the repository root, not the hub's parent.**
  #822 approximated the repo root as `hub_root.parent`, which is right for the scaffolded
  layout and wrong for a flat-layout hub or a hub nested deeper: paths began with the
  checkout's directory name and still differed between contributors. The nearest ancestor
  carrying `.git` is used, with the parent as fallback.
- **The reference rollup credits an ambiguous anchor to the copy the table's columns
  align to.** #523 keyed the rollup on the class URI, but a table anchored to a bare
  name declared by two modules was still credited -- with every custom column -- to both
  copies, and `custom_extensions_count` summed twice over the hub.
- **A `candidate` concept-mapping match does not name a draft-model node.** #762's lexical
  proposal became the node label and could acquire glossary evidence under that name
  before anyone confirmed it; the node keeps the TMDL table's own name until then.
- **`import-tmdl` finds the hub catalog from inside the hub.** The match proposer located
  the hub with a helper that does not walk parent directories, unlike the one that
  places the output, so a run from `ontology-hub/integration/` wrote its artifacts and
  proposed nothing.
- **`--model` typed as the default is recorded as `explicit-model`.** #545's provenance
  label used the default model's name as the "not passed" sentinel, so `--model
  gpt-5.4-mini` was indistinguishable from the option's absence.
- **Name tokens split an acronym run before a capitalised word.** `ETLLoadDate` tokenised
  to `etlload`, `date` and matched nothing after #522; it is `etl`, `load`, `date`.
- **A hand-edited alignment without a `domain` key no longer reads as
  `<domain>-alignment-alignment.yaml` in the staleness message.**
- **`scripts/collect_changelog.py` prints on a Windows console** whose code page cannot
  encode a fragment's characters.

### Documentation
- **The workflow between the context engineer and the data engineer is written down.** New
  practitioner page *How the context engineer and the data engineer work together* (ownership,
  the handshake step by step, escalation routes, what each stage leaves behind, what the toolkit
  enforces versus proposes), with matching sections in the context-engineer and data-engineer
  methodology guides.
- **New how-to, shipped to hubs:** *Document the architecture with a DDD overlay* — the subset
  invariant, the two kinds of file, "annotate, do not move", the overlay rules, the class ledger,
  the generated artifacts, the Lucid rule, and how to carry an external logical model.
- `kairos-help`, `kairos-flow`, `kairos-execute-validate`, `kairos-execute-project`,
  `kairos-design-domain` and `kairos-design-mapping` now name the architecture layer where it
  touches them; the user guide lists the DDD files and the class ledger among the authored
  inputs; *Design a domain* gains a "What you get" section.
- `alignment_closure` states what #518 compares -- the blueprint's activated module list,
  not a resolved `owl:imports` closure -- and what that does not detect.
- `update --check`'s exit-code help names undeclared workflow divergence as a failure
  cause; the lane test pins `full-validate.yml` as well as `pr-validate.yml`.

## [5.18.0rc3] — 2026-09-19

### Added
- **An alignment artifact stale against its domain's activated module list is now reported
  (issue #518).** `<domain>-alignment.yaml` recorded the `domain_uris` it was generated
  against and nothing ever compared them to anything, so a blueprint change that added or
  removed an activated module left the file silently stale while downstream stages consumed
  it as current. (A change *inside* an activated module, or an added bridge, does not alter
  that list and is not detected by this check.)

  The failure was invisible *and pointed the wrong way*: what surfaced was
  `integrity.managed-import-unused` — "this domain imports a module and references nothing
  from it" — which reads as a **sourcing** gap when the cause is a **staleness** gap. On a
  hub using those warnings as a sourcing backlog (DD-187), a stale file corrupts the
  backlog.

  `design-landscape` now names the modules added or removed since the alignment was
  generated, and says explicitly that an unused-import finding for an added module is
  staleness rather than missing data. Artifacts also record a `closure_sha256` fingerprint
  of that module list.
- **`foreign_properties` separates a misassignment from an invention.** A property that
  exists elsewhere in the closure but not on this class is a different finding from one
  that exists nowhere, and only the second is a hallucination. They call for different
  responses, and the report now says which it is.
- **`check-ai-config` now flags a model whose *tier* is wrong for the role (issue #545).**
  It reported `ok` with no caveat for `KAIROS_AI_ALIGNMENT_MODEL=gpt-5.5`, and the run then
  recorded `model_used: gpt-5.4` — which reads as a silent downgrade to a weaker model
  after a provider error. It is not: `--high-accuracy` selects `gpt-5.4` *on purpose* for
  this role, because alignment is deterministic closed-vocabulary matching and a reasoning
  model adds latency and cost without benefit. The configured value was the one at odds
  with the toolkit's own advice, and a parameter rejection can never change the model.

  Reconstructing that took reading `ai_provider.py`. The advisory now says it at
  pre-flight, which is where DD-159 wants it caught, and explicitly pre-empts the
  downgrade reading. It is a note, not a failure — the run works.

- **Alignment artifacts record `model_source` alongside `model_used`.** `high-accuracy-tier`,
  `explicit-model`, `role-env-override` or `default`, so the outcome carries its reason.
  Omitted when a library caller does not supply one, which keeps the previous artifact
  shape.
- **`validate` warns when an object property's effective ranges are not a subsumption
  chain (issue #731).** Ranges are superproperty-widened: for `hasCustomer
  rdfs:subPropertyOf hasParty`, with `hasParty rdfs:range Party` and `hasCustomer
  rdfs:range Customer`, the effective ranges are `{Customer, Party}`.

  RDFS requires the object to be in **every** declared range — the intersection — which
  only makes sense if the ranges are related by `rdfs:subClassOf`. Reference models
  routinely declare a subproperty's range without asserting that chain, leaving a property
  whose effective range is `Customer ∩ Party` with nothing proving the intersection is
  inhabited by anything.

  The new `range_not_subsumption_chain` warning names the unrelated pair, says which
  property contributed the inherited range, and states the two remedies: assert the missing
  `rdfs:subClassOf`, or narrow the range.
- **`dim_date` gains `quarter_number` and `month_name`.** Both are pure functions of the
  date and the macros to compute them already existed; month name was sliced on 32 times
  across 4 reports in the surveyed client estate. Every emitted surface picks them up
  automatically from the declaration.
- **`project --target erd` now writes a hub-wide `master-class-diagram.mmd` (issue #753).**
  The bound Silver and Gold ERD families already merge their per-domain diagrams into a
  master; the canonical target did not, so reading the whole canonical surface meant
  opening every domain file and holding them in your head.

  A class drawn by several domains appears once. That is the actual work: an imported class
  is drawn in *every* domain that reaches it, so naive concatenation emits the same block
  repeatedly. The owning domain's drawing wins — in a per-domain diagram a stereotype marks
  a class as imported *from that domain's view*, but in the merged hub-wide diagram every
  domain is local, so the importer's stereotype would be misleading.

  It is merged from the files the same run just wrote, so the master can never disagree
  with them, and the drift gate already regenerates it (`project --target erd`, added with
  #774).
- **`import-tmdl` now proposes a `reference_model_match` per table (issue #762).**
  Concept-mapping worksheets shipped 100% empty and nothing downstream infers the field by
  design, so on a hub with a large legacy estate `design-landscape` reported no BI weight
  at all until hundreds of rows were triaged by hand — 368 on the reported hub, across 18
  PBIP exports. The report-usage packs already rank fields and measures by real placement;
  the concept mapping is the only bridge from those to accelerator classes, and it started
  blank.

  The proposal reuses `class_anchoring.rank_candidates`, the same deterministic, lexical,
  explainable matcher `suggest-anchor` uses. No LLM: `design-landscape` performs no
  classification of its own by design, and a confident-looking score from an opaque
  similarity would make the modeller's judgement harder rather than easier. Only an
  unambiguous winner above the "qualified form" tier is proposed — a tie is the modelling
  judgement this pass exists to support, not to pre-empt. A BI role prefix (`d_`, `f_`) is
  stripped first, since it encodes table role and never the concept's name.
- **`[tool.kairos] customized-workflows` declares a workflow you edited on purpose.** A
  declared workflow is never auto-refreshed and never fails the check; it is still listed,
  so the divergence stays visible in review. An **undeclared** one now fails
  `update --check`, and the message prints the exact stanza to paste.

  Failing on *any* divergence was rejected deliberately: workflows legitimately carry local
  customization — an org CA bundle, extra credentials, a job nothing upstream knows about —
  which is why they were kept out of the marker-based managed-file set to begin with.
  Declaring is the middle ground. It also covers the second meaning of "customized", a
  generation this toolkit no longer ships, which a hub that skipped several releases can
  hit without having edited anything.
- **`validate-dbt --structural-only` now detects duplicate dbt resource names (issue
  #786).** It previously ran exactly one check — a dangling-`ref()` text scan — so it could
  not see two resources sharing a name, which is the one defect class that makes an
  assembled package fail at *parse* time. No `--select` or `--exclude` works around that,
  and no downstream dataplatform can consume the package at all. #777 and #779 were both
  this shape, and both passed `compile --check`, `--emit` and `--structural-only` before
  dbt itself rejected the manifest downstream. The compiler bugs behind them are fixed;
  this is the gate that stops the next one reaching a hub the same way.

  Two scans, both needing no warehouse and no dbt install, which is what lets them live in
  the phase a hub's CI release loop actually runs: model SQL stems against seed CSV stems
  (they share the `ref()` namespace, the same pairing the dangling-ref scan already makes),
  and `data_tests` entries that repeat identically on one model or column — dbt derives a
  generic test's name from the test name plus its arguments, so byte-identical entries
  collide. Both run before the dangling-`ref()` scan, since a duplicate name makes every
  other structural finding downstream noise.
- **The supported dbt stack is declared as toolkit config** (`core.adapters`), instead of
  existing only as pins copied into templates and rediscovered by trial. `DBT_CORE_FLOOR`
  is what the emitted package requires of its consumer; `DBT_CORE_REQUIREMENT` is the
  narrower intersection a hub installs so every supported adapter agrees on one dbt-core;
  `DBT_ADAPTER_REQUIREMENTS` and `DBT_PACKAGE_REQUIREMENTS` cover the adapters and the dbt
  packages the emitter hard-codes call sites against. Each records *why* both ends of its
  range exist. A test binds every surface that repeats them to the declaration.
- **The emitted dbt package declares `require-dbt-version`.** A consumer on an
  incompatible dbt now gets a dbt-native version error first, rather than a macro error
  several steps removed from the cause. Deliberately the floor only: the ceiling is one
  hub's offline-gate concern and would wrongly reject a dataplatform on a newer dbt with a
  different adapter.
- **`import-tmdl --fail-on-partial`** exits non-zero when any `model.tmdl` declares tables
  its export does not contain. Off by default, since a batch import of many exports should
  not fail wholesale because one of them is incomplete.
- **A conformed dimension can be shared across Gold products (issue #829, DD-228).** A new
  `gold.shared_domains` list in `kairos.yaml` names the domains several products may claim:

  ```yaml
  gold:
    shared_domains: [party, reference-data]
    products:
      - name: shipment-performance
        domains: [consignment, party, reference-data]
      - name: financial-performance
        domains: [billing, party, reference-data]
  ```

  DD-222 fixed the one-owner rule on *domains*, while the thing that must not be duplicated
  is a *table*. Those coincide for a fact-bearing domain and diverge for a dimension-only
  one — which is exactly what a conformed dimension is. A hub that needed `party` in two
  products had to choose between one product absorbing everything, or shipping a model
  whose customer slicer has no customer table.

  Sharing is **declared, never inferred**. Guessing it from a domain having no facts would
  mean that adding the first fact silently re-materializes all of its tables in every
  consuming product — a change in physical layout with no edit to say so.

- **`emit-gold` reports which tables a product builds and which it reads.** The issue's
  explicit ask. The product report carries `materialized_by: {domain, shared: true}`, the
  DDL block names the owning domain, and the emit prints the split:

  ```
  1 table(s) built by this product, 1 read as shared:
      dim_customer (owned by party)
  ```
- **The `mdm-profile` release now emits a `schema_version` field.** `kairos-mdm-runtime`'s
  profile contract already specified `schema_version` and a fail-closed compatibility check
  against it, treating its absence as an undocumented baseline. The toolkit now emits it
  explicitly (`"1.0.0"`, matching that assumed baseline), so runtime readers can check
  compatibility directly instead of inferring it. `schema_version` is covered by
  `content_digest` like the rest of the profile policy, so a `{domain}-mdm-profile.json`
  regenerated from an unchanged reviewed hub state will have a different digest than one
  produced before this change — re-pin dataplatform digests after upgrading.

### Changed
- **`read_reference_terms` now carries each class's property names (issue #524).** The
  loader flattened classes and properties into one list and dropped the link between them,
  so any caller needing "which properties does this class carry" had to resolve the closure
  a second time. `build_class_catalog` did exactly that for #519's anchor tie-break, and
  `propose_alignment` independently built its own indices for #517/#520 — the same
  relationship derived three times from two loaders.

  It is carried on `ReferenceTerm.property_names` now, which is where the loader already
  knew it. The duplicate resolution in `anchor_tables` is gone.
- **The three ways `_active_source_inputs` consumes `class_uris` are now documented and
  deliberate**, under the #729 policy (*traverse for compatibility, exact for identity*).
  Contracts and table mappings answer "does this domain own this?", which does not
  inherit, and stay exact. The property filter answers "could a class in scope carry
  this?", which does, and traverses up.

- The inline walk is replaced by the promoted `projections.shared.class_ancestors` — the
  ninth hand-rolled `rdfs:subClassOf` walker found in the #729 inventory, now the eighth.
- **A proposed match is not counted as BI weight until confirmed.** It is written as
  `action: candidate` alongside `match_confidence` and `match_reason`, and
  `design-landscape` reports it as awaiting confirmation rather than as evidence. BI weight
  exists to say what the business actually reports on; letting a name guess vote on that
  would invert its meaning. Confirming a proposal is far cheaper than authoring one, which
  is where the saving is.
- **The workflow header says what is actually true.** It read
  `Auto-generated by kairos-ontology-toolkit — do not edit`; it now explains that an
  undeclared edit is silently reverted, how to declare one, and that an edit worth having
  everywhere should go upstream instead. Both local edits this issue cited as legitimate —
  `uv run --no-sync` and the `architecture` drift gate — have since become upstream
  defaults, which is the argument for making that path explicit.
- **Scaffolded hubs now track `ontology-hub-publish/architecture/**` (issue #774).** The
  canonical class diagrams and DDD maps are how a model actually gets reviewed and
  explained — an architecture ERD shows the full canonical surface, including everything
  inherited from the industry tier. Left untracked they rot invisibly: one hub's had
  drifted into mixed vintages, some domains regenerated weeks apart, and nothing surfaced
  it because nothing was watching.

  Tracking alone would be worse than not tracking, so the drift gate regenerates them too:
  `architecture/**` comes from `project`, not from `compile --emit`, so `pr-validate.yml`
  and `full-validate.yml` now run `project --target erd` and `--target ddd` before the diff,
  and the tracked-ness guard covers the new path. A test pins the two halves together — any
  lane the template allowlists must appear in the gate that diffs it.

- **Canonical ERD and DDD diagrams carry a provenance stamp.** They were the only generated
  Mermaid artifacts without one, so a diagram produced by an older projector was
  indistinguishable from a current one — exactly the mixed-vintage problem above. They now
  use the same `mermaid_provenance_comment` helper as the Silver, Gold and contract
  diagrams, which records the toolkit version and deliberately carries **no timestamp**: a
  wall-clock stamp in a tracked, drift-gated file would fail CI on every run. *When* a
  diagram changed is what git history records; only *which version* drew it cannot be
  recovered afterwards.
- **SHACL is skipped for an orphan overlay rather than run against nothing.** Before, an
  overlay using `kairos-ddd:aggregateRoot` failed rule 4 with *"must point to an owl:Class
  present in the merged domain graph"* — which reads as a modelling error in the overlay
  when the real cause is that the file is orphaned, sending the reader to entirely the
  wrong place. That message is now replaced, not merely accompanied. The projection-leak
  scan still runs, because it reads the overlay alone and stays meaningful.
- The summary line reads `Checked N DDD overlay(s)` rather than `Validated N`, which was
  the specific claim an orphan made false.
- **`_shared__gold_models.yml` records every contributing calendar profile, not the last
  one to compile.** Two domains declaring the same bounds render a byte-identical
  `dim_date.sql` and differ only in the profile URI recorded as provenance — one table
  with two contributors, not a conflict. `calendar_profile` stays a scalar while one
  domain declares it, so every hub shipping today is byte-for-byte unchanged, and becomes
  a sorted list once several do.

### Removed
- Five helpers that lost their last caller in earlier releases: the medallion projector's
  `_build_sk_expression`, `_build_iri_expression` and `_fk_child_parents` (#234), the
  projector's `_discover_silver_extension_for_sync` (v5.0.0) and the CLI's
  `_format_refmodels_version` (DD-173); the never-read `GoldMeasureSpec.data_validated`.

### Fixed
- **The `operational` column rule no longer sweeps up business data (issue #522).**
  `_OPERATIONAL_PATTERNS` was matched by bare substring, so `timestamp` caught
  `transaction_timestamp`, `pickup_start_timestamp` and `timestamp_posted` — occurrence
  times, which are the central fact of an event or ledger row — while `source_id` caught
  `resource_id` and `_by` caught `owned_by_subco`.

  This matters more than a misreported reason code: `operational` is one of two reason
  codes DD-186 auto-dispositions to `not-business-data` without human review, and that is
  the only disposition which *removes* a column from the DD-169 gate rather than deferring
  it. On one hub, 114 of 185 columns auto-dispositioned from this reason were contradicted
  by the aligner's own output in the same run.

  Matching is now on name tokens with boundaries: `timestamp` alone decides nothing (audit
  intent is carried by the action — `created`, `loaded`, `ingested` — never by the type
  suffix), `by` counts only as a trailing token, and `source id` only as an adjacent pair.

  The vocabulary is `gap_decisions._AUDIT_NAME_TOKENS`, reused rather than copied: the
  gate and the aligner disagreeing about what "audit" means is how this class of bug
  arises. The aligner stays deliberately wider for pipeline artifacts the gate has no
  token for, and a test pins that it is never narrower.
- **The reference rollup no longer accuses a correct mapping of hallucinating (issue
  #523).** It deduplicated reference classes by **local name**, so where two imported
  modules each declare a `Terminal` with different property sets, the two collapsed and a
  property carried by only one copy was reported as `hallucinated_properties`.

  That is a false accusation of model error — close to the worst kind of bad signal,
  because it directs review at a working mapping and away from real defects. On the
  reported hub it was investigated as a strict-schema gap before the duplicate name was
  found. It also under-reported coverage, scoring a legitimately mapped column as unmapped.

  The rollup is now keyed on the class URI. An ambiguous local name is resolved the way
  the aligner already resolves it — to whichever same-named class actually declares the
  property — so the two components no longer disagree about the same data. Display names
  stay bare while unique and are qualified with the module (`tic/locations:Terminal`) when
  not, rather than merged.
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
- **The dbt `ref()` scan no longer warns on every contracted intermediate (issue #728).**
  `compile --check` and `compile --emit` each reported `ref('X') … matched no model in this
  domain's render scope` for every contracted model a Silver model reads — 24 unique
  warnings and 48 occurrences per CI run on one hub, with a **100% false-positive rate**.
  It was the single largest warning category in the PR gate, and it buried the warnings
  that mattered: 43 unresolved source paths and 2 undeclared PII properties.

  Two independent causes, either of which was enough on its own. `render_canonical_project`
  — the v5 render path — never passed `known_models` to the validation step at all, so the
  scan always ran against an empty set. And the set it would have passed was empty anyway,
  because `BoundSources.contracts` is hard-coded empty on the v5 binding path, so even a
  binding's own directly-bound contract was unknown to the scan. The comment in `render.py`
  claimed the scan saw "the directly-bound contract names", which had not been true.

  The model names now come from `SourceTableFact.ref_model`, already set wherever a
  resolved relation is a dbt model, so no new plumbing from the kernel was needed. The
  check is not weakened: a `ref()` naming something that is neither a rendered model nor
  any binding's declared contract is still reported.
- **`owl:Thing` no longer widens the dbt source scope (issue #735).** The ancestor walk in
  `_active_source_inputs` had no upper bound, unlike every other guarded class walk in the
  tree. A hub asserting `rdfs:subClassOf owl:Thing` put it in scope, and any property
  declaring `rdfs:domain owl:Thing` — a common symptom of a missing `owl:imports` — then
  matched every class at once.
- **A date-sliced insight is no longer reported as unanswerable (issue #747).** Insight
  coverage resolved `dim_date` against a two-element allowlist (`date_key`, `full_date`),
  so any insight slicing by month or year came back "not answerable yet" naming a column
  the warehouse demonstrably had. On one hub that was 6 of 9 insights — essentially every
  legacy report compares a period against a prior period — and the false negatives drowned
  the two real findings. The brief is the hand-off artifact to the BI engineer, so it was
  telling them the model could not answer questions it could.

- **…and `dim_date` now actually carries those columns in Power BI.** This is the half the
  issue did not reach: the TMDL declared only `date_key` and `full_date`, so
  `dim_date.month_number` was genuinely *absent from the semantic model* even though the
  dbt model and the DDL both built it. Coverage was telling the truth; the emitter was
  under-declaring the table. Widening the checker alone would have made the brief lie in
  the other direction.

  The column list was restated in seven places and they had drifted. It is now declared
  once, in `core.projections.dbt.calendar_columns`, and the dbt model, the DDL, the TMDL,
  the dbt `schema.yml`, the ERD, the measure-dependency allowlist and the insight-coverage
  allowlist all read it.
- **A cross-domain Gold bridge can now be authored (issue #763).** `gold_shape` documents
  its bridge-endpoint check as running "over the union, not per domain: a bridge may span
  two domains' tables" — but `compile <domain> --check` reaches that code through
  `_shape_dimensional`, which wraps a single domain in a 1-tuple. The union was a union of
  one, so `gold.bridge-endpoint-not-materialized` fired for every cross-domain bridge, and
  `emit-gold` failed too because it compiles each member domain first.

  Net effect: the one construct that gives Power BI a slicer across two facts — the reason
  `bridge` exists — could not be authored on a multi-domain product at all, and the error
  pointed at a binding that was correct.

  The check is now deferred on the single-domain path, where the other endpoint is out of
  scope by construction, and reported as `unresolved_bridges` on the compile plan, in the
  product JSON, and by `emit-gold`. At product level the union is real, so an endpoint
  genuinely outside it still fails closed — deferring does not become "never check".
- **`update --check` now reports drift in toolkit-managed GitHub workflows (issue #772).**
  A locally edited workflow was listed informationally and the run then printed
  `✅ All managed files are up to date` and exited 0 — so the `managed-check` job stayed
  green, a hub's deliberate CI fix got no signal, and the next `update` reverted it. The
  files carry a "do not edit" marker while nothing enforced it: the marker and the gate
  disagreed, which is what this issue is really about.
- **Tagged releases now work on GitHub Enterprise Server (issue #773).**
  `release-projections.yml` set `GH_TOKEN` but not `GH_HOST`, so `gh` fell back to
  inspecting the git remote, did not recognise a non-`github.com` hostname and gave up —
  *after* compile, emit, validation and packaging had all succeeded. No release object was
  created and the artifacts the job had just built were discarded with the runner. The host
  is now derived from `GITHUB_SERVER_URL`, which is correct on both github.com and GHES.
- **An RC tag now publishes as a pre-release.** GitHub does not infer pre-release status
  from a tag name, so `v0.2.0-rc.1` published as a normal release — which defeats cutting
  an RC, and misleads a consumer that pins by release.
- **Managed workflows no longer re-resolve dependencies on every command (issue #771).**
  Each workflow ran `uv sync --locked` in its own step and then invoked `uv run` up to six
  more times; because the toolkit and reference models are pinned as direct URLs rather
  than registry packages, every one of those was a fresh network fetch of the wheel
  metadata. A single job made roughly seven round trips where one would do, and any of them
  could catch a transient upstream error and fail the run — with a misleading message
  naming the URL, which reads as "the URL is corrupt" rather than "the registry blipped".
  Every invocation now passes `--no-sync`, and the one `uv sync` that was missing
  `--locked` has it.
- **`KAIROS_SKILL_CONTEXT` is set for the whole workflow, not one step of five (issue
  #721).** Every other skill-managed command printed a "prefer the skill in your AI coding
  session" advisory into CI logs, where there is no session to redirect to and no skill to
  prefer — and it implied the run had skipped validation gates that adjacent steps perform
  explicitly. Setting it at workflow level also means a step added later inherits it rather
  than silently regressing.
- **A freshly scaffolded hub can now parse the package the toolkit emits for it (issue
  #789).** The v5 Silver path emits generic-test config under the dbt 1.10+ `arguments:`
  key, while the scaffold pinned `dbt-core>=1.9,<1.10` — so `validate-dbt` failed at parse
  with `macro '...' takes no keyword argument 'arguments'`, a message about the macro
  rather than the version. The scaffolded pins now start at the floor the emitter actually
  requires.
- **The hub and the dataplatform no longer resolve different dbt versions.** The
  dataplatform built its own `>=1.9.0,<2.0.0` adapter pin, independent of the hub's, so
  each hid what the other would catch — deprecations emitted *by the hub* were only
  observable *in the dataplatform*, where nobody was looking. Both now read one
  declaration.
- **An imported class reached only by a relationship now shows its attributes (issue
  #804).** `project --target erd` drew every non-local class as a member-less stub. That
  is right for an inheritance ancestor — its attributes are already listed, prefixed `#`,
  on the classes that inherit them — but wrong for a class reached only across an object
  property, because nothing inherits from it and its attributes then appeared nowhere in
  the diagram at all. On one hub that hid `vesselName`, `imoNumber`, `draftValue` and
  every certificate, survey and crew-list class hanging off `imo:Vessel`. A class that is
  both an ancestor and an endpoint still renders as a stub, and every imported class keeps
  the stereotype naming the model it comes from.
- **A domain that re-declares imported classes now produces an ERD (issue #805).**
  `project --target erd` decided which classes belonged to a domain with an IRI-prefix
  string test. `kairos-design-domain` directs authors to reuse a reference-model class
  rather than mint a local one, re-declaring the imported IRI in the domain `.ttl` to
  attach labels — such a class keeps its reference-model IRI, so it was never local, and a
  domain modelled entirely that way emitted nothing at all. On one hub that was 5 of 12
  domains, and passing the right namespace explicitly did not help. Locality is now the
  union of the namespace test and what the domain file itself declares; a class the domain
  file only *references* (a reference-model superclass, say) still stays external.
- **A projection target that produces no artifacts now says so.** Both "this domain has
  nothing to draw" and "the projector found nothing" were silent, and the CLI reported
  success either way — which is why the above went unnoticed.
- **Two classes sharing a local name no longer collide on one ERD node (issue #806).**
  `project --target erd` derived every Mermaid node id from the class's local name alone,
  so two distinct IRIs with the same fragment became the same node. The canonical case is
  the modelling style `kairos-design-domain` recommends — a local subclass named after the
  reference-model class it specialises — which rendered two `class SeaLeg` blocks that
  Mermaid merged, plus an inheritance edge from the node to itself, making the diagram
  assert something the ontology does not. A contested name now takes the source-model
  label as a suffix (`SeaLeg_imo_port_call`); a name claimed by one class is untouched, so
  existing tracked diagrams stay byte-identical.
- **`import-tmdl` no longer reports an incomplete export as an empty model (issue #807).**
  Table discovery was a glob over `definition/tables/`, and the `ref table` pointers in
  `model.tmdl` — which name every table the model expects — were never read. An export
  shipped without its table bodies therefore produced `Tables: 0`, `tables: []` and a
  success exit, indistinguishable in every artifact written from a model that genuinely
  has no tables. Downstream, `design-landscape` then reported no BI weight for it and gave
  no hint anything was missing; on one hub that hid a 34-table / 375-field / 163-measure
  semantic model, the largest piece of BI demand evidence available. `import-tmdl` now
  names the unresolved pointers in a warning and in an `## Incomplete Export` section of
  the Engineering Pack, and qualifies the table count rather than printing a bare zero.
- **Spark's `long`, `short` and `byte` are now recognised source types (issue #808).** The
  compiler's type-alias table was T-SQL-flavoured and had no entry for Spark's integer
  names, but `import-source` writes the source catalog's `data_type` through verbatim — so
  on a Databricks-backed hub every 64-bit integer arrives as `long`. A column whose type
  missed the table was dropped from the bound relation's symbol table before any binding
  expression touched it, and referencing it anywhere — `fields:`, `grain.columns`,
  `identity.sourceKey`, `quality:` — failed with `safety.column-unresolved: not a column of
  the bound relation`. On one real hub that was 123 columns, essentially every weight,
  dimension, tonnage and monetary amount, producing a Silver contract with almost no
  measures in it. There was no binding-side workaround: `cast` is deliberately outside the
  closed scalar-expression grammar, so the only escape was a hand-written passthrough dbt
  model per affected table.
- **`scaffold-binding` no longer proposes `VARCHAR(255)` for an integer column.** The
  Fabric and Databricks warehouse type maps had the same gap and fell through to their
  string default, so the wrong type was baked into authored bindings before the compiler
  ever saw them.
- **An unrecognised source type now says so.** The diagnostic names the offending type and
  points at `kairos-ontology suggest-type` instead of claiming the column does not exist —
  the old message sent four separate authors hunting a schema problem that did not exist.
  `suggest-type`'s own "Supported:" list is now rendered from the compiler's table rather
  than hand-maintained beside it, which is how it came to omit these names in the first
  place.
- **Two EntityBindings may bind one `source.relation` to different canonical classes
  (issue #809).** The documented "one source table, several canonical entities" pattern
  failed `compile --check`: `_normalize_identities` kept its relation-to-identity-ref
  lookup keyed on the physical `table_uri` alone, so when two bindings shared a relation
  whichever was processed last silently overwrote the other's entry, and one class was
  then attributed the other's identity contributor. It surfaced as
  `safety.type-incompatible` / `identity.source-contributor-mismatch` pointing at a
  binding that was in fact correct, and the only workaround was a contracted dbt
  passthrough model per class — pure ceremony with no transformation in it — purely to
  mint distinct `virtual_source_iri` values. The lookup is now keyed by
  `(class, relation)`, matching the neighbouring `available_columns` map.
- **`validation-report.json` no longer embeds absolute machine-local paths (issue #822).**
  Every `file` entry carried the resolved path of the ontology file — leaking the
  developer's filesystem layout into an artifact routinely pasted into issues, PRs and
  support threads, and causing the report to ping-pong between contributors on any hub that
  deliberately tracks it. Paths are now rendered against the repo root with forward slashes
  (`ontology-hub/model/ontologies/customs.ttl`), matching how the drift gate and the dbt
  ref scan already report, and clickable in a pull request.

  Twelve emission sites, including the `shacl.semantic_context` dict **keys**, which are
  file paths too and would otherwise have left the report internally inconsistent.

  `run_validation` is a documented library entry point with direct callers, so the new
  `repo_root` argument defaults to off and their output is unchanged; the CLI passes it.
- **A dangling `ref()` in a join position is now reported (issue #823).** The dbt ref scan
  built its set of acceptable targets partly *from the content it was about to check*: a
  regex collected every `join ... ref('X')` in the artifacts and added X to the known set.
  A ref in a join position therefore whitelisted itself and could never be reported —
  including when the name was a typo naming nothing at all. It was the one place a
  dangling ref could hide from this scan completely.

  The exemption turned out to be load-bearing rather than dead weight, which measuring
  before deleting it revealed: one of the three join-position refs across the committed
  scenario hubs is a legitimate **cross-domain relationship join**, which is neither in the
  domain's render scope nor any binding's declared contract. Simply removing the exemption
  would have reintroduced a false positive of exactly the class #728 removed.

  The scan now consults the joins the project actually *declares* — `JoinSpec` already
  carries the referenced model as structured data — so a declared cross-domain join is
  known while a string that merely appears in a join position is not.
- **Generated properties YAML no longer emits generic tests in dbt's deprecated top-level
  argument form (issue #826).** dbt 1.10 moved a generic test's arguments under an
  `arguments:` key. The toolkit was half converted: its own tests nested correctly while
  the two `dbt_utils.unique_combination_of_columns` emissions kept the old form, so both
  shapes appeared in the same generated file. On dbt 1.12 each of those raises
  `MissingArgumentsPropertyInGenericTestDeprecation`, and dbt has them slated to become
  hard errors — at which point the emitted package stops parsing outright.

  This was invisible from the hub: it validated on dbt 1.10 while the dataplatform
  consuming its output ran 1.12, so deprecations emitted *by the hub* only surfaced
  *downstream*. That divergence closed with the version contract; this makes the emitted
  syntax match it.

  `config` deliberately stays at the top level — it scopes the test (the `where` clause
  that restricts a grain test to current rows) rather than being an argument to it, and
  nesting it would silently stop the scoping from applying.
- **`validate --ddd` no longer reports an orphan overlay as passing (issue #848).** A
  `*-ddd-ext.ttl` whose filename matches no domain ontology was validated against an
  **empty graph** and printed a green tick. So a typo in an overlay filename silently
  disabled validation for that overlay, and the run-level summary counted it as validated.

  The shapes that would have caught it cannot fire: `AggregateRootTargetShape` confirms a
  class is present in the merged domain graph, and with an empty domain graph there is
  nothing to confirm against.

  An overlay with no matching domain ontology is now a failure naming the file that was
  looked for:

  ```
  ❌ clint-ddd-ext.ttl
     no domain ontology at model/ontologies/clint.ttl -- an overlay is validated merged
     with the ontology its filename names, so this one was not validated at all. Rename
     the overlay to match its domain, or remove it.
  ```
- **Two domains with an approved calendar can now compile into one target (issue #849).**
  An approved `kairos-ext:calendarProfile` renders to `models/gold/shared/dim_date.sql`,
  deliberately outside the declaring domain's tree because one hub materializes one
  governed calendar. But `cli/compile.py` did not recognise that subtree as shared, so
  those files were claimed by the **per-domain** manifest — and the second domain in a hub
  to author an approved calendar could not `compile --emit` at all:

  ```
  ArtifactCollisionError: artifact destination collides with an unowned path:
  'models/gold/shared/_shared__gold_models.yml'
  ```

  The message named a path the author never wrote and gave no hint that two calendars were
  the cause. `models/gold/shared/` now belongs to the shared manifest, like every other
  cross-domain artifact.
- **A property one hop away in the import closure is named, not denied (issue #853).** A
  binding field targeting a property declared on another class reported:

  ```
  property 'imo:flagStateCountryCode' does not resolve in the ontology
  ```

  It does resolve. The compiler indexes the whole `owl:imports` closure (DD-103), so the
  property was sitting one hop away on a class a binding could target directly (DD-144).
  The message sent authors hunting for a typo, a missing prefix or a missing import, when
  the answer is "that property belongs to another class — bind it and link the two".

  Both halves of the same mistake now say so, and name the route:

  ```
  property 'acc:partyName' does not resolve against any class in this compile, but it
  exists in the import closure: it is declared on class 'acc:TradeParty', not on the
  bound class. Bind that class in its own EntityBinding -- an imported class needs no
  local rdfs:subClassOf to be bindable (DD-144) -- and reach it from here with a
  relationships: entry, or carry the raw value with technicalFields: (DD-139).
  ```

- **`binding.property-domain-incompatible` names the class that *does* declare the
  property**, not only the one that does not. Which of the two diagnostics an author gets
  depends on whether something else in the compile happened to pull the property's class
  into scope — invisible to them and irrelevant to their mistake — so both now carry the
  same guidance.
- **An approved calendar's `dim_date.tmdl` could not be loaded by Fabric.** #747 declared
  every calendar column in the semantic model, but placed each column's `///` description
  after its `sourceColumn:` line, inside the column body, where TMDL has no such line. The
  TOM validator rejected the whole model (`Unexpected line type: Empty!`), so `emit-gold`
  failed on every hub with an approved calendar, and with `--skip-tmdl-validation` it wrote
  a model Desktop and Fabric refused to open. Descriptions now precede the column
  declaration, as they do for every other table.
- **A domain can change its own shared calendar again.** #849 reconciled
  `models/gold/shared/` against whatever was on disk, with no notion of who wrote it, so a
  domain that extended its own `calendar_end` by a year -- or simply re-emitted after this
  upgrade, which renders more calendar columns -- was told two domains disagreed about one
  table, and the only way out was deleting the subtree by hand. When every calendar profile
  the on-disk schema yml credits is a profile of the incoming render, the incoming bytes
  supersede it; a genuine second contributor still fails closed as before. **Expect your
  first `compile --emit` after upgrading to rewrite `models/gold/shared/` once.**
- **The hub-wide master class diagram is drawn from the graphs, not merged from the
  per-domain files.** The first master (#753) merged text keyed on the Mermaid node id,
  the class's local name. Two classes that merely share a name (`party:Address`,
  `billing:Address`) collapsed into one block and one vanished silently; one IRI two
  domains had disambiguated differently was drawn as several nodes with the edges on a
  stub. Node ids are now assigned once over the whole hub, so one IRI is one node. The
  master's bytes change on your next `project --target erd`; the per-domain diagrams do
  not.
- **`binding.property-domain-incompatible` names the class that declares the property.**
  #853 made both "wrong class bound" diagnostics point at the owning class, but this one
  read the classes that *expose* the property, so a local `rdfs:subClassOf` heir was
  named as the declarer while the unresolved variant named the real one. Both now name the
  declaring class, as the same bindable token.
- **`_is_operational_column` no longer silences business columns.** #522 moved the
  predicate to whole-name tokens but took its vocabulary from the DD-169 gate's audit
  list, which was written as a generous *narrowing* check. Reused as the classifier it
  auto-dispositioned `batch_number`, `tariff_version`, `tenant_name`, `snapshot_date`,
  `sync_status` and `delete_reason` to `not-business-data` with no review. The predicate
  now has its own narrower vocabulary; ambiguous words decide only in a pair
  (`row_version`, `tenant_id`, `source_system`). The parallel substring list behind
  `recommended_disposition` is gone too, so `unload_date` and `upload_date` stop coming
  back `skip`. Re-run `draft-gap-decisions --dry-run` to see what changes on your hub.
- **`range_not_subsumption_chain` (#731) only judges range classes the file itself
  describes.** The naming lints run on one domain file with no `owl:imports` resolution, so
  a chain asserted in the shared kernel was invisible and every such pair was reported as
  unrelated -- 132 spurious warnings across the installed reference models -- with a
  remedy for an axiom that already exists.
- **`validation-report.md` carries repo-relative paths.** #822 fixed the JSON report; the
  Markdown sibling written by default still embedded the absolute checkout path in its
  options table and file list, so a hub tracking it still saw the file rewrite between
  contributors.
- **The `--no-probe` pre-flight carries the model-tier advisory.** #545 attached it only
  when the endpoint probe succeeded, so the CI path that never probes was exactly the one
  that kept producing the misreading it was meant to pre-empt.
- **The dataplatform scaffold pins `dbt-core` to the same range as the hub (#789).**
  `dbt-fabric` declares only a floor, so a dataplatform resolved the newest dbt-core while
  its hub sat on 1.10 -- the hub/dataplatform divergence #826 described as closed was not,
  for the default adapter. Existing dataplatforms: add `dbt-core>=1.10.1,<1.10.20` to
  `pyproject.toml` and re-lock.
- **Column-level generic tests nest their arguments under `arguments:` (#826).**
  Model-level tests were converted; a column `accepted_values` or a SCD2 `unique` with a
  `where` still rendered the top-level form dbt 1.12 deprecates. Argument values are now
  emitted as JSON rather than Python reprs, so a list argument changes bytes on re-emit.
- **`generate-bindings` and the relationship proposer know Spark's `long`/`short`/`byte`**
  (#808 covered `scaffold-binding` and the compiler). A Databricks `long` grain column no
  longer becomes `string` in a generated binding, and a `long` foreign key is
  identifier-shaped for proposals.
- **`ddd` and `contract-erd` no longer warn "produced no artifacts" for every domain
  without an overlay or contract.** The managed CI lane runs `ddd` on every hub, so the
  #805 warning fired once per domain on the default hub.
- **The concept-mapping worksheet's `candidate` instruction was wrong.** It said to
  confirm a proposed match by clearing `action`; an empty action is *untriaged*, so `next`
  kept recommending triage forever. Confirm by setting `use` or `specialize`. The
  design-landscape "decided" count no longer goes negative when candidate rows exist.
- **Stale text:** the `kairos-execute-validate` skill named the pre-#789 dbt-core pin.

### Security
- `uv.lock` moves `anyio` to 4.15.1 (CVE-2026-63374, CVE-2026-64847) and `pypdf` to
  6.19.0 (PYSEC-2026-3910/3911/3913), the two packages the dependency audit on `main` was
  failing on.

### Performance
- **`build_class_catalog` is roughly 3× faster.** Measured on the committed reference-model
  fixture (1271 classes): **22.9s → 7.2s**.

### Documentation
- Recorded the decision as `MDM-DD-005` in `docs/dev/mdm/mdm-design-decisions.md`.

### Notes
- Deliberately quiet where it cannot be sure: an unreadable artifact, one predating the
  fingerprint, or a closure that resolves to nothing is **not** reported as stale. This
  warns about a real difference; guessing would train readers to ignore it.
- The issue's third suggestion — having `integrity.managed-import-unused` itself
  distinguish "the alignment covered this module" from "the alignment never saw it" — is
  not done here, but the fingerprint it needs now exists.
- #521's cross-check now withholds fewer candidates, because fewer are misclassified in
  the first place. That is the intended direction: the cross-check is a safety net, not
  the fix.
- The property sets are now **strictly more complete**: on that fixture, 0 classes lose a
  property and 71 gain one. The second pass resolved only the modules that contributed a
  class copy, while the loader resolves each module's full `owl:imports` closure (the
  canonical DD-103 path), so the old narrower set was an artifact of the workaround. More
  properties can only strengthen #519's overlap-based tie-break, never weaken it — but it
  is a behaviour change, recorded here rather than left to be discovered.
- Deliberately a validator warning rather than a compiler error. #729's
  relationship-endpoint check accepts a target that is, or descends from, *any* declared
  range — because intersection semantics would turn today-green hubs red on exactly this
  ontology-quality issue. The compiler's non-suppressible safety kernel is the wrong place
  to adjudicate reference-model quality; the validator is the right one.
- This path is live on the **Gold** side: `medallion_gold_projector` calls `bind_sources`.
  The issue scopes itself to the legacy graph-driven projector, which is not the whole
  story.
- `medallion_silver_projector.generate_master_erd` is deliberately **not** reused: it emits
  and merges `erDiagram` bodies while this target emits `classDiagram`, so feeding one into
  the other produces a file Mermaid cannot parse. Its cross-domain block is also synthesised
  from `*-silver-constraints.json`, which is compile-plan-derived, while this target is
  binding-independent by construction (DD-209).
- The SVG half of #753 is **declined**, per DD-211 — see the issue for the reasoning.
- Hubs and dataplatforms on the previous generation of any of these four workflows are
  offered an automatic refresh rather than being reported as locally customized: the
  outgoing bytes are recorded under `scaffold/superseded-workflows/`. Only `pr-validate.yml`
  had a recorded history before this change, so `full-validate.yml`, `managed-check.yml`
  and `release-projections.yml` gain one.
- Builtin `unique` and `not_null` were checked and are unaffected: they are emitted as
  bare strings or with `config` only, neither of which is a deprecated form.
- **The materialization premise in the issue was wrong, and worth recording.** A Gold dbt
  model is emitted per *domain*, to `models/gold/<domain>/<table>.sql`, by that domain's
  own `compile --emit`; products exist only in the Power BI lane. So a conformed dimension
  was always built exactly once, and sharing changes only which semantic models may read
  it. That is why this change is as small as it is.
- A shared table keeps its own domain's `goldSchema`, so both products' TMDL partitions
  name `gold_party` and point at the one physical relation. Verified end-to-end rather
  than assumed — it is the assumption that would otherwise produce a model silently
  reading the wrong schema, discovered in Fabric.
- `emit-gold <shared-domain>` now fails with `gold.domain-shared-across-products` naming
  every product that reads it, rather than picking one arbitrarily.
- A genuine table-name collision still fails: sharing relaxes *who materializes* a table,
  not whether two different tables may carry one name.
- Undeclared sharing still fails with DD-222's original message, which now also names
  `gold.shared_domains` as the way to say otherwise.
- A deliberately orphaned overlay — for example a hub-level `_contexts-ddd-ext.ttl` for
  shared `BoundedContext` declarations — used to validate "successfully" by accident,
  which made an unsupported pattern look supported. It now fails, which is the honest
  answer until such a pattern is actually designed.
- Overlays that do match an ontology are unaffected; the shipped `acme-hub` overlays pass
  unchanged.
- A **genuine** disagreement still fails, and now says why. Domains declaring different
  bounds, week patterns or fiscal year starts describe one physical table two incompatible
  ways; reconciling that silently would be worse than the collision it replaces. The error
  names the field that differs and both values, rather than a path.
- Found while building #829, which needs the same subtree to be hub-owned; fixed on its
  own because it blocks any two-calendar hub regardless of Gold products.
- **Nothing changes about which bindings compile.** Both cases failed before and fail now;
  only the messages moved. A genuinely unknown token — a typo, an undeclared prefix — still
  reports as unknown with the usable-token list, which is the honest answer there.
- Split out of #811, and it **replaces that issue's "wall 2"**. #811 reported this as a
  reachability asymmetry — range-class scalars supposedly usable only when the hub declares
  a local subclass of the range. Measured both ways, neither shape makes the property
  usable from the parent binding, and the companion-binding route works with no local
  subclass at all. The defect underneath was always the diagnostic.
- The owning class is named with the token an author would type rather than a bare IRI: a
  resolved class carries both refs, and sorting between them was picking by first
  character.

### Known issues
- `dropped_params` is not yet persisted. A reviewer comparing two runs still has no record
  that one of them ran without `temperature` after a provider rejection. That needs state
  threaded from the provider retry through a threaded fan-out to the artifact, which is a
  larger change than the rest of this and is deliberately left out.
- A `ref()` between two copied intermediates is still outside this scan's view; the
  authoritative whole-project check remains `validate-dbt`, which the scaffolded PR gate
  runs.
- `week_number` is still not emitted, even though the calendar records a `week_pattern`.
  That column depends on a week-numbering convention nothing currently implements, so
  emitting it would repeat the mistake `week_pattern` already makes — declaring a
  convention the dimension does not honour. Tracked separately.
- `dbt-fabric` is pinned to exactly `1.10.0`. 1.10.1 replaced pyodbc with mssql-python,
  which parses the connection string eagerly and rejects the `Authority Id` keyword the
  offline validation profile produces, so the offline gate cannot pass on any later
  release. The constant records this; lifting it is tracked separately.

## [5.18.0rc2] — 2026-09-16

### Added
- **A semantic gate on the emitted Power BI model.** `pbip_validate` never reads TMDL and
  `tmdl_validate` only proves the TMDL deserializes, which is why every defect in #619, #623 and
  #790–#794 passed both and was rejected downstream. A new `gold_assert` module runs over the
  artifacts `emit-gold` and `package-powerbi-release` are about to write and fails closed on
  engine rules the serializer cannot see — starting with calculation-group columns, sort order,
  partition and ordinals, and the model-level `discourageImplicitMeasures` coupling. This is the
  gate #623's second fix item asked for.
- **`kairos-ext:goldPrimaryRelationship` declares which path stays active.** Which date role is
  active is not cosmetic — time intelligence follows it, so it is the product's fiscal semantics.
  The projector picks deterministically rather than failing closed, so existing hubs keep
  publishing, and reports every deactivated relationship in the Gold product report under
  `deactivated_relationships` so a silent pick cannot change a report's meaning unreviewed.
  Author `"Table.column -> Table.column"` on the `owl:Ontology` resource to decide it yourself;
  repeatable, and fail-closed on a value naming no emitted relationship
  (`gold.unknown-primary-relationship`). See DD-226.
- **A partial emit reports the domains it left stale.** `compile <domain> --emit --confirm-emit`
  now compares every other domain's recorded input digests against the working tree and names the
  ones whose committed output no longer matches:

  ```
  ✓ party: emitted 47 artifact(s) to ...
  ! 8 other domain(s) record authored inputs that have changed since they were emitted;
    their committed output is now stale: booking, consignment, equipment, ...
    run: kairos-ontology compile --all --emit --confirm-emit
  ```

  The toolkit already held everything needed to say this — each `metadata/<domain>.provenance.json`
  enumerates its inputs with their digests, so it is a lookup rather than an inference. Silent
  under `--all` (which has just refreshed everything), silent under `--quiet`, and silent when an
  input cannot be read, because a false alarm would train people to ignore the warning. The same
  fact appears in `--format json` as `stale_dependent_domains`. It never fails the command: the
  output that was written is correct, just incomplete.

### Changed
- **Role-playing date relationships are shaped rather than invented during rendering.** They were
  built directly into `relationships.tmdl` by the renderer, so they never appeared in the shaped
  relationship set and nothing reasoning over the model could see them — which is why the
  ambiguity they cause went undetected. Their emitted names are unchanged: in Fabric a renamed
  relationship is a new object, not an edit.

### Removed
- **A dead type-inference branch for `_kairos_fk_match_count_*` columns.** No producer ever
  emitted that spelling — the real name is `_kairos_fk_<hash>_match_count` — so the branch was
  unreachable.

### Fixed
- **The emitted time-intelligence calculation group can actually be created (issues #790, #791).**
  A calculation group is a table, and the Analysis Services engine enforces rules on it that the
  bundled TMDL validator does not. Kairos emitted the four `calculationItem` lines and nothing
  else, so the group had zero columns; the model also never set `discourageImplicitMeasures`,
  which the engine requires before it will create any calculation group at all. Both offline
  gates reported success — `package-powerbi-release` passed and TOM/TMDL structural validation
  reported no failures — and the Fabric service then refused to create the semantic model with
  `The total number of data columns inside the calculation group table 'Time Intelligence' is 0`.
  The group now carries the `'Time Calculation'` name column and the hidden `Ordinal` column it
  sorts by, an explicit `ordinal:` on every item so they read chronologically rather than
  alphabetically, and its own partition; the model sets `discourageImplicitMeasures` and declares
  `ref table 'Time Intelligence'` whenever a calendar is approved.
- **The emitted semantic model has one active filter path between any two tables (issue #792).**
  Power BI allows only one, and the projector emitted every relationship active — not one carried
  `isActive: false` — while routinely emitting several date roles on one fact and snowflake
  shortcuts alongside the multi-hop paths they duplicate. The model was unloadable in Fabric and
  in Desktop, and the service reports one offending pair per attempt, so on the product that
  surfaced this, finding all 21 ambiguities of 50 relationships would have cost 21 publish round
  trips. The projector now treats the relationships as an undirected graph and deactivates every
  edge beyond a spanning forest, in one offline pass, in a fixed priority order that never
  deactivates a business relationship in favour of a date role. A deactivated relationship stays
  in the model and is reachable from DAX with `USERELATIONSHIP`. A product with no ambiguity emits
  byte-identical output.
- **A measure can reference `dim_date`.** `_column_by_property` resolved column dependencies only
  against the product's tables, and the calendar is synthesized by the renderer rather than shaped
  as one — so `dim_date.full_date` was unresolvable and any measure declaring it failed with
  `measure.missing-column-dependency`. That is the dependency a `USERELATIONSHIP` measure needs,
  so without this the fix above would have deactivated relationships while making the only
  workaround uncompilable.
- **The semantic model no longer declares columns the Gold table does not have (issue #793).**
  The DD-109 `_kairos_fk_*_match_count` diagnostics reached the TMDL and the Gold DDL but never
  the dbt models that build the Gold tables, so the semantic model described a table shape that
  never existed and a Direct Lake refresh failed with `Delta protocol violation: the column
  _kairos_fk_<hash>_match_count is not found in delta table`. The cause is two `GoldTableSpec`
  objects shaped at different ages from one compile plan: `shape_project` shapes the Gold product
  before the compiler injects the diagnostics, and only `emit-gold` re-shapes afterwards, so
  `compile --emit` rendered the dbt models from the older spec. The diagnostics are now excluded
  from the Gold projection in the one function every Gold writer derives from, so the dbt model,
  the DDL, the TMDL, the ERD and the schema YAML agree by construction. They remain exactly where
  they belong, in Silver, and the Gold product report still records them under
  `silver_authority`. See DD-225, which supersedes DD-221 on this one column only — the rule that
  hiding is decided on provenance rather than role is unchanged.
- **A Gold table's primary key must be a column the product actually emits.** `_primary_key` read
  the raw Silver model while the emitted column set is filtered, and nothing reconciled them, so
  authoring `goldExcludeColumn` against a table's key left the key naming a column that is not
  there. Every consequence was silent: the relationship shaper pointed `toColumn` at a missing
  column, and `isKey`, the dbt `unique` test and the ERD `PK` marker simply stopped appearing —
  Power BI accepted the dangling endpoint at validation and rejected the model on load. This now
  fails closed as `gold.primary-key-not-emitted`.
- **A relationship's "one" side now needs a declared unique key (issue #794).** Analysis Services
  enforces uniqueness on that side when it builds the relationship index — not at validation — so
  a model with a non-unique key published, refreshed green, answered any measure that stayed on
  one table, and failed on the first query whose plan traversed the relationship with
  `Column <key> in Table <fact> contains a duplicate value`. Nothing offline caught it: the
  projector checked only that the target *had* a key, and `_primary_key` never consulted a
  declared one — it walks a role priority list and then falls back to "first non-nullable column,
  else first column". On the toolkit's own `invoice` fixture that produced
  `fact_invoice_line.invoice_sk -> fact_invoice._source_system`, putting a source-system name on
  the one side. The projector now requires a declared single-column key on the target's Silver
  model, and emits the relationship inactive when there is none rather than refusing the whole
  emit — an unproven relationship is a modelling smell, not necessarily an error, and the model
  stays loadable. Every deactivation is named in the Gold product report with a `reason`, either
  `unproven-key` or `ambiguous-path`. A composite key is not evidence about a single-column
  endpoint, and an SCD2 key predicated on `is_current` counts only where the emitted table applies
  that filter. See DD-227.

  `kairos-ext:factGrain` is deliberately not used for this: it is free text, emitted only as a
  comment, and cannot be parsed. Nor is a DAX probe against the published model reliable —
  `DISTINCTCOUNT` reported no duplicates on a column a `SUMMARIZE`-based count found many of.
- **`kairos-execute-project` now emits the whole hub, and says why (issue #796).** The skill
  prescribed `compile <domain> --emit --confirm-emit`, and `compile --all` appeared in no skill at
  all — while CI's drift gate runs `compile --all --emit --confirm-emit`. So the documented local
  workflow and the gate that judges it disagreed by construction. On any hub with more than one
  domain that reliably produced stale committed output: a domain's provenance records the hash of
  every authored file in its transitive import closure, so editing one domain's `.ttl` or contract
  invalidates the recorded provenance of every domain that imports it, directly or transitively.
  The emit succeeded, reported success, and the staleness surfaced minutes later in CI as a large
  hash-only diff — no SQL, model or contract-output differences — that reads like a serious
  failure when nothing is actually wrong. `docs/toolkit/how-to/compile-and-emit.md` and the
  scaffolded `CICD.md` say the same thing; the how-to's claim that `--all` is "a wall-clock
  optimisation, not a semantic one" was true of `--check` and wrong of `--emit`.

## [5.18.0rc1] — 2026-09-10

### Added
- **`validate-dbt-contracts` now rejects a canonical type name used as a SQL cast target
  (`dbt-contract.dialect-uncastable-type`, refs #778).** `cast(x as timestamp)` and
  `cast(x as boolean)` parse cleanly, pass `compile --check`, emit, and then fail against a real
  Fabric warehouse -- and a hub whose CI runs `validate-dbt --structural-only` never connects to
  one, so they reach `main` green. The confusion is narrow and real: `boolean` and `timestamp`
  are legitimate canonical kinds, correct in a binding's `externalReference.key[].type` and
  correct in a dbt contract's `data_type` (dbt-fabric translates `boolean` to `bit`) -- they are
  wrong only in a cast, and the two fields sit next to each other in the same authored file. The
  finding says so, so the fix is not to "correct" a `data_type` that was already right. A
  denylist of known-wrong spellings rather than an allowlist from the adapter type registry:
  T-SQL has many valid types the registry never names (`nvarchar`, `uniqueidentifier`,
  `datetimeoffset`), and flagging those would drown the real findings.

### Fixed
- **`compile --check` now rejects an `externalReference.key[].column` the parent domain's
  contract does not materialize (#775).** The key names the *parent's* output column, but the
  rename that produces that column happens in the parent's binding -- so the source-side name is
  the one an author has just been looking at. Four bindings in one hub drifted the same way
  independently, all four passed CI, `--emit` rendered joins against a column that does not
  exist, and the failure surfaced only when a downstream dataplatform ran `dbt run` against a
  real warehouse, taking five Silver models and three Gold facts with it. Nothing needed to
  change about per-domain statelessness to catch it: `discover_contract_paths` already admits a
  foreign domain's contract whenever this domain points a relationship at a class it declares,
  and already hashes it into provenance -- it was simply never parsed. The check consults the
  parent's *declared* interface (DD-213), never its emitted artifacts, and is keyed on the
  resolved target class rather than the model name. New diagnostic
  `relationship.external-reference-key-column-unknown`, which lists the parent's available
  columns. Fails open by construction: an ungoverned parent compiles exactly as it did before.
- **The generated Gold `dim_date` now builds on `fabric-warehouse` (#776).** Four constructs in
  one compiler-generated file, none of them portable, and the first failure hid the rest.
  `dbt_utils.date_spine` expands with a trailing `ORDER BY`; dbt-fabric's table materialization
  creates a view as an intermediate step and T-SQL rejects `ORDER BY` in a view without `TOP`, so
  the model failed even though it declares `materialized='table'`. Behind it: `EXTRACT` is not a
  T-SQL function, and `is_holiday` was rendered as `boolean` -- a type Fabric does not have --
  while the DDL for the very same table already said `BIT`. A fourth defect had not been reached
  yet: `cast(<date> as varchar)` uses style 0 on T-SQL and yields `Sep 09 2026`, so the
  `replace(..., '-', '')` that built `date_key` removed nothing and the outer cast to `bigint`
  failed; on Databricks the same expression is invalid because `varchar` needs a length, so
  `date_key` was broken on both adapters. The calendar model is now rendered per adapter, the
  same way the Gold DDL renderer beside it already was. `dim_date` is the product calendar, so a
  hub lost year-on-year, week and prior-period comparison everywhere until it built.

### Fixed
- **A conformance group no longer emits its relationship tests once per member, which made the
  generated package unparseable by dbt (#777, #779).** A group produces one Silver table, but
  relationship foreign keys were derived per *binding*: three members declaring the same
  relationship contract -- which `conformance.relationship-incompatible` requires them to --
  produced three byte-identical `kairos_temporal_fk_cardinality` entries per relationship, and
  dbt refuses to parse a project whose resources collide on name. There was no way to author
  around it while staying in the group. Single-source models were never affected, which is why
  the multi-source path reached a real warehouse before the defect surfaced. The duplication was
  wider than the schema YAML: the same tuple feeds the SCD runtime model's `*_match_count`
  columns, the branch SQL's temporal lookups, and the plan/explain JSON, so on an incremental
  entity it also broke DD-110 Silver output parity and blocked the compile outright. Fixed at
  both ends -- authoring facts are deduped where they are derived, and the policy that assembles
  `authority.foreign_keys` now keys on the property URI it already looks values up by.

### Performance
- **Hub PR validation is roughly halved, without weakening a gate.** A real 16-ontology hub's
  PR check took 9m10s. Three things were wrong with it. `compile --all --check` (110s) did no
  work the emit step did not already do — `compile_domain` forces rendering in every mode, and
  all four gates plus the success verdict are mode-blind, so `--check` is `--emit` minus the
  disk write; it is now dropped from the PR path and runs in the new serial `full-validate.yml`
  on main and nightly, which is also the only place a cache can be written that a later PR can
  restore. The two remaining halves run as **parallel jobs**: they share no path and neither
  reads what the other writes, and setup is ~9s, so paying it twice is cheap against the 161s
  saved by overlapping. The `validate` job id is kept, because it is the status-check context a
  hub's branch protection may already require. Plus `concurrency` with `cancel-in-progress`, and
  `enable-cache` on every `setup-uv`.
- **`validate` is 2.4x faster on a real hub (57.2s → 24.1s), with byte-identical output.** The
  per-domain SHACL passes are independent and read-only but CPU-bound Python, so threads would
  serialise on the GIL and only separate processes overlap them; they now run across processes,
  in input order, so counts, the error list and the printed report are unchanged — verified by
  diffing the full validation report between a serial and a parallel run. `KAIROS_VALIDATE_JOBS=1`
  forces serial for a low-memory container, and an unavailable pool degrades rather than fails.
  The reference-corpus walk (~17s) was performed twice per run, once for the DD-163 integrity
  audit and once for the DD-169 gate, with neither reusing the other's work; it is now resolved
  once. The GDPR scan re-parsed every source vocabulary once per domain — sixteen full parses of
  one corpus to answer sixteen questions differing by a one-line filter — and now reads it once.
- **`compile` no longer re-parses the whole hub once per domain.** The DD-163 gate ran per
  domain and each run parsed *every* authored `.ttl`, so a 15-domain hub performed 255 Turtle
  parses per invocation over one identical corpus. The scan is shared, keyed on a content hash
  of the files it reads — content rather than mtime, because re-auditing a hub after rewriting
  an ontology in the same process is a real pattern and a stale answer there is a wrong verdict,
  not a slow one.
- **Emit stages by hardlinking instead of copying.** With three or four transactions per domain,
  a 14-domain hub copied and then deleted a growing dbt project some forty times to write a
  handful of files. Safe because the emitter never writes through a path it did not create:
  artifacts use `open("xb")`, an exclusive create; a replaced owned file is unlinked first; the
  manifest is unlinked before rewrite; and commit only renames directories. A copy fallback is
  required rather than defensive — hardlinks need a filesystem that has them, which excludes a
  hub on a mapped network share or a FAT volume. Verified on a real 15-domain hub: two separate
  emit processes produce 363 byte-identical files.

### Added
- **`compile --all` reports per-domain progress.** It used to report a domain only once that
  domain had finished, so a 15-domain hub looked hung for minutes with no indication of which
  domain was in flight. Structured `kairos.compile.domain.started`/`.completed` events carry
  index, total and duration_ms at INFO for log consumers; the human line prints unconditionally,
  because the absence of any signal during a long command is a defect rather than a level to opt
  into. It goes to stderr, so `--format json` keeps stdout a single parseable document, and is
  suppressed by the new `--quiet`, under `--log-format json`, and for a single-domain run.
- **`KAIROS_LOG_LEVEL` sets the default log level**, so a long-running command can be made
  talkative without typing `-v` every time. Explicit `--verbose`/`--debug` still win, and an
  unparseable value is ignored rather than failing a command over its own logging configuration.
  Deliberately an environment variable and not a `kairos.yaml` key: that file's raw bytes are a
  compile provenance input hashed into `provenance_hash`, and the provenance sidecar is a
  tracked, drift-gated artifact, so a key there would rewrite the hash for every domain in the
  hub while changing no model bytes.

### Fixed
- **Changing a workflow template no longer silently strands every existing repo.** The contract
  is that the outgoing bytes are recorded as a superseded generation; skip it and each
  already-scaffolded repo classifies as "customized" and stops receiving template fixes. The
  ERD-relocation change edited `pr-validate.yml` and recorded nothing, and the suite stayed
  green because the only check compared hub generations against the *dataplatform* template,
  which they can never equal. Both missing generations are now recorded, that check covers both
  repo kinds, and a digest tripwire fails with the remediation steps the next time a template
  moves without its predecessor being kept.
- **The ontology parse cache is written atomically.** A bare write left a window in which the
  file existed but was short, and N-Triples is line-oriented, so a reader arriving mid-write got
  a *valid* parse of an incomplete graph — a silent wrong answer rather than a cache miss,
  reachable by an interrupted emit.

### Changed
- **Every ERD is written into the hub at `model/contracts/diagrams/`, beside the contract it
  describes, and the Power BI publish lane is no longer tracked.** The Silver ERD and its
  merged master used to land in `ontology-hub-publish/medallion/dbt/docs/diagrams/`, and the
  Gold ERDs under the Power BI publish root. A diagram is the one generated artifact a human
  actually reviews, so it belongs where a pull request shows it — in the authored tree,
  next to `<domain>.contract.yaml`. `compile --emit` and `emit-gold` write them there, and
  `pr-validate.yml` regenerates and diffs them like any other tracked output, so a committed
  diagram cannot drift from the inputs it was drawn from.

  `ontology-hub-publish/medallion/dbt` stays tracked, unchanged: a dataplatform consumes it
  as a dbt package pinned by `git` + `revision` + `subdirectory`, which `dbt deps` resolves
  out of the committed tree at that tag. `ontology-hub-publish/powerbi` is now ignored —
  `package-powerbi-release` renders and zips it in CI from the compile plan, so nothing
  needed it committed. Every other target was already ignored.

  Two behaviour changes to know about when upgrading a hub. The old diagram locations are
  cleaned up for you: the emit manifest that used to own those paths removes them.

  **The `.gitignore` change is not, and `update` will not mention it.** Delete this line
  from the hub's `.gitignore` by hand:

  ```
  !ontology-hub-publish/powerbi/**
  ```

  Leave it and the hub keeps tracking Power BI output that `package-powerbi-release` now
  renders in CI. Nothing prompts you, because `update`'s Git-hygiene check compares the
  template *against* the local file and reports only rules the hub is **missing** — it has
  no way to tell a rule the toolkit removed from a rule the hub added itself, so it never
  reports either. Git-hygiene files stay yours to merge by design; the blind spot for
  *removals* is tracked in #699 P2 and is deliberately not closed here.

### Added
- **`compile --emit` now draws the declared-contract ERD (DD-216).** It was only ever
  reachable through `project --target contract-erd`, a separate command over the older
  pre-CompilePlan pipeline, so a hub that only ran `compile --emit` never got one. It is a
  pure function of the authored contract — no graph, no compile plan — so emit renders it
  directly. `project --target contract-erd` still works and now writes to the same place.
  A domain with no contract still gets no diagram: adopting one stays opt-in (DD-213 §6).
- **Generated `.mmd` files carry the toolkit version that drew them**
  (`%% Generated by kairos-ontology 5.17.0 -- do not edit`). Deliberately no timestamp: the
  diagrams are tracked and drift-gated, and a wall-clock stamp is a fresh value on every run
  in a new process, so it would fail that gate unconditionally and make every emit a
  timestamp-only diff. The commit history records *when*; only *which version* could not be
  recovered afterwards.

## [5.17.0] — 2026-09-08

> The next release that includes this section must be a **minor** bump (5.16.0), not a
> 5.15.x patch: the SHACL change below adds emitted dbt tests to existing models.

### Added
- **A Power BI report design guide ships with `kairos-design-gold`, and a how-to covers the
  whole Gold lifecycle (#744).** `report-design-inspiration.md` collects what actually
  changes reporting outcomes: the native visuals and formatting-pane features teams
  underuse, JSON themes and `.pbit` templates as the highest-leverage consistency tool, and
  the UX practices worth arguing for — start from the decision rather than the data, one
  message per page, titles as takeaways, colour as signal with 4.5:1 contrast, accessibility
  and load time as usability, wireframe before building. Plus the insight side: IBCS, and
  the rule that every number needs a comparison to mean anything.
  It is **inspiration, not a gate**: nothing in it is validated by the toolkit or blocks an
  emit, and the guide says so at the top. It is reference material for shaping a
  conversation with a client, not a checklist to satisfy.
  A new how-to, *Design a Gold product*, walks the lifecycle end to end: declare the
  product's scope, author each domain's tables, record what people need to know, emit, hand
  off, and harvest what the BI engineer builds. `scripts/sync_dev_skills.py` now ships
  Markdown siblings of a skill, so reference material a skill links to reaches client hubs
  instead of stopping at this repository.
- **The hub/report ownership boundary is written down (#744).** The hub owns everything
  governed — tables, relationships, measures, calendar, security, column visibility,
  descriptions — and emits a *stub* report item. Report design belongs to the BI engineer,
  who builds it as a separate Fabric item with its own name bound to the deployed model:
  the generated `<Product>.Report` is republished on every hub release, so edits to it are
  lost. Model edits return through `harvest-gold`, never into the dataplatform repository.
  Recorded in the user guide, the dataplatform `CICD.md`, the *consume from a dataplatform*
  recipe and the `kairos-package-dataplatform` skill, which also now states that the
  dataplatform-side TMDL sanitizer is gone and must not come back — the `///` comments it
  used to strip are load-bearing, carrying the ontology's descriptions into Desktop.
- **`harvest-gold` brings Desktop and Fabric edits back into authored hub inputs (#744,
  DD-224).** A BI engineer opened the generated PBIP, hid a column, added measures — and
  the next `emit-gold` overwrote all of it. The only defences were to stop editing or to
  stop re-emitting, and both defeat the point of generating the model.
  `kairos-ontology harvest-gold <product> --from <exported model>` reads the edited model,
  diffs it against a fresh in-memory emit, and writes two review documents under
  `model/planning/gold-harvest/`: a Markdown report of everything that changed, and a
  Turtle snippet of the changes that have authoring vocabulary, grouped by owning domain.
  New measures arrive at DD-113 lifecycle `provisional`, carrying the author's own `///`
  description as the starting definition.
  **Nothing is applied.** Merging an edit into `model/extensions/` would make the hub's
  authored inputs a downstream artifact of a report, which inverts the ownership the design
  depends on. Tables match on the `Kairos_SilverBinding` annotation, columns and measures on
  `lineageTag` — which Desktop preserves across a rename, so a rename is reported as a
  rename rather than as a deletion plus an addition. A measure with no `Kairos_Lifecycle`
  annotation was not emitted by the hub, which is how a hand-added measure is told from a
  governed one. DAX is compared after normalising the reformatting Desktop applies, so a
  re-indented governed measure is not reported as changed.
- **`import-tmdl` harvests usage from the legacy report, not just the model (#744, DD-223).**
  The command turned the `.SemanticModel` half of a PBIP export into demand evidence and
  read nothing from the `.Report` half, where the reporting patterns live. It now writes a
  `<report>-report-usage.yaml` for every report folder with pages: which measures are
  actually *placed on a visual* rather than merely defined, which fields are used on
  slicers, a visual-type histogram and page names. That is the signal a model inventory
  cannot give — a legacy model typically defines far more measures than any report uses.
  DD-147's discipline is unchanged: derived counts only, no visual definitions, positions,
  filter values, titles, images, themes or connection strings, and the export still expands
  to a temporary directory. A visual whose JSON cannot be read is counted under
  `unreadable_visuals` rather than failing the import, because one bad visual out of 2,000
  must not cost the operator the other 1,999; a visual that parses but projects no field (a
  text box, a shape) is counted separately, so an annotated report does not read as a broken
  parse.
- **Personas, questions and KPIs are authorable, and `emit-gold` checks them (#744, DD-223).**
  A Gold product could be described completely without recording what anyone wanted to
  know, so report design started from the data that happened to be modelled rather than
  from the decision someone needs to make. `integration/discovery/bi/insights.yaml` records
  personas, their questions, the KPI that answers each, and the canonical measures and
  dimensions it needs. `emit-gold` reports which `confirmed` insights the product cannot
  answer yet and writes `<product>-insight-brief.md` beside the semantic model, grouped by
  persona. A measure still at DD-113 lifecycle `intent` does not count as answering
  anything, because it is deliberately not rendered into the model.
  A warning, never a gate: the gap between what the business wants to know and what the
  model answers is a backlog, not a build failure. A hub that authors no insights gets no
  brief and no warnings.
- **A Gold product can span ontology domains (#744, DD-222).** A semantic model was
  hard-wired to exactly one domain: product identity came from a single compile plan, every
  emitted path was derived from it, and any foreign key whose target class lived in another
  domain was dropped without a diagnostic. On a real reporting hub that meant a
  role-assignment fact carried a `legalentity_sk` to a sibling domain, `relationships.tmdl`
  carried only the intra-domain joins, and the column was dead — fixable only by a hand edit
  in Desktop that the next emit overwrote. Domains are a modelling boundary; analytical
  products follow business processes, with facts from one domain and conformed dimensions
  from several others.
  Declare one in `kairos.yaml`:
  ```yaml
  gold:
    products:
      - name: bookings-overview
        display_name: Bookings Overview
        domains: [booking, party, reference-data]
  ```
  `emit-gold bookings-overview` then compiles each listed domain — Silver compilation stays
  per domain, and each keeps its own provenance sidecar — and shapes them into one model, so
  the cross-domain join resolves. Every participating domain authors its own
  `<domain>-gold-ext.ttl` for the tables it owns, and a cross-domain relationship still needs
  its DD-138 `externalReference` in the binding.
  **Nothing changes for a hub that declares no product:** each Gold-configured domain stays
  its own product under its own name, with identical paths, manifest names and report
  contents. A single-domain product is the N=1 case of the same code path, not a second one.
  Moving a domain into a product retires its superseded per-domain emit, so fabric-cicd does
  not deploy the old model beside the new one.
- **A dangling Gold relationship is reported instead of dropped (#744).** Where the #207 fix
  skipped a foreign key whose target table was absent, `emit-gold` now lists it and records
  it in the product report as `unresolved_relationships`. It stays a warning, not an error:
  the model is valid without the join, and the fix is an authoring decision — add the owning
  domain to the product, or accept the column. This reverses the position taken in #661.
- **The Gold semantic model hides its technical columns, marks its keys, and carries the
  ontology's descriptions (#744, DD-221).** A `dim_customer` opened in Power BI Desktop
  used to show `customer_sk`, `country_sk`, `_source_identity_ref`, `_loaded_at` and
  `_kairos_fk_*_match_count` in the field list beside `customer_name` — half the table
  machinery — with no column marked as the key and no descriptions at all, even though the
  ontology's `rdfs:comment` already reached the physical plan. None of that was authored
  policy, so no hub could fix it.
  Columns are now hidden by their Silver column **role** (`source-identity`,
  `surrogate-join-key`, `entity-iri`, `audit`, `history`), not by name: the SCD history flag
  defaults to `is_current` with no underscore, and a business column may legitimately end in
  `_sk`. `foreign-key` is decided on provenance instead, because the compiler gives that one
  role both to the generated `{target}_sk` and to the mapped column its join reads from — so
  `country_code` stays visible while `country_sk` does not. Hiding is presentation only: a
  hidden column keeps its relationships, answers DAX, and can still be granted by a security
  role. `isKey` is emitted only for a dimension or bridge whose primary key is the Silver
  surrogate, because Power BI rejects a non-unique key at refresh in the workspace rather
  than at validation in CI. Column `rdfs:comment`s are emitted as TMDL `///`, so they reach
  Desktop's field-list tooltip.
  Every existing hub's TMDL changes on the next `emit-gold`; paths, manifests and the
  `.SemanticModel` layout do not.
- **`kairos-ext:goldHideColumn "Table.column"` (#744).** The authored escape hatch for a
  business-looking column a product does not want browsed. Repeatable on the `owl:Ontology`
  resource, case-insensitive on the table, and fail-closed as `gold.unknown-hidden-column`
  like `goldExcludeColumn` (DD-217) — a stale value after a Silver rename must not read as
  "successfully hidden" while the column is back in the field list. It hides; DD-217's
  `goldExcludeColumn` removes; `kairos-ext:securityPolicy` controls access.
- **A scaffolded hub now ships the toolkit's user documentation, and `update` keeps it
  current (#739).** `docs/guide/USER_GUIDE.md`, the eleven recipes under `docs/guide/how-to/`,
  `docs/guide/CLI_REFERENCE.md` and `docs/guide/CONSUMING_COMPILE_PLAN.md` existed only in this
  repository: not in the wheel, and not referenced by any scaffold file — so a hub operator
  asking "do we have any user guides?" found nothing, and a GitHub link would not have helped
  because client-side users do not necessarily have read access here. They are now copied
  into every hub under `docs/toolkit/`, with an index at `docs/toolkit/README.md` and a
  Documentation section on the hub README. They are **managed**, so hubs that already exist
  receive them — and later corrections to them — on `kairos-ontology update`, pinned to the
  toolkit version the hub runs. Namespaced under `docs/toolkit/` so they can never collide
  with documentation a hub writes for itself.
  Deliberately *not* shipped: the decision log, architecture record, DD-133, the practitioner
  guides, MDM material and the maintainer release process. Those describe the toolkit rather
  than how to operate a hub; the allowlist lives in `scripts/sync_dev_skills.py`, so adding a
  document to every client hub stays a deliberate act. Cross-links from the shipped guides to
  documents that stay behind were rewritten to absolute URLs, and a test now fails if a
  shipped guide gains a relative link to something the hub never receives.
- **`propose-relationships` matches endpoints through `rdfs:subClassOf` (#732).** Endpoint
  matching had two tiers — exact class URI, then a same-local-name heuristic across
  namespaces — so a hub that follows the prescribed pattern (subclass the reference-model
  class: `PortCallRecord ⊑ PortCall`) got no proposal for any blueprint bridge or
  reference object property whose endpoint is the reference class, unless the local names
  happened to coincide. DD-139 then told the author to "run `propose-relationships`" for
  entries it could not derive. A new `subclass` tier sits between the two: a binding whose
  `target.class` is an `rdfs:subClassOf` descendant of the endpoint class is a match, read
  from the same RDFS-profile index closure the compiler's endpoint check consults (#729), so
  what is proposed is exactly what compiles. Authored qname targets are expanded against the
  hub's own `@prefix` declarations, so a qname that denotes the endpoint class now counts
  as a `uri` match rather than a `local-name` one. A pair is reported as its *weaker*
  endpoint (`uri` < `subclass` < `local-name`), proposals order that way, and where several
  bound subclasses match one endpoint each is proposed — the author picks. The `local-name`
  heuristic remains as the last resort for hubs that mint an unanchored class.

- **`docs/` is split by audience: `guide/` for operating a hub, `dev/` for building the
  toolkit.** The two were mixed in one folder, so the user guide sat beside the 221-entry
  decision log and neither audience had an obvious entry point. `docs/guide/` now holds the
  user guide, how-to recipes, CLI reference, CompilePlan consumption, observability, the
  demo script and the practitioner guides — the same set shipped into hubs above.
  `docs/dev/` holds the decision log, architecture record, diagnostic codes, CLI behaviour
  notes, quality policies, roadmap, MDM design material and the release process.
  `docs/README.md` is now an audience-split index that states the rule for where a new
  document goes.
  The **two parallel DD stores are merged**: thirteen long-form design documents lived at
  `docs/design/dd-NNN-*.md` using the same DD numbers as the ADRs under
  `docs/design/decisions/`, with different slugs and no stated authority. The ten live ones
  are now `dd-NNN-<adr-slug>-companion.md` beside the record they expand; three whose
  decisions are formally superseded (DD-014, DD-025, DD-039) were removed, their records
  intact in the log. Also removed: the v4.7 medallion engineering guide and two completed
  migration notes.
  Four tracked ADRs cited change-request documents under `docs/temp/`, which is
  **gitignored** — those citations resolved only on the author's machine. They now cite the
  substance instead. New guards: no tracked document may link into `docs/temp/`, no relative
  link under `docs/` may dangle (eighteen broke during the move and nothing reported it),
  and a companion must sit beside a real decision record.

### Fixed
- **`scaffold-contract` refused the one blocked state it exists to resolve (#750).** A
  governed domain that gains a binding for a class its contract does not yet declare is
  blocked by `contract.class-not-declared` — and the command refused on `plan.blocked`
  without asking why, so the author could neither compile nor generate the entity block
  the diagnostic asked for. When that is the *only* blocking error it now proceeds (the
  shaped plan is intact behind it), printing which classes are undeclared. A new
  repeatable `--entity <class token or IRI>` scaffolds just those classes, so
  `--entity party:LegalEntity --dry-run` prints exactly the block to paste into the
  existing contract. Any other blocking error still refuses.
- **`init --domain` dropped a `.gitkeep` into populated publish slots (#755).** The
  comment said "empty publish subdirs" but nothing checked emptiness, so every domain
  registration on a hub that had already emitted added a stray tracked marker next to real
  `powerbi/` output. A slot is now only marked when it is genuinely empty; the directory
  itself is still created when missing. `init` and `new-repo` share the helper.
- **`guard-scope --check-since` consumed the token on success (#756).** A passing
  intermediate check deleted the snapshot the final check still needed. `--keep` retains
  it (rejected with `--snapshot`, like `--ignored-root` on the check side); the
  `kairos-design-domain` step-9 example uses it and says the last check may omit it.
- **`validate` failed without naming the failing section (#757).** The summary read
  `❌ Validation failed with 2 errors` and nothing else, so a reader scrolled back through
  every section to find the one that failed. It now reads
  `❌ Validation failed with 2 error(s): imports 1, decisions 1` followed by each failing
  section's first error message, and the imports section gained the
  `Imports — Passed: N, Failed: N` footer the decisions section already had.
- **`resolve-ontology <domain>` works from inside a hub (#759).** Every other inspection
  command accepts a bare domain name via `--domain`; `resolve-ontology` demanded a file
  path or `--catalog`, and the skill text told authors to run
  `resolve-ontology <domain> --json-output`. A bare name now resolves to
  `<hub>/model/ontologies/<domain>.ttl` when a hub is discoverable (`--catalog` stays
  optional — the loader finds `catalog-v001.xml` itself), and the error for anything else
  names all three accepted forms.
- **`explain-term` said a term "is not present in the closure" when the ERD draws it
  (#759).** The semantic index admits a class only when typed or on a `subClassOf` edge,
  while the ERD projector stubs any `rdfs:range` object, so a reader asking about a stub
  box was told it did not exist. The index is not widened; the message now says the term
  is not indexed in this closure but appears as the range/domain of `<property>`
  (declared in `<source>`), is drawn as a stub, and should be explained via its owning
  `--domain`. A term the closure never mentions keeps the original message.
- **`show-class-inventory` property links carried only a URI (#759).** Each
  `direct_properties`/`inherited_properties` entry was a bare `SemanticLink`
  (`uri`, `provenance`, `distance`), so a reader had to look every property up again to
  learn its name, kind, or range. The class slice now adds `name`, `property_type`, and
  `ranges` to each link, derived exactly as `list-class-properties` does. Existing keys
  are unchanged and `to_dict()` (closure hashes, determinism baselines) is untouched.
- **The canonical class diagram ignored a subclass's restriction on an inherited property and
  drew every `owl:inverseOf` pair twice (#753 P1+P2).** An inherited edge is rendered from
  the hub subclass, but its cardinality was read from the superclass that *declares* the
  property — so `:PortCallRecord rdfs:subClassOf [ owl:onProperty portcall:partOfVoyage ;
  owl:minCardinality 1 ; owl:maxCardinality 1 ]`, the one place a hub can tighten a
  reference-model property, was skipped and a mandatory single voyage rendered as `0..*`.
  Bounds now resolve from the drawn class, then its ancestors nearest-first, then the
  declaring class; the nearest restriction wins. Separately, `p` and its `owl:inverseOf`
  partner are both `owl:ObjectProperty`, so each produced an edge and one relationship drew
  as two arrows. When both directions are present between the same two classes they fold
  into one edge: the property whose IRI sorts first is the canonical direction and the label
  names both (`contactParty / hasPartyContact`); the partner's own restriction on the range
  class supplies the left multiplicity the forward property alone could never state.
  Part 3 of #753 (SVG rendering and the master class diagram) is not in this change.
- **The per-domain Silver ERD dropped every foreign key whose target lives in another domain
  (#754).** `_render_erd` only drew an edge when the referenced model was in the same plan, so
  a domain whose relationships are mostly cross-domain — invoices issued to a client — rendered
  as disconnected tables, and the master ERD was the only place the edge existed at all. The
  target is now drawn as a stub entity (`string external "model from another domain"`) and the
  edge labelled `[external]`, mirroring the declared-contract ERD; `_render_erd` stays a pure
  function of one plan. The master ERD, which has the hub-wide inventory, strips a stub and its
  `[external]` edge once the target's domain has been emitted so the real entity and the
  resolved cross-domain edge appear exactly once; a target no domain has emitted keeps its
  stub. The ERD is hashed into `{domain}-silver-parity.json`, so parity manifests of domains
  with cross-domain foreign keys change on the next emit.
- **`safety.column-unresolved` for a relationship `join.local` now says what would resolve
  (#751).** `join.local` is always the child's *source* column — the raw Bronze column for a
  `source.relation` binding, the contracted output column for `source.dbtModel`. Authoring a
  technical field's output `name` there (`voyage_source_id` instead of `JA_JV`) only appears
  to work on a dbtModel source because the two usually coincide; on a relation source it
  failed with a bare `does not resolve` and no hint. The diagnostic now names the resolved
  relation and its source kind, and either points at the source column the technical field
  binds (`'voyage_source_id' is the technical field name; join.local must be the source
  column -- use 'JA_JV'`) or lists up to eight candidate columns. Resolution semantics are
  unchanged; `kairos-design-mapping` now states the rule explicitly.
- **Name-based address detection redacted code, flag and type columns such as
  `AddressType` (#749).** `_kind_from_name` matched the `address` keyword as a bare substring
  of the camel-split column name, so CargoWise `E2_AddressType`, `PZ_AddressType`,
  `OA_AddressMap` and `OA_SuppressAddressValidationError` — none of which holds an address —
  had every sample value and every `kairos-bronze:sampleValues` literal replaced by
  `<redacted kind=address …>`. On the Fracht hub that hid the 13-value document-address role
  code vocabulary a party-role binding must map. The name rule now stands down when the
  column's own tokens carry a code/flag/type discriminator (`type`, `code`, `kind`, `map`,
  `suppress`, `validation`, `validate`, `error`, `flag`, `id`, `key`, `count`, `status`);
  `Address1`, `StreetAddress`, `postal_address` and `HasAddressOnFile` are unchanged, and a
  shaped value (email, IBAN, phone, long id) in such a column is still caught by value
  detection. The guard reads the name only — never the datatype (#672) — so the redactor and
  the persistence gate keep agreeing, and it is scoped to `address`: the art. 9 keywords
  disclose through a flag too, and `EmailId` routinely holds the email itself. There is no
  value-shape detector for postal addresses, so a street address typed into an `AddressType`
  column is not caught; the name rule was the only address detector.
- **The passthrough staging scaffold copied credential, payroll and personal-data columns
  verbatim (#758, #760, #761).** `scaffold-binding --archetype passthrough`,
  `scaffold-staging` and `scaffold-system` rendered one `select` line per Bronze column with
  no privacy awareness at all, so `GS_PasswordHash`, `GS_WagesBankAccount` and a birth date
  landed in a dbt model nobody had reviewed. All three now partition columns through the
  DD-075 `is_pii_column` policy (plus the import redactor's own `<redacted ...>` verdict):
  personal-data columns are left out of the `select`, the stage properties YAML and the
  merged model's common columns, named in the SQL header as
  `-- excluded by privacy policy (pass --include-pii to keep): ...`, and reported in the
  result notes. A new `--include-pii` flag on all three commands restores them. The shared
  `PII_KEYWORDS` list gains the credential and payroll terms it was missing (`password`,
  `sql_login`, `bank_account`, `wages`, `salary`, `emergency_contact`, `residency`,
  `security_card`, `birth_date`), deliberately without the broad tokens (`hash`, `bank`,
  `login`) that would fire on `geohash` or `login_count`.
  Alongside: `dbt-contract.dialect-fabric-nested-cte` reported only a count, so an author
  whose comments said "with" twice went hunting for a CTE that was not there — it now lists
  the 1-based line of every occurrence and says the scan includes comments, and the scaffold's
  new header is pinned by test to spend none of the one allowed `with `. The scaffolded
  `deploy-powerbi-semantic-model.yml` fell back to `github.token` for cross-repository `gh`
  calls against the hub, which cannot read a private sibling and only surfaced later as
  "release not found"; it now fails fast by name when `HUB_REPO_TOKEN` is missing and never
  falls back, and `pr-validate.yml`'s "assuming a public hub package" message says what a
  private-hub operator will see and which secret to add. The scaffolded
  `profiles.yml.example` activated `authentication: ServicePrincipal`, which dbt-fabric 1.11
  rejects outright (and whose accepted `ActiveDirectoryServicePrincipal` spelling appends
  `Authority Id=`, which the mssql-python driver refuses); it now uses
  `authentication: environment`, reads `AZURE_TENANT_ID`/`AZURE_CLIENT_ID`/
  `AZURE_CLIENT_SECRET` from the environment, and lists the accepted spellings.
- **The TMDL parser could not read bare flags, annotations or `///` descriptions (#744).**
  `isKey` and `isHidden` are written with no value, and the reader only handled
  `key: value` lines, so neither was visible; `annotation X = "..."` has no colon and was
  skipped entirely; `///` doc comments — which is how TMDL actually carries a description —
  were skipped in every block; and an `annotation` following a multi-line measure was
  swallowed into the DAX expression. All are now parsed, which is what makes a round trip
  from an edited model possible at all.
- **Legacy measure names reached the conformance judge as stringified dicts (#744).**
  `bi_demand_terms` normalised each measure with `_norm(measure)`, but `import-tmdl` writes
  measures as `{name, expression, format_string}` mappings, so the whole dict was
  stringified and no measure name could ever match a concept. The BI demand signal was
  silently empty for every worksheet the toolkit itself produced.
- **The scaffolded hub README told operators to run `compile <domain> --emit`, which the CLI
  rejects (#739).** `--emit` has required `--confirm-emit` since #264, and
  `test_scaffold_emit_invocations_pass_confirm_emit` exists to catch exactly this — but it
  filtered on `Path.suffix`, which for `README.md.template` is `.template`, not `.md`. Every
  `*.md.template` in the scaffold was therefore exempt, including the two READMEs a new hub
  operator reads first. The check now matches on the last two suffixes, and the three bare
  invocations it found (the repo README, the hub README, and the user guide) are fixed.
- **Gold contract errors reach the compile report under their own code and file, and
  `emit-gold` no longer claims success before it has written anything (#748, #752).**
  A `GoldContractError` raised while shaping the project was flattened into
  `safety.type-incompatible` at the hub root with `projection normalization failed:` in
  front of the real text, so a `gold.source-version-drift` told the author neither which
  rule fired nor which file to edit. The kernel now reports it under its own `gold.*` code
  and `DD-112` rule, located at `model/extensions/<domain>-gold-ext.ttl`; the plan stays
  blocked. The drift message itself now names the Gold table, its Silver model and the
  domain, and says where the pin lives. On `--confirm-emit`, `emit-gold` printed
  `✅ Emitted …` before calling `emit_artifacts`, so a failed swap left a success line
  directly above the error; the line is now echoed only after the write commits. The
  backup rename in `_commit_stage` raised without the Windows sharing-violation hint the
  stage-to-target swap already carried; both branches now carry it, and the hint names the
  Gold lane's usual holders — Power BI Desktop with the emitted `.pbip` open, or a shell
  whose current directory is inside the target. `kairos-design-domain` step 9 now warns
  that bumping `owl:versionInfo` invalidates every `goldSourceVersion` pin and allows the
  Gold extension in its `guard-scope` example.

### Changed
- **`owl:equivalentClass` is no longer presented as a compile-time anchor (#730).**
  `integrity.class-unanchored` accepted a local class anchored to a reference class by
  `owl:equivalentClass`, and its remediation recommended it alongside `rdfs:subClassOf`. The
  compiler never read it: symbol resolution runs under the DD-103 `rdfs` profile, where
  `equivalent_classes` is empty, and inherited properties and relationship endpoints resolve
  through `rdfs:subClassOf` alone. An author following the guidance got a green integrity check
  and a binding that inherited nothing. Equivalence is symmetric — "two URIs, one class" — and
  honouring it faithfully would reach the identity, conformance-grouping and artifact-ownership
  sites where subsumption is deliberately not applied, so this is not widened the way #729 was;
  no hub on record uses it for anchoring (the only `owl:equivalentClass` in reach are IATA
  `owl:oneOf` enumerations and vendored schema.org mappings). Now: `integrity.class-unanchored`
  counts `rdfs:subClassOf` only and its remediation says so (the shadowing check and the
  `class-anchoring` suggestion report read the same anchor set, so such a class now receives an
  anchor suggestion); the validator emits a new warning,
  `class_equivalence_not_a_compile_anchor`, on a local class that asserts `owl:equivalentClass`
  to a *named* class (blank-node enumerations are untouched), pointing at the two anchoring
  moves that work — subclass the reference class, or bind it directly (DD-144). The triple
  itself remains legal; the logistics blueprint's "add equivalence for cross-model querying" is
  a downstream graph-query concern and is unaffected.
- **BREAKING for hubs with SHACL shapes on reference-model classes: `sh:targetClass` now
  applies to subclasses (#729).** `_extract_shacl_tests` matched `sh:targetClass` by exact
  URI, so a NodeShape declared on a reference class (`sh:targetClass dcsa:TransportEvent`)
  contributed **no** dbt tests to a hub model bound to a subclass
  (`:LocalTransportEvent rdfs:subClassOf dcsa:TransportEvent`) — silently, with no
  diagnostic. That is exactly the shape the `kairos-design-domain` exemplar prescribes
  (governance rules on the reference class, local rules on the subclass), so the exemplar's
  own closed-code-list and mandatory-timestamp tests were never emitted. SHACL semantics say
  `sh:targetClass C` targets instances of `C` *and of its subclasses*. The projector now walks
  `rdfs:subClassOf` upward (asserted, transitive, via the new `projections.shared.class_ancestors`)
  and applies every ancestor's shapes, **nearest first**, so when a child shape and a parent
  shape constrain the same path the most specific one wins — deterministically, where
  before rdflib iteration order would have decided. Shapes with no `sh:targetClass` keep
  applying to every class, as before. **Migration:** subclass models may gain `not_null`,
  `unique`, `accepted_values`, regex or length tests they did not emit before. A build that
  turns red after upgrading is reporting a governance rule that was declared but never
  checked — fix the data or narrow the shape; do not delete the test.
- `ResolvedProperty.range_uri: str` is now `range_uris: tuple[str, ...]` and `ResolvedClass`
  gains `ancestor_uris` (internal compiler API; see Fixed).

### Fixed
- **Multi-inheritance classes lost Silver columns; `owl:Thing` as a first parent truncated
  inheritance (#733).** `_get_class_and_parents` in the dbt projector walked the class hierarchy
  with `graph.value(current, RDFS.subClassOf)`, which returns *one* object — so a class declared
  `rdfs:subClassOf :B, :C` contributed only one parent, chosen by rdflib iteration order, and
  a W3C parent (`owl:Thing`, as Protégé-style exports assert on every class) `break`-ed the
  walk before any real parent was seen. The set it returns decides which properties become
  Silver columns (and feeds FK inference, merge type maps, natural-key resolution and
  own-vs-inherited warnings), so the columns inherited through the unvisited branch were
  silently absent from the emitted model. Now delegates to the shared, cycle-safe
  `projections.shared.class_ancestors` (all named parents, transitive), dropping W3C classes
  from the result without stopping the walk. Models for multi-inheritance classes may gain
  columns they should always have had.
- **`safety.relationship-endpoint` rejected a relationship whose `target:` is a subclass of
  the property's declared `rdfs:range` (#729).** The guard compared the single resolved range
  URI with the authored target by strict equality, so a hub that followed the prescribed
  pattern — subclass the reference-model class — could not author any inherited object
  property whose range is a reference class the hub also subclasses (`partOfVoyage` from
  `PortCallRecord ⊑ PortCall` to `MaritimeVoyageRecord ⊑ Voyage`: sound OWL, hard error). The
  target is now accepted when it *is*, or descends from, **any** of the property's named
  ranges. Downward only — a *superclass* of the range still fails — and `owl:Thing` is kept out
  of the ancestor closure so `rdfs:range owl:Thing` remains rejected (#330) even for exports
  that assert `rdfs:subClassOf owl:Thing` on every class. Three things the issue got wrong,
  recorded so they are not re-filed: the **domain** side never had this defect
  (`ResolvedProperty.domain_uris` is the set of classes that *expose* the property, inherited
  included — DD-133 §8b — not `rdfs:domain`, so the hub subclass was already a member); the
  fix could not live at the check site as suggested (`ResolutionContext` is graph-free by
  design, so the ancestor closure is now carried into `ResolvedClass.ancestor_uris` at
  symbol-resolution time, populated on all three construction paths including DD-144
  accelerator-direct and the cross-domain fallback); and the check must accept **any** range,
  not all — ranges are superproperty-widened and URI-sorted, so the old `ranges[0]` was
  deterministic-but-arbitrary, and intersection semantics would newly reject reference models
  that omit the subsumption chain between a subproperty's range and its parent's (#731 tracks
  that as a validator warning). `propose-relationships` still matches endpoints by URI or
  local name, so DD-139's "run propose-relationships" remedy cannot derive these entries until
  #732 lands.

## [5.15.0rc17] — 2026-09-05

Covers **rc14 through rc17**. The rc14, rc15 and rc16 bumps shipped without promoting
`[Unreleased]`, so their changes had accumulated here unlabelled; everything recorded
under this heading landed across those four release candidates rather than in rc17
alone.

### Added
- **Emitted artifacts carry their own provenance (DD-218, #716).** Every emit now writes
  `metadata/<domain>.provenance.json` — and `metadata/<domain>-gold.provenance.json` for a
  Gold product — recording the toolkit version, adapter, `apiVersion`, namespace, the
  `BuildScope` provenance hash, and a sha256 for every authored input in the build. The
  manifest recorded one digest per file *written* and nothing about what those bytes were
  computed *from*, so a dataplatform repository could not tell which ontology and bindings
  produced a package without reconstructing it from whichever revision it happened to pin.
  It is an ordinary artifact rather than manifest metadata because the manifest rejects any
  key outside `{"files", "schema"}` — extending it fails closed on an older toolkit reading
  a newer publish tree — and because emission writes four manifests over disjoint sets, the
  shared one last-writer-wins across domains. No wall clock and no Git revision, so
  re-emitting unchanged inputs is byte-identical.
- **Task how-to guides (#719).** Twelve recipes under `docs/guide/how-to/`, one per lifecycle
  stage, each naming the skill that automates it. `tests/test_how_to_guides.py` resolves
  every `kairos-ontology ...` line in them against the real command tree — command,
  subcommand and every long flag — so a renamed flag breaks the build rather than the
  reader, and executes the create-a-hub recipe end to end.
- **A generated CLI reference (#718).** `docs/guide/CLI_REFERENCE.md` is now produced by
  `scripts/generate_cli_reference.py` from the Click tree: all 88 commands with usage,
  arguments, options and defaults. The hand-written file it replaced had fallen 14 commands
  behind. `tests/test_cli_reference_is_current.py` fails when the file and the CLI disagree.
  The behaviour essays it used to carry moved to `docs/dev/cli-behaviour-notes.md`.

### Changed
- **Scaffolded guidance is toolkit-managed (DD-219, #717).** Eleven per-directory `README.md`
  guides under `ontology-hub/` and `.import/` were written once at `init` and then frozen —
  half the scaffold's documentation lines could only ever be corrected in hubs created after
  a fix. They are managed now, so `kairos-ontology update` delivers corrections. `init` and
  `new-repo` stamp what the toolkit owns, without which a brand-new hub failed the
  `update --check` that `managed-check.yml` runs on every pull request.
  `decisions/index.md` and `.import/modeling/feedback/index.md` stay unmanaged on purpose:
  they are regenerated from the hub's own records, and managing them would overwrite an
  accumulated log.
- **A hub receives 21 skills instead of 26 (DD-219, #717).** `kairos-toolkit-dev` and
  `kairos-toolkit-dogfood` are maintainer activities aimed at this repository — dogfood is
  explicitly adversarial — and were selectable by an agent working in a client hub.
  `SC-merge-pr` documents this repository's own release process and shipped carrying a
  paragraph telling the reader not to apply it there; `SC-document` drives a Cnext Outline
  workspace. `kairos-design-mdm` is withheld while MDM is designed but not adopted, and
  returns when it goes live. `kairos-toolkit-ops` deliberately still ships.
- **The decision log is one file per decision (#713).** `toolkit-design-decisions.md` had
  reached 15,680 lines across 217 entries: too large to load as context, and every new
  decision appended at EOF so two branches adding one always conflicted. The file keeps its
  path as the index; entries live in `docs/dev/decisions/`. Adding a decision now creates
  a file, so the only possible collision is an adjacent index row.
- **The repository has an LF line-ending policy (#714).** No `.gitattributes` and
  `core.autocrlf=false` meant committed bytes were whatever the writing tool emitted; the
  tree had drifted to 390 CRLF and 534 LF files, with two carrying both internally. The
  toolkit already shipped this fix to every scaffolded hub (issue #699) while running
  without it. The renormalisation is listed in `.git-blame-ignore-revs`.
- **Architecture and roadmap are separate documents (#715).** 302 of the architecture
  document's 709 lines were a delivery plan; they moved to `docs/dev/roadmap.md`.

### Fixed
- **A qname parent class no longer breaks relationship proposals (#724).** `target.class`
  may be authored as a full URI, a `prefix:Local` qname, or a bare local name — the
  canonical example uses the qname form — but `propose-relationships` resolved it with
  `_local_name`, which splits on `#` and `/` only and hands a qname straight back. Two
  consequences, the second worse than the first. `externalReference.name` slugged
  `party:Customer` to `party_customer` while the compiler, which slugs the *resolved*
  class, emits `customer` — so the pasted `ref()` named a model that never exists, and
  `externalReference` deliberately skips model-existence checking, so nothing failed
  closed. And the endpoint index keyed the same authored token, so a hub authoring its own
  class as a qname against a blueprint declaring a full URI matched nothing at all and the
  bridge produced **no proposal whatsoever**. Both now route through DD-220's
  `_class_token`.
- **`propose-relationships` no longer re-proposes what a binding already authors
  (DD-220, #722).** The command counted a binding's `relationships:` entries but never
  read them, so on a real 33-binding hub five of eight resolved proposals were verbatim
  re-renders of entries already present — and because the rendered YAML hard-codes
  `cardinality`, `mode`, `missingParent` and `ambiguousParent`, pasting one back as the
  docs instruct replaced a deliberate, commented `missingParent: null` with `error`,
  turning a tolerant lookup into a hard load failure for exactly the five uncatalogued
  code types the comment named. A `(property, target)` pair the child already authors is
  now skipped outright: counted in the header, listed under `already_authored` in JSON,
  and never rendered, so there is nothing to paste over the author's policy.
- **A child's own identity column is no longer matched as a join key (DD-220, #722).**
  The tier-1 rule tried the child's `identity.sourceKey` columns first, so a hub using one
  uniform surrogate identity name proposed `source_record_id = source_record_id` — a row
  joined to itself across two relations — for every pair of relations, while ignoring
  `parent_invoice_source_id`, the real FK. A candidate that constitutes the child's
  *entire* identity is now excluded from name matching. Narrower than excluding every
  identity column on purpose: a line-item child keyed `[order_id, line_no]` still
  contributes `order_id`.
- **`purpose: relationship` is now a join signal instead of being discarded (DD-220,
  #722).** The annotation DD-139 makes authors write, and that
  `relationship.unrealized-technical-field` points at this command to resolve, was parsed
  out of the binding and thrown away before the matcher ran — so the command picked the
  wrong column precisely in the cases the warning asks it to fix. Declared carriers are now
  tried first (tier 0, reported as `join_evidence: "declared-fk"`) and are exempt from the
  identity exclusion above; one that names no parent key is surfaced as a `join_candidates`
  hint on the unresolved proposal rather than forced into a join. The text header now also
  states how many proposals carry a resolved join, and `SCHEMA_VERSION` is 2.
- **The compile provenance hash is now stable across platforms (#716).** `provenance_hash`
  covers each input's *name*, and two of the six `ProvenanceInput` sites did not normalise
  path separators — so on Windows bindings, source vocabularies and ontologies entered the
  hash as `integration\bindings\...` while templates entered as `templates/...`. The same
  hub hashed differently per platform, quietly undermining the reproducibility a pinned
  release tag is supposed to provide. Linux digests are unchanged; Windows now agrees with
  them.
- **DD-213's recorded status matched reality (#715).** It was logged as `Proposed`, and its
  companion opened with "Nothing in this document is implemented", while Gate A had shipped:
  four compiler modules and 24 `contract.*` diagnostics. Gate B genuinely is not built. A
  record claiming a shipped feature does not exist tells an agent to build what is already
  there.
- **The dataplatform's `CICD.md` no longer shows an unsubstituted `{ORG}` (#717).** It is
  written by the verbatim managed-file copy, so the placeholder reached clients as literal
  text telling them to pin `https://github.com/{ORG}/kairos-ontology-toolkit`.
- **`scripts/sync_dev_skills.py` runs on a Windows console (#717).** It printed a non-ASCII
  status mark and died with `UnicodeEncodeError` under a legacy code page — which is where
  the pre-commit hook runs it.
- **Four decision-log index rows disagreed with the entries they point at (#713).** Git
  history confirmed the entry bodies were right; DD-077, DD-091, DD-185 and DD-186 are
  corrected. The old consistency test compared titles only and never checked status or date.
- **Six committed `.orig` merge artefacts are gone (#714).** Stale snapshots of live source,
  indistinguishable from real code to anything grepping the tree. `*.orig` and `*.rej` are
  now ignored.
- **A conformance `UNION` now carries the width its branches declare (#681).** A class's
  published column type silently widened the moment it gained a second source —
  `string(50)` on every branch emitted as unsized `string` on the union, with no ontology
  change, no binding change and nothing to review. The width only ever existed on the
  mapping expression's resolved output type, so it is recovered from the union's own
  branches. Branches that genuinely disagree are reported as the new
  `conformance.type-parameter-incompatible` rather than resolved by widest-wins, since
  picking a width on the author's behalf is the same silent change this removes.
- **`scaffold-contract` no longer generates a contract that fails its own compile gate
  (#697).** It classified columns by `role` alone, but the kernel stamps `foreign-key` on
  whatever `relationships[].join.local` names — conflating an authored DD-139 technical
  field, an ordinary mapped field, and the compiler's own generated columns — then zipped
  them positionally against the authored relationships. Adoption failed for *any* binding
  declaring a relationship. The declaring surface now owns the column, and
  `relationships:` declares the `(property, target)` pair only. A grain stated on such a
  column also stopped `scaffold-contract` raising outright.
- **`import-source` publishes everything or nothing (#688).** A fail-closed privacy
  refusal on table N used to leave every vocabulary written, every relation marked
  deprecated, and a handful of samples on disk — a state no command produces deliberately.
  Samples are now sanitized before anything is written, and both publication stages go
  through the staging helper `source-privacy --fix` already used.
- **`project` writes LF on every platform.** `Path.write_text` rewrote LF to CRLF on
  Windows, so byte-identical projector output landed differently per platform and churned
  `git diff` on every regeneration. `compile --emit` was never affected; it writes bytes.
- **The concept-mapping triage count can reach zero (#687).** It counted a row untriaged
  on an empty `reference_model_match` and never read `action`, but `skip` and `new_class`
  never carry a match — so every decision a modeler recorded left the number unchanged and
  `next` recommended triage forever. Split into an *untriaged* count (drives `next`) and an
  *unfilled* count (absence of BI weight evidence, reported by `design-landscape`).
- **`kairos-design-source` documents a `check-ai-config --role` the CLI accepts (#689).**
  The role was folded into `alignment` by #562; the documented DD-159 preflight had been
  exiting with a usage error, whose natural workaround is to skip the preflight entirely.
- **The scaffolded PR gate can now fail (#686, #699).** `validate-dbt --structural-only`
  stops after the ref scan, so a project `dbt parse` refuses passed every step; the full
  offline gate now runs, with the adapter extra resolved by the toolkit rather than
  composed. The drift gate also failed open — `git diff --exit-code -- <path>` exits 0
  when nothing at that path is tracked — and now asserts tracked-ness first.
- **A dataplatform `_sources.yml` binds what it claims to (#701).** Without
  `overrides: <package>` a same-named root-project source is a second, unrelated node:
  dbt parses cleanly and the hub's models keep resolving to the hub's own placeholder
  database until `dbt run` reports a missing relation. Emitted now, and
  `validate-source-bindings` fails when a shadowing source omits it.
- **`bump-hub` and staleness checking work on GitHub Enterprise Server (#702).** The pin
  parser hardcoded `github.com`, so a GHES pin matched nothing — and
  `validate-source-bindings` swallowed the resulting error into "0 stale", switching a
  fail-closed DD-206 gate off with nothing in the output.
- **The scaffolded dataplatform PR workflow can be installed (#705).** An unquoted step
  name made it invalid YAML, so GitHub Actions rejected the whole file; `--refresh-workflows`
  declined to install it; the offline fabric profile used an authentication value dbt-fabric
  rejects; and `dbt compile` cannot run credential-free against dbt-fabric at all.
- **`propose-alignment` no longer leaves a contradictory alignment file behind (#696).**
  Declining to write a fallback-only domain left the previous file standing, describing
  tables that no longer exist — on one hub the sole source of 23 validation errors long
  after every other domain had been regenerated.
- **Langfuse says when it is off (#694).** Credentials set but the package missing logged
  at `info`, which the default level hides, so an explicit request for tracing was dropped
  in silence. Now a warning, and reported by `check-ai-config` before a long stage rather
  than during one. Long stages also stream: stdout is line-buffered, so a piped run no
  longer emits zero bytes for 26 minutes.
- **`safety.prefix-ambiguous` names the files that declare the colliding prefix (#699).**
- **A canonically-BOOLEAN expression is now rendered per adapter in predicate and value
  position (DD-215).** Fabric maps BOOLEAN to `BIT`, and T-SQL rejects a bare bit column
  wherever a condition is expected. The DD-107 typed AST did not prevent this: a bare
  source column bound to a bit column *is* canonically BOOLEAN, so it satisfied the type
  gate for a `CASE WHEN` condition, an `AND`/`OR`/`NOT` operand, or a `rowFilter`, and
  then rendered unwrapped. The guard had been placed in typing, but this is a rendering
  concern. Also fixes the mirror case — a native predicate such as `(a IS NULL)` in a
  select list, which T-SQL rejects too. Reported from a client hub whose
  `silver.partyrole` could not build.
- **`compile --emit` survives a transient Windows sharing violation, and explains itself
  when it does not.** Total backoff on the staged directory swap was 0.75s, inside the
  window an antivirus or sync client typically needs to release files `copytree` created
  microseconds earlier; it is now ~5.4s. Only `PermissionError` was retried, so
  `ERROR_DIR_NOT_EMPTY` (WinError 145) — exactly what a directory rename raises when a
  handle is open inside it — got zero attempts, and the pre-swap and rollback renames had
  no retry at all. The error now names the blocked path and the usual holders, including a
  `--log-file` pointed inside the emission target.

### Changed
- **The target platform names the engine, not the vendor (DD-215).** `adapter:` in
  `kairos.yaml` is now `fabric-warehouse` or `databricks`. `fabric` still resolves, with a
  deprecation warning; `fabric-lakehouse` is recognised and **rejected** rather than
  compiled as T-SQL, because it is Spark SQL and there is no profile for it.
  `init`/`new-repo` gain `--adapter`, so a hub is no longer born `fabric` from a hardcoded
  template line with no flag to change it, and `init-dataplatform --platform` uses the same
  vocabulary instead of a parallel one that collapsed into it via a bare `else`.
  `validate-dbt` defaults `--platform` to the hub's own adapter instead of ignoring it.

  **This requires one re-emit per hub.** The adapter is part of `BuildScope`, so it feeds
  the provenance hash; each hub's `pr-validate.yml` drift check will fail until it runs
  `compile --all --emit --confirm-emit` once. Authored `fabric` in `kairos.yaml` and in dbt
  contracts' `supported_adapters` keeps working.

### Added
- **The canonical ERD renders inherited content (#678, #704, DD-212 amended).** For a hub
  whose classes specialize imported reference models — the style `kairos-design-domain`
  recommends — the diagram discarded nearly everything: on a real hub 1 of 29 inheritance
  edges and 63 of 237 datatype properties rendered, leaving DD-212's stated reason for
  choosing `classDiagram` inert. Scope is now *reachability* rather than the namespace: an
  out-of-namespace class is drawn as a stereotyped stub where a domain class inherits from
  or references it, inherited attributes appear on the subclass prefixed `#`, and an edge
  survives when either end is domain-local. The header states what it omits.
- **`project --target contract-erd` diagrams the declared Silver contract (#698, DD-216).**
  The contract sits between the ontology and the bindings, both of which already had a
  diagram; it was the one layer you had to read as raw YAML, and it is the published
  promise. Renders `requirement`, declared nullability, `stability`, `closed`, per-column
  deprecation and cross-domain reach — none of which the emitted-Silver ERD can express.
- **`kairos-ext:goldExcludeColumn` keeps a column out of a Gold product (#703, DD-217).** A
  Gold dimension mirrored its Silver model's full column set, so PII reaching Silver for
  legitimate operational use also reached Power BI with no authorable way to stop it.
  Fail-closed: a value that excluded nothing is rejected, so a Silver rename cannot
  silently re-expose the column.
- **Scaffolded hubs get a `.gitattributes`, and `update` reports Git-hygiene gaps (#699).**
  Without it a contributor on `core.autocrlf=true` sees the whole tracked publish tree as
  modified after an emit. `.gitignore` was written only at scaffold time, so a hub
  predating a rule never received it while `update --check` reported everything up to
  date — including the block whose purpose is keeping client evidence out of Git. Both are
  additive-only: created when absent, otherwise the missing rules are reported, never
  overwritten.
- **`dbt-contract.dialect-*` lint findings, and the guidance that prevents needing them
  (DD-215).** `validate-dbt-contracts` now checks authored model SQL against the hub's
  adapter and runs in hub CI, where it was absent. The one rule today is `dbt-fabric`'s
  nested-CTE detector, which counts the substring `"with "` across the whole file including
  comments rather than parsing. `kairos-develop-dbt-transformation` now states the target's
  dialect rules — it previously never mentioned T-SQL, dialect, platform, or Fabric at all,
  so the skill writing the SQL was never told what engine it was writing for. The complete
  gate is `dbt build --empty` on the dataplatform's `bump/hub-*` PRs, now documented in
  `CICD.md`: it runs every model at `limit 0`, and is the only check that catches dialect
  errors, since dbt hands a model body to the engine verbatim.
- **Sample redaction is now opt-in on every import path (DD-214, issue #692).**
  `extract-schema`, `import-source` and `import-flatfile` write sample values as-is
  unless `--redact-pii` is passed. The control was costing more than it bought: a
  74-table client bronze profile was refused over 2197 NULLs across 136 columns
  with zero real values among them (and aborted mid-write, leaving 77 files created
  and 76 modified), while money, datetime and business-ID columns reached the
  vocabulary TTL with *zero* sample evidence mislabelled `kind=phone` — with no
  privacy upside, since the real values sat unredacted in the sibling
  `.samples.yaml` in the same directory. Sample values are the evidence binding
  design reads, and the detector accepts over-redaction by design (DD-075).

  Both halves matter and neither alone suffices: `extract-schema`'s default is what
  stops redaction at the warehouse boundary, while gating `import-source` is what
  recovers the false-positive damage, since money and date values already survived
  the per-value pass and were destroyed later by `sanitize_vocabulary_graph`.

  `extract-schema --no-redact-pii` (shipped in 5.15.0rc12) is kept as an accepted
  no-op, since it now asks for the default.

  **Accepted consequences, stated plainly:** committed artifacts under
  `integration/sources/**` may contain raw client PII and enter the client's git
  history — the exact condition DD-205's authorization rested on — and sample values
  may reach the configured AI provider unredacted. No automated control remains;
  `source-privacy` stays available as a deliberate audit and `--fix` step.
- **`analyse-sources` reports unredacted findings instead of refusing (DD-214).**
  Refusing is no longer coherent once redaction is opt-in: a hub that deliberately
  keeps raw samples could not run the command at all. The scan still runs before the
  provider call and still reports paths and kinds only, never a value.

### Fixed
- **`source-privacy` would have been permanently red for a hub that opted out
  (issue #692).** It never read `sample_privacy.policy`, so there was no way to
  record that an exposure was intended, and the new `analyse-sources` advisory would
  have fired on every run forever. Findings in artifacts that *declare*
  `policy: none` are now reported as acknowledged rather than as failures. A missing
  `sample_privacy` block is deliberately **not** treated as consent — hand-authored
  and pre-policy artifacts have none either.
- **`--emit-seed` could have put raw client rows in a tagged GitHub Release
  (issue #692).** `seeds/` is not gitignored, and the emitted copy under
  `ontology-hub-publish/medallion/dbt/` is explicitly *un*-ignored and packaged into
  a Release by `release-projections.yml`. `--emit-seed` now requires `--redact-pii`
  and refuses before connecting to the warehouse; its help text no longer claims the
  samples are redacted.
- **The `" | "` sample-value delimiter became injectable from client data
  (issue #692).** Redaction tokens are delimiter-safe by construction, so this never
  mattered while every published value was a token — but a raw value containing the
  separator (an invoice note, a concatenated address, a CSV-in-a-cell) would split
  into sample values that were never in the source, indistinguishable from real ones,
  across all four consumers that split it: affinity, alignment, the source catalog
  and the silver audit. `join_sample_values` now substitutes the separator inside
  values, and the separator lives in one constant instead of ten literals.
  `enumValues` also gained the `distinct_samples` cap that `sampleValues` always had.
- **`audit-column-coverage` printed a raw sample value to stdout and `--format json`
  (issue #692).** With redaction off by default that would land client data in
  terminals, agent transcripts and CI logs. It now redacts unconditionally,
  per-value, so money, dates and identifiers survive intact and only a genuine
  detection becomes a token.
- **`import-source` could leave a plaintext copy of every table's samples in the OS
  temp directory (issue #692).** Directory-mode import writes a combined YAML with
  `delete=False`, and cleanup sat on the success path only — so any exception left
  client data outside the hub, where no gitignore or hub policy reaches it. Now in a
  `try/finally`.
- **Artifacts stamped a redaction policy they had not applied (issue #692).** Three
  of four writers hardcoded `policy: redact-detected-pii`. All now record the policy
  that actually ran, and omit the policy *version* when no policy ran — the same
  overstatement DD-075's first amendment exists to prevent.
- **A NULL in a PII-named column was reported as unredacted PII, and the report could
  not be cleared.** `detect_sample_pii_kind` ran `_kind_from_name` before it looked at
  the value, so `GS_HomePhone = NULL` was convicted on the column name alone. The
  verdict was unfixable by construction: `redact_sample_value` returns NULL untouched,
  so the residual check in `sanitize_samples_document` re-raised on the same cells and
  `source-privacy --fix` spun without converging. `import-source` therefore refused an
  extract that was already fully redacted — a 74-table client bronze profile was
  blocked by 2197 NULLs across 136 columns, with zero real values among them. Worse,
  the refusal happened mid-write: 77 files had already been created and 76 modified
  before the gate fired, leaving the hub's source directory in a partially-imported
  state. Absent values (NULL, blank string, empty container) are no longer classified;
  `0` stays in scope, because it is a value rather than an absence.
- **`update --check` reported the same `.claude/settings.json` finding differently on
  Windows and Linux, and only Windows overwrote the file (issue #684).** Three entries in
  the known-generation table were LF hashes; the fourth was the CRLF rendering of the
  pre-#659 generation. Since the comparison hashed raw bytes, a hub carrying that
  generation was classified by line ending rather than by content: Git for Windows checks
  out CRLF, so `update --check` exited 1 there and 0 on Linux for the identical commit,
  and only the Windows path went on to replace the file. Hashes are now LF-normalized --
  the same normalization the retired-managed-file loop already applied -- and the entry is
  corrected. Note the consequence: hubs still holding the pre-#659 generation will now be
  advanced on **every** platform, which is the #659 fix being delivered rather than a
  regression. Those twelve `Read(...)` deny rules are the pre-#659 shipped file verbatim,
  not local customization, and #659 removed them because denying `Read` also disables
  `Edit`, making `kairos-design-domain`'s authoring steps impossible. A genuinely
  hand-extended settings file still matches no known hash and is still left alone.
- **A `.claude/settings.json` refresh described the wrong change, and dropped deny rules
  silently (issue #684).** All four report sites hard-coded one sentence about the DD-103
  boundary being "broadened (.ttl/.rdf/.owl, not just .ttl)" — true only of the oldest of
  four registered generations. A hub on the #659 generation was told its pending change
  concerned file extensions when it was actually the removal of twelve `Read` denies,
  which is why the overwrite read as destroying local edits. The table now maps each
  generation to what changed after it, and every replacement prints the `permissions.deny`
  rules it removes and adds.
- **A duplicate generated dbt model name was a non-blocking warning, so an unparseable
  project reached tracked publish output (issue #685).** A Gold product whose
  `goldTableName` equalled its `goldSourceModel` emitted `models/silver/<d>/x.sql` and
  `models/gold/<d>/x.sql`; `dbt parse` rejects that outright, but `compile --check` passed
  and `--emit` wrote it, logging only `self-referential ref(...)` — which named the symptom
  in the generated Gold SQL and read as though dbt would resolve it. Duplicate stems are
  now a blocking render error naming both paths and the authoring fix. The check runs over
  the rendered artifact paths rather than authored names, so it also catches the derived
  names no authoring-time check can see (dual-current views, the shared `dim_date`
  calendar, DQ quarantine models); it is scoped to `models/` because macros are also `.sql`
  but occupy a separate dbt resource namespace. Cross-domain collisions are rejected at
  emit, since Gold shaping is per-domain while every domain emits into one dbt project —
  and one Gold extension per owning domain is the recommended pattern.
- **`extract-schema` reported a table count that included previous runs and double-counted
  every table (issue #679).** The success message globbed `*.yaml` in the output directory,
  which accumulates across runs and holds two files per table (`<table>.yaml` and
  `<table>.samples.yaml`), so `--tables invoices` against a directory with four existing
  tables reported "Extracted 8 tables" for one table's work. `run_extract_schema` now
  returns the tables it actually extracted. The related `_manifest.yaml` clobber was
  already fixed in 5.15.0rc12 (issue #672).

## [5.15.0rc13] — 2026-09-01

### Added
- **Declared Silver contract — bindings conform to it instead of constituting it
  (DD-213, PR #682).** The canonical Silver model was never declared anywhere: model
  name came from `_slug(class)`, column name from `camel_to_snake(property)`, the column
  set from whatever properties a binding happened to map, and column order from the
  authored `fields:` sequence. Ordinary authoring therefore rewrote a published contract
  — deleting a `fields:` entry dropped a column, reordering it changed the parity
  fingerprint, renaming an ontology property renamed the physical column — and onboarding
  a *second* source could not leave the model alone, because
  `conformance.property-incompatible` demanded identical property sets across a group.

  A new authored input, `model/contracts/<domain>.contract.yaml`, sits between the
  ontology (meaning) and the bindings (source fulfilment) and declares the model name,
  the ordered property list with pinned `columnName`, canonical type, nullability and
  `requirement: required | optional`, the governed technical and relationship columns,
  grain and identity, per-entity `stability`/`closed`, and per-column deprecation.
  Two gates enforce it: a compile-time `contract.*` family extending the DD-133 §5 safety
  kernel, and (later) release-time comparison. `scaffold-contract <domain>` generates a
  contract from the current compile plan, and adopting it is a provable no-op.

  A source that cannot supply an optional property now declares the gap under the new
  `unmapped:` binding key and still emits the column as a typed NULL, so a genuinely
  partial source can join an established conformance group without reshaping Silver or
  touching any existing binding. Padded columns are excluded from SCD2 change detection,
  so the day a source starts supplying one it does not re-version the whole entity.

  **A domain with no contract compiles exactly as before** — verified byte-identical.
  Adoption is incremental; there is no migration and no clean break.

### Known issues
- **The conformance union drops the string length its branches keep (issue #681).** A
  column typed `string(50)` on every branch emits as unsized `string` on the union, so a
  class's consumer-facing column type silently widens the moment it gains a second
  source. Pre-existing and reproducible with no contract present; surfaced by the new
  `contract.type-mismatch` check, which is deliberately left strict rather than relaxed
  to hide it. Not fixed in this release.

## [5.15.0rc12] — 2026-08-31

### Fixed
- **`update --check` reported "all managed files up to date" while a scaffolded
  `.github/workflows/*.yml` was entirely missing (issue #671).** `operations.py`'s
  `update` command computed a `"missing"` workflow status but never read it in either
  the `--check` or plain-`update` report block -- only `outdated`/`customized` were
  surfaced. A dataplatform repo scaffolded before `pr-validate.yml` existed had no
  PR-time `dbt parse`/`compile` gate, and nothing said so. Both report blocks now
  surface missing workflows, and `--check` no longer exits 0 while one is absent.
- **`extract-schema` overwrote `_manifest.yaml`'s `tables:` list instead of extending
  it (issue #672).** Re-running `extract-schema --tables <subset>` after an earlier
  full extraction dropped every table not in the current invocation from the manifest,
  even though their per-table YAML files were still on disk. A second run now unions
  the existing manifest's tables with the current run's (and refuses to merge tables
  from a different system/platform/database/schema). Also added `--no-redact-pii` to
  opt out of the `redact-detected-pii` sample policy for sources already known to hold
  no sensitive values.
- **`promote-transform`'s "copies, never moves" docs didn't say the local copy must be
  removed once the promotion ships (issue #673).** Once a promoted model is compiled,
  emitted, and reinstalled via `dbt deps`, the dataplatform repo's still-present local
  copy collides with the installed `kairos_medallion_project` package copy (`dbt
  parse` fails with "two resources with identical database representations"). Both
  `kairos-develop-dbt-transformation` SKILL.md copies now document the required
  cleanup, and `promote-transform`'s own CLI output warns about it at promotion time.
- **`show-class-inventory`/`list-class-properties` listed a class token that `compile`
  then rejected as ambiguous, with no cross-reference between the two (issue #674).**
  `_compute_class_tokens` unconditionally attached the `<domain-stem>:<local>` token to
  every class sharing a local name anywhere in the import closure, even when multiple
  imports declare the same short prefix for different namespaces with no root
  declaration -- so three unrelated `party:Contact` classes each falsely claimed
  `party:Contact` as a usable token. The domain-stem token is now scoped to the root
  ontology's own namespace, matching what `compile` actually resolves. Additionally,
  when a `target.class` token remains unresolved specifically because its prefix is
  ambiguous, `binding.unknown-class`'s message now names the disambiguated alternative
  (e.g. "did you mean `bsp:Contact`?") instead of leaving the author to cross-reference
  a separate `safety.prefix-ambiguous` warning by hand.
- **`explain-term` had no `--domain` shorthand, unlike `show-class-inventory` and
  `list-class-properties` (issue #675).** It required spelling out `--ontology
  <file-path>` even when the caller already knew the domain name. `--domain` now
  resolves the same way the other two commands do.
- **`kairos-develop-dbt-transformation` had no caveat for `dbt-fabric`'s comment-text
  nested-CTE false positive (issue #676).** `dbt-fabric`'s `check_for_nested_cte` macro
  counts literal `"with "` occurrences across the whole compiled SQL text, including
  comments -- a model with zero real CTEs can still fail to build. Worse, the
  toolkit's own `scaffold-staging`-generated single-source `int_merged__<entity>.sql`
  comment already contained the substring three times, tripping the false positive the
  moment its materialization moves off the scaffolded `view` default. The SKILL.md
  caveat is added and the generated comment reworded to avoid the trigger.
- **Dataplatform README lacked guidance for extending an installed dbt package (issue
  #615, partial).** The generated `README.md` only said never to edit
  `dbt_packages/kairos_medallion_project/` directly; it now documents the five
  supported extension patterns (config override, wrapper model, macro override,
  disable + replace, snapshot) with concrete examples.

## [5.15.0rc11] — 2026-08-31

### Fixed
- **`compile --emit` shipped a dbt package with no macros at all (issue #660).** The
  canonical v5 compile path assembles `BoundSources` through
  `core/compiler/adapter.py::_assemble_bound_sources`, which hard-coded
  `macro_names=()` -- so every emitted package carried *zero* of the packaged
  `templates/dbt/macros/*.sql` files, not the one the issue reported (that single
  `kairos_current_timestamp.sql` was a stale file already on disk, preserved by
  `compile`'s shared-artifact reconciliation, never compiler output). A realized
  cross-domain `relationships:` entry with `missingParent`/`ambiguousParent`
  enforcement compiles a `kairos_temporal_fk_cardinality` generic test, so `dbt build`
  failed with `'test_kairos_temporal_fk_cardinality' is undefined` and the referential
  integrity that relationship was authored to guarantee silently could not be checked.
  The macro pack is now resolved from the template root on both paths into
  `BoundSources` via one shared `packaged_macro_names()` helper -- the existing
  `tests/test_cr3_macros.py` only ever drove the other path (`bind_sources()`), which
  is why the suite stayed green through the whole regression. Macros are copied
  unconditionally: they are inert until called, and deciding which ones a compile
  "needs" is precisely the reasoning that produced a package referencing undefined
  macros.
- **The scaffolded DD-103 deny rule blocked the ontology authoring its own skill
  documents (issue #659).** `.claude/settings.json` denied `Read` on
  `model/ontologies/**` and `model/shapes/**`. Claude Code requires a prior `Read` of a
  file before `Edit` will touch it, so denying `Read` made `kairos-design-domain`'s step
  6b ("author the classes and properties by hand") and its governance-SHACL step
  structurally impossible under the default scaffold -- even though `Edit`/`Write` were
  never on the deny list. DD-103 is a boundary on *inspection*: understand ontologies
  through `explain-term`/`show-class-inventory`/`list-class-properties`/
  `resolve-ontology` rather than by scanning serialized RDF as unstructured text, and
  `Grep` is what does that scanning. The 12 `Read` rules are removed; every `Grep` rule
  and both `Edit`/`Write(ontology-hub-publish/**)` guards are unchanged. Existing hubs
  receive this through `update`, which replaces the file only when it matches a recorded
  prior generation -- a hand-extended settings file still gets an advisory instead.
- **Gold's dbt models had no packaging or consumption path (issue #665).** `emit-gold`
  wrote them under `ontology-hub-publish/powerbi/<domain>/dbt/`, a directory with no
  `dbt_project.yml` -- so dbt's `packages.yml` `subdirectory:` mechanism could not
  install it, and the only way to consume a working Gold model was to hand-copy three
  files downstream, where they went stale silently on every re-emit. The medallion side
  was already built for them: the `dbt_project.yml` template has always carried a
  `models/gold/<domain>` config block and `_existing_gold_domains()` has always scanned
  for it, but `render_canonical_project` never rendered the Gold models and
  `_planned_artifact_paths` never listed them, so the compile result filtered them out
  before anything reached disk. Gold dbt models now ship inside the medallion package
  via `compile --emit`, consumed through the same `bump-hub` + `dbt deps` cycle as
  Silver, and the redundant Power BI-side copies are gone. `_existing_gold_domains()`
  also unions in the current run's own Gold domains, so `dbt_project.yml` configures
  them on the first emit instead of converging only on a second.
- **`emit-gold` collided on the shared `parameter.yml` across domains (issue #664).**
  It is a hub-wide root artifact -- fabric-cicd reads exactly one per
  `repository_directory` -- but each domain owns only its own manifest, so the second
  domain's emit saw an unowned file on disk and failed closed. That made the
  one-Gold-extension-per-owning-domain pattern impossible to actually run. It is now
  declared mergeable via `replace_unowned_paths`, mirroring how the Silver emit path
  already handles its own shared artifacts.
- **The scaffolded `kairos.yaml` shipped a `gold.direct_lake_connection` example the
  parser rejects (issue #663).** It declared `environments` as a list of `- name: dev`
  entries where the parser requires a mapping keyed by environment name, so every fresh
  hub's first attempt at configuring Gold failed on a verbatim copy of its own template.
  The example is fixed, and `gold.direct-lake-connection-invalid` now prints the correct
  shape inline instead of only naming the symptom.
- **An all-zero placeholder GUID is no longer accepted as a Direct Lake connection.** It
  matches the GUID format, so nothing downstream rejected it, and the emitted TMDL
  carried a OneLake path resolving to nothing -- a well-formed semantic model that
  silently could not deploy.
- **`gold.unmaterialized-silver-source` now explains itself (issue #661).** A Gold table
  is materialized only by the compile of the domain that binds it; an `owl:imports` of a
  sibling domain resolves its classes but does not carry its compiled Silver bindings.
  The error now names the compiled domain, states that rule, and points at authoring a
  separate Gold extension on the owning domain. `kairos-design-gold` documents it too.

### Added
- **`update --refresh-workflows`: scaffolded GitHub Actions workflows can finally receive
  template fixes (issue #658).** `.github/workflows/*.yml` were written once at
  `init-hub`/`init-dataplatform` time and never revisited, so a real fix landing in a
  template -- `pr-validate.yml`'s guard against `local:` dbt package pins, for instance --
  could not reach any repo that already existed, and `update` reported "all managed files
  up to date" while silently skipping every one of them. They cannot join the existing
  managed-file loop: `_stamp_managed` injects an HTML comment, which is not valid YAML,
  and workflow files carry real local customization that must never be silently
  overwritten. Detection is therefore structural. Several of these workflows are rendered
  from templates with `{ORG}`/`{HUB_REPO}`/`{DBT_CI_PROFILE_YAML}` substitutions, so their
  on-disk bytes are repo-specific and no fixed hash can describe them; `update` instead
  inverts the rendering to ask "is this file an unmodified rendering of a template we
  shipped, and with which values?" -- which is exactly the question that decides whether
  rewriting it is safe. A workflow matching a superseded generation is refreshed in place,
  keeping the repo's own substituted values; one carrying local edits is reported and left
  alone. Plain `update` and `update --check` report drift (and `--check` now fails on a
  refreshable workflow, so `managed-check.yml` catches it); rewriting is opt-in. The
  pre-#650 `pr-validate.yml` generation ships as the first recorded prior generation, so
  existing dataplatforms can pull in the `local:` guard directly.
- **`kairos-ontology apply-gold-connection`: deploy-time Direct Lake overrides (issue
  #662).** `gold.direct_lake_connection` had to be authored in the hub's own
  `kairos.yaml`, and the emitted `parameter.yml` could only rewrite between environments
  the hub itself declared -- so every Fabric workspace a hub might ever deploy to needed
  its real GUIDs committed to a repo that is otherwise infrastructure-agnostic, and a
  hub author with no Fabric infrastructure yet had no option but a placeholder. The
  dataplatform can now declare the workspaces it owns in
  `.github/fabric/gold-connections.yml` (values may be `${VAR}` references resolved from
  the deploy environment, so real GUIDs need never be committed), and the deploy
  workflow applies them after the archive's checksum is verified. Only
  `replace_value[<target_environment>]` is rewritten; `find_value` stays exactly as the
  hub emitted it, because fabric-cicd matches it as a literal substring against the URL
  baked into the TMDL and a locally supplied value would silently fail to match. The
  `.zip`, its checksum, and every TMDL/PBIP file are untouched, and the before/after
  URLs are logged. No config file, or no matching environment, is a clean no-op.

## [5.15.0rc3] — 2026-08-27

### Fixed
- **The emitted Fabric package is schema-valid, and is now validated (issue #623).** Power BI
  Desktop refused an `emit-gold` project before reading the report or the model, while every
  local gate passed — the TOM gate reads only the TMDL tree, so nothing checked the files
  Desktop and Fabric look at first, and the schema URLs in those files were string literals
  nothing dereferenced. Verified against the published schemas, each of which sets
  `additionalProperties: false`: the `.pbip` declared a `$schema` URI that 404s (the published
  family is `/fabric/pbip/…`, not `/fabric/item/…`); `report.json`, `version.json`, `pages.json`
  and `page.json` all omitted the `$schema` their schemas require; `version.json` carried `"4.0"`
  where the value is constrained to `major.minor.0`; `themeCollection.baseTheme` carried only
  `name` where `reportVersionAtImport` and `type` are required too; both `.platform` files
  carried the all-zero `logicalId`, so nothing could tell the report from the semantic model; and
  relationships moved to the canonical `definition/relationships.tmdl`. A new gate validates
  every package file against the schema *it declares*, from vendored copies, never touching the
  network — which is what makes a wrong URI a failure rather than something a test must enumerate.
- **`emit-gold` describes its TOM gate accurately.** It claimed "the same engine Power BI Desktop
  and Fabric use to open a model"; it is one call, `TmdlSerializer.DeserializeDatabaseFromFolder`,
  and covers neither the package JSON nor the model rules Desktop enforces when it creates its
  local database.
- **Four places claimed Fabric Direct Lake "needs no connection configuration"** while the
  projector fail-closes without `gold.direct_lake_connection`. The scaffolded `kairos.yaml` also
  shipped `adapter: fabric` with no `gold` block, so a freshly scaffolded hub failed `emit-gold`
  on its first run with no hint why.

### Added
- **Direct Lake semantic models are promotable between Fabric workspaces (issue #623).**
  `parameter.yml` was emitted only for non-Direct-Lake models, so the OneLake workspace and
  lakehouse GUIDs were baked into the emitted M expression with no deploy-time rewrite path — one
  artifact was pinned to whichever environment was default at emit time, which defeats deploying
  to a Fabric dev workspace to validate. Direct Lake now emits the same root `parameter.yml`,
  with a single `find_replace` entry on the whole OneLake URL (a bare GUID also appears in
  lineage tags, where rewriting it would be wrong). The URL is built by one helper shared with
  the named expression, so `find_value` cannot drift from the TMDL it must match.

### Changed
- **`provenance_hash`-style behaviour change:** `.platform` `logicalId` values change from the
  all-zero placeholder to deterministic, distinct ids derived from item name and type.
  `scaffold/dataplatform/scripts/package_fabric_semantic_model.py` still backfills the zero
  placeholder for hand-authored models only, and does not overwrite projector output.


## [5.15.0rc2] — 2026-08-27

### Changed
- **`emit-gold` now runs the real TOM SDK TMDL validation by default.** `validate_tmdl_artifacts()` existed since 5.15.0rc1 but had no caller — a hub could emit a structurally broken TMDL tree (e.g. a placeholder Direct Lake OneLake GUID, or a genuine TMDL syntax error) and only discover it when a human opened the `.pbip` in Power BI Desktop. `emit-gold` now calls it after projection, in both dry-run and `--confirm-emit` mode: a `status="fail"` result fails the command with the exact file/line before anything is written; a `status="unavailable"` result (no `dotnet` on PATH) is reported but never blocks the emit, matching the module's existing best-effort design. Pass `--skip-tmdl-validation` to opt out entirely.

## [5.15.0rc1] — 2026-08-26

### Added
- **`kairos-ontology emit-gold DOMAIN [--confirm-emit]` (issue #619 Bug 2).** Previously the only way to produce Gold/PowerBI artifacts (TMDL, PBIP, DAX, ERD) was the Python API (`project_downstream_compile_plan('powerbi', plan)`) — `project --target gold/powerbi` was explicitly disabled, and `compile --emit` never rendered Gold (it's not a dbt project file, so it was never wired into the fixed dbt publish target). `emit-gold` builds the same typed `CompilePlan` and atomically writes the projected Gold product to its own fixed location, `ontology-hub-publish/powerbi` (a sibling of the dbt publish target, never inside it). Without `--confirm-emit` it validates and reports what would be written, matching `compile --emit`'s safety conventions.
- **Optional TMDL structural validation via the real Microsoft TOM SDK (issue #619 feature request).** `validate_tmdl_artifacts()` (`kairos_ontology.core.projections.dbt`) runs a bundled `dotnet`-based validator (`Microsoft.AnalysisServices.Tabular`'s `TmdlSerializer.DeserializeDatabaseFromFolder`) against generated TMDL — the same engine Power BI Desktop and Fabric use to open a model — catching a syntax/structure error at projection time with an exact file/line instead of only surfacing as a cryptic dialog in Desktop. Verified end-to-end against the real NuGet package. Opt-in and best-effort: nothing calls it by default, and it reports `status="unavailable"` rather than failing when `dotnet` isn't installed, since most toolkit installs won't have a .NET SDK.

### Fixed
- **Gold PowerBI projection no longer false-positives `gold.silver-registry-drift` on FK-bearing entities (issues #617, #619 Bug 1).** `kernel.py`'s `_project_relationship_match_counts` adds `_kairos_fk_*_match_count` runtime diagnostic columns to Silver models *after* `shape_project()` already snapshotted `silver_registry` from the pre-augmentation columns, so any entity with an FK relationship (e.g. `PartyIdentification` → `Party`) failed `project_downstream_compile_plan('powerbi', plan)` with a spurious drift error. The registry is now refreshed for every model this step touches, so it always reflects the model's real final column set — not just for this one check. This affects every FK-bearing master/business-entity model, which is about to become the common case as hubs adopt the day-one `int_merged__<entity>` pattern from #616/#618.
- **Gold relationship joins now prefer the FK surrogate key over a same-property natural key (issue #619 Bug 12).** `_relationship_column()` matched columns by `property:{uri}` provenance only, but the FK surrogate-key column (`{target}_sk`) kernel.py generates is tagged `relationship:{uri}`, not `property:{uri}` — so it could never match, and relationships silently joined on the natural key (or were dropped entirely when both a natural-key and an explicit override existed). `relationship:`-tagged columns are now preferred, falling back to `property:`-tagged and then the explicit override as before.
- **Gold TMDL/PBIP output was missing several properties Power BI Desktop / Fabric require to open the model (issue #619 Bugs 3, 5, 7, 8, 9, 10).** `model.tmdl` now declares `ref table` per table (and `ref table dim_date` when a calendar is approved) plus `defaultPowerBIDataSourceVersion`/`sourceQueryCulture`; Direct Lake partitions use a bare `entityName` instead of a schema-qualified one; `database.tmdl` declares `compatibilityMode: powerBI`/`language: 1033` and bumps `compatibilityLevel` to 1702; and table TMDL now emits measures before columns with `///` doc-comment descriptions instead of a `description:` property, matching Microsoft's TMDL authoring guidelines.
- **Direct Lake Gold models had no OneLake connection at all (issue #619 Bugs 4, 6).** Every Direct Lake partition declared `mode: directLake` but no `expressionSource`, and no named-expression TMDL file existed for it to reference — Power BI Desktop had nothing to resolve the data source through. Gold projection now emits a shared `AzureStorage.DataLake(...)` named expression (quoted wherever referenced, since its name contains a space and a hyphen) from a new `gold.direct_lake_connection` `kairos.yaml` block (workspace/lakehouse ID per environment, GUID-validated), mirroring the existing `gold.databricks_connection` pattern — fail-closed like it, since an unresolved workspace/lakehouse ID would ship a model that can't resolve its data source.
- **A measure's DAX could reference a table that was never emitted, and nothing caught it (issue #619 Bug 11).** A stale or mistaken table name in a `measureExpression` (e.g. a leftover `dim_`-prefixed name) rendered silently into the TMDL instead of failing. `_shape_measures` now checks every DAX table reference (single-quoted, or a bare identifier before a column bracket) against the tables actually emitted in the product, failing closed with `measure.unresolved-dax-table-reference`.
- **`scaffold-staging` now accepts a single `--source` (issue #616).** It previously refused fewer than two sources, contradicting `kairos-design-mapping/SKILL.md`'s decision rule to default to `int_merged__<entity>` from day one for master/business-entity accelerator classes (Party, Location, TransportOrder, Equipment, ...) even with one contributing source — pushing authors toward a hand-authored, `stg_`-less `int_merged__<entity>.sql` instead. A single source now scaffolds its `stg_<source>__<entity>` model as usual, plus a trivial `int_merged__<entity>.sql` (`select * from {{ ref(...) }}`, no survivorship sentinels) that is ready to grow into a real union+survivorship model when a second source arrives.

## [5.14.0] — 2026-08-23

Consolidates everything recorded under `5.13.0rc1` through `rc31` (2026-08-19 through
2026-08-23) into this release's actual changelog, grouped by kind rather than by the
sequence of individual pre-release bumps they landed in. The full per-change record is
preserved below for history.

### Added
- **`profile-sources`: deterministic Stage-0 profiling of raw `.import/` extracts (DD-189).** Per-column statistics and signal tags — null/empty ratio (blank strings count), cardinality (`unique`/`const`/`low-card(n)`), value shape, sampled cross-table `fk?->table.col` inclusion evidence, and `versioned?`/`code-list?`/`empty-table` table tags — written to `integration/sources/<system>/<system>.profile.yaml` with an evidence-basis marker. Statistics only: no data value is ever persisted. `anchor-tables` consumes the profile automatically (outline annotations + legend); always-empty columns are omitted from model context only under a declared `data_maturity: production` (`kairos.yaml`, `--data-maturity` override) — otherwise every tag is advisory. Measured on the validation corpus: grain 9/9 with profile tags vs 0/9 without (every unprofiled miss keyed on the SaaS tenant discriminator).
- **`generate-bindings`: first-draft EntityBindings from the design sheet (DD-191, no LLM).** One draft per anchored, non-rejected sheet row with a `propose-alignment` result: reuse-first `target.class` from the sheet's anchor URI, fields from scalar alignment mappings (module-scoped resolution, duplicate claims deduped by confidence), object-property and sheet-relationship columns as `technicalFields purpose: relationship`, grain/natural-key columns materialized `purpose: identity` with profile-derived canonical types, and quality tests only where the DD-189 profile proved them. Every draft is validated against the closed v5 contract BEFORE writing — invalid drafts are reported, never written — and existing bindings are never overwritten without `--force`. Secondary entities are echoed as a worklist, never auto-generated.
- **Design rulings: durable human modeling decisions that outrank model judgment (DD-192).** `integration/discovery/design-rulings.yaml` records contested-space resolutions once, by condition (`applies_when`), and `anchor-tables` renders them into the global prompt with `rulings_applied` provenance in the artifact. Boundaries: only human-decided entries feed the prompt (model proposals are inert and reported); a ruling never introduces a class (unresolvable targets skipped with reasons; `rejection` rulings exempt); a ruling never maps columns. Absent file is a silent no-op. Validated live: ruled tables converge to the ruled answer (0.91–0.95, rejected candidate kept as alternate) with collateral movement confined to already-unstable rows.
- **Scaffolded hubs never had a way to install the `langfuse` extra (DD-195, issue #563).** The scaffold template only passed through `azure`/`foundry`/`flatfile`/`parquet`/`otel`; `langfuse` is now offered the same way, so a hub with real Langfuse credentials in `.env` can `uv sync --extra langfuse` instead of tracing silently no-oping.
- **`[tool.kairos].max_workers` sets a hub-level default for `--max-workers` (DD-197, issue #562).** `analyse-sources` and `propose-alignment` both bound their per-table LLM call concurrency via `--max-workers`, but a hub had no way to set its own default the way `accelerator`/`channel` already can — every invocation needed the flag retyped. Precedence: explicit `--max-workers` > `[tool.kairos].max_workers` > the existing default of 16.
- **`update --upgrade` also upgrades reference models (DD-200, issue #551).** Previously it only ever moved the toolkit pin; a hub's reference-models pin drifted independently with nothing to catch it. A hub that pins reference models (a dataplatform repo never does) now gets both upgraded in one `--upgrade` run — non-atomically (the toolkit half was never transactional either), but a refmodels-side failure is now named and exits 1 rather than silently leaving the hub on a new toolkit with a stale reference-models pin.
- **`validate_naming_conventions` gains `property_domain_owl_thing` (DD-204, issue #328).** Mirrors the `property_range_owl_thing` warning #330 shipped for the range side: an `owl:DatatypeProperty`/`owl:ObjectProperty` in a hub's own authored file whose `rdfs:domain` includes `owl:Thing` now gets a warning at author time, suggesting `schema:domainIncludes` as the alternative that avoids an `owl:imports` cycle. Reference-model files are still never validated (DD-188) — this only ever fires on a hub's own domain files.
- **A new raw-sample channel feeds the alignment LLM prompt itself (DD-205, issue #562).** `import_source.py`/`import_flatfile.py` now also write pre-redaction sample values to a new gitignored sidecar (`.import/raw-samples/<system>.json`, alongside the existing `.import/businessdiscovery/` convention) at the same import step that has always redacted the committed artifacts. `propose_alignment.py` overlays these values onto the prompt when available; the per-table cache key picks up the change automatically since it already hashes the (now-overlaid) samples. `KAIROS_ALIGNMENT_SEND_RAW_SAMPLES` (default on) governs the channel end to end — off means the writer never creates the file, not just "the reader ignores it". The committed vocabulary/source-dir artifacts remain permanently redacted regardless of this setting. `kairos-design-domain`/`kairos-design-mapping` SKILL.md Gates updated: `example_values` can no longer be assumed pre-redacted.
- **`compile --no-cache` bypasses the new ontology-closure parse cache.** Use after manually editing a hub's `.cache/ontology-parse/` directory, or when debugging a suspected stale-cache result.
- **Seed column docs are a first-class authored artifact (issue #586, stage b).** A sibling `integration/transforms/dbt/seeds/<name>.yml` (or `.yaml`) next to `<name>.csv` is dbt's plain `seeds: - name: ... columns: ...` properties form. It is deliberately **not** a `meta.kairos` contract — a seed is not a bindable virtual source, so it declares no output contract and stays out of the contract-parsing path entirely. Selecting a seed into a compile closure selects its sibling docs too, and both are emitted together under `seeds/`. Carried on the plan as a new `seed_properties` dependency kind, which — like model properties YAML — has no `model_name`: the CSV owns the resource name and the document only describes it.
- **`validate-dbt-contracts` gains three seed findings (issue #586, stage b).** `dbt-contract.seed-docs-unmatched` (warning) for seed docs naming no authored CSV stem (typo or stale docs after a rename); `dbt-contract.seed-unreadable` (warning) for a CSV that is unreadable, not UTF-8, or has an empty header row; and `dbt-contract.seed-model-collision` (**error**, not a warning like the other two) for a seed stem colliding with an authored model stem — dbt resolves `ref()` in one resource namespace, so the generated project would fail to parse, and the dbt bundle hard-fails the same case. A lint that called that advisory would disagree with the build.
- **`init` and `new-repo` now create `integration/transforms/dbt/seeds/`.** Note that `update` does **not** backfill hub directories: an existing hub must `mkdir integration/transforms/dbt/seeds` itself before authoring its first seed. This is the scaffold's standing behavior, not a seed-specific gap.
- **`docs/dev/ontology-dbt-dataplatform-design-architecture.md`**, a standalone architecture reference for how the ontology hub governs source discovery, bronze-to-canonical bindings, and Silver/Gold dbt generation, and how a separate dataplatform repository consumes that output safely — including repository/ownership boundaries, release-compatibility and reproducibility design, extraction/profiling design, the int-layer authoring boundary, and a dbt Core 2.0 version-strategy note.
- **`kairos-ontology feedback new/resolve/list/sync-index` (issue #588).** A lighter-weight, OKF-style sibling of the Decision Log for running design/business observations captured before (or instead of) they become a `kairos-ontology decision` — replacing the single hand-maintained `modelingfeedback.md` scratchpad with one toolkit-managed file per observation. Simpler than a Decision Record by design: `open`/`resolved` status only (no lifecycle/materiality state machine, no supersession graph), and evidence is a warning when absent, never required. `feedback resolve <id> --note ...` is the one new verb — it rejects resolving an already-resolved record rather than overwriting a prior note. (Records originally lived under `.import/businessdiscovery/insights/`; relocated to `.import/modeling/feedback/` later in this same release — see Changed, issue #591.)
- **dbt seeds now declare a `seeds:` config block (issue #596).** Previously `dbt_project.yml` declared `seed-paths: ["seeds"]` with no matching `seeds:` config, so emitted seeds landed in the profile's default schema with adapter-dependent type inference. Seeds now get `+schema: 'reference'` (a new, dedicated hub-wide layer for business-supplied reference/lookup data), `+quote_columns: true`, and `+tags: ['reference']`. `column_types` remains on adapter inference for now — see the DD-140 amendment for the deferred typed-seeds design and a forward-looking note on seed sourcing. (Resolves the "open question, deliberately unresolved" noted below when seeds first became resolvable.)

### Changed (BREAKING, privacy-relevant — see DD-205)
- **Source sample values now reach Langfuse, the alignment review artifact, and the alignment LLM prompt itself by default (DD-205, issue #562, maintainer-authorized).** Three independent masks previously starved the pipeline of the sample evidence that most helps diagnose a bad mapping: Langfuse tracing masked the `| samples: ...` block (`KAIROS_LANGFUSE_SEND_SAMPLES` now defaults to `1`; set `0` to mask); `example_values` in `*-alignment.yaml` always masked PII-shaped values (now gated by the same setting as below; set `KAIROS_ALIGNMENT_SEND_RAW_SAMPLES=0` to restore masking); and the alignment prompt itself only ever saw the committed vocabulary's *permanently* redacted values, since there was no other on-disk copy to read from.

### Removed (BREAKING)
- **The `affinity` AI-provider role collapses into `alignment` (DD-203, issue #562).** `analyse-sources` and `propose-alignment` used to have separate, independently-configurable AI-provider roles; issue #562 asked for one role, the strongest configured provider, for every pre-modeling LLM call. `ROLE_AFFINITY` is removed outright (a hard removal, not a shim): `KAIROS_AI_AFFINITY_*` env vars (`_ENDPOINT`/`_KEY`/`_MODEL`/`_SEED`/`_REASONING_EFFORT`) are no longer read at all — rename them to `KAIROS_AI_ALIGNMENT_*`. `check-ai-config --role` drops the `affinity` choice. This is a deliberate behavior change, not a rename: `analyse-sources`'s default reasoning effort rises from `low` to `medium` (alignment's tier), and any `KAIROS_AI_ALIGNMENT_*` tuning now also governs the high-volume table-classification call.

### Changed
- **`anchor-tables` output is now a reviewable design sheet (DD-190, artifact schema_version 2).** The global call additionally returns per-table `relationships`, `secondary_entities`, and `flags` — each validated deterministically (unknown/self relationship targets, non-column join inputs, invented secondary classes and same-grain clusters are dropped and counted, never kept silently). Entries carry `status` and `schema_hash`: a human-`confirmed`/`edited` entry with an unchanged schema is pinned — preserved verbatim and excluded from the model call — and a pinned entry whose schema changed releases to `stale-confirmed` with the previous values kept for review. `propose-alignment` applies confirmed sheet anchors without the confidence floor (`sheet-confirmed`); out-of-pool anchors are still never applied. All new fields are additive; v1 artifacts keep working unchanged.
- **`propose-relationships` gains two evidence sources it was blind to.** Tier-2 join matching consumes DD-189 `fk?->table.col` profile tags: measured value containment resolves joins exact name equality cannot see (a child `parent_ref` column proven contained in the parent's key), labelled `[join from measured fk-inclusion evidence]` and carried as `join_evidence` in the JSON output; same-system only, tier-1 name equality still wins when it applies. And `owl:inverseOf` is now entailed: a property declared parent→child whose inverse asserts no domain/range of its own yields the swapped edge, so the side that actually carries the FK can receive a proposal (the TransportOrder `coversConsignment` / consignment-side FK gap).
- **Compiled dbt dependencies are validated through a kind registry instead of a boolean ladder (issue #586, stage b).** `compile`'s dependency-state loader hand-expanded per-kind checks and then computed `expected_prefix = "seeds/" if kind == "seed" else "models/"`, whose else-branch silently claimed every future kind lives under `models/`. Each kind now declares its allowed suffixes, whether a `model_name` is required, and its expected path prefix, so an unknown kind fails closed instead of being mis-validated against a default.
- **The deferred `dbt_bundle`/`dbt_source` ref-regex consolidation is settled as a deliberate non-consolidation (issue #586, stage b).** The two regexes encode opposite obligations and stay separate permanently: `dbt_source.REF_RE` is a *selection* rule that must match dbt's own resolution exactly (case-sensitive, single-argument), while `dbt_bundle._REF_RE` is a *fail-closed validation* rule that is deliberately over-broad (IGNORECASE, accepts the two-argument package form). What did consolidate is the one real defect the duplication caused: `dbt_bundle` now strips Jinja `{# ... #}` comments through the shared helper, so a commented-out `ref()` is no longer read as a dependency or as an unresolved-ref error. The compiler's filesystem and plan walks share one `extract_refs()` helper, mirroring #584's `extract_sources`.
- **The cross-domain union of shared `_<system>__sources.yml` catalogs now fails closed.** Previously, when two domains rendered the same source with conflicting header metadata (database/schema/description) or conflicting same-name table entries, the first-seen variant silently won. `compile --emit` now aborts with an artifact-collision error before touching the target tree; re-emit every domain after a vocabulary change that alters shared source metadata. Non-conflicting unions produce byte-identical output as before.
- **`compile` accepts several domains, or `--all`, and builds the alignment report once per process (issue #598, fixes 1 and 5).** `build_alignment_report` resolves the entire reference-model vocabulary -- domain-independent work that dominated wall clock -- and `compile` asked for the identical report twice per invocation, once for the DD-180 anchor gate and once for the DD-169 column gate. It is now memoized in-process on `(analysis_dir, hub_root)`, excluding `domains` because callers filter by scope after the build, and a hit is only trusted after re-fingerprinting the alignment files and source vocabularies. On a 14-domain hub a redundant build drops from 3.86s to 0.01s, and the release loop drops from 351.07s across 14 invocations to 51.38s in one (6.83x), with all 14 domains reporting an identical verdict either way. Each domain still compiles independently and emits its own subtree atomically (DD-133/140); one domain's failure is reported against that domain and does not skip the rest. The scaffolded release workflow replaces its shell domain-discovery loop with a single `compile --all`.
- **The reference-class index is cached across processes (issue #598, fix 2).** Resolving it walks the whole reference corpus — ~17s on a 14-domain hub — and the answer is identical for every domain, yet every fresh process paid it. It is now cached at `<hub>/.cache/reference-index.json`. The key is corpus *content* — every catalog mapping with its target's path, mtime and size, plus rewrite rules and `KAIROS_REFMODELS_ROOT` — not the reference-models version, because a hub can extend or replace the effective corpus at a fixed wheel version in several ways. Read by every command, **written only by `--emit`**, which is the one mode DD-133 permits to write into the hub; the honest consequence is that a read-only command benefits only after some `--emit` has warmed the cache. On a 14-domain hub a warm `compile <domain> --check` drops from 32.1s to 8.5s. `--no-cache` bypasses it.
- **Modeling-feedback records relocated to `.import/modeling/feedback/` (issue #591).** Previously at `.import/businessdiscovery/insights/` (#608), which both misdescribed the content (these are ontology-modeling observations, not business-discovery evidence) and sat inside a blanket-gitignored tree with no tracking carve-out, so `HUB-FB-*.md` records were silently never committed by default. `.import/modeling/` is a new root for toolkit-managed, git-tracked OKF-style records, reserved for future record types (e.g. the OKF business-knowledge/model-input convention) alongside `feedback/`. The scaffolded `.gitignore` now tracks `.import/modeling/**` while the rest of `.import/` (raw client evidence) stays ignored. **If you already ran `kairos-ontology feedback new`** on an existing hub, move `.import/businessdiscovery/insights/` to `.import/modeling/feedback/` by hand; `update` does not migrate this automatically.
- **`.import/businessdiscovery/README.md` documents the append-only naming convention (issue #591).** Dated, immutable snapshots (`YYMMDD_<topic>.<ext>`) — never edit a dropped file in place; a correction is a new dated file. `discovery-status`'s `CHANGED` output now says so explicitly.

### Fixed
- **Source profiling's class catalog is scoped to the resolved accelerator (DD-193, issue #558).** `build_class_catalog` (and thus `anchor-tables`) previously offered every module the whole installed reference-models package maps as an anchor candidate — on a logistics hub this put ~400 FIBO classes in front of the model as `UNOWNED` noise, with a real risk of a table falling back to an unrelated vendor class instead of being flagged for review. `read_reference_terms` gains an optional `module_scope` parameter (defaulting to the unrestricted legacy behaviour every other caller keeps); `build_class_catalog` seeds it with the resolved accelerator's own declared domain imports. A module the accelerator never reaches, directly or transitively, is excluded outright; a module reached only via `owl:imports` from an accelerator-declared module remains visible (transitivity is unaffected — only the seed set narrows). An unresolved accelerator keeps today's unrestricted behaviour rather than emptying the catalog.
- **`profile-sources` no longer crashes on a unique timezone-aware timestamp column (DD-194).** Found on a real client extract: key-set construction ran `to_pylist()` on any `unique`-tagged column regardless of type, and a tz-aware timestamp needs a timezone database (`ArrowInvalid` on a bare Windows Python without `tzdata`). Temporal columns are now excluded from key-set candidacy outright — a timestamp was never a meaningful FK join signal — while keeping their `unique`/`date-like` profile tags unaffected.
- **`coverage-report` (and every caller of `resolve_reference_models`) scanned archived reference-model snapshots and misattributed their pre-fix content to live modules (DD-196, issue #566).** An archived `.ttl` under `derived-ontologies/<vendor>/archive/**` shares its live module's permanent IRI, so a defect already resolved in the live file (e.g. a missing `owl:imports`, fixed upstream in referencemodels v1.32.0) still resolved from the frozen pre-fix snapshot and got reported as if it were live. Archived paths are now excluded unconditionally, matched on path segment rather than a caller-supplied glob — this was originally filed against the reference-models repo (#108) before the real cause (this toolkit's resolver, not the reference data) was identified.
- **AI preflight surfaces a missing SDK as a missing dependency, with a uv-native fix (DD-198, issue #553).** `check-ai-config --probe` against a hub with `KAIROS_AI_PROVIDER` configured but the matching SDK not installed previously reported `unreachable` with a "verify network connectivity" remediation — misleading, since no network call was attempted, and it buried the real install hint. `_probe_client` now lets the underlying `NotConfigured` propagate instead of rewrapping it, and `preflight_ai_provider` reports a new `missing_dependency` status with the exact fix as remediation. The Foundry (×2) and Azure `NotConfigured` messages themselves, and the scaffolded `.env.example`'s install comments, now say `uv sync --extra foundry/azure` instead of `pip install kairos-ontology-toolkit[foundry/azure]`.
- **`update-refmodels` silently did nothing, then reported success (DD-200, issue #551).** Reference models ship only as a GitHub Release wheel, never to a package index, so `uv pip install --upgrade kairos-ontology-referencemodels` (the default, no-`--version` path) had no package to find and installed nothing — this is how a real hub's pin sat thirteen minor versions behind (#541). The command now resolves the latest published release the same draft-filtered, version-ordered way scaffolding does, and always installs that exact wheel. Also fixed: an unprefixed `--version 1.33.1` produced a 404 pin (no `v`-prefix normalization) — now normalized like every other caller.
- **A class-name collision across two DIFFERENT domains was resolved by ownership, not richness (DD-201, issue #564).** `choose_class_copy` hard-filtered candidate copies into a same-domain-owned tier before any richness scoring ran, so a richer copy owned by a different domain (e.g. BSP's `Person`) was discarded in favor of a bare same-domain copy (IATA's `Person`) purely because of catalog read order — the sibling of the #519 defect one level out. Same-domain ownership is now a tie-break inside the ranking, after column-property overlap and property count, not a filter ahead of them. A deterministic `property-less-anchor` sheet flag now also survives into `table-anchors.yaml` whenever a resolved anchor has zero properties (previously console-only).
- **The global-anchor path's resolved URI never reached `likely_entity_uri` (DD-201, issue #564).** `TableAlignment.likely_entity_uri` was only populated on the older uri-anchor-contract "confirmed" path; the newer global-anchor/design-sheet path (DD-185/190) never carried its own resolved `anchor_uri` forward, even though both existing consumers (`design_landscape`, `conformance_evidence`) already prefer it over the bare `ref_class` name. `design_landscape` also gains a defensive fallback to `table-anchors.yaml` for already-generated alignment artifacts that predate this fix, guarded to only apply on an exact anchor-name match.
- **`generate-bindings` failed 27/59 tables (46%) with a generic schema error instead of skipping them (DD-202, issue #565).** This generator never emits `relationships:` (deferred to `propose-relationships`), so any table with zero mapped scalar fields was always going to fail the v5 contract's conditional-`relationships:` requirement — and a table with `grain_columns: []`/`natural_key: []` failed the same way. Both are now recognized as non-generatable *before* a draft is built, and report `skipped` with a specific reason (e.g. "no grain identified on the sheet row", or "no scalar fields mapped for this table" with a note when relationship wiring was deferred) instead of `invalid` with a generic validator message.
- **`rdfs:domain owl:Thing` silently produced dead properties, invisible to the compiler and every projector, with no diagnostic anywhere (DD-204, issue #328).** Issue #328 was closed by #330, but #330's own diff explicitly left this half — the domain side — "deliberately unchanged"; only the sibling `rdfs:range owl:Thing` case got a warning. Reopened with fresh evidence: a real client hub's `coverage-report` found 49 property-domain assertions in the reference-models package's own `onerecord.iata.org/ns/cargo` module, all declaring `rdfs:domain owl:Thing`, none of them attached to any class. `_warn_unattached_property_domains` now tells the two causes apart instead of blaming every unattached property on a missing `owl:imports`: an `owl:Thing` domain gets its own message pointing at issue #328, since no amount of importing fixes it.
- **`compile --emit` now includes the contracted dbt dependency closure selected by each immutable `CompilePlan` (issue #580).** Authored SQL, transitive authored `ref()` dependencies, and the selected properties YAML are copied to their stable paths in the unified dbt project. Per-domain dependency ownership is reconciled across sequential emits, stale files are removed only after their final owner drops them, and conflicting paths, bytes, or dbt model names fail closed.
- **`audit-silver-samples` no longer reports contracted dbt virtual outputs as missing Bronze columns (issue #581).** Contracted output columns now produce an informational offline-evaluation limitation with contract paths and traceable contributing source systems. Genuine missing physical source columns remain errors, so `--fail-on error` retains its intended meaning.
- **`compile <domain> --emit` was slow because the compile path reparsed and re-resolved the same inputs repeatedly, with no caching anywhere.** Three fixes: (1) `resolve_scope` parsed every hub-wide source `.ttl` file up to twice just to test which ones a domain's bindings reference; it now parses each candidate at most once, gated by a cheap byte-level pre-filter that skips files that provably cannot match. (2) A dbt-sourced binding's contract and SQL dependency closure were read up to three times per compile (`resolve_scope`'s pre-pass, its duplicate-virtual-source check, and `build_compile_plan`'s main loop); they are now resolved once and reused via `ResolutionContext`. (3) `load_ontology` now caches the parsed `owl:imports` closure: in-process for the lifetime of one compile (content-hash verified before every reuse, so a hub file changing mid-process is never served stale), and on disk per source file (content-hash keyed, so it survives across the separate `compile --emit` processes a hub-wide release job runs one per domain). The on-disk cache only ever gets written during `--emit`, never during `--check`/`--explain`, and lives in a gitignored `.cache/` directory scoped to one call so it can never leak into another command.
- **`compile --emit` now declares the physical dbt sources a contracted model's dependency closure reads (issue #584).** `{{ source('name', 'table') }}` pairs are extracted from the contracted `ref()` closure at resolution time, validated against the hub's source vocabularies (new `dbt-source.source-unresolved` / `dbt-source.source-ambiguous` diagnostics), and declared through the same shared `models/silver/_<system>__sources.yml` catalogs relation-backed bindings use — so offline `dbt parse` passes on the emitted project. A purely-contracted domain now discovers and provenance-tracks the vocabularies its closure reads. A direct binding and a contracted `source()` read of the same table legally coexist (contracted declarations do not grant or revoke mapping authority).
- **A `ref()` pointing at an authored dbt seed CSV no longer blocks the domain with `dbt-source.dependency-unresolved` (issue #586, stage a).** `ref('<name>')` may resolve to exactly one `integration/transforms/dbt/seeds/<name>.csv`; the seed joins the compile closure as a leaf, is carried on the `CompilePlan` as `kind="seed"`, and is emitted under `seeds/` so the generated project stays self-contained. A name matching both a model and a seed fails closed with the new `dbt-source.dependency-ambiguous` diagnostic, and `validate-dbt` counts emitted seed stems as valid `ref()` targets.
- **`generate` / `run_projections` no longer hard-fail on a hub that has a seed (issue #586, stage b).** dbt bundle assembly only scanned `models/`, `macros/`, and `tests/`, so an authored seed CSV never entered the bundle and its stem was absent from the ref-closure check. An authored model's `{{ ref('country_codes') }}` therefore raised `unresolved dbt ref targets`, which the projector escalates into a fatal *"dbt assembly failed; no dbt artifacts were written"* for the whole dbt/silver target — one seed took down every model in the projection. Since stage (a) shipped the compile path only, the same hub had `compile --emit` succeeding while `generate` failed. The bundle now scans `seeds/` for `*.csv` plus sibling `*.yml`/`*.yaml` seed docs, carries them as `seeds/<name>.csv` artifacts, exposes `DbtBundle.seed_names`, counts seed stems as known `ref()` targets, and allow-lists a `seeds:` key in scoped-mode properties filtering. A seed stem colliding with an authored or generated model stem now fails the bundle closed rather than emitting a project dbt cannot parse.
- **A seeds-only transforms tree is no longer invisible to `next` and `validate-dbt-contracts` (issue #586, stage b).** The hub-inspection presence probe for `dbt_transforms` was `.sql`-only, so a hub whose only authored transform content was a seed reported *missing* to `kairos-ontology next`. `validate-dbt-contracts` returned early with `transforms_present=false` whenever `models/` was absent, so the same hub looked like it had no transforms at all. Both now accept an authored seed CSV as transform content.
- **Extraction matches dbt's own semantics.** `source()` calls are recognized in both the positional and keyword (`source_name=`/`table_name=`, either order) forms; Jinja `{# ... #}` comments are stripped before `ref()`/`source()` extraction so commented-out calls create no phantom dependencies or false diagnostics; `ref()` names match authored file stems case-exactly on every platform; and an unreadable or non-UTF-8 dependency file (e.g. a cp1252 seed CSV export) is a binding-attributed `dbt-source.dependency-unresolved` diagnostic instead of a crash. `field-mapping-report` lineage treats a seed-backed `ref()` as a traceable leaf.
- **A `source()` call the compiler cannot read now fails the compile instead of being silently skipped (new `dbt-source.source-unparsed`).** Any `source(` call site whose arguments are not statically resolvable — mixed positional/keyword arguments, `var()` or other variable arguments, string concatenation, macro-generated names — is reported with the supported forms named, in both closure walks. Previously such a call produced no catalog entry and no diagnostic, so the failure only surfaced later as an offline `dbt parse` error. Macros whose names merely end in `source` (e.g. `my_source(...)`) are unaffected.
- **Commands that hit an incomplete ontology closure no longer die with a raw `OntologyLoadError` traceback (issue #587).** The CLI boundary now renders the exception's attached diagnostics to stderr — `missing_import` entries first — and, when those missing imports coincide with `kairos-ontology-referencemodels` being absent from the running interpreter (the typical pipx / `uv tool` global-install symptom), adds a hint to use `uv run kairos-ontology …`. Exit code stays 1 and the DD-151 `kairos.cli.command.failed` record is still written.
- **The outside-venv startup warning now catches pipx / `uv tool` global installs (issue #587, DD-049 amendment).** The guard is identity-based: inside a managed hub it compares `sys.prefix` against the hub's own `.venv` instead of asking "am I in *some* venv?" — a global pipx install is a venv too, so it previously passed silently and then failed with missing hub-pinned packages. Outside a managed hub the old bare-global heuristic is unchanged.
- **The auto-close-issues workflow no longer closes a multi-part issue when a merged PR references it with a partial-fix qualifier (issue #578).** `(#562 P2)`, `(#562 P3+P4)`, and `(#562 Problem 2)` now mark the reference as scoped to part of the issue and leave it open (PR #577 closed #562 with Problems 3 and 4 untouched). A Python meta-test pins the workflow's inline regexes and reimplements its decision loop, and the SC-merge-pr skill, PR template, and CONTRIBUTING now describe the workflow's actual parenthetical-close behavior.
- **Every scaffolded `compile ... --emit` now passes `--confirm-emit`.** `--emit` has required `--confirm-emit` since #264, but the scaffolded release workflow kept the bare form from v5.0.0 onward and there is no CI bypass, so every hub scaffolded since 2026-08-10 shipped a release workflow that failed on its first domain. The same stale invocation appeared in two "Canonical commands" listings that tell an agent to run a command the CLI rejects. A new guard scans the whole scaffold tree for real `kairos-ontology compile ... --emit` invocations, so this closes the class rather than the instance.
- **`provenance_hash` is reproducible across processes again (issue #600).** Identical inputs produced two different hashes from one run to the next. Two independent causes. First, provenance inputs were sorted by `name` alone, and names are not unique — an ontology outside the hub root is recorded under its bare filename and reference modules share basenames — so `sorted`'s stability left colliding entries in set-iteration order. Second, and the one that actually drove the reported symptom, the domain namespace came from `next(graph.subjects(RDF.type, OWL.Class))`: an arbitrary member of an unordered store, sometimes an anonymous restriction blank node, whose string form has no `#` or `/` and so fell through to the `urn:kairos:ontology:` placeholder. That is not just a hash ingredient — `list_classes` uses the namespace to decide what counts as the domain's own vocabulary, so a hub could compile against two different namespaces on consecutive runs. Namespace candidates are now named classes only, sorted, and preferred from the root ontology's own IRI over anything the import closure drags in; the `owl:Ontology` pick beside it follows the same rule. **`provenance_hash` values change once as a result.** Emitted dbt artifacts are unaffected (the hash appears nowhere in them); `compile --format json` payloads and `project --target gold` parity output carry the new value.
- **The reference-models catalog overlay is additive-only again (issue #602).** DD-158 requires that the hub catalog's entries win and the overlay only supply resolutions the hub does not already provide. Because overlays loaded last and wrote every mapping variant unconditionally, a packaged entry silently replaced a hub's own mapping for the same IRI — so a hub that deliberately points a reference-model IRI at a local TTL was overridden without a diagnostic. Overlay entries now use `setdefault`, across all normalized variants, and the flag propagates through `<nextCatalog>`. **Behaviour change:** a hub whose local entry was previously being shadowed now resolves to its own file.
- **`compile --all --format json` always returns an array.** The shape used to depend on how many domains the hub happened to have, so a script broke on hub shape alone. An explicitly named single domain keeps the object shape.
- **A gate refusal now appears in the JSON payload.** The DD-180, DD-169, DD-163 and discovery gates return before a `CompileResult` exists, so a refused domain contributed no JSON at all and simply vanished from the `--all` array — a consumer saw 13 of 14 entries with no machine-readable reason. Each gate now returns a payload with the same keys, `succeeded: false`, and real diagnostics. **Behaviour change:** a single-domain gate refusal now emits JSON where it previously emitted none.
- **The `init-dataplatform` scaffold's `dbt-fabric`/`dbt-databricks` pins had no upper bound** (`dbt-fabric>=1.9.0`, `dbt-databricks>=1.9.0`), so a routine `uv sync` in a scaffolded dataplatform repo could silently resolve into dbt Core 2.0 (the former Fusion engine, now in beta, with a stricter codified language spec and no validated adapter support yet). Both pins now read `>=1.9.0,<2.0.0`. This changes no currently-resolved version — it only prevents a future silent jump into unvalidated pre-GA territory.
- **Scaffolded (and this toolkit's own) CI workflows failed on GitHub Enterprise Server (issue #589).** An unpinned `astral-sh/setup-uv@v4` queries `github.com`'s "latest release" API for uv's version, which 404s on GHES since `astral-sh/uv` doesn't exist there. Pinned `setup-uv@v10.0.1` with an explicit uv version everywhere it's used (scaffolded `managed-check.yml`/`release-projections.yml`/`copilot-setup-steps.yml`, and this toolkit's own `ci.yml`/`release.yml`/`dependency-audit.yml`/`refmodels-pin.yml`). Also: scaffolded workflows now use `uv sync --locked` (fails loudly on a stale lockfile instead of silently re-resolving), switched the npm step from `npm ci` to `npm install` (no lockfile is ever shipped alongside the scaffolded `package.json`, so `npm ci` always hard-failed), and bumped scaffolded `setup-node` to Node 22 (Node 20 is deprecated on GitHub-hosted runners).
- **DDL nullability for FK/surrogate columns ignored `missingParent: null` (issue #609).** A relationship declaring `missingParent: null` correctly produced a nullable `_sk` column in the generated dbt SQL (a genuine `left join`), but the generated DDL analysis file always declared the same column `NOT NULL`, contradicting runtime behavior. Root cause: the Silver authority builder (`policy_normalize.py`) never recognized a wired FK column as such — it matched only by local-join-column name, never the emitted `_sk` column — so it fell through to `SURROGATE_JOIN_KEY`, which is unconditionally hard-coded non-nullable regardless of the relationship's actual policy. Invisible for the common `missingParent: error` case, since that happened to land on `NOT NULL` via the same broken path anyway.

<details>
<summary>Per-change record: <code>5.13.0rc1</code>–<code>rc31</code> (2026-08-19 to 2026-08-23), consolidated above</summary>

## [5.13.0rc31] — 2026-08-23

### Changed
- **Modeling-feedback records relocated to `.import/modeling/feedback/` (issue #591).**
  Previously at `.import/businessdiscovery/insights/` (#608), which both misdescribed
  the content (these are ontology-modeling observations, not business-discovery
  evidence) and sat inside a blanket-gitignored tree with no tracking carve-out, so
  `HUB-FB-*.md` records were silently never committed by default. `.import/modeling/`
  is a new root for toolkit-managed, git-tracked OKF-style records, reserved for future
  record types (e.g. the OKF business-knowledge/model-input convention) alongside
  `feedback/`. The scaffolded `.gitignore` now tracks `.import/modeling/**` while the
  rest of `.import/` (raw client evidence) stays ignored. **If you already ran
  `kairos-ontology feedback new`** on an existing hub, move
  `.import/businessdiscovery/insights/` to `.import/modeling/feedback/` by hand; `update`
  does not migrate this automatically.
- **`.import/businessdiscovery/README.md` documents the append-only naming convention
  (issue #591).** Dated, immutable snapshots (`YYMMDD_<topic>.<ext>`) — never edit a
  dropped file in place; a correction is a new dated file. `discovery-status`'s
  `CHANGED` output now says so explicitly.

## [5.13.0rc30] — 2026-08-23

### Fixed
- **DDL nullability for FK/surrogate columns ignored `missingParent: null` (issue #609).**
  A relationship declaring `missingParent: null` correctly produced a nullable `_sk`
  column in the generated dbt SQL (a genuine `left join`), but the generated DDL analysis
  file always declared the same column `NOT NULL`, contradicting runtime behavior. Root
  cause: the Silver authority builder (`policy_normalize.py`) never recognized a wired FK
  column as such — it matched only by local-join-column name, never the emitted `_sk`
  column — so it fell through to `SURROGATE_JOIN_KEY`, which is unconditionally hard-coded
  non-nullable regardless of the relationship's actual policy. Invisible for the common
  `missingParent: error` case, since that happened to land on `NOT NULL` via the same
  broken path anyway.

## [5.13.0rc29] — 2026-08-22

### Added
- **`kairos-ontology feedback new/resolve/list/sync-index` (issue #588).** A lighter-weight,
  OKF-style sibling of the Decision Log for running design/business observations captured
  before (or instead of) they become a `kairos-ontology decision` — replacing the single
  hand-maintained `modelingfeedback.md` scratchpad with one toolkit-managed file per
  observation. Records (`HUB-FB-*.md`) live under `.import/businessdiscovery/insights/`,
  deliberately kept at that existing location so they keep flowing into the glossary via
  `kairos-design-discovery` exactly as the single-file scratchpad did, with no
  discovery-pipeline changes. Simpler than a Decision Record by design: `open`/`resolved`
  status only (no lifecycle/materiality state machine, no supersession graph), and evidence
  is a warning when absent, never required. `feedback resolve <id> --note ...` is the one
  new verb — it rejects resolving an already-resolved record rather than overwriting a
  prior note.

## [5.13.0rc28] — 2026-08-22

### Fixed
- **Scaffolded (and this toolkit's own) CI workflows failed on GitHub Enterprise Server
  (issue #589).** An unpinned `astral-sh/setup-uv@v4` queries `github.com`'s "latest release"
  API for uv's version, which 404s on GHES since `astral-sh/uv` doesn't exist there. Pinned
  `setup-uv@v10.0.1` with an explicit uv version everywhere it's used (scaffolded
  `managed-check.yml`/`release-projections.yml`/`copilot-setup-steps.yml`, and this toolkit's
  own `ci.yml`/`release.yml`/`dependency-audit.yml`/`refmodels-pin.yml`). Also: scaffolded
  workflows now use `uv sync --locked` (fails loudly on a stale lockfile instead of silently
  re-resolving), switched the npm step from `npm ci` to `npm install` (no lockfile is ever
  shipped alongside the scaffolded `package.json`, so `npm ci` always hard-failed), and bumped
  scaffolded `setup-node` to Node 22 (Node 20 is deprecated on GitHub-hosted runners).

## [5.13.0rc27] — 2026-08-22

### Fixed
- **The `init-dataplatform` scaffold's `dbt-fabric`/`dbt-databricks` pins had no upper bound**
  (`dbt-fabric>=1.9.0`, `dbt-databricks>=1.9.0`), so a routine `uv sync` in a scaffolded
  dataplatform repo could silently resolve into dbt Core 2.0 (the former Fusion engine, now in
  beta, with a stricter codified language spec and no validated adapter support yet). Both pins
  now read `>=1.9.0,<2.0.0`. This changes no currently-resolved version — it only prevents a
  future silent jump into unvalidated pre-GA territory.

### Added
- **`docs/dev/ontology-dbt-dataplatform-design-architecture.md`**, a standalone architecture
  reference for how the ontology hub governs source discovery, bronze-to-canonical bindings, and
  Silver/Gold dbt generation, and how a separate dataplatform repository consumes that output
  safely — including repository/ownership boundaries, release-compatibility and reproducibility
  design, extraction/profiling design, the int-layer authoring boundary, and a dbt Core 2.0
  version-strategy note.

## [5.13.0rc26] — 2026-08-22

### Fixed
- **`provenance_hash` is reproducible across processes again (issue #600).** Identical
  inputs produced two different hashes from one run to the next. Two independent causes.
  First, provenance inputs were sorted by `name` alone, and names are not unique — an
  ontology outside the hub root is recorded under its bare filename and reference modules
  share basenames — so `sorted`'s stability left colliding entries in set-iteration order.
  Second, and the one that actually drove the reported symptom, the domain namespace came
  from `next(graph.subjects(RDF.type, OWL.Class))`: an arbitrary member of an unordered
  store, sometimes an anonymous restriction blank node, whose string form has no `#` or
  `/` and so fell through to the `urn:kairos:ontology:` placeholder. That is not just a
  hash ingredient — `list_classes` uses the namespace to decide what counts as the
  domain's own vocabulary, so a hub could compile against two different namespaces on
  consecutive runs. Namespace candidates are now named classes only, sorted, and preferred
  from the root ontology's own IRI over anything the import closure drags in; the
  `owl:Ontology` pick beside it follows the same rule. **`provenance_hash` values change
  once as a result.** Emitted dbt artifacts are unaffected (the hash appears nowhere in
  them); `compile --format json` payloads and `project --target gold` parity output carry
  the new value.
- **The reference-models catalog overlay is additive-only again (issue #602).** DD-158
  requires that the hub catalog's entries win and the overlay only supply resolutions the
  hub does not already provide. Because overlays loaded last and wrote every mapping
  variant unconditionally, a packaged entry silently replaced a hub's own mapping for the
  same IRI — so a hub that deliberately points a reference-model IRI at a local TTL was
  overridden without a diagnostic. Overlay entries now use `setdefault`, across all
  normalized variants, and the flag propagates through `<nextCatalog>`. **Behaviour
  change:** a hub whose local entry was previously being shadowed now resolves to its own
  file.
- **`compile --all --format json` always returns an array.** The shape used to depend on
  how many domains the hub happened to have, so a script broke on hub shape alone. An
  explicitly named single domain keeps the object shape.
- **A gate refusal now appears in the JSON payload.** The DD-180, DD-169, DD-163 and
  discovery gates return before a `CompileResult` exists, so a refused domain contributed
  no JSON at all and simply vanished from the `--all` array — a consumer saw 13 of 14
  entries with no machine-readable reason. Each gate now returns a payload with the same
  keys, `succeeded: false`, and real diagnostics. **Behaviour change:** a single-domain
  gate refusal now emits JSON where it previously emitted none.

### Changed
- **The reference-class index is cached across processes (issue #598, fix 2).** Resolving
  it walks the whole reference corpus — ~17s on a 14-domain hub — and the answer is
  identical for every domain, yet every fresh process paid it. It is now cached at
  `<hub>/.cache/reference-index.json`. The key is corpus *content* — every catalog mapping
  with its target's path, mtime and size, plus rewrite rules and `KAIROS_REFMODELS_ROOT` —
  not the reference-models version, because a hub can extend or replace the effective
  corpus at a fixed wheel version in several ways. Read by every command, **written only
  by `--emit`**, which is the one mode DD-133 permits to write into the hub; the honest
  consequence is that a read-only command benefits only after some `--emit` has warmed the
  cache. On a 14-domain hub a warm `compile <domain> --check` drops from 32.1s to 8.5s.
  `--no-cache` bypasses it.


## [5.13.0rc25] — 2026-08-21

### Fixed
- **Every scaffolded `compile ... --emit` now passes `--confirm-emit`.** `--emit` has
  required `--confirm-emit` since #264, but the scaffolded release workflow kept the bare
  form from v5.0.0 onward and there is no CI bypass, so every hub scaffolded since
  2026-08-10 shipped a release workflow that failed on its first domain. The same stale
  invocation appeared in two "Canonical commands" listings that tell an agent to run a
  command the CLI rejects. A new guard scans the whole scaffold tree for real
  `kairos-ontology compile ... --emit` invocations, so this closes the class rather than
  the instance.

### Changed
- **`compile` accepts several domains, or `--all`, and builds the alignment report once
  per process (issue #598, fixes 1 and 5).** `build_alignment_report` resolves the entire
  reference-model vocabulary -- domain-independent work that dominated wall clock -- and
  `compile` asked for the identical report twice per invocation, once for the DD-180 anchor
  gate and once for the DD-169 column gate. It is now memoized in-process on
  `(analysis_dir, hub_root)`, excluding `domains` because callers filter by scope after the
  build, and a hit is only trusted after re-fingerprinting the alignment files and source
  vocabularies. On a 14-domain hub a redundant build drops from 3.86s to 0.01s, and the
  release loop drops from 351.07s across 14 invocations to 51.38s in one (6.83x), with all
  14 domains reporting an identical verdict either way. Each domain still compiles
  independently and emits its own subtree atomically (DD-133/140); one domain's failure is
  reported against that domain and does not skip the rest. The scaffolded release workflow
  replaces its shell domain-discovery loop with a single `compile --all`.


## [5.13.0rc24] — 2026-08-21

### Fixed
- **`compile --emit` now declares the physical dbt sources a contracted model's dependency
  closure reads (issue #584).** `{{ source('name', 'table') }}` pairs are extracted from the
  contracted `ref()` closure at resolution time, validated against the hub's source
  vocabularies (new `dbt-source.source-unresolved` / `dbt-source.source-ambiguous`
  diagnostics), and declared through the same shared `models/silver/_<system>__sources.yml`
  catalogs relation-backed bindings use — so offline `dbt parse` passes on the emitted
  project. A purely-contracted domain now discovers and provenance-tracks the vocabularies
  its closure reads. A direct binding and a contracted `source()` read of the same table
  legally coexist (contracted declarations do not grant or revoke mapping authority).
- **A `ref()` pointing at an authored dbt seed CSV no longer blocks the domain with
  `dbt-source.dependency-unresolved` (issue #586, stage a).** `ref('<name>')` may resolve to
  exactly one `integration/transforms/dbt/seeds/<name>.csv`; the seed joins the compile
  closure as a leaf, is carried on the `CompilePlan` as `kind="seed"`, and is emitted under
  `seeds/` so the generated project stays self-contained. A name matching both a model and a
  seed fails closed with the new `dbt-source.dependency-ambiguous` diagnostic, and
  `validate-dbt` counts emitted seed stems as valid `ref()` targets.
- **`generate` / `run_projections` no longer hard-fail on a hub that has a seed
  (issue #586, stage b).** dbt bundle assembly only scanned `models/`, `macros/`, and
  `tests/`, so an authored seed CSV never entered the bundle and its stem was absent from
  the ref-closure check. An authored model's `{{ ref('country_codes') }}` therefore raised
  `unresolved dbt ref targets`, which the projector escalates into a fatal *"dbt assembly
  failed; no dbt artifacts were written"* for the whole dbt/silver target — one seed took
  down every model in the projection. Since stage (a) shipped the compile path only, the
  same hub had `compile --emit` succeeding while `generate` failed. The bundle now scans
  `seeds/` for `*.csv` plus sibling `*.yml`/`*.yaml` seed docs, carries them as
  `seeds/<name>.csv` artifacts, exposes `DbtBundle.seed_names`, counts seed stems as known
  `ref()` targets, and allow-lists a `seeds:` key in scoped-mode properties filtering. A
  seed stem colliding with an authored or generated model stem now fails the bundle closed
  rather than emitting a project dbt cannot parse.
- **A seeds-only transforms tree is no longer invisible to `next` and
  `validate-dbt-contracts` (issue #586, stage b).** The hub-inspection presence probe for
  `dbt_transforms` was `.sql`-only, so a hub whose only authored transform content was a
  seed reported *missing* to `kairos-ontology next`. `validate-dbt-contracts` returned
  early with `transforms_present=false` whenever `models/` was absent, so the same hub
  looked like it had no transforms at all. Both now accept an authored seed CSV as
  transform content.
- **Extraction matches dbt's own semantics.** `source()` calls are recognized in both the
  positional and keyword (`source_name=`/`table_name=`, either order) forms; Jinja
  `{# ... #}` comments are stripped before `ref()`/`source()` extraction so commented-out
  calls create no phantom dependencies or false diagnostics; `ref()` names match authored
  file stems case-exactly on every platform; and an unreadable or non-UTF-8 dependency file
  (e.g. a cp1252 seed CSV export) is a binding-attributed
  `dbt-source.dependency-unresolved` diagnostic instead of a crash. `field-mapping-report`
  lineage treats a seed-backed `ref()` as a traceable leaf.
- **A `source()` call the compiler cannot read now fails the compile instead of being
  silently skipped (new `dbt-source.source-unparsed`).** Any `source(` call site whose
  arguments are not statically resolvable — mixed positional/keyword arguments, `var()` or
  other variable arguments, string concatenation, macro-generated names — is reported with
  the supported forms named, in both closure walks. Previously such a call produced no
  catalog entry and no diagnostic, so the failure only surfaced later as an offline
  `dbt parse` error. Macros whose names merely end in `source` (e.g. `my_source(...)`) are
  unaffected.
- **Commands that hit an incomplete ontology closure no longer die with a raw
  `OntologyLoadError` traceback (issue #587).** The CLI boundary now renders the
  exception's attached diagnostics to stderr — `missing_import` entries first — and,
  when those missing imports coincide with `kairos-ontology-referencemodels` being
  absent from the running interpreter (the typical pipx / `uv tool` global-install
  symptom), adds a hint to use `uv run kairos-ontology …`. Exit code stays 1 and the
  DD-151 `kairos.cli.command.failed` record is still written.
- **The outside-venv startup warning now catches pipx / `uv tool` global installs
  (issue #587, DD-049 amendment).** The guard is identity-based: inside a managed hub
  it compares `sys.prefix` against the hub's own `.venv` instead of asking "am I in
  *some* venv?" — a global pipx install is a venv too, so it previously passed
  silently and then failed with missing hub-pinned packages. Outside a managed hub
  the old bare-global heuristic is unchanged.
- **The auto-close-issues workflow no longer closes a multi-part issue when a merged
  PR references it with a partial-fix qualifier (issue #578).** `(#562 P2)`,
  `(#562 P3+P4)`, and `(#562 Problem 2)` now mark the reference as scoped to part of
  the issue and leave it open (PR #577 closed #562 with Problems 3 and 4 untouched).
  A Python meta-test pins the workflow's inline regexes and reimplements its decision
  loop, and the SC-merge-pr skill, PR template, and CONTRIBUTING now describe the
  workflow's actual parenthetical-close behavior.

### Added
- **Seed column docs are a first-class authored artifact (issue #586, stage b).** A sibling
  `integration/transforms/dbt/seeds/<name>.yml` (or `.yaml`) next to `<name>.csv` is dbt's
  plain `seeds: - name: ... columns: ...` properties form. It is deliberately **not** a
  `meta.kairos` contract — a seed is not a bindable virtual source, so it declares no output
  contract and stays out of the contract-parsing path entirely. Selecting a seed into a
  compile closure selects its sibling docs too, and both are emitted together under `seeds/`.
  Carried on the plan as a new `seed_properties` dependency kind, which — like model
  properties YAML — has no `model_name`: the CSV owns the resource name and the document only
  describes it.
- **`validate-dbt-contracts` gains three seed findings (issue #586, stage b).**
  `dbt-contract.seed-docs-unmatched` (warning) for seed docs naming no authored CSV stem
  (typo or stale docs after a rename); `dbt-contract.seed-unreadable` (warning) for a CSV
  that is unreadable, not UTF-8, or has an empty header row; and
  `dbt-contract.seed-model-collision` (**error**, not a warning like the other two) for a
  seed stem colliding with an authored model stem — dbt resolves `ref()` in one resource
  namespace, so the generated project would fail to parse, and the dbt bundle hard-fails the
  same case. A lint that called that advisory would disagree with the build.
- **`init` and `new-repo` now create `integration/transforms/dbt/seeds/`.** Note that
  `update` does **not** backfill hub directories: an existing hub must `mkdir
  integration/transforms/dbt/seeds` itself before authoring its first seed. This is the
  scaffold's standing behavior, not a seed-specific gap.

### Changed
- **Compiled dbt dependencies are validated through a kind registry instead of a boolean
  ladder (issue #586, stage b).** `compile`'s dependency-state loader hand-expanded per-kind
  checks and then computed `expected_prefix = "seeds/" if kind == "seed" else "models/"`,
  whose else-branch silently claimed every future kind lives under `models/`. Each kind now
  declares its allowed suffixes, whether a `model_name` is required, and its expected path
  prefix, so an unknown kind fails closed instead of being mis-validated against a default.
- **The deferred `dbt_bundle`/`dbt_source` ref-regex consolidation is settled as a
  deliberate non-consolidation (issue #586, stage b).** The two regexes encode opposite
  obligations and stay separate permanently: `dbt_source.REF_RE` is a *selection* rule that
  must match dbt's own resolution exactly (case-sensitive, single-argument), while
  `dbt_bundle._REF_RE` is a *fail-closed validation* rule that is deliberately over-broad
  (IGNORECASE, accepts the two-argument package form). What did consolidate is the one real
  defect the duplication caused: `dbt_bundle` now strips Jinja `{# ... #}` comments through
  the shared helper, so a commented-out `ref()` is no longer read as a dependency or as an
  unresolved-ref error. The compiler's filesystem and plan walks share one `extract_refs()`
  helper, mirroring #584's `extract_sources`.
- **Open question, deliberately unresolved:** emitted seeds land in the profile's default
  target schema with dbt's default type inference, because no `seeds:` config block is added
  to the generated `dbt_project.yml`. Seed schema, quoting, and explicit `column_types` are a
  materialization design decision with its own adapter-portability consequences.
- **The cross-domain union of shared `_<system>__sources.yml` catalogs now fails closed.**
  Previously, when two domains rendered the same source with conflicting header metadata
  (database/schema/description) or conflicting same-name table entries, the first-seen
  variant silently won. `compile --emit` now aborts with an artifact-collision error before
  touching the target tree; re-emit every domain after a vocabulary change that alters shared
  source metadata. Non-conflicting unions produce byte-identical output as before.

## [5.13.0rc21] — 2026-08-20

### Added
- **`compile --no-cache` bypasses the new ontology-closure parse cache.** Use after
  manually editing a hub's `.cache/ontology-parse/` directory, or when debugging a
  suspected stale-cache result.

### Fixed
- **`compile <domain> --emit` was slow because the compile path reparsed and
  re-resolved the same inputs repeatedly, with no caching anywhere.** Three fixes:
  (1) `resolve_scope` parsed every hub-wide source `.ttl` file up to twice just to test
  which ones a domain's bindings reference; it now parses each candidate at most once,
  gated by a cheap byte-level pre-filter that skips files that provably cannot match.
  (2) A dbt-sourced binding's contract and SQL dependency closure were read up to three
  times per compile (`resolve_scope`'s pre-pass, its duplicate-virtual-source check, and
  `build_compile_plan`'s main loop); they are now resolved once and reused via
  `ResolutionContext`. (3) `load_ontology` now caches the parsed `owl:imports` closure:
  in-process for the lifetime of one compile (content-hash verified before every reuse,
  so a hub file changing mid-process is never served stale), and on disk per source file
  (content-hash keyed, so it survives across the separate `compile --emit` processes a
  hub-wide release job runs one per domain). The on-disk cache only ever gets written
  during `--emit`, never during `--check`/`--explain`, and lives in a gitignored
  `.cache/` directory scoped to one call so it can never leak into another command.

## [5.13.0rc20] — 2026-08-20

### Fixed
- **`compile --emit` now includes the contracted dbt dependency closure selected by each
  immutable `CompilePlan` (issue #580).** Authored SQL, transitive authored `ref()`
  dependencies, and the selected properties YAML are copied to their stable paths in the unified
  dbt project. Per-domain dependency ownership is reconciled across sequential emits, stale files
  are removed only after their final owner drops them, and conflicting paths, bytes, or dbt model
  names fail closed.
- **`audit-silver-samples` no longer reports contracted dbt virtual outputs as missing Bronze
  columns (issue #581).** Contracted output columns now produce an informational offline-evaluation
  limitation with contract paths and traceable contributing source systems. Genuine missing
  physical source columns remain errors, so `--fail-on error` retains its intended meaning.

## [5.13.0rc19] — 2026-08-20

### Changed (BREAKING, privacy-relevant — see DD-205)
- **Source sample values now reach Langfuse, the alignment review artifact, and the alignment LLM prompt itself by default (DD-205, issue #562, maintainer-authorized).** Three independent masks previously starved the pipeline of the sample evidence that most helps diagnose a bad mapping: Langfuse tracing masked the `| samples: ...` block (`KAIROS_LANGFUSE_SEND_SAMPLES` now defaults to `1`; set `0` to mask); `example_values` in `*-alignment.yaml` always masked PII-shaped values (now gated by the same setting as below; set `KAIROS_ALIGNMENT_SEND_RAW_SAMPLES=0` to restore masking); and the alignment prompt itself only ever saw the committed vocabulary's *permanently* redacted values, since there was no other on-disk copy to read from.

### Added
- **A new raw-sample channel feeds the alignment LLM prompt itself (DD-205, issue #562).** `import_source.py`/`import_flatfile.py` now also write pre-redaction sample values to a new gitignored sidecar (`.import/raw-samples/<system>.json`, alongside the existing `.import/businessdiscovery/` convention) at the same import step that has always redacted the committed artifacts. `propose_alignment.py` overlays these values onto the prompt when available; the per-table cache key picks up the change automatically since it already hashes the (now-overlaid) samples. `KAIROS_ALIGNMENT_SEND_RAW_SAMPLES` (default on) governs the channel end to end — off means the writer never creates the file, not just "the reader ignores it". The committed vocabulary/source-dir artifacts remain permanently redacted regardless of this setting. `kairos-design-domain`/`kairos-design-mapping` SKILL.md Gates updated: `example_values` can no longer be assumed pre-redacted.

## [5.13.0rc18] — 2026-08-20

### Fixed
- **`rdfs:domain owl:Thing` silently produced dead properties, invisible to the compiler and every projector, with no diagnostic anywhere (DD-204, issue #328).** Issue #328 was closed by #330, but #330's own diff explicitly left this half — the domain side — "deliberately unchanged"; only the sibling `rdfs:range owl:Thing` case got a warning. Reopened with fresh evidence: a real client hub's `coverage-report` found 49 property-domain assertions in the reference-models package's own `onerecord.iata.org/ns/cargo` module, all declaring `rdfs:domain owl:Thing`, none of them attached to any class. `_warn_unattached_property_domains` now tells the two causes apart instead of blaming every unattached property on a missing `owl:imports`: an `owl:Thing` domain gets its own message pointing at issue #328, since no amount of importing fixes it.

### Added
- **`validate_naming_conventions` gains `property_domain_owl_thing` (DD-204, issue #328).** Mirrors the `property_range_owl_thing` warning #330 shipped for the range side: an `owl:DatatypeProperty`/`owl:ObjectProperty` in a hub's own authored file whose `rdfs:domain` includes `owl:Thing` now gets a warning at author time, suggesting `schema:domainIncludes` as the alternative that avoids an `owl:imports` cycle. Reference-model files are still never validated (DD-188) — this only ever fires on a hub's own domain files.

## [5.13.0rc17] — 2026-08-20

### Removed (BREAKING)
- **The `affinity` AI-provider role collapses into `alignment` (DD-203, issue #562).** `analyse-sources` and `propose-alignment` used to have separate, independently-configurable AI-provider roles; issue #562 asked for one role, the strongest configured provider, for every pre-modeling LLM call. `ROLE_AFFINITY` is removed outright (a hard removal, not a shim): `KAIROS_AI_AFFINITY_*` env vars (`_ENDPOINT`/`_KEY`/`_MODEL`/`_SEED`/`_REASONING_EFFORT`) are no longer read at all — rename them to `KAIROS_AI_ALIGNMENT_*`. `check-ai-config --role` drops the `affinity` choice. This is a deliberate behavior change, not a rename: `analyse-sources`'s default reasoning effort rises from `low` to `medium` (alignment's tier), and any `KAIROS_AI_ALIGNMENT_*` tuning now also governs the high-volume table-classification call.

## [5.13.0rc16] — 2026-08-20

### Fixed
- **`generate-bindings` failed 27/59 tables (46%) with a generic schema error instead of skipping them (DD-202, issue #565).** This generator never emits `relationships:` (deferred to `propose-relationships`), so any table with zero mapped scalar fields was always going to fail the v5 contract's conditional-`relationships:` requirement — and a table with `grain_columns: []`/`natural_key: []` failed the same way. Both are now recognized as non-generatable *before* a draft is built, and report `skipped` with a specific reason (e.g. "no grain identified on the sheet row", or "no scalar fields mapped for this table" with a note when relationship wiring was deferred) instead of `invalid` with a generic validator message.

## [5.13.0rc15] — 2026-08-20

### Fixed
- **A class-name collision across two DIFFERENT domains was resolved by ownership, not richness (DD-201, issue #564).** `choose_class_copy` hard-filtered candidate copies into a same-domain-owned tier before any richness scoring ran, so a richer copy owned by a different domain (e.g. BSP's `Person`) was discarded in favor of a bare same-domain copy (IATA's `Person`) purely because of catalog read order — the sibling of the #519 defect one level out. Same-domain ownership is now a tie-break inside the ranking, after column-property overlap and property count, not a filter ahead of them. A deterministic `property-less-anchor` sheet flag now also survives into `table-anchors.yaml` whenever a resolved anchor has zero properties (previously console-only).
- **The global-anchor path's resolved URI never reached `likely_entity_uri` (DD-201, issue #564).** `TableAlignment.likely_entity_uri` was only populated on the older uri-anchor-contract "confirmed" path; the newer global-anchor/design-sheet path (DD-185/190) never carried its own resolved `anchor_uri` forward, even though both existing consumers (`design_landscape`, `conformance_evidence`) already prefer it over the bare `ref_class` name. `design_landscape` also gains a defensive fallback to `table-anchors.yaml` for already-generated alignment artifacts that predate this fix, guarded to only apply on an exact anchor-name match.

## [5.13.0rc14] — 2026-08-20

### Fixed
- **`update-refmodels` silently did nothing, then reported success (DD-200, issue #551).** Reference models ship only as a GitHub Release wheel, never to a package index, so `uv pip install --upgrade kairos-ontology-referencemodels` (the default, no-`--version` path) had no package to find and installed nothing — this is how a real hub's pin sat thirteen minor versions behind (#541). The command now resolves the latest published release the same draft-filtered, version-ordered way scaffolding does, and always installs that exact wheel. Also fixed: an unprefixed `--version 1.33.1` produced a 404 pin (no `v`-prefix normalization) — now normalized like every other caller.

### Added
- **`update --upgrade` also upgrades reference models (DD-200, issue #551).** Previously it only ever moved the toolkit pin; a hub's reference-models pin drifted independently with nothing to catch it. A hub that pins reference models (a dataplatform repo never does) now gets both upgraded in one `--upgrade` run — non-atomically (the toolkit half was never transactional either), but a refmodels-side failure is now named and exits 1 rather than silently leaving the hub on a new toolkit with a stale reference-models pin.

## [5.13.0rc13] — 2026-08-20

### Fixed
- **AI preflight surfaces a missing SDK as a missing dependency, with a uv-native fix (DD-198, issue #553).** `check-ai-config --probe` against a hub with `KAIROS_AI_PROVIDER` configured but the matching SDK not installed previously reported `unreachable` with a "verify network connectivity" remediation — misleading, since no network call was attempted, and it buried the real install hint. `_probe_client` now lets the underlying `NotConfigured` propagate instead of rewrapping it, and `preflight_ai_provider` reports a new `missing_dependency` status with the exact fix as remediation. The Foundry (×2) and Azure `NotConfigured` messages themselves, and the scaffolded `.env.example`'s install comments, now say `uv sync --extra foundry/azure` instead of `pip install kairos-ontology-toolkit[foundry/azure]`.

## [5.13.0rc12] — 2026-08-20

### Added
- **`[tool.kairos].max_workers` sets a hub-level default for `--max-workers` (DD-197, issue #562).** `analyse-sources` and `propose-alignment` both bound their per-table LLM call concurrency via `--max-workers`, but a hub had no way to set its own default the way `accelerator`/`channel` already can — every invocation needed the flag retyped. Precedence: explicit `--max-workers` > `[tool.kairos].max_workers` > the existing default of 16.

## [5.13.0rc11] — 2026-08-20

### Fixed
- **`coverage-report` (and every caller of `resolve_reference_models`) scanned archived reference-model snapshots and misattributed their pre-fix content to live modules (DD-196, issue #566).** An archived `.ttl` under `derived-ontologies/<vendor>/archive/**` shares its live module's permanent IRI, so a defect already resolved in the live file (e.g. a missing `owl:imports`, fixed upstream in referencemodels v1.32.0) still resolved from the frozen pre-fix snapshot and got reported as if it were live. Archived paths are now excluded unconditionally, matched on path segment rather than a caller-supplied glob — this was originally filed against the reference-models repo (#108) before the real cause (this toolkit's resolver, not the reference data) was identified.

## [5.13.0rc10] — 2026-08-20

### Added
- **Scaffolded hubs never had a way to install the `langfuse` extra (DD-195, issue #563).** The scaffold template only passed through `azure`/`foundry`/`flatfile`/`parquet`/`otel`; `langfuse` is now offered the same way, so a hub with real Langfuse credentials in `.env` can `uv sync --extra langfuse` instead of tracing silently no-oping.

## [5.13.0rc9] — 2026-08-19

### Fixed
- **`profile-sources` no longer crashes on a unique timezone-aware timestamp column (DD-194).** Found on a real client extract: key-set construction ran `to_pylist()` on any `unique`-tagged column regardless of type, and a tz-aware timestamp needs a timezone database (`ArrowInvalid` on a bare Windows Python without `tzdata`). Temporal columns are now excluded from key-set candidacy outright — a timestamp was never a meaningful FK join signal — while keeping their `unique`/`date-like` profile tags unaffected.

## [5.13.0rc8] — 2026-08-19

### Fixed
- **Source profiling's class catalog is scoped to the resolved accelerator (DD-193, issue #558).** `build_class_catalog` (and thus `anchor-tables`) previously offered every module the whole installed reference-models package maps as an anchor candidate — on a logistics hub this put ~400 FIBO classes in front of the model as `UNOWNED` noise, with a real risk of a table falling back to an unrelated vendor class instead of being flagged for review. `read_reference_terms` gains an optional `module_scope` parameter (defaulting to the unrestricted legacy behaviour every other caller keeps); `build_class_catalog` seeds it with the resolved accelerator's own declared domain imports. A module the accelerator never reaches, directly or transitively, is excluded outright; a module reached only via `owl:imports` from an accelerator-declared module remains visible (transitivity is unaffected — only the seed set narrows). An unresolved accelerator keeps today's unrestricted behaviour rather than emptying the catalog.


## [5.13.0rc7] — 2026-08-19

### Added
- **Design rulings: durable human modeling decisions that outrank model judgment (DD-192).** `integration/discovery/design-rulings.yaml` records contested-space resolutions once, by condition (`applies_when`), and `anchor-tables` renders them into the global prompt with `rulings_applied` provenance in the artifact. Boundaries: only human-decided entries feed the prompt (model proposals are inert and reported); a ruling never introduces a class (unresolvable targets skipped with reasons; `rejection` rulings exempt); a ruling never maps columns. Absent file is a silent no-op. Validated live: ruled tables converge to the ruled answer (0.91–0.95, rejected candidate kept as alternate) with collateral movement confined to already-unstable rows.


## [5.13.0rc6] — 2026-08-19

### Added
- **`generate-bindings`: first-draft EntityBindings from the design sheet (DD-191, no LLM).** One draft per anchored, non-rejected sheet row with a `propose-alignment` result: reuse-first `target.class` from the sheet's anchor URI, fields from scalar alignment mappings (module-scoped resolution, duplicate claims deduped by confidence), object-property and sheet-relationship columns as `technicalFields purpose: relationship`, grain/natural-key columns materialized `purpose: identity` with profile-derived canonical types, and quality tests only where the DD-189 profile proved them. Every draft is validated against the closed v5 contract BEFORE writing — invalid drafts are reported, never written — and existing bindings are never overwritten without `--force`. Secondary entities are echoed as a worklist, never auto-generated.


## [5.13.0rc5] — 2026-08-19

### Changed
- **`propose-relationships` gains two evidence sources it was blind to.** Tier-2 join matching consumes DD-189 `fk?->table.col` profile tags: measured value containment resolves joins exact name equality cannot see (a child `parent_ref` column proven contained in the parent's key), labelled `[join from measured fk-inclusion evidence]` and carried as `join_evidence` in the JSON output; same-system only, tier-1 name equality still wins when it applies. And `owl:inverseOf` is now entailed: a property declared parent→child whose inverse asserts no domain/range of its own yields the swapped edge, so the side that actually carries the FK can receive a proposal (the TransportOrder `coversConsignment` / consignment-side FK gap).


## [5.13.0rc4] — 2026-08-19

### Changed
- **`anchor-tables` output is now a reviewable design sheet (DD-190, artifact schema_version 2).** The global call additionally returns per-table `relationships`, `secondary_entities`, and `flags` — each validated deterministically (unknown/self relationship targets, non-column join inputs, invented secondary classes and same-grain clusters are dropped and counted, never kept silently). Entries carry `status` and `schema_hash`: a human-`confirmed`/`edited` entry with an unchanged schema is pinned — preserved verbatim and excluded from the model call — and a pinned entry whose schema changed releases to `stale-confirmed` with the previous values kept for review. `propose-alignment` applies confirmed sheet anchors without the confidence floor (`sheet-confirmed`); out-of-pool anchors are still never applied. All new fields are additive; v1 artifacts keep working unchanged.


## [5.13.0rc3] — 2026-08-19

### Added
- **`profile-sources`: deterministic Stage-0 profiling of raw `.import/` extracts (DD-189).** Per-column statistics and signal tags — null/empty ratio (blank strings count), cardinality (`unique`/`const`/`low-card(n)`), value shape, sampled cross-table `fk?->table.col` inclusion evidence, and `versioned?`/`code-list?`/`empty-table` table tags — written to `integration/sources/<system>/<system>.profile.yaml` with an evidence-basis marker. Statistics only: no data value is ever persisted. `anchor-tables` consumes the profile automatically (outline annotations + legend); always-empty columns are omitted from model context only under a declared `data_maturity: production` (`kairos.yaml`, `--data-maturity` override) — otherwise every tag is advisory. Measured on the validation corpus: grain 9/9 with profile tags vs 0/9 without (every unprofiled miss keyed on the SaaS tenant discriminator).



</details>

## [5.13.0] — 2026-08-18

### Added
- **`next` now proposes recording a source-table disposition (DD-164).** This was the only gate in the flow that `validate` *enforced* without anything ever *asking for it* — no skill step, no next action. The first an operator heard of it was a red `validate` late in a run, by which point the backlog had accumulated: on the hub that prompted this, **70 tables were outstanding at once**.

  New `SourceDispositionObservation` (`tables_total`, `tables_undecided`, `coverage`) and a blocking `record-source-disposition` action routed to `kairos-design-source`, the lifecycle owner. The rationale carries the counts and the coverage percentage so the work can be sized from the line alone, and names the distinction from the column-grain gap gate (DD-169/DD-186, `draft-gap-decisions`) — confusing the two sends the operator to the wrong command.

  Status is `HUMAN_DECISION_REQUIRED` rather than `BLOCKING`: `validate` does block on it, but the reason it cannot be automated is that *"is this table in scope"* is a judgement, not a derivable fact. Proposed, never applied.

  The observer degrades to the all-zero no-observation default on any failure, so a hub mid-import with a half-written vocabulary cannot take `next` down — and an all-zero observation reports `coverage == 1.0`, because *no imported tables* must not read as *nothing decided*.

### Changed
- **`next` proposal `SCHEMA_VERSION` 6 → 7.** Consumers pin this; every prior observation set bumped it, and the two tests that assert it were updated rather than relaxed.

## [5.12.0] — 2026-08-18

### Changed
- **An anchored table's class pool is now derived from its anchor instead of lexically scored.** `_score_ref_class` ranks classes by how many of their *properties* match the table's columns, which answers *"which class holds columns like mine"* — not *"what is this table"*. Conflating the two inverts the answer whenever a table is largely built from some other class's properties: measured on a live hub, `Address` scored **44** against `TradeParty`'s **20** for a *companies* table, because a companies table is mostly address columns. Denoising cannot fix that — `Address` genuinely does hold those properties. The question was wrong.

  DD-185 already answers the identity question globally against the full catalog, and `anchor_override` already pins the result in the prompt. What was missing is that the *pool* was still built by the scorer, so a lexically-similar but unrelated class kept contributing properties to STEP 2. The prompt permits a column to map to a property of the anchor *or of any other listed class*, so that pool is the STEP 2 property surface, not decoration.

  New `anchor_derived_class_pool` offers the anchor (always first, always present), its specializations, and classes reachable through blueprint-declared bridges (DD-181). Value objects one hop out continue to come from `expand_value_object_pool` (#517) downstream. It returns empty — and the run falls back to the lexical shortlist — when the anchor is blank, unresolvable in the domain, below `ANCHOR_CONFIDENCE_FLOOR`, or outside the domain's pool, so nothing is ever sent a pool that lacks its own anchor.

  **The lexical path is untouched for un-anchored tables and `--without-anchors` runs.** This is additive, not a swap.
- **The full-inventory retry no longer fires on an anchored table.** The retry existed because a lexical shortlist is unreliable; when the class is already decided, widening cannot improve STEP 1 and floods STEP 2 with ~1200 classes the model must read past. A weak result on an anchored table is a gap signal, not a cue to widen. This was previously ungated: `anchor_override` pinned the class in the prompt but did nothing to stop the retry.
- **Each domain reports which question decided its pools** (`class pool: 9 from anchor, 2 from lexical`). Per domain rather than per table — on a 70-table hub the per-table line is noise, but a domain where every pool came from the scorer means the anchors did not resolve, and that should be visible without `--verbose`.

### Notes
- **Not measured end-to-end.** This ships on unit and integration evidence plus the mechanism argument; there is no before/after run on a real hub, because the labelled oracle that would have scored anchor accuracy was dropped by decision. The integration tests assert the *wiring* (an anchored table is not offered the lexically dominant class; an un-anchored one still is), which is weaker than a measured improvement in mapped columns. Treat the 44:20 figure as the motivation, not as a result reproduced here.

## [5.11.1] — 2026-08-18

### Changed
- **Tested against reference models 1.35.0 (was 1.33.1).** Picked up by `scripts/check_refmodels_pin.py --check`, which failed the pin within twenty minutes of the release — the reciprocal check added in 5.10.2 doing exactly what its absence had prevented for thirteen minor versions. `_REFMODELS_FALLBACK_TAG` follows to `v1.35.0`, which the tether test in `test_scaffold_refmodels_pin.py` required rather than merely suggested: that test was the only failure in the run against the new bundle.

  1.35.0 closes reference-models gh#104, filed from this repo: `freight-forwarder` goes **13 → 36 modules and 52 → 203 core concepts**, gaining `bsp/financial`, `bsp/cost-accounting`, `bsp/revenue-yield` and `bsp/commercial`, and with them 38 money concepts where it previously had **zero**. One of the new labels — `Charge (cost and/or sell line on a job)` — is the concept the issue's evidence was built on. Full suite green against it: 4415 passed, 4 skipped.

## [5.11.0] — 2026-08-18

### Changed
- **BREAKING: `propose-alignment` now refuses to run when `table-anchors.yaml` is absent.** It read the artifact and said `if global_anchors:` with **no `else` branch**, and `load_table_anchors` returns an empty mapping when the file is missing — so a hub that never ran `anchor-tables` skipped the entire DD-185 regrouping block in total silence and the run looked normal.

  What that costs is stated in the code's own comment at that line: *"this is what makes affinity a prior rather than a constraint: a misplaced table is aligned in the domain whose classes it actually needs."* Without anchors, affinity becomes a hard constraint. On the hub that prompted this guard, **18 of 68 tables ended with an empty `ref_class`, and every domain with empty anchors scored 0% mapped.**

  The same file carries the `excluded` block, so its absence *also* silently disabled the schema-catalogue screen — one missing file, two features quietly inert, which means the 5.7.0 and 5.8.0 exclusion fixes never took effect on any hub that skipped anchoring.

  Pass `--without-anchors` to proceed anyway; it says so loudly, twice. Modelled on `--without-discovery`: refuse by default, proceed when the operator insists. **Existing hubs that never ran `anchor-tables` will now stop** — that is the point, and `anchor-tables` is the one-command fix.

### Added
- **A three-way signal for pipeline artifacts: absent / unparseable / present-but-empty (`ArtifactState`, `probe_anchors`).** Every loader in `anchor_tables.py` collapsed those into one empty result, so callers could not tell "you have not run `anchor-tables`" from "anchoring found nothing". The refusal message differs accordingly: a missing artifact says run `anchor-tables`, an unparseable one does *not* — re-running would overwrite whatever it holds.
- **A malformed disposition ledger is now fatal (`MalformedLedgerError`).** `load_table_dispositions` and `load_excluded_columns` returned an empty result on a parse failure **with no log line at all**. The first exists precisely so the schema-catalogue heuristic cannot overrule a recorded decision, so degrading to empty let a heuristic quietly overrule human governance while reporting success. An *absent* ledger stays the normal case; only a present-but-unreadable one raises. This follows the distinction `registered_concepts` already draws for a malformed registration file.

### Fixed
- **Three loaders swallowed a parse failure in complete silence** (`load_excluded_columns`, `load_table_dispositions`, and the per-file `continue` in `load_affinity_domains`). All artifact reads now go through one helper that always warns on corruption and never warns on absence.
- **`extract_ref_model_inventory` discarded a class's properties depending on module order (#540).** A class URI reachable from two modules was deduped first-wins, so the *later* module's view of the same class was thrown away. Measured against the shipped reference models, `bsp:TradeParty` resolved to **13 properties or 17 purely on module order** — 13 forward, 17 reversed.

  Identity is still the URI; only the property sets are now unioned, own-before-inherited and sorted within each group so DD-175 reproducibility holds. A merged class records `contributing_uris` in its `_semantic` block. That block is read only for `source_identity` (the prompt's module list), so no closure hash, prompt, or determinism baseline moves.

  This is one function with six consumers — the class candidates `_score_ref_class` ranks, the cross-module property pool, `resolve_bridge_anchor_classes`, the `anchor-tables` tie-break, `class_anchoring` and `scaffold_system`. A truncated property set silently depresses a class's score against a class that kept its full set, which is a candidate contributor to the measured `Address` 44 : `TradeParty` 20 inversion on a `companies` table. Because the truncation was *order-dependent*, no seed could make a run reproducible — so this is a prerequisite for measuring any alignment change, not just an undercount.

## [5.10.2] — 2026-08-17

### Added
- **`scripts/check_refmodels_pin.py` — the reciprocal reference-models pin check (#541).** The reference-models repo has failed *its* build on toolkit pin drift for some time via `scripts/check_toolkit_pin.py`; nothing enforced the other direction. That asymmetry is why this repo's pin sat at `v1.20.0` while `v1.33.1` was current — thirteen minor versions — with the cross-repo contract and bundle-conformance suites reporting green against a 1.20-era bundle. Passing against a stale bundle is weaker evidence than it looks: those suites were green against a bundle that predated the very defects this repo spent the week finding.

  `--check` for CI, `--update` to rewrite the pin and re-lock. Channel-aware via `[tool.kairos] refmodels-channel` (default `stable`), so a pre-release does not fail the build, and it degrades to a pass when the release feed is unreachable — a firewalled contributor is not pin drift. Wired into `ci.yml` as its own job, so it can neither mask nor be masked by a test failure.

  Latest-release resolution is deliberately **not** reimplemented in the script: it imports `_list_published_release_tags` / `_latest_stable_tag` from the toolkit, so drafts are filtered and ordering is by version. #542 was caused by a second, sloppier copy of exactly that logic; a third copy in a CI script would have been the same mistake again.

  No release-time exemption is wired, unlike the sibling repo's `skip-toolkit-pin-check` input: `release.yml` triggers on tags and declares its own jobs, so it never calls `ci.yml` and this time-dependent check cannot block a release. The reasoning — including why such a guard must be phrased as skip-rather-than-require — is recorded in `ci.yml` for whoever changes that.

### Fixed
- **A freshly scaffolded hub could be born on a stale reference-models bundle (#542).** `_resolve_scaffold_refmodels_pin` picked the pin with `gh api /repos/.../releases --jq '.[0].tag_name'`, which is wrong in two independent ways: `/releases` includes **drafts** and GitHub lists them ahead of published releases, and element zero is the newest *by creation date*, not by version. The refmodels repo held a draft tagged `v1.28.1`, so every hub scaffolded after 2026-08-16 17:54Z pinned `v1.28.1` while `v1.33.1` was current.

  Nothing caught it. `gh` exited 0 with a non-empty tag, so the existing "could not list releases" warning never fired, and because a *published* `v1.28.1` also exists the wheel URL built from the draft's tag resolved and `uv sync` succeeded. A client hub therefore ran the bundle that predates the 1.32.0 `owl:imports` fix and 1.33.0 module routing — precisely the ontology that makes 5.10.0's `property-domain-unreachable` warning fire.

  Both scaffold pins now resolve through one shared `_list_published_release_tags`, which filters drafts in the jq expression and sorts by PEP 440 version. This also closes a gap in the *toolkit* pin: `_resolve_scaffold_toolkit_pin` documents that it "only ever pins a ref that has a published GitHub release", but it delegates to `_resolve_channel`, which read drafts too — a draft toolkit release would have produced a pin that 404s on a hub's first `uv sync`.
- **`--ref-models-version` did nothing.** Both `init` and `new-repo` declared the option, accepted it as a parameter, and never read it, so the documented way to reproduce a known-good bundle silently pinned latest instead. It is now threaded to the resolver and accepts either `v1.29.0` or `1.29.0`.

### Changed
- `init` and `new-repo` print the pins they resolved (`toolkit v5.10.1 (channel 'stable'), reference models v1.33.1`). The resolvers were silent on success, so a mispin was invisible at the one moment an operator could still question it.
- `_REFMODELS_FALLBACK_TAG`, used only when the release list is unreachable, moves `v1.20.0` → `v1.33.1` and is now tethered by a test to the reference-models version this toolkit is actually tested against. It had drifted thirteen minor versions behind with nothing to catch it; bumping the dev pin (as #539 did) now forces the fallback to keep up, with no network access needed in CI.
- The `--ref-models-version` help examples advertised `v1.19.0`, fourteen releases old. They are illustrative, not functional, but they read as recommendations. Refreshed to `v1.33.1` in `cli/setup.py` and `cli/operations.py`.

### Notes
- The `>= v1.11.0` mentions in `cli/sources.py` and `core/archetype_loader.py`, and the `v1.13.0` mention in `core/pattern_loader.py`, are deliberately **left alone** despite being listed alongside the help-text examples in #541. They are not stale recommendations: the first two state the contract floor at which a reference-models checkout becomes readable, and the third records which release shipped `temporal-quartet` unparseable. Raising them would assert a floor the code does not require and falsify a historical fact.

## [5.10.1] — 2026-08-17

### Fixed
- **A typo'd anchor counted as an anchor, silencing two checks and inflating the anchoring score (#537).** `scan_domain_ontology` treated *any* non-local `rdfs:subClassOf` / `owl:equivalentClass` / `rdfs:subPropertyOf` parent as an anchor without resolving it. A parent in a correctly imported module but with a misspelled local name therefore registered as anchored, which suppressed `integrity.class-unanchored` and `integrity.local-class-shadows-reference-model` and raised `class_anchoring` / `property_anchoring` in the report score. A correctly spelled dangling reference was an error; a misspelled one was rewarded.

  Anchoring is now resolution-aware: `audit_ontology_integrity` resolves the reference modules before the scan rather than after, and a parent absent from the module it names no longer anchors. Behaviour is unchanged when no catalog resolves (`compile` passes none) and for modules the catalog does not manage — declaring every anchor broken in those cases would be worse than the bug.

  Patch rather than minor: both checks that resume firing are advisory, so no build that passed before fails now. 5.10.0's `integrity.external-term-unresolved` already reported the typo itself; this restores the three signals it was suppressing.

## [5.10.0] — 2026-08-17

### Added
- **Reference-model properties that attach to no class are now reported (#534).** A property whose `rdfs:domain` names a class its module never `owl:imports` attaches to nothing, and was dropped in silence — the property was enumerated and its domain resolved, then discarded because no bucket existed. The silence was the defect: it made a real reference term indistinguishable from an absent one, so a coverage audit proposed adding terms the model already defined. `SemanticIndex` gains `unattached_property_domains`, threaded beside `import_complete` and summarised once per resolution pass.

  On the shipped reference models: **50 distinct orphaned assertions across 14 modules** in four of five vendor trees, every module reporting `import_complete: True`. The upstream fix is the missing `owl:imports` (reference-models #97); this only makes the loss visible, and is advisory because the toolkit consumes bundles it does not own.
- **`integrity.external-term-unresolved`** — flags a reference term a hub TTL names that does not exist in the module it names. Distinct from `missing_managed_import`, which asks whether the *module* is imported; this asks whether the *term* is real. A typo in the local name satisfies the import check completely and was previously caught by nothing. Registered `DEGRADABLE`, matching the severity of the check it complements.

### Notes
- `unattached_property_domains` is excluded from `SemanticIndex.to_dict()`: it describes what a closure failed to hold, so it must not move a closure hash or a determinism baseline.
- No global warning-dedup state was introduced. An earlier draft proposed a module-level set to suppress repeats across the ~131 parses in a run; threading the data on the returned dict removes the need, and `extract_ref_model_inventory` is untouched.
- **Known gap, tracked separately:** `scan_domain_ontology` still counts a class as *anchored* on the strength of an unresolvable parent, so a typo'd `rdfs:subClassOf` continues to silence `check_unanchored_classes` and both arms of `check_reference_model_shadowing`. The new diagnostic surfaces the typo; it does not yet restore those three checks.

## [5.9.0] — 2026-08-17

### Changed
- **The address detector in `propose-alignment` is now driven by pack data, not by constants compiled into the toolkit (#531, DD-188).** `propose_alignment.py` carried postal-address semantics across six `_ADDRESS_*` vocabularies, including an *e-commerce* role list — `billing`, `shipping`, `mailing`, `home`, `work`, `delivery` — with no `pickup`, `origin` or `destination`. On a live logistics hub that asymmetry was the whole defect: `delivery_location_city` clustered and `pickup_location_city` did not. All six are deleted. The detection *logic* stays in the toolkit (cluster a table's columns by role, require `min_complementary_parts` distinct kinds, resolve the target class in the domain's import closure, emit an advisory candidate); every token now comes from the accelerator pack's `client-hub-blueprint/entity-projections.yaml`, read by the new `core/entity_projections.py` alongside the `data-domains.yaml` precedent.

  Measured on the 75-table hub with the logistics pack's file: `stops` 1 candidate / 5 columns → **3 / 18**; `orders` 0 → **3 / 13**; `shipments` 0 → **2 / 10**; `bookings` 0 → **1 / 24**; `consignments` 1 / 5 → **2 / 12**; hub-wide 10 clusters → **29**. No new cluster appeared on a party or person table: `contacts` still emits none and `companies` is unchanged, because the `weak: true` guard on `city`/`country` and the stricter `requires: context` guard on `state`/`region` were carried over intact.

- **BREAKING for hubs pinned to reference-models < 1.31.0: no `entity-projections.yaml` means no relationship candidates.** There is deliberately no built-in fallback vocabulary — a silent fallback is exactly what DD-188 forbids and would have made this change cosmetic. A pack that ships no such file (which `financial-services` does on purpose) produces no candidates, and `propose-alignment` says so in its run output rather than letting the absence look like a hub with no address columns. These candidates are advisory (`requires_human_confirmation: true`) and have never altered a disposition, so nothing downstream breaks; upgrade the pack to get them back.

- **Candidate shape.** The emitted candidate is now `type: entity_projection_candidate` (was `address_relationship_candidate`), gains `projection_id`, `target_class_uri` and `target_resolved`, and renames `address_parts` → `part_kinds`. A candidate whose `target_candidates` do not resolve in the domain's closure is still emitted with `target_resolved: false` and the reason in its rationale — never guessed at, never dropped.

- `_FINANCIAL_COLUMN_TOKENS` and `hasportof` in `_LOCATION_ROLE_PREFIXES` are the same class of debt with different call sites and are explicitly out of scope here; DD-188 records them.

## [5.8.0] — 2026-08-17

### Fixed
- **Tables the schema-catalogue screen excluded were still aligned (#528, alignment stage).** `_propose_alignments` enumerates its work from the affinity reports, which are written before anchoring and know nothing about the screen; it read `table-anchors.yaml` only for anchor overrides. So a table already judged not business data was aligned anyway and its columns entered the registry as claims about a reference class. This is the single-point fix — nothing excluded now reaches any alignment file, which makes the filters in the conflict detector and the report defence against stale artifacts rather than load-bearing.

  Measured on a live hub: `booking` 79 → 70 mapped columns, `consignment` 45 → 25 — exactly the 9 and 20 columns belonging to the two excluded sheets, with no over-removal. The DD-169 gate falls from **1,097 undecided columns to 922**, the full 175 that belonged to those two tables. No gate was weakened: those columns are simply no longer enumerated, because the table they belong to is no longer aligned.

### Added
- **`propose-alignment --no-schema-catalogue-screen`** — overrules the screen for a false positive, matching the flag `anchor-tables` already carries.
- **`excluded_tables` in each domain's alignment file** — the skipped table with the evidence string that excluded it, emitted only when non-empty so unaffected domains are byte-identical. An excluded table is reported in the progress output too: it must be auditable, not silently absent, so a false positive in the screen is questioned rather than invisible.

### Notes
- A domain left with no tables at all is dropped rather than written as an empty registry over a good one; if that empties every domain the run raises instead of reporting success over nothing.
- `build_decision_sheet`'s `gap_columns_in_excluded_tables` counter is now structurally zero on any hub re-aligned after this fix (measured 177 → 0). It stays meaningful for hubs whose alignment predates it, so it is left in place.

## [5.7.0] — 2026-08-17

### Added
- **`anchor-tables --no-schema-catalogue-screen`** — an escape hatch for the screen that routes a source's own schema-catalogue tables out before anchoring, plus help text covering the screen and the artifact keys it writes (`excluded`, `anchor_properties`, `anchor_column_overlap`, per-entry `warning`).
- **`load_excluded_tables()`** — reads the screen's verdicts back out of `table-anchors.yaml`. The `excluded` block was write-only: nothing in the codebase read it. It carries the evidence string per table, so a stage that honours an exclusion can say what it dropped and why.

### Fixed
- **Disposition conflicts included tables the anchoring screen had already excluded (#528).** A quarter of the conflicts on a live hub — 26 of 109 — were rows of two schema-catalogue sheets, i.e. columns of a table that lists another table's columns. Two stages cannot meaningfully disagree about those. `find_disposition_conflicts` now skips excluded tables (109 → 83, residual zero) and logs the suppressed count.
- **The CLI never surfaced withheld conflicts (#525).** `apply_auto_dispositions` has returned `withheld_conflicting` and `conflicts` since 5.6.0 and the handler printed neither, so on the live hub 83 contradicted columns were reported as silence. `--auto` now names the count, the block to open and the remediation, and separately calls out entries written by an earlier run before the cross-check existed — those are recorded today and are *not* withheld.

### Notes
- `build_decision_sheet` deliberately does **not** drop excluded tables. The DD-169 gate still counts those columns undecided, so removing them from the sheet would strand them with no bulk route to a decision, and the sheet is read as the complete worklist — a false positive in the screen should be questioned, not vanish. It reports `schema_catalogue_tables_excluded` and `gap_columns_in_excluded_tables` instead.
- Three stages still need this fix in files outside the change: `_propose_alignments` (the single-point fix — excluded tables are still aligned), `build_alignment_report`, and `undecided_gap_columns`, where it is largest at **175 of 1,097 undecided columns**.

## [5.6.0] — 2026-08-17

### Added
- **`draft-gap-decisions --accept-proposals`** — fills every empty `decision` in
  `gap-decisions.yaml` from its drafted proposal and applies it, recorded as `decided_by=autopilot`
  so it is never mistaken for a human decision. Intended for unblocking the DD-169 gate once the
  drafts have been read, not as a substitute for reading them.
- **`source_disposition.clear_dispositions()`** — withdraws recorded dispositions by table,
  disposition or decider, so a blanket deferral can be reversed once the tables behind it are
  anchored.

### Fixed
- **Value objects were crowded out of the alignment pool, producing false gaps (#517).** The
  candidate pool is a flat top-12 lexical shortlist over the domain, so a measurement class such as
  `imo/vessel-registry` `GrossTonnage` lost to eleven certificate classes and `grossTonnageValue`
  never reached the prompt. The model then correctly reported no matching property and the column
  was recorded as a gap for a term that already existed. The pool now expands two hops from the
  shortlist through object-property ranges into value objects and related entities, contributing
  only a subclass's own asserted properties, capped at 8 added classes per table (measured: 0–8,
  average 3.5).
- **The strict-schema property enum was flat, so a valid-but-wrong-class property passed validation
  (#520).** `(class, property)` was never checked as a pair. Every response is now validated
  against the offered pool: a pair that exists is kept, a property owned by exactly one offered
  class has its class repaired, and an ambiguous or unowned pair is rejected to the canonical
  unmatched form with the discarded pair recorded in the rationale. Enum members are additionally
  qualified as `Class.property` where the provider budget allows, degrading through bare names to a
  free string so nothing that previously fitted stops fitting.
- **Anchoring chose classes that could not carry a single column (#519).** Among duplicate class
  names, ownership was the only tier and ties fell through to catalog read order — so `bookings`
  and `shipments` anchored to `onerecord/cargo` classes with zero properties in closure instead of
  the `dcsa/booking` classes carrying 23 and 13. A 0.98-confidence anchor over 90 columns therefore
  produced no class at all. Ties within the ownership tier now break on column-to-property word
  overlap, and a propertyless anchor on a table with columns is reported.
- **The source's own schema-catalogue tables were anchored as business tables (#519).** A workbook
  listing tables and columns was fed to the model as four business tables. A screen now routes them
  to `not-business-data` before anchoring, on three decreasing-directness rules, recording the
  evidence for each exclusion rather than dropping anything silently. Measured on a live hub: 4 of
  75 tables flagged, no false positives — a seed table whose `TableName` column holds table names
  from a different system is correctly kept.
- **Auto-disposition silenced real business data (#521).** `operational` was derived from a bare
  substring match on the column name and converted straight to `not-business-data`, the one
  disposition that removes a column from the DD-169 gate rather than deferring it, with nothing
  checking it against what alignment had said about the same column. `apply_auto_dispositions` now
  withholds a candidate when the alignment output contradicts it and surfaces the conflict in the
  decision sheet, where `accept_proposals` cannot reach it. Measured on a live hub: 114 of 185
  auto-recorded columns are contradicted, including `stops.actual_start_timestamp` and
  `consignments.pickup_start_timestamp`. The underlying name predicate is tracked separately
  (#522).

## [5.5.0] — 2026-08-17

### Added
- **`kairos-ontology draft-gap-decisions`** — drafts the DD-169 gap-gate decisions instead of
  presenting a thousand-row column list (DD-186). `--auto` records only the two reason codes that
  were never judgment calls (`operational` audit columns, `vendor-slot` placeholders); the default
  drafts everything else into `gap-decisions.yaml` as one entry per **domain-scoped family** or
  single column name, with occurrence counts, tables and types; `--apply` fans one decision out to
  every column it covers. Measured on a live hub: 224 auto-recorded, and the remaining 1,286
  blocking columns reduced to 526 decisions (63 families + 463 names).
- **`draft-gap-decisions --suggest`** — one opt-in model call that names the concept each family
  represents and flags families whose members do not belong together. It fills `reasoning` and
  `proposed_disposition` only; `decision` is always the reviewer's, and `blueprint-gap` (which
  asserts a reference-model defect to file upstream) is never treated as the neutral default.

### Changed
- Gap grouping respects the domain boundary: `UnmappedColumn` carries its `domain`, so the same
  column name in two domains is two decisions — it can be a modelled fact in one and a genuine gap
  in the other. Families additionally require semantic coherence: structural prefixes (`is_`,
  `created_`, `total_`) never form a family, and members must be a qualified form of the shared
  token, not the bare entity.
- The `kairos-design-source` skill documents the new pipeline order, including that `anchor-tables`
  runs **before** `propose-alignment`.

### Fixed
- **`record_disposition` silently deleted previously recorded columns.** Its replace filter matched
  `(system, table)` and ignored the column, so each column-grain write removed the table's earlier
  column entries — a run recording 224 dispositions kept 37. The writer now matches the
  `(system, table, column)` grain that `load_dispositions` already keyed on.

## [5.4.0] — 2026-08-17

One arc: make the generated ontology match what the evidence supports, and make every
step that decides something be measurable, reproducible, and attributable. Every change
below was driven by a measured failure on a live client hub, and each is recorded as a
design decision (DD-163 … DD-185).

### Added
- **Global table anchoring** (`kairos-ontology anchor-tables`, DD-185): one model call
  anchors every source table against the full reference class catalog (ownership-marked,
  pattern-rule-guided), emitting `table-anchors.yaml` with anchor, confidence, derived
  domain, grain columns, natural key and load hint. `propose-alignment` consumes anchors
  through the uri-anchor-contract (status `anchored`, never `confirmed`), regroups tables
  into their anchor-derived domains, and states the decided anchor in the prompt.
  Affinity becomes a prior, not a constraint. Measured: 6/6 human-reviewed anchors, 9/9
  grain-column matches against a hand-crafted hub, 55/71 tables anchored on the full run,
  −40 low-confidence mappings / +15 high-confidence, 37% faster.
- **Strict alignment output schema** (DD-177): `column_alignments` keyed by column name
  with every key required — omitting, inventing or duplicating a column is a schema
  violation. Enum-constrained `ref_class`/`ref_property` under a measured 1,000-value
  provider budget; automatic JSON-mode fallback via `param_fallbacks`.
- **Graph-aware alignment** (DD-179): the prompt renders the table's apparent role
  structure (`shipper_*` / `consignee_*` groups) with the rule that distinct roles must
  not share an object property, and `flag_role_collisions` checks the finished mapping as
  a set (flags, never blocks).
- **Cross-domain bridge anchoring** (DD-181): classes reachable through blueprint-declared
  `cross_domain_relationships` join the anchor pool by default, tagged with their owning
  domain — no flag, the declaration is the authorisation.
- **Unanchored-table detection and gate** (DD-180): tables alignment cannot anchor are
  reported with the candidate class and the domain that already imports it, and `compile`
  gates on undecided ones before the column gate.
- **Alignment coverage report with reason codes** (DD-168) and a **hard gap gate before
  entity binding** (DD-169): every unmapped column carries one of a closed reason set;
  gap columns with real signal and no recorded decision block `compile`.
- **Conformance judgment offload** (DD-167) with retrieval grounding, coded guards,
  themed review (`discovery-conformance review`) and auditable human confirmation
  (`confirm`, the only path that clears `needs_confirmation`).
- **Hub-wide ontology integrity checks** (DD-163) and the **source disposition ledger**
  (DD-164), now also consumed at prompt time: column-grain `not-business-data` entries
  (including system-wide wildcards) are excluded from anchoring outlines.
- **Langfuse tracing** (DD-184, opt-in extra `langfuse`): every pipeline model call is a
  named, tagged, session-grouped generation with token usage; source sample values are
  masked by default and the strict schema is summarised to counts. Off unless all three
  `LANGFUSE_*` variables are set; can never fail a run.
- **Deterministic sampling** (DD-174): every stage passes `seed=resolve_ai_seed(role)`
  (`KAIROS_AI_{ROLE}_SEED` → `KAIROS_AI_SEED` → default) and per-role
  **reasoning effort** (DD-176, `resolve_reasoning_effort`). `temperature` was measured
  as rejected by the reasoning tier and had never taken effect.
- **AI provenance on generated artifacts** (DD-178): model, role, seed and effort in a
  comment header plus an AI-assistance disclaimer; Markdown reports lead with a one-line
  attribution. Deterministic generators never claim AI assistance.
- **Local-proposal validation** (DD-170), **glossary as a preflight input** (DD-171,
  now filtered per table to terms sharing tokens with its columns), and **class-anchoring
  suggestions** with live resolution (DD-165).

### Changed
- **Reference models resolve live; the materialized inventory is removed** (DD-173):
  `generate-inventory`/`check-inventory` and the freshness gate are gone with no
  compatibility shim. When the resolver was fixed, every cached inventory kept the old
  wrong answer — the fast path preferred the cache.
- **Prompts are reproducible** (DD-175): multi-valued RDF annotations are picked
  deterministically (`stable_value` in the canonical loader), reference terms and source
  tables/columns are ordered stably, and the per-table cache key includes the anchor.
- **`analyse-sources` resolves the hub's accelerator** (DD-183) instead of silently
  classifying against every ontology in the reference tree (274 pseudo-domains including
  FIBO and version strings); unresolved packs warn loudly on stderr.
- Per-table vocabulary files are a **projection of the aggregate** (DD-182), written by
  `split_vocabulary_by_table` — the two can no longer drift (a missed `formatHint` sync
  produced 75 catalog conflicts and blocked the pipeline).
- Sample values are budgeted by cardinality (DD-166) and wide tables split across calls
  at 200 columns with pinned anchors instead of silent truncation.

### Fixed
- `schema:domainIncludes` had **never matched a triple** — the constant bound
  `http://schema.org/` while every reference model binds `https` (DD-172; namespace
  guard test added). TradeParty gained its four address/contact properties.
- The Foundry provider path bypassed tracing instrumentation; the capability-aware
  completion wrapper now remembers per-model parameter rejections for the process and
  supports value fallbacks.
- Affinity/judgment stages called the client directly and would have hard-failed on
  reasoning models; all stages now route through `create_chat_completion` (guard test).
- Cross-domain bridge loading resolved the wrong accelerator pack when several are
  installed (alphabetically-first); now resolved via the shared DD-125 path.
- Duplicate class names across modules no longer derive table ownership from an
  arbitrary copy; ownership aggregates across every copy of the name.
- AI preflight treats a 404 from `models.list()` as "try a minimal inference call",
  and API-key auth goes directly to the OpenAI-compatible surface.

### Removed
- `core/inventory.py`, `generate-inventory`, `check-inventory` and their tests (DD-173).

## [5.3.0] — 2026-08-15

### Added
- **`kairos-ontology register-concept`** — hub-side registration of source-discovered concepts
  (#505 Layer B, DD-162). Of the three mechanisms #505 reported as blocking a domain from being
  modeled, two did not exist as described: the archetype tier `not_applicable` (Layer A) is not in
  the published tier enum at all (`VALID_TIERS = ("required", "recommended", "optional")` —
  ref-models #82 was closed for exactly that reason), and the `not-applicable` *outcome* (Layer C)
  is issue #507. The third is real and had no answer: **a business concept that exists in the source
  data but has no entry in the archetype catalog is invisible to the entire system.** Discovery only
  ever iterates the catalog, so such a concept cannot be judged, cannot carry a `likely_domains` tag,
  never reaches `design-landscape`, and never becomes an authored domain. On the CLdN hub roughly ten
  BI-relevant concepts sat in that hole (planning zones, tariff scales, empty-unit lifecycle,
  distance/toll matrix, order source attribution). DD-160 surfaced the *domain*-level version of this
  gap; this is the concept-level counterpart.
  Registrations are written to `integration/discovery/registered-concepts.yaml` and mirrored by
  `discovery-conformance build` into a **sibling** `registered_concepts` list in the conformance
  artifact — never merged into `core_concepts`, because `validate_artifact`'s coverage/identity
  checks require every entry there to be a real catalog concept and `concept_set_hash` staleness
  would fire on every registration. Registering a concept must not make the archetype look wrong.
  The reference-models archetype schema is **not** extended: registration is hub-side only, so the
  catalog stays a stable shared contract and one hub's extra concept never needs a cross-repo
  release. A URI already in the catalog is rejected — it belongs in `core_concepts` with a real
  discovery judgment. Registered concepts always carry tier `optional` (the source data argued them
  in; no blueprint recommended them) and are counted separately from the archetype scorecard so
  conformance percentages stay comparable across hubs.
  An `ai`/`autopilot` registration without a confidence, or flagged `needs_confirmation`, blocks
  `compile`/`validate` through the existing DD-148 gate — inventing a concept the blueprint omitted
  is a strictly larger authority than judging one it included. `--source-evidence` and `--rationale`
  are both mandatory. Surfaced downstream by `design-landscape` (via a synthetic class record —
  required, since the report's join skips any URI the activated accelerator modules do not declare,
  which is every registered concept by construction) and by `kairos-ontology next` as
  `model-registered-concept`, routed to kairos-design-domain. `next` proposal `schema_version` 5→6.
  The conformance artifact gains an optional `registered_concepts` key; absence is indistinguishable
  from empty, so no artifact already on disk is invalidated.
- **Discovery judgments are now source-evidence aware** (#507, Layer C of #505). During discovery an
  `optional`-tier concept with real source data behind it was routinely judged `not-applicable` — the
  one outcome `design_landscape` treats as the *opposite* of demand evidence. On the CLdN hub that
  deferred 20 optional-tier concepts, including a 289K-row cost-accounting table BI reports actively
  used. The rule the skill should follow is simple — **if data exists and the concept is optional,
  model it** — but nothing deterministic ever told the skill, or the human reviewing it, that data
  existed for a given concept. DD-160 (#496/#498) already joined source affinity to modeled/bound
  state, but at *domain* granularity; this is the concept-level half.
  New `core/conformance_evidence.py` joins two artifacts that already exist and are written at
  Stage 1, well before discovery at Stage 2 — `propose-alignment`'s per-table `ref_class` (direct,
  concept-level) and `analyse-sources`' per-table domain assignment (indirect, via a concept's
  `likely_domains`). No new LLM call, no new artifact, no new lifecycle ordering constraint.
  Surfaced in four places: `judgments-template` attaches a read-only `source_evidence` block naming
  the actual tables and pre-fills `outcome: conforms` for `optional`-tier concepts with evidence
  (required/recommended keep their sentinel — they are in scope regardless of what the sources
  contain); `build` **rejects** an `optional`-tier `not-applicable` that contradicts source evidence
  unless an explicit non-sentinel `rationale` is recorded; `validate` warns about the same thing but
  never fails; and `summarize` gains a `by_evidence` split (`blueprint` vs `data-driven`).
  The build/validate asymmetry is deliberate: `build` is new authoring, where overriding
  deterministic evidence should be an explained decision; `validate` also re-reads artifacts written
  long ago, where the same rule would be an unconvergeable gate on work already done (the CLdN hub
  alone carries 22 such judgments). **No artifact schema change** — `source_evidence` is
  template-only and `by_evidence` is recomputed live, deliberately *not* added to
  `compute_scorecard`, whose output `validate_artifact` compares for equality against the scorecard
  stored in the artifact (a new key there would fail every artifact already on disk).
  The `kairos-design-discovery` skill gains the missing rule the misapplication traced back to:
  `not-applicable` means **structurally incompatible**, never "I could not find a source table" —
  that is `partial`, which keeps the concept in scope for a later binding pass.
- **`kairos-ontology validate-dbt-contracts`** (#504). The toolkit generates Silver dbt models from the
  `CompilePlan`, but the *hand-authored* intermediate layer under `integration/transforms/dbt/models/`
  had no validation of its own: a `meta.kairos` block was only ever checked indirectly, once an
  `EntityBinding` referenced the model via `source.dbtModel` **and** `compile --check` ran for that
  binding's domain. The documented authoring flow is "author `stg_*` → author `int_merged__` → author
  properties YAML → return to the mapping skill → bind", and nothing existed to run between the third
  and fourth steps — a wrong `grain_key` surfaced only once a binding existed to contradict it,
  potentially much later. The new command is a **fully offline** lint (no dbt install, no adapter, no
  warehouse) over that tree: `meta.kairos` completeness, `grain_key` ⊆ declared output columns,
  `config.contract.enforced: true`, `target_class` resolving in the hub's ontology import closure,
  hub-wide `virtual_source_iri` uniqueness, and any unreplaced `<CONFIRM_...>` scaffold sentinel
  (reported by field name, pre-parse — every sentinel is *also* structurally invalid, so a post-parse
  check would only ever have said "your IRI is malformed"). Warnings that never block: a `stg_*` model
  declaring a `meta.kairos` block (a stage is internal to one transform, never a bindable virtual
  source), an `int_*` model lacking one, and a contracted model no binding selects yet.
  Deliberately a **sibling** of the existing `validate-dbt` rather than a mode on it — that command
  shells out to real dbt against the *emitted* project under `ontology-hub-publish/medallion/dbt` at
  Stage 5, and is gated to `kairos-execute-validate`; this one lints the authoring tree at Stage 4 and
  is gated to `kairos-develop-dbt-transformation`. Reuses `dbt_contracts.py`'s existing contract parser
  through a new non-raising `scan_dbt_contracts()`; `discover_dbt_contracts()` is now a fail-fast
  wrapper over it with its exact previous contract, so the bundle path is unchanged.

### Changed
- **`meta.kairos.target_class` is now required and cross-checked at compile time** (#503).
  `compiler/dbt_source.py` validated `grain`, `grain_key`, `virtual_source_iri` and
  `supported_adapters` but never read `target_class` at all — even though the contract declares it,
  `dbt_contracts.py`'s bundle-time parser requires it, and `scaffold-staging` writes it as a
  `<CONFIRM_TARGET_CLASS>` sentinel whose module docstring claimed "`compile --check` rejects the
  merged model's contract until confirmed". That claim was false for this one field: an unconfirmed
  sentinel sailed straight through. `resolve_dbt_model_source` now requires an absolute HTTP(S)
  `target_class` (existing `dbt-source.contract-invalid`), and a new `dbt-source.target-mismatch`
  rejects a contract whose `target_class` disagrees with the binding's *resolved* `target.class` IRI —
  the case where a model claims to produce `RevenueLine` while the binding maps its columns onto
  `InvoiceLine`, which previously compiled clean and only surfaced as wrong data. The comparison is
  invoked from `kernel.py` rather than `dbt_source.py` because it needs a `ResolutionContext`.
  **Behaviour change:** a hand-authored contract that omits `meta.kairos.target_class` now fails
  `compile --check`. Add the field (it is already documented as required by the
  kairos-develop-dbt-transformation skill), or run `validate-dbt-contracts` to find every such model
  at once.
- **Two contracted dbt models sharing one `virtual_source_iri` are now rejected** (#503). The IRI
  identifies one contracted model's output; only its *shape* was validated, so two models could claim
  the same identity and silently conflate two grains for every consumer keyed on it. A new
  `dbt-source.virtual-source-duplicate` blocks both participants (a pre-pass resolves every selected
  dbt-model binding up front, so the collision is not attributed solely to whichever binding the loop
  reached second). Necessarily **domain-scoped** — a per-domain compile never loads peer domains'
  bindings — so the message routes the author to `validate-dbt-contracts`, which owns the
  authoritative hub-wide check.
- **`domain-coverage --explain <domain>` and `--owns <ClassName>`** (#418, DD-157). The blueprint's
  per-domain `owns`/`does_not_own` boundaries were loaded by the toolkit and shown only inside an LLM
  prompt no design author ever sees — nothing in the design loop surfaced or checked ownership, so a
  misplaced class passed every gate. `--explain` prints a domain's OWNS / DOES NOT OWN text and its
  blueprint module imports; `--owns` reverse-looks-up which domain(s) own a class name through the
  materialized `referencemodels-unpacked/*-inventory.yaml` files (class → asserting module IRI → managed
  profile → activating domain list; no closure parsing, case-insensitive, plural ownership listed as
  such). Both are advisory and always exit 0: a hub without reference models gets a clean informational
  notice, an unknown domain gets the valid id list, and missing inventories point at `generate-inventory`.
  The kairos-design-domain skill's Gate 3 gains a confirmation step (not a gate — the boundaries are free
  text) running both before authoring. domain-coverage JSON `schema_version` 1→2 (optional
  `explain`/`owns` payloads).
- **Surplus managed-import warning** (#418, DD-157). Post-DD-155 the *missing*-import case is caught; the
  undetected residue was the surplus import — an author in the wrong domain adds the other domain's module
  import and satisfies every completeness check. `validate` (all modes) and the `init --domain` gate now
  emit a warning-level `surplus_managed_import` diagnostic for an authored direct `owl:imports` of a
  managed module the import plan does not require (surplus = authored direct imports ∩ managed-module IRIs
  − plan requirement IRIs), naming the module and the domain(s) the blueprint assigns it to. It never fires
  on required, cross-module-term-use, accepted-transitive, or init-added imports, and never blocks —
  warning severity flows through the existing validator/init-gate paths with zero validator edits.
- **`kairos-ontology next` observes untriaged BI concept-mapping worksheets** (#421, DD-157). On a real
  hub, `import-tmdl` had generated concept-mapping worksheets whose 24 tables were all still unfilled — two
  deterministic consumers existed (`design-landscape`'s advisory `bi_weight` and `draft-model-report`), but
  no skill text and no `next` action routed anyone to them. `next` now reports a hub-level
  `bi_concept_mappings` observation (total / unfilled `reference_model_match`) and derives an advisory
  `triage-concept-mapping` action routed to **kairos-design-source** (the import-tmdl lifecycle owner —
  kairos-design-domain must never fill the worksheet), status `human_decision_required`, exit 0 (DD-137).
  The unfilled count comes from one shared helper (`evidence_loaders.scan_concept_mapping_worksheets`) also
  used by `design-landscape`, so the two surfaces cannot diverge. Proposal `schema_version` 3→4.
- **kairos-design-domain skill routes BI demand evidence** (#421, DD-157). Authoritative input #5 no longer
  calls TMDL/PBIP "optional … supplied by the user": `integration/discovery/bi/` artifacts are written by
  `import-tmdl`, and reading the ones relevant to the active domain is required when present. Gate 2 states
  the concrete conditional (first pass reads the whole model — the worksheet `domain` field is typically
  unfilled), and step 4 sources the evidence matrix's "Downstream demand" column from the concept-mapping
  worksheet + Engineering Pack, naming both consumers. BI evidence remains demand, never business authority
  (DD-147 reaffirmed; the anti-pattern stays).
- **`source-privacy` now detects geographic coordinates in the persistence path** (#423, closing the
  deferral recorded in the DD-075 amendment). A column whose name carries a full-word `latitude`/
  `longitude`/`lng`/`coordinate(s)` token and whose value is a numeric literal with a textual fractional
  part inside the token's range (latitude [-90, 90]; longitude/lng [-180, 180]; coordinate or mixed tokens
  the union [-180, 180]) — or a single-column `"lat,lon"` comma pair — is persisted as an opaque
  `<redacted kind=location …>` token. Detection pairs name with value shape and never touches declared
  datatypes, so the #302 numeric/timestamp exemptions and the datatype-blind residual gate are unaffected;
  nested `{"latitude": …}` JSON values are covered. Deliberately still not checked (deferred to the
  sibling-address follow-on): `lat`/`lon`/`geo`-abbreviated column names (false-positive on
  latency/geo-score-class columns) and WKT geometries — the clean-result coverage message now states
  exactly this residual. Display and suggestion paths (`propose-alignment` examples, `suggest-shapes` PII
  classification) deliberately gain no location awareness. `SAMPLE_PRIVACY_VERSION` bumps to "2" as inert
  bookkeeping; **existing hubs keep previously persisted coordinates until `source-privacy --fix` is run
  once**.
- **`discovery-conformance judgments-template`** (#410). Phase 2.5 of `kairos-design-discovery` forbids
  hand-transcribing or hand-scripting the concept list, then required a `--judgments-file` whose schema had no
  scaffold and incomplete documentation — so every author had to write exactly the serializer the skill
  discourages, discovering the contract by failed `build`. Three requirements were undiscoverable: `label` was
  required, it had to *exactly* match the catalog label, and `confidence` had to be a float 0.0-1.0 rather than
  `high`/`medium`/`low` (a plausible mistake, since the unrelated extraction schema uses that scale for a
  different field). On a 174-concept archetype each cost a full author-generate-build cycle.
  The new command emits `build`'s exact input envelope with `uri`/`label`/`tier` pre-filled from the catalog and
  `<CONFIRM_…>` sentinels on the fields an author must actually decide, so an unedited template is caught by the
  content lint above rather than silently accepted. The `outcome` enum is loaded live from the reference models
  rather than hardcoded. Output follows `scaffold-mapping`'s convention: stdout without `--output`, and a refusal
  to clobber without `--overwrite`.
- **`label` and `tier` are now optional in a judgments file** and derived from the archetype catalog when absent
  (#410). Both were validated identically and both were derivable from data the command already held — a field
  that can only ever be correct one way adds no information, only failure modes, and it was the single largest
  source of hand-copying in a large file. A value that *is* supplied is still validated, so a genuinely wrong
  `label` or `tier` still fails.
- **`discovery-status` now reports duplicate documents and extraction `status`** (#417, #416). It already
  hashed each staged document for change detection but never compared digests *across* documents — on a real
  hub 7 of 56 tracked documents were byte-identical and were reported as 7 independent units of work.
  Duplicates are reported **additively**: a duplicate that has no extraction record still needs processing,
  so nothing is subtracted from the work count. Separately, `status: processed | partial | skipped` was
  documented in the extraction schema and read **nowhere** in the toolkit; on the same hub 23 of 56 records
  were legitimately `partial` (long documents where only decision-bearing sections were read) and the command
  printed one unqualified green line. It now prints the breakdown.
  New findings route into a **separate strict-eligible property**, deliberately not into the existing
  work signal: widening that would have made `--strict` unconvergeable on a hub with legitimately-partial
  records — the same pathology as #405 — and would have listed already-processed documents as needing work.
  - **`check-ai-config` command and AI provider preflight** (#459, DD-159). A new `kairos-ontology
    check-ai-config` command reports per-role AI provider status (`ok`/`not_configured`/`misconfigured`/
    `unreachable`/`unprobed`) with computed remediation, supporting `--format text|json`, `--role`, `--model`,
    `--probe`, `--strict`, and `--warn-only`. It never prints secret values (env var names only). The
    `require_ai_provider` raising wrapper is called at the entry of each LLM judgment loop
    (`propose-alignment`, `analyse-sources`) so a missing/misconfigured provider fails fast with a typed
    `AIProviderError` instead of silently falling through to a heuristic. `AIProviderError` subclasses
    `EnvironmentError`, so existing `except EnvironmentError`/`pytest.raises(EnvironmentError, match=...)`
    sites keep passing unchanged. `require_ai_provider` now returns the resolved provider config, eliminating
    the second `resolve_provider_config` call.
  - **`GenerationOutcome` constants moved to leaf module** (#459, DD-159).
    `OUTCOME_SEMANTIC_SUCCESS`/`OUTCOME_PROVIDER_FAILURE`/`OUTCOME_FALLBACK_ONLY` moved from
    `propose_alignment.py` to `core/generation_outcome.py` and re-exported. Values unchanged — no artifact
    change. Adds `OUTCOME_UNRESOLVED_ANSWER` for the "model answered but returned an unresolvable id" case.

  ### Changed
- **`suggest-shapes` emits `sh:in` enums only from full-table distinct evidence** (#424, DD-076 amendment).
  On a real hub, 82% of 217 generated `sh:in` enums were single-value and several provably wrong
  (`booking_status` → only `"TO_REQUEST"` of 5 real values): a distinctCount computed inside a capped
  profiling window was treated as population truth. `sh:in` now additionally requires the table to assert
  `kairos-bronze:distinctScope="table"` (the DD-156 evidence contract), a non-temporal/non-decimal/non-boolean/
  non-UUID datatype (integer status codes stay eligible; UUID is caught via `formatHint` or the sample pattern —
  SQL Server `uniqueidentifier` maps to `xsd:string`), and — when the true `rowCount` is known — at least
  100 rows. Sample-scoped evidence yields per-case advisory comments instead (saturated window / window below
  the 100-row floor / unsaturated "possible enum … not verified against full data"). **Behavior change for
  existing hubs**: legacy vocabularies (no `distinctScope`) produce a "regenerate the source vocabulary with
  import-source" advisory instead of enums until re-imported, and capped flatfile imports never produce `sh:in`
  — the drafts stop emitting exactly the weakly-evidenced enums the old rule fabricated.
- **`row_count` now means true table cardinality — one meaning per profiling field** (#422, DD-156).
  It previously meant full-table `COUNT(*)` on the warehouse path but capped-read *window size* on the
  flatfile path, so consumers thresholding on it treated 1,000-row windows as population truth. Schema YAML
  v1.2 splits the evidence: `row_count`/`kairos-bronze:rowCount` = true cardinality only, **omitted when
  unknown** (capped CSV/XLSX reads; the old `0` default is gone); new `rows_sampled`/`kairos-bronze:rowsSampled`
  = profiling-window size; new `kairos-bronze:distinctScope` (`table`/`sample`, omitted when there is no
  evidence either way) says whether distinct/sample evidence covers the full relation. Parquet now reports the
  true count for free from file metadata (also fixing a latent multi-row-group undercount). Legacy v1.0/1.1
  YAML is normalized on import by platform allowlist: only warehouse-emitted platforms keep `row_count`;
  flatfile/unknown/missing reinterpret it as `rows_sampled`. Enum suggestions now require exhaustive evidence,
  and cardinality-based FK matching is knowingly disabled on capped flatfiles (both advisory-only — the old
  behavior fabricated them from windows). **Migration is regeneration**: re-run `import-flatfile` +
  `import-source`; the three predicates are merge-managed, so a refreshed import updates them in place in
  existing vocabulary TTLs. `suggest-shapes` consumes this contract (#424, entry above).
- **`kairos-bronze.ttl` now declares every predicate `import-source` emits** (chore; groundwork for #422/#424).
  The importer emitted ten `kairos-bronze:` predicates that the scaffold vocabulary never declared —
  `rowCount`, `distinctCount`, `sampleValues`, `formatHint`, `suggestedEnum`, `enumValues`,
  `suggestedForeignKey`, `fkConfidence`, `jsonClassification`, `derivedFromJson` — so their meaning lived only
  in the emitting code. They are now declared with labels, comments, and domain/range; `rowCount` is pinned as
  the *true total row count of the source relation*, the meaning the upcoming #422 fix relies on.
  `owl:versionInfo` bumped to 1.1.0. Alongside, the CLI's `--sample-size`/`--max-rows` default literals in
  `import-flatfile` and `extract-schema` are now imported from their core modules instead of duplicated
  (identical values, zero behavior change).
- **`build-glossary` now excludes `status: skipped` extraction records** and reports how many it excluded.
  It read `extracted_terms` from every record regardless of status, so a skipped record's terms landed in the
  company glossary. This only became a *contradiction* once `status` became load-bearing (above), so it is
  fixed in the same change rather than left to be discovered later. `partial` records are still included —
  partial coverage is honest coverage.

### Fixed
- **Managed Import Completeness now runs in every `validate` mode and gates domain registration** (#426,
  DD-155). The check was accidentally gated on `--shacl`/`--consistency`, so Gate 5's inner-loop
  `validate --syntax` never ran it and `init --domain` performed no import check at all — a domain missing a
  blueprint-required managed `owl:imports` sailed through four green gates and was registered silently
  unactivated. Three changes: (1) `validate --syntax` now also reports Managed Import Completeness whenever
  reference models are resolvable (no-refmodels hubs keep byte-identical output; knowingly accepted:
  catalog/module infrastructure errors now fail `--syntax` on misconfigured refmodels-present hubs);
  (2) `init --domain` refuses to register a **pre-existing** import-incomplete domain — exit 1 with the
  diagnostics, before the catalog write and `_master.ttl` sync — and gains a `--degraded` flag mirroring
  `validate`'s as the only (explicit) bypass; freshly scaffolded starters are never gated. The gate's scoped
  single-domain check is a lower bound versus `validate --all`, which the kairos-design-domain skill now runs
  before registration; (3) the skill documents both behaviors in Gate 5 and step 9. **Release note:** hubs
  whose blueprint dual-assigns a domain (e.g. logistics `equipment` → both `mmt/equipment` and
  `dcsa/equipment`, referencemodels#64) now need both imports authored before that domain re-registers.
- **Inventory writes are content-addressed — `init --domain` no longer rewrites all 79 reference-model
  inventories on every run** (#419, DD-154). The envelope is a pure function of the source TTLs except
  `generated_at`, so every registration produced a 78-file diff in which only the timestamp changed — and the
  documented 3-glob `guard-scope --check-since` footprint hard-failed on every registration. `write_inventory`
  now compares the new YAML text against the existing file (newline-normalised, ignoring the `generated_at:`
  line) and skips the write when nothing else changed; any compare failure falls through to a plain write.
  Unchanged files still count as produced (DD-153) — `generate-inventory` reports them as
  `N generated, M unchanged, …` where "generated" counts actual writes, and an idempotent rerun of `init` or
  `generate-inventory` produces a zero-file diff. `generated_at` in a committed inventory now means "when the
  content last changed". **Release note:** run `generate-inventory` once after upgrading, before the next
  domain registration, so the expected one-time full rewrite (toolkit version bump + the #414 `generated_from`
  migration) lands outside a registration diff.
- **Decision Log source citations under `.import/` now resolve; binary evidence is now checked** (#420).
  `validate` warned "local source path does not resolve" for correct citations: the resolution base was the
  hub root (deliberate per #349 but documented nowhere), so `.import/` evidence — a repo-root *sibling* of the
  hub in nested layouts — could never resolve. On a nested hub (one inside a toolkit-managed repo root),
  citations whose first segment is `.import/` or `ontology-reference-models/` now also try the repo root;
  no other path does, so a rotted hub citation is never silently satisfied by the repo's own same-named file.
  Backslash citations (`.import\businessdiscovery\x.pdf`) are normalized before joining, and
  `.pdf`/`.docx`/`.xlsx`/`.pptx` citations are now recognized as local paths (all extensions
  case-insensitive) instead of being silently skipped. The base is now documented in `decision new --source`
  help, the decisions README, and the record template (DD-141 amendment). Accepted consequence: prose
  citations ending in `.pdf` now warn, same class as the existing `.md` behavior.
- **`source-privacy` reported an unqualified all-clear that named no patterns** (#415). It printed
  `✅ Source sample artifacts are privacy-safe for supported patterns.` — DD-075 always recorded that detection
  is bounded, but the bound lived in the design doc rather than the output, so a reader could not tell which
  patterns were covered. The case that surfaced it: three address components correctly redacted while
  `CoordinateLatitude`/`CoordinateLongitude` persisted at six decimal places (~0.1 m) in the same row, leaving
  the address recoverable by reverse-geocoding the two columns beside it. A clean result now reports the
  artifact count, the redaction kinds actually looked for, and the coordinate gap explicitly (#423).
  The kind list is **derived from the detectors** rather than maintained alongside them — a hand-written
  coverage list would eventually claim detection the code does not have, which is the same class of failure
  this fix exists to remove.
  **The detector is deferred to #423, not skipped**, because three separate mechanisms make the obvious
  implementations wrong: blanket-redacting decimals would regress #302 (whose exemption is value-shape, not
  datatype — datatype gating was explicitly rejected and a test forbids it); a range-only rule breaks existing
  fixtures, since `3.14159265358979` and `0.123456789` are both valid latitudes; and precision reduction cannot
  pass through `is_redaction_token`, the sole idempotence mechanism, without a 2-decimal threshold — roughly
  1.1 km, which still identifies a rural facility. A privacy gate has to be binary.
- **`import-flatfile` was hard to use in four specific ways** (#407). A missing optional extra produced one
  warning *per file* and then a multi-thousand-character aggregate repeating the same install hint — there is
  now a single preflight that keys on the extra being **importable**, not on the suffix, so a corrupt `.xlsx`
  is still tolerated when openpyxl is present. Directory mode is non-recursive and never said so, reporting
  `No … files found` for a nested tree, which reads as "wrong path" rather than "wrong shape"; it now says how
  many candidates are in subdirectories, and `--recursive` derives table names from the path relative to
  `--from` so nested same-basename files no longer collide. Legacy `.xls` raised an `InvalidFileException` that
  escaped the CLI's handler as an unhandled traceback in single-file mode; both dispatch sites now raise a
  clean "convert to .xlsx" error. `.xls` deliberately **stays** a recognised candidate — dropping it from the
  suffix set would have degraded directory mode from a named skip to `No … files found`.
  Item 3 of that issue (`row_count`) is **not** included: it turned out to be a semantic collision between the
  two import paths that drives enum detection, and is tracked separately as #422.
- **`generate-inventory --prune` deleted committed inventories** (#405, found while planning it — not in the
  issue). Prune is on by default and unlinked every `*-inventory.yaml` absent from the set the run wrote. Two
  paths made that set wrongly incomplete: a source that **failed** never entered it, so its previously-good
  committed inventory was deleted — the fix command destroying the evidence that the source had ever been fine;
  and, worse, only *one* of the ontology / reference-model roots need resolve, so a run scoped to the hub alone
  reported **zero failures** and deleted **every** reference-model inventory with no warning at all. Because of
  the second path, the obvious guard — "don't prune if anything failed" — would not have closed it. Prune now
  hard-skips with an explanation when either scope root was unresolved, and otherwise reuses the checker's own
  orphan notion, which is built from the sources it enumerated regardless of parse success; a source that merely
  fails is still *seen*, so it can never be mistaken for orphaned.
- **`generate-inventory` reported success while losing inventories** (#405, #408). It printed
  `✅ Generated N inventory file(s)` and exited 0 while sources failed to build and others were skipped by a
  filename collision — the collision printing `❌` in a command that then reported success. `written` was the only
  counter it kept, so the summary had no denominator. Outcomes are now tracked in a shared `CommandOutcome`
  (`core/command_outcome.py`) whose blocking rule is **intrinsic to the outcome**, not a per-command policy:
  no artifact produced for a requested target, or an explicitly-named target failing, or an escalation flag.
  A per-command `blocking`/`advisory` flag was rejected — it mis-classifies `import-flatfile`, which is
  legitimately both (partial reads exit 0, total failure exits 1). Recorded as **DD-153**, along with the
  exit-code convention the 76 hand-rolled `SystemExit` sites never had. A single unbuildable *vendored*
  reference-model source stays advisory, because a hub author cannot repair it.
- **`check-inventory` sent users into a loop it could not clear** (#405). A source whose closure failed to
  resolve was collapsed into `missing` or `stale` — both blocking, both indistinguishable from "you forgot to
  regenerate" — and the remediation named exactly one command, `generate-inventory`, which cannot fix an
  unparseable source. So `check-inventory` → `generate-inventory` → `check-inventory` never converged. A new
  `unbuildable` classification (non-blocking, `--strict`-eligible, mirroring `unverifiable`) now carries those
  sources and selects a remediation message naming the real remedy. See the DD-047 amendment for why weakening
  this gate is correct rather than convenient.
- **Two blueprint pattern templates collided on one inventory filename, leaving `template` permanently STALE**
  (#406). `blueprints/patterns/*/template.ttl` files fall outside the `derived-ontologies` tree that the DD-054
  naming rule namespaces on, so **every** pattern template collapses to `template-inventory.yaml` — the collision
  scales with the pattern library rather than being a two-file accident. Those files are copyable stubs with
  `https://example.org/` placeholder namespaces and deliberately no `owl:versionInfo`, so an inventory of one has
  no consumer; they are now excluded from enumeration in `iter_reference_inventory_sources`, so generator and
  checker agree by construction. DD-054 also claimed the generator "aborts loudly on any residual same-name
  collision" — it did not; it does now.
- **Trust artifacts accepted placeholder content and reported green** (#416). The artifacts an unattended run
  produces *as its evidence of work* had no content validation: an extraction record whose `strategy` and
  `summary` were literally `TODO` with `extracted_terms: []` passed `discovery-status --strict`, because only
  `source_path` and `source_sha256` were ever read; and an unedited decision-record template indexed as a
  normal **Accepted** record. The second is subtler than "no validation" — `_has_rejected_alternative` scans
  for a table row with non-separator cells, and the shipped template's own
  `| <option> | <why it was not chosen> |` satisfies exactly that, so the stub *passed an existing check*.
  Content linting is now shared in `core/hub_utils.py` (joining `is_authored_discovery_ttl` from #288, whose
  principle this generalises: scaffold-provided content is not authored evidence), and subsumes the
  `<CONFIRM_…>` sentinel family so that convention is enforced rather than incidental.
  **Severity is deliberately asymmetric.** Extraction findings and unedited `Proposed`/`Rejected` records
  **warn**; only `Accepted`/`Superseded` records with an unedited body **error**. An error-level lint would
  have turned `kairos-ontology validate` red on every hub with one in-progress record, because the
  decision-record validator's errors fold into `validate`'s exit code — and an unedited record is `Proposed`
  *by construction*, since that is `decision new`'s default. Accepting a record whose rejected-alternatives
  table is still a placeholder is the case that is unambiguously wrong.
  Also: `sync-index` and `decision list` computed validation diagnostics and then **discarded** them
  entirely, so even the checks that already existed were invisible. They are now surfaced.
- **`next` said "narrative" for a check that only accepts a glossary TTL** (#411). The predicate behind
  *"No authored businessdiscovery/ narrative found"* matches authored `.ttl` files only, so prose notes in
  that folder never counted — correct behaviour, since the DD-048 artifact is the SKOS glossary, but the
  message named a genre rather than the artifact. A user who had authored a substantial markdown business
  narrative was told none existed, and the only way to resolve the contradiction was to read the source. The
  strings now name `businessdiscovery/*.ttl` and add the parenthetical that saves the source dive. The
  predicate was renamed to match what it does, and one rationale that named `integration/discovery/` for a
  signal computed from `businessdiscovery/` was corrected. No behaviour change.
- **Inventories embedded an absolute machine-local path, so they were not portable** (#404).
  `generated_from` was `str(ttl_path)` — an absolute path from whichever machine ran
  `generate-inventory` — written into an artifact that is committed and reviewed. One real hub had all
  75 inventories carrying `C:\Git\<hub>\…` while the hub itself lived on `G:\`, so the recorded path
  did not resolve on the machine holding the file. It is now stored relative to the reference-models
  root (or hub root), with POSIX separators.
  The field cannot simply be blanked: it is re-read by `_canonical_filename_from_generated_from()` to
  derive the canonical inventory filename (DD-054). The relativisation is therefore anchored to **the
  same root passed to `inventory_filename`**, and the `derived-ontologies` marker fallback runs only
  when relativisation is impossible — never instead of it. Truncating at the marker looks equivalent
  and is not: with a root pointed at `…/ontology-reference-models/derived-ontologies` it derives
  `bsp-party-inventory.yaml` for a file actually named `party-inventory.yaml`, and that mismatch is
  swallowed as `stale`. `.as_posix()` is likewise load-bearing rather than cosmetic — a relative value
  containing backslashes fails to parse on Linux exactly as an absolute one does. Legacy absolute
  values still derive correctly, and freshness is unaffected because it compares `closure_hash` only.
- **Regenerating inventories rewrote every file even when nothing had changed** (#404). `generated_at`
  used `datetime.now()`, so all 75 files churned on every run and genuine inventory changes were hard
  to see in review. It now uses the existing `core/determinism.resolve_generated_at()`, honouring
  `KAIROS_GENERATED_AT` / `SOURCE_DATE_EPOCH`. Without this, the portability fix alone would not have
  removed the diff noise the issue was filed about.
- **The reference-models fetch never copied the upstream root `LICENSE`/`NOTICE`** (#413), so the
  aggregate third-party attribution — naming FIBO (MIT, © 2020 EDM Council) and IATA ONE Record
  (MIT, © 2025 IATA-Cargo) alongside the toolkit's own Apache-2.0 terms — never travelled with the
  ~409 vendored ontology files. The sparse checkout takes only the `ontology-reference-models/`
  subtree, and the fetcher already reached into the clone root for `VERSION`; it now copies all three,
  each independently guarded so an upstream lacking them cannot break the fetch. The per-family MIT
  licences already arrived, since they sit inside the copied subtree; it was the document explaining
  the set as a whole that did not.
- **The DD-103 agent boundary left most raw ontology exposed, and could be escaped by choice of
  working directory.** The scaffolded `.claude/settings.json` denied only `*.ttl`, but a fetched
  reference-model tree is **297 `.rdf` to 112 `.ttl`** — and the toolkit itself treats `.rdf` as a
  first-class serialisation (`core/validator.py` and `core/projector.py` both glob `**/*.rdf`
  alongside `**/*.ttl`). So the majority of raw ontology, all of FIBO, was never covered. The deny
  list now spans `.ttl`/`.rdf`/`.owl`, keeping `.json` and `.xml` deliberately readable: the tree
  carries 19 JSON *Schemas* the toolkit itself consumes and no JSON-LD ontologies, and
  `catalog-v001.xml` must be readable for domain registration.
  Two further problems were found while fixing it. A `./`-prefixed permission path anchors to the
  **current working directory**, not the project root — and this toolkit deliberately supports being
  run from inside `ontology-hub/` (DD-064), which voided the whole boundary from there. And `Grep(...)`
  rules may never have matched anything, since permission matching is documented against `Read`/`Edit`
  only. Both claims come from documentation that cannot be verified against the installed runtime, so
  rules are now emitted in **both** anchorings and **both** tool prefixes: the redundancy is
  deliberate fail-closed behaviour and should not be tidied away without measuring first.
- **Existing hubs never received boundary updates at all.** `.claude/settings.json` was created once
  and never revisited: it is absent from the managed-file map, and `update` only wrote it when missing
  — with the check wrapped so `update --check` (and therefore the `managed-check` workflow) could not
  even report drift. It cannot use the managed-marker mechanism, because that marker is an HTML
  comment and a settings file that fails validation is rejected *as a whole*, which would silently
  void every rule. `update` now recognises previously-shipped generations by SHA-256 and replaces only
  those, reports them in `--check`, and leaves a hand-extended file untouched with an advisory rather
  than destroying local edits.
- **A managed skill instructed the agent to read a file the boundary already blocked.**
  `kairos-design-domain` told it to open `model/ontologies/*.ttl` to recover the ontology IRI; it now
  uses `resolve-ontology`. The same prohibition was added to the five skills that sit next to ontology
  files, which — unlike the settings JSON — are managed and therefore reach existing hubs. The
  `copilot-instructions.md` boundary section no longer restates the deny globs inline (it went stale
  the moment they changed) and now states plainly that this is a guardrail, not a sandbox: shell tools
  still reach these files, and non-Claude agents are bound only by convention.
  - **`analyse-sources` never caches a failure and exits 1 on total provider failure** (#459, DD-159).
    Previously a failed table was cached with a fabricated `domain: ""` at `confidence: 0.0`, poisoning
    subsequent runs from cache as if the failure were a real result, and a total provider outage still
    exited 0. The cache write is now gated on `generation_outcome == SEMANTIC_SUCCESS`; failed tables
    persist with `domain: ""` + `confidence: null` + `generation_*` keys (emitted only on non-success
    so happy-path YAML stays byte-identical, `schema_version` stays 2). Staged writes + tally guard:
    `AffinityTotalFailureError` raised when every attempted table fails, caught in `cli/sources.py`
    as `⛔` + exit 1. Partial failure still exits 0 with a visible warning.
  - **`propose-alignment` prefights the AI provider and never silently falls through** (#459, DD-159).
    The old `except EnvironmentError` swallow at the top of `_propose_alignments` silently degraded to
    heuristic mode when the provider was misconfigured. Now `require_ai_provider(ROLE_ALIGNMENT, …)`
    is called before per-table fan-out — a missing/misconfigured provider raises `AIProviderError`
    (subclass of `EnvironmentError`) with a one-line remediation. The wrong flag name
    `--allow-fallback-registry` was corrected to `--allow-fallback-output` in error messages, docs,
    and tests.
  - **Boolean literal normalization in EntityBinding parser** (#448). `str(node["literal"])` converted
    YAML `true` → Python `True` → `"True"`, rejected by the normalizer which accepts only XSD canonical
    lowercase `{"true","false"}`. Now normalizes `bool` → `"true"/"false"` at the parse site. **Breaking:**
    `{literal: true, datatype: string}` emits `"true"` instead of `"True"`.
  - **`.import/` is now gitignored** (#453). The toolkit-created convention for raw client evidence was
    not in `gitignore.template`, so large imported files could be committed accidentally. Defence-in-
    depth: a `pre-push` hook checks for files over 1 MB.
  - **Autopilot transparency report: source coverage, conformance risk, and BLOCKED status**
    (#458). The autopilot transparency report now requires four new metrics: source coverage
    (bound / total relations, percentage), unbound tables over 1000 rows with a likely canonical
    target (row counts only — no fabricated "business value" score per DD-159), a conformance-risk
    list (unbound sources vs already-bound classes), and an explicit **BLOCKED** status when any
    LLM judgment step was skipped (a run that skipped an LLM step can never report "complete").
    The "rank by business value" suggestion from the issue was dropped — domain importance is not
    quantifiable by the toolkit and fabricating a score would violate DD-159.
  - **Cross-source FK scanner in scaffold-binding** (#457). `scaffold-binding` now scans the
    hub's existing bindings' identity columns for exact normalized name matches against FK-shaped
    columns (``*_id`` / ``*_fk`` / ``*_code``) in the table being scaffolded. Each match is reported
    as a tier-1 candidate (deterministic, zero LLM, zero false positives) in the binding header
    and `ScaffoldBindingResult.cross_source_fk_matches`. A "Zero-relationships flag"
    transparency-report bullet was also added: the autopilot report states the total count of
    `relationships:` blocks across all bindings; zero across N bindings means silver models
    cannot join — a signal, not a finding.
  - **Grain materialization audit in `--explain`** (#449, DD-159). `compile --explain` now
    classifies how each grain column is materialized in the silver output via a new additive
    `grain_mechanisms` field on `ExplainEntity`. Each grain column is labelled as
    `direct-field` (a `fields:` entry maps the source column directly), `technical-field`
    (a DD-139 `technicalFields:` entry carries it), `expression-only` (the source column
    appears only inside a multi-part expression and is not materialized standalone), or
    `absent` (no field or technical field references it). The classification is explain-only
    (no new diagnostics) and is also rendered in the text output as
    `grain: {column} via {mechanism} → {output}`.

  - **Partial-match sentinels in scaffold-binding** (#450). `scaffold-binding` now emits
    `<CONFIRM_PROPERTY:…>` sentinel entries for orphan columns (no property match and no
    technical field) even in partial-match relations — previously sentinels were only emitted
    when zero properties matched. The sentinel entries are merged into the `fields:` list
    before YAML serialization (not appended as raw text), keeping the binding structurally
    valid and making orphans visible at `compile --check` time as `safety.property-unresolved`
    until a human or `propose-alignment` maps them.

  - **Honest absent-evidence reporting in fit-report** (#451). When no evidence source is
    found (no binding, no `propose-alignment` output), `fit-report` no longer lists every
    universe property as "unpopulated" — that reads like a finding ("everything is empty")
    when the truth is "nothing was evaluated." The `unpopulated` list is now empty and the
    notes carry the absent-evidence explanation with a remediation path.

  - **Inverse class→candidate-source scan** (#452). New `inverse-scan` command answers the
    inverse of `fit-report`: given a class, which source tables across all source systems
    have columns whose names deterministically match the class's properties? Only the
    deterministic tier (exact column-name equality via the class-name-aware candidate ladder)
    is evaluated; the output explicitly labels what was NOT evaluated (LLM-assisted semantic
    matching, fuzzy name similarity, value-sample inference, cross-system relationship
    discovery) so a short candidate list is never mistaken for a completeness finding.

  ## [5.2.2] — 2026-08-14

### Added
- **`field-mapping-report`**: generates an Excel workbook (one worksheet per domain) listing
  every declared scalar `owl:DatatypeProperty` field with its ontology-authored description
  and IRI, cross-referenced against the EntityBindings that map a chosen `--source-system`
  (e.g. `tms`) onto it -- embedding the mapped source column and a real sample value
  when source vocabulary/sample data is available for it. Unmapped fields are shown with a
  blank source/sample rather than omitted, so coverage gaps stay visible instead of reading
  as complete. Reuses the compiler's own binding resolution (`resolve_scope`/`adapt_binding`,
  factored out of `silver_sample_audit.py`'s `load_binding_mappings` into a shared
  `resolve_v5_column_facts` with an optional `source_system` filter) and the canonical
  `load_ontology`/`SemanticIndex` loader (DD-103) for per-domain property enumeration, scoped
  to each domain file's own asserted properties (`provenance.import_depth == 0`) so imported
  properties from other domains don't leak into a domain's tab. A class also picks up
  properties from its ancestor classes ("inherited", tagged in a new `Origin` column
  alongside "direct") even when the ancestor is declared in a different, `owl:imports`-ed
  foundation/reference file -- via `SemanticIndex.class_properties`, computed under the
  `rdfs` profile (the default `asserted` profile skips subclass-transitivity entirely).
  Object properties (relationship joins) are out of scope for this version -- only
  `fields:`-declared scalar mappings are shown; a CASE/fallback expression's multiple source
  columns are still surfaced correctly via `expression_input_uris`, not just its
  (often-empty) top-level column. A field with no binding under the selected source system
  shows `NO-MAPPING-FOUND` in its "Source Field(s)" cell rather than a blank one
  indistinguishable from a mapped-but-unsampled field. Columns are ordered `Ontology Class
  (Label) | Ontology Field (Label) | Origin | Ontology Description | Range | Source
  Field(s) | Source Field Example | Ontology Reference IRI` -- `Range` is the property's
  compacted `rdfs:range` (e.g. `xsd:string`) -- with a styled header row (colored fill, bold
  white text, frozen, auto-filtered) and auto-sized/wrapped columns. Ships under the
  existing `flatfile` extra (`openpyxl`).
- **`field-mapping-report`**: a new "Core Concepts" worksheet, inserted right after the
  `Overview` cover sheet, briefly explains every blueprint pattern (`patterns/<id>`) the
  hub's own ontologies reference in a property's `rdfs:comment` -- pulling the title and a
  brief explanation straight from the pattern library's own `pattern.md` (its `## Problem`
  section's first paragraph), paired with one real example: the first (domain, class,
  property) in the hub that actually cites the pattern, not an invented illustration.
  Scans both datatype and object properties (`_collect_pattern_examples`), since the
  patterns most worth explaining here (`deferred-relationship`, `multimodal-order-leg`) are
  usually documented on the object property, not a scalar. The pattern library is located
  via `_discover_patterns_root`, checked both inside the hub
  (`<hub>/ontology-reference-models/blueprints/patterns`) and as a sibling of the hub root.
  Degrades gracefully -- an explanatory note in the report, no error -- when no ontology
  references a pattern, when the pattern library isn't checked out, or when a referenced
  pattern has no `pattern.md`; existing reports with no pattern references are unaffected
  (no new sheet).
- **`audit-column-coverage`**: advisory gate flagging source columns with real, populated
  sample data that no EntityBinding references anywhere -- not in `fields:`,
  `technicalFields:`, `identity`/`grain`/`relationships`/`quality`, or `load.incremental`
  (`sourceUpdatedAt`, `cdcOperation.column`, `mergeIdentity`, etc.) -- and source tables with
  zero bindings at all (issue #353). This is the closest v5 equivalent to v4's deleted Claim
  Registry column-omission gate (DD-077/DD-127/DD-128), recomputed fresh on every run rather
  than persisted, matching v5's stateless design (DD-133). An adversarial pre-implementation
  review found that a cardinality-ratio threshold is unreliable in both directions on real
  data (audit-trail timestamps can show low distinct/row ratios from batched edits, while
  genuine business timestamps often show high ones), so orphan columns are filtered by name
  instead, reusing and extending `propose-alignment`'s existing DD-077 operational/audit
  pattern lists (`_OPERATIONAL_PATTERNS`/`_AUDIT_AUTO_PATTERNS` in `core/propose_alignment.py`,
  now also matching `systemcreate`/`systemlastedit`) rather than a bespoke heuristic. Advisory
  by default, with `--fail-on any`. `SourceColumnSample` (`core/silver_sample_audit.py`) gained
  `distinct_count`/`nullable`/`row_count`, read from the bronze vocabulary's existing
  `kairos-bronze:distinctCount`/`nullable`/`rowCount` predicates.
- **`kairos-toolkit-dogfood` and `kairos-flow-autopilot` skills**: formalize two
  opposite-intent variants of running the full hub lifecycle end to end, distilled from two
  real client dogfood sessions plus prior art in issue #339. `kairos-toolkit-dogfood` is the
  adversarial, exploratory loop whose purpose is finding real toolkit gaps against a real
  hub's data -- the hub built along the way is instrumental, not the deliverable; success is
  measured by confirmed findings, not hub polish. `kairos-flow-autopilot` is the opposite
  intent -- fleet-managed, bounded-stage autonomous delivery of a real client hub, with a
  declared-up-front scope contract, escalation guardrails that extend rather than relax
  `kairos-design-mapping`'s existing DD-088 fleet-mode stop-conditions, a Decision Log
  treated as the primary deliverable (not a debugging aid), and a human-readable
  transparency report as the run's closing artifact. Both also document the previously
  unreferenced-by-any-skill `field-mapping-report` command (`kairos-execute-report` gained
  the same reference), since a prior dogfood session hand-built an equivalent report from
  scratch, in the wrong location, for lack of any skill pointing at the command that
  already existed.

### Fixed
- **`audit-silver-samples` (DD-089) read only the v4 `model/mappings/` SKOS surface, so on a v5
  hub it audited nothing and reported an unqualified `✅ ... (100% coverage)`** (#348). Root
  cause: `run_silver_sample_audit` obtained its mapped columns exclusively from
  `_parse_skos_mappings(mappings_dir)`; `integration/bindings/*.binding.yaml` (v5 EntityBindings)
  was never read, and `sample_coverage_ratio` special-cased a zero denominator to `1.0`, so
  `0 mapped columns` rendered as a green, unqualified pass. The audit now also resolves v5
  bindings via the compiler's own `resolve_scope`/`adapt_binding` (reusing the same
  binding-to-column-mapping resolution `compile` uses, not re-deriving it), joining back to
  persisted samples on `(table_uri, column_name)` since the compiler's per-relation column
  symbol is a synthesized identifier, not the real bronze `SourceColumn` URI. A column mapped on
  both surfaces at once (mid v4-to-v5 migration) is counted once. `sample_coverage_ratio` now
  returns `None`, not `1.0`, when nothing was mapped; the CLI prints an explicit
  `⚠ ... nothing was audited`, naming both authoring surfaces searched, instead of `✅`, and a new
  `no_mapping_surface_found` warning finding means `--fail-on warning` now catches an inert audit.
  A new `--bindings` option (default: `integration/bindings/`, auto-detected) mirrors `--mappings`.
- **The GDPR PII scan (`validate --gdpr`) matched keywords as bare local-name substrings, with no
  regard to datatype or source evidence** (#325). On a real four-domain hub this produced two false
  positives — `Address.addressCode` (a governed reference code, `xsd:string`) and
  `AddressRoleAssignment.isMainAddressRole` (`xsd:boolean`) both matched the `"address"` keyword —
  while missing the two classes a DPIA would actually care about (`party:Contact`/`party:StaffMember`,
  sourced from 158 real client columns including birthdate/passport/next-of-kin), because their
  canonical property names happened not to contain a keyword substring. `core/validator.py`'s
  `validate_gdpr` now suppresses a name-keyword hit when the property's declared `rdfs:range` is
  `xsd:boolean` (no keyword describes a plausible boolean fact) or when the local name ends in a bare
  `Code` segment and the matched keyword is `"address"` specifically (a postal address cannot be
  compressed into a short code, so `<X>AddressCode` is definitionally a lookup key, not content).
  Both gates are scoped narrowly on purpose, per the precedent in #302: `rdfs:range` is
  author-declared metadata, not the inferred/mutable `column_types` #302 explicitly rejected gating
  on, and neither gate touches numeric or temporal properties or any other keyword — a
  `dateOfBirth: xsd:dateTime` still gets flagged, and `nationalIdCode`/`genderCode`-shaped names stay
  detectable, since `core/_samples.py`'s own identifier-token logic already treats a `Code`/`Id`
  suffix on a person-context column as the sensitive content itself, not an exemption.
  Independently, `run_gdpr_validation` now resolves each domain's `integration/bindings/*.binding.yaml`
  against its source relation's columns (`integration/sources/**/*.ttl`, reusing the same tolerant
  `_binding_domain`/`_binding_source_ref`/`_binding_target_class`/`_source_relations` helpers
  `resolve_scope()` already uses for `compile`) and flags a bound class whose *source* columns carry a
  PII keyword even when its canonical property name does not — still fully respecting existing
  `kairos-ext:gdprSatelliteOf` protection. Added `"next_of_kin"` to the shared `PII_KEYWORDS` list
  (`core/_samples.py`, DD-075's single source of truth for both the validator and the sample-masking
  policy) to cover the third named evidence category. Also: the scan's warning count reached nobody —
  `validate` (running all checks) printed an unqualified `"✅ All validations passed!"` even with open
  GDPR warnings. `run_validation` now accepts the already-computed `gdpr_warnings` count and, when
  nonzero, prints `"✅ All validations passed (⚠️ N unprotected PII warning(s) ... remain open)"`
  instead. This is a deliberate, non-blocking choice: whether unprotected PII should fail the build is
  a separate product decision the issue explicitly declines to make unilaterally, and this fix keeps
  the scan advisory — matching the toolkit's other warning-tolerant checks (DD-089's
  `audit-silver-samples`, NK-coverage-warned-not-enforced) — while making sure the summary line never
  overclaims again.
- **`compile --explain`'s default text output showed nothing about relationships, and even
  `--format json` omitted the relationship's own property and its join columns** (#338, partial —
  narrowed from the full issue, see below). A reader inspecting the human-facing `--explain` output
  had no way to see which relationships an entity binding declares at all; `ExplainRelationship`
  carried only `target`/`mode`/`cardinality`/`temporal`, never the authored `property:` or `join:`
  columns, in either output form. `ExplainRelationship` now also carries `property` and `join` (each
  authored `local`/`foreign` pair flattened to `"<local>=<foreign>"`, matching the existing
  `ExplainQualityCheck.columns` convention), and `compile --explain`'s text renderer prints one line
  per relationship (`rel: <property> → <target> [<cardinality>, <mode>] on (<join>)`).
- **`_wire_relationships` had `continue` paths that dropped a relationship with no diagnostic** — the
  `silently-dropped-relationship` anti-pattern the pattern library names and
  `core/pattern_rules.py` records as enforced (#338, partial). Re-auditing against the current
  codebase (not the issue's original count, which predates #334/#335): `_wire_relationships` has 2
  syntactic `continue` statements covering 4 distinct drop conditions. Three of those are already
  detected and blocked, pre-wiring, by `_relationship_diagnostics` — added by #334/#335 — which
  rejects the whole binding with a proper diagnostic before it is ever admitted into
  `_wire_relationships`, making them defensive/unreachable via the normal `compile_domain` entry
  point today. The fourth is **not** fully unreachable: it fires for real when a relationship's
  target binding is later blocked for a reason unrelated to that relationship, because
  `_relationship_diagnostics` resolves the target binding from a pre-blocking snapshot of every
  *selected* binding, while `_wire_relationships` resolves it from the post-blocking valid set —
  the two views can disagree. In that case `compile`'s pass/fail outcome is still unchanged
  (`quality.py`'s independent, non-suppressible safety kernel already blocks the same scenario with
  its own `safety.relationship-endpoint`), so the effect is a redundant second diagnostic with the
  same code, not a new silent drop or a newly-failing hub; left un-deduplicated deliberately (see
  the `_wire_relationships` docstring). Every one of the 4 conditions now raises a diagnostic anyway
  (reusing `safety.source-unresolved`, `safety.relationship-endpoint`, or
  `safety.adapter-unsupported`, matching the codes `_relationship_diagnostics` already uses for the
  same conditions) instead of a bare `continue`, so a future change that weakens or bypasses the
  upstream gate on the other three cannot reopen a silent drop.
  **Out of scope, left for a follow-up decision:** the other four gaps #338 also reported — a
  class with only object properties is unbindable (`fields` requires `minItems: 1`), no
  one-to-many/many-to-many `EntityBinding` cardinality, no polymorphic (type-discriminated) joins,
  and no `technicalFields.purpose` value for a plain carried column — are real modelling-construct
  design decisions with product-facing scope and are **not** addressed here.
- **A cross-domain `ref()` naming a model absent from the assembled dbt project went undetected by
  every gate that runs by default** (#342). `compile --check` passes per-domain; `--emit` succeeds;
  only running real `dbt` against the fully assembled project ever surfaced the dangling reference —
  and nothing in the sanctioned per-domain authoring workflow invokes it. Root cause traced to a real
  case: `externalReference.name` is free text a binding author types by hand (DD-138/139 deliberately
  keep the compiler from searching peer-domain bindings to validate it, since `externalReference` must
  also support parents genuinely outside the hub, where no peer binding would ever exist to check
  against) — so a wrong value is never caught at the point it's written. `validate-dbt` now runs a
  structural dangling-`ref()` scan first, unconditionally, before shelling out to `dbt` at all: it
  text-scans the already-assembled project's emitted `.sql` files against the set of model files
  actually present, the same class of check `dbt_bundle.py` already runs for custom transform
  artifacts, applied here to the standard generated Silver models. A new `--structural-only` flag
  runs just that scan with no dbt install required, and the scaffolded CI release workflow now runs
  it as a mandatory step immediately after the per-domain emit loop finishes — not fused into each
  domain's own `--emit`, since that would false-positive on the toolkit's own documented
  single-domain incremental workflow whenever a domain with a legitimate external reference is
  emitted before its target domain has been (re-)emitted.
- **Generic-test arguments emitted in the pre-deprecation top-level form** (also #342). dbt has
  announced removal of unnested arguments on generic tests; the seven `kairos_runtime_*` /
  `kairos_temporal_fk_cardinality` tests emitted by the v5 Silver path (`projections/dbt/shape.py`)
  now nest their arguments under `arguments:`. Scoped to v5 only — the legacy v4 projector
  (`medallion_dbt_projector.py`) emits its own, separate generic test and is unaffected.

### Fixed
- **Two relationships from one binding to the same target class collided on the generated Silver
  FK column name** (#351). `_wire_relationships` (`core/compiler/kernel.py`) now qualifies the FK
  column/join alias with the relationship's own property name whenever a binding has more than one
  relationship to the same target (or `externalReference` system) -- the common single-relationship
  case keeps its existing `{target}_sk` name unchanged. Previously both relationships emitted an
  identically-named column, which the schema-YAML renderer silently collapsed while the raw
  `model.columns` tuple did not, tripping the Silver parity gate (`compiler.render-failed: ...
  schema YAML columns differ from spec`) -- or, worse, losing one relationship's materialization
  entirely if a hub worked around the collision by hand.
- **`decision new --decision-state Accepted` scaffolded a record its own validator immediately
  rejected**, with no CLI way to fix it short of hand-editing YAML frontmatter (#349). `decision
  new` now has a `--materiality` option (repeatable, `click.Choice` over `VALID_MATERIALITY`); an
  `Accepted` record with no `--materiality` fails fast at creation with a clear error naming the
  valid choices, instead of failing silently at the next `validate` run. Separately, a decision
  record's `sources[].resource` local paths now resolve against the hub root instead of
  `decisions/`'s own directory, matching every other path-citation convention a hub uses.
- **`scaffold-binding` proposed a system audit timestamp as a table's grain** (#346).
  `GB_SystemLastEditTimeUtc`-shaped columns (and the rest of the `SystemCreateTimeUtc` /
  `SystemLastEditTimeUtc` / `SystemCreateUser` / `SystemLastEditUser` family) are now excluded from
  grain candidacy, and a `<prefix>_PK`-shaped non-nullable column tied for the table-wide highest
  distinct count is now recognized and preferred ahead of the distinct-count proxy that used to
  pick the audit column on small samples. A remaining no-good-candidate case is now worded
  explicitly as a **guess**, not a NOTE that reads like a finding. Separately, `--out` pointing at
  an existing directory now raises a clean CLI error instead of crashing with a raw `PermissionError`
  traceback.
- **`validate` rendered warnings in the Markdown/JSON report but never the console** (#332), so a
  run with open warnings (e.g. a `property_range_owl_thing` latent-compile-failure warning) printed
  an unqualified `✅ All validations passed!` with no indication anything was open. Every section
  that can carry warnings now prints a `Warnings: N` count and the warnings themselves, and the
  final summary line is never unqualified while any section has one open. Exit code is unchanged --
  warnings still never fail the run; this is a console-visibility fix only.
- **`coverage-report` ignored `rdfs:subPropertyOf` when aligning properties**, while crediting the
  weaker `rdfs:seeAlso` signal for classes (#326). A hub with ten explicit `subPropertyOf` links to
  reference-model properties reported `Properties: 1/99 (1%)`, reading as a failed model when it
  wasn't. Property alignment now checks `subPropertyOf` first (a new `alignment: "subproperty"`,
  `confidence: 1.0` tier, resolved via the canonical `SemanticIndex`), crediting the single most
  explicit, formal alignment signal OWL offers for properties.
- **No field-vs-field duplicate-property or duplicate-output-column diagnostic** (#343).
  `_binding_safety_diagnostics` checked `technicalFields:` for duplicate source columns/output
  names but had no equivalent check over `fields:`; two entries resolving to the same property, or
  to different properties whose output columns collide, were accepted silently, and
  `semantic_outputs`'s `setdefault`-based construction quietly discarded the second entry instead
  of erroring. Two new errors: `field.duplicate-property` (same property mapped twice) and
  `field.output-collision` (different properties, same resulting output column name).
- **An expired approved deviation still authorized a Power BI capability degradation** (#319).
  `kairos-ext:Deviation.expiryDate` was parsed, type-checked and rendered, but never compared to a
  clock -- `_matching_deviation` (`core/projections/dbt/capabilities.py`) now takes an explicit
  `current_date`, resolved once via the existing `core/determinism.py::resolve_generated_at()`
  (never a direct wall-clock read, preserving this package's determinism guarantees), and skips a
  matched deviation whose `expiry_date` has passed so the underlying requirement blocks again, as
  if the deviation had never been written.
- **`discovery-conformance validate` gates accepted what they were built to reject** (#307, #308).
  The DD-148 unresolved-judgment gate was keyed on the artifact's own self-declared `mode` field
  (`mode: interactive` disabled it entirely, even with every concept `decided_by: ai` and
  unconfirmed) -- `open_questions()` now keys on each concept's own `decided_by`/
  `needs_confirmation`/`confidence`, in any mode. Separately, `validate_artifact` never compared
  the artifact to the archetype it claims to conform to: an artifact covering 1/48 concepts, or
  with a mismatched/tampered `archetype.id`/`catalog_hash`, validated clean. `validate_artifact`
  now optionally checks full coverage and per-concept identity against the resolved archetype
  catalog, reuses the existing `is_stale()` for hash verification, rejects `rename_to`/
  `deviation_reason` on an outcome that doesn't call for them, and type-checks `business_area`.
  (One further hole -- `topology_confirmations`/`cardinality_answers` shape validation -- needs a
  reference-models-side change and is tracked separately.)
- **The canonical `EntityBinding` example failed its own schema, and the DD-108 identity error
  message was both misleading and silently case-sensitive** (#337). `missingParent: null` parsed
  to Python `None` instead of the required string `"null"`, and `ambiguousParent: first` is
  schema-valid but always rejected by the adapter -- both now use values the schema and the
  adapter actually agree on. The DD-108 identity error said an authored naturalKey "must be
  explicitly materialized as mapped fields" (false -- `technicalFields:` is an accepted remedy
  too) and silently case-mismatched an authored `technicalFields` name against its
  already-lowercased output-column expectation with no mention of case; the comparison is now
  case-insensitive and the message names both valid remedies. Separately, `--target-class
  party:Branch` was rejected (only `:Branch` or a full IRI worked) because a domain ontology
  conventionally self-declares with the default/empty prefix rather than an alias for its own
  domain name; `fit_report.py`'s prefix resolution (shared by `scaffold-binding`/`fit-report`) now
  falls back to the root ontology's default namespace when the requested prefix matches nothing
  declared but equals the ontology's own file stem.
- **`property_missing_domain` had no escape for the reference models' deliberately
  domainless "reusable" properties** (#367). The reference models now ship object
  properties (`bsp/party#hasContact`/`#hasParty`/`#hasAddress`/etc.) whose domain is
  intentionally omitted -- asserting one would infer that domain's subsumption onto every
  hub class using the property, re-creating the subclass-identity-by-role anti-pattern by
  the back door -- marked with an `rdfs:comment` starting `REUSABLE — no rdfs:domain by
  design`. A hub author following this convention hit a hard, unfixable error. The check
  now stays fully silent (not a downgraded warning -- this is a permanent, intentional end
  state, unlike the transitional missing-range case) when that exact marker leads the
  property's comment.
- **The `deferred-relationship` pattern's prescribed shape changed upstream, and three
  toolkit surfaces still described the old one as prescribed** (#363). The pattern now
  wants a *marked stub class* as an eventual object property's `rdfs:range` (mint the
  target class now, mark its `rdfs:comment` `STUB (deferred-relationship):`), not an
  omitted range -- omission is merely *tolerated*. Reworded the validator's
  `property_missing_range` warning text, the DD-133 §7 design doc, and the
  `kairos-design-domain` skill's authoring guidance to match; the `owl:Thing`-is-worse-
  than-omitting guidance in all three was already correct and is unchanged.
- **The `temporal-quartet` pattern's synonym-ban anti-pattern (no `eta`/`etd`/`due`/etc.
  token in a temporal property name) was classified `not_enforceable`** because the
  banned-token list was open-ended and collided with real reference-model property names
  (#364). Upstream has since closed the list, added a formal per-name/per-IRI exemptions
  mechanism, and published exact tokenization/matching semantics -- both objections are
  resolved. `validate` now checks it (opt-in: only when a temporal-quartet `pattern.yaml`
  is resolvable via `--ref-models`/auto-detection, and only against the closed
  `banned_name_tokens`/`applies_to_ranges`/`exemptions` a *current* pattern.yaml actually
  publishes -- an older, pre-upgrade checkout with the prior open-ended shape degrades to
  zero findings, not a crash or a flood). New warning code
  `temporal_quartet_synonym_ban`; `RULE_REGISTRY`'s entry for this unit is now `enforced_by`
  and `MINIMUM_ENFORCED_UNITS` moves from 1 to 2.
- **A source vocabulary with no sample data read as "present," identical to a fully-sampled
  one** (#298). Nothing distinguished "sources present" from "sources present *with sample
  evidence*," so a hub could reach fully-authored bindings on schema names alone. New
  `SourceSampleStatus`/`SourceSampleObservation` observe per-table `kairos-bronze:
  sampleValues` coverage; `next` reports NONE/PARTIAL/FULL (with a `design-source` action
  when evidence is missing/partial), and `import-source` now warns per-table when no
  sibling `.samples.yaml` is found instead of silently producing a sample-free vocabulary.
- **`validate`/`discovery-status` reported success on an empty set** (#309). A hub with
  zero domain ontology files printed the identical `✅ All validations passed!` a hub with
  real, passing content would -- and `discovery-status` reported "up to date" when both
  discovery directories were empty (a vacuous comparison). Both now say "nothing to
  check"/"nothing was validated" instead, matching the existing `catalog-test` precedent:
  informational only, exit code unchanged.
- **`next` printed `discovery: missing` directly next to text saying the compile/validate
  gate IS satisfied** via a conformance artifact (#310). New `discovery_gate_satisfied()` is
  now the single source of truth for both the recommendation rationale and the rendered
  status line/JSON payload, so they can no longer disagree about the same hub state.
- **The `kairos-design-discovery` skill forbade one-off Python scripts, but its own step 4
  required calling `build_artifact()`/`write_artifact()` directly** (#311), since
  `discovery-conformance` exposed no way to build/write an artifact from the CLI. New
  `discovery-conformance build --archetype <id> --judgments-file <path>` subcommand wraps
  both calls and, by default, immediately validates its own output -- one CLI call instead
  of a hand-rolled script.
- **`guard-scope` couldn't detect writes into gitignored paths, and `validate` always wrote
  a report file with no opt-out** (#312). `guard-scope --snapshot` gains an opt-in,
  repeatable `--ignored-root <path>`, fingerprinting gitignored files via `git status
  --ignored=matching` the same way tracked ones already are -- the resolved roots are
  stored in the snapshot token itself, so `--check-since` never needs its own flag.
  `validate --report-format` gains a `none` choice.
- **`discovery-conformance load` emitted `discovery_doc` as an absolute, machine-local
  path** (#313), which could land in a *committed* `core-concepts-conformance.yaml` and
  produce spurious per-machine diffs. Now relativized to the reference-models root before
  emitting; `validate_artifact` rejects an absolute or backslash-containing value.
- **The reference-models contract test suite (8 tests, including the regression guard for a
  specific known `pattern.yaml`-loading defect class) has never run in CI** (#315), because
  CI never checked out `kairos-ontology-referencemodels` or set `KAIROS_REFMODELS_ROOT` --
  silently skipped on every run, invisible in a green build. CI now checks it out pinned to
  `v1.16.0` (never a floating branch); a missing checkout is now a hard failure specifically
  in CI (the local skip-when-absent behavior for contributors without a checkout is
  unchanged).
- **`check-inventory` blocked a hub straight out of `init`**, for a directory the scaffolder
  deliberately no longer creates, with no command ever surfacing the remedy (#321). `init`
  now pre-generates reference-model inventories after fetching reference models; a new
  `inventory_status` observation surfaces a blocking `generate-inventory` action in `next`
  when missing, and the `kairos-design-domain` skill's Gate 0 text now names the fix.
- **`validate` enforced every accelerator `data-domains.yaml` import as mandatory,
  ignoring the archetype's own `tier: required|recommended|optional`**, forcing hubs to
  import modules they could never use, with no way to record a justified exclusion (#324).
  `recommended`/`optional`-tier imports now emit a `"warning"`, not an `"error"`; the error
  message no longer substitutes the unhelpful `(configured module)` filler or leaks a raw
  internal module id.
- **`init --domain` mangled `catalog-v001.xml` and misreported an existing hub as freshly
  initialized** (#327, sub-findings 2-4 -- sub-finding 1 was already fixed by a prior
  commit). `sync_domain_catalog_entry` round-tripped the file through `ElementTree`,
  producing a 24-line diff for a 1-line change (dropped the prolog comment, stripped blank
  lines, changed the XML declaration's quote style, dropped the trailing newline, inserted
  the new `<uri>` in the wrong section). Rewritten as a pure textual edit that preserves the
  file's own line-ending convention exactly (CRLF or LF, whichever it already used) --
  fixes all of the above at once, no new dependency. `init` now also distinguishes a fresh
  scaffold from a domain added to an existing hub in its closing banner.
- **A pre-existing empty-string environment variable silently and permanently shadowed a
  hub's real `.env` credential** (#188), because `load_dotenv(..., override=False)` only
  checks key *presence*, not truthiness. Fixed generally (every var this loader handles is
  endpoint/key/model/version-shaped; none has a meaningful empty value): a stale empty key
  the loaded `.env` file itself defines is now cleared before `load_dotenv` runs, so the
  hub's real value can apply; a genuinely-set non-empty override is completely unaffected.
- **`next`'s inventory-status check ignored accelerator scoping, reporting a false
  `inventory: missing` on multi-accelerator hubs** (#386) even when the domain-relevant
  accelerator's inventories were fresh. `_inventory_status` now scopes the same way
  `check-inventory --domains` already does when a `--domain` filter is given, falling back
  to the prior unscoped behavior when it isn't.
- **`import-tmdl` failed with a raw `zipfile.BadZipFile` on a modern Fabric git-integration
  `.pbip` project** (#387), which is a small JSON pointer file referencing sibling
  `.Report`/`.SemanticModel` folders, not a zip archive. `.pbip` content is now sniffed
  before assuming zip; legacy zip-format `.pbip` files are unaffected, and a pointer file
  whose referenced folders are missing now raises a clear, actionable error instead.
- **`decision new` had no way to resync a stale `decisions/index.md`** after a record's
  `decision_state` was hand-edited post-creation (#388). New `decision sync-index` command
  regenerates the index from the records currently on disk.
- **`validate --syntax` hard-failed on any unresolved DD-148 discovery-conformance judgment
  anywhere in the hub, even one with no relevance to the domain being validated** (#389),
  contradicting the flag's own "syntax only" contract. Discovery-conformance judgments can
  now carry an optional `likely_domains` tag (#390); `check_discovery_gate`/`compile`/
  `validate --domain`/`discovery-conformance validate`/`build` all scope unresolved-judgment
  gating to the active domain (plus any judgment left cross-cutting, the default), while a
  plain `validate`/`compile` with no domain filter still gates on everything unchanged.
- **A "REUSABLE — no `rdfs:domain` by design" property shared across multiple classes was
  silently unbindable in any EntityBinding** (#391) — the compiler already supports
  `schema:domainIncludes` for exactly this case, but the domain-design skill never
  documented it. Gate 5 now names the required triple.
- **The EntityBinding relational-complexity trigger list never mentioned row-level
  filtering of a mixed-row-type source table** (#392), even though the binding schema has
  no `where`/filter construct at all. Both copies of the trigger list now name it, and
  `kairos-design-mapping`'s Gate 1 now requires checking for other Bronze sources that
  plausibly feed the same canonical class before authoring a single-source binding,
  routing to `int_merged__<entity>` from the start when one exists (#394) —
  `kairos-develop-dbt-transformation` now documents both reconciliation strategies
  (priority-based survivorship via the existing `kairos_survivor` macro, and
  attribute-level outer-join-with-presence-flags for complementary sources).
- **A domain could be fully authored, cataloged, bound, and validated yet never imported by
  `_master.ttl`, leaving it unreachable from the hub's single ontology entry point** (#393).
  `init --domain` now syncs `_master.ttl`'s `owl:imports` automatically (textual,
  marker-based editing -- never an rdflib round-trip, to preserve comments/formatting
  exactly as `sync_domain_catalog_entry` already does for the catalog); a new
  `domain-coverage` command reports blueprint-domain vs. modeled vs. bound vs.
  `_master.ttl`-imported status; `validate` now warns (non-blocking) when an authored
  domain isn't imported.

## [5.2.1rc4] — 2026-08-12

### Fixed
- **The domain-authoring skill made registering a domain impossible** (#322). This is the root cause of
  the "13 domains, 0 resolvable catalog entries" failure that motivated the dogfooding exercise.
  `core/catalog_test.py` states that only `init --domain` registers a domain; the
  `kairos-design-domain` skill mentioned that command **zero times**, its guard-scope step allowed a
  single path, and its anti-pattern list closed with "Writing any file outside the approved ontology
  patch". So following the skill correctly and registering a domain were mutually exclusive, and a
  compliant author produced exactly the broken hub. The skill now names `init --domain` as the
  registration step **at step 9, after the patch is applied** — the ordering is load-bearing, because
  the command scaffolds a starter `.ttl` when the file is absent — states that `--company-domain` is
  required and where to obtain it, states that the command is idempotent on an existing hub (its only
  change is the catalog entry, though its output reads like a re-run of setup), and widens the
  guard-scope allow-list to the three paths a domain legitimately touches.
  Deliberately **not** done, both rejected on evidence: auto-wiring `_master.ttl`'s `owl:imports`,
  which would re-implement DD-126 — decided, implemented, then silently deleted with its module and
  no superseding decision — to maintain a file whose imports nothing reads; and flipping
  `catalog-test` to a hard failure, which changes nothing because nothing invokes `catalog-test` (no
  skill, no toolkit workflow, no hub workflow).

### Added
- **The skill's own commands are now executed by a test rather than asserted as strings.** A test
  checking that `"init --domain"` appears in the file would pass the moment the string is typed and
  prove nothing about whether following the document works — which is the defect class that produced
  #322. The new tests **extract the command lines from `SKILL.md` itself**, substitute the
  placeholders, and run them through the CLI against a real hub layout, asserting the catalog gains a
  resolving entry; and they check the published `--allow` globs against the repo-root-relative paths
  `guard-scope` actually reports, so the #329 mismatch cannot silently return. Both fail against the
  pre-fix skill. A future re-word that breaks either instruction fails the build.

## [5.2.1rc3] — 2026-08-12

### Fixed
- **`scaffold-binding` matched zero columns on any prefixed-column source, then reported success over
  a binding that failed its own schema** (#336). Matching required exact equality after normalisation,
  so every column of a prefixed ERP schema missed: `GB_BranchName` normalises to `gbbranchname` while
  the property normalises to `branchname`. Measured against ground truth — 20 hand-authored bindings
  over a 156-property universe — that is **0% recall**, with all 20 relations matching nothing. It then
  wrote `fields: []`, printed a success banner, and the next command rejected the file.
  Matching now walks a three-rung ladder: the column as-is, the column with one detected prefix
  stripped, and the class name prefixed to the stripped remainder (`GB_Code` → `Code` → `BranchCode`
  → `:branchCode`). That third rung is the highest-yield one and keys off an *ontology-authoring*
  convention rather than a vendor quirk, so it generalises: **32.5% recall at 100% precision**,
  against 22% for prefix-stripping alone.
  Deliberately **not** done, each rejected on measured evidence: recursing the prefix strip (6
  within-table collisions on the real corpus, including three departure timestamps collapsing to one
  name, where the collapsed distinction between estimated, actual and scheduled *is* the semantics);
  deriving the prefix from the table name (53 of 70 tables fail, and an initials rule maps two
  different tables to one prefix while their real prefixes differ); and fuzzy or token-subset
  matching (62% precision, whose errors are the plausible kind a reviewer waves through — four
  distinct currency foreign keys all collapsing to one property).
- **The match universe is now restricted to datatype properties** (#314). There was no property-type
  filter, so an object-property name match landed in `fields:` — the #280 data-loss shape, which
  since that fix is a *blocking* diagnostic rather than a silent pass. Without the filter the
  improved matching above would have produced a success banner followed by a compile rejection, so
  the two had to land together. Object-property matches are **not** discarded: they are reported as
  detected relationship candidates and promoted to a DD-139 `purpose: relationship` technical field
  so the foreign-key value still reaches silver. They are the strongest FK signal available on a real
  ERP corpus — the DD-139 FK-name regex matches 13 of 3,087 columns there, and no source schema
  carries `is_primary_key` at all.
- **A zero-match relation no longer reports success.** It writes a commented, ready-to-uncomment
  skeleton to a `.draft` sibling the compiler never globs, and raises through the existing
  `ScaffoldBindingError` → `declined("scaffold-failed")` path, so the CLI exits non-zero with no
  success banner. A fully-commented `fields:` block cannot be written into the binding itself, since
  the schema requires that key with at least one entry — the draft keeps the author's starting point
  without emitting an invalid binding. This matters because 8 of the 20 real relations still match
  nothing even with the full ladder, and bare refusal would leave them with no artifact at all.
- **The match rate is reported against the target class's property universe**, not the column count.
  The old framing would read 7% where the truth is 50%: `party:Branch` declares 3 properties and its
  authored binding maps 2, so a 28-column denominator was never achievable. A `--column-prefix`
  override is added for the layer detection cannot reach — 147 of 434 doubly-prefixed columns carry a
  natural-key marker that is not a delimited segment.

## [5.2.1rc2] — 2026-08-12

### Fixed
- **A relationship could not join on a surrogate key, so most foreign keys were unauthorable** (#334).
  `join.foreign` resolved only against `fields:`, and a surrogate GUID primary key carries no business
  meaning so is never a mapped ontology property. On a real 70-table client hub only 3 of ~15
  evidenced foreign keys could be authored, and the `booking` domain compiled with **zero
  relationships** while carrying the raw foreign key as a column with no join beside it. This was not
  a design boundary: **DD-139 already declared that `join.local`/`join.foreign` resolve against
  authored technical fields "exactly as they do against `fields:`"**, status Accepted (implemented) —
  for `join.foreign` that was simply untrue, and the decision record is corrected here. There is no
  purpose filter, matching DD-139: the adapter materialises every technical field regardless of
  purpose, so all are valid join targets. The match is on the technical field's source expression and
  the value returned is its **output** name, because technical fields rename — a lookup returning the
  authored `join.foreign` verbatim would emit a column that does not exist under that name and
  survive only by case-insensitive SQL resolution.
- **A self-referential relationship emitted a dbt dependency cycle and a duplicate column.** With the
  above fix, four of the newly-authorable foreign keys were self-joins (parent and child are the same
  class, hence the same silver model). Those emitted `{{ ref('<model>') }}` *inside* that model, plus a
  generated foreign-key column equal to the model's own surrogate key — the existing collision guard
  only reserves the generated name when an `externalReference` is present. `render.py` logged a
  non-blocking warning about the self-reference and compiled anyway, so this shipped a broken dbt
  project with a log line. Now rejected with `relationship.self-reference-unsupported`.
- **`externalReference` naming the binding's own domain was silently accepted** (#335), bypassing the
  join validation entirely and emitting `ref()` to a model nothing checks exists — so either a
  dangling reference that fails at dbt parse, or a correct-looking but wholly unvalidated join plus a
  duplicate foreign-key column. It also switched off the in-scope-target check, which is
  `safety.relationship-endpoint` for `silently-dropped-relationship` — the single enforced normative
  pattern unit in the library. Now rejected with `relationship.external-reference-same-domain`, under
  its own code rather than the eight-site `safety.relationship-endpoint` so a test cannot pass while
  the check does nothing.
- **Two technical fields mapping one source column are no longer resolved silently.** That shape is
  legal — the uniqueness key is `(source column, purpose)` — so a join naming that column had two
  equally valid candidates. Now `technical-field.relationship-target-ambiguous`, raised only where a
  join actually resolves, so the legal duplicate itself stays valid.

Deliberately **not** implemented: validation that an `externalReference` domain resolves. The only
available mechanism is "a domain with bindings exists in this hub", which would break the deliberate
out-of-hub parent — the exact case `patterns/deferred-relationship` exists for, and which a real hub
documents.

## [5.2.1rc1] — 2026-08-12

Opens the post-GA fix line. No functional change; `__version__` is moved off the
released `5.2.0` so that subsequent fixes have a pre-release to accumulate in and
the GA tag stays immutable.

## [5.2.0] — 2026-08-12

First GA release of the 5.2 line. Every release since v5.0.2 had shipped as a pre-release, so the
`stable` channel — which `init` uses to pin a freshly scaffolded hub — still pointed at v5.0.2 and a
new client hub was pinned to a toolkit predating everything below. Promoting this line is what makes
`stable` mean the current toolkit again.

The rc sections below remain the detailed record. The headline changes in this line:

### Added
- **Structured, OpenTelemetry-ready logging and diagnostics** (DD-151, rc12) — `configure_logging()`
  at the CLI boundary, NDJSON or text formatters, secret redaction, per-invocation `operation_id`
  correlation, an optional `[otel]` OTLP bridge, and compiler trace points under `--debug`.
- **`list-patterns --coverage`** (rc21) — a total ledger mapping every normative unit in the pattern
  library to `enforced_by`, `not_enforceable` or `unrecognized_shape`. Against reference models
  v1.15.0 that is 43 units, 1 enforced. It gates nothing; it exists so the enforceable surface is
  auditable rather than assumed.
- **Per-environment Databricks connection config and a fabric-cicd `parameter.yml`** (rc20), plus a
  fail-closed `GoldContractError` when nothing is configured.

### Fixed
- **`import-flatfile` lost 66 of 70 tables to one timezone-aware column** and aborted a whole
  directory on any unreadable file (rc13). Directory mode is now partial-failure tolerant.
- **Unhandled exceptions produced zero structured records** (rc14) — the one failure mode the new
  observability layer could not see.
- **`import-tmdl` wrote outside the hub**, and expanding a PBIP archive would have committed raw
  report definitions and connection strings into it (rc15).
- **Source samples redacted timestamps and amounts as phone numbers** (rc17) — 1,229 false
  redactions on a real 70-table import, now 45, all deliberate.
- **An `owl:ObjectProperty` under `fields:` silently emitted the raw foreign key** as a business
  attribute, while the *correct* authoring was rejected (rc18). This is the
  `silently-dropped-relationship` anti-pattern the pattern library names, performed by the compiler.
- **One toolkit pin per hub, one pinning policy, and no silent downgrade** on `update --upgrade`
  (rc19).
- **`validate` rejected the deferred-range shape `compile` declares supported** (rc22), and
  `rdfs:range owl:Thing` — the workaround authors reached for — is now warned about, because it is
  the one form that breaks at compile time.
- **`guard-scope` reported false cleans, and the `--allow` globs published in the design skills could
  not match**, so the guard flagged the file the skill had just authored and the skill then told the
  agent to restore pre-patch content (rc23).

## [5.2.0rc24] — 2026-08-12

### Fixed
- **The #280 remediation message named a binding key that does not exist.** It told authors to
  declare the property "as a `relationships:` entry with an `on:` clause"; the schema requires
  `join`, and `additionalProperties` is false. Following the advice verbatim therefore failed —
  and failed opaquely, because `on` is a YAML 1.1 boolean, so the author got
  `Additional properties are not allowed (True was unexpected)`, which names no key at all. Found by
  authoring 20 real bindings against the message. The regression test now checks every `key:` the
  message names against the shipped schema rather than asserting the wording, since asserting the
  wording is what let the wrong key ship in the first place.

## [5.2.0rc23] — 2026-08-12

### Fixed
- **The `--allow` globs published in the design skills could not match the paths `guard-scope`
  reports, and the skill then told the agent to delete its own work** (#329). `git status --porcelain`
  emits repo-root-relative paths (`ontology-hub/model/ontologies/party.ttl`) while both design skills
  published hub-relative globs (`model/ontologies/<domain>.ttl`), so `fnmatch` never matched. On a
  clean tree the guard therefore flagged the file the skill had just authored, and
  `kairos-design-domain`'s own instructions say to **restore the pre-patch content** on a non-zero
  exit — destroying the domain. On a dirty tree the failure inverted into a false pass. Both skills
  now use a leading-`*` glob, which also works for a hub whose `model/` sits at the repo root, where
  an `ontology-hub/`-prefixed glob would fail in the opposite direction. The test fixture, which
  built its files at the **repo root** — a layout `init` never produces — is moved to the realistic
  `ontology-hub/…` shape, so the assertions now exercise the case hubs actually have.
- **`guard-scope --check-since` compared path sets, so an already-dirty file could change without
  limit and never be reported** (#323). It now records `(status_code, content_hash)` per path and
  compares the maps **symmetrically**. The two values are partially disjoint rather than ordered:
  `git add` on a dirty file changes ` M` → `M ` with an identical hash, invisible to a hash alone.
  The symmetric comparison closes the cases where a path *leaves* the status output — an already-dirty
  untracked file that is deleted, and a tracked file flipping ` M` → ` D`. The token also records
  `HEAD`, so a `git commit` inside the window — which empties the status output and previously
  reported clean — is now reported.
- **Non-ASCII paths were unmatchable and would have crashed a naive fix.** Porcelain v1 quotes and
  octal-escapes them; one real hub has 14 tracked paths containing an en dash, which no
  human-written glob could match and which `read_bytes()` would fail on. Snapshotting now uses `-z`
  output, with the parser rewritten for its NUL-delimited fields and its **reversed** rename encoding
  (rename fields arrive NUL-separated as new-then-old, the opposite order from the `old -> new` form). Paths resolve against `git rev-parse
  --show-toplevel` rather than the working directory, so the guard works when run from inside the hub.

### Changed
- **The snapshot token is versioned and fails closed.** Its format was uncontracted and unread by any
  test; a new token parsed by an older toolkit would have sliced hash-prefixed lines into garbage
  paths and could have produced a false **pass**. Unrecognised or legacy tokens are now a hard error.
- **`guard-scope`'s help states that gitignored paths are out of scope** (#312). The guard derives
  everything from `git status`, so writes into ignored trees — such as the `validation-report.json`
  that `validate` puts under `ontology-hub-publish/` — are invisible to it. A green result means less
  than it appeared to, and now says so.

This is a **fidelity fix, not a security control**: a `git commit` mid-window is a total bypass that
no hashing scheme closes, and the agent under observation is cooperative. The justification is
instrument validity — `guard-scope` is the detection mechanism for onboarding runs, and a false clean
silently invalidates the evidence they produce.

## [5.2.0rc22] — 2026-08-12

### Fixed
- **`validate` hard-errored on the exact shape `compile` declares supported.** DD-133 §7 states that a
  `relationships:` entry does not require the object property to declare a named `rdfs:range` — "it is
  exactly the shape the reference-model `deferred-relationship` pattern prescribes" — and the
  `binding.object-property-in-fields` row in the diagnostic catalogue restates it. But
  `validate_naming_conventions` raised `property_missing_range` as a blocking error for every
  property, so the two halves of the same package disagreed and the pattern could not be authored.
  Missing `rdfs:range` is now a **warning for object properties** and remains an **error for datatype
  properties**, where a scalar with no `xsd:` type is a genuine oversight. `property_missing_domain`
  is deliberately unchanged for both: an omitted domain is not the symmetric case — the property
  attaches to no class and becomes invisible to the compiler, `fit-report`, `coverage-report` and
  every dbt projector.

### Added
- **New `property_range_owl_thing` warning.** `rdfs:range owl:Thing` on an object property is *worse*
  than omitting the range, and nothing said so. Verified on the real compiler: an omitted range
  leaves `range_uri` empty so the relationship guard short-circuits and the binding compiles, while
  `owl:Thing` is a plain `URIRef` that can never equal the authored target, producing a hard
  `safety.relationship-endpoint` failure. So the workaround authors reach for when `validate` rejects
  a deferred range is the one form that breaks at compile time — silently, since `validate` passed it.
- **Warnings now render in the Markdown validation report.** `render_validation_markdown` keyed off
  `errors` and skipped any section without them, so every warning the validator produced — including
  the two above and the existing PII and import warnings — was written to `validation-report.json`
  and never shown. The summary table gains a `Warnings` column and the findings loop renders both
  kinds, errors first, with the DD-120 deterministic ordering preserved.

## [5.2.0rc21] — 2026-08-12

### Added
- **`list-patterns --coverage` — a total ledger of which normative pattern units the toolkit
  actually enforces.** The pattern library declares `normativity.naming: normative` with MUST rules
  and named anti-patterns, and until #280 nothing enforced any of it — but the real problem was that
  nothing *recorded* that fact, so `silently-dropped-relationship` sat unenforced in no list at all
  and nobody noticed. Every normative unit in the published library now maps to exactly one of
  `enforced_by <diagnostic code>`, `not_enforceable <reason>`, or `unrecognized_shape`. Against
  v1.15.0 that is **43 units across 5 patterns: 1 enforced, 42 not enforceable, 0 unrecognized**.
  The single enforced entry is `deferred-relationship/silently-dropped-relationship` →
  `safety.relationship-endpoint`, the check added for #280.
  The ledger gates nothing and cannot fail a build: no new `kairos.yaml` key, no
  `validation-report.json` section, and no change to any exit code. It exists so the enforceable
  surface is auditable before anyone argues about severity — the `not_enforceable` reasons are
  recorded per unit, including the ones that are not enforceable because a rule contradicts itself
  (referencemodels#39) or has no machine-readable denylist (referencemodels#40), and the ones a
  check would fire on documented practice for.
  Enumeration reads the **raw parsed pattern payload including keys the loader does not promote**,
  so a future reference-models release that adds a normative block under an unknown key lands in
  `unrecognized_shape` rather than vanishing from the denominator. A contract test asserts the
  ledger is total over the live library and that at least one unit is enforced, so an empty registry
  cannot pass silently.

## [5.2.0rc20] — 2026-08-12

### Fixed
- **Every Databricks gold projection emitted a semantic model that could not connect to anything**
  (#283). The Power BI partition carried literal `{{DATABRICKS_SERVER_HOSTNAME}}` and
  `{{DATABRICKS_HTTP_PATH}}` tokens, and **no substitution mechanism existed anywhere in the
  codebase** — those tokens appeared at exactly one site, with no reader, no config key and no
  templating pass over TMDL. Since the partition branch fires whenever the adapter is not Fabric,
  every Databricks gold run produced a dead artifact, silently. Fabric was never a working sibling
  to copy from: Direct Lake resolves its binding from the workspace it is deployed into and has no
  external connection to parameterise, so Databricks was structurally the only adapter needing one.

### Added
- **Per-environment Databricks connection config and a fabric-cicd `parameter.yml`** (#283). A new
  `gold.databricks_connection` block in `kairos.yaml` declares `server_hostname` / `http_path` per
  environment; the partition is emitted with the default environment's resolved values, and a
  `parameter.yml` with `find_replace` entries rewrites them per target environment at deploy time —
  matching the `environment=` argument the scaffolded deploy workflow already passed to
  `FabricWorkspace`, which was the half of the mechanism that existed. The released artifact is
  therefore deployable as emitted and still promotable across environments. Schema verified against
  fabric-cicd 1.3.0's own source and validator rather than from documentation alone; note its
  `find_replace` performs a literal substring replacement, so `find_value` must be a real value
  present in the file, not a placeholder.
- **Gold projection now fails closed on missing or malformed Databricks connection config**, raising
  `GoldContractError` with `gold.databricks-connection-missing` / `gold.databricks-connection-invalid`
  (rule `DD-113-connection`), matching how every other Gold precondition is enforced. Unknown keys,
  non-string values, values containing quoting or newline characters, and an ambiguous default
  environment are all rejected rather than partially applied.

## [5.2.0rc19] — 2026-08-12

### Fixed
- **The toolkit version was pinned in five places in a scaffolded hub, and the scaffolders,
  the channel and the drift warning all disagreed about it** (#297).
  - *One pin.* The wheel URL was repeated once in `[project.dependencies]` and once per extra, each
    embedding the version twice — five strings nothing kept in agreement, and the `otel` extra added
    in rc12 was never added to the template at all. Extras of the same distribution resolve through
    the single direct reference, so the four extras are now bare requirements and `{toolkit_version}`
    / `{toolkit_ref}` appear exactly once. Verified with `uv lock` and `uv sync --extra flatfile
    --extra otel` against a rendered template: one distinct URL in the lockfile, extras recorded with
    no URL, and both `openpyxl` and the OpenTelemetry packages installed alongside the pinned wheel.
    `update --test-ref`/`--restore` now skip url-less toolkit requirements instead of raising.
  - *One pinning policy.* `init` pinned whatever the `stable` channel resolved to while `new-repo`
    pinned the **running** toolkit's version — which, from a development build, is a release that does
    not exist and a wheel URL that 404s on the hub's first `uv sync`. Both scaffolders now share one
    policy: only ever pin a ref with a published release, never pin behind the running toolkit when a
    newer release exists, and write `[tool.kairos] channel` to match the chosen pin so the pin and the
    channel are a single truth. A hub scaffolded by a pre-release toolkit therefore follows `preview`,
    and returns to `stable` automatically once a GA release catches up.
  - *No silent downgrade.* `update --upgrade` rewrote the pin to whatever the channel resolved to with
    no comparison against the current pin. Because every release since v5.0.2 has shipped as a
    pre-release, a hub pinned to a current pre-release was **downgraded** to a toolkit predating the
    scaffold it was running. It now refuses to move the pin backwards without `--allow-downgrade`,
    comparing with `packaging.version` rather than strings. **This will block existing hubs** that pin
    a 5.x pre-release while declaring `channel = "stable"` — deliberately, since the alternative is the
    silent downgrade.
  - *Honest advice.* The version-mismatch warning always claimed a globally-installed toolkit and
    always advised `uv sync`, which is wrong when the running toolkit is **newer** than the pin: the
    user is not on a stale global install, and syncing would downgrade them. It now branches on
    direction and points at `update --upgrade`.
  - *`_read_hub_channel` read commented-out keys.* Its `re.search(..., re.DOTALL)` with a lazy `.*?`
    let `# channel = "preview"` win over the real key below it. Latent in shipped hubs, reachable in
    hand-edited ones, and it feeds the channel resolution the downgrade guard depends on.

## [5.2.0rc18] — 2026-08-12

### Fixed
- **An `owl:ObjectProperty` under `fields:` silently emitted the raw foreign key as a business
  attribute, and the compiler steered authors into doing it** (#280). For an object property whose
  `rdfs:range` is absent or a class expression — the shape the reference-model
  `deferred-relationship` pattern prescribes — authoring it *correctly* under `relationships:` was a
  hard error (`safety.relationship-endpoint`) while authoring it *wrongly* under `fields:` compiled
  clean. An author who hit the first and "fixed" it by moving the entry got a green build, losing
  the surrogate key, the join and the orphan-detection window; the model YAML recorded
  `silver_role: "business"` for an object property and the ERD dropped the relationship edge
  entirely. This is the `silently-dropped-relationship` anti-pattern the pattern library already
  names ("Data loss, not simplification — the relationship was observed in the source"), applied by
  the compiler below the author's line of sight.
  Both symptoms shared one cause: `_class_index_properties` fabricated `xsd:string` as the range
  whenever none resolved, which made an object property indistinguishable from a string property
  downstream *and* made the range comparison in `_relationship_diagnostics` fail. The fabrication is
  now conditional on the property being a datatype property, so a range-less object property is
  authorable under `relationships:`, and the `fields:` loop rejects object properties outright with
  a source-located `binding.object-property-in-fields` diagnostic naming both `relationships:` and
  the DD-139 `technicalFields:` escape hatch. The diagnostic is remapped onto the existing
  `safety.relationship-endpoint` family rather than extending the closed `SAFETY_RULE_CODES`
  catalogue. The legacy v4 RDF-authored path, where mapping an object property to a scalar FK
  passthrough is deliberate, is untouched. DD-133 §7 records the widened `relationships:` contract.

## [5.2.0rc17] — 2026-08-11

### Fixed
- **Source samples replaced timestamps and amounts with `<redacted kind=phone>`** (#302). On a real
  70-table parquet import, 1,194 cells were falsely redacted — 973 `datetime` and 221 `decimal` —
  leaving a sample corpus with no usable temporal or numeric evidence for `audit-silver-samples`
  (DD-089) or for modelling. Two shape bugs, both now fixed by whole-value exemptions in
  `core/_samples.py`. First, the ISO date-time exemption was tested against the *substring* matched
  by `_EMBEDDED_PHONE_RE`, whose character class excludes `:`; on `2026-07-29 14:19:00` that
  substring is `2026-07-29 14`, which can never fullmatch an anchored date-time pattern, so every
  space-separated timestamp — the only form the toolkit writes, since `str(datetime)` produces it —
  was classified as a phone number. The whole value is now tested first, while the per-match check
  is retained so a bare date inside prose still does not read as a phone number. Second, there was
  no numeric exemption at all, so `1234567.89` was a phone number and `0.123456789` an identifier;
  a bare decimal literal is now exempt when it has a fractional part or fewer than 9 integer
  digits — the digit bound keeps national registry numbers (BE INSZ, NL BSN, DK CPR), which arrive
  in `bigint` columns, detectable, and a leading zero disqualifies the exemption so bare phone
  numbers like `06123456` still classify. Both exemptions are applied in `value_is_pii_shaped` too,
  so the human-facing masking path agrees with the persistence path.
  The exemptions deliberately do **not** consult the declared column datatype: `column_types` is
  inferred from the very values it would protect on the CSV path and read from a mutable sibling
  YAML elsewhere, and gating on it leaked emails, phone numbers and IBANs out of free-text columns
  that merely begin with a timestamp. Column-*name* detection is likewise untouched, so a boolean
  named for a special category (`Religion_*`, `Has*HealthFlag`) still redacts. Real-data
  re-verification: false positives on those datatypes fell from 1,229 to 45, all 45 name-driven.
- **`infer_column_type` typed free text as `datetime`.** `_DATETIME_PATTERNS` was the only pattern
  in `core/import_flatfile.py` missing its `$` anchor (the `_DATE_PATTERNS` beside it all have
  one), so any column whose sampled values merely *began* with a timestamp — audit trails, comment
  logs, contact notes — was declared `datetime`. Anchored, and extended to accept seconds,
  fractional seconds and offsets so the common `2024-01-15 10:30:00` form still infers correctly.

## [5.2.0rc16] — 2026-08-11

### Fixed
- **`import-flatfile` persisted non-ASCII values as `\uXXXX` escapes, so the next command rewrote
  the file** (#303). Its three `yaml.dump` calls were the only YAML writers in the toolkit that
  omitted `allow_unicode=True`, and PyYAML defaults it to `False`. A job title containing an
  en-dash was written as `"Team Lead – EPC Operations"`; any non-Latin source data became
  fully unreadable. Worse, `import-source` rewrites the same `.samples.yaml` files *with*
  `allow_unicode=True`, so a step that should be a pure read of those files produced a one-line
  diff in each affected one — review noise that masks real changes, and the reason this was caught
  by change-detection around the step rather than by reading the output. All three writers now
  match the other 14 YAML writers in the codebase, and a regression test asserts the persisted
  bytes round-trip byte-identically through the rewriter.

## [5.2.0rc15] — 2026-08-11

### Fixed
- **`import-tmdl` wrote outside the hub, and expanded PBIP archives into it** (#296). `--output`
  defaulted to the cwd-relative literal `integration/discovery/bi`, so running the command from
  the repository root — the natural place, since raw Power BI exports are kept there — created a
  stray top-level `integration/discovery/bi/` tree *outside* `ontology-hub/`, while the scaffolded
  destination inside the hub stayed empty. The readers disagreed with the writer: `design-landscape`
  and `draft-model-report` both resolve that path from the hub root, so nothing ever found the
  output. The default is now resolved against the hub root (DD-147 amended), an explicit `--output`
  is still honoured verbatim, and the resolved destination is echoed *before* anything is written —
  the defect was invisible precisely because the command only reported paths after the fact.
  Relatedly, a PBIP ZIP was expanded with `extractall` **into the output directory**: correcting the
  destination alone would have committed raw report definitions, `.pbi/localSettings.json`, and M
  expressions carrying server names into the hub, contradicting that folder's own README ("Never
  commit credentials, connection strings, raw personal data, or proprietary report content"), and
  in-place extraction accumulated stale members across re-runs because `extractall` never prunes.
  Archives now expand in a temporary directory and only the engineering pack and concept mapping
  enter the hub.
- **Commands run from inside the hub wrote to a doubly-nested path.** `find_hub_root` inspects only
  `cwd` and `cwd/ontology-hub`, so running an import from `ontology-hub/integration/` resolved the
  output relative to the cwd and produced `integration/integration/discovery/bi` — the DD-064
  nesting symptom, this time inside the hub where nothing gitignores it. Hub-relative output
  resolution now also searches ancestor directories (requiring `model/ontologies/`, so a bare
  `ontology-hub/` directory name several levels up cannot silently redirect writes). The three
  verbatim copies of hub-detect + warn + relative-fallback in `import_flatfile`, `import_source`
  and `import_tmdl` are unified into one `hub_utils.resolve_hub_output_dir()`, following the same
  de-duplication that #288 and #289 forced on this module.

## [5.2.0rc14] — 2026-08-11

### Fixed
- **An unhandled exception produced zero structured log records (#295, DD-151).** rc12 added
  structured logging, but a crash that escaped a command body was the one failure mode it did not
  observe: Click's `standalone_mode` rendered a traceback to stderr and exited, so `--log-file`
  ended with the last successful phase and no failure record at all — exactly the case a
  skill-assisted diagnosis or a bug report needs most. The root group is now a `_KairosGroup`
  whose `invoke()` logs one `kairos.cli.command.failed` record — `exception.type`,
  `exception.message`, `exception.stacktrace`, and the run's `kairos.operation.id` — then
  re-raises, so Click still owns every exit code and all stderr rendering. `click.exceptions.Exit`,
  `click.Abort`, `click.ClickException` (with `UsageError`), `KeyboardInterrupt`, and `SystemExit`
  are exempt: they are the deliberate exit and user-error channels, and in click 8.4.1
  `Exit.__mro__` runs through `RuntimeError`, so a bare `except Exception` would have logged every
  subcommand's `--help` as a command failure. The stacktrace is built as a string and passed as a
  normal `extra`, never via `exc_info=` — `RedactionFilter` skips `exc_info`/`exc_text`, so an
  `exc_info`-bound traceback would have written an unredacted traceback, passwords included, to
  both console and `--log-file`. Because Click runs `@result_callback` only on success, the
  boundary also performs the observability teardown (`reset_operation_context`, `flush_otel`,
  `reset_logging`), which is what flushes and closes the `--log-file` handler on the failure path.
  Root option parsing and command resolution remain outside the boundary — they run before
  `configure_logging` — and `docs/guide/OBSERVABILITY.md` documents that limitation, the record shape,
  and that the persisted stacktrace is redacted and therefore lossy.

## [5.2.0rc13] — 2026-08-11

### Fixed
- **`import-flatfile` lost 66 of 70 tables to one timezone-aware column, and aborted the whole
  directory on any unreadable file** (#293). Two defects compounded. First, `read_parquet_table`
  materialised sample values with `to_pylist()`, which resolves a named-zone
  `timestamp[us, tz=America/New_York]` column through `zoneinfo` and raises
  `ZoneInfoNotFoundError` wherever no tz database is installed — stock Windows, and any slim
  container. Second, the directory loop had no per-file error handling, so that single raise
  aborted the entire import and wrote nothing: a 70-table client export produced zero output
  (only the four tables whose tz-aware columns were entirely null survived, because an all-null
  column never constructs a `TimestampScalar`). tz-aware columns are now materialised via
  `_arrow_column_to_pylist()`, which normalises to UTC and renders RFC-3339 with an explicit
  `+00:00` offset — no tz database needed, the offset is never silently dropped, and the value
  still matches the datetime exemption in the PII detectors (`core/_samples.py`), so timestamps
  are not mistaken for sensitive values and redacted. tz-naive columns are unchanged and stay
  offset-free. Directory mode is now partial-failure tolerant: each file is read independently,
  unreadable files are skipped and reported as `M of K file(s) could not be read — skipped:` with
  the exception type per file, and the run exits 0 having written every readable table. Zero
  readable files remains a hard failure — exit 1, nothing written — and a path pointing directly
  at a single file still fails fast. `pyarrow` is a core dependency, so this needed no new extra
  and no `tzdata`.

## [5.2.0rc12] — 2026-08-11

### Added
- **Structured, OpenTelemetry-ready logging and diagnostics (DD-151).** The toolkit had no
  central logging configuration, so unhappy flows in offline dbt validation, projections, and
  the compiler surfaced only through return codes or `CompileDiagnostic` — no debug/warning trail
  for skill-assisted self-healing or bug tracing. A new `core/observability/` subpackage provides
  central `configure_logging()` at the CLI boundary with `--verbose`/`--debug`/`--log-file`/
  `--log-format` flags, NDJSON or text formatters, redaction of secrets/tokens/connection
  strings, and per-invocation `operation_id` correlation (also surfaced in `compile --format
  json`). Offline dbt validation phases and the silver-projector Mermaid render emit stable
  `kairos.dbt.*` / `kairos.projection.*` events with retryable classification. The compiler
  keeps `CompileDiagnostic` as its stable contract and adds targeted `logger.debug` trace points
  (scope resolution, binding selection, emit plan/commit/recovery) visible only under `--debug`.
  An optional `[otel]` extra wires a `LoggingHandler` OTLP bridge — off by default, telemetry
  failure never fails compilation. See `docs/guide/OBSERVABILITY.md`.
- **Gold Power BI output is now a complete PBIP project** (#206). The projector emitted only the
  inner `{Domain}.SemanticModel/` TMDL, so Fabric git-integration worked but Power BI Desktop
  could not open the result — Desktop opens a *report*, not a semantic model. It now also emits
  the top-level `{Domain}.pbip` (artifacts pointer), plus a `{Domain}.Report/` sibling carrying
  `.platform` (`type: Report`), `definition.pbir` binding the report to `../{Domain}.SemanticModel`
  by relative path, and a minimal single-blank-page PBIR definition. Kairos generates the model,
  not the visuals; the blank report exists only so the project opens with an empty canvas already
  bound to the generated model. Page name is content-derived, so re-projection stays byte-identical.
  **Desktop-opening is not verifiable in CI** — tests assert the wrapper's structure and that both
  relative references resolve to emitted folders; the round-trip needs one manual open per format
  change.
- **Cross-repo contract tests** at `tests/test_refmodels_contract.py`, running the pattern and
  archetype loaders against a **real** `kairos-ontology-referencemodels` checkout rather than the
  synthetic fixtures every other loader test uses. Fixtures prove the loaders behave correctly
  given well-formed input; they cannot prove that what the reference models actually publish *is*
  well-formed. Reference-models `temporal-quartet/pattern.yaml` shipped unparseable in their
  v1.13.0 and stayed broken for two minor versions — nothing here misbehaved (`load_patterns`
  warned, `list-patterns` printed it) but no test in either repo ever pointed a loader at a real
  checkout, so the library's only *normative* naming pattern was absent from the
  `kairos-design-domain` flow while both CIs stayed green. Skipped when no checkout is present,
  so CI here gains no cross-repo dependency; set `KAIROS_REFMODELS_ROOT` or keep a sibling
  checkout. A mirror ships in the reference-models repo as `tests/test_toolkit_contract.py`.
- The suite asserts the published `archetype.schema.json` `$defs/tier` enum **resolves**, and that
  the offline `VALID_TIERS` fallback never lists a tier the published enum has *dropped*. (An
  earlier form of this entry asserted strict equality; that became a false alarm once the enum is
  resolved at runtime — see below.)
- `load_valid_tiers()` resolves the conformance-tier enum from the checkout's published
  `archetype.schema.json`, with `VALID_TIERS` as an offline fallback, mirroring the existing
  `load_outcome_codes` precedent. Reference-models owns that enum, so the proposed
  `not_applicable` tier — letting a catalog say "this concept is deliberately out of scope for
  this archetype" — now needs no toolkit release. **This closes a forward-compat break:**
  `validate_artifact` hard-rejected any tier outside the hardcoded tuple, so the first discovery
  run against a catalog using a new tier produced an artifact this toolkit called invalid.
- A contract test pins `design_landscape`'s hardcoded `CONFIRMED_DISCOVERY_OUTCOMES` /
  `NON_EVIDENCE_DISCOVERY_OUTCOMES` against the published `outcome-codes.yaml`.
  `load_outcome_codes` deliberately never hardcodes the *list*, but the *semantics* built on it
  were literals with no test — a published rename would have left them silently matching nothing
  (a class quietly losing its confirmed-demand evidence) with green CI.
- `ontology_tier` (`blueprint` / `derived` / `authoritative` / `unknown`) per module in
  `discovery-conformance load`, derived from the path the catalog resolves each module to. This is
  what lets a consumer distinguish "subclassing a blueprint class is expected" from "subclassing a
  derived, mode-bound class outside its own mode is the error to flag". Deliberately a **separate
  key** from `tier`, which in that same dict already means the archetype's *conformance*
  obligation level.
- `grain_collisions` is now a first-class `Pattern` field (all five published patterns ship it),
  carrying the do-not-subclass / do-not-merge boundaries.

### Removed
- **Dead code cleanup.** Removed verified-unreachable functions, methods, and classes with no
  callers in `src/` or `tests/`: `read_provenance_version`, `running_toolkit_version`
  (`_provenance`), `validate_catalog`, `is_mapped`, `get_all_mappings` (`catalog_utils`),
  `load_validated_artifact` (`conformance_artifact`), `generated_at_slug` (`determinism`),
  `remove_property` (`ontology_ops`), `CompileDiagnostics.with_added` (`compiler/result`),
  `_one` (`dbt/bind`), `scalar` (`dbt/builders`), `supports_preparation_feature`,
  `physical_source_type` (`dbt/capabilities`), `_safe_identifier` (`dbt/policy_normalize`),
  `MappingExpressionKind` (`dbt/mapping_specs`), and `SourceTableIdentitySpec`
  (`dbt/policy_specs`). Also dropped the ignored `entity_uris` parameter of `bind_policy_facts`
  (and the caller-side set it was fed). Deleted the orphaned `core/managed_text_block.py` module
  entirely — it was infrastructure for the retired `claims-to-silver-ext` command and had no
  remaining importers.

### Fixed
- **`init` never populated `ontology-reference-models/`** (#290). `cli/setup.py` carried only a
  *comment* claiming reference models were "populated later"; the sole real call lived in
  `new_repo`. So an `init`-created hub had no archetypes, patterns, blueprints or accelerator
  packs — `discovery-conformance`, `list-patterns`, `check-inventory`, `design-landscape`,
  `coverage-report`, `fit-report` and `analyse-sources --accelerator` could not run at all — and
  the catalog it wrote chained to an `<nextCatalog>` that dangled from birth. `init` now fetches
  them, with `--skip-refmodels` to opt out and `--ref-models-version` to pin.
  The fetch **resolves the newest semver tag** rather than floating `main`, since archetypes carry
  `compatible_with.repo_tag_range` checked against exactly that; it also copies the upstream root
  `VERSION` file, which lives outside the vendored subdirectory and whose absence had silently
  disabled version-drift checking. Failure is never fatal — no network, no git, a clone error or a
  Windows `MAX_PATH` overrun all degrade to a warning naming `update-refmodels`, and `init` still
  exits 0 with a usable hub. An existing checkout is never clobbered, **not even with `--force`**,
  because the documented flow runs `init` inside a `new-repo` hub whose reference models are
  already pinned.
  The clone/copy logic is now one `_fetch_reference_models()` helper shared by `init`,
  `update-refmodels` and `new_repo`, replacing two near-duplicate implementations. It builds into a
  temporary directory and validates the result before replacing the destination, so a partial
  clone can no longer masquerade as a complete reference-model set.
- **`new_repo` committed the entire index when populating reference models.** Its dirty check ran
  `git status --porcelain` over the whole repository and its `git commit` carried no pathspec, so
  any work the user had staged was swept into a `chore: populate ontology-reference-models`
  commit — and then pushed. Both are now scoped to `-- ontology-reference-models`.
- **`init`'s own glossary template silently disabled the DD-148 discovery gate** (#288). `init`
  copies `glossary-template.ttl` into `businessdiscovery/`, and the predicate deciding whether
  business-discovery evidence exists excluded only names ending `.template` — not
  `-template.ttl`. So a freshly-scaffolded hub counted the scaffold's own file as authored
  evidence: `check_discovery_gate()` passed and `compile`/`validate` proceeded with zero
  discovery. The predicate lived in **two** copies (`core/hub_inspection.py` for the advisory
  `next` signal, `core/conformance_artifact.py` for the actual gate); patching only the first
  would have had no enforcement effect at all — `next` is advisory and always exits 0 (DD-137) —
  and would have made it print a rationale claiming a hard-fail that does not happen. Both now
  share one `is_authored_discovery_ttl()` in `core/hub_utils.py`, so they cannot drift again. The
  regression test drives a real `init` and asserts both the snapshot **and** the gate see
  discovery as missing, pinning the end-to-end property rather than the predicate.
- **`catalog-test` was almost a no-op** (#289). It verified only that the catalog file existed and
  was readable, so a dangling `<uri>` target and a domain ontology with no entry both passed with
  a green checkmark — observed in the field as a hub with 13 domains, zero catalog entries, and one
  active entry pointing at a `logistics.ttl` that was never created, with every tool reporting
  success. It now checks entry targets, unmapped domains, `<nextCatalog>` targets and catalog
  cycles, and reports parse failures instead of raising. Severity is deliberately narrow: it
  **fails** only on a dangling entry declared in the catalog under test, or an unparseable
  catalog. Unmapped domains are advisory, because `sync_domain_catalog_entry` runs only from
  `init --domain` and nothing else registers a domain — a hard gate would redden every hub that
  grew via the design skill, for a convention the toolkit does not maintain. Dangling entries in
  *chained* catalogs are likewise advisory and name the owning file, so a bad entry in the
  vendored reference-models catalog (79 of 80 audited entries on a real hub) cannot fail a hub its
  author cannot fix. Absolute-URI entries are no longer mangled into false danglers.
- **Multi-source conformance collapsed to one contributor for contracted dbt-model sources**
  (#284, DD-028 amendment). N `EntityBinding`s sourced from `source.dbtModel` and sharing a
  `conformance` group produced a single silver model, and `compile --check` failed with a
  misleading `identity.source-contributor-mismatch` ("declared 8, actual 1") that pointed at
  the identity declaration rather than the real cause. The compiler adapter blanked
  `source_name`/`table_name` to `""` for dbt-model sources — putting the relation identity in
  `ref_model` — but `merge_bound_sources` builds conformance branch names from exactly those
  two fields, so every branch was named `{entity}__from___` and all but the last were
  overwritten. The blanking was never load-bearing: `ref()` vs `source()` has always been
  decided by `ref_model` alone. The spec now always describes the bound relation, giving
  `{entity}__from_dbt__{model}` branches. This also fixes `_source_system`, which rendered as
  the empty string literal in every dbt-sourced branch — and therefore in the reconciliation
  and contribution-lineage models — and now renders `'dbt'`. Raw `relation:` sources are
  unaffected; their branch names are unchanged. A duplicate branch name is now a hard error
  instead of a silent last-write-wins that would `UNION ALL` a model with itself.
- **The managed virtual source of a contracted dbt model leaked back out as a raw dbt source**
  (#284). `merge_bound_sources` rebuilt its result with `replace(base, ...)` and never
  re-derived the top-level `virtual_table_uris` set, so only the *first* binding's virtual IRIs
  survived the merge. Any later dbt-model binding then failed the filter that keeps virtual
  tables out of the source catalog and was emitted into `models/silver/_dbt__sources.yml` as a
  physical source that nothing references — a `source('dbt', '<model>')` declaration for a
  relation the projector deliberately reaches by `ref()`. This fired whenever a
  relation-sourced binding sorted ahead of a dbt-model one, independent of conformance.
  **Migration:** the file is no longer generated, but `*__sources.yml` is treated as a shared
  cross-domain artifact and preserved across compiles, so an already-emitted
  `models/silver/_dbt__sources.yml` will linger and must be deleted by hand.
- **Fabric packaging helper corrupted Databricks semantic models** (#206). `_sanitize_tmdl` in
  `scaffold/dataplatform/scripts/package_fabric_semantic_model.py` rewrote `" = m"` → `" = entity"`
  on **every** line containing `partition `, to fix a Direct Lake partition older projector
  releases mislabelled. But `= m` is the *correct* TMDL source-type keyword for a Power Query
  partition, which is exactly what the Databricks/directQuery path emits — so the helper stamped an
  entity-partition header over a `let … in` M body, producing an unloadable model. The rewrite is
  now block-aware: it inspects the partition body and only converts blocks that are genuinely
  Direct Lake shaped (bare `source` + `entityName:`), never one carrying a `source =` M expression.
  Also anchored to end-of-line, so a partition named e.g. `= model` is no longer mangled to
  `= entityodel`.
- **The PBIP wrapper had two writers that had already diverged** (#206). Both the gold projector and
  the packaging helper wrote `.platform` and `definition.pbism`, with different contents — the
  projector emitted a bare `{"version": "4.2"}` pbism while the helper wrote one with `$schema` and
  `settings`. The projector is now the single source of truth and emits the complete, schema-stamped
  files; the helper only *backfills* them when absent, for hand-authored or imported models. That
  also stops it resetting a `logicalId` Fabric has since assigned.
- **`init` scaffolded a nested second hub when run from a content subdirectory** (#187, DD-062).
  `init` took `Path.cwd()` as the repo root unconditionally, so running it from the `ontology-hub/`
  content root of a split-layout hub fabricated an entire second hub inside it — a nested
  `ontology-hub/ontology-hub/`, a duplicate managed `.github/` (skills + copilot-instructions), and
  a second `pyproject.toml` pinning a **different** toolkit version and channel than the
  authoritative repo-root pin. The DD-062 resolver `find_managed_root()` already existed but was
  wired only into `update`. `init` now refuses when an enclosing managed root is detected, naming
  it and pointing at `update`. It **refuses rather than re-roots** (unlike `update`, which safely
  re-roots): `init` creates ~15 paths and honours `--force`, so silently re-rooting could overwrite
  a live hub's managed files. Re-running `init` at the hub root itself stays supported, so the
  documented `new-repo` → `init --company-domain` backfill flow is unaffected.
- **`extract-schema` CLI command was unreachable.** `cli/shared.py::extract_schema` carried a full
  `@click.option` stack and a tested `core.extract_schema.run_extract_schema` implementation, but
  was missing its `@click.command` decorator and was never registered, so
  `kairos-ontology extract-schema` returned "No such command" despite being referenced as an
  upstream step by `import-source`/`import-flatfile`. It is now decorated and registered.
- **`kairos-design-domain` assumed one shape for `grain_collisions`.** The instruction added
  earlier in this release told the skill to read each entry "against the named class" and quote
  "the stated `reason`" — but the published library ships **two shapes**: `multimodal-order-leg`
  uses `{against, reason}` mappings while `governed-code-list` and `qualified-role-assignment`
  ship bare prose strings. The guidance was wrong for two of the three patterns that have
  content. It now handles both and never assumes the keys exist. The test fixture was also
  corrected: it used a `naming_conventions` **mapping**, which no published pattern does.
- **Hollow patterns are no longer silent.** `pattern_quality_warnings()` flags a pattern that
  parses but cannot deliver what it claims — `normativity.naming: normative` with no
  `naming_conventions`, an `anti_patterns` entry with no `rejection_reason` for the skill to
  cite, or `naming_conventions` that is not a list of entries. Warnings surface in
  `list-patterns` (whole library **and** `--pattern <id>`, which previously reported none at
  all). Deliberately **consumer-side detection, not enforcement**: patterns are still returned
  and nothing raises, because breaking the authoring loop over advisory craft would be worse.
  Valid YAML is only the floor, and reference-models still owes
  `blueprints/patterns/_schema/pattern.schema.json` — the authoring-time fix. The five
  currently-published patterns pass these checks cleanly.
- **`compute_scorecard` silently dropped concepts.** Tier buckets were seeded from `VALID_TIERS`
  and any other tier was skipped, so a concept carrying a tier this toolkit predated was counted
  in `total` but omitted from every bucket — `total` no longer equalled the sum of `by_tier`, with
  no warning. Buckets are now seeded from the supplied tiers *union the tiers actually present*,
  and no concept is ever skipped.
- **Scorecard validation no longer depends on ambient checkout state.** `validate_artifact`
  recomputes the scorecard and demanded exact equality, so an artifact built where the tier enum
  resolved to four tiers and validated where it fell back to three (no `KAIROS_REFMODELS_ROOT`)
  differed only in an *empty* bucket yet failed with "'scorecard' contradicts 'core_concepts';
  regenerate it" — pointing the user at something that was not wrong. Empty buckets are now
  normalised away before comparison; a genuinely inconsistent scorecard is still caught.
- **Version drift now covers every ontology tier, not just `derived-ontologies/`.**
  `check_version_drift` resolved `compatible_with.ontology_versions` pins only under
  `derived-ontologies/<KEY>/VERSION`, so a `Blueprint` or `FIBO` pin resolved to `None` and was
  skipped silently. `freight-forwarder` already declares the blueprint module **`required`** and
  `blueprints/ontology/` is at 0.1.0 on its own cadence, so the one dependency most likely to
  move under a hub had no drift coverage at all. Also probes
  `authoritative-ontologies/<KEY>/VERSION` and `blueprints/ontology/VERSION`.
- `_load_archetype_schema` now normalizes its root like every other entry point in
  `archetype_loader`; it was the module's only raw path join, safe only because its one caller
  pre-normalized.

### Changed
- **Removed `black` as the formatter; `ruff format` is now the sole formatter.** Black was a
  declared dev dependency and documented formatter but was never enforced in CI, leaving the code
  drifted from its own config. The redundant tool and `[tool.black]` config are removed, the whole
  `src/` and `tests/` tree is reformatted with `ruff format` (black-compatible, 100-char), and
  `CONTRIBUTING.md` now names `ruff format` as the formatter.
- **`kairos-design-domain` pattern guidance now covers structure, not just naming (DD-150).**
  `mode_bindings`, `grain_collisions` and `participants` already reached the CLI payload via the
  `extra` flatten, but the skill only instructed on `naming_conventions` / `anti_patterns`, so the
  most expensive guidance in the library never reached a designer. Step 6 now reads four surfaces:
  normative naming; `anti_patterns` rejected on **structure as well as names** (mode-typed
  subclasses of an aggregate, subclassing a mode-bound standard at the wrong grain, shortcut links
  bypassing a reified intermediate, a document standing in for a reservation); `mode_bindings` as
  the per-mode binding decision (`modelled` → bind, `extension-point` → **do not invent a class**,
  `pattern-only` → pattern alone); and `grain_collisions` as do-not-subclass boundaries. Still
  advisory and still a silent no-op on an absent library.
- Reference-models **v1.14.0 resolves the `temporal-quartet` finding** recorded under DD-146 — all
  five published patterns now parse under `yaml.safe_load`. A
  `blueprints/patterns/_schema/pattern.schema.json` is still absent and remains the standing ask.
- `pattern_loader` module docstring records that leniency is correct for callers and useless as a
  quality signal — a skipped pattern is an absent pattern — and points callers wanting a
  guarantee at `load_pattern` or at asserting `load_patterns` returned no warnings. Also corrects
  a stale cross-repo reference: the pattern library is `v0.2 — markdown-first, parse-guarded`,
  not `v0.1 — no JSON Schema`. That exact class of stale reference is what let the defect above
  survive: this repo's loader was written lenient *because* the reference-models README said the
  library had no schema, while that README said there was no toolkit consumer for the library.
  Each repo was relying on the other's assumption.
- **Power BI/TMDL analysis is demand evidence, not a source (DD-147):** `import-tmdl` now
  defaults its output to `integration/discovery/bi/` instead of `integration/sources/powerbi/`,
  matching its semantics as downstream demand evidence rather than a canonical input source.
  `design-landscape` reads BI concept-mappings from `integration/discovery/bi/**` (still reading
  the legacy `integration/sources/**` location for back-compat), `draft-model-report --tmdl-dir`
  auto-detects the new folder with a legacy fallback, and `init`/`new-repo` scaffold it with a
  README. The `kairos-design-source` import skill now offers a Power BI/TMDL import step after
  sources, explicitly as demand evidence — never a source relation.
- **`kairos-design-source` batch import:** the source-import skill now enumerates every available
  source up front, asks whether to import all sources in one batch, continues past individual
  failures, and shows a short report of which sources were imported and which remain.

### Added
- **Discovery-before-design hard gate and human-confirmed archetype selection (DD-148,
  DD-149):** `kairos-ontology compile`/`validate` now hard-fail unless a
  `businessdiscovery/` narrative (DD-048) or a discovery conformance artifact (DD-090)
  exists, and always hard-fail when a fleet-mode (DD-088) conformance artifact has
  unresolved AI-decided concept judgments — `discovery-conformance validate` gets the
  same check plus a `--allow-unresolved` escape hatch for diagnostic use.
  `kairos-ontology next` mirrors both as advisory `blocking` signals. Archetype selection
  in `kairos-design-discovery` is now a human-only confirmation gate (never fleet-eligible),
  recorded as `archetype.confirmed_by` in the conformance artifact, which bumps to
  schema v2 (breaking change; no hub in production yet).
- **`validate --domain <domain>`:** the `validate` command now accepts `--domain` for
  parity with `compile`, using it as the domain hint that resolves the accelerator so a
  multi-pack hub no longer trips on accelerator ambiguity between Gate 0 and Gate 5. The
  validation target is unchanged when omitted.
- **`check-inventory --verbose` / `--all`:** with `--domains`, out-of-scope module
  inventories are collapsed to a single non-blocking summary line instead of a wall of
  `❌ MISSING` output; `--verbose` restores the full per-module listing. A domain with no
  reference-model profile now says so explicitly rather than listing every module as
  missing.
- **`scope.no-bindings-authored` diagnostic:** the ontology-only waypoint (a valid
  ontology slice exists but no `EntityBinding` is authored yet, or none selects the domain)
  now raises a distinct, still-blocking code instead of `safety.source-unresolved`, so a CI
  gate can tell an expected early authoring stage from a broken source.
- **Docs:** `kairos-setup-config` documents pinning `[tool.kairos].accelerator` in the hub
  `pyproject.toml`; `kairos-design-domain` shows the `--domain`/`--accelerator` forms on
  Gate 0 and Gate 5.
- **`design-landscape` command (Phase 0 Design Landscape, CR-7):** `kairos-ontology
  design-landscape [--accelerator <id>] [--domain <domain>] [--format text|json]` joins,
  per activated accelerator class, four already-existing evidence signals — source
  coverage (generalized `fit-report` across every `propose-alignment`-aligned table),
  business-discovery demand (the DD-090 `discovery-conformance` artifact), BI/report
  weight (`import-tmdl`'s Concept Mapping `reference_model_match`), and current binding
  state — into a single classification per class: `canonical-candidate`,
  `passthrough-candidate`, `demanded-but-unbound`, `bound-but-undemanded`, or
  `no-evidence`. A deterministic aggregation only — no LLM calls, no raw TTL reads (every
  ontology fact is read via `ontology_loader`/`fit_report`, per DD-103). BI/TMDL evidence
  is kept in a structurally separate, always-present `bi_weight` field and may only
  affect ranking within the `demanded-but-unbound` backlog, never a class's
  classification (C1) — enforced by a test that removes all BI evidence and asserts the
  classification is unchanged. Missing inputs (no accelerator checkout, no
  `propose-alignment` output, no conformance artifact, an unresolvable binding) are
  reported as `gaps` rather than raised, so the report degrades gracefully instead of
  failing outright.
- **`scaffold-system` command (batch fast path to Silver, CR-4/CR-7):** `kairos-ontology
  scaffold-system --system <system> [--dry-run]` runs `scaffold-binding --archetype
  passthrough` across every unscaffolded table under `integration/sources/<system>/`, using
  only `propose-alignment`'s already-persisted `ref_class`/`ref_class_confidence` evidence —
  it never guesses a target class. A table is declined (with a concrete reason:
  `already-covered`, `no-alignment-evidence`, `ambiguous-class`, `ambiguous-domain`,
  `non-mechanical`, `scaffold-failed`) rather than scaffolded on a low-confidence or
  multi-source-claimed match, so a human can override the call by hand. After scaffolding,
  every touched domain is run through `compile --check` and each diagnostic is attributed
  back to the binding file it points at, producing one review report (text or `--format
  json`) instead of one-file-at-a-time output. `--dry-run` (also newly added to
  `scaffold-binding` itself) previews the same decisions with zero writes under the hub.
- **`scaffold-binding` command (fast path to Silver, DD-144):** `kairos-ontology scaffold-binding
  --system <system> --table <table> --archetype <type> [--target-class <IRI>]` generates a
  first-draft v5 `EntityBinding` YAML for one Bronze source table. Supports five standard
  archetypes: `passthrough` (tier passthrough, fully automatic, ready to compile unedited),
  `single-source-master`, `merged-master`, `event-stream`, and `line-item-child` (all tier
  canonical, write skeletons with `<CONFIRM_...>` placeholders for grain/identity/survivorship).
  Reuses DD-144 accelerator-direct class targeting (no local subclass minted by default), DD-139
  technical fields for unmapped key/FK columns, and `fit-report`'s property resolution. Orphan
  columns are reported but never auto-materialized. Also provides `--list-unscaffolded --system
  <sys>` (read-only report of tables without bindings yet) and `--list-archetypes` (print the
  archetype catalog). Can seed merged-master from an existing passthrough binding via
  `--from-binding <path>`.
- **`fit-report` command:** `kairos-ontology fit-report --class <IRI-or-qname> [--source
  <system>.<table>] [--binding <path>]` computes, deterministically and without any LLM
  call, the set-difference between an accelerator class's full property universe (direct +
  inherited, via the DD-103 semantic index) and what's already populated by an existing
  binding or `propose-alignment` evidence — `populated`, `unpopulated` ("what you can still
  pick from"), and `orphan_columns`. Advisory input to design, not a completeness gate; its
  core logic (`core/fit_report.py::run_fit_report`) is a plain library function reused by
  `scaffold-binding`.
- **`--check`/`--explain` combinable on `compile`:** both flags may now be passed together
  in one invocation (diagnostics and the explain report both come back; `CompileResult`
  already computed both internally, so this required no new compile mode). `--emit` stays
  mutually exclusive, since it's the only side-effecting mode.
- **Stable diagnostic-code catalog (`docs/dev/diagnostic-codes.md`):** documents all 117
  distinct `CompileDiagnostic` codes across the compiler, with severity and owning
  `rule_id`/DD citation, backed by an AST-based test that fails if a new or removed code
  drifts out of sync with the doc.
- **Accelerator-direct binding resolution (DD-144):** an `EntityBinding`'s `target.class`
  (and a relationship's `target`) may now resolve directly against an accelerator/
  reference-model class with no local `rdfs:subClassOf` declaration at all — the compiler
  already builds its semantic index over the full resolved `owl:imports` closure (DD-103),
  it simply never looked outside the domain's own locally-declared namespace before. A
  local subclass is now needed only for a genuine deviation, not as the default path for
  reusing an accelerator concept as-is. Resolution is scoped to only the class/property
  tokens a binding in the current compile scope actually references, so it never floods
  diagnostics with an accelerator's entire term universe, and a token that resolves nowhere
  still reports the existing `binding.unknown-class`/`binding.unknown-property` diagnostics
  unchanged.
- **DD-139 authored technical fields, implemented (auto-materialization stays rejected):**
  an `EntityBinding` may now declare `technicalFields:` — an explicit, closed-schema way to
  materialize a source column (for identity, quality, or relationship support) without
  asserting a new ontology property. Technical fields are real Silver outputs (real dbt
  columns, schema, and parity hash) but are never emitted as OWL and are explicitly labelled
  as technical in `compile --explain`. A column must still be explicitly mapped by the
  author — the compiler never adds a technical field on its own.
- **`metadata.tier` on `EntityBinding` (passthrough / canonical):** an additive, optional
  field distinguishing a generated, single-source "conformed passthrough" binding from a
  hand-designed "canonical" entity binding. Absent `tier` still defaults to `canonical`
  (today's only behavior), so every existing binding continues to validate unchanged.
  `kairos-ontology next`'s hub-input snapshot now tallies passthrough vs. canonical bindings
  per domain for future coverage reporting; this is data collection only and does not change
  `next`'s readiness ladder.
- **`distinct_count` surfaced by `parse_source_vocabulary()`:** the Bronze source-vocabulary
  parser used by `analyse-sources`/`propose-alignment`/`suggest-shapes` now also returns each
  column's `distinct_count` (already persisted on the Bronze TTL via
  `KAIROS_BRONZE.distinctCount`, previously read only by `suggest-shapes`'s own parser).
  Strictly additive — no existing key changes.
- **DD-103 semantic-access enforcement:** `init`/`update`/`new-repo` now scaffold a
  `.claude/settings.json` denying direct `Read`/`Grep` access to domain ontology TTL
  (`model/ontologies/**`, `model/shapes/**`) and accelerator reference-model TTL
  (`ontology-reference-models/**`), steering any Claude-Code-mediated session toward the
  canonical semantic commands (`resolve-ontology`, `show-class-inventory`, `explain-term`,
  `list-class-properties`) instead of reading raw Turtle text. A new static test
  (`tests/test_ttl_access_boundary.py`) asserts no `core/*.py` module other than
  `ontology_loader.py`/`catalog_utils.py` parses TTL directly going forward, with an
  honestly-tracked, non-growing exemption list for 18 pre-existing modules already
  migrating incrementally per DD-103's own consequences.
- **Standard conformance-report output format for `kairos-design-discovery` (DD-143, #257):** the
  discovery skill now documents a standard visual archetype conformance-report template (outcome-code
  badge legend, at-a-glance Mermaid dashboard, per-section heading badges, interview log) so
  conformance findings render consistently across hubs.
- **Business-friendly `kairos-help` orientation:** the skill now leads with a plain-language
  purpose statement, a lifecycle-stage table, and a full skills reference table with example
  prompts, so new users get oriented without needing prior ontology vocabulary.
- **Toolkit-driven `kairos-design-discovery` conformance authoring:** the skill now mandates using
  the `kairos-ontology discovery-conformance list-archetypes` / `load` / `validate` CLI commands
  as the authoritative source for archetype ids, outcome codes, and the core-concept catalog,
  instead of hand-transcribing archetype files or hand-rolling generator scripts. The outcome-code
  legend now reflects the actual 5-code contract instead of a stale, hardcoded 8-code list.
- **Three-tier dbt validation guidance in `kairos-execute-validate`:** clarifies the distinction
  between canonical `compile --check` (always in scope), the offline `validate-dbt` gate
  (opt-in, no warehouse credentials), and real `dbt build`/`dbt test` (dataplatform-only, requires
  a live warehouse connection and is out of scope for this skill). Documents the exact
  `uv sync --extra dbt-validate-*` commands needed before `validate-dbt` can run, and directs the
  skill to confirm the target platform (Fabric or Databricks) with the user before the first
  `validate-dbt` invocation in a session.
- **Platform-aware dataplatform `profiles.yml.example`:** `init-dataplatform --platform` now
  pre-activates the matching connection block (Fabric Lakehouse, Fabric Warehouse, or Databricks)
  in the generated `.dbt/profiles.yml.example`, with the other two platforms kept as commented
  reference blocks — no more manual comment-toggling to switch platforms.

### Fixed
- **`technicalFields[].type` schema/normalizer drift:** the entity-binding schema enum now
  covers the full `CanonicalTypeKind` vocabulary (`int16`, `float64`, `time`, `binary`,
  `json`, …) that the normalizer already accepts, closing the reverse drift left after the
  earlier canonical-token fix. A test asserts the enum equals the enum's value set so the
  two cannot diverge again.
- **`managed-check` workflow uses `uv run kairos-ontology update --check`:** the scaffolded GitHub
  Actions workflow referenced the bare `kairos-ontology` command, which is not on `PATH` after
  `uv sync`; it now calls `uv run kairos-ontology update --check` so the managed-files check runs in
  the uv-managed venv.

## [5.0.2] — 2026-07-29

### Fixed
- **`compile --emit` no longer nests output inside the hub (DD-142 amendment):** `--emit` is now a
  pure flag with a fixed, non-configurable target — `<repo>/ontology-hub-publish/medallion/dbt`.
  The previous optional `--emit DIRECTORY` argument anchored relative values (e.g.
  `ontology-hub-publish/medallion/dbt`) to the hub root, producing
  `ontology-hub/ontology-hub-publish/medallion/dbt` (the publish tree wrongly nested inside the
  hub). Passing a directory to `--emit` is now rejected.

## [5.0.1] — 2026-07-30

### Added
- **Toolkit `kairos_` dbt macro pack (CHG-3):** shipped four compiler-emitted, adapter-portable
  macros — `kairos_clean_sentinel`, `kairos_normalize_key`, `kairos_survivor` (deterministic
  survivorship ranking with a mandatory total order), and `kairos_source_system_label` — for use
  in hand-authored contracted `int_*` models. The `kairos_` macro namespace is reserved.

### Changed
- **Derived output relocated to sibling `ontology-hub-publish/` (DD-142):** all emitted/derived
  artifacts (dbt, Power BI, Neo4j, Azure Search, a2ui, prompt, reports, architecture, MDM,
  validation reports, shapes-draft) now materialize at `<repo>/ontology-hub-publish/…` — a sibling
  of `ontology-hub/` at the repository root — instead of inside the hub at `<hub>/output/…`. A
  shared `publish_root(hub)` helper routes every path. Bare `--emit` targets
  `ontology-hub-publish/medallion/dbt`; explicit `--emit DIR` uses the exact directory and anchors
  relative values to the hub root (fixing the cwd-relative wrong-output-folder bug). `output` is no
  longer a hub marker directory. Scaffold `.gitignore`, `packages.yml.template`, and the release
  workflow repoint to the new location; the tree stays in the repository.
- **Per-adapter reserved-word quoting (CHG-5):** the medallion dbt projector now selects reserved
  identifiers from the per-adapter capability registry (`is_reserved_identifier`) instead of a
  single hardcoded T-SQL list, so identifier quoting is correct for both `fabric` and `databricks`.
  Fabric now also quotes `from`.

### Documentation
- **Contracted dbt naming/layering conventions (CHG-1/CHG-2):** documented single-source
  `int_<source>__<entity>`, multi-source survivorship `int_merged__<entity>`, and the
  `stg_<source>__<entity>` → `int_merged__<entity>` layering in the
  `kairos-develop-dbt-transformation` skill (conventions, not linted invariants).
- **MDM seam clarification (CHG-4):** noted that survivorship / `in_<system>` presence flags remain
  deferred design-time MDM policy not yet exposed as CompilePlan fields, and that `core` must never
  import `mdm`.

## [5.0.0] — 2026-07-29

### Added
- **Stateless `next` readiness inspector (DD-137):** new CLI command that reports the
  next inspect/design/bind/validate/compile action from authored hub inputs without
  mutating state.
- **Per-hub OKF Decision Log (DD-141):** capability for capturing confirmed design
  decisions with rationale, confidence, and references.
- **Unified cross-domain emit (DD-140):** consolidated emit path and resolver/diagnostic
  remediation for cross-domain compilation.

### Fixed
- Toolkit confirmed-defect batch and follow-up remediation of resolver, diagnostics, and
  the compile validation loop.

### Documentation
- Consolidated the **5.0 candidate** documentation around the implemented DD-133 clean
  break: canonical TTL/source vocabularies, one closed EntityBinding per source, optional
  ordinary dbt SQL/YAML and Gold/MDM policy, stateless compile modes, the immutable
  `CompilePlan`, supported adapters, and downstream consumption.
- Added an exact retained-command reference and removed active guidance for retired v4
  claims, preparation, lifecycle/readiness, release-evidence, and Silver-extension
  authorities. Historical ADR records remain labeled and available for provenance.
- Rewrote the lean hub and dataplatform scaffold documentation, including reversible
  `update --test-ref` / `update --restore` testing.

## [5.0.0rc1] — 2026-07-27

### Added
- **V5 authoring and compilation (DD-133):** introduced closed YAML
  `EntityBinding` contracts and stateless `compile --check`, `--explain`, and
  `--emit` workflows with deterministic Fabric/dbt output and atomic,
  manifest-owned emission.
- **Unreleased toolkit testing (DD-134):** added reversible
  `update --test-ref <branch-or-sha>` and `update --restore` workflows so hubs
  can test immutable toolkit commits without publishing a release.

### Changed
- **Intentional V5 authoring break:** canonical ontology and source vocabulary
  remain authoritative, while one YAML binding replaces the V4 mapping,
  preparation, lifecycle-state, and release-evidence authoring path. Existing
  client hubs start fresh; no V4 hub compatibility or migration path is
  provided.
- Reworked the canonical-domain and mapping skills around bounded ontology
  patches, source-grounded bindings, explicit review, and fail-closed privacy.

### Removed
- Removed the accidentally tracked `fabric_cicd.error.log` diagnostic artifact.

## [4.7.0rc12] — 2026-07-27

### Fixed
- **Silver sync evaluated inactive accelerator domains (#243):**
  `check-projection --scope silver` now limits claim/projection synchronization
  to the domains selected by the shared projection plan instead of requiring
  ontology files for every domain declared by an accelerator pack.

## [4.7.0rc11] — 2026-07-27

### Changed
- **Fact-extraction decomposition guarded by a full-artifact characterization
  baseline (DD-132):** the large medallion dbt fact-extraction functions
  (`_extract_silver_model_facts` / `_extract_schema_model_facts`) and the
  preparation-policy normalization (`_index_preparation_policies`) were decomposed
  into smaller single-purpose helpers with **no change to generated artifacts**. A
  new characterization test pins the complete artifact set (all file paths + byte
  content + non-file coverage/release facts, in true emission order) for the
  acme-hub client, invoice, and logistics scenarios against a frozen SHA-256
  baseline, with a deliberate `regenerate_dbt_artifact_baseline.py --write` path for
  intentional changes.

## [4.7.0rc10] — 2026-07-26

### Fixed
- **Silver bound-confirmation gate ignored accelerator context (#239, DD-131):**
  `check-projection --scope silver` computed `expected_imports` without the
  accelerator / catalog / ref-models context, so every data-domain-activated
  `owl:imports` was false-flagged as an `extra import` and the Silver
  bound-confirmation gate could never go green. `_silver_sync_diagnostics` now
  threads `accelerator`, `catalog_path`, and `ref_models_dir` into
  `evaluate_projection_sync`, matching `claims-to-silver-ext --check-only`.

### Added
- **Multi-class property domains (#240, DD-131):** a shared
  `effective_domain_classes()` resolver now honours `owl:unionOf` domains,
  `schema:domainIncludes`, and repeated `rdfs:domain` (treated as union) in exactly
  one place, consumed by the semantic index (`validate-mapping`), dbt `bind`, and
  the medallion dbt projector. A property whose domain spans classes with no common
  local parent is recognised on every member class, so `validate-mapping` accepts a
  column mapped to it from any member class's table. Scope is limited to Silver /
  dbt / `validate-mapping`; the single-`rdfs:domain` case is behaviour-preserving.

## [4.7.0rc9] — 2026-07-26

### Fixed
- **Silver-ext shape discovery with packaged fallback and Windows-safe loading
  (DD-130):** `validate-silver-ext` and `scaffold-silver-ext` now resolve the
  Silver SHACL shape from the hub-local managed file first and fall back to the
  packaged canonical shape, reporting the selected source. A missing shape yields
  a precise `silver.shapes-missing` diagnostic, and shapes are parsed via a
  resolved `file://` URI so an absolute Windows drive-letter path (e.g. `G:\...`)
  is never mis-read as a URL scheme. A new `--shapes` override is validated by
  Click before it reaches rdflib.
- **Booking / medallion dbt projection fixes:** refinements to the medallion dbt
  projector, dbt policy normalization, FK normalization, projection specs, the
  projector claim gate, managed-import synchronization, and the dbt bundle, with
  expanded scenario and unit coverage.

## [4.7.0rc8] — 2026-07-26

### Fixed
- **Convergent Silver readiness and managed imports (DD-129):** focused Silver
  validation now prefers the hub catalog, reports distinct closure, shape-loading,
  and SHACL execution failures, and behaves consistently with explicit catalog
  selection. Managed-import synchronization and readiness now consume the same
  reasoned `ManagedImportPlan`, retaining activated, authored, and accepted
  transitive dependencies without hiding genuinely stale imports.
- **Domain-scoped projection source authority (DD-129):** dbt bind now derives one
  immutable, explainable active-source scope for preparation, mapping, identity,
  coverage, and physical planning. Unrelated-domain mappings no longer create
  readiness obligations, while synchronized contracted dbt virtual sources and
  required cross-domain identity dependencies remain visible with inclusion
  reasons in readiness output.

## [4.7.0rc7] — 2026-07-26

### Added
- **Intent-preserving coverage classification, run-atomic registry writes, and
  authoritative model precedence (DD-128):** a table whose class anchor is
  deliberately unresolved (DD-124) emits zero claims by design, so `check-claims`
  no longer reports it as a blocking column omission ("columns were dropped");
  it is surfaced instead as a new non-blocking `unresolved_anchor_tables` facet
  (`⚠ Unresolved class anchors`, plus an additive `registry.unresolved_anchor_tables`
  JSON key) whose remediation points at the anchor decision, while genuine
  truncation keeps blocking. `propose-alignment` now stages every registry and
  unresolved-anchors write and commits them only after the run-wide semantic
  verdict is known, so `AlignmentTotalFailureError`'s "no claim registries were
  written" promise also holds for a domain mixing `provider_failure` with
  `fallback_only` tables and for an opted-in `--allow-fallback-output` domain —
  existing files are never touched by a failed run. The caller/CLI-resolved model
  (`--model` > `--high-accuracy` > `KAIROS_AI_ALIGNMENT_MODEL` > default) is now
  authoritative for the whole run: the provider preflight is endpoint/auth
  metadata only and no longer lets the per-role env override beat an explicitly
  pinned model.
- **Unified claim-activation predicate and a versioned claim-check result
  (DD-122):** `binding_analysis` gains one shared
  `claim_activates_projecting_import()` predicate (plus its complement
  `is_decided_non_activating()`), now the single authority behind managed-import
  planning, claims↔projection sync, and activation-inventory selection, so those
  three consumers can never diverge on whether a decided claim activates a
  projecting `owl:imports`/`silverInclude`. A deferred/rejected claim whose
  reference module stays active for another reason is now reported as a
  `DisputedClaimModule` (claim id, status, module, import IRI, reasons) in both
  `check-claims` and `claims-to-silver-ext`, instead of the decision silently
  reading as ignored. New `core/claim_check_result.py` composes the existing,
  independently governed evaluators into one versioned
  (`CLAIM_CHECK_RESULT_SCHEMA_VERSION = 1`) `ClaimCheckResult` with separate
  `registry` / `semantic_generation` / `mapping` / `projection_sync` facets and a
  flattened `disputed_claims` list, emitted verbatim by the new
  `check-claims --format json`. `semantic_generation` consumes DD-121's additive
  `generation_outcomes` metadata rather than inventing a second notion of
  "generated", so registries predating that feature stay vacuously complete.
  `SourceCoverageReport` and `ProjectionSyncReport` now declare the `owner_skill`
  that enforces them.
- **Domain-ownership handoffs and generalized, stable-cluster relationship
  candidates (DD-127):** `propose-alignment`'s claim emission now enforces the
  accelerator's `owns`/`does_not_own` domain boundary *before* a claim is ever
  created: a column resolved to a sibling/shared reference-model module
  (DD-070 `ref_module`) becomes a versioned `DomainHandoff` record (owning
  domains + source evidence, surfaced via a new `cross_domain_handoffs` report
  key) instead of an in-domain property claim. Relationship-candidate
  clustering is generalized beyond address parts: every cluster now carries a
  stable, column-membership-independent `cluster_id` (derived from source
  table, semantic role, target class, and cardinality), so multiple
  contributing columns merge into one cluster, scalar evidence stays
  associated underneath, and a re-run *refreshes* cluster membership/rationale
  while preserving any curated fields and never replacing prior decisions or
  stable ids. New generic safeguards downgrade a false-positive object-property
  mapping before it is trusted: technical/audit-actor columns
  (`created_by_*`/`updated_by_*` and similar) always fall back to
  audit/passthrough evidence and never produce a relationship candidate;
  non-location object properties require identifier-shaped column evidence;
  specialized location properties require the column to carry that location's
  own typed-role evidence. An `"unresolved"` table anchor now emits neither
  claims nor relationship clusters. All new logic is accelerator-generic — no
  hard-coded logistics/DCSA/Booking vocabulary was added.
- **Metadata-complete, convergent scaffolding (DD-126):** `claims-to-silver-ext`'s
  fresh-domain scaffolding now emits a full `rdfs:label` / `rdfs:comment` /
  `owl:versionInfo` / prefix-bound skeleton for `{domain}.ttl` and
  `{domain}-silver-ext.ttl`, validated against the same metadata gate as
  hand-authored ontologies before anything is written. Scaffolding also
  convergently updates `_master.ttl`'s `owl:imports` registration and the
  scaffold README's domain table (when those files already exist), preserving
  all authored content outside the regions it owns. The command now returns/prints
  an explicit created/updated/unchanged path accounting with counts, a
  managed-vs-authored explanation, and a `git status` hint for new files. An
  invalid domain or failed metadata check is isolated to that domain — sibling
  domains still scaffold, and no rollback of already-written files is ever
  claimed or performed; a `ScaffoldPartialFailureError` reports precisely what
  succeeded and what didn't.
- **Failure-safe alignment generation (DD-121):** `propose-alignment` now records a
  typed per-table generation outcome (`semantic_success` / `provider_failure` /
  `fallback_only`) with sanitized provider/model/error metadata. A run where every
  attempted table fails exits non-zero and writes nothing; partial failure keeps
  succeeding tables visible while the failed ones are reported (never cached, never
  silently masqueraded as semantic output). Writing a domain whose tables are all
  `fallback_only` (no reference model to align against) now requires the explicit
  `--allow-fallback-output` flag. `check-claims` surfaces incomplete generation
  per domain as a non-blocking `incomplete_generation` warning, distinct from
  structural claim validity. `ai_provider.create_chat_completion()` now handles
  unsupported request parameters with one capability-aware, narrowly-guarded retry
  (no hard-coded per-model capability table), and `propose-alignment` preflights
  and reports the effective role model before fan-out.
- **Additive JSON/Markdown validation reports (DD-120):** `validate --report-format
  json|markdown|both` and `--report-path PATH` select an explicit report destination
  without changing the pre-existing JSON-only default. The Markdown report is
  deterministic and includes the toolkit version, effective command options, catalog,
  accelerator, scope/files, and findings, plus a typed, non-writing DD-080
  lifecycle-state suggestion (`run_validation` never mutates `.kairos-state/`).
- `sync-dbt-contracts` now reports the running toolkit version and, when an existing
  generated artifact carries a toolkit provenance stamp, its prior generator version —
  never invented when no stamp is present.
- **URI-first confirmed-anchor resolution (DD-124):** `propose-alignment` now resolves a
  table's reference-model class anchor against the confirmed `kairos-design-discovery`
  Core Concepts Conformance evidence (`outcome: conforms`/`conforms-with-rename`) *before*
  any LLM/name-similarity class selection, and that confirmed URI wins over the model's own
  pick. When the confirmed evidence itself is ambiguous for a table, the anchor is never
  silently resolved to the nearest class: the table is written with
  `ref_class_status="unresolved"` and produces zero property/custom claims, and a versioned
  `{domain}-unresolved-anchors.yaml` record (stable id, candidate URIs, evidence) is written
  alongside the claims registry so the decision can be resolved later without being lost. A
  human resolution recorded in that file is honored on subsequent runs. `CoverageTable`
  gained a sparse `likely_entity_uri` field preferred over name-based URI lookup, and
  imported `claim`/`specialize` records missing a resolvable class/property URI now raise a
  non-blocking warning-level `validate_registry()` diagnostic. Old Claim Registries without
  these fields continue to load unchanged.
- **Domain-ownership-inferred accelerator resolution (DD-125):** `validate`, `project`/
  `check-projection`, `check-inventory`, and `check-claims` now all route accelerator
  selection through one shared resolver (`resolve_hub_accelerator_detailed`), with the
  precedence explicit `--accelerator` > `[tool.kairos].accelerator` > unambiguous inference
  unchanged and no new configuration key. When multiple accelerator packs are installed and
  neither is set, the active domain(s) are now checked against each pack's
  `data-domains.yaml` (via the same nested `groups[].domains[]` parser used by inventory and
  managed-import planning); if exactly one pack owns the domain it is inferred, otherwise the
  original ambiguity error is preserved unchanged. `check-inventory` gained a previously
  missing `--accelerator` option, and all four commands now print the resolved accelerator,
  its source, and the resolved `data-domains.yaml` path as diagnostics.

### Changed
- **`check-claims` blocking scope narrowed to curation (DD-122) — behavioural
  change.** `check-claims` (with or without `--strict`) no longer exits non-zero
  on source-mapping gaps or claim↔projection sync drift alone. Only registry
  validity/freshness and governance policy block by default, plus undecided
  (`proposed`) claims under `--strict`. Mapping gaps and sync drift are still
  reported — now with the `owner_skill` that enforces them and `⚠` styling —
  and are enforced by `kairos-design-mapping` and
  `claims-to-silver-ext --check-only` respectively. CI invocations that relied
  on `check-claims --strict` to catch sync drift must now also run
  `claims-to-silver-ext --check-only`; the new opt-in `--require-mapping` flag
  folds mapping-coverage gaps back into the exit code for
  `kairos-execute-project`'s DD-094 pre-silver gate.
- Standardized user-facing terminology on **toolkit upgrade**, **managed-file
  refresh**, and **contract synchronization** across CLI help/output and the
  `kairos-help`/`kairos-execute-validate` skills.
- **Mapping-skill-derived table scope (DD-123):** `kairos-design-mapping` now derives a
  repeatable **Confirmed table scope** `--table` list from the confirmed Phase 1 Table
  Alignment Proposal, persists it in the phase log for reuse across pause/resume, and
  passes it to Gate 6's `check-transformation-readiness --stage mapping`. A blocked
  contract outside that scope now stays visible as a non-blocking diagnostic in
  `evaluate_transformation_readiness` instead of disappearing from the report; unscoped
  invocation remains reserved for hub-status/release checks.

### Fixed
- Non-strict dbt projection now permits unverified contract-output identity as
  review-only bootstrap output, while strict projection and release eligibility remain
  blocked until current warehouse uniqueness and non-null evidence is captured.
- `check-transformation-readiness --stage mapping|silver` no longer blocks on unverified
  contract-output identity alone; `--stage release` still blocks until current, passing
  warehouse evidence is captured (DD-119).
- **`check-inventory` scoped-domain wording (DD-125):** a scoped `--domains` result no longer
  reports the ambiguous `"(none matched)"` for a domain it still calls ready. Each requested
  domain now reports one of "matched accelerator profile", "matched direct inventory"
  (naming the inventory keys that made it ready), or "no profile found".
- **`check-claims` registry-ownership diagnostics (DD-125):** the "registry domain not found
  in data-domains.yaml" warning is now computed against the same accelerator pack every other
  command resolves for the hub (instead of an independently, and sometimes incorrectly,
  chosen pack), and the warning now includes the checked `data-domains.yaml` path.

## [4.7.0rc6] — 2026-07-26

### Added
- **Shared non-writing projection readiness (DD-116):** versioned diagnostics support
  fail-fast generation and collected, prerequisite-aware readiness across scoped closure,
  phase gates, Silver bound confirmation, and monotonic lifecycle status.
- Verified dbt contract-output identity evidence, focused mapping/Silver validators,
  evidence-grounded authoring scaffolds, and an explicit preview-first column-IRI migration.

### Changed
- Lifecycle skills now route logical Silver through any required contracted transformation,
  final mapping, non-writing bound confirmation, full readiness, and only then generation.
- Managed regeneration preserves authored content, and status reports stale phase-log
  deliverables without treating legacy completion as readiness evidence.

## [4.7.0rc5] — 2026-07-25

### Added
- **Typed medallion contract redesign (DD-106–DD-115):** immutable bind, normalize,
  shape, materialize, and render phases now govern preparation, Silver, Gold, quality,
  lineage, identity, incremental processing, and adapter capabilities.
- **Profile-driven Gold products:** dimensional Power BI v1 now uses explicit table roles,
  governed measures, calendars, security, incremental policy, and strict release evidence.
- **Typed operational reporting:** reports distinguish normative policy, generated checks,
  known deviations, and downstream runtime observations without inferring success.

### Changed
- Silver dbt, YAML, DDL, ERD, preparation, and multi-source outputs now consume shared
  contracts with deterministic parity and canonical hashing.
- Scaffold skills, SHACL authorities, documentation, and lifecycle/status guidance now
  describe the redesigned medallion and release boundaries.
- Missing downstream DQ observations are reported as `not-evaluated`, not supported.

### Fixed
- Registered future Gold profiles dispatch through their materializer registry.
- Peer ontology metadata loads through the canonical semantic boundary without allowing
  extension versions to override the domain ontology version.
- Gold foreign-key qualification no longer reads the removed Gold column override.

## [4.7.0rc4] — 2026-07-23

### Fixed
- Hub-local ontology inventories no longer conflict with namespaced reference-module
  inventories that share the same source stem.

## [4.7.0rc3] — 2026-07-22

### Added
- **Governed imported-dbt candidate assessment (DD-105):** explicit repository-contained
  SQL/dbt roots can be inventoried as non-executable planning evidence, surfaced in
  deterministic status, and checked before Mapping, Silver, and release.

### Changed
- Custom dbt contracts may declare a valid subset of Fabric/Databricks adapters; projection
  still rejects a selected adapter the model does not support.
- Validation and projection resolve accelerator context from the explicit CLI option, hub
  configuration, or an unambiguous installed pack.

### Fixed
- Managed virtual-source vocabularies now preserve explicit non-key `not_null`
  tests/constraints instead of marking every non-key contract column nullable.

## [4.7.0rc2] — 2026-07-22

### Added
- **Typed reference-module activation and managed imports (DD-104):** version-pinned
  module profiles now drive deterministic ontology-document imports and activation
  inventories without copying imported definitions into authored domain ontologies.
- **Portable Silver lineage and temporal contracts:** generated dbt models now retain
  Bronze-primary-key source identity and load context, support explicit current/as-of
  SCD2 FK resolution and relationship change detection, and emit contract metadata and
  generic tests consistently for Fabric and Databricks.

### Changed
- Bound incremental Silver models now reject missing or partially mapped natural
  keys, use timestamp-precision SCD2 windows, and enforce portable physical identifiers.
- Multi-source Silver models now implement the declared SCD1/SCD2 lifecycle instead of
  advertising history semantics over a plain table.

### Fixed
- SCD2 parent lookups no longer fan out across historical rows, and generated lineage
  columns no longer duplicate names supplied by a custom audit envelope.
- **Nested business-discovery imports (DD-060 amendment):** `discovery-status` now
  scans `.import/businessdiscovery/` **recursively** and matches extractions by
  normalized `source_path` provenance, so valid records for documents in subfolders
  are no longer misreported as orphaned. New nested records get collision-safe,
  path-derived extraction filenames; existing records are preserved and never
  renamed. Duplicate provenance is surfaced as a new `conflict` warning.

## [4.7.0rc1] — 2026-07-22

### Added
- **Canonical ontology closure loading (DD-103):** recursive catalog-aware
  `owl:imports` traversal now provides deterministic manifests, diagnostics,
  cross-machine-stable closure hashes, cycle handling, and explicit strict or
  degraded semantics.
- **Versioned semantic index:** asserted, RDFS, Kairos design, and OWL RL profiles
  expose class/property hierarchies, restrictions, equivalence, inverses,
  individuals, and module provenance without consumer-specific reparsing.
- **Structured semantic inspection:** new `resolve-ontology`,
  `show-class-inventory`, `show-source-schema`, and `explain-term` CLI commands
  provide authoritative machine-readable context for users and managed skills.

### Changed
- Semantic consumers now share the canonical closure and semantic index across
  validation, inventory, analysis, alignment, projection, and prompt generation.
- Inventory schema 2.0 records semantic profile, closure freshness, import
  completeness, and direct versus inherited properties.
- Required imports fail closed by default; callers that intentionally accept
  partial semantics must explicitly enable degraded mode.

### Fixed
- Transitive dependency changes now invalidate generated inventories.
- Projection failures propagate when every ontology fails closure loading instead
  of returning a successful process status.

## [4.6.0] — 2026-07-21

### Added
- **Deterministic Silver-first lifecycle:** confirmed conformance outcomes now
  deterministically produce proposed-only claims, approved unbound claims can emit
  target-first dbt stubs, and `check-release` composes claim, mapping, synchronization,
  validation, projection, binding, and release-eligibility gates without duplicating
  their rules.
- **Canonical projection facts:** shared completeness, materialization, target, and
  foreign-key models now provide one deterministic interpretation across status,
  coverage, synchronization, Silver DDL, dbt, Gold/Power BI, and release gates.
- **Five-phase dbt pipeline (DD-102):** dbt generation now orchestrates typed immutable
  `bind → normalize → shape → materialize → render` phases while preserving existing
  public facades and byte-identical artifacts.
- **Authoritative Silver-first lifecycle scenario:** the copied `acme-hub`
  integration now proves validated conformance → proposed-only claims → explicit
  governance approval → managed extension sync → aspirational stubs → selected
  source binding → strict release, including deterministic output and real dbt
  parse/compile tooling.

### Fixed
- Fresh scaffold placeholders no longer falsely complete source or projection phases,
  and validation reports are written where deterministic status expects them.
- Projection timestamps are resolved once per run, malformed reproducibility inputs
  fail explicitly, and generated reports use stable manifest-managed paths.
- Claim regeneration now enforces preservation of every declared human-curated field.
- Silver, dbt, and Gold projectors now share one FK classifier, including redirected
  and inferred relationships.
- Catalog-resolved approved imported classes now participate in the same
  `BindingAnalysis` used by `status` and `check-release`.
- SHACL-derived dbt generic-test arguments render as nested YAML instead of
  sibling keys that dbt rejects during parse.

### Changed
- **Legacy inventory and Claim Registry projection layouts now require an explicit
  migration.** Runtime inventory readers no longer self-heal or dual-read retired
  stem-named reference inventories, and claim projection sync no longer converts
  inline controlled triples during normal operation. Run
  `kairos-ontology migrate --hub <hub>` first; `--check` / `--dry-run` preview every
  change. The migration is idempotent, preserves non-managed authored Turtle, and
  retains rollback copies in `.kairos-migrations/legacy-format-backups/`.
- Runtime source/claim coverage now evaluates one canonical per-table completeness
  snapshot; the retired alignment-coverage runtime and its parallel authority have
  been removed.

### Removed
- Unused Silver/projector helpers and four obsolete dbt staging/date templates.

## [4.5.0rc4] — 2026-07-21

### Fixed
- **`update --upgrade` now rewrites optional-extras toolkit pins.** The
  pin-rewriter previously only matched the primary
  `kairos-ontology-toolkit @ …` dependency, leaving
  `[project.optional-dependencies]` pins such as
  `kairos-ontology-toolkit[flatfile] @ …` on the old version. With the primary
  pin advanced and extras pins stale, `uv lock` failed with conflicting URLs for
  the same package. The rewriter now preserves any `[extra]` marker and updates
  every occurrence. The scaffold `pyproject.toml.template` also gains `azure`,
  `foundry`, and `parquet` extras pins alongside `flatfile`.

## [4.5.0rc3] — 2026-07-21

### Fixed
- **Alignment & projection correctness hardening** (DD-098,
  `docs/draft/toolkitoptimizations.md`; F1 fixes #219). Seven independent
  correctness/governance gaps in the source→domain alignment and medallion
  projection pipeline, each keeping default output byte-identical when no new
  condition fires:
  - **F1 naming parity (#219):** the dbt silver projector no longer hardcodes
    `silver_{domain}` / `camel_to_snake(local)`. A shared physical-naming helper
    (`silver_schema_name` / `silver_table_name` / `silver_naming_convention` in
    `projections/shared.py`) is now consumed by both the silver DDL and dbt
    projectors, so `silverSchema` / `silverTableName` / `isReferenceData` /
    `namingConvention` produce identical schema, table, and SK-key names across
    targets; the gold `ref()` registry uses the generated model name.
  - **F4:** URI backfill threads an optional inventory index into
    `write_claims_output` so proposed claims carry resolved `class_uri` /
    `property_uri`.
  - **F5:** `check-inventory` gains `--domains` / `--explain-scope` with a
    catalog-resolved domain→inventory map (repo-wide check stays the default).
  - **F6:** truncation integrity — a deterministic source column count + sha256
    is persisted per `(system,table)`, every source column is reconciled into a
    passthrough candidate, and a blocking `column_omissions` signal is added.
  - **F2/F7:** grain-conflict detection — `likely_entity` provenance is carried
    on `TableAlignment` and a blocking `grain_conflicts` record is emitted when
    distinct candidate entities collapse onto one `ref_class`.
  - **F3:** object-property target resolver — a scalar column attached to an
    object property whose governed target does not resolve is downgraded to a
    passthrough custom claim plus an `object_property_relationship_candidate`.

## [4.5.0rc2] — 2026-07-21

### Fixed
- **Multi-domain dbt projection collisions & peer-import drift** (DD-097, #220):
  full-hub `project --target dbt` no longer aborts with a false artifact
  collision on shared/package-level files (README, `dbt_project.yml`,
  `models/gold/shared/dim_date.sql`, `_shared__gold_models.yml`, per-system
  `_{sys}__sources.yml`). Shared gold artifacts are now domain-neutral
  (materialized to a stable `gold_shared` schema), per-system `_sources.yml`
  files are reconciled via a deterministic union, and package-level config is
  merged last-wins. Domain-only projection (`--ontology <domain>.ttl`) now
  collects hub domain namespaces from the full ontologies directory, so required
  peer-domain `owl:imports` are no longer flagged as claim/projection drift.
- **S3-folded subtype SHACL constraints lost on parent model**: when a subtype
  using the discriminator inheritance strategy is S3-folded into its parent
  silver model, its SHACL property constraints (e.g. `sh:pattern` →
  `dbt_expectations.expect_column_values_to_match_regex`) now propagate onto the
  parent model's folded columns instead of being dropped.

### Changed
- **dbt package source**: generated `packages.yml` and the approved-package list
  now reference `metaplane/dbt_expectations` (the maintained namespace for
  versions ≥0.10) instead of the deprecated `calogica/dbt_expectations`,
  silencing dbt's hub-namespace deprecation warning. Version constraint and the
  in-package `dbt_expectations.*` macro namespace are unchanged.

### Added
- **Target-first aspirational Silver stub → bind loop** (DD-096): opt-in
  `project --emit-aspirational-stubs` flag (also `KAIROS_EMIT_ASPIRATIONAL_STUBS`)
  emits typed, zero-row Silver stub models (`where 1 = 0`, `cast(null as <type>)`,
  tagged `kairos_aspirational_stub`, `meta.is_aspirational`) for approved,
  materialization-eligible claims that have no bronze mapping yet — so downstream
  Silver/Gold can be built target-first. Adding a source mapping transparently
  **binds** the stub on the next projection. `aspirational` is **derived** at
  projection time from the Claim Registry + mappings (never persisted). Feature-off
  output is byte-identical to prior releases. Backed by a new canonical
  `BindingAnalysis` service.
- **Release gate for unbound approved claims** (DD-096 / DEC-1): `project --strict`
  (env fallback `KAIROS_PROJECT_STRICT`, dbt/all only) fails when any approved,
  materialization-eligible claim has no bronze mapping (an *unbound target*), so an
  incomplete hub cannot be released with vacuous zero-row stubs. Wired into the
  scaffold `release-projections.yml` workflow. Independent of stub emission —
  release-eligibility, not artifact existence, is the gate.
- **Status-scan awareness of stubs** (DD-096 D4): `kairos-ontology status` distinguishes
  stub vs bound by running the canonical `BindingAnalysis` over the hub's authorities
  (Claim Registry + graph + sources + mappings), not generated `meta.is_aspirational`. A
  silver domain with an approved-but-unbound claim now reports `in-progress`
  ("aspirational stub(s) pending binding") instead of `done`, keeping `kairos-flow` and
  `kairos-diagnose-status` correct.
- **Obsolete dbt output reconciliation** (DD-096 C3): the dbt projector records a
  `.kairos-projection-manifest.json` and deletes previously generated files it no
  longer produces (e.g. a stale aspirational stub after the feature is disabled or its
  claim is deferred), pruning emptied directories. Only toolkit-recorded files are
  removed — hand-authored files are never touched.
- **Deterministic projection output**: generated artifacts embed an injected
  `generated_at` + `toolkit_version` context (env-overridable via
  `KAIROS_GENERATED_AT` / `SOURCE_DATE_EPOCH`) and all RDFLib iteration is sorted, so
  re-projection is byte-identical across processes and Python hash seeds.

## [4.4.0] — 2026-07-19

### Added
- **Contracted advanced dbt transformations** (DD-092): package handwritten,
  contract-first intermediate models for joins, windows, aggregation, fallback logic,
  JSON expansion, and grain changes while retaining generated ontology-aligned Silver
  wrappers. Adds managed virtual-source vocabulary synchronization, Fabric/Databricks
  platform selection, offline dbt graph validation, and the interactive
  **kairos-develop-dbt-transformation** skill.
- **Governed source replacement coverage** (DD-093, #215): contracted dbt models can
  declare canonical Bronze `replaces_sources` without unsafe direct SKOS mappings.
  Coverage requires an approved matching claim, synchronized replacement RDF,
  table-level `skos:exactMatch`, matching `silverSourceRef`, and no competing source
  authority; generated dbt sources retain declared contract inputs.
- **Privacy-safe source sample persistence** (DD-075): source import, schema
  extraction, and Bronze vocabulary generation now replace supported detected PII
  with opaque source-aware tokens before writing. The skill-gated `source-privacy`
  check/fix command remediates existing YAML and vocabulary artifacts without
  printing raw values.
- **Canonical Bronze source discovery** (DD-093): source analysis, coverage, and
  dbt-contract validation now share source identity rules. Generated contract
  vocabularies no longer create redundant affinity obligations, legacy reports are
  archived, split-source reports are consolidated, equivalent monolithic/split
  vocabularies are reconciled, and divergent definitions remain blocking.
- **Design-time MDM layer** (MDM-DD-001..003, mdmhubdesignv2.md ADR-1): a new,
  additive Master Data Management design layer expressed in
  `model/extensions/{domain}-mdm-ext.ttl` overlays, driven by the managed
  `kairos-mdm` vocabulary (`https://kairos.cnext.eu/mdm#`) — mastered concepts +
  MDM style, match attributes/identifiers, attribute authority + survivorship,
  deterministic match rules/thresholds, a content-addressed probabilistic-artifact
  reference (weights never in Turtle), maker/checker + SLA workflow policy, abstract
  steward roles, reference-data policy, and six-dimension DQ rules.
  - `kairos-ontology project --target mdm-profile` projects an **immutable,
    runtime-neutral** MDM profile (`{domain}-mdm-profile.json` with a reproducible
    `content_digest`, plus a `{domain}-mdm-profile.md` review summary) to
    `output/mdm/`. The target is opt-in (not part of `--target all`).
  - `kairos-ontology mdm-validate` runs a structural design-time gate over
    `*-mdm-ext.ttl` (controlled enumerations, thresholds, match rules, DQ
    dimensions, probabilistic-artifact digest). Skill-managed via **kairos-design-mdm**.
  - **Source split**: ontology functionality moved into `kairos_ontology.core`;
    the new `kairos_ontology.mdm` design-time package is an *additive consumer* of
    core. A one-way boundary is enforced — `core` never imports `mdm` (registry
    pattern; `tests/test_layering.py` guard). Public API is preserved via top-level
    `kairos_ontology` re-exports.
  - New scaffold asset `kairos-mdm.ttl`. See **MDM-DD-001..003** and
    `docs/dev/mdm/`.
  - New **kairos-design-mdm** skill (`.github/skills/` + scaffold mirror) for
    interactive `*-mdm-ext.ttl` authoring, plus MDM docs under `docs/dev/mdm/`
    (`mdm-design-decisions.md`, `user-stories.md`, `mdm-navigator-spec.md`).

### Changed
- **Docs housekeeping**: reorganised `docs/` for navigability. Added a
  `docs/README.md` documentation map; consolidated all MDM docs under `docs/dev/mdm/`
  (moved `mdmhubdesignv2.md` from `docs/dev/`); archived unreferenced historical
  material (former `docs/draft/` and the `evidence-led-modeling` tracker) under
  `docs/archive/` with a `README.md` frozen-history marker; removed a duplicate
  `ddd-governance-implementation-plan.md`; and repathed all inbound references. Pure
  relocation via `git mv` — no doc content was rewritten.

## [4.4.0rc17] — 2026-07-05

### Added
- **Optional DDD governance overlay** (DD-091): a new, additive Domain-Driven
  Design design layer expressed in `model/extensions/{domain}-ddd-ext.ttl`
  overlays, driven by the managed `kairos-ddd` vocabulary
  (`https://kairos.cnext.eu/ddd#`) with typed bounded contexts, reified context
  relationships, and controlled tactical-pattern individuals.
  - `kairos-ontology validate --ddd` (also run by `validate --all`) validates
    overlays through a dedicated path that merges each overlay with its domain
    ontology + the `kairos-ddd` vocabulary and applies packaged DDD SHACL shapes.
    Overlays that leak `kairos-ext:silver*`/`gold*` predicates fail.
  - `kairos-ontology project --target ddd` renders one-way documentation
    (Mermaid context map + aggregate overview + Markdown report) to
    `output/architecture/ddd/`. It never changes silver/gold/dbt/Power BI output.
  - Governance (ownership, approval, disposition, materialization) stays in the
    claim registry; XMI / Enterprise Architect round-trip is out of scope.
  - New modules `ddd.py`, `projections/ddd_projector.py`; scaffold assets
    `kairos-ddd.ttl` and `kairos-ddd-shapes.shacl.ttl`. See **DD-091**.

## [4.4.0rc16] — 2026-06-22

### Added
- **Core Concepts Conformance** (archetype + discovery contract v0.2, ref-models
  v1.11.0): new `discovery-conformance` CLI command group (`list-archetypes`,
  `load`, `validate`) and supporting modules `archetype_loader.py`,
  `archetype_topology.py`, `conformance_artifact.py`. Loads a business archetype's
  machine catalog (modules + core concepts + tiers), validates it against the
  shipped JSON Schema, derives relationship topology by parsing each
  `ref_model_modules[].iri` directly, and persists a validated
  `integration/discovery/core-concepts-conformance.yaml` artifact.
- `kairos-design-discovery` gains a **Phase 2.5 — Core Concepts Conformance**
  interview (interactive by default; fleet pre-fill); `kairos-design-domain` now
  reads the conformance artifact during reference-model selection (warn-only).
- New scaffold dir `ontology-hub/integration/discovery/` created by `init` /
  `new-repo`. New `KAIROS_REFMODELS_ROOT` env var for refmodels-root resolution.
- New runtime dependency `jsonschema>=4.0.0`. See **DD-090**.

## [4.4.0rc15] — 2026-06-22

### Fixed
- Silver FK metadata now resolves S3 discriminator-folded FK targets to the
  projected parent table, so DDL comments, ALTER documentation, and ERD lineage no
  longer point at skipped child tables.
- dbt projection now routes table mappings targeting S3-folded subtypes into the
  projected parent model while preserving subtype discriminator values, mapped
  subtype columns, and mapping filters.
- `audit-silver-samples` now accepts dbt lineage comments and full target URIs
  when checking mapped-target SQL presence, avoiding false positives for object
  properties rendered as FK columns.
- Power BI projection claim-sync gating now validates `silverInclude` against the
  exact domain silver extension while still passing gold extensions to the
  Power BI projector.
- Power BI gold projection now emits Fabric semantic-model wrapper files and
  parser-ready TMDL directly, so generated SemanticModel folders no longer need
  downstream sanitation before deployment.
- Per-domain Power BI SemanticModel output now omits cross-domain relationships
  to tables that are absent from the local model, avoiding invalid TMDL while a
  future master SemanticModel covers cross-domain reporting.

## [4.4.0rc14] — 2026-06-22

### Added
- `analyse-sources` now reports advisory sample-data coverage in affinity YAML and
  warns non-blockingly when fewer than half of a source system's analysed tables
  have sample values, because schema-only analysis can be semantically ambiguous.
- Design skills now support a skill- and invocation-scoped **design fleet mode**
  override for test runs. Fleet consent never propagates across lifecycle phases;
  AI decisions preserve evidence, validation, and traceable AI-approved logs.
- Source design now asks for the LLM provider and authentication mode at every
  invocation, including Azure AI or Microsoft Foundry through
  `DefaultAzureCredential`; a complete `.env` configuration is the recommended
  default and is confirmed before the first LLM call.
- Added `audit-silver-samples`, an offline advisory QA command that checks
  generated dbt silver mappings against source sample values without a warehouse
  connection.

## [4.4.0rc13] — 2026-06-21

### Added
- Scaffolded hub repos now expose a `flatfile` optional dependency that installs
  the toolkit's Excel support (`openpyxl`) via `kairos-ontology-toolkit[flatfile]`,
  enabling `uv sync --extra flatfile` before Excel `import-flatfile` runs.

### Changed
- `kairos-design-source` now recommends analysing all ready source systems in one
  `analyse-sources` pass by default, reserving scoped `--sources` runs for
  explicit exclusions, rate-limit workarounds, or targeted retries.
- `kairos-design-discovery` now treats image-heavy artifacts as first-class
  discovery evidence, including screenshots, diagrams, scanned PDFs, embedded slide
  images, and OCR/visible text, with optional visual provenance in extraction YAML.
- `kairos-flow` and `kairos-design-domain` now offer a governed data-product
  vertical-slice route for report/TMDL/semantic-model intent while preserving source
  analysis, claim, mapping, silver, and gold confirmation gates.
- `kairos-design-domain` now batch-scans in-scope domains for stale, missing,
  incomplete, empty, or unverifiable claim evidence and proposes one costed refresh
  plan using scoped `--domains ... --max-workers` runs instead of one-domain-at-a-time
  refresh loops.

### Fixed
- `generate-inventory` and `check-inventory` now ignore archived reference-model TTLs,
  preventing current/archive duplicates from fighting over the same inventory file and
  falsely marking fresh inventories stale.
- `decide-claims` now blocks unsafe approvals before writing: materializing
  `claim`/`specialize` claims cannot be approved without required URI/evidence, while
  reviewed `passthrough` approvals remain URI-free.

## [4.4.0rc12] — 2026-06-21

### Changed
- Clarified the V3 stable hotfix workflow while V4 release-candidate work lives
  on `main`, including worktree setup, tag-from-stable guardrails, and
  stable/preview channel expectations.

## [4.4.0rc11] — 2026-06-21

### Added
- **Data-product vertical-slice planning reports (DD-087).**
  `draft-model-report` now accepts a planning-only data-product contract to emit
  scoped `data-product-plan.yaml`, Markdown, and Mermaid ERD artifacts under
  `model/planning/data-products/{product}/`. The slice remains advisory
  (`projection_authority: false`) and derives triage from DD-086 evidence
  statuses instead of bypassing claims, mappings, silver, or gold design.

## [4.4.0rc10] — 2026-06-21

### Added
- **Reporting-informed draft model reports (DD-086).** New deterministic,
  advisory `draft-model-report` command builds all-domain draft evidence packs
  from claim extraction inputs, richer TMDL evidence, source affinity, mappings,
  and glossary terms. It writes YAML/Markdown plus one cross-domain Mermaid ERD
  under `model/planning/draft-model/` and is explicitly non-authoritative:
  no claim auto-approval, no TTL writes, and no projection authority.
- **Deterministic address relationship candidates surfaced during alignment
  (issue #192, Phase A1).** `propose-alignment` now promotes clustered address-part
  columns (e.g. `billing_street` + `billing_city` + `billing_postal_code`) into a
  machine-readable, **advisory** `relationship_candidates` entry on the Claim Registry
  (`hasBillingAddress → Address`), in addition to the existing scalar column
  dispositions. The detector is role-aware (`billing_*` vs `shipping_*` are separate
  relationships), always-on, additive, and uses **no LLM / no cross-module widening**;
  candidates carry the source columns and `requires_human_confirmation: true` but no
  resolvable target URI. A new MANDATORY *Checkpoint 3c — Relationship &
  Satellite-Entity Review* in `kairos-design-domain` blocks TTL generation until each
  candidate has an explicit model/relate/defer decision. Concrete target-URI naming
  (A2) and FK-driven satellite detection (Phase B) are deferred. See DD-084.
- **`decide-claims` CLI — query + bulk-curate claim status/disposition (issue #190).**
  A new AI-free command (`decide_claims.py`) to list claims by selector
  (`--status`/`--disposition`/`--type`/`--origin`/`--id`/`--column` globs) and to
  bulk-set status via `--by-disposition` or `--set-status` (`--dry-run` for counts).
  Writes back through the canonical `write_registry`, so curation produces minimal,
  reviewable diffs instead of hand-edited YAML noise.

### Changed
- **`analyse-sources` now reports table completions as concurrent LLM workers finish.**
  The command already used up to 8 per-table LLM calls by default; progress is now
  streamed per completed table while output YAML remains deterministic.
- **OKF phase logs replace interactive `.sessions-design` logs (DD-085).** New hubs
  use `.kairos-state/phases/...` as the required design-session memory for
  discovery/source/domain/mapping/silver/gold skills. Legacy `.sessions-design/*.md`
  files are historical only and are not auto-migrated. Import audit logs
  (`.sessions-design-import/`) and projection reports (`.sessions-projection/`)
  remain separate.
- **`project --ontology` supports single-domain projection.** Operators can now run
  `kairos-ontology project --ontology model/ontologies/party.ttl --target silver`
  to regenerate one ontology file while preserving hub-root discovery for
  extensions, mappings, sources, shapes, and claims. Existing `--ontologies`
  directory mode remains unchanged.
- **Hub-side offline dbt validation guidance.** Ontology-hub scaffolds now include
  a `dbt-validate` optional dependency group (`dbt-core` + Fabric adapter in the
  1.9 family) and `.env.example` version guidance so `kairos-execute-project` can
  run `dbt deps` + `dbt parse` against `output/medallion/dbt/` after dbt
  projection. Downstream dataplatform repos are not given extra validation-only
  dependencies.

### Fixed
- **dbt SCD2 FK joins stay in scope for inherited role/subclass relationships
  (issue #194).** SCD2 silver models now select FK lookup columns in the
  `mapped` CTE where the FK join aliases are visible, then reference the mapped
  FK aliases from `source_data`. This fixes invalid SQL such as
  `address_ref.address_sk` being emitted after `address_ref` has gone out of
  scope.
- **Claim projection sync now fails loudly on invalid intra-hub ontology bases.**
  `_collect_hub_domain_bases` no longer silently skips malformed Turtle while
  collecting `_foundation.ttl` / `_master.ttl` imports, avoiding false "in sync"
  reports when a shared hub base is broken.
- **Intra-hub shared bases (`_foundation.ttl`, `_master.ttl`) are no longer stripped
  from domain `owl:imports` (issue #190).** `_collect_hub_domain_bases` skipped every
  `_`-prefixed file, so foundation/master imports were flagged as `extra` and removed
  by projection sync. It now treats any `owl:Ontology`-declaring `*.ttl` under
  `model/ontologies/` as an allowed intra-hub base (only `-ext.ttl` surfaces are skipped).
- **`migrate-claims` now back-fills `class_uri`/`property_uri` from the reference-model
  inventory (issue #190),** so anchored claims can be approved without manual URI lookup.
  Ambiguous names stay null (never guessed); resolved/unresolved counts are printed.
  `--no-resolve-uris` opts out; `--inventory-dir` overrides discovery.
- **`claims-to-silver-ext` now scaffolds a minimal valid ontology / `*-silver-ext.ttl`
  skeleton for a fresh domain instead of silently writing nothing (issue #190).**
  The skeleton carries a provenance header and inferred hub base / foundation import;
  `--no-scaffold` disables it.
- **The MDM-anchor warning in `check-claims` now prints a concrete `mdm_anchor: true`
  reference_data claim example and points to the skill / `--no-mdm-anchor` (issue #190).**
- **`claims-to-silver-ext` no longer destroys authored TTL when syncing projection
  surfaces (issue #191).** The destructive whole-graph rdflib re-serialize is replaced
  by a **block-delimited managed region** (`# >>> kairos-managed … # <<< kairos-managed`)
  that the tool regenerates with full URIs; the provenance header, comments, prefix
  layout, local subclasses, and triple ordering outside the block are preserved
  verbatim. Managed import/include sync is unchanged and still enforced by `check-claims`.
  Repeated syncs are idempotent, and legacy inline imports migrate into the block on the
  next sync. Also closes the DD-082 item-5 limitation (scaffolded header survives the
  first sync with approved imported claims). See DD-083.

> ~~The destructive whole-graph rdflib rewrite of projection surfaces (issue #190 item 6)
> is tracked separately as **issue #191**.~~ Resolved above (issue #191).

## [4.4.0] — 2026-06-20

### Fixed
- **`analyse-sources --domains` no longer forces unrelated tables into the filtered
  domain (issue #189).** `--domains` previously pruned the LLM **candidate** domain
  set before classification, so every table was forced into the requested domain (or
  `unclassified`), polluting affinity evidence and downstream `check-claims` counts.
  It is now a pure **post-classification output filter**: tables are always classified
  against the full accelerator/reference domain set (getting their true primary domain),
  then only tables whose primary domain matches `--domains` are written. A system with
  no matching tables now writes an empty affinity report instead of erroring. `--max-domains`
  (which still truncates candidates as a rate-limit guard) now warns when it truncates.
- **`release.yml` now normalizes the release tag to PEP 440 before comparing it to
  `__version__`**, mirroring `_tag_to_version()`. Both `vX.Y.Zrc1` and the
  SemVer-style `vX.Y.Z-rc.1` (the form the channel resolver and `_whl_url` already
  expect) now validate, instead of only the exact PEP 440 string.

### Added
- **Two-layer lifecycle state, deterministic `status` CLI, and the `kairos-flow`
  single entry point (DD-080).** Introduces a formal, resumable lifecycle state model
  for ontology hubs.
  - **`kairos-ontology status`** — a new read-only, AI-free CLI (`status.py`) that
    deterministically scans committed hub artifacts and reports a per-phase /
    per-instance objective state (`not-started` / `in-progress` / `done`) for the
    whole lifecycle (`discovery, source, domain, mapping, claims, silver, gold,
    validate, project`). Supports `--format text|json|markdown`; exempt from the
    skill-gate like the other deterministic gates.
  - **`kairos-flow` skill** — the single entry point ("start / where are we /
    continue / resume"). Runs the scan, reconciles it against the saved continuation
    state, presents a lifecycle overview, offers clean-start vs continue, and hands
    off to the correct phase skill. Interactive-only; it is the only writer of
    `status.md`.
  - **OKF continuation-state bundle** at `ontology-hub/.kairos-state/` (created by
    `init` / `new-repo`): `status.md` (scan-derived / continuation / phase-index
    regions) plus per-instance `phases/<phase>/<instance>.md` logs with an Open
    Questions resume anchor, following the Open Knowledge Format v0.1 as a storage
    convention.

### Changed
- **`kairos-diagnose-status`** now defers objective status to `kairos-ontology
  status` (deterministic backbone) and focuses on enrichment/diagnostics.
- **Phase design/execute skills** (discovery, source, domain, mapping, silver, gold,
  validate, project) gain a lightweight read-state + state-proposal contract against
  `.kairos-state/`; they no longer maintain global status themselves.
- Methodology doc gains §21 (lifecycle state model and single-entry orchestration);
  skill routing table, `kairos-help`, and the CLI lifecycle table point to
  `kairos-flow`.

## [4.3.0] — 2026-06-15

### Added
- **MDM/reference-data rules + ownership hardening in `check-claims` (DD-EL-6).**
  Slice 4 adds four deterministic governance checks to the single `check-claims`
  gate plus the Claim Registry schema they need.
  - **MDM-anchor gate (§5.4).** A *broad domain claim* (an approved class claim
    with disposition claim/specialize) is blocked with `anchor_pending` when the
    domain declares `mdm_anchor` reference-data claims that are still `proposed`,
    and warned with `anchor_missing` (pragmatic — anchors must be *known*, not
    fully implemented) when broad claims have no declared anchors at all.
  - **deviation-log check (§12/§14).** Approved `gap` (client-native) claims that
    lack a deviation record (owner + reason) block with `deviation_missing`.
  - **ownership-boundary check (§14).** Approved claims whose `class_uri` falls
    under another data-domain's `data-domains.yaml` `uris` prefix block with
    `ownership_conflicts` unless an `ownership_override` (owner + rationale) is
    present.
  - **passthrough-review check (§11.2).** High-use passthrough claims (evidence
    across ≥2 source systems, a powerbi measure/slicer/filter/hierarchy/join/fk/
    sample_signal evidence type, or any evidence carrying a `measure`) that are not
    yet `passthrough_reviewed` warn with `passthrough_review`.
  - **Shared-conformed-dimension escape hatch.** Cross-file same-URI approved
    claims now route to a `shared_dimensions` warning instead of the
    `duplicate_approved` block when either claim carries an `ownership_override`.
- **Claim Registry schema fields (DD-EL-6).** New `ReferenceData`
  (`authority_system` / `code_system` / `key` / `scd_type`), `Deviation`
  (`reason` / `owner` / `gap_request`), and `OwnershipOverride`
  (`owner` / `rationale`) dataclasses, plus `Claim` fields `reference_data`,
  `mdm_anchor`, `deviation`, `ownership_override`, and `passthrough_reviewed`. All
  are omitted from serialized output when default (byte-stable golden output
  preserved) and preserved across re-runs by `merge_preserving_decisions`.
  `validate_registry` gains structural checks (warns on `reference_data`/`mdm_anchor`
  set on a non-`reference_data` claim; errors on an `ownership_override` missing owner
  or rationale).
- **`check-claims` flags.** `--no-mdm-anchor` and `--no-ownership` skip the
  respective gates.

## [4.2.0] — 2026-06-15

### Added
- **`derive-claims` command (DD-EL-5).** A **deterministic, AI-free** aggregator
  that merges/enriches the Claim Registry (`model/claims/{domain}-claims.yaml`)
  into `proposed` candidate claims, reducing hand-authoring. The
  semantically-hard LLM work already happened upstream in `analyse-sources`
  (affinity) and `propose-alignment` (column→property); `derive-claims` is the
  deterministic merge/enrich layer. It joins **five evidence streams**
  deterministically on `(system, table[, column])` and ref_class/ref_property
  names — the existing claims registry, `analyse-sources` affinity,
  `import-tmdl` concept-mapping, SKOS mappings, and sample-derived signals —
  attaching **multiple `evidence_sources` per claim**. All derived/new claims are
  `status: proposed` and are **never** auto-`approved` (the C4 guard); human
  decisions survive re-runs via the existing `merge_preserving_decisions()`. For
  parity with the AI commands it reuses `--max-workers` (default 8) and `--force`
  (`_concurrency` / `_cache`), but **deliberately omits the cost banner** because
  nothing is billed. A future opt-in `--llm-reconcile` flag (LLM tie-breaking /
  rationale synthesis, with a cost banner) is **deferred** to a later slice.

## [4.1.0] — 2026-06-15

### Added
- **`claims-to-silver-ext` command (DD-EL-4).** Deterministically generates/
  regenerates a domain's external `owl:imports` set and per-class
  `kairos-ext:silverInclude` assertions in `{domain}-silver-ext.ttl` from the
  **approved imported** class claims in `model/claims/{domain}-claims.yaml`
  (realizing A1 — claims drive imports). `--check-only` reports drift and exits 1
  without writing.
- **Foundation/thin-ontology scaffold (A2-lite).** New
  `scaffold/ontology-hub/model/ontologies/foundation.ttl.template`; the starter
  domain ontology now `owl:imports` the thin `_foundation` ontology.

### Changed
- **`check-claims` claim↔projection sync gate (DD-EL-4).** `check-claims` now
  blocks when a domain's `owl:imports` / `silverInclude` surfaces drift from its
  approved claims, or when a `silverIncludeImports` bulk-bypass flag is present.
  Add `--no-extension-sync` to skip the gate.
- **Projector claim-authority gate for silver/dbt/powerbi (DD-EL-4).** For those
  targets, if `model/claims/{domain}-claims.yaml` exists, projection of that domain
  fails (records a projection error) when the claim-derived imports/includes are out
  of sync. Retains the DD-021 no-bypass guarantee but makes materialization
  claim-driven.

## [4.0.0] — 2026-06-15

### Changed (BREAKING)
- **Claim Registry replaces the alignment YAML (DD-EL-1).** The evidence-led
  cutover retires `{domain}-alignment.yaml` in favour of a single governed
  `model/claims/{domain}-claims.yaml` registry as the source of truth for which
  concepts are approved to materialize.
  - `propose-alignment` now emits candidate (`proposed`) claims into the registry
    (default output `model/claims/`) instead of alignment YAML, preserving
    table/column coverage, the freshness digest, and custom-column disposition
    triage. Re-runs merge over existing claims without clobbering human decisions.
  - **New `check-claims` gate** replaces **both** `check-alignment` and
    `check-source-coverage` (now removed). It verifies, per affinity domain, that a
    `{domain}-claims.yaml` exists, is structurally valid, covers every affinity
    table, and is fresh; it blocks on cross-file duplicate `approved` claims and
    (unless `--no-source-coverage`) on unmapped tables, and — with `--strict` —
    on undecided (`proposed`) claims. It rejects any leftover `*-alignment.yaml`
    with a migration message (no dual path).
  - **New `migrate-claims`** command performs the one-way
    `{domain}-alignment.yaml` → `{domain}-claims.yaml` conversion.
  - Design/help skills updated to the claims workflow (`check-claims`,
    registry-based curation).

### Removed (BREAKING)
- `check-alignment` and `check-source-coverage` CLI commands (folded into
  `check-claims`).
- Alignment-YAML reader machinery in `alignment_coverage` (the module now provides
  only the reused affinity/freshness primitives and triage heuristics).

## [3.24.1] — 2026-06-14

### Changed
- **Alignment `--high-accuracy` now prefers `gpt-5.4` (non-reasoning).** The
  `propose-alignment` high-accuracy tier dropped from `gpt-5.5` to `gpt-5.4`:
  alignment is deterministic closed-vocabulary matching, so a non-reasoning model
  is preferred (lower latency/cost, no reasoning-model overhead). gpt-5.4 is also
  the recommended `KAIROS_AI_ALIGNMENT_MODEL` in the scaffold `.env.example`.

### Fixed
- **Foundry AI provider: extras packaging + API-key auth crash (DD-078).** Two
  related defects that made the Microsoft Foundry provider unusable for
  `analyse-sources` / `propose-alignment`:
  - The user-facing extras (`azure`, `foundry`, `flatfile`, `parquet`) were declared
    **only** under `[dependency-groups]`, so the documented
    `pip install kairos-ontology-toolkit[foundry]` resolved nothing (extras are not
    written into wheel metadata). They are now also declared under
    `[project.optional-dependencies]`; a parity test
    (`tests/test_packaging_extras.py`) keeps the two in sync.
  - `_create_foundry_client` passed an `AzureKeyCredential` (from
    `AZURE_FOUNDRY_API_KEY`) to `AIProjectClient`, but azure-ai-projects 2.x
    `get_openai_client()` requires a token credential (`get_token`) — crashing every
    table to `mdm`/0.00. The Foundry path now prefers `DefaultAzureCredential` and,
    when an API key is set, tries it then **falls back to `DefaultAzureCredential`**,
    with a clear error if neither works.
- **dbt cross-table warning conflated inherited vs own props (issue #181, DD-079).**
  For a subtype claimed as its own silver table (`Child ⊂ Parent`), every inherited
  parent property mapped on the parent's table fired a `Cross-table reference … may
  need a JOIN` ⚠️ warning — even though those columns are excluded from the subtype
  model **by design** — producing 40+ noise warnings per subtype. Cross-table
  properties are now classified by their **direct** `rdfs:domain`: **own** props
  (declared on the subtype) still emit a per-column ⚠️ warning (genuine JOIN
  candidates, own-precedence), while **inherited** props are reclassified
  warning → **info** and collapsed into one consolidated ℹ️ note per class (surfaced
  under a `## ℹ️ Info` section of the dbt session log). WARNING-log volume and report
  warning counts drop accordingly.

## [3.24.0] — 2026-06-14

### Added
- **Custom-column triage hardening (issue #182, DD-082).** A set of deterministic
  / confidence-gated fixes to `propose-alignment` and the `check-alignment` gate
  that make the Checkpoint-3b custom-column triage reliable at scale (hundreds of
  custom columns) — **no new AI cost** (DD-077):
  - **Confidence-gated suggestions (WS1).** An unmatched custom column only keeps a
    `suggested_property` when the model is confident enough
    (`--custom-confidence-floor`, default `0.5`); below the floor it is dropped to
    `null` rather than emitting a confident-but-wrong guess. A catch-all detector
    downgrades any property proposed for ≥3 dissimilar columns (the
    `stageCode`/`customsID` sink problem).
  - **Two-tier auto-disposition (WS2).** Every custom column gets an advisory
    `recommended_disposition` (`skip` / `silver-passthrough` / `""`). A final
    `disposition` is auto-filled **only** for narrow, near-zero-ambiguity
    audit/technical columns (`created_on`, `tenant_id`, surrogate `id`, …), stamped
    `disposition_source: heuristic`. Generic vendor slots (`CFSTRING33`, …) are
    *recommended* `silver-passthrough` but stay undisposed (still block under
    `--strict`) unless `check-alignment --accept-heuristics` is passed.
  - **Reference-rollup integrity (WS4).** Matched properties are validated against
    the class's real reference-model property set; coverage is capped at 100% and a
    `hallucinated_properties` sample is surfaced instead of silently clamping.
  - **Hallucinated-anchor detection (WS6).** Generation records a non-clean
    `ref_class_status` (`fallback` / `rejected` / `unmatched`) + `rejected_ref_class`
    so a force-fit or unanchored table is visible without re-running the LLM. A new
    `check-alignment --check-anchors` gate re-validates `ref_class` anchors against
    the real installed reference-model class set and blocks on hallucinated anchors
    (e.g. a `Booking` class that exists in no reference model).
  - **Prompt hardening (WS7).** For an unmatched column the model now emits
    `alignment: custom` + `ref_property: null` (never an invented camelCase name),
    may return `ref_class: null` when no class fits, and is steered away from
    catch-all sinks and >100% over-mapping.
  - **Opt-in high-accuracy preset (WS8).** `propose-alignment --high-accuracy`
    selects a higher-tier model for the accuracy-sensitive class-anchoring step;
    mini stays the default and the cost banner notes alignment is accuracy-sensitive.
  - **Per-role LLM endpoints.** The two pre-modeling steps can now use independent
    endpoints/models via `KAIROS_AI_AFFINITY_*` and `KAIROS_AI_ALIGNMENT_*`
    (`_ENDPOINT` / `_KEY` / `_MODEL`): keep `analyse-sources` on a cheap mini
    endpoint while pointing `propose-alignment` at a stronger model/deployment. A
    role with no override falls back to the global provider. Documented in both
    `.env.example` scaffolds.
  - **Disposition preservation on regeneration (WS9).** Re-running
    `propose-alignment` (including `--force`) no longer wipes a modeler's
    hand-triaged dispositions: human-owned `disposition`/`note` values are merged
    back by `(system, table, column)`; only heuristic-owned fields are recomputed.
  - **Schema/cache/version contract (WS0).** An explicit `algorithm_version` is
    emitted and folded into the per-table and domain cache keys, so the hardened
    prompt/heuristics take effect instead of serving stale cache. Fixes a latent bug
    where the freshness hash was written as `source_sha256` but read as
    `affinity_sha256` (dead domain-level cache skip).

### Notes
- Cross-domain candidate tagging and a non-LLM repair path for existing large
  alignment YAMLs were scoped under issue #182 but deferred to follow-up issues.

## [3.23.0] — 2026-06-14

### Added
- **Sample-grounded mapping evidence (DD-075).** `propose-alignment` now emits
  masked `example_values` for each mapped column **by default** (real source
  sample values are the strongest mapping evidence), plus an advisory
  `transform_compat` note when a proposed numeric/bool `CAST(...)` looks
  incompatible with the sampled values (e.g. *"2/5 sample values are
  non-numeric — CAST may NULL/fail"*). A shared `_samples` policy module is the
  single source of truth for PII detection and masking: PII columns (by name,
  mapped property, `gdpr_protected`, or value shape) are **always masked**
  (`jo***@***.com`) and never enumerated. Both fields are additive — no
  `schema_version` bump. Suppress with `--no-sample-values`. The
  `kairos-design-mapping` skill gains a **mandatory** masked Examples column in
  its Phase 2 proposal table and a privacy rule (never copy raw values into
  committed TTL/comments/session logs).
- **`suggest-shapes` — draft SHACL from source profiling (DD-076).** New
  deterministic CLI command that builds a **DRAFT** SHACL file from bronze
  profiling metadata: `sh:datatype` always; `sh:pattern` when one format matches
  all samples; `sh:minCount 1` from `nullable:false`; `sh:in` only when a
  reliable `kairos-bronze:distinctCount` ≤ `--enum-distinct-max` fully matches
  the sampled distinct set (never for PII). Output defaults to
  `output/shapes-draft/<name>.ttl` — **outside** `model/shapes/` and with a
  `.ttl` (not `.shacl.ttl`) suffix — so the validator does not auto-load drafts;
  the user reviews and promotes them. Surfaced via the `kairos-execute-validate`
  skill (skill-gated; set `KAIROS_SKILL_CONTEXT=1`).

### Fixed
- **dbt merge: explicit FK mapping no longer leaks across sources (issue #178).**
  When two bronze sources merged into one silver entity and only one source
  declared an **explicit** SKOS FK column-mapping (`bronze:<col> skos:exactMatch
  <fkProperty>`), the dbt projector applied that mapping to *every* source's
  per-source staging view — producing a phantom `left join` and a join predicate
  referencing a column the other source does not have. `_resolve_fk_source_column`
  now scopes the explicit-mapping branch to the current source's columns (using a
  None sentinel so legacy non-merge callers are unaffected, and a physical-column
  fallback so synthetic/composite/transform-only mapping subjects are still
  attributed to the declaring source). Non-declaring sources emit a typed
  `CAST(NULL AS …)` placeholder; the declaring source keeps its real join.
- **dbt silver: table mapping to an unprojected class is no longer silently
  dropped (issue #179).** A `skos:exactMatch` table mapping whose target class is
  not in the projected set (e.g. an unclaimed imported subtype —
  `silverIncludeImports=false` and no `silverInclude`) was discarded with no
  model and no warning. `_gen_silver_models` now detects such orphaned targets and
  either **folds** their source(s) onto a projected discriminator parent (when one
  exists) or emits a loud warning naming the table and class, so the contribution
  is never lost without notice.

## [3.22.0] — 2026-06-14

### Fixed
- **Silver/dbt merge pattern no longer generates invalid/lossy `UNION ALL`
  (issue #175).** When two or more bronze sources merged into one silver entity
  with non-identical mapped column sets (the normal master-data case), the dbt
  projector produced broken SQL: the union column list was taken from the first
  source only, per-source views projected only their own mapped columns (so the
  `UNION ALL` branches had mismatched column counts), and FK `_sk` columns were
  silently dropped. The merge pattern now builds a **canonical column superset**
  across all sources, projects every per-source staging view to that superset
  with explicitly-typed `CAST(NULL AS <type>)` pads for unmapped columns, and
  emits **explicit per-branch column lists** (no `select *`) so the `UNION ALL`
  is positionally consistent. A loud warning fires when a source does not map a
  natural-key column (which would yield NULL/duplicate surrogate keys).
- **Silver/dbt FK auto-inference no longer mis-resolves same-range FK properties
  (issue #174).** When a class declared two or more FK object properties whose
  natural-key signature was identical (e.g. `hasBillingAddress` and
  `hasShippingAddress`, both ranged on `Address`), NK-based auto-inference would
  silently resolve an *unmapped* role to the *mapped* sibling's source columns,
  producing a semantically wrong join with no warning. The dbt projector now
  detects FK targets that share a natural-key signature (keyed on resolved NK
  property URIs, so discriminator-folded subtypes and `silverForeignKeyOn`
  redirects are covered too) and **disables auto-inference** for them — they are
  resolved only from explicit SKOS mappings; unmapped roles emit a NULL
  placeholder plus an explicit ambiguity warning directing the user to add an
  explicit mapping. Correctly-mapped roles are unaffected.

### Changed
- **Foreign keys are now resolved in the merge pattern (issue #175).** Because
  each per-source staging view is single-source, the existing single-source FK
  machinery now runs *inside* each view: the source that maps a FK emits a real
  `left join {{ ref(target) }}` and the resulting `_sk` column, while sources
  that don't map it emit a NULL pad. The FK `_sk` flows through the `UNION ALL`
  as an ordinary canonical column — no union-level join, no hidden columns, no
  silent drop. The union model itself performs no joins. See DD-074.

## [3.21.0] — 2026-06-14

### Added
- **`kairos-ext:silverExclude` annotation (DD-073, issue #172).** A new boolean
  class annotation that suppresses a class's silver table while keeping it in the
  ontology for inheritance/semantics. It overrides `silverInclude` /
  `silverIncludeImports`; descendants still inherit the excluded class's
  properties (it is treated as an unclaimed / cross-domain FK target). The
  projector warns when a materialised class subclasses or FK/junctions to an
  excluded class. Declared in `scaffold/kairos-ext.ttl`; documented in the
  `kairos-design-silver` skill.
- **Automated projection session-log archival (DD-071 amendment).** Each
  projection run now moves any pre-existing per-domain logs
  (`projection-{domain}-*.md`, `dbt-{domain}-*.md`) for the in-scope domains into
  `.sessions-projection/_archive/` before writing the new logs (collision-safe,
  never deleted), mirroring the design-session `_archive/` convention.
  `kairos-diagnose-status` ignores the `_archive/` subfolder for
  `.sessions-projection`.

### Fixed
- **Transitive S3 discriminator folding (DD-073, issue #172).** Discriminator
  folding now walks `rdfs:subClassOf` through **unclaimed** intermediate classes
  and folds a subtype into the nearest **claimed** discriminator ancestor, instead
  of inspecting only the direct parent. Properties of the unclaimed intermediates
  fold into the parent table too (previously they were silently dropped).
  `folded_subtypes` is now URI-keyed for namespace safety, traversal is
  deterministic, and conflicting strategies among same-depth claimed ancestors
  emit a warning. Single-level (depth-1) folding behaviour is unchanged.

## [3.20.0] — 2026-06-14

### Added
- **Provenance comment header on toolkit-generated TTL (DD-072).** Files the
  toolkit writes itself now begin with a small Turtle `#`-comment block stamping
  the toolkit version, a UTC generation timestamp, the generator name and an
  edit-policy note. Applied to source vocabulary (`*.vocabulary.ttl`), the SKOS
  glossary (`*-glossary.ttl`), and the scaffold ontologies (`_master.ttl`,
  per-domain `{domain}.ttl`) written by `init` / `new-repo`. The header is plain
  comments only — it adds no RDF triples, so it never affects parsing, SHACL
  validation, merge, or projection. A new shared helper
  (`kairos_ontology._provenance.provenance_comment` / `prepend_provenance`) is
  exposed and idempotent (regenerating never stacks headers); the design skills
  (`kairos-design-domain`, `kairos-setup-config`) document the convention for
  hand-authored ontology/SHACL files.

## [3.19.0] — 2026-06-14

### Added
- **Cross-module candidate properties in `propose-alignment` (DD-070, issue #166).**
  The actual fix for the limitation #167/#168 only *detected*: a column whose true
  reference-model match lives in a sibling/shared accelerator module (e.g. a shared
  `Address`, `PaymentTerms`, or `currency`) could not be matched and was force-fit
  onto an unrelated home-domain scalar. A new opt-in `--cross-module` flag (requires
  `--accelerator <name>`) widens the **STEP-2 property candidate pool** to the whole
  accelerator while keeping **STEP-1 table classification home-only** (two separate
  pools). Each matched non-home class is tagged with its owning `ref_module`
  (+ `ref_module_uri`, `belongs_to_domain(s)`) and accumulated into a separate
  `cross_module_matches` section that tells the modeler which module to import. The
  home `reference_rollup` is unchanged. Classes carry a stable `ref_class_id`
  (`<module>:<Class>`) and are deduped by URI so same-named classes across modules
  stay distinct. Freshness/cache keys include a cross-module params signature
  (`alignment_params_sha256`) so a cross-module run is never skipped after a prior
  home-only run, and the unbounded full-inventory retry is disabled in cross-module
  mode (cost guard). **Default output (no `--cross-module`) is byte-identical.**
- **Business-discovery glossary marked non-authoritative (DD-071).** Every generated
  `{company}-glossary.ttl` `skos:ConceptScheme` is now stamped with an `rdfs:comment`
  + `skos:editorialNote` disclaimer making explicit that the glossary is initial
  inspiration only — not kept in sync with the domain ontology, and its
  `seeAlso`/`relatedMatch` links are not reconciled during modeling.

### Changed
- **Design-skill session logs are archived, not overwritten, on "Start fresh" (DD-071).**
  When a user starts a fresh design session, existing `.sessions-design/*.md` logs are
  moved to `ontology-hub/.sessions-design/_archive/` before the new log is created
  (never silently deleted). `kairos-diagnose-status` ignores `_archive/` when locating
  the most recent session log.

## [3.18.0] — 2026-06-14

### Added
- **propose-alignment plausibility & address review flags (DD-069, issues #167/#168).**
  A deterministic, no-LLM review pass now flags structurally implausible column
  maps for human review instead of letting them pass silently. Each flagged column
  in `{domain}-alignment.yaml` gains `review: true` + a `review_reason`
  (emitted only when a rule fires, so default output is unchanged). Rules cover:
  address-part columns (`street`/`postalCode`/`addressLine*`/qualified
  `city`/`zip`) force-fit onto non-address party scalars (#167); boolean source →
  identity/name property; financial-flavoured column → generic identity property;
  and no-name-token-overlap + low-confidence maps (#168). `check-alignment` collects
  these into a new **report-only** "flagged for review" section — it never blocks
  (separate from the #164 custom-column `--strict` gate). The column mapping is
  kept (only flagged), and no cross-module `reference-data#Address` target is
  hardcoded (that remains #166's scope).

## [3.17.0] — 2026-06-14

### Added
- **Custom-column triage in domain modeling (DD-068, issue #164).** Source-evidenced
  columns with no reference-model property are no longer silently dropped before
  mapping. `propose-alignment` now writes a `disposition` field (`model` /
  `silver-passthrough` / `skip`; `null` until triaged) on each `custom_columns`
  entry. `check-alignment` surfaces and classifies these columns (business vs likely
  operational/audit) and gains a `--strict` flag that **blocks** until every custom
  column is dispositioned (default warns; `--warn-only` overrides `--strict`). The
  `kairos-design-domain` skill now requires every custom column to appear in the
  Source Evidence Table, records a per-column disposition back into the alignment
  YAML in Checkpoint 3b, runs `check-alignment --strict` at the completion gate, and
  clarifies that "Reference Model Enforced" governs class-hierarchy reuse — not
  "add nothing local".

## [3.16.1] — 2026-06-14

### Added
- **Release-management guide + policy (DD-067).** New `docs/dev/RELEASING.md` documents
  SemVer discipline, the "support only the latest line" policy, and a bugfix decision
  tree that keeps patches out of feature releases via ephemeral `hotfix/x.y.z`
  branches cut from the release tag (with a mandatory back-merge to `main`).
  `CONTRIBUTING.md` gains a branch-naming table and the `kairos-toolkit-ops` skill
  links to the guide. Docs/process only — no tooling or CI changes.

### Removed
- **PyPI publishing scaffolding removed from release CI (DD-066).**
  The dormant (commented-out) `publish-pypi` job and the unused `id-token: write`
  permission are removed from `.github/workflows/release.yml`. The toolkit was never
  published to PyPI; it is distributed via GitHub Releases (wheel + sdist assets) and
  consumed through git-tag / wheel-URL pins. README and skills updated to drop the
  PyPI badge and `pip install kairos-ontology-toolkit` instructions in favour of the
  git-tag install. No behavioural change to the `build` / `github-release` jobs.

## [3.16.0] — 2026-06-14

### Added
- **Concurrent, cached AI pre-modeling for `analyse-sources` and `propose-alignment` (DD-065).**
  Both commands now parallelize their per-table LLM calls with a bounded thread pool
  (`--max-workers`, default `8`; `--max-workers 1` reproduces the old serial path),
  collapsing large-hub runs from tens of minutes to a few. Two-level incremental
  caching skips unchanged work: a domain-level skip via the existing `affinity_sha256`
  freshness hash plus a schema-neutral per-table sidecar cache under
  `<analysis-dir>/.cache/`. `--force` bypasses both cache layers. Both commands now
  print a prominent cost banner before running (showing table count × workers and
  recommending `gpt-5.4-mini`), suppressed by `--quiet`. Rate-limit (HTTP 429) errors
  are retried with exponential back-off.

### Changed
- **`propose-alignment` anchors class selection on the affinity `likely_entity` (DD-065).**
  The prompt now asks the model to confirm the affinity-derived entity rather than
  re-derive it, and falls back to `likely_entity` when the model returns an invalid
  class (previously blanked). Defaults retuned for fewer redundant calls:
  `--max-prompt-classes` `18`→`12`, `--retry-min-confidence` `0.75`→`0.6`,
  `--retry-min-mapped-ratio` `0.55`→`0.4`.

## [3.15.5] — 2026-06-14

### Fixed
- **AI provider `.env` auto-loading now resolves repo-root settings when running from `ontology-hub/`.**
  AI-dependent commands could miss credentials when only repo-root `.env` existed.
  Dotenv discovery now checks cwd, hub dir, and repo root deterministically.

### Changed
- **`propose-alignment` retry + prompt payload optimized further for runtime.**
  Full-inventory retry now triggers only when shortlist output is truly weak
  (both low confidence and low mapped-column ratio, or missing class). Source
  sample values in prompts are also compacted by filtering noisy ID-like values
  and clipping long text, reducing token payload while preserving semantic signal.

## [3.15.4] — 2026-06-13

### Changed
- **`propose-alignment` prompt payload is now token-optimized with quality safeguards.**
  Per table, the first pass now uses a deterministic shortlist of reference classes
  (`--max-prompt-classes`, default `18`) instead of always sending the full class
  inventory. If the shortlist result is weak, the command retries once against the
  full inventory using configurable gates
  (`--retry-min-confidence`, `--retry-min-mapped-ratio`). This keeps default behavior
  quality-safe while reducing runtime/token cost on large domains.

## [3.15.3] — 2026-06-13

### Fixed
- **`validate` / `project` now resolve paths from the hub root, not the CWD (DD-064).**
  Both commands hardcoded option defaults relative to the current directory
  (`ontology-hub/model/...`, `ontology-hub/output`), assuming you ran them from the
  repo root. Run from inside `ontology-hub/` (or in a hub without a `shapes/` dir),
  `validate` hard-errored with Click exit 2 ("Path '…' does not exist") before
  running, and `project` wrote artifacts to a doubly-nested
  `ontology-hub/ontology-hub/output/`. Defaults are now resolved via
  `find_hub_root()` (like `coverage-report`), so both work whether invoked from the
  repo root or inside the hub; `--shapes` is optional (SHACL skipped if absent);
  catalog auto-detection is hub-root-aware. Explicit `--ontologies`/`--shapes`/
  `--output`/`--catalog` still win. Note: this prevents *future* nesting — a hub
  with an existing stray `ontology-hub/ontology-hub/output/` should delete it and
  regenerate.

### Added
- **Deterministic SKOS glossary builder (DD-063).** New read-only, AI-free CLI
  command `kairos-ontology build-glossary` reads the confirmed business-discovery
  extraction files (`businessdiscovery/_extractions/*.extraction.yaml`) and emits
  the company glossary overlay (`businessdiscovery/{company}-glossary.ttl`) as a
  SKOS `ConceptScheme` via `rdflib`. It aggregates `extracted_terms` into
  deduplicated concepts (grouped by `linked_iri`, else `prefLabel`), maps
  `linked_iri` to `rdfs:seeAlso` (or `skos:relatedMatch` when a term sets
  `link_relation: relatedMatch`), and auto-detects the company namespace from the
  hub `README.md`. The `kairos-design-discovery` skill now calls this command
  instead of hand-writing a one-off `rdflib` script each run. The domain ontology
  is never modified (overlay only).

## [3.15.2] — 2026-06-13

### Fixed
- **`update`/`--upgrade` no longer scaffolds a second hub from a subdirectory (DD-062).**
  The command now resolves the hub via an upward-walking `find_managed_root()`
  (anchored on the `[tool.kairos]` / toolkit pin or the managed
  `.github/copilot-instructions.md` marker) and auto-re-roots to it with a notice,
  instead of trusting `Path.cwd()`. Running it inside a content subdirectory (e.g.
  `ontology-hub/`) now updates the real repo-root hub. Fabricating a `pyproject.toml`
  is restricted to positively-detected (legacy) hubs; in a non-hub directory the
  command now hard-errors with guidance instead of manufacturing a spurious hub.


## [3.15.1] — 2026-06-13

### Added
- **Deterministic source-coverage gates (DD-061).** Two new read-only, AI-free CLI
  commands close the asymmetry where reference-model coverage was hard-gated
  (`check-inventory`) but source coverage was only advisory.
  `kairos-ontology check-alignment` (pre-modeling) verifies that every data domain
  in the affinity reports has a `{domain}-alignment.yaml` from `propose-alignment`
  that **covers all** the domain's tables and is **fresh** — blocking on
  *missing / incomplete / stale*. `kairos-ontology check-source-coverage`
  (pre-silver) verifies that every affinity-assigned source table is mapped to a
  domain entity (a SKOS match on the bronze table or one of its columns) — blocking
  on any unmapped table. Both hard-block by default with a `--warn-only` escape
  hatch and stay out of the soft skill-gate set (like `check-inventory`).
  `check-alignment` is wired as a hard pre-flight in `kairos-design-domain`
  (Step 0a.2); `check-source-coverage` as a mandatory pre-flight before silver in
  `kairos-design-silver` and `kairos-execute-project`.

### Changed
- **`propose-alignment` output is versioned and carries a freshness hash (DD-061).**
  Alignment YAML `schema_version` is bumped 1 → 2 and now stores a `source_sha256`
  digest of the affinity `(system, table)` set so `check-alignment` can detect
  staleness. Pre-existing v1 alignment files remain valid and are reported as
  *unverifiable* (warn, non-blocking) until regenerated.
- **`pypdf` and `pyarrow` are now core dependencies.** Business-discovery document
  parsing (DD-060) needs to extract text from PDF artifacts in
  `.import/businessdiscovery/`, and Parquet source import needs `pyarrow`. Because
  hubs install the toolkit as a bare wheel, optional extras don't reach them — so
  both libraries are promoted to core `[project.dependencies]` and now arrive
  automatically on `update --upgrade`. `pyarrow` remains exposed via the `[parquet]`
  extra for backward compatibility. (pypdf: BSD-3-Clause; pyarrow: Apache-2.0 —
  both Apache-2.0-compatible.)

## [3.15.0] — 2026-06-13

### Added
- **Per-document extraction tracking for business discovery (DD-060).** The
  `kairos-design-discovery` skill now writes one extraction file per processed
  document to `ontology-hub/businessdiscovery/_extractions/{slug}.extraction.yaml`,
  recording the document's `source_sha256`, a summary, the extraction strategy, and the
  extracted terms — so you always know **what was extracted from which document**. A new
  deterministic, AI-free command `kairos-ontology discovery-status` scans
  `.import/businessdiscovery/` and reports which documents are **new**, **changed**, or
  **up to date** (hash-based, mirroring `check-inventory`); `--strict` exits non-zero
  when there is work to do. Reruns now reprocess only new/changed documents instead of
  re-reading everything. New hubs get a `businessdiscovery/_extractions/` folder + README
  via `init`/`new-repo`.

### Changed
- **Modeling now gates on source analysis and unpacks reference models first
  (DD-058).** `kairos-design-domain` gains a pre-flight branch (**P2b**) that detects
  imported-but-unanalysed sources (`integration/sources/_analysis/` has no
  `*-affinity.yaml`) and auto-hands off to `kairos-design-source` Phase 4 before any
  class design — closing a gap where "start modeling" could skip the data-first source
  analysis. `kairos-design-source` Phase 4 now makes `generate-inventory` (+
  `check-inventory`) a required up-front step run **before** the AI `analyse-sources`
  pass (cheap/AI-free first), which also de-risks the Step 0c.1b / DD-047 inventory gate.
  The Source-Completeness Checkpoint is renumbered P2b → **P2c**.
- **Modeling pre-flight adds a Discovery-Completeness gate (DD-059).**
  `kairos-design-domain` now checks for business-discovery artifacts
  (`businessdiscovery/*.ttl`, `.sessions-design/businessdiscovery-*.md`) in a new **P1b**
  checkpoint that fires **independent of source state** — so a hub with imported sources
  but no discovery context is now prompted to run `kairos-design-discovery` first
  (recommended, not hard-blocked). Step 2a is upgraded from "read if present" to an
  explicit gate. Closes a gap where discovery (the canonical lifecycle start) was only
  surfaced in the empty-sources branch.

### Fixed
- **Inventory class entries now include their canonical `uri` (schema 1.1).**
  `generate-inventory` previously emitted each class with `name`/`label`/`comment`/
  `properties`/`specializations` but no top-level URI, forcing consumers to reconstruct
  IRIs from the domain namespace + class name. Each class now carries a `uri` field
  (matching the `class_uri` already present on specializations). `INVENTORY_VERSION`
  bumped `1.0` → `1.1`; regenerate inventories with `kairos-ontology generate-inventory`
  to pick up the field.
- **Windows `update --upgrade` no longer fails the managed-file refresh with a
  file-lock error (DD-057).** The running `kairos-ontology.exe` locks its own
  executable, so the previous synchronous re-exec could not `uv sync` to the new
  version. The upgrade now schedules a **detached** helper that waits for the current
  process to exit, then runs `uv sync` + `kairos-ontology update` automatically. A
  transcript is written to `.kairos/upgrade-refresh.log`. Non-Windows behaviour is
  unchanged.

## [3.14.0] — 2026-06-13

### Changed
- **Business discovery now materializes the full reference-model breadth and links
  glossary terms to reference-model IRIs (DD-055).** The `kairos-design-discovery`
  skill gains a read-only "Phase 1a" that runs `generate-inventory` over the
  reference models first, makes Phase 1 research explicitly company-wide, and
  resolves glossary IRIs in priority order hub → reference-model → flag-as-novel.
  Reruns are idempotent: previously-flagged terms are re-linked to hub IRIs as each
  domain is modeled, so terminology is no longer lost across domains.
- **Hub folders relocated & renamed (new hubs only, DD-056).** The business
  glossary folder moved from `ontology-hub/model/glossary/` to
  `ontology-hub/businessdiscovery/`, and the materialized inventory folder from
  `ontology-hub/model/inventory/` to `ontology-hub/referencemodels-unpacked/`.
  `init`/`new-repo` scaffolding, `generate-inventory`/`check-inventory` default
  paths, and all design skills now use the new locations. Existing hubs are **not**
  auto-migrated — move the two folders manually (or recreate the inventory with
  `kairos-ontology generate-inventory`).
- **CHANGELOG is now enforced as part of the release process.** Previously
  `release.yml` generated GitHub Release notes purely from merged PRs
  (`--generate-notes`) and never consulted or updated `CHANGELOG.md`, so the file
  silently drifted (e.g. `3.10.x`/`3.11.x` shipped with no entry). Now
  `release.yml` fails a tagged GA release whose version has no `## [X.Y.Z]`
  `CHANGELOG.md` section, and `version-check.yml` fails a PR that bumps
  `__version__` without the matching entry. Pre-releases (`rc`/`beta`/`alpha`) are
  exempt. The `kairos-toolkit-ops` release steps now include promoting
  `[Unreleased]` to a dated heading.

### Fixed
- **Reference-model inventories are now namespaced by their owning model
  (DD-054).** `generate-inventory` previously named every inventory from the TTL
  stem (`{stem}-inventory.yaml`), so same-named modules across reference models
  (e.g. `party.ttl` in BSP, DCSA, IMO, MMT, TIC, WCO) collapsed into one
  last-write-wins file and silently dropped five models' classes (`TradeParty`,
  `MaritimeParty`, `TransportParty`, …); `documents`, `locations`, `events`, and
  `equipment` were affected too. Reference-model files are now written as
  `{model}-{stem}-inventory.yaml` (e.g. `bsp-party-inventory.yaml`) via a shared
  `inventory_filename()` helper used by both `generate-inventory` and
  `check-inventory`. This also fixes the DD-047 staleness **deadlock** (colliding
  stems reported as permanently `STALE` with no way to clear them) and the glitch
  where a stem appeared in both the `ok` and `stale` lists. `generate-inventory`
  gains a default `--prune` that removes inventory files no longer produced by any
  source (self-heals legacy stem-named files). Re-run `generate-inventory` and
  commit the regenerated `model/inventory/`.
- **Reference-model auto-detection now consistently uses the repo-root
  `ontology-reference-models/` directory.** `generate-inventory` and
  `check-inventory` previously defaulted to the non-existent
  `model/reference-models/`, so the `kairos-design-domain` pre-flight silently
  found zero reference models. All four commands (`generate-inventory`,
  `check-inventory`, `analyse-sources`, `coverage-report`) now share a single
  `_resolve_ref_models_dir()` resolver that prefers the repo-root location
  (legacy `model/reference-models/` kept as a last-resort fallback). Help text
  and the `kairos-toolkit-ops` skill corrected accordingly.

### Added
- **Import commands auto-write an import-results session file.** `import-flatfile`
  and `import-source` now write a machine-generated
  `import-{system}-{YYYY-MM-DD}.md` to `ontology-hub/.sessions-design-import/`
  (created at `init`/`new-repo`), capturing tables, columns, change report, and
  enrichment using a template consistent with the existing session files. The
  write is best-effort and skipped when no hub root is detected. (DD-052)
- **CLI soft skill-gate.** Skill-managed commands (`validate`, `project`, `init`,
  `new-repo`, `migrate`, `update`, `update-refmodels`, `import-source`,
  `import-flatfile`, `generate-staging`, `analyse-sources`, `init-dataplatform`)
  now emit a loud stderr warning redirecting to the owning Copilot skill when run
  directly, then still run (soft gate). Set `KAIROS_SKILL_CONTEXT=1` to silence
  it; gated skills set it automatically. (DD-053)

### Changed
- **Renamed the business-discovery artifacts folder `.imports/` → `.import/`**
  (singular). `kairos-ontology init` / `new-repo` now create
  `.import/businessdiscovery/` at the repo root; the dotless scaffold source
  folder is `scaffold/import/`. Skills, docs (DD-048), and tests updated. (DD-048)

## [3.13.2] — 2026-06-13

### Changed
- **Start-modeling now auto-hands off to the lifecycle start, and the
  source-completeness check is always-on.** Refines v3.13.1 (DD-051): on a fresh
  hub, "start modeling" auto-routes to `kairos-design-source` (offering
  `kairos-design-discovery`) before domain modeling. When sources already exist,
  the `kairos-design-domain` skill now poses a **mandatory Source-Completeness
  Checkpoint on every modeling start** — including the first pass — asking whether
  additional/other sources should be imported first (previously only on
  restart/extension). (DD-051)

## [3.13.1] — 2026-06-13

### Changed
- **"Start modeling" now points to the lifecycle start.** The Copilot instructions
  and the `kairos-design-domain` skill now frame domain modeling as a mid-lifecycle
  step (`discovery → source → domain → …`): on a fresh hub, "start modeling" routes
  the user to discovery + source import first. The modeling skill gains advanced
  pre-flight checks — a *fresh* mode (empty `integration/sources/` → go import
  sources) and a *restart/extension* mode (prompt to import additional sources and
  re-run `analyse-sources` before continuing). Guidance only; Gate 6 unchanged.
  (DD-051)

## [3.13.0] — 2026-06-13

### Added
- **Parquet source import.** `import-flatfile` now accepts `.parquet` files
  (single file or mixed into a directory of CSV/Excel/Parquet). Column types are
  mapped directly from the Parquet schema, and only sample data (`--max-rows`) is
  read — the full file is never loaded. Requires the new optional `[parquet]`
  extra (`pyarrow`). (DD-050)

## [3.12.1] — 2026-06-13

### Fixed
- **`update --upgrade` now refreshes managed files under the new version.**
  Previously the post-upgrade managed-file refresh ran in the same process, which
  still had the *old* toolkit loaded, so skills/instructions were stamped against
  the old version and a manual second `update` was needed. The command now
  re-execs the refresh in a fresh `uv run` when the version changes. (DD-049)

### Added
- **Running-vs-pinned version guard.** The CLI now warns (non-blocking) when the
  running toolkit version differs from the version pinned in the hub's
  `pyproject.toml` — catching users who run a global/older `kairos-ontology`
  instead of `uv run kairos-ontology`. (DD-049)

## [3.12.0] — 2026-06-13

### Removed
- **FastAPI service** — removed the `service/` directory and `tests/service/` tests.
  The REST API backend (ontology CRUD, validation, projection, AI chat endpoints) was
  built to support a frontend UI that has been removed. The toolkit CLI and Copilot
  skills are the primary interfaces. (DD-045)

### Added
- **Business discovery phase + company SKOS glossary** — new `kairos-design-discovery`
  skill at the front of the design lifecycle: explores company context and captures the
  company's alternative/business terminology (esp. logistics jargon) as a SKOS glossary
  overlay, without modifying the domain ontology. `kairos-design-mapping` consumes
  `skos:altLabel` as advisory mapping candidates. `init`/`new-repo` create repo-root
  `.imports/businessdiscovery/` and `ontology-hub/model/glossary/`. Added a "clear
  Copilot session" recommendation at the modeling entry points. (DD-048)
- **`kairos-int:` integration extension vocabulary** — new `kairos-int:` namespace
  (`https://kairos.cnext.eu/integration#`) with 22 annotation properties for
  integration pipeline behaviour: load strategy, batching, error handling, retry,
  scheduling, data validation, FK lookup, and sensitive data masking. (DD-045)
- Integration projector emits a new `"integration"` section in mapping JSON (schema v2)
- Dapr projector uses `schedule` and `retryPolicy` annotations for cron bindings
  and resiliency policies
- Scenario tests for integration extension annotations (`test_scenario_integration.py`)
- Vocabulary coverage test for `kairos-int:` annotations
- **`propose-alignment` mapping hints** — opt-in `--include-mapping-hints` flag emits
  deterministic transform hints (passthrough/CAST) and structural candidates
  (split/dedup/multi-target) to seed the `design-mapping` skill. Default output is
  unchanged. (design log DD-045)
- **Reference-model specialization visibility in `design-domain`** — the modeler now
  surfaces reference-model subclasses and their subclass-specific properties (from the
  materialized inventories) at Step 0c.1b, Checkpoint 1, and Checkpoint 3b, steering
  reuse over local duplication. (DD-046)
- **`kairos-ontology check-inventory`** — deterministic pre-flight gate that verifies
  `model/inventory/*.yaml` exists and is current (via a stored `source_sha256`),
  blocking domain modeling against a missing/stale inventory. `generate_inventory()`
  now stamps `source_sha256` into the inventory envelope. (DD-047)
- Tests: `test_propose_alignment_hints.py`, `test_scenario_mapping_hints.py`,
  `test_inventory_freshness.py`, `test_design_domain_skill_contract.py`,
  `test_scenario_specialization.py`
- `docs/guide/practitioner/context-engineer-methodology-guide.md` — two-design-model
  methodology + three-tier (deterministic/promptable/judgment) guide

### Removed
- Dead `--catalog` option / `catalog_path` parameter from the `generate-inventory`
  command and `generate_inventory()` (reserved-for-future, never wired)

## [3.9.2] — 2026-06-08

### Fixed
- **CR-005 — SCD2 `source_data` CTE uses aliased column names for SK/IRI** — in SCD2
  silver models, the `source_data` CTE reads `FROM mapped`, where columns are already
  aliased. The projector previously used the original source column name (e.g.
  `uniqueIdentifier`) in `generate_surrogate_key()` and the IRI `CONCAT`, causing a
  runtime T-SQL error (`Invalid column name`). The fix passes `scd_type` into
  `_extract_silver_columns` and skips the source-expression substitution for SCD2 models,
  so SK/IRI correctly reference the aliased names available in `mapped`.

## [3.6.2] — 2026-05-31

### Fixed
- **Single-source column scoping** — entities with one source table now only include
  columns from that table. Previously, inherited properties from other tables generated
  invalid column references in the SQL SELECT.
- **Cross-domain ref() validation** — the post-generation validator no longer emits
  false-positive warnings for `ref()` targets used in FK JOIN clauses (cross-domain
  references). Genuine typos still trigger warnings.

## [3.6.1] — date not recorded

> Date metadata reconciled on 2026-07-21. The previous future date was invalid,
> and no reliable historical release date was available.

### Fixed
- **Cross-table warnings filtered by domain** — the dbt projector's cross-table
  column warning now only fires for properties whose `rdfs:domain` matches the
  current class (or its parents). Previously it warned for ALL column_maps regardless
  of domain, causing 100+ spurious warnings in hubs with many source tables.

### Added
- **Scenario tests for cross-table warnings** — two tests verify the domain filter:
  warnings fire for legitimate cross-table references and stay silent for properties
  belonging to other entities.

## [3.3.0] — 2026-05-30

### Added
- **Extension vocabulary coverage guard** — `tests/test_ext_vocabulary_coverage.py`
  fails if any `kairos-ext` annotation consumed by a projector is undeclared in
  `kairos-ext.ttl`, keeping the vocabulary the single source of truth (DD-034).
- **`docs/dev/dd-034-extension-explanation.md`** — hub-author reference for the full
  `kairos-ext:` vocabulary (per-layer annotations, naming conventions, FK-child
  identity guidance, RESERVED list).
- **Context-aware `naturalKey` warning** — the dbt projector now detects FK-child
  entities (targeted by `silverForeignKeyOn`) and names the parent + explains the
  weak-entity / source-identity / embedded options (CR-3 Option 4).

### Changed
- **Declared previously-undeclared gold annotations** in `kairos-ext.ttl`:
  `perspective`, `generateTimeIntelligence`, `olsRestricted` (plus RESERVED
  `incrementalColumn`); marked `surrogateKeyStrategy` and `rolePlayingAs` RESERVED;
  fixed the stale "Silver Layer" header and documented the layer-prefix convention.
- **Standardized** `KAIROS_EXT.term("x")` → `KAIROS_EXT.x` within the dbt projector.

### Decisions
- **DD-034** — extension vocabulary is the single source of truth; `identityStrategy`
  (CR-3) deferred in favour of improved warnings.

### Fixed
- **CI lockfile drift** — raised the `ruff` floor to `>=0.5.0` and regenerated
  `poetry.lock` (ruff `0.1.15` → `0.15.15`). The previously locked ruff `0.1.15`
  was too old for `pytest-ruff 0.5`, which passes `--output-format=full`, breaking
  the `test` job for all files regardless of code changes.

## [2.36.0] — 2026-05-26

### Added

- **Per-domain projection markdown reports** — After projections complete, a
  human-readable markdown report is written to
  `ontology-hub/.sessions-projection/projection-{domain}-{YYYY-MM-DD_HH-MM-SS}.md`
  containing domain info, projection results, warnings, and errors.
- **`.sessions-projection/` folder** — New dedicated folder in the hub for
  projection session reports, created by `init` and `new-repo` commands.
- **Hash-tolerant catalog resolution (DD-024)** — `CatalogResolver` now
  resolves `owl:imports` URIs with or without trailing `#`, preventing silent
  failures when catalog entries and import statements disagree on hash usage.
  A diagnostic warning is logged when hash fallback is needed.

### Changed

- **Renamed `.modeling-sessions/` → `.sessions-modeling/`** — The modeling
  session folder now uses the `.sessions-*` naming convention for consistency.
- **Renamed modeling session files** — From `{domain}-config-{timestamp}.md`
  to `modeling-{domain}-{YYYY-MM-DD}.md` to mirror projection report naming.

## [2.31.0] — 2026-05-19

### Added

- **Shared extension defaults for reference models (DD-023)** — Reference model
  repositories can now ship `*-silver-defaults.ttl` and `*-gold-defaults.ttl`
  files alongside their ontologies. The toolkit auto-discovers these via catalog
  resolution and merges them as a fallback layer beneath hub domain extensions.
- **`resolve_import_paths()` utility** — New public function in `catalog_utils.py`
  that exposes catalog-resolved local paths for `owl:imports` URIs.
- **Layered extension merge** — Merge priority: hub domain ext > reference model
  defaults > built-in projector conventions. Hub annotations always win.

### Changed

- Silver/gold projectors support `silverInclude`/`goldInclude` declared in
  reference model defaults files (inherited by downstream hubs).
- Updated silver and modeling skill documentation with DD-023 guidance.

### Removed

- Obsolete draft documents (`docs/MIGRATION.md`, `docs/TOOLKIT_IMPROVEMENT_SPEC*.md`,
  `docs/medallion-restructure-advisory.md`).

## [2.28.0] — 2026-05-17

### Added

- **Import whitelisting (DD-021)** — Silver and gold projectors now support
  projecting imported classes from reference models (BSP, MMT, DCSA).
  Imported classes require explicit claiming via `kairos-ext:silverInclude` /
  `goldInclude` (per-class) or `silverIncludeImports` / `goldIncludeImports`
  (bulk, ontology-level). Peer hub domain imports are automatically excluded
  from bulk inclusion. See DD-021 in `docs/dev/toolkit-design-decisions.md`.
- **4 new `kairos-ext:` annotations** — `silverInclude`, `silverIncludeImports`,
  `goldInclude`, `goldIncludeImports` added to the extension vocabulary.
- **Pre-release publishing** — `release.ps1` supports rc/beta/alpha pre-releases
  with auto-incrementing sequence numbers and PEP 440 version format.
- **Channel system** — hub repos can set `[tool.kairos] channel` in `pyproject.toml`
  to `"stable"` (default), `"preview"`, or an explicit version tag.
- **`update --upgrade`** — resolves the channel to a git tag and upgrades the
  toolkit via pip, updating the `pyproject.toml` dependency pin automatically.
- **Multi-platform dbt** — Fabric (default) and Databricks staging templates
  with platform-specific type maps and cross-platform macros.
- **Branch protection** — `new-repo` auto-configures branch protection on `main`
  (require PR, 1 reviewer, dismiss stale reviews, block force push).
- **Design decisions log** — `docs/dev/toolkit-design-decisions.md` (ADR format).

### Fixed

- **Jinja2 `loop.parent`** — replaced invalid attribute with `{% set outer_last %}`
  pattern in staging templates.
- **Empty columns guard** — `columns[0]` unique_key fallback now handles empty lists.

## [2.27.0] — 2026-05-17

### Changed

- **Consolidated modeling skill** — removed separate `kairos-ontology-modeling-config`
  skill; its logic (business alignment checkpoints, session persistence, validation
  gates) is now embedded in the unified `kairos-ontology-modeling` skill with a
  quick-edit mode for minor changes.

## [2.26.1] — 2026-05-17

### Fixed

- **Skill folder naming** — renamed `kairos-ontology-modelling-config` to
  `kairos-ontology-modeling-config` for consistent US English spelling across
  all skill folders, scaffold copies, and copilot-instructions references.

## [2.26.0] — 2026-05-17

### Added

- **Modeling configurator skill** (`kairos-ontology-modeling-config`) — interactive
  modeling workflow with business alignment checkpoints, session persistence
  (`.modeling-sessions/`), and structured validation gates.
- **Reference-model-first workflow** — updated `kairos-ontology-modeling` skill with
  accelerator pack selection, domain mapping tables, OWL catalog imports, and
  business validation steps before any custom modeling.
- **`.modeling-sessions/` folder** — added to scaffold and CLI `init`/`new-repo`
  commands for persisting modeling session state across conversations.

## [2.6.1] — 2026-04-23

### Fixed

- **Mapping terminology** — clarified "source-to-silver mappings (SKOS + kairos-map:)"
  vs "ontology alignment" across medallion-projection, hub-setup, and quickstart skills.
- **Stale directory trees** — fixed hub-setup and quickstart skills still showing old
  `integration/mappings/` and `output/medallion/bronze/` paths.

## [2.6.0] — 2026-04-23

### Added

- **`<nextCatalog>` chaining** — `CatalogResolver` now follows `<nextCatalog>` elements
  recursively, enabling hub-local catalogs to chain to shared reference catalogs.
- **Hub-local catalog support** — `init` and `new-repo` generate
  `ontology-hub/catalog-v001.xml` with `<nextCatalog>` pointing to the shared
  `ontology-reference-models/catalog-v001.xml`. Auto-discovered by `--catalog`.

### Changed

- **Bronze vocabulary relocated** — moved from `output/medallion/bronze/` to
  `integration/sources/{system-name}/` as it is a discovery artifact, not a projection
  output. `_parse_bronze()` now uses `rglob("*.ttl")` on the sources directory.
- **Mappings relocated** — moved from `integration/mappings/` to `model/mappings/` with
  per-source-system subfolders (`model/mappings/{system-name}/`).
- **Mappings README** — clarified dual-purpose design: each mapping file contains both
  SKOS alignment and `kairos-map:` dbt transform annotations.
- Updated all skills (×10), MIGRATION.md, and copilot-instructions.md for new paths.

## [2.3.0] — 2026-04-23

### Added

- **dbt projector rewrite** — complete dbt Core project generation from ontology + bronze
  source system descriptions + SKOS mappings. Generates staging models (views), silver
  entity models (tables), schema YAML with SHACL-derived tests, `dbt_project.yml`, and
  `packages.yml`.
- **`kairos-bronze:` vocabulary** — new namespace (`https://kairos.cnext.eu/bronze#`)
  for describing source system schemas (SourceSystem, SourceTable, SourceColumn).
- **`kairos-map:` vocabulary** — new namespace (`https://kairos.cnext.eu/mapping#`)
  for technical mapping annotations (transform expressions, deduplication, filtering).
- **Bronze directory scaffold** — `bronze/` directory with README and template for
  describing source systems in hub repositories.
- **Updated mappings scaffold** — `mappings/README.md` now documents both external
  vocabulary alignment and bronze-to-silver SKOS mapping patterns.
- **`kairos-dbt-projection` skill** — 4-phase guide for describing bronze sources,
  creating SKOS mappings, running the projection, and validating dbt output.
- **19 new dbt projector tests** — covers bronze parsing, SKOS mapping, SHACL test
  extraction, and full artifact generation (225 total tests).
- **6 new Jinja2 templates** — `sources.yml`, `staging_model.sql`, `silver_model.sql`,
  `schema_models.yml`, `dbt_project.yml`, `packages.yml`.

### Changed

- **dbt staging models materialized as views** (per dbt best practices).
- **SHACL → dbt test mapping** now uses `dbt_expectations` package for regex, length,
  and range constraints (previously used `dbt_utils.expression_is_true`).
- **Projector orchestrator** now auto-discovers `bronze/` and `mappings/` directories
  and passes them to the dbt projector.

## [2.2.2] — 2025-07-26

### Added

- **`update` creates `package.json` if missing** — ensures Mermaid CLI is available
  for silver projection SVG export on existing client repos.
- **`.devcontainer/` scaffold** — new Dev Container config with Python 3.12, Node.js
  LTS, and GitHub CLI. Created by both `init` and `update` commands.

## [2.2.1] — 2025-07-26

### Fixed

- **Namespace detection for hash-fragment ontologies** — `_auto_detect_namespace()`
  now correctly returns `{ontologyURI}#` when classes use `#`-fragment naming
  (e.g. `https://example.com/ont/client#Client`). Previously it truncated to the
  parent path (`https://example.com/ont/`), causing the IMP-1 domain filter to
  match ALL domains with a shared path prefix.

## [2.2.0] — 2025-07-26

### Added

- **GDPR PII validation** (`validate --gdpr`) — scans domain ontologies for
  properties matching PII keywords (first_name, national_id, iban, email, etc.)
  and warns when the owning class lacks a `kairos-ext:gdprSatelliteOf` annotation.
  Runs as part of `validate --all` or standalone with `validate --gdpr`.
- **Projection-time GDPR warning** — the silver projector now emits `logging.warning`
  messages when classes with PII-like properties lack GDPR satellite protection.
- **Explicit annotation mandate** — silver projection skill (Phase 2) updated to
  instruct Copilot to always write every annotation explicitly, even defaults.
  Includes new Phase 2f "Annotation completeness check" step.
- `validate_gdpr()` function added to public API.

### Changed

- **Scaffold template** (`silver-ext.ttl.template`) — audit envelope example now
  uses Spark SQL types (TIMESTAMP, STRING) instead of T-SQL (DATETIME2, NVARCHAR).
  Added `kairos-ext:inlineRefThreshold` ontology-level annotation. All class-level
  examples now show explicit `isReferenceData "false"` for non-reference classes.

## [2.1.1] — 2025-07-26

### Fixed

- **BUG-1: S5/S6 columns on all domains** — `_row_hash` and `_deleted_at` are now
  fixed structural columns, always appended after the audit envelope. Previously
  they were part of the customizable `auditEnvelope` string and could be missing
  when a domain used a pre-v2.1.0 custom audit annotation.
- **BUG-2: Duplicate subtype names** — S3 flattening comment no longer lists the
  same subtype multiple times when a class is reachable via multiple import paths.
- **BUG-3: GDPR satellite breach in imported tables** — Imported classes from
  other namespaces are no longer materialized as tables. This prevents GDPR
  satellite columns (e.g. NaturalPerson PII) from being flattened into
  cross-domain copies where the GDPR annotation is not visible.
- **BUG-4: S4 inlined column names** — Smarter prefix merging avoids redundant
  segments (e.g. `shareholder_property_right_property_right_name_en` →
  `shareholder_property_right_name_en`).

### Changed

- **IMP-1: Canonical schema only** — The projector now only generates tables for
  classes whose URI belongs to the current domain namespace. Imported classes
  become cross-domain FK comment references (e.g. `-- FK: party_sk →
  silver_party.party`). This typically reduces table count by 40-60%.
- `_resolve_external_table` now handles `ref_` prefix for cross-domain reference
  data classes.

## [2.1.0] — 2025-07-26

### Changed

- **Silver Fabric Warehouse rules (S1–S8)** — Major overhaul of silver projector
  targeting MS Fabric Warehouse:
  - **S1**: Spark SQL types — BOOLEAN, TIMESTAMP, STRING, DOUBLE replace T-SQL types
  - **S2**: PK/FK/UNIQUE constraints emitted as DDL comments (Fabric cannot enforce)
  - **S3**: Full inheritance flattening — ALL subtypes merge into parent table with
    auto-generated discriminator column (supersedes R16 empty-subtype-only suppression)
  - **S4**: Inline small reference tables (≤3 business columns) into parent table
  - **S5**: `_row_hash BINARY` column added to audit envelope for incremental MERGE
  - **S6**: `_deleted_at TIMESTAMP` column added for soft-delete tracking
  - **S7**: Canonical schema ownership — no cross-domain table duplication
  - **S8**: No dim_/fact_ prefixes in silver (reserved for Gold layer)

### Added

- **Three-layer rule architecture** — R1–R16 common annotations + S1–S8 Silver
  Fabric behaviours + G1–G8 Gold placeholder rules
- **Gold projection placeholder** — G1–G8 rules documented in skill file for
  future Power BI / dimensional model projector
- `kairos-ext:inlineRefThreshold` annotation property for S4 configuration
- `ref_` prefix now included in `table_name_for()` for consistent FK references

### Fixed

- FK columns to reference tables now correctly use `ref_` prefix in column and
  constraint names (was generating `gender_sk` instead of `ref_gender_sk`)

## [2.0.2] — 2025-07-25

### Fixed

- **Duplicate FK column** — Self-referential properties (e.g. reportsTo, supervisor)
  no longer generate duplicate column names
- **PK/FK collision** — Self-referential FK no longer collides with table PK name
- **Duplicate constraints** — ALTER TABLE no longer emits duplicate FK constraints
- **Nullable annotations** — `kairos-ext:nullable "false"` now correctly generates
  NOT NULL on FK columns

## [2.0.1] — 2025-07-25

### Fixed

- **Non-domain TTL filter** — Projector now skips `*-silver-ext.ttl` and
  `_master.ttl` files when discovering domain ontologies

## [2.0.0] — 2025-07-25

### Changed

- **License**: Migrated from MIT to **Apache License 2.0** as part of Kairos
  Community Edition
- SPDX headers added to all Python source files

### Added

- `NOTICE` file with copyright attribution
- `CONTRIBUTING.md` with contribution guidelines
- `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1)
- `SECURITY.md` with vulnerability reporting policy
- GitHub issue and PR templates

## [1.9.0] — 2025-07-25

### Added

- **Ontology IRI traceability** — All 6 projection targets now include ontology
  IRI, version, and toolkit version in their output
- Per-domain `projection-manifest.json` generated alongside projections
- `extract_ontology_metadata()` helper in projector module

## [1.8.0] — 2025-07-25

### Added

- **R16 — Empty subtype suppression** — Subtypes with no own properties under a
  discriminator-strategy parent are folded into the parent table
- `_has_own_properties()` helper for silver projector

## [1.7.0] — 2025-07-24

### Added

- **Silver ERD generation** — Mermaid ERD diagrams for silver layer
- **SVG export** — Mermaid CLI integration for ERD SVG rendering
- Cross-domain FK relationship labels in ERD diagrams

## [1.6.0] — 2025-07-23

### Added

- **Silver layer projection** — Full DDL generation (R1–R15)
- SCD Type 2 audit envelope columns
- GDPR satellite tables
- Junction tables for many-to-many relationships
- Discriminator-based inheritance

## [1.5.0] — 2025-07-22

### Added

- Multi-domain architecture support
- Domain-scoped projection output folders
- `_master.ttl` catalog for domain registration

## [1.4.0] — 2025-07-21

### Added

- A2UI message schema projection
- Prompt projection for AI chat context

## [1.3.0] — 2025-07-20

### Added

- Azure Search index projection
- Neo4j Cypher schema projection

## [1.2.0] — 2025-07-19

### Added

- dbt model + schema.yml projection
- Jinja2 template system for projections

## [1.1.0] — 2025-07-18

### Added

- SHACL validation support
- Ontology validation CLI command

## [1.0.0] — 2025-07-17

### Added

- Initial release
- OWL/Turtle ontology loading and parsing
- Syntax validation
- CLI with `validate` and `project` commands
- FastAPI service with GitHub repository integration
- Hub scaffolding (`kairos init`)
