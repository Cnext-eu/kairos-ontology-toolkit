---
name: kairos-help
description: >
  Orientation guide to the Kairos Ontology Toolkit — explains design philosophy,
  hub structure, projections, CLI commands, and best practices. Use when users ask
  "how does Kairos work?" or need a conceptual overview. NOT for performing
  actual work (setup, modeling, projections).
---

# Kairos Ontology Toolkit — Help & Reference

You are a Kairos ontology assistant. Use this skill when users need orientation,
ask how the toolkit works, want to understand design choices, or need guidance
on best practices.

## 1  Design Philosophy

### 1.1  Ontology-Driven Architecture

Everything starts from the **domain ontology** (OWL/Turtle `.ttl` files).
All downstream artifacts — database schemas, dbt models, search indexes,
semantic models, documentation — are **generated (projected)** from the
ontology. The ontology is the single source of truth.

### 1.2  Shift-Left Principle

> **Never edit generated output. Always change the model and regenerate.**

When a projection output doesn't match requirements, the fix belongs in the
ontology or its annotations — never in the generated files. This is the
"shift-left" principle: push decisions as far upstream as possible.

**Examples:**

| Desired outcome | ❌ Wrong approach | ✅ Right approach |
|---|---|---|
| A field must be required / NOT NULL | Add a `not_null` dbt test manually | Add `sh:minCount 1` in the SHACL shape → dbt test is generated automatically |
| A column needs a specific SQL type | Edit the generated DDL | Add `kairos-ext:sqlType "DECIMAL(18,4)"` on the property in an extension file |
| A table should be a fact table | Rename the generated model | Author its explicit role, grain/type, source version, version binding, and runtime policy |
| A measure needs YTD calculation | Write DAX in generated TMDL | Link an approved bounded calendar profile with role-playing date bindings |
| A field should be hidden from some users | Edit a generated role | Add a complete fail-closed `SecurityPolicy` with an explicit OLS binding and tests |

### 1.3  Separation of Concerns

The toolkit enforces clean boundaries:

| Layer | Owns | Does NOT own |
|---|---|---|
| **Domain ontology** | Classes, properties, relationships, business vocabulary | Physical storage, BI measures, integration logic |
| **Extension files** (`*-ext.ttl`) | Physical annotations (SQL types, table types, gold schema) | Business semantics |
| **SHACL shapes** | Validation constraints (required fields, value ranges, patterns) | Downstream schema |
| **Bronze vocabulary** | Source system field descriptions | Domain meaning |
| **Mappings** | Source-to-domain column alignment (SKOS + kairos-map:) | Transform implementation |
| **Projections** | Generated artifacts (dbt, DDL, TMDL, indexes) | — (read-only output) |

### 1.4  dbt vs Semantic Model Split

For the medallion gold layer, follow this rule:

- **dbt = data logic** — cleansing, joins, conformed dimensions, fact tables, surrogate keys, incremental loads, data quality tests, documentation, lineage
- **Semantic model = business metrics** — DAX measures, relationships, hierarchies, RLS/OLS, perspectives, calculation groups, business-friendly names
- **Reports = visuals only** — consume semantic model measures; no business logic in reports

The toolkit enforces this with first-class `kairos-ext:Measure` resources.
Measures never replace or remove physical input columns. Intent measures are
documentation-only; provisional and later measures emit DAX only after every declared
column/measure dependency resolves.

## 2  Fresh Hub Lifecycle — From Empty Repo to First Projection

Just created a hub and wondering *"now what?"* — this is the recommended
end-to-end path. Each phase is owned by a dedicated skill (DD-040). The flow is
a **recommendation, not enforcement**: you can invoke any skill at any time, and
a minimal first pass can stop after **Execute** (validate + project), layering
mapping/silver/gold on later as needed.

### Canonical order

```text
discovery → source → domain → logical Silver
→ [advanced dbt when needed] → mapping → bound Silver confirmation
→ gold → validate → check-projection → project
→ compile/runtime validation → release → diagnose → consume
```

For simple direct/scalar mappings, omit only advanced dbt. The objective state
chain is `authored → design-valid → bound-valid → projection-ready → generated
→ compile-valid → runtime-valid → release-eligible`. Legacy phase `done` means
legacy/unknown input, not readiness and not failure.

### Step-by-step

| # | Phase | Invoke skill | Produces | Required for a first projection? |
|---|-------|--------------|----------|----------------------------------|
| 1 | **Orient** | `kairos-help` | Understanding of the toolkit | — |
| 1b | **Start / resume** | `kairos-flow` | Lifecycle status overview + clean-start/continue routing (owns `.kairos-state/`) | — (recommended entry) |
| 2 | **Setup — create repo** | `kairos-setup-init` | GitHub repo + scaffold + first domain | ✅ |
| 3 | **Setup — configure** (optional) | `kairos-setup-config` | Folder/config/SHACL tuning | — |
| 4 | **Design — discovery** | `kairos-design-discovery` | Company context (`.kairos-state/phases/discovery.md`) + business glossary (`businessdiscovery/`) | — (recommended first) |
| 5 | **Design — source** | `kairos-design-source` | Bronze vocabulary (`*.vocabulary.ttl`) | Needed for `dbt` |
| 6 | **Design — domain** | `kairos-design-domain` | OWL classes + properties (`*.ttl`) | ✅ |
| 7 | **Design — logical Silver** | `kairos-design-silver` | SCD, identity/grain, FK, PII/DQ intent | Needed for `silver`/`dbt` |
| 7b | **Develop — advanced dbt** (optional) | `kairos-develop-dbt-transformation` | Contracted intermediate SQL/YAML/tests + generated virtual source | Only for complex relational logic |
| 7c | **Design — final mapping** | `kairos-design-mapping` | Physical/virtual source→domain mappings | Needed for `dbt` |
| 8 | **Confirm — bound Silver** | `kairos-design-silver` | Non-writing shared-evaluator evidence | Needed for `silver`/`dbt` |
| 9 | **Design — gold** | `kairos-design-gold` | `*-gold-ext.ttl` annotations | Needed for `powerbi` |
| 9b | **Design — MDM** (optional) | `kairos-design-mdm` | `*-mdm-ext.ttl` policy | Needed for `mdm-profile` |
| 10 | **Execute — validate** | `kairos-execute-validate` | Syntax + SHACL pass/fail | ✅ |
| 10b | **Check — projection readiness** | `kairos-execute-project` | Non-writing blocker/readiness report | ✅ before generation |
| 11 | **Execute — project** | `kairos-execute-project` | All output artifacts | ✅; only when projection-ready |
| 12 | **Diagnose** | `kairos-diagnose-status` | Completeness / gap report (deep dive on `kairos-ontology status`) | — |
| 13 | **Consume** | `kairos-package-dataplatform` | Downstream dbt consumption | — |

> **Discovery first (recommended):** before modeling, run **kairos-design-discovery**
> to capture what the company does and the *alternative names* they use for things
> (especially in logistics, where industry terms can carry a different meaning).
> This context grounds domain naming and lets mapping resolve the company's own
> jargon — without ever changing the domain ontology.

> 🧹 **Clean context first:** modeling works best in a fresh Copilot session. Before
> starting the design phases (discovery → … → gold), clear the current chat
> (`/clear`) so unrelated history doesn't add noise to naming and mapping decisions.

### Minimal first pass (smallest loop)

To see your first generated output as fast as possible:

1. `kairos-setup-init` — create the repo + first domain.
2. `kairos-design-domain` — model a few classes + properties.
3. `kairos-execute-validate` — fix any syntax/SHACL issues.
4. `kairos-execute-project` — generate the `prompt` / `neo4j` / `a2ui` targets,
   which need no extensions or mappings.

Then layer on **discovery → source → mapping → silver → gold** when you're ready
for the `dbt`, `silver`, and `powerbi` targets.

> **Skill-first:** always invoke the skill for each phase rather than running
> raw `kairos-ontology` CLI commands — the skills add pre-flight checks and
> interactive validation gates that the bare CLI bypasses.

## 3  Hub Folder Structure

A Kairos ontology hub repository follows this layout:

```
ontology-hub/
├── model/                          # Domain knowledge (ontologies + shapes)
│   ├── ontologies/                 # OWL/Turtle domain ontologies
│   │   ├── _master.ttl             # Imports all domains
│   │   ├── sales.ttl               # Example domain
│   │   └── hr.ttl
│   ├── shapes/                     # SHACL validation shapes
│   │   ├── sales-shapes.ttl
│   │   └── hr-shapes.ttl
│   ├── extensions/                 # Physical / BI annotations
│   │   ├── sales-silver-ext.ttl    # Silver-layer annotations (R1–R16)
│   │   ├── sales-gold-ext.ttl      # Gold-layer annotations (G1–G8)
│   │   └── hr-silver-ext.ttl
│   ├── glossary/                   # Business glossary (SKOS overlay of alt-names)
│   │   └── {company}-glossary.ttl  # From kairos-design-discovery; used by mapping
│   └── mappings/                   # Source-to-domain mappings (SKOS + kairos-map:)
│       ├── custom-transformations/ # Generated-source mappings
│       └── sales-erp-mapping.ttl
├── integration/                    # Source system documentation
│   ├── sources/                    # API specs, Bronze vocabularies
│   │   ├── custom-transformations/ # Generated contract vocabularies
│   │   └── erp/
│   └── transforms/dbt/             # Authored contracted dbt models/macros/tests
├── output/                         # Generated artifacts (DO NOT EDIT)
│   ├── medallion/                  # Medallion architecture outputs
│   │   ├── dbt/                    # dbt Core project (silver + gold)
│   │   │   ├── models/
│   │   │   ├── analyses/
│   │   │   └── docs/
│   │   └── gold/                   # Power BI semantic model (TMDL)
│   │       └── {Domain}.SemanticModel/
│   │           └── definition/
│   │               ├── model.tmdl
│   │               ├── tables/
│   │               ├── relationships/
│   │               ├── roles/
│   │               ├── perspectives/
│   │               └── calculationGroups/
│   ├── neo4j/                      # Cypher constraints + import scripts
│   ├── azure-search/               # Azure AI Search index definitions
│   ├── a2ui/                       # A2UI navigation model
│   └── prompt/                     # LLM-optimised ontology descriptions
├── .github/
│   ├── skills/                     # Copilot skills for this hub
│   └── copilot-instructions.md
├── package.json                    # Hub metadata
└── README.md                       # Domain catalog

# At the REPO ROOT (not under ontology-hub/):
.import/
└── businessdiscovery/              # Drop-in artifacts (notes, decks) for discovery
ontology-reference-models/          # Imported industry reference models
```

### Key rules

- **`model/`** is the source of truth. All changes start here.
- **`output/`** is generated. Never edit files here — regenerate with `kairos-ontology project`.
- **`integration/`** holds source system reference docs used by the bronze vocabulary skill.
- **Advanced dbt authority:** custom SQL owns relational logic; contract YAML owns physical
  outputs; ontology/glossary own meaning; SKOS owns source-to-domain semantics; Silver
  extensions own semantic keys/SK/FK/SCD and `silverSourceRef`. Generated virtual
  vocabularies and `output/` are never hand-edited.
- **Imported dbt evidence:** explicit repository-contained SQL/dbt roots can be inventoried
  under `model/planning/dbt-transformations/`. The inventory is non-executable and
  non-projecting; deterministic SQL signals trigger a governed
  **dbt-transformation checkpoint** before Mapping/Silver, not a new lifecycle phase.
- **`_master.ttl`** must import every domain ontology.

## 4  Available Projections

The toolkit supports the following projection targets:

| Target | Command flag | What it generates | When to use |
|---|---|---|---|
| `dbt` | `--target dbt --platform fabric\|databricks` | dbt SQL/YAML plus adapter DDL, constraint metadata, ERD, and parity manifest from one `SilverModelSpec` | Data warehouse / lakehouse pipeline |
| `silver` | `--target silver --platform fabric\|databricks` | Explicit evidence-bound facade over the same Silver pipeline; fails without source/prep/mapping/policy evidence | Silver physical/parity review |
| `powerbi` | `--target powerbi` | Power BI TMDL semantic model (tables, measures, relationships, RLS, perspectives) | BI semantic layer |
| `neo4j` | `--target neo4j` | Cypher constraints, indexes, and import scripts | Graph database |
| `azure-search` | `--target azure-search` | Azure AI Search index definitions (JSON) | Search / RAG scenarios |
| `a2ui` | `--target a2ui` | A2UI navigation model | UI integration |
| `prompt` | `--target prompt` | LLM-optimised ontology descriptions | AI / copilot context |
| `report` | `--target report` | HTML mapping report with data flow diagrams and coverage dashboards | Documentation / governance |
| `ddd` | `--target ddd` | Mermaid context maps + aggregate overviews + Markdown architecture report from `*-ddd-ext.ttl` overlays → `output/architecture/ddd/` | DDD architecture documentation |
| `mdm-profile` | `--target mdm-profile` | Immutable, content-addressed MDM policy profile (JSON + review MD) from `*-mdm-ext.ttl` → `output/mdm/` | Master Data Management (opt-in; consumed by `kairos-mdm-runtime`) |
| `all` | `--target all` | Standard targets; dbt already includes the Silver physical/parity bundle | Full regeneration |

Structured semantic inspection commands use the same recursive closure and semantic index
as validation and projection:

```bash
kairos-ontology resolve-ontology model/ontologies/client.ttl --json-output
kairos-ontology show-class-inventory --domain client --profile kairos-design
kairos-ontology show-source-schema --system erp
kairos-ontology explain-term https://example.org/ont/client#Client \
  --ontology model/ontologies/client.ttl
```

> **Target-first aspirational Silver stubs (DD-096):** the dbt target supports an
> opt-in `--emit-aspirational-stubs` flag (also `KAIROS_EMIT_ASPIRATIONAL_STUBS`).
> When enabled, an *approved but not-yet-mapped* claim projects a typed, zero-row
> **stub** Silver model so downstream Silver/Gold can be built target-first; adding a
> source mapping later transparently **binds** the stub on the next projection. Off by
> default (output byte-identical). See the **kairos-execute-project** skill.

> **Optional DDD overlay (DD-091):** DDD design intent — bounded contexts,
> context maps, aggregate roots, value objects — lives in optional
> `model/extensions/{domain}-ddd-ext.ttl` overlays using the `kairos-ddd`
> vocabulary. It is **additive documentation only**: it never changes
> silver/gold/dbt/Power BI output, and governance (ownership, approval,
> disposition, materialization) stays in the claim registry. Validate overlays
> with `kairos-ontology validate --ddd` (also part of `validate --all`) and
> render docs with `kairos-ontology project --target ddd`. It slots into the
> lifecycle after `domain/claims`:
> `discovery → source → domain/claims → optional DDD overlay → mapping → silver → gold → validate → project`.

> **Optional MDM layer (MDM-DD-001..003):** Master Data Management policy — mastered
> concepts, match rules, survivorship, workflow, DQ — lives in optional
> `model/extensions/{domain}-mdm-ext.ttl` overlays using the `kairos-mdm` vocabulary.
> Like `ddd`, the `mdm-profile` target is **opt-in and excluded from `--target all`**;
> run it explicitly. It emits an immutable, content-addressed profile to `output/mdm/`
> consumed by the separate `kairos-mdm-runtime` repo. Author policy with
> **kairos-design-mdm**, validate with `kairos-ontology mdm-validate`. See `docs/mdm/`.


> **Import whitelisting (DD-021):** When a domain ontology uses `owl:imports`
> to reference external models, imported classes are NOT projected by default.
> Use `kairos-ext:silverInclude` / `kairos-ext:goldInclude` per class or
> `kairos-ext:silverIncludeImports` / `kairos-ext:goldIncludeImports` on the
> ontology to explicitly claim imported classes for projection.  See the
> silver and gold medallion skills for details.

> **Runtime semantics (DD-109):** Fresh hubs get no generic SCD fallback. SCD1/SCD2
> classes link a complete incremental policy and source prep supplies canonical CDC
> operation, separate source-update/effective/ingestion timestamps, and total order.
> SCD2 emits separate business-valid and system intervals. Optional canonical hashes
> use contract v1 SHA-256 typed length-delimited bytes. Every FK declares
> current/as-of/none, cardinality, all failure actions, and change-detection
> participation. Missing or adapter-unsupported behavior blocks before render.
>
> **Managed reference modules (DD-104):** Accelerator `data-domains.yaml` may define
> version-pinned module profiles with roots, descendant policy, an explicit projection
> allow-list, accepted transitive dependencies, and a local-extension boundary.
> `claims-to-silver-ext --accelerator <pack>` resolves document IRIs, synchronizes the
> managed import/include block, and emits `output/reference-modules/*-activation.json`.
> Validation and projection use the same import plan and fail closed unless degraded
> mode is explicitly selected.
>
> **Simplified FK annotations (DD-022):** Use `kairos-ext:silverForeignKey true`
> on an object property to generate a FK column without OWL cardinality
> restrictions.  Use `kairos-ext:silverForeignKeyOn <Class>` to control which
> table receives the FK (useful for parent→child relationships on imported
> properties).

## 5  CLI Commands

```bash
# Validate syntax + SHACL shapes
kairos-ontology validate [--ontologies PATH] [--shapes PATH] \
  [--report-format json|markdown|both] [--report-path PATH]

# Generate projections (`--platform` applies to dbt/all; default fabric)
kairos-ontology project [--ontologies PATH] [--target TARGET] \
  [--platform fabric|databricks]

# Check the same projection scope through artifact planning without rendering/writing
kairos-ontology check-projection [--ontologies PATH | --ontology FILE] \
  [--catalog FILE] [--ref-models PATH] [--accelerator NAME] [--target TARGET] \
  [--platform fabric|databricks] [--namespace IRI] \
  [--scope projection|source|mapping|transformation|silver] [--json-output]

# Focused, read-only design validation and proposed-only authoring previews
kairos-ontology validate-mapping --domain DOMAIN [--mapping FILE] [--catalog FILE]
kairos-ontology validate-silver-ext --domain DOMAIN [--catalog FILE]
kairos-ontology scaffold-mapping --domain DOMAIN --source-table IRI --target-class IRI
kairos-ontology scaffold-silver-ext --domain DOMAIN [--mapping FILE]
kairos-ontology reconstruct-dbt-transformation --vocabulary FILE [--output DIRECTORY]

# Synchronize custom dbt contracts to managed virtual-source RDF
kairos-ontology sync-dbt-contracts [--check] [--transforms PATH] [--sources PATH] \
  [--bronze-sources PATH]

# Check or remediate persisted source sample privacy without printing values
kairos-ontology source-privacy [--sources PATH] [--fix]

# Validate generated dbt dependencies, parse, manifest graph, and compile
kairos-ontology validate-dbt --platform fabric|databricks \
  [--project-dir PATH] [--profiles-dir PATH]

# Initialise a new hub from scaffold
kairos-ontology init [--name NAME]

# Create a new hub repository
kairos-ontology new-repo [--name NAME]

# Refresh managed files to the installed toolkit version
kairos-ontology update

# Upgrade toolkit to channel's latest version (stable/preview)
kairos-ontology update --upgrade

# Preview what the managed-file refresh would change
kairos-ontology update --check

# Migrate flat layout → grouped layout
kairos-ontology migrate

# Run catalog tests
kairos-ontology catalog-test

# Import TMDL/PBIP files for ontology modeling input
kairos-ontology import-tmdl <source> [--output PATH]

# Import CSV/Excel flat files as source documentation
kairos-ontology import-flatfile --from <path> [--system NAME] [--output PATH] \
  [--sample-size 5] [--max-rows 1000]

# Analyse sources against reference models (LLM-powered, pre-modeling)
# Concurrent (--max-workers, default 8) + cached; prints a cost banner (use gpt-5.4-mini).
kairos-ontology analyse-sources [--sources PATH] [--ref-models PATH] [--output PATH] \
  [--model gpt-5.4-mini] [--domains "Domain1,Domain2"] [--max-domains N] [--materialize PATH] \
  [--max-workers 8] [--force]

# Propose source→domain column alignment (LLM-powered, pre-modeling)
# Embedded primarily in the kairos-design-domain skill (Step 0a.2 alignment gate);
# there is no separate alignment skill — run it via kairos-design-domain.
# Concurrent (--max-workers) + cached; anchors on affinity likely_entity, preferring a
# confirmed kairos-design-discovery Core Concepts Conformance URI when present; an
# anchor ambiguous even in that confirmed evidence is never guessed — it is left
# unresolved (zero property claims) and recorded in {domain}-unresolved-anchors.yaml.
# check-claims reports such a table as a non-blocking "Unresolved class anchors"
# warning — never as a blocking column omission (its empty coverage is intended).
# Cost banner.
kairos-ontology propose-alignment [--domains "Domain1,Domain2"] [--ref-models PATH] \
  [--max-workers 8] [--force] [--max-prompt-classes 12] \
  [--retry-min-confidence 0.6] [--retry-min-mapped-ratio 0.4]
kairos-ontology check-claims [--domains "Domain1,Domain2"] [--strict] [--warn-only] \
  [--require-mapping] [--format text|json]

# Check overall lifecycle status (deterministic, AI-free — DD-080/DD-101)
kairos-ontology status [--format text|json|markdown]

# One composed release-readiness gate: claims + source-coverage + extension-sync +
# release eligibility (DD-096) + committed validation/projection state (DD-101)
kairos-ontology check-release [--domains "Domain1,Domain2"] [--format text|json] [--warn-only]

# Generate coverage report (deterministic alignment, post-modeling)
kairos-ontology coverage-report [--ontology PATH] [--ref-models PATH] [--format both]

# Suggest DRAFT SHACL shapes from bronze source profiling (DD-076)
# Writes to output/shapes-draft/<name>.ttl (outside model/shapes, NOT auto-loaded).
# Run via the kairos-execute-validate skill; PII never enumerated, always masked.
kairos-ontology suggest-shapes [--source PATH] [--out PATH] \
  [--enum-distinct-max 12] [--no-sample-values] [--force]

# Build the SKOS company glossary from confirmed discovery extractions (deterministic)
kairos-ontology build-glossary [--company-specific-only] [--company-domain acme.com] \
  [--glossary-namespace IRI] [--output PATH]
```

Contracted outputs may provide DD-108 source identity through a generated
`kairos-dbt:ContractIdentity`. This remains contract-output scoped and requires actual
passing uniqueness/non-null evidence captured with `capture-dbt-contract-evidence`; declared
tests alone surface a review-only `identity.contract-unverified` diagnostic — it blocks
`project --strict` and release eligibility, but not ordinary generation, `check-projection`,
or mapping/silver readiness. See `docs/dbt-contract-identity.md`.
Capture rejects artifacts without matching invocation metadata and cryptographic SQL/YAML
provenance. Ordinary standard manifest v12 and run-results artifacts work without custom
fields; evidence is never synthesized from current files plus stale test statuses.

Default paths:
- `--ontologies` → `ontology-hub/model/ontologies`
- `--shapes` → `ontology-hub/model/shapes`

## 6  Annotation Namespaces

| Prefix | Namespace | Purpose |
|---|---|---|
| `kairos-ext:` | `https://kairos.cnext.eu/ext#` | Physical annotations (SQL types, gold table types, BI features) |
| `kairos-bronze:` | `https://kairos.cnext.eu/bronze#` | Source system vocabulary |
| `kairos-map:` | `https://kairos.cnext.eu/map#` | Source-to-domain column mappings |

### Common `kairos-ext:` annotations

| Annotation | Level | Effect |
|---|---|---|
| `goldProductProfile` | Ontology | Required registered Gold product profile; v1 supports only `dimensional-powerbi-v1` |
| `goldTableType` | Class | Required explicit `"fact"`, `"dimension"`, or `"bridge"` role; never inferred |
| `goldSourceModel` / `goldSourceVersion` | Class | Exact actual Silver registry binding |
| `goldSchema` | Ontology | Target schema for the Gold product |
| `measureExpression` | `Measure` resource | Governed DAX expression; never removes a physical column |
| `sqlType` | Property | Override SQL column type |
| `calendarProfile` | Ontology | Links an explicit approved bounded calendar; no calendar is invented |
| `securityPolicy` | Ontology | Links a complete fail-closed RLS/OLS entitlement contract |
| `perspective` | Class | Navigation-only grouping; never a security boundary |
| `incrementalPolicy` | Class | Complete DD-109 merge/CDC/time/order/delete/replay/backfill contract |
| `hashPolicy` | Class | Canonical hash v1 inputs, SHA-256, and explicit null representation |
| `silverForeignKeyTemporalMode` | Object property | Explicit `current`, `as-of`, or `none` lookup |

## 7  Common Workflows

### Adding a new domain

1. Create `model/ontologies/new-domain.ttl` (OWL classes + properties) — or, once
   an approved `model/claims/new-domain-claims.yaml` exists, run
   `kairos-ontology claims-to-silver-ext` and let it scaffold a metadata-complete
   skeleton (`rdfs:label`/`rdfs:comment`/`owl:versionInfo`/imports) for you.
2. Add `owl:imports` in `_master.ttl` — `claims-to-silver-ext` converges this
   registration (and the README domain table) automatically for every ready
   domain when `_master.ttl` already exists; it reports created/updated/unchanged
   paths explicitly so you can confirm what changed.
3. Create `model/shapes/new-domain-shapes.ttl` (SHACL constraints)
4. Run `kairos-ontology validate` → fix any issues
5. Run `kairos-ontology project --target all` → generates all outputs
6. Commit model + output together

### Changing a projection output

1. **Identify what needs to change** in the output
2. **Trace back** to the ontology class/property or annotation
3. **Modify the model** (ontology, shape, or extension file)
4. **Regenerate**: `kairos-ontology project --target <target>`
5. **Verify** the output matches expectations
6. Commit

### Adding silver/gold annotations

1. Create `model/extensions/{domain}-silver-ext.ttl` or `{domain}-gold-ext.ttl`
2. Use the appropriate namespace (`kairos-ext:`) to annotate classes/properties
3. Regenerate: `kairos-ontology project --target dbt` (or `powerbi`)

### Adding an advanced dbt transformation

1. For imported evidence, invoke **kairos-design-source** and inventory only explicitly
   selected roots with `inventory-dbt-candidates`.
2. Invoke **kairos-develop-dbt-transformation** for grain, target, authority, replacement
   scope, contract, SQL, and tests.
3. Run `sync-dbt-contracts`; map the generated virtual source with
   **kairos-design-mapping** and set Silver routing with **kairos-design-silver**.
   For a governed wrong-grain replacement, declare canonical
   `meta.kairos.replaces_sources[].table_iri`; do not add an unsafe direct mapping.
4. Project and validate each required adapter:
   `project --target dbt --platform <fabric|databricks>`, then
   `validate-dbt --platform <fabric|databricks>`.

## 8  Ontology Modelling Best Practices

| Practice | Guideline |
|---|---|
| **Naming** | PascalCase for classes (`SalesOrder`), camelCase for properties (`orderDate`) |
| **Labels** | Every `owl:Class` must have `rdfs:label` and `rdfs:comment` |
| **Properties** | Every property must have `rdfs:domain`, `rdfs:range`, and `rdfs:label` |
| **Ontology header** | Must declare `owl:Ontology` with `rdfs:label` and `owl:versionInfo` |
| **Namespaces** | Use HTTP/HTTPS URIs with `#` or `/` separator |
| **SHACL for constraints** | Required fields → `sh:minCount 1`; patterns → `sh:pattern`; value ranges → `sh:minInclusive` / `sh:maxInclusive` |
| **Extension files for physical** | SQL types, table types, BI annotations go in `*-ext.ttl`, not in the domain ontology |

## 9  Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Validation fails with "No owl:Ontology" | Missing ontology header | Add `<uri> a owl:Ontology ; rdfs:label "..." ; owl:versionInfo "1.0" .` |
| dbt model missing a column | Property lacks `rdfs:domain` | Add `rdfs:domain` pointing to the class |
| Gold projection blocks | Missing/unknown profile or stale Silver binding | Select `dimensional-powerbi-v1`; update `goldSourceModel` and `goldSourceVersion` from passing Silver parity |
| TMDL measure not generated | Measure is `intent` or has unresolved dependencies | Promote through governance only after expression, dependencies, type/format/folder, tests, evidence, and owner are complete |
| SHACL validation passes but dbt test fails | Shape constraint mismatch | Align SHACL `sh:minCount` with expected NOT NULL behaviour |

## 10  Keeping This Skill Up to Date

This skill must be updated whenever **new core functionality** is added to the
toolkit — new projections, new annotations, new CLI commands, or new design
patterns. The PR checklist in `SC-merge-pr` includes a reminder to verify this.

---

*This skill is auto-distributed to hub repositories via the scaffold system.
Changes here are mirrored to `src/kairos_ontology/scaffold/skills/kairos-help/`.*
