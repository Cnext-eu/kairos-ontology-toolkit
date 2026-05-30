# DD-033: Skill Lifecycle Architecture — Design / Execute Separation

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-05-30 |
| **Scope** | All Copilot skills |
| **Impact** | Skill naming, routing, scaffold distribution |

> **Implementation status:** Phase 1 (design/execute separation) and Phase 2 (rename to
> shorter `kairos-design-*`, `kairos-execute-project`, etc.) are both implemented on the
> `rename-alignment-strategies` branch. All skills now use the new naming convention.

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
│ Setup   │  kairos-setup-init                                          │
│         │  kairos-setup-config                                         │
│         │  kairos-setup-migrate                                       │
├─────────┼───────────────────────────────────────────────────────────┤
│ Design  │  kairos-design-source     (bronze vocabulary)             │
│         │  kairos-design-domain     (OWL ontology)                  │
│         │  kairos-design-mapping    (SKOS source→domain)            │
│         │  kairos-design-silver     (silver annotations)            │
│         │  kairos-design-gold       (gold annotations)              │
├─────────┼───────────────────────────────────────────────────────────┤
│ Execute │  kairos-execute-project           (generate all projection targets│
│         │  kairos-execute-validate          (syntax + SHACL check)          │
│         │  kairos-execute-report            (HTML mapping reports)          │
├─────────┼───────────────────────────────────────────────────────────┤
│ Diagnose│  kairos-diagnose-status        (completeness check)            │
├─────────┼───────────────────────────────────────────────────────────┤
│ Consume │  kairos-package-dataplatform      (dbt package in downstream repo)│
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
| Execute | `kairos-execute-project` / `kairos-execute-validate` / `kairos-execute-report` | ❌ No | ❌ No | ✅ Yes |
| Setup | `kairos-hub-*` | Minimal | ✅ Yes (scaffolding) | ✅ Yes |
| Diagnose | `kairos-diagnose-status` | ❌ No | ❌ No | ✅ Yes (read-only) |
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
| `kairos-ontology-mapping-report` | `kairos-execute-report` | Rename + merge scope |
| `kairos-ontology-projection` | `kairos-execute-project` | Rename + absorb all execution |
| `kairos-ontology-validation` | `kairos-execute-validate` | Rename |
| `kairos-ontology-hub-status` | `kairos-diagnose-status` | Rename |
| `kairos-ontology-hub-setup` | `kairos-setup-config` | Rename |
| `kairos-ontology-hub-migration` | `kairos-setup-migrate` | Rename |
| `kairos-ontology-quickstart` | `kairos-setup-init` | Rename |
| `kairos-ontology-help` | `kairos-help` | Rename |
| `kairos-ontology-dataplatform` | `kairos-package-dataplatform` | Rename |
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
> To generate the silver DDL and dbt models, invoke `kairos-execute-project --target silver`
> (or use the **kairos-execute-project** skill)."

### What changes for `kairos-design-gold` (currently `medallion-gold`)

**Before:** Creates annotation file → runs `project --target powerbi` → shows output.

**After:** Creates annotation file → ends with:
> "Gold annotations are ready in `model/extensions/{domain}-gold-ext.ttl`.
> To generate the Power BI TMDL and star schema, invoke `kairos-execute-project --target powerbi`
> (or use the **kairos-execute-project** skill)."

### What changes for `kairos-execute-project` (currently `projection`)

**Before:** Runs projections; if annotations are missing, suggests invoking medallion skill.

**After:** Same behavior but becomes **the single execution entry point**. All "run this"
requests route here. Pre-flight checks still point to design skills when files are missing.

## Routing Table (new)

```markdown
| User intent | Skill |
|---|---|
| "How does Kairos work?" | **kairos-help** |
| "Create a new hub" | **kairos-setup-init** |
| "Set up / configure hub" | **kairos-setup-config** |
| "Upgrade hub structure" | **kairos-setup-migrate** |
| "Describe source systems / create bronze vocab" | **kairos-design-source** |
| "Model / design / create classes / properties" | **kairos-design-domain** |
| "Map source columns to domain" | **kairos-design-mapping** |
| "Design silver annotations / SCD / FK / natural keys" | **kairos-design-silver** |
| "Design gold annotations / measures / hierarchies" | **kairos-design-gold** |
| "Generate / run projection / produce dbt / DDL / TMDL" | **kairos-execute-project** |
| "Validate ontology" | **kairos-execute-validate** |
| "Generate mapping report" | **kairos-execute-report** |
| "What's the status / what's missing" | **kairos-diagnose-status** |
| "Use dbt package in data platform" | **kairos-package-dataplatform** |
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
- Add handoff language pointing to `kairos-execute-project`
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
   (next in lifecycle) or to `kairos-execute-project` (execution).
3. **Execute skills never ask design questions.** If prerequisites are missing,
   they say what's missing and point to the design skill that creates it.
4. **The lifecycle flow is a recommendation, not enforcement.** Users can invoke
   any skill at any time — the routing table guides, not restricts.
