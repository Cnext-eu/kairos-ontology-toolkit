# 06 — The Power BI authoring boundary: what is generated, what is authored

Status: analysis, 2026-10-17. No decision record yet. Triggered by questions from a client BI
developer (Fracht). Builds on DD-113, DD-236, DD-238, DD-239 and DD-253, and on
[01](01-apache-ossie-positioning.md).

## The questions

1. **Model objects that are structure, not data:** field parameters, numeric parameters,
   calculation groups, calculated tables, DAX user-defined functions and Power Query
   functions. How are they managed? Must they be written as code in the hub?
2. **The report:** visuals, interactions, bookmarks, drill-through, slicer sync, visual
   calculations, custom visuals and tooltips. If a report is generated, how do we change it?
3. **Embedding:** does a regenerated report get a new ID and break the *myFracht* embedding?
   Has that been validated?
4. **RLS:** how is it managed in code?
5. **Ossie:** does Apache Ossie cover part of this?

## What the toolkit does today

### Semantic model (hub-owned, regenerated on every release)

`render_powerbi_artifacts` (`core/projections/dbt/gold_render.py:1695-1834`) emits the
following:

| Object | Today | Evidence |
|---|---|---|
| Tables and columns (from Silver), relationships including inactive ones, `dim_date` | Generated | `gold_render.py:1004-1208` |
| Measures | Generated from `kairos-ext:Measure` resources in the hub (DAX, format, folder, lifecycle, display name) | `kairos-ext.ttl:732-801` |
| Calculation group | **One fixed group**, *Time Intelligence*, with 8 hard-coded items. No author-defined groups. | `gold_render.py:1283-1378` |
| Perspectives | Generated | `gold_render.py:1249-1280` |
| RLS and OLS roles | Generated skeleton: `filterExpression: FALSE()` (fail-closed placeholder) and OLS `metadataPermission: none`. **No members, no dynamic RLS.** | `gold_render.py:1211-1246`, `BPA_PROFILE.md:52,63,88` |
| Partitions | DirectLake (Fabric) or DirectQuery M (Databricks). No import mode. | `gold_render.py:840-873` |
| **Field parameters, numeric (what-if) parameters, calculated tables, calculated columns, DAX UDFs, hierarchies, translations, authored Power Query** | **Not supported.** Calculated columns and tables are excluded by design (DD-238). | `bpa_profile.py:139`, `BPA_PROFILE.md:46-61` |

**There is no overlay.** Hand edits to the emitted TMDL are lost on the next release. The
supported loop is `harvest-gold` (`core/gold_harvest.py`), which reads an edited model,
proposes new or changed **measures** and hidden columns back as provisional TTL, and is
re-emitted after review. It does not see calculation groups, field parameters, roles,
functions or calculated tables, because `tmdl_parser` does not parse them.

> Our docs don't say the model is "generated output, not a working copy" in those words. The
> phrasing they use is *"republished on every hub release, so edits to it are lost"*
> (`design-a-gold-product.md:100`, USER_GUIDE:190, DD-236).

### Report (authored by people, never generated)

- **DD-236:** the hub emits only a **blank** `<Product>.Report` stub (one empty page) so the
  PBIP opens. It does not generate pages, visuals, bookmarks or a theme.
- **DD-253:** the report people actually use is **authored in Power BI Desktop** and stored
  as PBIR under the dataplatform's `powerbi/reports/`, listed in `reports.yml`. At deploy it
  binds to the model **by display name**, resolved to the model ID in each workspace.

Every report feature on the list (interactions, bookmarks, drill-through, slicer sync,
visual calculations, tooltips, custom visuals) therefore lives in an authored, Git-tracked
report that the toolkit never regenerates.

### Identity and deploy

- **Model logicalId:** deterministic, a SHA-256 of `"<display name>.<type>"`
  (`gold_render.py:673-692`). Lineage tags are seeded from table, column and measure IDs.
- **Deploy:** fabric-cicd 1.3.0 `publish_all_items` (`deploy-powerbi-semantic-model.yml.template:225-250`).
  `unpublish_all_orphan_items` is **deliberately not called** (DD-239), so authored reports
  are never deleted.
- **Not stated or tested anywhere in the repository:** whether a redeploy keeps the item
  **GUID**. Embedding is never mentioned.

## Answers

### Q1 — Model objects that are structure, not data

**Today:** only measures and the fixed time-intelligence group can be authored, both in the
hub. Everything else on the list cannot be expressed. A hand-added field parameter or
calculation group is lost at the next release, and `harvest-gold` won't even report it.

**What is needed** (V6). Each object type gets one of three treatments:

| Object | Treatment | Why |
|---|---|---|
| **Field parameter** | **Declarative in the hub**, generated. Example: `kairos-ext:FieldParameter` with an ordered list of measure IDs or Gold columns, a display name and a default. | Its contents are references to objects the hub already owns, so it should be generated from them. Generating it means an ontology rename updates the parameter instead of breaking it. |
| **Numeric (what-if) parameter** | Declarative: name, min, max, step, default, and the generated measure | A tiny, fully specified structure (`GENERATESERIES` plus `SELECTEDVALUE`) |
| **Calculation group** | Declarative, generalising the existing time-intelligence emitter: items with DAX, ordinal and format-string expression | The emitter already exists. Opening it up is small. |
| **DAX user-defined function** | Authored like measures (`kairos-ext:DaxFunction`: signature, body, description) | Measures already work this way. Functions reduce duplicated DAX across measures. Check GA status before relying on it. |
| **Hierarchies, translations** | **Derived from the ontology**: hierarchies from declared roll-ups, translations from language-tagged `rdfs:label` and `skos:altLabel` | The meaning is already in the hub, so no extra authoring is needed |
| **Calculated table** (other than the parameter tables above) | **Stays out.** Model it as a Gold table in dbt. | DD-238: logic belongs upstream, where it is tested, versioned and reused outside Power BI |
| **Power Query functions and transformations** | **Stays out** for DirectLake. Do the transformation in dbt. M is used only for the deploy-time connection parameters we already emit. | DirectLake tables do not run M. Logic in M is invisible to every non-Power BI consumer. |
| **Anything else** (rare or new Power BI features) | Bounded **escape hatch**: authored TMDL *fragments* in the hub (`integration/gold/<product>/authored/*.tmdl`), additive only. The compiler checks them against the emitted model (each reference must resolve), and they go through BPA. | Avoids blocking the client while a declarative form doesn't exist. The reference check is the value: an ontology rename fails the build instead of silently breaking a fragment. This **reverses `gold_harvest.py`'s "no overlay" stance for a narrow, checked case** and needs its own decision record. |

`tmdl_parser` and `harvest-gold` must learn the new object types, so that objects built in
Desktop can be harvested back into declarations.

### Q2 — Report changes

**This is already the design, and nothing generated is touched.** Build the report in
Desktop, save it as PBIR in the dataplatform's `powerbi/reports/`, and register it in
`reports.yml`. Visuals, interactions, bookmarks, drill-through, slicer sync, visual
calculations and tooltips all live there and survive every hub release. The emitted
`.Report` stub is a placeholder only, and nobody should build on it.

Gaps to close:

- **Custom visuals.** Verify that the deploy staging copies a report's
  `StaticResources/RegisteredResources` (private visuals) intact. Organisational visuals
  come from the tenant admin portal and need nothing from us. Not validated yet.
- **Model changes can break reports.** A report references fields by name. Add a **report
  reference check** at deploy or PR time: parse each PBIR visual's field and measure
  references and fail when the release no longer has them. Today that breakage would only
  show up as broken visuals in the service.
- **Field parameters used in reports** need stable names. That is one more reason to
  generate them declaratively (Q1).

### Q3 — Embedding (*myFracht*)

**Not validated. The repository neither states nor tests GUID stability.**

The expected behaviour, still to be proven live, is as follows:

- fabric-cicd matches an existing workspace item by **name and type** and updates its
  definition **in place**. The Fabric `updateDefinition` API targets the existing item ID,
  so the report and model GUIDs should survive a redeploy.
- The authored report keeps its own name and logicalId (DD-253), so a hub release never
  recreates it.

When the ID *would* change:

- a **display-name change** (our logicalId is derived from it);
- someone **deletes** the item;
- deploying to a **new workspace** (each workspace has its own IDs; the same applies when
  promoting from DEV to PRD);
- the embed pointing at the hub's **blank stub** instead of the authored report.

**Actions:**

- A live test: deploy twice to a test workspace, compare report and model IDs, and keep a
  CI step that asserts the IDs are unchanged after each deploy.
- Recommend that *myFracht* **resolves the report ID by name per workspace** at runtime
  (one REST call) instead of hard-coding the GUID. DD-253 already resolves the model the
  same way.

### Q4 — RLS in code

**Today:** RLS is declared in the hub (`kairos-ext:securityPolicy`, `entitlementSource`,
`identityMapping`, `rolePolicy`, `securityBinding`, `failClosed`). The roles are generated,
but the filter is a **fail-closed `FALSE()` placeholder** (nobody sees data until someone
completes it). OLS works. Role **members** are assigned in the workspace (DD-238), not in
code. **Dynamic RLS is not generated.**

**What is needed** (V6):

1. **Generated dynamic RLS.** An entitlement (security bridge) table modelled in Gold. The
   role filter becomes, for example,
   `[CustomerKey] IN CALCULATETABLE(VALUES(Entitlement[CustomerKey]), Entitlement[UPN] = USERPRINCIPALNAME())`,
   generated from `entitlementSource` and `identityMapping`.
2. **Embedding RLS.** For *myFracht* (app-owns-data), the effective identity passed in the
   embed token must match `identityMapping`. Document this contract.
3. **Members.** Role members are Entra security groups assigned at deploy time per GitHub
   Environment (DD-239), through the Fabric API. People are never committed to Git.
4. **Tests.** The positive and negative security tests already in the vocabulary run against
   a deployed model before promotion.

### Q5 — Does Apache Ossie cover this?

**Only the part we already cover.** Ossie's Microsoft converter models tables, calculated
columns, measures and simple relationships. **Calculation groups, RLS roles, perspectives,
hierarchies, translations and Power Query expressions** are only *stashed* in a `POWER_BI`
extension so that a round trip restores them. They are not modelled. Field parameters,
numeric parameters, DAX UDFs and OLS aren't mentioned, and inactive and many-to-many
relationships are dropped. **Ossie has no report layer.** None of these questions gets an
answer from Ossie. TMDL stays the authoring and emission surface for these objects, and
Ossie remains an outbound interchange (topic 01).

## Proposed V6 items

| # | Item | Size | Priority |
|---:|---|---|---|
| 1 | **Live GUID-stability test** and a deploy CI assertion. Name-based report resolution guidance for embedders. | S | **Now.** It blocks a client answer. |
| 2 | Generated **dynamic RLS** from `entitlementSource` and `identityMapping`; group membership assigned at deploy | M | High |
| 3 | Declarative **field parameters** and **numeric parameters** | M | High (a client ask) |
| 4 | Authorable **calculation groups** (generalise the time-intelligence emitter) | S–M | High |
| 5 | **Report reference check** (PBIR field references against the release) | M | High |
| 6 | Hierarchies and translations derived from the ontology | M | Medium |
| 7 | DAX UDFs as `kairos-ext:DaxFunction` | S | Medium (after GA) |
| 8 | Checked TMDL **fragment** escape hatch, with a decision record reversing the "no overlay" stance for additive objects | M | Medium |
| 9 | Extend `tmdl_parser` and `harvest-gold` to calculation groups, field parameters, roles and functions | M | With 3, 4 and 7 |
| 10 | Verify custom visuals (`RegisteredResources`) survive deploy staging | S | With 1 |
| — | Fix the stale `BPA_PROFILE.md:92`, which says "four items" while 8 are emitted | XS | Housekeeping |

## Sources

- In the repository: DD-113, DD-236, DD-238, DD-239, DD-253; `core/projections/dbt/gold_render.py`;
  `core/gold_harvest.py`; `core/authored_reports.py`; `docs/guide/BPA_PROFILE.md`
- [apache/ossie Microsoft converter README](https://github.com/apache/ossie/blob/main/converters/microsoft/README.md)
- [Fabric REST: Update Report Definition](https://learn.microsoft.com/fr-fr/rest/api/fabric/report/items/update-report-definition)
- [SQLBI: UDFs vs calculation groups](https://docs.sqlbi.com/dax-internals/user-defined-functions/vs-calculation-groups)
