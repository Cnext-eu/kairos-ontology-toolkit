# Issues detected — 2026-07-28

Log of defects and rough edges found in the Kairos Ontology Toolkit (v5.0.0)
while enabling Git LFS, running business discovery, importing sources
(Qargo, Qlik/AGEPE, EsriGrid), and materializing reference-model inventories.

Legend — **Severity**: Blocker / Major / Minor. **Status**: Fixed locally /
Worked around / Open (upstream).

> **Independent code verification (2026-07-28):** every technical claim below was
> re-checked against toolkit source at the cited call sites. Per-issue verdicts
> (Confirmed / Confirmed with correction / Reclassify — design decision /
> Reclassify — process) and a reclassification summary are in the
> **[Validation pass](#validation-pass--independent-code-verification-2026-07-28)**
> section at the end of this document.

---

## 1. Scaffolded `catalog-v001.xml` is invalid XML (breaks inventory/validate/compile)

- **Severity:** Blocker
- **Status:** Fixed locally; **open upstream** (scaffold template)
- **Symptom:** `kairos-ontology generate-inventory` failed for **every** TTL
  (including local `_foundation.ttl`/`_master.ttl`) with
  `not well-formed (invalid token): line 8, column 39`, producing 0 inventories.
  This blocked Gate 0 of `kairos-design-domain`.
- **Root cause:** The header comment in `ontology-hub/catalog-v001.xml`
  contained `kairos-ontology compile <domain> --check`. The `--` inside an XML
  comment (`<!-- ... -->`) is illegal per the XML spec, so `xml.etree`
  (`CatalogResolver._load_catalog_file`) raised `ParseError`. Because
  `load_ontology()` builds the `CatalogResolver` before parsing any ontology,
  the same error surfaced for all TTLs (misleadingly attributed to each `.ttl`).
- **Where:**
  - Hub file: `ontology-hub/catalog-v001.xml` (comment line 8).
  - Toolkit scaffold source (same defect, ships to every new hub):
    `kairos_ontology/scaffold/ontology-hub/catalog-v001.xml.template`.
  - Failure path: `core/catalog_utils.py:125` (`ET.parse`) →
    `core/ontology_loader.py:237` → `core/inventory.py:259`.
- **Fix applied:** Reworded the comment to `kairos-ontology compile <domain>
  (check mode)` to remove the `--`. Both catalogs now parse; 66 inventories
  generate.
- **Recommended upstream fix:** Correct `catalog-v001.xml.template` so the
  scaffold no longer emits invalid XML (avoid `--` in comments). Consider a
  scaffold test that asserts every generated `*.xml` is well-formed.

---

## 2. `import-flatfile` collapses Excel files by worksheet name

- **Severity:** Major (silent data loss)
- **Status:** Worked around
- **Symptom:** Importing the Qlik directory of 31 `.xlsx` exports produced only
  13 tables. Files whose first sheet shared a name (many were `Sheet1`, `data`,
  `PBI`, ...) overwrote each other.
- **Root cause:** `read_xlsx_tables` names each table by the **worksheet title**
  (`core/import_flatfile.py:228-292`, `"name": sheet_name`), while the directory
  writer keys tables by that name — so identically-named sheets across different
  files collide. CSV import instead uses the filename stem
  (`core/import_flatfile.py:142`), which is unique per file.
- **Workaround:** Flattened the nested folders and converted each worksheet to a
  uniquely-named CSV (`<filestem>[__sheet].csv`) before import; 31 files then
  yielded 35 distinct tables with no collisions.
- **Recommended upstream fix:** For directory/xlsx imports, qualify the table
  name with the source filename (e.g. `<filestem>__<sheet>`) so single-sheet
  files never collide.

## 2a. `import-flatfile` is non-recursive and cannot read legacy `.xls`

- **Severity:** Minor
- **Status:** Worked around
- **Detail:** Directory import uses `Path.iterdir()`
  (`core/import_flatfile.py:637`), so nested subfolders are ignored — inputs had
  to be staged flat. Legacy `.xls` files crash the importer
  (`InvalidFileException`, openpyxl only supports `.xlsx`); dropped the two `.xls`
  validation-checklist files.
- **Also:** Excel support requires the `[flatfile]` extra (`openpyxl`); it is not
  installed by the base package, so the first xlsx import failed with a clear
  "openpyxl is required" message. Installed `openpyxl` (+ `xlrd`).

---

## 3. Auto-redaction / `source-privacy` misses free-text person names and IDs

- **Severity:** Major (PII exposure risk on real data)
- **Status:** Worked around (manual redaction)
- **Symptom:** After import-time redaction and a clean `source-privacy --fix`
  ("privacy-safe for supported patterns", 0 rewrites), sample rows still
  contained personal data:
  - Qargo `contacts.name`: `Dominik` (person first name).
  - Qlik `cr01__6_haulier_driver_keys_per_order.DriverDescription`:
    `2- kamida- 14`, `3-BULSO 3` (driver names).
  - EsriGrid `operational_sql.DriverNo`: driver-level identifiers
    (e.g. `4042`, `9690`).
- **Root cause:** The detector recognises structured patterns (email, address,
  VAT, phone) and some name columns (`DebtorFirstName` was caught as
  `kind=name`), but not free-text driver/description fields or short numeric
  driver keys.
- **Workaround:** Manually redacted the residual values with the same token
  format. Company/haulier codes (business identifiers, not personal) retained.
- **Recommended upstream fix:** Extend the detector with heuristics/allow-lists
  for driver/contact/name-bearing columns, and treat driver-level identifiers as
  personal data by default. Consider a `--strict`/interactive review that flags
  columns whose name matches `*driver*`, `*contact*`, `*name*`.

---

## 4. `generate-inventory`: 3 FIBO/financial modules fail import closure

- **Severity:** Minor (out of scope here)
- **Status:** Accepted — not needed for this hub
- **Symptom:** `financial-services-accelerator`, `ACTUS-examples`, and
  `scaffolding` fail with "Ontology closure is incomplete; rerun with
  degraded=True..." and stay MISSING; `check-inventory` therefore exits non-zero
  even though all 66 logistics/maritime/multimodal modules are up to date.
- **Decision:** CLdN is a cargo/RoRo logistics domain — **FIBO/financial models
  are not used here**, so these modules are intentionally left un-materialized.
  Domain design proceeds against the logistics scope (DCSA, MMT, IMO, WCO, TIC,
  supply-chain, sustainability, logistics-accelerator).
- **Note:** `check-inventory` returning overall failure on out-of-scope missing
  modules is noisy; the domain-scoped check (`--domains <domain>`) is the
  authority for a given design.

---

## 5. Cosmetic: `import-flatfile` over-counts documented tables

- **Severity:** Trivial
- **Status:** Open (cosmetic)
- **Detail:** The success line reports roughly double the real table count
  (e.g. "70 table(s) documented" for 35 CSVs; "2" for 1). The written YAML/sample
  counts are correct.

---

## 6. `source-natural` identity check couples source-column name to ontology property name

- **Severity:** Major (blocks correct binding authoring)
- **Status:** Worked around (surrogate); **open upstream** — filed as
  [kairos-ontology-toolkit#245](https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/245)
- **Symptom:** `kairos-ontology compile booking --check` rejected a valid
  `source-natural` EntityBinding for `qargo.orders → booking:TransportOrder`
  with `identity.authored-key-not-supplied: ... missing: name`, even though the
  identity source column `name` (the unique, not-null order reference,
  e.g. `Or-0000005`) is mapped (to `booking:orderReference`) and carries
  not-null + unique quality checks.
- **Root cause:** `_validate_identity_columns`
  (`core/projections/dbt/policy_normalize.py:~3679-3706`) compares
  `identity.business.keys` — which are the **source** `sourceKey` columns,
  snake-cased at `policy_normalize.py:1582-1585` — against silver output column
  names, which are derived from the **target property** local name
  (`core/compiler/adapter.py:628`, `core/compiler/kernel.py:236`,
  `core/ontology_ops.py:143`). The check therefore only passes when
  `camel_to_snake(sourceKey_column) == camel_to_snake(property_local_name)`.
  The canonical example passes only by coincidence (`customer_id` ↔
  `party:customerId`).
- **Workaround:** Switched the binding to `strategy: surrogate` (generated key
  from the same `name` column) so `booking` compiles. Documented inline in
  `integration/bindings/qargo-to-booking.binding.yaml`. Revert to
  `source-natural` once #245 is fixed.
- **Recommended upstream fix:** Follow the source-column → output-column mapping
  when validating identity keys, rather than assuming the source column name
  equals the target property column name.

---

## 7. Compiler resolves only properties whose `rdfs:domain` is *exactly* the bound class (no inheritance)

- **Severity:** Major (directly blocks the "reuse industry models, avoid
  duplication" guidance)
- **Status:** Worked around (re-declared local subproperties)
- **Symptom:** When redesigning `party` to a role-based model, we wanted to bind
  `party:Organisation` (`⊑ bsp-pt:TradeParty`) fields **directly** to reused
  reference properties `bsp-pt:partyName` / `bsp-pt:partyIdentifier`. The binding
  field resolver cannot see them for the subclass, so every attribute had to be
  re-declared locally on `party:Organisation`.
- **Root cause:** `core/ontology_ops.py` `list_properties` (L131-153) keeps a
  property only if `cls_ref in <rdfs:domain objects>` — an **exact** domain match
  with no superclass walk; `core/compiler/kernel.py` `list_classes` (~L204) only
  iterates hub-namespace classes. Inherited reference-model properties are
  invisible to binding field resolution.
- **Workaround:** Declared local datatype properties on `party:Organisation`
  aligned to the reference model via `rdfs:subPropertyOf bsp-pt:*`. Functional,
  but it duplicates every reused attribute into the hub ontology — the opposite of
  the strict-reuse intent.
- **This is a "LLM fixing what the toolkit should do" case:** the model had to be
  restructured to satisfy a resolver limitation rather than express the cleanest
  ontology.
- **Recommended upstream fix:** Resolve properties across the bound class's
  superclass chain (including imported reference modules), so a hub subclass can
  bind inherited reference properties without local redeclaration. If intentional,
  document it prominently and reconcile with the reuse guidance.

---

## 8. `check-inventory --domains <d>` still exits non-zero when *out-of-scope* inventories are missing

- **Severity:** Minor (noisy; contradicts the scoped-gate contract)
- **Status:** Worked around (treated the printed scoped "ready" as authority)
- **Symptom:** `check-inventory --domains party --explain-scope` printed
  `✅ Active-domain inventories are ready` **and still exited code 1** because
  unrelated inventories (financial-services, booking, equipment, ...) are missing.
- **Tension:** `kairos-design-domain` Gate 0 says *"Unrelated repository-wide
  failures are non-blocking when the scoped command exits zero."* But the scoped
  command **never** exits zero while any global inventory is missing, so the
  documented gate contract cannot actually be satisfied — the LLM must ignore the
  exit code and read the prose instead.
- **Recommended fix:** When `--domains` is supplied and all in-scope inventories
  are ready, exit 0 and downgrade out-of-scope misses to warnings.

---

## 9. Inconsistent CLI flags: `validate` uses `--report-format`, `compile` uses `--format`

- **Severity:** Trivial (DX friction)
- **Status:** N/A (corrected the invocation)
- **Symptom:** `validate --format text` fails with
  `No such option '--format'. Did you mean '--report-format'?`, while
  `compile --format text` is correct. The flag name differs per subcommand, so the
  natural by-analogy invocation is wrong.
- **Recommended fix:** Accept `--format` as an alias on all subcommands (or
  standardize on one name).

---

## 10. New hub *domain* ontologies require manual catalog wiring for cross-domain `owl:imports`

- **Severity:** Major (easy to get wrong; silently blocks import resolution)
- **Status:** Worked around (hand-edited `catalog-v001.xml`)
- **Symptom:** Cross-domain `owl:imports` of the hub's own domain IRIs
  (`https://cldn.com/ont/{party,equipment,booking}`) did not resolve until
  `<uri name="https://cldn.com/ont/<x>" uri="model/ontologies/<x>.ttl"/>` entries
  were **manually** added to `ontology-hub/catalog-v001.xml` (exact IRI, no
  trailing slash).
- **Root cause:** The hub catalog maps reference-model IRIs but not
  hub-authored domain IRIs; authoring a new `model/ontologies/<domain>.ttl` does
  not register it in the catalog.
- **This is a "LLM fixing what the toolkit should do" case:** every new domain
  file needs a hand-edited catalog line before it can be imported by a sibling.
- **Recommended fix:** Auto-generate/refresh hub-domain catalog entries from
  `model/ontologies/*.ttl` (e.g. in a scaffold/validate step), or resolve local
  `https://cldn.com/ont/<stem>` IRIs by convention without explicit catalog lines.

---

## 11. Managed Import Completeness forces importing *every* configured module for a domain, even unused ones

- **Severity:** Minor (design tension; import-closure bloat)
- **Status:** Worked around (imported all configured modules)
- **Symptom:** `party.ttl` must `owl:imports` `bsp/party`, `mmt/party` **and**
  `imo/party` even though only `bsp-pt:TradeParty` is used; `booking.ttl` must
  import `bsp/documents` though nothing from it is referenced. Omitting any makes
  `validate --consistency` fail.
- **Root cause:** `resolve_hub_accelerator` (`core/reference_modules.py`) enforces
  that a `<domain>.ttl` imports every reference module the blueprint maps to that
  domain id, regardless of use.
- **Recommended fix:** Require imports only for modules actually referenced (or
  offer an opt-out), to avoid accumulating unused import closure and reasoning
  cost.

---

## 12. Reference-model `VERSION` not available for Gate 0 provenance

- **Severity:** Trivial
- **Status:** Open
- **Symptom:** `kairos-design-domain` Gate 0 asks to report the installed
  reference-model version from `ontology-reference-models/VERSION`; the file is
  absent, so version is reported as `unknown`.
- **Recommended fix:** Ship a `VERSION` file with the reference-models pack and/or
  surface the version in `check-inventory` output.

---

## 13. Binding-identity authoring is opaque and drove repeated LLM guess-and-check cycles

- **Severity:** Major (workflow friction; the root cause of the surrogate
  compromise in #6)
- **Status:** Worked around
- **Symptom:** Authoring a single 3-field binding required many `compile --check`
  iterations chasing successive identity/quality diagnostics
  (`binding.quality-column-unmapped` → `identity.authored-key-not-supplied`),
  whose messages never revealed the underlying source-column-vs-property-column
  naming rule (#6). The LLM repeatedly re-edited the binding to appease the
  checker rather than being guided to a correct authoring shape, and ultimately
  had to downgrade `source-natural` identity to a generated `surrogate` (losing
  the business-identity assertion) just to compile.
- **Recommended fix:** Make identity/quality diagnostics state the **expected
  output column name and how it derives from the property**, and accept
  source-column-named identity keys (see #6/#245). A worked "identity + quality"
  authoring example in the skill would also cut the iteration count.

---

## 14. Domain design does not *enforce* import-and-align as the default (drifts to `seeAlso`)

- **Severity:** Major (produces weakly-aligned, non-reasoning ontologies by default)
- **Status:** Open (process/skill default) — surfaced twice by the user
- **Symptom:** The first-draft ontology proposals created CLdN-local classes with
  `rdfs:seeAlso` weak links to accelerator/reference terms instead of
  `owl:imports` + `rdfs:subClassOf`/`rdfs:subPropertyOf`. The correct
  import-and-align approach only happened after the user explicitly demanded it.
- **Why it matters:** `seeAlso` asserts no structural relationship, so the hub
  class does not actually specialize the reference class and cannot inherit its
  semantics; it silently diverges from the industry model.
- **Recommended fix:**
  - Make `owl:imports` + `subClassOf`/`subPropertyOf` alignment the **enforced
    default** in `kairos-design-domain` (route the managed SKILL.md change through
    **kairos-toolkit-ops**); reserve `seeAlso` for genuinely non-authoritative
    cross-references only.
  - Consider a `validate` warning when a hub class only `seeAlso`s a reference
    term whose module is imported but which it does not `subClassOf`.

---

## 15. Domain design starts too narrow (single role) instead of broad-base-first

- **Severity:** Major (myopic, hard-to-extend models)
- **Status:** Open (process/skill default)
- **Symptom:** The `party` slice modeled a narrow `Customer` role as the primary
  class first, rather than establishing the broad reference base
  (`bsp-pt:TradeParty` → hub `Organisation`) and preparing the role structure
  (customer, carrier, haulier, subcontractor, ...) beneath it. The user expects
  the bigger concepts first so child classes inherit the industry model's data
  properties.
- **Coupling with #7:** This goal is partly blocked by #7 — even with a correct
  broad base + imports, the compiler only resolves properties whose `rdfs:domain`
  is *exactly* the bound class, so inherited reference data properties are not
  visible to bindings without local redeclaration. Broad-base-first and #7 should
  be solved together.
- **Recommended fix:**
  - Update `kairos-design-domain` (via **kairos-toolkit-ops**) to require the
    reference base class + import closure be established before narrowing to a
    specific role/subtype, and to surface the reference subclass tree and its
    inherited data properties in the evidence matrix (Gate 3 already asks for the
    specialization tree — make it a hard step, not optional).
  - Pair with the #7 resolver fix so inherited industry data properties are
    bindable on hub subclasses.

---

## 16. The toolkit *has* a formal graph/semantic-index API, but the binding compiler bypasses it (reads structure via a weak namespace-scoped helper)

- **Severity:** Major (root of #7; makes the compiler blind to reference-model
  subclasses and inherited properties despite having the data loaded)
- **Status:** Open (upstream)
- **Question investigated:** *Are we reading the formal TTL structure (and fetching
  subclasses) with proper RDF code, or scraping TTL as text?*
- **Finding — the good part (formal API exists and is correct):**
  - `core/ontology_loader.py` `load_ontology(..., profile=...)` builds the full
    **catalog-resolved `owl:imports` closure** with reasoning profiles
    (`asserted` / `rdfs` / `kairos-design` / `owl-rl`) — not text parsing.
  - `core/semantic_index.py` exposes `class_by_uri`, `term`, and
    `class_properties()` returning **direct *and* inherited** properties, and
    traverses `rdfs:subClassOf` over the graph.
  - `core/analyse_sources.py` `_walk_subclasses` (DD-044) does a proper rdflib
    BFS down `rdfs:subClassOf` (no namespace filter) to collect descendant
    classes and their properties.
  - CLI inspection commands already surface this formally:
    `resolve-ontology`, `show-class-inventory`, `list-class-properties`
    ("direct and inherited class properties, including effective ranges"),
    `explain-term` (`cli/inspection.py`).
- **Finding — the gap (compiler ignores it):**
  - `core/compiler/kernel.py:186` loads the closure **and** the semantic index
    (`loaded = load_ontology(...)`, `loaded.semantic_index` is available), but
    `kernel.py:204` then resolves classes/properties via
    `ontology_ops.list_classes(graph, namespace)` instead of the semantic index.
  - `core/ontology_ops.py` `list_classes` (L110-129) filters classes to the hub
    namespace and keeps only same-namespace superclasses; `list_properties`
    (L131-153) requires an **exact `rdfs:domain`** match with no subclass walk.
  - Net: even though the reference-model subclass tree and inherited properties
    are fully present in `loaded.graph`/`loaded.semantic_index`, the binding
    resolver discards them. This is the **root cause of #7** and why reused
    reference properties are not bindable on a hub subclass.
- **Finding — design workflow reads text:** `kairos-design-domain` asks the LLM to
  "surface the specialization tree / subclasses of the parent," but does not
  direct it to the formal inspection commands, so in practice the reference
  subclass tree is read from the reference `.ttl` **as text** (this session read
  `derived-ontologies/BSP/current/party/party.ttl` via a file view to enumerate
  `TradeParty` subclasses) — bypassing `list-class-properties` /
  `show-class-inventory` / `explain-term`, and risking missed transitive
  structure.
- **Recommended fixes:**
  1. Have the compiler's binding resolver use `loaded.semantic_index`
     (`class_properties`, subclass-aware class resolution) instead of
     `ontology_ops.list_classes`/`list_properties`, so inherited reference
     properties and cross-namespace subclasses are resolvable (fixes #7).
  2. Either delete or clearly quarantine the namespace-scoped, exact-domain
     `ontology_ops` helpers so they are not used where structure-aware resolution
     is required (avoid "two ways to introspect, one weak").
  3. Update `kairos-design-domain` (via **kairos-toolkit-ops**) to mandate the
     formal inspection commands (`show-class-inventory`, `list-class-properties`,
     `explain-term`) for enumerating the reference base class, its subclass tree,
     and inherited properties — instead of reading reference TTL as text.

---

## Validation pass — independent code verification (2026-07-28)

Each issue was re-verified against toolkit source. Verdict vocabulary:
**Confirmed** (evidence matches), **Confirmed w/ correction** (real, but the
mechanism/framing needs a fix), **Reclassify — design decision** (real behaviour,
but plausibly intentional; needs a DD, not a bug fix), **Reclassify — process**
(skill/workflow opinion, no code defect).

### Load-bearing technical findings — Confirmed

- **#1 Invalid scaffold catalog XML — Confirmed (still live upstream).**
  `scaffold/ontology-hub/catalog-v001.xml.template` line 8 contains `--check`
  inside the `<!-- ... -->` block (lines 2-13); `--` inside an XML comment is
  illegal, so `ET.parse` fails. The `<domain>` angle brackets are *legal* in a
  comment and are **not** the cause — the report correctly isolates `--`.
  ⚠️ Every newly scaffolded hub inherits this, including hubs created after this
  log. Fix the template and add a "generated *.xml is well-formed" scaffold test.

- **#2 xlsx tables collapse by sheet name — Confirmed.** CSV import keys tables by
  `path.stem` (`core/import_flatfile.py:142`, unique per file); the xlsx path keys
  by worksheet title, so same-named sheets across files collide. Asymmetry is real.

- **#6 Identity couples source column to target-property name — Confirmed
  (with a sharper mechanism).** Exact chain verified:
  `identity.sourceKey` are **source** columns (validated as such at
  `core/compiler/adapter.py:662-668`); `strategy: source-natural` is remapped to
  `business-key` (`adapter.py:82-84`); output `ColumnSpec.name = prop.column_name`
  — the **target property** local name (`adapter.py:628`); `_validate_identity_columns`
  (`core/projections/dbt/policy_normalize.py:3690-3695`) compares snake-cased
  `sourceKey` against those property-derived output columns. It therefore passes
  only when `camel_to_snake(source_col) == camel_to_snake(property_local_name)`.
  The canonical example (`sourceKey: [customer_id]` <-> `party:customerId`) passes
  purely by that coincidence. Root defect is a **vocabulary mismatch**: a
  source-centric authoring surface (`sourceKey`, `source-natural`) is validated by
  a property/output-centric DD-108 policy layer. Legitimately **Major**.

- **#7 + #16 Compiler bypasses its own semantic index — Confirmed (strongest
  finding).** `core/compiler/kernel.py:186` builds the full `owl:imports` closure
  incl. the semantic index via `load_ontology`, then `kernel.py:204` resolves via
  `ontology_ops.list_classes`, which filters to the hub namespace
  (`if not uri.startswith(namespace): continue`, `core/ontology_ops.py:110-129`)
  and whose `list_properties` requires an **exact** `rdfs:domain` match with no
  superclass walk (`ontology_ops.py:131-153`). Grep confirms **zero** references to
  `semantic_index`/`class_properties` anywhere under `core/compiler/`, even though
  `core/semantic_index.py:129` `class_properties()` returns direct **and**
  inherited properties over `rdfs:subClassOf`. The gap is exactly as reported.

### Reclassify — design decisions (real behaviour, ratify via a DD, not a "bug")

- **#7/#16 fix is not free.** The exact-domain, hub-namespace resolver is
  consistent with a deliberate "hub owns its binding surface; reuse via
  `subPropertyOf` redeclaration" boundary (which is exactly the #7 workaround).
  Switching the resolver to `semantic_index` makes inherited, cross-namespace
  reference properties directly bindable — that materially changes the
  identity/lineage surface DD-108 keeps explicit. Right diagnosis; the remedy
  should go through a DD-108/DD-104 amendment before implementation.

- **#11 Managed Import Completeness — Reclassify.** Requiring `<domain>.ttl` to
  import every blueprint-mapped module is the DD-104 managed-imports / portable
  Silver-contract guarantee, enforced by `resolve_hub_accelerator`
  (`core/reference_modules.py`). Import-closure cost is a fair critique, but this
  is intentional, not a defect. Reframe as an opt-out / scoped-import request.

- **#4 / #8 Global exit code on out-of-scope inventories — Reclassify.** Real
  friction, but "the scoped-gate contract cannot be satisfied" only holds if
  fail-closed on out-of-scope misses is unintended. Treat as a scoped-exit
  feature request (exit 0 when all in-scope inventories are ready), not a
  contradiction.

### Reclassify — process / skill opinions (no code defect)

- **#14 import-and-align by default** and **#15 broad-base-first** are reasonable
  `kairos-design-domain` authoring preferences, but they are subjective workflow
  claims with no underlying code defect. Keep them, but track them separately from
  verified compiler bugs and route as managed `SKILL.md` changes via
  **kairos-toolkit-ops**. #15 is additionally coupled to #7 and should be solved
  alongside the resolver DD.

### Minor / trivial — Confirmed

- **#2a** (non-recursive dir import, no legacy `.xls`, `[flatfile]` extra),
  **#3** (redaction misses free-text names / short driver IDs),
  **#5** (over-counted table total), **#9** (`--report-format` vs `--format`),
  **#10** (hub-domain IRIs need manual catalog wiring), **#12** (missing
  reference-models `VERSION`), **#13** (opaque identity diagnostics) — accepted as
  described. #13 is the UX symptom of the #6 mechanism; fixing #6 diagnostics to
  state the expected output column name and its derivation should resolve most of
  the guess-and-check loop.

### Reclassification summary

| Bucket | Issues |
|---|---|
| Confirmed defects | #1, #2, #2a, #3, #5, #6, #9, #10, #12, #13, and the #16 root cause |
| Design decisions to ratify (DD needed) | #7 (resolver), #11 (managed imports), #4/#8 (scoped exit) |
| Process / skill opinions | #14, #15 |

**Severity note:** the four load-bearing findings (#1, #6, #7, #16) are accurate
and well-evidenced. The main correction to the original log is to stop treating
two probably-intentional behaviours (#11, and the #7/#16 resolver boundary) as
outright bugs, and to separate process opinions (#14, #15) from verified compiler
defects.
