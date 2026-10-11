# Carrying the logical data model as a DDD overlay, without coupling it to the Silver contract

Written 2026-09-19 against toolkit `5.18.0rc1` (hub pin) / `5.18.0rc2` (current), source read at
`G:\Git\kairos-ontology-toolkit\src\kairos_ontology`. Input: the Enterprise Architect export at
`.import/businessdiscovery/customerinput/logicaldatamodel/Fracht - Logical Data Model export.xml`
(EA 2.5, XMI 1.1, exported 2026-09-15), scoped to the three subject areas the business asked for —
**Fracht Entities**, **Consignments**, **Transport Plans**.

## 0. The question

The architect's logical model is deliberately broader than anything we can bind today. It names
concepts with no source column behind them, it draws aggregate boundaries, and it separates
concerns (address, geography, organisational structure) that our Silver layer keeps pragmatically
merged. Two worries follow:

1. If we put the logical model into the ontology, does it force its way into the Silver contract?
2. If DDD wants a boundary that Silver does not want — Address as its own context, say — do we have
   to choose?

**No to both.** The hub already has the layering to hold all three readings at once, and the
toolkit ships the vocabulary. This note records why, and what it constrains.

---

## 1. The load-bearing fact: Silver is a subset by construction

The Silver contract's entity set **is** the binding set. `compiler/contract_scaffold.py`
(`build_contract_document`) iterates `plan.bindings`; `CompilePlan` (`compiler/plan.py`) carries
`bindings: tuple[EntityBinding, ...]` and **no class inventory at all**. An `owl:Class` that no
binding targets never enters the plan.

So an unbound class is a *benign omission* — not an error, and in the v5 canonical compile path not
even a warning. Every `code="..."` diagnostic literal in `core/compiler/` (58 of them) was
enumerated; none concerns an unbound class. The only adjacent gate is `scope.no-bindings-authored`,
which fires when a domain has **zero** bindings, and is documented as an expected early stage
rather than a fault:

> Ontology-only waypoint: the hub has a valid ontology slice but no EntityBinding authored yet.
> Distinct from a genuine source-resolution failure so a CI gate can tell an expected early stage
> apart from a broken binding.

**We already rely on this.** `reference-data#RegionCode` is authored with four properties and no
binding. It appears in zero contracts, zero Silver models, zero ERDs; nothing fails.
`HUB-DD-20260907-23c51f.md` records the outcome as accepted: *"Until the seed exists Silver and Gold
are unchanged; nothing was emitted for this slice."* Current arithmetic: **44 authored classes, 45
bindings, 43 classes bound, 1 deliberately not.**

The governance gate runs the *other* way. Once a domain has a contract, a binding whose
`target.class` is not declared in it fails with `contract.class-not-declared` —
*"a governed domain cannot silently regrow ungoverned entities"* (`compiler/contract_conformance.py`).
That protects Silver from the ontology; it never constrains the ontology from Silver.

> **Invariant to hold on to:** the ontology may run ahead of the sources. Growing it does not grow
> Silver. Only authoring a binding grows Silver.

---

## 2. Bounded context and physical domain are orthogonal

Nothing in the compiler derives a class's domain from the ontology graph. Two filename/YAML
mechanisms do it:

1. the binding declares it — `metadata.domain` is required by `entity-binding.schema.json`, read at
   `compiler/kernel.py:2703` as *"the scope discriminator"*;
2. the compiler resolves the TTL by that name — `kernel.py:844`,
   `root / "model" / "ontologies" / f"{domain}.ttl"`.

`kairos-ddd:boundedContext` is a free annotation living in a separate overlay file. It can slice the
class universe along entirely different lines from the 15 domain TTLs — several domains into one
context, or one domain across several contexts — and the compiler is blind to it.

**This is the answer to the Address question** (§6).

---

## 3. What the toolkit ships

`kairos-ddd:` — namespace `https://kairos.cnext.eu/ddd#`, introduced as DD-091 in toolkit
`4.4.0rc17` (2026-07-05). Vocabulary at `scaffold/kairos-ddd.ttl`, shapes at
`scaffold/kairos-ddd-shapes.shacl.ttl`. Its own header states the contract:

> It is architecture-documentation only (DD-091): it never drives silver/gold/dbt/Power BI
> generation, and it is NOT a governance source.

**Classes:** `BoundedContext`, `ContextRelationship`, `TacticalPattern`, `ContextRelationshipPattern`.

**Annotation properties:** `boundedContext`, `tacticalPattern`, `aggregateRoot`, `publishedLanguage`,
`designNote`, `sourceContext`, `targetContext`, `relationshipPattern`.

**Controlled tactical individuals** (SHACL-closed): `AggregateRoot`, `AggregateMember`, `Entity`,
`ValueObject`, `DomainService`, `DomainEvent`, `Policy`.

**Controlled context-map patterns:** `SharedKernel`, `CustomerSupplier`, `Conformist`,
`AnticorruptionLayer`, `OpenHostService`, `PublishedLanguage`, `SeparateWays`.

**Tooling.** `kairos-ontology validate --ddd` (`cli/validation.py:446`) and
`kairos-ontology project --target ddd` → `architecture/ddd/` (`core/projector.py:246`), emitting
`{domain}-context-map.mmd`, `{domain}-aggregate-overview.mmd`, `{domain}-ddd-report.md`.

**No hub-local installation is required.** `core/ddd.py` loads vocabulary and shapes from the
installed package *"so that hubs that predate the feature validate correctly without a hub-local
copy."* No `catalog-v001.xml` entry, no `_foundation.ttl` change, no `_master.ttl` import.

### The firewall

Three independent mechanisms keep the overlay out of the emission path:

1. **File segregation.** Overlays must be `model/extensions/{domain}-ddd-ext.ttl`
   (`core/ddd.py`, `_OVERLAY_SUFFIX`). Domain ontologies must stay free of DDD concerns (R1).
2. **Active leak detection.** `_scan_ext_leak` scans the overlay *alone* and **fails** it if any
   `kairos-ext:silver*` or `kairos-ext:gold*` predicate appears in it.
3. **The compiler never opens the file.** `compile` reads exactly one extension file per domain,
   `model/extensions/{domain}-gold-ext.ttl` (`kernel.py:1481`). The DDD projection is separately
   gated on the overlay existing (`projector.py:521`).

Adding an overlay therefore cannot change a contract, a Silver model, a Gold table or an ERD. It
*will* move `metadata/<domain>.provenance.json` input hashes only if we touch a domain TTL — the
overlay itself is not a compile input.

### One operational note

The projection writes to `ontology-hub-publish/architecture/ddd/`, which is gitignored by
`ontology-hub-publish/**` (`.gitignore:74`; the projection-output block above it explains the
allowlist, and §13 explains why the `architecture/**` exception is missing here). The output is therefore **untracked working-tree material**, regenerated on demand. If
we want the diagrams reviewed in a PR diff, they have to be copied somewhere tracked — the same
problem toolkit 5.18.0rc1 solved for contract ERDs by moving them into
`ontology-hub/model/contracts/diagrams/`. Do not widen the ignore silently; see `CICD.md`.

---

## 4. What is actually in the EA export

**Structural correction worth knowing before reading the file:** "Fracht Entities", "Consignments"
and "Transport Plans" are **EA diagrams, not packages**. The model has exactly two packages
(`Logical Data Model`, 118 classes, and `Logical Data Model/Customer Grouping`, 3). Subject-area
membership exists *only* as diagram membership — there is no model-level classification to import.
"Transport Plans" is spelled `TransportPlan` in the file.

| | Classes |
|---|---|
| Whole model | 122 |
| minus EA junk (`EARootClass`, `Class1`–`Class4`, `None`) | 116 |
| Fracht Entities / Consignments / TransportPlan (union, 9 shared placements removed) | **54** |

So the three areas are ~47% of the real model. Also present: 118 attributes (only 40 classes carry
any), 99 associations, 49 generalizations, 13 datatypes, 10 comments.

**The architect already used a light DDD vocabulary.** Stereotype counts: `BusinessEntity` ×45,
`ValueObject` ×11 (in scope: only `InformedParty`), `enumeration` ×1 (`ConsignmentType`), none ×65.
There is **no aggregate-root stereotype and no subject-area marker** — aggregate boundaries exist
only as `composite`/`Aggregation` association ends.

**The seven composite ends in scope** — these are the aggregates:

| Root | Members |
|---|---|
| `Consignment` | `ConsignmentItem`, `ConsignmentNote`, `InformedParty` |
| `Route` | `TransportLeg` (`ea_type=Aggregation`, "consists of") |
| `TransportPlan` | `Route` ("defines") |
| `OrganizationalUnit` | `Position` ("has") |
| `LegalEntity` | `EntityLocation` ("is headquarter of") |
| `FrachtEntity` (the 2026-08-25 one) | `EntityPosition` ("has") |

**Documentation is nearly absent** — 12 of 122 classes, 5 of them in scope, all one-liners
(`Consignee`, `Carrier`, `CustomsBroker`, `ForwardingAgent`, `NotifyParty (to review)`). The real
design intent is in six notes, and **four of them are open questions** (§8). No `AssociationEnd`
role names are populated anywhere; 19 of 99 associations are unnamed.

### Mapping table

| EA construct | Encoded as | Where |
|---|---|---|
| `BusinessEntity` stereotype | `kairos-ddd:tacticalPattern kairos-ddd:Entity` | `{domain}-ddd-ext.ttl` |
| `ValueObject` stereotype | `tacticalPattern kairos-ddd:ValueObject` | overlay |
| Composite / `Aggregation` end | `AggregateRoot` on the owner; `AggregateMember` + `kairos-ddd:aggregateRoot` on the member | overlay |
| Diagram (subject area) | `kairos-ddd:boundedContext` + a `BoundedContext` individual | overlay |
| Class + attributes | `owl:Class` + `owl:DatatypeProperty` — bound or not | `model/ontologies/{domain}.ttl` |
| Generalization | `rdfs:subClassOf` | domain TTL |
| Association | `owl:ObjectProperty` with `rdfs:domain`/`rdfs:range` | domain TTL |
| Multiplicity | `owl:Restriction` min/maxCardinality | domain TTL — ignored by compile, honoured by the ERD projector |
| Note / open question | `kairos-ddd:designNote` + a decision record | overlay + `decisions/` |
| `enumeration` (`ConsignmentType`) | `skos:ConceptScheme` + `skos:Concept`, per the hub's existing closed-code-list pattern | domain TTL + SHACL |

On multiplicity: the compiler runs the **RDFS** profile (`kernel.py:679`), under which
`semantic_index.py` records no restrictions at all (`design = profile in {KAIROS_DESIGN, OWL_RL}`).
Compiled cardinality comes from the binding's `relationships[].cardinality`. OWL restrictions are
therefore emission-neutral and read only by `projections/erd_projector.py::_effective_bounds` — the
one place in the toolkit that honours them. That makes them the right home for the EA
multiplicities.

Also relevant: `project --target erd` walks `owl:Class`/`owl:ObjectProperty`/`rdfs:subClassOf`
directly off the graph, *"independent of EntityBinding/compile-plan coverage"*, explicitly so that a
class *"modeled but not yet bound … is still visible in at least one diagram output."* That is our
logical-model view.

---

## 5. Rules the overlay must respect

Verified against `core/ddd.py` and `scaffold/kairos-ddd-shapes.shacl.ttl`:

1. **One overlay per domain, annotating that domain's own classes.** `validate_ddd_overlay` builds
   the merged graph from `{domain}.ttl` **plus that file's import closure** plus the overlay plus
   the vocabulary. Nothing else is in scope.
2. **`aggregateRoot` must resolve to an `owl:Class` in that merged graph** (Rule 4). A
   cross-domain aggregate edge only validates if the child's domain TTL imports the root's domain.
   `consignment.ttl` currently imports `mmt/consignment`, `dcsa/shipment-journey`, `reference-data`,
   `fracht-company`, `route-schedule` — **not `party`**. This is the single place where our physical
   layering constrains the DDD layering.
3. **An `AggregateMember` must declare its `aggregateRoot`** (Rule 3, SPARQL constraint).
4. **`tacticalPattern` values are closed** to the seven individuals (Rule 2).
5. **Every `BoundedContext` needs an `rdfs:label`** (Rule 1).
6. **`ContextRelationship` needs source, target and pattern, with both endpoints typed
   `BoundedContext` in the merged graph** (Rules 5/6). Practical consequence: **keep the context map
   — the relationship edges and the context declarations — in a single overlay.** Other overlays
   reference contexts by IRI via `boundedContext`.
7. **No `kairos-ext:silver*`/`gold*` predicates in an overlay**, enforced in Python.

---

## 6. The worked tension: Address

DDD wants `Address` as its own bounded context. Silver wants it in `party`, because CargoWise is the
only source and party is the only consumer. Today `party#PostalAddress` ([party.ttl:471]) is bound
by `cargowise-postal-address.binding.yaml` with `metadata.domain: party`, and is referenced by
`cargowise-address-channel` and `cargowise-contact-channel`.

**Both readings hold simultaneously. Annotate; do not move.**

```turtle
# model/extensions/party-ddd-ext.ttl
party:PostalAddress
    kairos-ddd:boundedContext ctx:AddressContext ;
    kairos-ddd:tacticalPattern kairos-ddd:ValueObject ;
    kairos-ddd:designNote "Physically resident in the party domain: CargoWise is the only source and party the only consumer, so a separate domain would buy a folder and cost a cross-domain externalReference on every join. The context boundary is architectural; revisit the physical split only on a physical trigger." .
```

The class stays in `party.ttl`, in `models/silver/party/`, in `party.contract.yaml`. The context map
renders `AddressContext` as its own subgraph. Cost: three triples.

**What moving it would actually cost**, for contrast — new `address.ttl`, `_master.ttl` import and
catalog entry; binding `metadata.domain` change; the Silver model moves folder; a new
`address.contract.yaml`; a new `address-gold-ext.ttl` whose `goldSourceVersion` must stay pinned in
lockstep with the TTL's `owl:versionInfo` or `gold.source-version-drift` errors; the two referencing
bindings convert from same-domain joins to `externalReference` blocks; `party.ttl` gains an
`owl:imports`; version bumps, ERD regeneration, provenance churn; and downstream dbt refs in the
dataplatform repo break.

**Move a class only on a physical trigger** — a second source system binds it, it acquires its own
release cadence or owner, or the host TTL stops being reviewable. Never because the DDD picture
wants a box: the overlay already draws the box.

---

## 7. What this does *not* give us

| Want | Status | Workaround |
|---|---|---|
| Invariants in the ontology | **No vocabulary.** `designNote` is free prose. | SHACL in `model/shapes/` (validate-time) or a `DataQualityRule` in the binding (runtime dbt test) |
| Declare a class *intentionally* unbound | **No class-level ledger.** The disposition ledger (`integration/sources/_analysis/table-dispositions.yaml`, where an undisposed table is an error) covers source **tables** only. | A decision record per batch. `design-landscape` classifies such classes `demanded-but-unbound` / `no-evidence` — advisory, never a gate |
| DDD driving generation | **Architecturally refused**, and actively policed by `_scan_ext_leak`. | — |
| EA / XMI round-trip | **Out of scope**, stated in the DD-091 changelog entry. | A one-off translation script in the hub |
| Aggregates shaping Silver | **Absent.** `grep -i "cascade\|embedded\|composition\|aggregate"` over `core/compiler/` returns zero. Every binding relationship is a child→parent FK, `many-to-one` or `one-to-one`; there is no `one-to-many`, so no direction in which a parent owns children. `missingParent: error\|null` is row-lookup policy, not lifecycle. | Each bound class is one flat Silver table. By design |

One caveat on maturity: the DDD overlay has had **no changelog entry since its 4.4.0rc17
introduction**. It validates and it renders, but it has no downstream consumer and should be treated
as a stable documentation feature, not an evolving one.

---

## 8. Open questions for the architect

Carried from the EA notes; each wants a `designNote` and, once answered, a decision record.

1. **"Should realize a separation of Legal structure / Geographical classification / Organizational
   Structure / Reporting Structure."** Unattached note on the Fracht Entities diagram. This is the
   big one, and it is visibly unresolved *in the export*: the diagram contains **two `FrachtEntity`,
   two `Region`, two `Country` and two `Location`** — a geography tree and an organisational tree
   reusing the same names. The newer `FrachtEntity` (2026-09-15, `BusinessEntity`) is the one wired
   into Consignments; the 2026-08-25 one carries the `OrganizationalUnit` generalisation and the
   `EntityPosition` composition. **Choosing the wrong one silently drops half the relationships**,
   so Fracht Entities cannot be encoded faithfully until this is settled.
2. **"equivalent?"** — attached to both `Route` and `TransportPlan`. If they are the same concept,
   the `TransportPlan --defines--> Route --consists of--> TransportLeg` chain collapses by a level
   and the aggregate root changes.
3. **"uncertain which party roles are linked to which concept"** — on `Role`. Bears directly on our
   own open party-role-assignment work.
4. **"Multiple possible? link to consignment, consignment item or Transport plan?"** — on
   `TransportEquipment`.
5. **"or via party role?"** — on `FrachtEntity`.
6. **Ports derived from legs** — the note on `TransportLeg` says port of loading, port of discharge,
   place of receipt, place of delivery and trans-shipment should all be *derived from the legs* via
   specialised origin/destination roles, rather than held on the consignment. That is the intent
   behind the four unnamed `Location` associations on `MasterConsignment`/`HouseConsignment`, and it
   conflicts with how we bind load/discharge ports today.

Lower-priority hygiene: `Container.type` points at an unresolvable `xmi.id`; `(to review)` in a class
name is the architect's own uncertainty marker (`NotifyParty`, `BillTo`, `ImporterOfRecord`,
`ExpoterOfRecord`); `Customs`, `HouseConsignment` and `EquipmentAssignment` are bare placeholders.

---

## 9. Adoption path

1. **Dry run** — overlays for domains that already have classes, covering only classes that already
   exist. Run `validate --ddd` and `project --target ddd`. Zero contract impact, fully revertible.
2. **Review with the architect** — put the generated context map and aggregate overview next to his
   EA diagrams, and use §8 to close the open questions.
3. **Extend the canonical TTLs** with his classes, properties and multiplicities once the shape is
   agreed — unbound, per §1, with a decision record stating the intent.
4. **Bind selectively**, only where source evidence exists, via the normal
   `kairos-design-mapping` route. Silver grows deliberately, one binding at a time.

Steps 1–3 never touch Silver. Step 4 is the only one that does, and it is the existing, governed
path.

---

## 10. Dry run — executed 2026-09-19, branch `model/fracht-organisation-consignment_20260919`

Four overlays authored over classes that already exist, annotating nothing new:

| Overlay | Classes | Contexts |
|---|---|---|
| `consignment-ddd-ext.ttl` | `MasterConsignmentRecord`, `HouseConsignmentRecord`, `TransportLegRecord` | all five declared + the whole context map |
| `party-ddd-ext.ttl` | `Party`, `PartyContact`, `PartyIdentification`, `PartyRole`, `ConsignmentPartyRoleAssignment`, `PostalAddress`, `ContactPoint` | Party, Address, Consignment |
| `fracht-company-ddd-ext.ttl` | `FrachtLegalEntity`, `FrachtBranch`, `FrachtStaffMember`, `Job` | Fracht Organisation |
| `route-schedule-ddd-ext.ttl` | `SailingScheduleRecord`, `TransportCallRecord` | Transport Plan |

### Results

- `validate --ddd` → **4 overlays, 0 failed.**
- `project --target ddd` → **12 files**, correctly gated: the 11 domains without an overlay produced
  nothing.
- `compile --all --check` → **15/15 domains pass.** The only warnings are pre-existing
  (`safety.prefix-ambiguous` on party/route-schedule/vessel-maritime,
  `relationship.unrealized-technical-field` on `cargowise-maritime-voyage`, and the dbt render-scope
  notes on copied intermediates).
- `git status` → the four overlays and this document. **No contract, Silver model, ERD or Gold
  artifact changed.** §1 and §3 hold in practice, not just in the source.

### Two findings the dry run surfaced

1. **The context map renders only for the domain whose overlay declares the edges.**
   `party-ddd-report.md` says *"No context relationships declared"* even though `party-ddd-ext.ttl`
   declares three contexts, because the `ContextRelationship` individuals live in
   `consignment-ddd-ext.ttl`. This follows directly from per-domain merged-graph validation (§5.1)
   and is not a defect, but it means **`consignment-ddd-report.md` is the hub-wide architecture
   document** and the other three are domain-local views. Worth stating wherever we publish them.
2. **Bounded-context individuals have to be redeclared in every overlay that references them.**
   Also a consequence of §5.1. The duplication is idempotent in RDF and cheap, but it is
   hand-maintained: a label changed in one overlay and not the others will render inconsistently
   across reports. A shared `contexts-ddd-ext.ttl` is not an option — overlays are discovered by the
   `{domain}-ddd-ext.ttl` pattern and merged only with their matching domain TTL.

### Two things the overlays deliberately record as disagreements

Both are the pilot doing its job — making a modelling question visible rather than silently picking
a side:

- **`TransportLegRecord` sits in the Transport Plan context but is rooted on
  `MasterConsignmentRecord` in the Consignment context.** An aggregate spanning a context boundary
  is a smell. It exists because EA roots the leg on `Route` and `Route` on `TransportPlan`, and the
  hub has neither class. Resolving the architect's "equivalent?" note (§8.2) resolves this.
- **`ConsignmentPartyRoleAssignment` is hosted in the party domain but belongs to the Consignment
  context.** Rooting it on the house consignment instead would not validate from `party-ddd-ext.ttl`
  regardless, since `aggregateRoot` must resolve inside the domain's import closure and `party.ttl`
  imports `consignment.ttl` rather than the reverse — a concrete instance of §5.2.

### Not yet decided

The EA export itself (`.import/businessdiscovery/customerinput/logicaldatamodel/`, ~950 KB) is
currently untracked and *not* gitignored, so it would be committed along with this branch. Confirm
that is wanted before committing — it is customer input, and `.import/` holds other evidence whose
tracking was decided case by case.

---

## 11. Visualisation: what to render where

### Mermaid is the source of truth

`.mmd` is already the hub's convention — the contract ERDs live in
`ontology-hub/model/contracts/diagrams/`, and toolkit 5.18.0rc1 deliberately moved them *into* the
authored hub so they would be reviewed in the PR diff. The properties that matter: generated from
the ontology on every run so it cannot drift, sorted with no embedded timestamps so diffs are
semantic, and rendered natively by GitHub, VS Code and Azure DevOps wikis.

Two limits, both specific:

1. **The context map drops information.** The projector renders `-->|Customer-Supplier|` and nothing
   else. Standard DDD context-map notation — upstream/downstream `U`/`D` markers, ACL/OHS/PL boxes
   on the edge — is not emitted, and `kairos-ddd:publishedLanguage` does not appear in the diagram at
   all (it is a column in the `.md` report). **The artifact is the `.mmd` + `.md` pair, never the
   diagram alone.**
2. **`graph LR` degrades past roughly 10–12 nodes.** Fine at five contexts; a problem if we go to one
   context per EA subject area across all thirteen diagrams.

### What Lucidchart can and cannot express

Checked against `lucid://diagram-specification` and `lucid://endpoint-styles`.

| Our construct | Lucid |
|---|---|
| Aggregate membership | ✅ `composition` / `aggregation` endpoint styles — true UML diamonds |
| `rdfs:subClassOf` | ✅ `generalization` endpoint |
| Class with typed attributes | ✅ `umlClass` — title / properties / methods compartments |
| Bounded context grouping | ✅ `rectangleContainer` with `containerTitle`, `assistedLayout` |
| EA multiplicities | ✅ crow's-foot endpoints (`one`, `many`, `zeroOrMore`, `oneOrMore`, …) |
| Context relationship | ✅ line with positioned label |
| `designNote` | ✅ per-shape `note` |
| Class IRI / provenance | ✅ `customData` key-value pairs — **Mermaid cannot do this** |
| **The 7 tactical patterns** | ❌ no stereotype slot on `umlClass`, and its fields are plain text only |
| **The 7 context-map patterns** | ❌ no native notation (same as Mermaid) |
| **A DDD shape library** | ❌ the named libraries are AWS / GCP / Azure icon sets only |

So Lucid gives us all the UML *structure* and none of the DDD *vocabulary*. The workaround is
arguably better than what it replaces: `style.fill` is per-shape, so colour-code by tactical pattern
and put the pattern in `customData`. A legend plus consistent colour reads faster than `«AggregateRoot»`
repeated on forty boxes.

### The rule that matters more than the format

**A Lucid document is a snapshot; the `.mmd` is generated.** The moment someone edits the board it
disagrees with the hub — which is exactly the failure mode we are trying to escape, given that the EA
model is already internally unreconciled (§8.1). So: **Lucid is a rendering, never a source.**
Regenerate it, do not hand-edit it. Workshop annotations come back as overlay or ontology edits and
the board is regenerated. If we cannot hold that line we have simply bought a second EA.

### Test result — Mermaid → Lucid does NOT work (2026-09-19)

`lucid_create_diagram_from_mermaid` was given the generated `consignment-context-map.mmd` verbatim.
**It returns HTTP success and a document id, but produces an empty placeholder.** Fetching the page
returns exactly one item:

```
"shapeType": "Mermaid Diagram Zero State",
"BlockClass": "LucidNativeMermaidDiagramZeroStateBlock",
"BoundingBox": "x: 0, y: 0, w: 368, h: 148"
```

No shapes, no lines. `lucid_search_document` finds none of "Consignment", "Address", "Party",
"Customer-Supplier" or "Conformist" — not even the Mermaid source is stored as searchable text. A PNG
export shows a grey code-block placeholder with three generic empty boxes.

A controlled retry with the leading `%%` comment removed produced an **identical** zero-state block,
so the toolkit's provenance comment is not the cause.

Documents created by the test, both safe to trash:
`81b4397f-ed06-4aee-a19f-d0b0776d22b8`, `509a2756-468d-4528-be6b-522e8f84ab11`.

**Caveat, not yet ruled out:** the Lucid editor may render a Mermaid block client-side from stored
source, in which case a human opening the link could see the diagram even though the server-side
representation is empty. Against that reading: the block class is literally *Zero State*, the PNG
export is blank, and the source text is not searchable. Opening the edit URL settles it in ten
seconds and should be done before anyone relies on this path.

### Recommendation

- **Keep `.mmd` as the committed, diffable source of truth.** Unaffected by any of the above.
- **Do not build on the Mermaid → Lucid route** until the zero-state behaviour is understood. It
  reports success while producing nothing, which is worse than failing.
- **If we want Lucid, use `create_diagram_from_specification`** with hand-built Standard Import JSON.
  It is where `composition`/`generalization` endpoints, `umlClass` compartments, per-context
  containers and `customData` IRIs actually buy fidelity over Mermaid — and it can be checked before
  a document exists via `lucid_validate_diagram_specification`. Cost: the geometry preflight is
  strict (size shapes from content, 60 px pairwise clearance, 80 px container padding, connector-path
  and label-collision checks), so this is a generator to write once, not a diagram to hand-draw.
- **Publishing to Lucid sends hub content to an external service.** Keep it an explicit, per-occasion
  decision rather than a step in any automated lane.

---

## 12. `tools/ddd_context_erd.py` — the context-scoped generator

Built 2026-09-19. Closes the gap in §11: the toolkit has two diagram targets and **neither draws a
bounded context**, because both select by file.

| Target | Selects by | Draws |
|---|---|---|
| `project --target erd` | domain TTL | one `classDiagram` per domain, full member list incl. inherited |
| `project --target ddd` | domain TTL + overlay | minimal aggregate overview; context map only for the domain declaring the edges |
| `tools/ddd_context_erd.py` | `kairos-ddd:boundedContext` | one `classDiagram` per **context**, cross-domain by construction |

Mermaid's `classDiagram` turns out to express the entire overlay: `<<AggregateRoot>>` annotations for
the seven tactical patterns, `namespace` blocks for contexts, `*--` for aggregate membership, `<|--`
for `rdfs:subClassOf`, quoted multiplicities, and `note for`. The result is the closest hub-side
counterpart to the architect's EA subject-area diagrams, and **strictly more than the toolkit's
`.mmd` + `.md` pair**, which splits contexts and aggregates across two pictures.

### Output — `ontology-hub/docs/diagrams/ddd/` (tracked, beside `party-hierarchy-erd.mmd`)

`context-map.mmd`, `all-contexts.mmd` (every context in one view), one `<context>-context.mmd` per
context, and `design-notes.md`. Regenerate with `uv run python tools/ddd_context_erd.py`.

### Layout — the two things that decide whether the diagram is readable

The first version was messy in exactly two ways, both fixable without touching the model:

1. **`layout: elk`, on by default** (`--layout dagre` to revert). It routes edges orthogonally and
   clusters the external stubs above and below the container; dagre scatters them and draws long
   diagonals across the whole canvas. On `fracht-organisation-context`, with five external stubs,
   this is the difference between unusable and clean. The frontmatter must be the first thing in the
   file, before the provenance comments.

   **ELK has to be registered by the renderer, and the fallback is silent.**
   `getRegisteredLayoutAlgorithm` logs `Layout algorithm elk is not registered. Using dagre as
   fallback.` and carries on — no error, no marking on the output. Where it is registered:

   | Surface | ELK | Evidence |
   |---|---|---|
   | `mmdc` (mermaid-cli 11.x) | yes | `mermaid-cli/src/index.js:511` registers `@mermaid-js/layout-elk` |
   | VS Code, Mermaid Chart ext 2.7.8 | yes | `out/src/previewmarkdown/shared-mermaid/index.js:82` registers `@mermaid-chart/layout-elk` |
   | GitHub / Azure DevOps wiki | **no** | vanilla Mermaid; silent dagre fallback |

   So the diagrams read as intended in the IDE and in rendered SVG/PNG, and degrade quietly in a
   wiki. Anyone reporting a messy layout is either on a surface without ELK or looking at a file
   generated before this was added — check for the frontmatter first.
2. **Design notes out of the diagram, on by default** (`--notes diagram` to pin them back). Mermaid
   renders `note for` as a free-floating box joined by a dotted leader, and 200 characters of
   architecture rationale sends that leader across the entire drawing. The notes are the most
   valuable content in the overlay, so they now get `design-notes.md` — grouped by context, with the
   tactical pattern, published-language flag and aggregate root alongside — rather than being
   truncated into a diagram that cannot hold them.

Not fixed, and probably not worth fixing: `operationsRepresentative` and `salesRepresentative` each
appear twice in the organisation context, once from `HouseConsignmentRecord` and once from `Job`.
They are genuinely two different properties on two different classes that happen to share a local
name. Qualifying the labels would reduce a real ambiguity but add noise to every other edge.

### Design decisions worth knowing

- **Hub-local TTLs only, no import closure.** Inherited reference-model members (`mmt:`, `dcsa:`,
  `bsp:`) are not listed — deliberate at architecture altitude. `HouseConsignmentRecord` shows its 18
  hub-declared properties, not its ~40 with inheritance. Use `project --target erd` for the full list.
- **Multiplicity reads the lower bound from the class restriction and the upper bound from the
  property**, mirroring the convention stated in `reference-data.ttl`: *"Property-level
  `owl:FunctionalProperty` carries the upper bound; the class-level restrictions below carry the
  lower bound."* Reading only the restriction renders a functional property as `1..*` whenever it has
  `minCardinality 1` — which is what the first version did to `assignedToParty`.
- **Namespace identifiers come from the context IRI local name, never the label.** Mermaid treats a
  namespace as the parent container of its classes, so a namespace named `Party` containing a class
  named `Party` fails the render outright: *"Setting Party as parent of Party would create a cycle."*
  Context labels collide with class names routinely; IRI local names do not.
- **Classes outside a context but connected to it are drawn as stubs** — pattern annotation, no
  members — so a context diagram shows its boundary without pulling in the neighbour's detail.
- **The unannotated-class report is the backlog.** The run prints every authored class carrying no
  `boundedContext`: **28 of 44 today.** That list is the honest gap between the overlay and the hub.

### Verification

All seven diagrams render under Mermaid 11.4 (`npx mmdc`, the repo's existing devDependency). Note
`namespace` is a relatively recent `classDiagram` feature — GitHub and VS Code are current, but
**Azure DevOps wikis lag and should be checked** before anyone depends on the grouping. The fallback
is `classDef` colour-coding per context, which is universally supported.

### Known refinement, not a defect

Where an aggregate edge and an object property describe the same relationship in opposite directions,
both are drawn — `Party *-- PartyContact : aggregate` alongside `PartyContact --> Party : contactParty`.
De-duplicating would need `owl:inverseOf` awareness, which the hub declares only three times. Left as
is; it is visible, not wrong.

---

## 13. Where the artifacts belong, and what was filed upstream

### Hub or publish? Publish — but we cannot act on it yet

`TargetSpec.hub_relative` decides this in the toolkit, and its own docstring states the
criterion: almost every target is *"derived output that belongs outside the authored tree"*,
and `contract-erd` is the exception because it is *"a pure function of an authored contract
file … written beside the contract it describes."*

A bounded-context diagram is the opposite extreme — a function of every domain TTL, every
overlay, and the resolved reference-model closure. No single authored file to sit beside. So
it is derived output: publish tree, alongside `ddd` and `erd`. That is what #846 proposes.

Investigating that surfaced a defect in this hub, recorded as
[HUB-DD-20260919-a71c3e](../../ontology-hub/decisions/HUB-DD-20260919-a71c3e.md):

| Path | Mermaid type | What it is | Tracked |
|---|---|---|---|
| `ontology-hub/model/contracts/diagrams/party-erd.mmd` | `erDiagram` | physical Silver ERD | yes |
| `ontology-hub/model/contracts/diagrams/party-contract-erd.mmd` | `erDiagram` | declared contract | yes |
| `ontology-hub-publish/architecture/erd/party-erd.mmd` | **`classDiagram`** | **the ontology itself** | **no** |

Our `.gitignore` untracked `architecture/**` on the stated premise that toolkit 5.18.0rc1
had moved "the canonical class diagrams" into the authored tree. It moved the two `erDiagram`
families. The canonical `classDiagram` — the only view that shows the model as a model rather
than as tables — still lives only in the publish tree, and `git ls-files
ontology-hub-publish/architecture` returns 0.

Worse than the loss is that the gate cannot report it: `git diff --exit-code -- <path>` exits
0 when nothing at that path is tracked. Our `pr-validate.yml` warns about exactly this
fail-open (#699) for the two paths it *does* check, and never applies it to the one it does not.

**Not fixed here, deliberately.** Re-tracking is half the fix and the dangerous half alone —
tracked-but-never-regenerated files look authoritative and rot. The other half is regeneration
plus diff lines in `pr-validate.yml`, whose header reads *"Auto-generated — do not edit"* and
which `update --check` reports as matching the shipped rc1 template exactly. Upstream `81b9407`
(#774) does both halves together, but `git merge-base --is-ancestor 81b9407 v5.18.0rc2` answers
**no** — it is on toolkit `main` and in no released tag, and `update --upgrade` only sees
published releases. It arrives with a future upgrade.

Until then `ontology-hub-publish/architecture/**` is regenerate-on-demand
(`project --target erd --target ddd`); treat it as a local view, never as a reviewed artifact.
This is also why `tools/ddd_context_erd.py` writes to `ontology-hub/docs/diagrams/ddd/`, which
*is* tracked — a prototype placement that keeps the overlay reviewable in the PR diff, not a
claim about where the capability belongs.

### Filed upstream, 2026-09-19

| Issue | Kind | Scope |
|---|---|---|
| [#846](https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/846) | feature | `project --target ddd-context` — diagrams scoped to a bounded context rather than a domain file. Includes the four findings from building our prototype, and the instruction *not* to port its multiplicity logic. |
| [#847](https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/847) | feature | Class-level disposition ledger, so "intentionally unbound" can be declared rather than inferred. Filed as the class-side sibling of #492 and the authored-declaration counterpart to #496, and honest that our evidence is prospective — §7's gap is what creates the population it governs. |
| [#848](https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/848) | bug | `validate --ddd` reports an orphan overlay as passing: no matching domain ontology means SHACL runs against an empty graph and prints a tick. |
| [#855](https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/855) | feature | Emit Mermaid frontmatter selecting the ELK layout engine. Applies to every existing diagram target, not just the proposed one — the toolkit emits no frontmatter today, so everything renders under default dagre. Non-regressive: Mermaid falls back to dagre with only a `log.warn` where ELK is not registered. |

### The `tools/` lifecycle, and why this document mentions it

`tools/contract_erd.py` was written here on 2026-09-02 to draw the declared contract. The
toolkit then shipped DD-216 `project --target contract-erd`, and every
`*-contract-erd.mmd` in the hub has since read *"Generated by kairos-ontology 5.18.0rc1 — do
not edit"*. Nobody deleted the hub copy; it sat in `tools/` for two weeks with a docstring
asserting the toolkit had no such target. **It was removed in this branch.**

That is the pattern to expect and to manage, not to avoid: prototype locally where the gap is
real, propose upstream, delete when it ships. The only failure is forgetting the last step —
so `tools/ddd_context_erd.py` now carries its exit condition in its own docstring, naming #846.
