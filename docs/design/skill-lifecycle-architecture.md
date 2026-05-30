# DD-033: Skill Lifecycle Architecture — Design / Execute Separation

| Field | Value |
|-------|-------|
| **Status** | Proposed |
| **Date** | 2026-05-30 |
| **Scope** | All Copilot skills |
| **Impact** | Skill naming, routing, scaffold distribution |

> ⚠️ **Implementation status:** Phase 1 (design/execute separation) is implemented —
> design skills no longer run projections directly. Phase 2 (rename to shorter names
> like `kairos-design-silver`, `kairos-project`) is **not yet implemented**. Current
> skill names remain `kairos-ontology-*` until the rename PR.

---

## Context

The toolkit ships 19 Copilot skills that evolved organically. The `medallion-silver`
and `medallion-gold` skills currently combine interactive design decisions (creating
annotation files) with execution (running the projection). This creates routing
confusion: users and the LLM cannot reliably determine whether to invoke `projection`
or `medallion-silver` when they want to generate silver output.

## Decision

Reorganize all skills into **lifecycle groups** with a strict separation between
**design** (interactive, checkpoint-gated, modifies source files) and **execute**
(non-interactive, runs commands, produces artifacts).

## Lifecycle Groups

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ONTOLOGY HUB LIFECYCLE                       │
├─────────┬───────────────────────────────────────────────────────────┤
│  PHASE  │  SKILLS                                                   │
├─────────┼───────────────────────────────────────────────────────────┤
│ Orient  │  kairos-help                                              │
├─────────┼───────────────────────────────────────────────────────────┤
│ Setup   │  kairos-hub-init                                          │
│         │  kairos-hub-setup                                         │
│         │  kairos-hub-migrate                                       │
├─────────┼───────────────────────────────────────────────────────────┤
│ Design  │  kairos-design-source     (bronze vocabulary)             │
│         │  kairos-design-domain     (OWL ontology)                  │
│         │  kairos-design-mapping    (SKOS source→domain)            │
│         │  kairos-design-silver     (silver annotations)            │
│         │  kairos-design-gold       (gold annotations)              │
├─────────┼───────────────────────────────────────────────────────────┤
│ Execute │  kairos-project           (generate all projection targets│
│         │  kairos-validate          (syntax + SHACL check)          │
│         │  kairos-report            (HTML mapping reports)          │
├─────────┼───────────────────────────────────────────────────────────┤
│ Diagnose│  kairos-hub-status        (completeness check)            │
├─────────┼───────────────────────────────────────────────────────────┤
│ Consume │  kairos-dataplatform      (dbt package in downstream repo)│
├─────────┼───────────────────────────────────────────────────────────┤
│ Toolkit │  kairos-toolkit-dev       (modify the toolkit)            │
│ (internal) kairos-toolkit-ops       (release, upgrade, versioning)  │
├─────────┼───────────────────────────────────────────────────────────┤
│ Workflow│  SC-feature-branch        (create branch)                 │
│ (git)   │  SC-merge-pr              (PR + merge)                    │
│         │  SC-document              (Outline wiki)                  │
└─────────┴───────────────────────────────────────────────────────────┘
```

## Design Flow (left to right)

```
source → domain → mapping → silver → gold → project
  │        │         │         │        │        │
  │        │         │         │        │        └── Generate ALL outputs
  │        │         │         │        └── Design gold annotations
  │        │         │         └── Design silver annotations
  │        │         └── Map source columns to domain properties
  │        └── Model OWL classes + properties
  └── Describe source systems (bronze vocab)
```

Each design skill creates/modifies files. The `project` skill reads those files
and generates output. **No design skill runs projections.** No execute skill makes
design decisions.

## Naming Convention

| Group | Prefix | Interactive? | Modifies source? | Runs commands? |
|-------|--------|---|---|---|
| Design | `kairos-design-*` | ✅ Yes (checkpoints) | ✅ Yes | ❌ No |
| Execute | `kairos-project` / `kairos-validate` / `kairos-report` | ❌ No | ❌ No | ✅ Yes |
| Setup | `kairos-hub-*` | Minimal | ✅ Yes (scaffolding) | ✅ Yes |
| Diagnose | `kairos-hub-status` | ❌ No | ❌ No | ✅ Yes (read-only) |
| Orientation | `kairos-help` | ❌ No | ❌ No | ❌ No |

**Key simplification:** Drop the verbose `kairos-ontology-` prefix. The Copilot
context already knows we're in an ontology toolkit. Shorter names reduce cognitive
load in routing tables and cross-references.

## Migration Mapping

| Current name | New name | Type of change |
|---|---|---|
| `kairos-ontology-modeling` | `kairos-design-domain` | Rename |
| `kairos-ontology-medallion-source` | `kairos-design-source` | Rename |
| `kairos-ontology-medallion-silver` | `kairos-design-silver` | Rename + **strip execution** |
| `kairos-ontology-medallion-gold` | `kairos-design-gold` | Rename + **strip execution** |
| `kairos-ontology-mapping` | `kairos-design-mapping` | Rename |
| `kairos-ontology-mapping-report` | `kairos-report` | Rename + merge scope |
| `kairos-ontology-projection` | `kairos-project` | Rename + absorb all execution |
| `kairos-ontology-validation` | `kairos-validate` | Rename |
| `kairos-ontology-hub-status` | `kairos-hub-status` | Rename |
| `kairos-ontology-hub-setup` | `kairos-hub-setup` | Rename |
| `kairos-ontology-hub-migration` | `kairos-hub-migrate` | Rename |
| `kairos-ontology-quickstart` | `kairos-hub-init` | Rename |
| `kairos-ontology-help` | `kairos-help` | Rename |
| `kairos-ontology-dataplatform` | `kairos-dataplatform` | Rename |
| `kairos-ontology-toolkit-dev` | `kairos-toolkit-dev` | Rename |
| `kairos-ontology-toolkit-ops` | `kairos-toolkit-ops` | Rename |
| `SC-feature-branch` | `SC-feature-branch` | Keep (workflow, not ontology) |
| `SC-merge-pr` | `SC-merge-pr` | Keep |
| `SC-document` | `SC-document` | Keep |

**Net result:** 19 skills → 19 skills (no merge/split). Cleaner names, clear lifecycle.

## Behavioral Changes

### What changes for `kairos-design-silver` (currently `medallion-silver`)

**Before:** Creates annotation file → runs `project --target silver` → shows output.

**After:** Creates annotation file → ends with:
> "Silver annotations are ready in `model/extensions/{domain}-silver-ext.ttl`.
> To generate the silver DDL and dbt models, invoke `kairos-project --target silver`
> (or use the **kairos-project** skill)."

### What changes for `kairos-design-gold` (currently `medallion-gold`)

**Before:** Creates annotation file → runs `project --target powerbi` → shows output.

**After:** Creates annotation file → ends with:
> "Gold annotations are ready in `model/extensions/{domain}-gold-ext.ttl`.
> To generate the Power BI TMDL and star schema, invoke `kairos-project --target powerbi`
> (or use the **kairos-project** skill)."

### What changes for `kairos-project` (currently `projection`)

**Before:** Runs projections; if annotations are missing, suggests invoking medallion skill.

**After:** Same behavior but becomes **the single execution entry point**. All "run this"
requests route here. Pre-flight checks still point to design skills when files are missing.

## Routing Table (new)

```markdown
| User intent | Skill |
|---|---|
| "How does Kairos work?" | **kairos-help** |
| "Create a new hub" | **kairos-hub-init** |
| "Set up / configure hub" | **kairos-hub-setup** |
| "Upgrade hub structure" | **kairos-hub-migrate** |
| "Describe source systems / create bronze vocab" | **kairos-design-source** |
| "Model / design / create classes / properties" | **kairos-design-domain** |
| "Map source columns to domain" | **kairos-design-mapping** |
| "Design silver annotations / SCD / FK / natural keys" | **kairos-design-silver** |
| "Design gold annotations / measures / hierarchies" | **kairos-design-gold** |
| "Generate / run projection / produce dbt / DDL / TMDL" | **kairos-project** |
| "Validate ontology" | **kairos-validate** |
| "Generate mapping report" | **kairos-report** |
| "What's the status / what's missing" | **kairos-hub-status** |
| "Use dbt package in data platform" | **kairos-dataplatform** |
| "Release / upgrade toolkit" | **kairos-toolkit-ops** |
```

## Hub Update Strategy

Existing hubs will receive new skill names via `kairos-ontology update`:
1. Old skill folders are removed
2. New skill folders are written
3. `copilot-instructions.md` is regenerated with new routing table

The `update` command already handles managed-file replacement. Skills are managed files.

## Implementation Phases

### Phase 1: Strip execution from medallion skills (this PR)
- Remove "run projection" steps from silver and gold skills
- Add handoff language pointing to `kairos-project`
- Fix routing guidance in copilot-instructions
- Keep current names (rename comes in Phase 2)

### Phase 2: Rename all skills (separate PR, major version bump)
- Rename all `.github/skills/` folders
- Update all cross-references within skills
- Update `copilot-instructions.md` routing table
- Update scaffold
- Bump to v3.0.0 (breaking change for hub `update`)

### Phase 3: Hub update (after Phase 2 release)
- Run `kairos-ontology update` on all managed hubs
- Verify old skill folders are cleaned up
- Verify new routing works correctly

## Alternatives Considered

### Keep medallion skills doing both design + execute (status quo)
**Rejected:** Creates persistent routing confusion. Users don't know whether to
invoke `projection` or `medallion-silver` for "generate my silver output."

### Merge all execution into medallion skills (remove projection skill)
**Rejected:** Leaves non-medallion targets (neo4j, azure-search, a2ui, prompt)
without a clear home. Also violates single-responsibility — design skills shouldn't
own command execution logic.

### Just fix the documentation
**Rejected:** Documentation alone doesn't solve the structural issue. The LLM sees
the skill description and routes based on it. If silver's description says "generate
dbt models," it will be invoked for execution.

---

## Appendix: Design Skill Interaction Rules

1. **Design skills never call CLI commands** that produce output artifacts.
   They may read files (to check what exists) but never write to `output/`.
2. **Design skills always end with a handoff** — either to another design skill
   (next in lifecycle) or to `kairos-project` (execution).
3. **Execute skills never ask design questions.** If prerequisites are missing,
   they say what's missing and point to the design skill that creates it.
4. **The lifecycle flow is a recommendation, not enforcement.** Users can invoke
   any skill at any time — the routing table guides, not restricts.
