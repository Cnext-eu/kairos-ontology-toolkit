# Kairos Toolkit — Issue Log

Running log of toolkit issues, observations, and their status found while working in
this hub. Newest first.

**Environment when logged (2026-07-28):**

- Toolkit: `kairos-ontology-toolkit` **5.0.0**, installed from Git ref
  `feature/v5-stage2-4` pinned to SHA `c4dd565c69853a0c9abad60d34ba6931b40c5068`.
- Hub: `cldn2-ontology-hub`, adapter `fabric`.
- OS: Windows.

---

## ISSUE-7 — Cross-domain relationship targets do not resolve (per-domain compile scope)

- **Status:** OPEN (capability gap)
- **Severity:** high (a semantically valid FK between domains cannot be modelled as a
  compiler-wired relationship)
- **Area:** per-domain binding selection + relationship endpoint resolution
  (`core/compiler/kernel.py:1595, 1602` binding selection;
  `kernel.py:991, 1303` relationship target lookup;
  `_relationship_diagnostics` emits `safety.relationship-endpoint`)

### Observed / expected

`equip:Unit` (domain `equipment`, source `qargo.resources.subcontractor_company_id`)
should relate to `party:Organisation` (domain `party`, keyed on `company_id`) — the
subcontractor that owns/operates the unit. There is no supported way to author this,
because a relationship's `target` must be a binding **selected in the same domain
compile**:

```python
# kernel.py — only same-domain bindings are selected
if declared_domain not in {None, domain}: continue        # :1595
...
if binding.domain != domain: continue                     # :1602
# kernel.py — relationship target resolved only among those bindings
by_target = {binding.target_class: binding for binding in bindings}   # :991
target_binding = by_target.get(relationship.target)                   # None for party:Organisation
```

Attempting the natural authoring:

```yaml
# qargo-resources-to-equipment.binding.yaml (domain: equipment)
relationships:
  - property: equipment:operatedBySubcontractor
    target: party:Organisation        # binding lives in domain 'party'
    join:
      - local: subcontractor_company_id
        foreign: company_id
    cardinality: many-to-one
    mode: non-temporal
    missingParent: null
    ambiguousParent: first
```

would yield (relationship target not in `equipment` compile scope):

```
[error] safety.relationship-endpoint: relationship 'equipment:operatedBySubcontractor'
  target 'party:Organisation' does not resolve in compile scope
```

Importing `party.ttl` into `equipment.ttl` makes the *class* resolvable but not its
*binding*, so the endpoint still fails. The `RelationshipSpec` docstring
(`core/compiler/bindings.py:274`) mentions "materializable or external reference
entity", but there is **no implemented field** for a declared external key contract —
so no cross-domain escape hatch exists.

### Impact

Any FK that crosses canonical domains (equipment→party, booking→party, …) cannot be a
compiler-wired relationship in this version. Only intra-domain relationships work.

### Suggested toolkit improvements

1. **Implement the "declared external reference with a key contract"** the skill/
   docstring already promise: let a relationship target a class in another domain by
   referencing that domain's binding output + key columns, without pulling its whole
   binding into scope.
2. **Or support a multi-domain compile scope** so related domains resolve together.
3. **Meanwhile, improve the diagnostic** to name the cause: *"target 'party:Organisation'
   is bound in domain 'party'; cross-domain relationship targets are not supported"* —
   rather than a generic "does not resolve in compile scope".
4. **Document** the intra-domain-only constraint in `kairos-design-mapping` (Gate 6).

### Workaround

Materialize a **scalar soft-FK** on the child (e.g. `equipment:subcontractorReference
← subcontractor_company_id`) and document that it references `party:Organisation`
(`company_id`), leaving the actual join to a downstream/dbt layer. This is not a
compiler-enforced relationship. (In this hub the column's FK evidence is also weak:
nullable, distinctCount 2, `fkConfidence "medium"`, `suggestedForeignKey` = `tenants`.)

---

## ISSUE-6 — Binding term resolution keyed to ontology **filename stem**, not the declared `@prefix`

- **Status:** OPEN (resolver / DX)
- **Severity:** medium-high (a valid ontology + binding fails to compile with a
  misleading "unresolved" error until an unrelated-looking prefix rename)
- **Area:** binding class/property resolver
  (`core/compiler/kernel.py:246, 249, 271` — `domain_prefix = ontology_path.stem`,
  then `class_refs.add(f"{domain_prefix}:{info.name}")` /
  `property_refs.add(f"{domain_prefix}:{prop.name}")`)

### Observed

`equipment.ttl` declared the short prefix `equip:` for its namespace and defined
`equip:Unit`. The binding targeted `equip:Unit`, and compile failed:

```
[error] safety.class-unresolved: target class 'equip:Unit' does not resolve
  (…/qargo-resources-to-equipment.binding.yaml at /target/class) [DD-133]
```

Ontology (as authored — valid Turtle, parses fine in rdflib):

```turtle
@prefix equip: <https://cldn.com/ont/equipment#> .
equip:Unit a owl:Class ; rdfs:subClassOf mmt-eq:TransportEquipment .
```

Binding:

```yaml
target:
  class: equip:Unit          # -> safety.class-unresolved
```

### Root cause

The resolver synthesizes each term's bindable ref from the **ontology filename stem**
(`ontology_path.stem`), not from the `@prefix` declared inside the file. For
`equipment.ttl` the stem is `equipment`, so the only reliably-bindable aliases are
`equipment:Unit`, `equipment:unitReference`, … — never `equip:*`. The `party` domain
worked only because its declared prefix (`party:`) happens to equal its filename stem
(`party.ttl`).

### Fix applied

Renamed the ontology's declared prefix to match the stem (same namespace IRI, purely a
serialization-label change) and used it in the binding:

```turtle
@prefix equipment: <https://cldn.com/ont/equipment#> .
equipment:Unit a owl:Class ; … .
```

```yaml
target:
  class: equipment:Unit      # resolves
```

### Suggested toolkit improvements

1. **Also expose the ontology's declared prefixes** as bindable aliases (carry the
   ttl's `@prefix` map into the resolver), so `equip:Unit` resolves when the file
   declares `equip:`.
2. **Detect the mismatch explicitly:** when `target.class` / field `property` uses a
   prefix that is declared in the ontology but ≠ the filename stem, emit a targeted
   diagnostic (e.g. *"prefix 'equip' is declared but binding resolution uses the
   filename-stem prefix 'equipment'; use 'equipment:Unit'"*) instead of a generic
   `unresolved`.
3. **Document the convention:** a domain ontology's declared prefix must equal its
   filename stem (and the domain name).

---

## ISSUE-5 — `identity.sourceKey` column must also be a materialized field (DD-133)

- **Status:** OPEN (DX / documentation) — same family as ISSUE-4
- **Severity:** medium (forces a mid-mapping ontology change for the identity key)
- **Area:** identity kernel rule `identity.authored-key-not-supplied`
  (`core/compiler/adapter.py:_resolve_identity_output_columns`, `kernel.py`)

### Observed

A `source-natural` identity whose key column is not mapped to any property fails, even
though the key is the table's real not-null unique PK. In
`qargo-resources-to-equipment.binding.yaml`, `resource_id` (uuid, `nullable false`,
`distinctCount = rowCount`) was the identity but was not in `fields:`:

```yaml
identity:
  strategy: source-natural
  sourceKey: [resource_id]     # not mapped to any property
fields:
  - property: equipment:unitReference
    expression: code           # (resource_id absent)
quality:
  - kind: unique
    columns: [resource_id]
```

Errors:

```
[error] identity.authored-key-not-supplied: identity key source column 'resource_id'
  maps to no target property; add a field whose expression is source column
  'resource_id' so it is emitted as an output column …
[error] binding.quality-column-unmapped: quality check column 'resource_id' is a
  SOURCE column, but no field maps source column 'resource_id' to a target output …
```

### Root cause

Like the relationship-FK rule (ISSUE-4), only **field-expression** inputs become
materialized output columns. `identity.sourceKey` and `quality.columns` reference
source columns but do not themselves materialize them, so an identity/quality column
must additionally be a mapped field.

### Fix applied

Added a dedicated property `equipment:resourceId` (the Qargo UUID PK, also the FK other
relations reference) and mapped it, satisfying identity + both quality checks at once:

```turtle
equipment:resourceId a owl:DatatypeProperty ;
    rdfs:label "resource id"@en ;
    rdfs:domain equipment:Unit ; rdfs:range xsd:string .
```

```yaml
fields:
  - property: equipment:resourceId
    expression: resource_id     # now materialized -> identity + quality satisfied
```

### Suggested toolkit improvements

1. **Document** (in `kairos-design-mapping`, alongside ISSUE-4): *"every
   `identity.sourceKey` and `quality.columns` source column must also be mapped as a
   field."*
2. **Or auto-materialize** identity/quality source columns into the Silver projection,
   as with relationship FKs — the identity key is structurally required regardless.
3. This and ISSUE-4 share one root principle worth stating once in the docs: *a source
   column is only "owned"/materialized when a `fields:` expression references it.*

---

## ISSUE-4 — Relationship FK join column must be a mapped scalar field (DD-107)

- **Status:** OPEN (DX / documentation + ergonomics)
- **Severity:** medium (cryptic error; forces a mid-mapping ontology change)
- **Area:** dbt normalizer FK ownership rule
  `mapping.unresolved-join-input` / `DD-107-source-ownership`
  (`core/projections/dbt/normalize.py:205-209, 346-358`)

### Observed

A relationship whose local join column is **not** independently mapped to a scalar
property fails to compile. In `qargo-contacts-to-party.binding.yaml`, the
`contactOrganisation` relationship joins on `company_id`, but `company_id` was not one
of the mapped `fields:` — it only appeared in `grain`, `identity.sourceKey`, and the
relationship `join`:

```yaml
identity:
  strategy: surrogate
  sourceKey: [company_id, name]     # company_id present here …
fields:
  - property: party:contactName
    expression: name                # … but NOT mapped as a field
  # (no field references company_id)
relationships:
  - property: party:contactOrganisation
    target: party:Organisation
    join:
      - local: company_id           # join needs company_id to be an "owned" symbol
        foreign: company_id
```

Result:

```
[error] safety.type-incompatible: projection normalization failed:
  mapping.unresolved-join-input: Silver FK join references a source symbol absent from
  normalized mappings at https://…/source/qargo#contacts/company_id
  [DD-107-source-ownership]
```

### Root cause

`mapping_inputs` is built only from **field-expression** referenced inputs
(`normalize.py:205-209`); `grain`, `identity.sourceKey`, and relationship `join`
columns do **not** make a source column an "owned" symbol. The join can only bind to a
column that some `fields:` expression already references. The toolkit's own example
binding hides this because its `hasCountry` join reuses `country`, which is *also*
mapped (`party:countryCode = upper(country)`):

```yaml
# example-entity-binding.yaml
fields:
  - property: party:countryCode
    expression: { fn: upper, args: [{ column: country }] }   # owns `country`
relationships:
  - property: party:hasCountry
    join: [{ local: country, foreign: iso2 }]                 # reuses owned `country`
```

### Fix applied in this hub

Added a scalar FK property `party:contactOrganisationReference` (xsd:string,
domain `ContactPerson`) mapping `company_id`, so the FK becomes an owned column:

```yaml
fields:
  - property: party:contactOrganisationReference
    expression: company_id          # now company_id is materialized/owned
```

This required an ontology bump (party.ttl v0.4.0 → v0.5.0) **in the middle of a mapping
task**, which the mapping skill does not lead you to expect.

### Suggested toolkit improvements

1. **Document the rule** in `kairos-design-mapping` (Gate 6 / relationships): *"a
   relationship's local join column must also be mapped as a scalar field, or the FK
   cannot be materialized."*
2. **Improve the message** from `references a source symbol absent from normalized
   mappings` to something actionable, e.g. *"FK join column 'company_id' is not
   materialized; add a `fields:` entry mapping it to a scalar property."*
3. **Ideal:** have the compiler **auto-materialize** a relationship's local join column
   into the Silver projection (it is structurally required), removing the need for a
   synthetic FK property such as `contactOrganisationReference`.

---

## ISSUE-3 — Binding property resolution is ambiguous for inherited reference-model properties

- **Status:** OPEN (resolver correctness + DX)
- **Severity:** high (blocks legitimate subproperty modelling; suggested fix is
  un-followable)
- **Area:** binding property resolver / qname synthesis
  (`core/compiler/kernel.py:245-277`, `core/compiler/adapter.py:683-698`,
  `_qnames` at `kernel.py:100-107`)

### Observed

Defining a hub subproperty whose **local name matches an inherited reference-model
property** makes the domain-qualified ref ambiguous and un-bindable.

Context: `party:ContactPerson ⊂ bsp-pt:Contact`, and BSP already defines
`contactName`, `contactEmail`, `contactPhone`, `jobTitle`. I first modelled cldn
subproperties with the **same local names**:

```turtle
# party.ttl (first attempt)
party:contactName a owl:DatatypeProperty ;
    rdfs:subPropertyOf bsp-pt:contactName ;      # same local name as the parent
    rdfs:domain party:ContactPerson ; rdfs:range xsd:string .
```

Binding those fields failed:

```yaml
fields:
  - property: party:contactName     # -> binding.ambiguous-property
    expression: name
```

```
[error] binding.ambiguous-property: property 'party:contactName' is ambiguous; it
  resolves to 2 distinct ontology properties (https://cldn.com/ont/party#contactName,
  https://www.kairosflow.ai/ont/bsp/party#contactName); qualify the field with the
  owning namespace prefix
```

Following that advice does **not** work — the reference-model prefix does not resolve:

```yaml
fields:
  - property: bsp-pt:contactName    # -> safety.property-unresolved
    expression: name
```

### Root cause

For **every** property in the class closure (including inherited, cross-namespace
ones), the resolver synthesizes a `"<domain_prefix>:<localName>"` alias
(`kernel.py:271`: `property_refs.add(f"{domain_prefix}:{prop.name}")`). So both
`cldn#contactName` and inherited `bsp#contactName` get the alias `party:contactName`
→ two distinct URIs share one ref → `binding.ambiguous-property`
(`adapter.py:683-698`).

The only *other* ref offered is rdflib's computed qname
(`_qnames` → `compute_qname(uri, generate=False)`). The BSP ontology binds its own
namespace to the **empty prefix** (`@prefix : <…/bsp/party#>` in
`ontology-reference-models/derived-ontologies/BSP/current/party/party.ttl:1`), so the
alias exposed is `:contactName`, **not** the `bsp-pt:` prefix declared in party.ttl.
Hence the error's suggestion to "qualify with the owning namespace prefix" is
effectively un-followable with any predictable prefix.

### Workaround used

Removed the four duplicate cldn subproperties and bound the fields directly to the
inherited BSP properties via the domain alias (unique local name → unambiguous):

```turtle
# party.ttl (final) — no cldn contactName/Email/Phone/jobTitle; ContactPerson just
# inherits bsp-pt:contactName etc. through ⊂ bsp-pt:Contact
party:ContactPerson a owl:Class ; rdfs:subClassOf bsp-pt:Contact .
```

```yaml
fields:
  - property: party:contactName     # now resolves uniquely to bsp#contactName
    expression: name
```

This matches the existing convention elsewhere (e.g. `organisationName ⊂
bsp-pt:partyName` uses a **distinct** local name to avoid the collision).

### Suggested toolkit improvements

1. **Prefer the exact domain-namespace hit.** When `party:contactName` matches one
   property actually in the party namespace plus others only via the synthesized
   inherited alias, resolve to the domain-namespace property instead of erroring — the
   author qualified with the domain prefix and a property exists there.
2. **Make disambiguation possible.** Carry the hub ontology's declared prefixes
   (party.ttl's `bsp-pt:`) into the resolution `namespace_manager`, and/or accept a
   full-IRI ref, so the "qualify with the owning namespace prefix" advice actually
   works.
3. **List usable refs in the error.** Show the exact bindable tokens (e.g.
   `:contactName` vs `party:contactName`) rather than only the URIs.
4. **Document the convention** in `kairos-design-domain`: when subclassing a reference
   model, give hub subproperties **distinct** local names, or bind directly to the
   inherited property.

---

## ISSUE-2 — `compile --emit` output tree does not match scaffolded projection slots

- **Status:** OPEN (needs toolkit clarification / decision)
- **Severity:** medium (DX / layout correctness; artifacts can land in the wrong place
  and get committed)
- **Area:** `kairos-ontology compile <domain> --emit <directory>` (dbt projector)

### Observed

Running:

```powershell
uv run kairos-ontology compile party --emit output
```

produced a **domain-centric** tree:

```
output/party/
  dbt_project.yml
  packages.yml
  README.md                     (title: "dbt Project — party_project")
  models/silver/party/organisation.sql
  models/silver/_qargo__sources.yml
  models/silver/party/_party__models.yml
  analyses/party/party-ddl.sql
  docs/diagrams/party/party-erd.mmd
  metadata/party-silver-constraints.json
  metadata/party-silver-parity.json
  .kairos-compile-manifest.json
```

### Expected / scaffolded layout

The hub scaffold pre-provisions **projection-centric** output slots (each with a
`.gitkeep`):

```
output/
  a2ui/
  architecture/ddd/
  azure-search/
  mdm/
  medallion/dbt/          <-- dbt projection presumably belongs here
  medallion/powerbi/
  neo4j/
  prompt/
  reports/
```

### Problem

1. `--emit` writes a self-contained per-domain tree under `output/<domain>/` and
   ignores the scaffolded projection slots. The dbt project does **not** land in
   `output/medallion/dbt/`, and non-dbt artifacts (`analyses/`, `docs/diagrams/`,
   `metadata/`) are mixed into the same `<domain>/` folder rather than the
   corresponding projection slots.
2. `--emit DIRECTORY` has no per-projection targeting and no default tied to the
   scaffold, so a natural `--emit output` misplaces everything at the top level.
3. Each domain emit is a **standalone dbt project** (its own `dbt_project.yml` /
   `packages.yml`). Emitting several domains into one directory yields multiple
   separate dbt projects (`output/.../booking`, `output/.../party`), not one unified
   project under `medallion/dbt`. Whether that is intended is unclear.
4. `output/` is git-tracked here (no `.gitignore` entry), so a misplaced emit would be
   committed.

### Reproduction

1. Hub with scaffolded `output/medallion/dbt/.gitkeep` etc.
2. `uv run kairos-ontology compile party --emit output`
3. Observe `output/party/…` instead of `output/medallion/dbt/…`.

### Open questions for the toolkit

- What is the canonical emit target for the dbt projection — `output/medallion/dbt`,
  and should non-dbt projections (ERD/docs, metadata) route to their own slots?
- Should `--emit` be projection-aware (populate `medallion/dbt`, `medallion/powerbi`,
  `neo4j`, `azure-search`, … from one command), or is domain-centric `output/<domain>/`
  the intended v5 layout and the scaffolded slots are stale?
- Should there be a configured default emit directory in `kairos.yaml`?

### Workaround (unconfirmed)

Emit explicitly into the dbt slot, e.g. `--emit output/medallion/dbt` (produces
`output/medallion/dbt/<domain>/…`). This still mixes non-dbt artifacts under the dbt
slot, so it is a stopgap only.

---

## ISSUE-1 — `source-natural` identity rejected by DD-108-business-identity

- **Status:** RESOLVED in `feature/v5-stage2-4` (verified 2026-07-28)
- **Upstream:** https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/245
- **Area:** static-safety identity rule `identity.authored-key-not-supplied`
  (`DD-108-business-identity`)

### Summary

Previously, a valid `source-natural` `EntityBinding` was rejected whenever the identity
key **source column name** did not equal the snake-cased **local name of a mapped
ontology property**, coupling physical column naming to ontology property naming.

### Verification

On `feature/v5-stage2-4`, `integration/bindings/qargo-to-booking.binding.yaml` was
switched from the `surrogate` workaround back to the semantically-correct
`source-natural` identity on the order-reference column `name`:

```powershell
uv run kairos-ontology compile booking --check   # -> passed
uv run kairos-ontology compile booking --explain # -> identity_strategy: source-natural
```

The same pattern also compiles for `qargo.companies -> party:Organisation`
(`source-natural` on `company_id`). The disputed rule no longer blocks these cases.
Issue #245 can likely be closed after a maintainer confirms the intended new rule
semantics.

---

## OBS-1 — `ontology-reference-models/VERSION` absent

- **Status:** OPEN (minor)
- **Area:** reference-model versioning / `check-inventory --explain-scope`

`check-inventory` reports the local reference-model version from
`ontology-reference-models/VERSION`, which does not exist in this hub, so the version is
reported as `unknown`. Scoped inventories still resolve as up to date; this only affects
version reporting/traceability.

---

## OBS-2 — `tenant_id` leaked into Bronze (source/ingestion, not toolkit)

- **Status:** NOTE (source ingestion)
- **Area:** Qargo source vocabularies (`companies`, `contacts`, …)

Per business confirmation, Qargo `tenant_id` is a system/environment identifier
(prod vs non-prod) that should not have reached Bronze. It carries no canonical business
meaning and is excluded from ontology models and bindings. Recorded here so the ingestion
side can strip it upstream.
