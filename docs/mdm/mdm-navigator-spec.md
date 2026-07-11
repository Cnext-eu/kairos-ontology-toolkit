# MDM Navigator — Authoring-Module Spec (design-time)

Status: **Spec only** — no runnable UI ships from this repo. This documents the
design-time authoring surface so the future Kairos portal can implement it against the
toolkit's existing operations and the `kairos-design-mdm` skill.

Source: `docs/design/mdmhubdesignv2.md` §17. Boundary rules: MDM-DD-001/002/003.

---

## 1. Purpose & positioning

The **MDM Navigator** is a *module of the Design portal* (the Ontology Navigator), **not**
a third UI and **not** the operational Stewardship UI. It lets an MDM designer author and
validate `model/extensions/{domain}-mdm-ext.ttl` policy in **business terms**, then produce
a **reviewed PR**. It is **design-time only** and must never mutate active production policy.

| | MDM Navigator (this spec) | Stewardship UI (`kairos-mdm-runtime`) |
|---|---|---|
| Surface | Design portal module | Operational surface |
| Writes | `*-mdm-ext.ttl` via toolkit ops → PR | Golden records / cases via versioned API |
| Cadence | Design-time, reviewed | Runtime, live |
| Auth model | Hub contributor / governance reviewer | Steward / approver RBAC |

The two surfaces share a design system, auth shell and graph components, and **deep-link**:
ontology class/constraint ↔ affected profile policy ↔ operational evidence ↔ semantic
definition + lineage.

---

## 2. Hard constraints

1. **Never concatenate Turtle.** All writes go through toolkit RDF operations
   (`rdflib.Graph` / `ontology_ops`), matching the repo convention.
2. **Reviewed loop only.** Output is a branch + PR; the module cannot publish policy to
   runtime directly (ADR-12 / MDM-DD-003).
3. **Skill-backed.** Authoring flows delegate to the `kairos-design-mdm` skill's phases,
   pre-flight checks and validation gates — the UI is a front-end over the skill, not a
   parallel implementation.
4. **Validation before PR.** `mdm-validate` (structural + SHACL, MDM-DD-003) must pass and
   its semantic/runtime-impact preview must be shown before the PR can be opened.
5. **Digest-visible.** Show the projected profile's `content_digest` so reviewers see when
   policy content actually changed (vs. cosmetic/provenance-only diffs).

---

## 3. Authoring capabilities (maps to MDM-DESIGN stories)

| Panel | Authors | `kairos-mdm:` vocabulary | Story |
|---|---|---|---|
| **Scope** | Designate classes as master / reference data | `MasteredConcept`, `ReferenceListPolicy` | DESIGN-01 |
| **Identity & match** | Enterprise identifiers, match attributes, comparators, normalization refs | `MatchAttribute`, `MatchRule`, `matchAction` | DESIGN-02 |
| **Survivorship** | Attribute authority + survivorship strategy | `SurvivorshipRule` | DESIGN-03 |
| **Workflow** | Auto-action bounds, maker/checker, abstract steward roles | `WorkflowPolicy`, `StewardRole` | DESIGN-04 |
| **Reference lifecycle** | Ownership, release, deprecation | `ReferenceListPolicy` | DESIGN-05 |
| **Data quality** | DQ rules (six DAMA dimensions) + severity thresholds | `DataQualityRule` | DESIGN-06 |
| **Probabilistic ref** | Content-addressed pointer to an owned matching artifact (never weights) | `probabilisticArtifact` + `artifactDigest` | DESIGN-02 |
| **Validate & impact** | Run `mdm-validate`; show semantic + runtime impact | — | DESIGN-07 |
| **Project & review** | Project `mdm-profile`; open PR with digest | — | DESIGN-08 |
| **Evidence intake** | Load a runtime evidence pack to propose a reviewed change | — | DESIGN-09 |

---

## 4. Interaction flow

```text
select domain
  -> load {domain}.ttl + existing {domain}-mdm-ext.ttl (if any)
  -> author policy panel-by-panel (business terms; skill checkpoints)
  -> mdm-validate  (block on errors; surface warnings)
  -> project --target mdm-profile  (preview JSON/MD + content_digest + impact)
  -> open PR (branch, reviewer sees semantic diff + digest change)
  -> [later] runtime evidence pack -> proposed change -> back to author
```

Every checkpoint follows the **interactive-by-default** design-mode policy (governance sign-off
on match keys, survivorship, auto-action bounds, reference-data licensing) unless the user
explicitly opts into design-fleet mode.

---

## 5. Non-goals

- No live master-data editing, case management, merge/split, or RBAC enforcement — those are
  Stewardship UI / runtime (`kairos-mdm-runtime`).
- No direct DB or API writes to runtime state.
- No probabilistic weight editing in the UI (weights live in the owned, versioned artifact;
  the UI only references it by digest).
