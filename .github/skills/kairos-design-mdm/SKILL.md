---
name: kairos-design-mdm
description: >
  Interactive workflow for authoring design-time Master Data Management (MDM)
  policy as `{domain}-mdm-ext.ttl` extensions — mastered concepts, match
  attributes/identifiers, deterministic match rules, survivorship, maker/checker
  workflow, abstract steward roles, reference-data policy, and DQ rules. Projects
  the immutable `mdm-profile` target. NOT for runtime matching/stewardship (that
  lives in kairos-mdm-runtime) and NOT for domain class modeling (kairos-design-domain).
---

# Kairos MDM Design Skill

Authors the **design-time** MDM policy overlay for a domain. MDM policy is an
*additive ontology extension* projected as the 8th target (`mdm-profile`) — it is
**not** a separate toolkit and **not** runtime code (ADR-1, MDM-DD-001). Runtime
services (matching engine, stewardship UI, operational store, sync-back) live in the
separate `kairos-mdm-runtime` repository and are out of scope here.

See `docs/mdm/mdm-design-decisions.md` (MDM-DD log), `docs/mdm/user-stories.md`
(epics), and the [full MDM architecture spec](https://github.com/Cnext-eu/kairos-ontology-toolkit/blob/main/docs/mdm/mdmhubdesignv2.md).

## Design fleet mode (DD-088)

Default is interactive: present each MDM policy proposal (mastered concepts,
match keys, survivorship, thresholds, workflow bounds, DQ rules) and wait for
stakeholder confirmation. Data governance owns this policy — it is reviewed before
the profile is trusted. If the user explicitly requests design fleet mode, make
checkpoint decisions with AI judgment for testing speed, but mark them
**AI-approved** rather than user-confirmed, and record rationale, confidence, and
source/mapping evidence. Always stop for low-confidence match keys, auto-merge
bounds, PII exposure, licensing of reference data, or destructive survivorship
choices.

Any fleet override applies only to this skill invocation. It expires when the
skill ends or pauses and is never inherited by another skill or a later resume.

## Lifecycle state (DD-080)

> The **kairos-flow** skill is the lifecycle orchestrator and the **only** writer of
> `ontology-hub/.kairos-state/status.md`. This skill plugs into that shared state.

**On start (pre-flight):** read `ontology-hub/.kairos-state/` — the `status.md`
continuation region and this phase's log at `phases/mdm/<domain>.md`. MDM policy is a
**late-lifecycle** step: it needs modeled classes (kairos-design-domain), mappings
(kairos-design-mapping), and ideally silver/gold extensions in place, because match
attributes, authority and survivorship are grounded in real source columns. If the
domain has no mapped sources yet, hand off to those phases first.

**On pause or finish:** append a *State update proposal* to `phases/mdm/<domain>.md`.

## The `kairos-mdm:` vocabulary

Namespace `https://kairos.cnext.eu/mdm#` (managed scaffold `kairos-mdm.ttl`). Annotate
ontology IRIs in a **separate** `model/extensions/{domain}-mdm-ext.ttl` file; never add
MDM policy to the domain `{domain}.ttl`.

### Class-level (on `owl:Class`)

| Term | Meaning | Values |
|------|---------|--------|
| `kairos-mdm:mastered` | class is a mastered entity | `true`/`false` |
| `kairos-mdm:mdmStyle` | MDM implementation style | `registry`, `consolidation`, `coexistence`, `centralized` |
| `kairos-mdm:referenceList` | class is governed reference data | `true`/`false` |
| `kairos-mdm:makerChecker` | four-eyes approval required | `true`/`false` |
| `kairos-mdm:autoActionBound` | score ≥ bound may auto-act | decimal 0..1 |
| `kairos-mdm:slaHours` | abstract case SLA | integer |
| `kairos-mdm:escalationRole` | abstract escalation role | string |
| `kairos-mdm:referenceOwner` / `releasePolicy` / `license` | reference-data policy | string |

### Attribute-level (on `owl:DatatypeProperty` / `owl:ObjectProperty`)

| Term | Meaning | Values |
|------|---------|--------|
| `kairos-mdm:matchAttribute` | participates in matching | `true`/`false` |
| `kairos-mdm:identifier` | match-capable identifier | `true`/`false` |
| `kairos-mdm:identifierType` | identifier scheme | e.g. `VAT`, `KBO`, `LEI`, `EORI` |
| `kairos-mdm:authoritativeSource` | source(s) authoritative for the golden value | string (repeatable) |
| `kairos-mdm:survivorship` | survivorship strategy | `source-precedence`, `recency`, `completeness`, `most-trusted`, `manual` |
| `kairos-mdm:survivorshipPriority` | tie-breaker (lower wins) | integer |

> Attributes declared on a **subclass** of a mastered concept (e.g. `vatNumber` on
> `CorporateClient` under a mastered `Client`) are correctly attributed to the mastered
> concept — you do not need to re-declare them.

### Deterministic match rules (`a kairos-mdm:MatchRule`)

`kairos-mdm:appliesTo` (class) · `kairos-mdm:onAttribute` (property, repeatable) ·
`kairos-mdm:comparator` (`exact`/`normalized`/`fuzzy-reference`) ·
`kairos-mdm:threshold` (0..1) · `kairos-mdm:matchAction`
(`auto-merge`/`candidate`/`review`).

### Probabilistic model reference (ADR-5) — on `owl:Ontology`

`kairos-mdm:probabilisticArtifact [ kairos-mdm:artifactDigest "sha256:…" ;
kairos-mdm:artifactVersion "…" ; kairos-mdm:artifactUri "…" ]`. **Never author
probabilistic weights in Turtle** — only an immutable, content-addressed reference to
the owned, versioned artifact.

### Abstract steward roles (`a kairos-mdm:StewardRole`)

`kairos-mdm:roleName` · `kairos-mdm:scope`. Environment identity mapping (Entra
groups → roles) is a dataplatform binding and never declared here.

### Data-quality rules (`a kairos-mdm:DataQualityRule`)

`kairos-mdm:appliesTo` / `onAttribute` · `kairos-mdm:dimension` (the six DAMA
dimensions: `accuracy`, `completeness`, `consistency`, `timeliness`, `uniqueness`,
`validity`) · `kairos-mdm:scorecardThreshold` (0..1) · `kairos-mdm:severity`
(`info`/`warning`/`error`).

## Workflow

1. **Pre-flight** — confirm the domain has modeled classes + mapped sources; read the
   phase log. Identify which concepts the business actually masters.
2. **Mastered concepts** — for each, confirm `mastered`, `mdmStyle`, and workflow
   policy (maker/checker, auto-action bound, SLA, escalation).
3. **Match keys** — confirm identifiers, match attributes, `authoritativeSource`, and
   survivorship per attribute (grounded in source evidence).
4. **Match rules** — author deterministic rules; reference (do not author) the
   probabilistic artifact by digest.
5. **Reference data & DQ** — mark reference lists + ownership/license; author DQ rules
   on the DAMA dimensions.
6. **Validate** — run `mdm-validate` (this skill sets `KAIROS_SKILL_CONTEXT=1`).
7. **Project** — hand off to **kairos-execute-project** for `project --target mdm-profile`.
8. **State update** — append a proposal to `phases/mdm/<domain>.md`.

## Commands (wrapped by this skill)

```bash
# structural design-time gate over *-mdm-ext.ttl
kairos-ontology mdm-validate

# project the immutable, runtime-neutral profile to output/mdm/
kairos-ontology project --target mdm-profile
```

The profile JSON carries a reproducible `content_digest` (sha256 over the policy,
excluding timestamps) — same reviewed hub state → same digest (ADR-11). The
`mdm-profile` target is **opt-in** and not part of `project --target all`.

## Boundaries (what this skill does NOT do)

- No runtime matching, stewardship UI, operational SQL store, or sync-back — that is
  `kairos-mdm-runtime`.
- No domain class/property modeling — use **kairos-design-domain**.
- No source-to-domain column mapping — use **kairos-design-mapping**.
- Governance ownership/approval of *claims* stays in the claim registry
  (`mdm_anchor`/ownership gates), which is distinct from this profile policy
  (MDM-DD-001).
