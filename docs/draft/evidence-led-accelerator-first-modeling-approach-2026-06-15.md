# Evidence-Led Accelerator-First Modeling Approach

> Draft methodology proposal.
>
> This document defines a complete modeling approach for ontology hubs that use
> accelerator reference models, customer source data, existing reporting assets,
> and governed claim approval to generate silver and gold outputs.

---

## 1. Executive summary

The recommended methodology is **evidence-led accelerator-first modeling**.

The approach starts with a prebuilt accelerator vocabulary, but it does not let
that vocabulary automatically define the client's warehouse. Instead, customer
evidence determines which concepts are claimed, how they are mapped, where client
specializations are needed, and what becomes part of the downstream silver/gold
contract.

In short:

```text
accelerator vocabulary
+ MDM/reference data discovery
+ customer source evidence
+ existing Power BI/reporting evidence
+ governed Claim Registry
+ deterministic checks
+ versioned silver/gold contracts
= faster modeling with controlled semantic drift
```

The key design decision is:

> The accelerator foundation is infrastructure. The **Claim Registry** is the
> governance center.

The methodology therefore uses:

- an **accelerator foundation ontology** to make the standard vocabulary
  resolvable;
- **thin client/domain ontologies** for client-specific specialization only;
- a **Claim Registry** to approve what materializes;
- **source mappings** to bind customer systems to approved claims;
- **silver-passthrough** for useful data that should not become ontology
  vocabulary;
- **gold/PBI fit-gap simulation** to compare reporting expectations with source
  coverage;
- **MDM/reference-data-first discovery** to stabilize identifiers, reference
  lists, conformed dimensions, and cross-domain joins before broad modeling.

---

## 2. Core concepts

### 2.1 Accelerator

An **accelerator** is a reusable pack of ontology/reference-model concepts for a
business area or industry, such as logistics, transport, customs, finance, or
sustainability.

It provides:

- common classes,
- properties,
- relationships,
- standard terminology,
- extension defaults,
- reusable modeling patterns.

The accelerator is the preferred starting vocabulary. It is not automatically
the client's full data model.

### 2.2 Accelerator foundation ontology

An **accelerator foundation ontology** is a small shared ontology in the hub that
imports the selected accelerator pack or sub-packs.

Typical file:

```text
model/ontologies/_foundation.ttl
```

Purpose:

- make the accelerator vocabulary available to all domains;
- centralize accelerator imports;
- avoid repeated per-domain import decisions;
- simplify catalog/import resolution;
- allow all domains to reference the same standard concepts.

The foundation ontology should normally contain only:

- `owl:Ontology` metadata,
- `owl:imports` statements,
- possibly hub-level comments explaining which accelerator packs are selected.

It should not contain client-specific modeling.

### 2.3 Thin client/domain ontology

A **thin ontology** is the client's domain ontology layer. It imports the
foundation and contains only the model elements that are truly specific to the
client or domain.

Typical examples:

- a client-specific subclass of an accelerator class;
- a client-native class where no accelerator concept fits;
- a client property that represents a true semantic gap;
- labels/comments for local clarity.

It should not copy accelerator classes merely because the client uses them.
Imported accelerator concepts are materialized through approved claims.

### 2.4 Claim

A **claim** is a governed decision that a concept belongs in the client's
implemented model.

A claim says:

> This domain owns this concept for this client implementation, there is evidence
> for it, and it may materialize into silver/gold outputs.

Claims can target:

- accelerator classes,
- accelerator properties,
- client-native classes,
- client specializations,
- relationships/FKs,
- gold measures or reporting concepts.

### 2.5 Claim Registry

The **Claim Registry** is the source of governance for approved concepts.

Suggested location:

```text
model/claims/{domain}-claims.yaml
```

The registry records:

- which concept is claimed,
- which domain owns it,
- which evidence supports it,
- whether it is proposed, approved, rejected, deferred, or deprecated,
- whether it should be modeled, specialized, passed through, skipped, or treated
  as a gap,
- expected silver/gold impact,
- reviewer/owner and rationale.

Projection annotations such as `silverInclude` can be generated from, or
validated against, this registry.

### 2.6 Source evidence

**Source evidence** is proof that a concept exists in the customer's actual data
landscape.

It can include:

- source schemas,
- sample files,
- source profiling,
- accepted column mappings,
- source-to-domain affinity results,
- stakeholder confirmation,
- source documentation.

### 2.7 Reporting evidence

**Reporting evidence** is proof that a concept is already used in analysis,
decision-making, KPIs, or reporting.

It can include:

- existing Power BI/PBIP/TMDL models,
- DAX measures,
- dimensions,
- relationships,
- hierarchies,
- slicers/filters,
- report pages,
- semantic model metadata.

Reporting evidence is valuable, but it is "as-is" evidence. It must be checked
against source evidence before it becomes an approved claim.

### 2.8 MDM and reference data

**MDM/reference data** means master data, identifiers, code lists, hierarchies,
controlled values, and slowly changing reference structures that give stability
to the rest of the model.

Examples:

- customer/party master,
- vessel master,
- location/port master,
- product/service catalog,
- currency codes,
- country codes,
- status codes,
- company/legal entity lists,
- route/region hierarchies.

This methodology treats MDM/reference data as a first-class starting point, not
an afterthought.

---

## 3. Guiding principles

### 3.1 Evidence before materialization

Imported accelerator concepts do not materialize automatically.

A concept can be imported freely, but it only becomes part of the generated
silver/gold model when there is an approved claim backed by evidence.

### 3.2 MDM/reference data first

Before broad domain modeling, identify the reference data and master data that
will stabilize the rest of the model.

This should happen early because reference data drives:

- natural keys,
- conformed dimensions,
- cross-domain joins,
- ownership boundaries,
- FK design,
- gold dimensions,
- Power BI slicers,
- RLS/security boundaries,
- slowly changing dimension strategy.

If MDM/reference data is treated too late, domains may model the same business
object differently and create avoidable integration debt.

### 3.3 Claims are governance decisions

Claims should be reviewed explicitly. They should not be hidden only in TTL
extension annotations.

### 3.4 Projection annotations are execution syntax

`silverInclude`, `silverIncludeImports`, FK annotations, natural-key annotations,
and gold annotations are still used by projectors.

Methodologically, however, they execute approved decisions; they are not the
primary governance record.

### 3.5 Power BI is evidence, not authority

Existing Power BI models are highly valuable because they show what the business
uses today. They also often contain shortcuts, denormalization, stale logic, and
report-local semantics.

Therefore:

- use Power BI to propose claims, measures, dimensions, and hierarchies;
- run fit-gap against source coverage before approval;
- do not copy a report model blindly into the ontology.

### 3.6 Silver is a contract

Existing silver outputs are downstream contracts. New systems and fields create
candidate deltas; only approved and versioned deltas change silver.

---

## 4. Target lifecycle

Recommended lifecycle:

```text
business discovery
→ MDM/reference-data discovery
→ customer evidence intake
→ Power BI/reporting inventory
→ accelerator foundation selection
→ source analysis and mapping analysis
→ candidate claim derivation
→ Power BI/source fit-gap simulation
→ claim approval
→ thin ontology specialization
→ mapping and passthrough triage
→ silver design
→ gold/Power BI design
→ validation and projection
→ change management
```

The important sequencing changes are:

1. MDM/reference data is identified before broad claim approval.
2. Power BI/reporting assets are inventoried before gold design.
3. Candidate claims are tested against both reporting demand and source supply.
4. Silver/gold projection follows approved claims, not raw tool suggestions.

---

## 5. MDM/reference-data-first discovery

### 5.1 Why MDM comes early

MDM/reference data should be addressed near the beginning because it defines the
stable anchors for the rest of the model.

Without early MDM clarity, these problems appear later:

- duplicate party/customer/vendor concepts;
- inconsistent natural keys;
- wrong grain for dimensions;
- unclear ownership of reference tables;
- multiple conflicting status/code lists;
- FK relationships that cannot be trusted;
- gold measures that join through unstable keys;
- Power BI dimensions that do not match silver entities.

### 5.2 MDM discovery questions

Ask early:

- What are the master entities?
- Which system is authoritative for each master entity?
- Which systems contain copies or local variants?
- What are the natural keys?
- Are keys stable over time?
- Which reference lists are controlled?
- Who owns each code list?
- Which lists are client-specific vs industry-standard?
- Are hierarchies present?
- Are reference lists slowly changing?
- Are there crosswalks between source identifiers?
- Which dimensions are used in Power BI slicers and filters?

### 5.3 MDM/reference-data claims

Reference data should be represented as claims too.

Example claim types:

- conformed dimension claim,
- reference-list claim,
- code-list ownership claim,
- crosswalk claim,
- hierarchy claim,
- SCD strategy claim.

Suggested fields:

```yaml
claims:
  - id: ref-country-code
    type: reference_data
    class_uri: https://example.org/accelerator/common#Country
    domain: reference
    status: approved
    reference_data:
      authority_system: iso
      code_system: ISO-3166-1
      key: alpha2
      scd_type: 1
    evidence_sources:
      - type: source_table
        system: mdm
        table: country
      - type: powerbi_slicer
        model: operations-report
        field: Country
```

### 5.4 MDM as a gate

Before approving broad domain claims, identify:

- master entities,
- authoritative source systems,
- conformed reference dimensions,
- natural keys,
- domain ownership.

This does not mean every reference table must be fully implemented first, but
the major reference anchors must be known.

---

## 6. Customer evidence intake

Customers often already have useful modeling evidence. The approach uses it
directly instead of starting from a blank ontology.

### 6.1 Source schemas and samples

Use source schemas and samples to understand:

- tables,
- columns,
- identifiers,
- cardinality,
- enum-like values,
- FK-like structures,
- data quality,
- candidate MDM/reference data,
- candidate passthrough fields.

Use source analysis to produce:

- table-to-class affinity,
- domain routing,
- candidate claims,
- source coverage evidence,
- mapping candidates.

Raw customer extracts should not be committed to the repository. Use sanitized
or masked samples only.

### 6.2 Existing mapping analyses

Existing mapping spreadsheets or prior analyses can seed:

- source-to-domain mappings,
- SKOS mappings,
- claim evidence,
- field dispositions,
- known gaps,
- transformation rules.

They should be treated as candidate evidence and reviewed for currency.

### 6.3 Existing Power BI / TMDL

Existing Power BI models provide a view of what the business already consumes.

Use TMDL/PBIP import to inventory:

- tables,
- columns,
- relationships,
- measures,
- hierarchies,
- calculation groups,
- display names,
- hidden fields,
- slicer/filter fields.

Use this for:

- claim candidates,
- gold measure candidates,
- hierarchy candidates,
- glossary terms,
- FK hints,
- passthrough promotion triggers,
- fit-gap simulation.

Guardrail:

> Power BI shows current analytical usage. It does not automatically define the
> target ontology or warehouse design.

---

## 7. Power BI/source fit-gap simulation

### 7.1 Purpose

Power BI/source fit-gap simulation compares:

1. what existing reports expect,
2. what accelerator claims would provide,
3. what customer source systems can actually supply.

It answers:

- Can approved source claims feed the expected Power BI/gold model?
- Which existing Power BI fields have no source mapping?
- Which measures depend on fields that are only passthrough?
- Which report dimensions imply missing claims?
- Which relationships in Power BI conflict with source/accelerator grain?
- Which source fields are available but unused in reporting?

### 7.2 Inputs

Recommended inputs:

- TMDL/PBIP inventory,
- source schema/sample inventory,
- mapping analysis,
- candidate Claim Registry,
- accelerator class/property inventory,
- proposed silver extension annotations,
- proposed gold annotations.

### 7.3 Simulation outputs

The simulation should produce a fit-gap report:

| Finding | Meaning | Action |
|---|---|---|
| PBI field covered by approved source mapping | good fit | keep |
| PBI field maps to accelerator concept but no source evidence | reporting demand without source supply | investigate source or reject claim |
| Source field available but no PBI usage | source supply without reporting demand | passthrough/model based on business value |
| PBI measure depends on passthrough field | semantic debt risk | review for promotion to modeled property |
| PBI relationship conflicts with source grain | model mismatch | review FK/grain; do not copy blindly |
| PBI dimension has no approved claim | missing claim or legacy report artifact | approve, defer, or reject |
| Approved claim unused in PBI but present in source | operational/domain need, not reporting need | keep if source/business evidence exists |
| PBI-only calculated field | derived/gold concept | model as gold measure/calculation if still needed |

### 7.4 How it feeds Power BI gold

The fit-gap result should seed gold design:

- dimensions from approved claims,
- measures from validated DAX/business definitions,
- hierarchies from PBI if backed by reference data,
- relationships from source-confirmed silver FKs,
- slicers from conformed dimensions/reference data,
- RLS from approved master/reference dimensions.

The goal is not to reproduce the existing Power BI exactly. The goal is to
produce a governed gold model that can explain:

- what was kept,
- what changed,
- what was rejected,
- what is missing from sources,
- what must be sourced later.

### 7.5 Simulation loop

Recommended loop:

```text
import TMDL
→ extract reporting expectations
→ map expectations to candidate claims
→ compare against source mappings
→ classify gaps
→ approve/reject/defer claims
→ seed gold annotations
→ project gold
→ compare generated model to expected reporting shape
```

This can start as a manual report and later become a toolkit command.

---

## 8. Claim Registry

### 8.1 Recommended location

```text
model/claims/{domain}-claims.yaml
```

### 8.2 Example

```yaml
schema_version: 1
domain: party
claims:
  - id: party-trade-party
    type: class
    class_uri: https://example.org/accelerator/logistics#TradeParty
    domain: party
    status: approved
    disposition: claim
    evidence_sources:
      - type: source_table
        system: crm
        table: account
      - type: source_table
        system: erp
        table: customer
      - type: powerbi_table
        model: commercial-report
        table: Customer
      - type: stakeholder_confirmation
        note: Confirmed as customer/supplier/legal-party concept.
    source_tables:
      - crm.account
      - erp.customer
    pbi_artifacts:
      - commercial-report.Customer
    owner: data-domain-party
    silver_impact:
      table: dim_party
      change_type: additive
    rationale: >
      TradeParty is the closest accelerator concept for the client's party master
      data used across CRM, ERP, and commercial reporting.

  - id: party-credit-limit
    type: property
    property_uri: https://example.org/client/party#creditLimit
    domain: party
    status: approved
    disposition: specialize
    evidence_sources:
      - type: source_column
        system: erp
        table: customer
        column: credit_limit
      - type: powerbi_measure_dependency
        model: finance-report
        measure: Credit Exposure
    owner: data-domain-party
    silver_impact:
      table: dim_party
      column: credit_limit
      change_type: additive
    rationale: >
      Credit limit is a shared finance concept used in reporting and not covered
      by the selected accelerator concept.
```

### 8.3 Claim statuses

| Status | Meaning |
|---|---|
| `proposed` | suggested by evidence/tooling, not yet approved |
| `approved` | accepted for projection/governance |
| `rejected` | considered and explicitly declined |
| `deferred` | valid candidate, not in current scope |
| `deprecated` | previously approved, being phased out |

### 8.4 Claim dispositions

| Disposition | Meaning |
|---|---|
| `claim` | materialize an existing accelerator/client concept |
| `specialize` | add a client subclass/property |
| `passthrough` | carry data in silver without ontology promotion |
| `skip` | do not model or carry |
| `gap` | client-native concept or upstream accelerator gap |

### 8.5 Approval requirements

An approved claim should have:

- a resolvable class/property URI or a defined client-native URI,
- an owning domain,
- evidence,
- source mapping or documented exception,
- known silver/gold impact,
- reviewer/owner,
- no duplicate/conflicting ownership.

---

## 9. Projection annotations

Projection annotations remain the execution layer.

Examples:

- `kairos-ext:silverInclude`,
- `kairos-ext:silverIncludeImports`,
- silver natural keys,
- silver SCD annotations,
- silver FK annotations,
- gold fact/dimension annotations,
- DAX measure annotations.

Recommended rule:

> Projection annotations should be generated from, or checked against, approved
> Claim Registry entries.

This keeps the source of governance in one place while preserving the existing
projection architecture.

---

## 10. Role of affinity and proposal-fit

`analyse-sources` and `propose-alignment` remain important. Their role is to
generate candidate evidence, not final approval.

### 10.1 Affinity

Affinity helps answer:

- which class does a source table appear to support?
- which domain should own it?
- which source tables are not covered by claims?
- which claims have no source support?

The old import-selection role becomes less important because the accelerator
foundation handles import availability.

### 10.2 Proposal-fit

Proposal-fit helps answer:

- which source column maps to which property?
- which columns are passthrough?
- which columns should be skipped?
- which fields suggest a specialization or gap?
- do approved claims have enough mapped evidence?

### 10.3 Confirmation rule

Tool outputs may propose claims and mappings. They do not approve them. Approval
requires evidence strength and human/domain-owner confirmation.

---

## 11. Silver-passthrough

Silver-passthrough means:

> Carry the column into the silver table, but do not promote it to a domain
> ontology property.

It is the middle disposition between `model` and `skip`.

| Disposition | Meaning | Outcome |
|---|---|---|
| `model` | shared business meaning | ontology property/class + mapped silver column |
| `silver-passthrough` | real data worth carrying, no shared ontological value yet | silver column only |
| `skip` | technical/audit/noise or out-of-scope | not modeled and not carried |

### 11.1 Why passthrough exists

The ontology and the warehouse serve different purposes:

- the ontology models shared business meaning,
- the silver layer carries usable data.

Not every source field deserves a first-class semantic property. Vendor fields,
single-source custom fields, report-only attributes, and low-reuse operational
fields can be valuable in silver without being valuable in the ontology.

### 11.2 Promotion triggers

Review passthrough fields for promotion when they:

- appear in multiple systems,
- are used in Power BI measures,
- are used in joins/FKs,
- are used in slicers/filters,
- support governed KPIs,
- are confirmed by the business as shared terminology,
- become part of MDM/reference data.

---

## 12. When an accelerator concept does not fit

Apply the cheapest correct route:

| # | Mismatch | Approach | Mechanism |
|---|---|---|---|
| 1 | terminology only | relabel, do not fork | glossary/SKOS `altLabel`, business labels in gold |
| 2 | irrelevant concept | do not claim it | unclaimed imports do not materialize |
| 3 | granularity or extra attributes | specialize | subclass or add client property in thin ontology; passthrough extras |
| 4 | partial overlap | map loosely | `skos:closeMatch` / `relatedMatch`, not `exactMatch` |
| 5 | genuine semantic gap | model client-native | class/property in client namespace, with owner and evidence |
| 6 | recurring gap across clients | escalate upstream | accelerator gap request |

Guardrails:

- never subclass merely to reuse columns,
- do not assert `subClassOf` when semantics differ,
- keep client-native concepts in the client namespace,
- track native concepts and upstream gaps in a deviation log,
- high mismatch rate means accelerator pack selection should be revisited.

---

## 13. Change management for new systems and fields

New systems are expected. They should enter as evidence and candidate deltas,
not as automatic model changes.

Core rule:

> New evidence may expand silver, but must not silently mutate existing silver.

### 13.1 New system flow

```text
new source system
→ source import / sample intake
→ MDM/reference-data delta check
→ analyse-sources
→ propose-alignment
→ Power BI/source fit-gap update
→ candidate delta report
→ claim/mapping/passthrough review
→ impact analysis
→ approval
→ versioned silver/gold update
```

### 13.2 Candidate delta types

| Delta type | Meaning | Typical impact |
|---|---|---|
| new table maps to existing approved class | source coverage expands | mapping-only, no silver schema change |
| new table maps to unclaimed accelerator class | candidate new claim | possible new silver table |
| new column maps to existing property | mapping expands | no schema change if concept already exists |
| new column has no property | passthrough / skip / specialize decision | possible additive column |
| new reference list appears | candidate MDM/reference-data claim | possible conformed dimension/code list |
| new relationship appears | candidate FK/junction update | possible FK/relationship change |
| conflicting semantics | same label, different meaning/grain | human review; possible breaking change |
| changed key/type/grain | existing contract may be invalid | breaking or migration-required change |

### 13.3 Does a new field impact existing silver?

Only if the approved disposition changes the silver contract.

| Case | Example | Silver impact |
|---|---|---|
| maps to existing concept | `CustomerName` → `Party.name` | no schema change; add mapping |
| source-specific field | local flag or vendor custom slot | optional passthrough column if approved |
| missing shared concept | `creditLimit` used across systems/reporting | additive modeled column/property |
| unclaimed accelerator class | `CustomsDeclaration` appears | possible new table if claim approved |
| semantic conflict | `status` means different things | no silent merge; model separately or break/change with approval |
| new reference data | `PortRegionCode` code list | reference-data claim; possible dimension/lookup table |

### 13.4 Impact analysis report

Every new system should produce an impact report:

- new source tables,
- new source columns,
- candidate MDM/reference-data changes,
- candidate new claims,
- candidate passthrough fields,
- skipped fields,
- changed mappings,
- semantic conflicts,
- expected silver table additions,
- expected silver column additions,
- expected FK/junction changes,
- expected gold/measure impacts,
- breaking changes,
- required approvals.

### 13.5 Silver/gold contract versioning

Suggested versioning:

| Change | Version impact |
|---|---|
| new source mapping only | no schema version change or patch |
| additive nullable column | minor |
| additive table | minor |
| additive FK with unchanged grain | minor, review downstream |
| new reference dimension/code list | minor unless replacing existing logic |
| changed meaning | major |
| changed type | major unless backward-compatible cast remains |
| changed natural key | major |
| changed grain | major |
| removed/renamed column | major |
| passthrough promotion with same output column | minor or patch if contract unchanged |

### 13.6 Backward compatibility tactics

Where possible:

- add new columns instead of changing existing ones,
- preserve old columns with deprecation metadata,
- introduce compatibility views,
- keep aliases for renamed business terms,
- mark claims as deprecated before removal,
- require downstream sign-off for major changes.

---

## 14. Deterministic checks

The approach needs deterministic checks to keep governance real.

| Check | Failure condition |
|---|---|
| claim-to-ownership | approved claim not owned by declared domain |
| duplicate-claim | same class approved in multiple domains without exception |
| claim-to-extension | approved claim missing projection annotation |
| extension-to-claim | projection annotation exists without approved claim |
| evidence-required | approved claim lacks evidence |
| mapping-required | claim has no accepted mapping and no exception |
| MDM-anchor-required | broad domain claims approved before required reference anchors are known |
| PBI-source-gap | gold/reporting expectation has no source-backed claim |
| passthrough-review | repeated/high-use passthrough fields not reviewed |
| deviation-log | client-native class lacks deviation/gap record |
| contract-impact | new source changes silver/gold without version decision |

These can start as manual review gates and later become toolkit commands.

---

## 15. Gate 0 spike

Before rolling out broadly, prove the operating model on one representative
domain, such as `party`.

### 15.1 Spike scope

Use:

- source schemas/samples,
- one existing mapping analysis if available,
- one Power BI/TMDL model if available,
- MDM/reference-data candidates,
- accelerator foundation import,
- Claim Registry,
- silver projection,
- gold/Power BI fit-gap simulation,
- change-impact report.

### 15.2 Spike steps

1. Identify MDM/reference-data anchors for the domain.
2. Wire the accelerator foundation.
3. Import customer evidence.
4. Import TMDL/PBIP if available.
5. Run affinity and proposal-fit.
6. Derive candidate claims.
7. Run Power BI/source fit-gap simulation.
8. Approve/reject/defer claims in the Claim Registry.
9. Generate or validate projection annotations.
10. Triage fields into model/passthrough/skip.
11. Log accelerator deviations/gaps.
12. Project silver/gold/dbt as applicable.
13. Run coverage, ownership, and contract checks.
14. Produce measured outcome report.

### 15.3 Pass criteria

All must hold:

- MDM/reference anchors are identified,
- accelerator closure resolves cleanly,
- no unresolved imports,
- no phantom FK/dbt references from unclaimed imports,
- every approved claim has evidence,
- duplicate claim count is zero,
- unowned claim count is zero,
- projection annotations match approved claims,
- Power BI expectations are classified as fit/gap/defer/reject,
- PBI-derived claims are confirmed against source or stakeholder evidence before
  approval,
- passthrough ratio is measured and reviewed,
- native client class count is measured and justified,
- source-delta/contract impact is understood,
- projection runtime is acceptable,
- the method is faster, safer, or materially clearer than manual modeling.

If full accelerator closure is too heavy, use sub-pack imports while preserving
the same evidence-led claim governance model.

---

## 16. Recommended phased delivery

| Phase | Output | Gate |
|---|---|---|
| 0. Spike | one-domain proof with MDM, claims, PBI fit-gap, and measurements | pass §15 criteria |
| 1. Governance format | final claim YAML shape, statuses, dispositions, approvals | approved by model owners |
| 2. Deterministic checks | ownership, duplicate claims, evidence, MDM anchor, extension sync | checks green on spike domain |
| 3. Methodology docs | publish methodology and DD entry | reflects spike outcome |
| 4. Tooling | derive-claims, TMDL-to-gold seed, claim checker, fit-gap report | validated on spike domain |
| 5. Rollout | migrate domains in small batches | each batch has delta/impact report |
| 6. Upstream | toolkit issues/PRs for skill support and scaffold templates | tracked to closure |

---

## 17. Tooling follow-ups

Recommended toolkit/hub tooling:

- `derive-claims`: aggregate TMDL, affinity, proposal-fit, mappings, MDM
  inventory, and samples into candidate claims.
- `check-claims`: validate ownership, duplicate claims, evidence, MDM anchors,
  and extension synchronization.
- `claims-to-silver-ext`: generate `silverInclude` and related annotations from
  approved claims.
- `tmdl-to-gold-ext`: seed measures and hierarchies from existing Power BI.
- `pbi-source-fit-gap`: compare existing Power BI expectations with approved
  source-backed claims and mappings.
- `source-delta-report`: compare a new system to approved claims/mappings and
  report schema/semantic impact.
- `passthrough-review`: detect repeated or high-value passthrough candidates.
- `deviation-log-check`: require client-native concepts to have a recorded
  deviation/gap decision.

---

## 18. Copilot skills as thin-chat orchestrators

Ontology hubs can rely on Copilot skills, but the skills should not be the
primary work product or the durable governance record. They should orchestrate
the methodology, enforce gates, and ask for decisions, while the repository and
GitHub remain the source of truth.

Recommended model:

```text
skill = orchestrator + gatekeeper + artifact writer
chat = concise decision UI
repo = source of truth
GitHub PR = review / approval layer
```

### 18.1 What skills are good for

Use skills for:

| Use | Why |
|---|---|
| lifecycle orchestration | enforce the correct order of discovery, MDM, claims, mapping, silver, gold, validation, projection |
| decision checkpoints | ask approve/reject/defer at the right moments |
| pre-flight checks | verify sources, claims, mappings, extensions, projections, and contract impact |
| artifact generation | create/update claim files, mappings, extensions, reports, and decision logs |
| resume state | continue from `.sessions-design/`, Claim Registry files, and reports |
| guardrails | avoid unsafe direct CLI use and preserve validation gates |

### 18.2 What skills should not be used for

Avoid using chat/skills as:

| Weak use | Better place |
|---|---|
| long methodology explanation | methodology docs |
| full rationale dumps | Markdown/YAML artifacts |
| approval history | GitHub PR reviews |
| repeated context | session state and Claim Registry |
| governance source of truth | versioned repository files |

### 18.3 Thin-chat, artifact-first mode

Skills should default to a concise mode for experienced teams:

- chat shows only the current gate, summary, and decision options;
- detailed findings are written to versioned artifacts;
- methodology is linked, not repeated;
- full logs appear only on failure or explicit request;
- each phase ends with a repo diff/PR-ready artifact set.

Example interaction:

```text
Claim approval: party
- 12 candidate claims
- 8 backed by source + Power BI evidence
- 2 source-only
- 2 weak/LLM-only

Decision needed: approve the 8 strong claims?
1. approve
2. review one-by-one
3. defer

Artifact: model/claims/party-claims.yaml
Report: integration/reports/party-claim-fit-gap.md
```

The chat is the control surface. The files are the record.

### 18.4 Decision packets

Each skill checkpoint should emit a compact decision packet, ideally YAML or
Markdown, for example:

```yaml
checkpoint: claim-approval
domain: party
summary:
  proposed_claims: 12
  strong_evidence: 8
  weak_evidence: 2
  passthrough_candidates: 17
requires_decision:
  - id: party-credit-limit
    recommendation: approve
    reason: ERP source column + finance Power BI measure dependency
options:
  - approve
  - reject
  - defer
artifact: model/claims/party-claims.yaml
```

The skill renders the decision in chat and stores the full packet in the repo or
session state.

### 18.5 GitHub as the versioning and approval layer

Since the hub is versioned in GitHub, use normal GitHub workflows for governance:

- branch per modeling/change task;
- artifacts generated into the repo;
- pull request shows claim/mapping/silver/gold diffs;
- PR review captures durable approval;
- issues track gaps and open decisions;
- DD entries record architectural or methodology decisions.

This reduces chat burden and makes modeling decisions auditable.

### 18.6 Skill modes

Recommended standard modes:

| Mode | Behavior |
|---|---|
| `guided` | explanatory, useful for new users |
| `concise` | default for experienced teams; decisions only |
| `silent-artifact` | minimal chat, writes findings to files |
| `review-only` | no generation, summarizes deltas for approval |

The methodology should default to `concise` once the team understands the
workflow.

---

## 19. Risks and mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Claim governance becomes heavier than manual modeling | High | automate candidate generation and checks |
| MDM is under-modeled and domains diverge | High | MDM/reference-data-first gate |
| Power BI becomes accidental authority | High | source-backed fit-gap before approval |
| Passthrough becomes semantic dumping ground | Medium | passthrough review and promotion triggers |
| Full accelerator closure causes projection leaks/perf issues | High | spike gate; sub-pack fallback |
| Duplicate/domain-conflicting claims | High | ownership checker |
| LLM suggestions become unreviewed truth | High | candidate-only until approval |
| Client-native classes fragment the standard | Medium | deviation log and upstream gap process |
| New systems silently change silver/gold | High | source-delta report and contract versioning |

---

## 20. Final recommendation

Adopt **evidence-led accelerator-first modeling** with MDM/reference data,
Power BI/source fit-gap simulation, and claim governance as first-class parts of
the methodology.

The approach is safe when:

- MDM/reference anchors are identified early,
- customer evidence drives claims,
- existing Power BI is used as fit-gap evidence rather than authority,
- approved claims govern projection annotations,
- passthrough and deviations are reviewable,
- new systems go through source-delta/change management,
- silver/gold contracts are versioned.

Do not use the accelerator as an automatic model generator. Use it as the
standard vocabulary against which customer evidence is claimed, checked, and
projected.
