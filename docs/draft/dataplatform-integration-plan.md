# Ontology Hub ↔ Dataplatform Repo Integration

## Problem Statement

The **pkfbofidi-ontology-hub** generates medallion dbt models (staging, silver, gold SQL) and DDL analyses that the **dataplatform** repo (dbt + Logic Apps + Bicep/Terraform) needs to consume. Currently there is no defined integration mechanism. Additionally, when dataplatform developers discover gaps (missing properties, needed extensions), they need a structured way to feed requests back to the ontology hub.

## Key Design Decisions

### Where do projections run?

**Projections run ONLY in the ontology-hub repo.** The dataplatform repo is a pure consumer.

Rationale:
- The ontology-hub has the toolkit installed (`kairos-ontology-toolkit @ git+...main`)
- The ontology-hub has all source ontologies, SHACL shapes, extensions, and mappings
- Running projections requires the full ontology context (imports, reference models, catalog)
- Keeping projection generation in one place ensures a single source of truth
- The dataplatform repo should NOT need Python/kairos-ontology-toolkit installed

### How does the dataplatform consume projections?

**`dbt deps` with a git package + subdirectory** — the native dbt approach.

The ontology-hub's dbt output at `ontology-hub/output/medallion/dbt/` already contains a valid `dbt_project.yml`. The dataplatform's `packages.yml` references it as a git package:

```yaml
# dataplatform/packages.yml
packages:
  - git: "https://github.com/Cnext-eu/pkfbofidi-ontology-hub.git"
    revision: v1.3.0   # pinned to ontology-hub release tag
    subdirectory: ontology-hub/output/medallion/dbt
```

Running `dbt deps` downloads the package into `dbt_packages/` (which is gitignored). The dataplatform can then `ref()` models from the ontology-hub package.

**Why `dbt deps` is better than git submodule:**

| Aspect | dbt deps (git package) | Git submodule |
|--------|----------------------|---------------|
| Native to dbt? | ✅ Yes — standard dbt workflow | ❌ No — requires git knowledge |
| Read-only? | ✅ Naturally — `dbt_packages/` is gitignored, regenerated on `dbt deps` | ⚠️ Not inherently — needs CI guard |
| Version pinning | ✅ `revision:` tag/commit | ✅ Submodule commit hash |
| Developer UX | ✅ Just run `dbt deps` | ⚠️ Need `--recurse-submodules` on clone |
| Works with dbt Cloud? | ✅ Yes | ⚠️ Needs extra config |
| Transitive deps | ✅ dbt resolves `dbt_utils` etc. automatically | ❌ Must install separately |
| CI setup | ✅ Standard `dbt deps && dbt build` | ⚠️ Extra checkout steps |

**Key advantage: transitive dependencies.** The ontology-hub dbt project already declares `dbt_utils` and `dbt_expectations` in its `packages.yml`. When consumed via `dbt deps`, these are resolved automatically.

## Proposed Approach

### A. Two Deliverable Packages

The medallion projection produces **two distinct deliverables** for downstream consumption:

#### Deliverable 1: dbt Package (Data Pipeline Models)

The dbt output at `ontology-hub/output/medallion/dbt/` is a complete dbt project consumable via `dbt deps`. It contains silver models, gold models, sources, and analyses (DDL/ALTER scripts).

**Dataplatform repo structure:**

```
dataplatform/
├── dbt_project.yml
├── models/              # Custom / override models (extending ontology-generated ones)
├── analyses/            # Custom analyses
├── packages.yml         # Git package pointing to ontology-hub
├── dbt_packages/        # ← gitignored, populated by `dbt deps`
│   └── pkfbofidi_ontology_hub/
│       ├── models/silver/    # Generated silver models
│       ├── models/gold/      # Generated gold models
│       └── analyses/         # DDL + ALTER scripts
├── logic-apps/
├── infra/               # Bicep / Terraform
└── .github/workflows/
```

**Consumption via `packages.yml`:**

```yaml
# dataplatform/packages.yml
packages:
  - git: "https://github.com/Cnext-eu/pkfbofidi-ontology-hub.git"
    revision: v1.3.0   # pinned to ontology-hub release tag
    subdirectory: ontology-hub/output/medallion/dbt
```

**Usage in dataplatform dbt project:**

```sql
-- Reference an ontology-generated silver model
SELECT * FROM {{ ref('pkfbofidi_ontology_hub', 'party') }}

-- Extend with custom business logic
SELECT
    p.*,
    custom_score
FROM {{ ref('pkfbofidi_ontology_hub', 'client') }} p
LEFT JOIN {{ ref('custom_scoring') }} cs ON p.client_sk = cs.client_sk
```

**Key advantage:** Transitive dependencies (`dbt_utils`, `dbt_expectations`) are resolved automatically by `dbt deps`.

#### Deliverable 2: Power BI Semantic Model Package (to be refined)

The gold projector outputs a Power BI semantic model at `ontology-hub/output/medallion/powerbi/`. This is the second deliverable — a deployable TMDL package for Power BI / Microsoft Fabric.

**Contents:**

```
output/medallion/powerbi/
├── {Domain}.SemanticModel/
│   └── definition/
│       ├── model.tmdl
│       ├── tables/
│       │   ├── dim_party.tmdl
│       │   ├── fact_engagement.tmdl
│       │   └── ...
│       ├── relationships/
│       ├── roles/              # RLS roles (GDPR-driven)
│       ├── perspectives/
│       └── calculationGroups/
├── master-gold-erd.mmd         # Mermaid ERD
├── {domain}-gold-ddl.sql       # Fabric Warehouse DDL
└── {domain}-gold-alter-fk.sql  # FK constraints
```

**Packaging:** Released as a zip artifact attached to the GitHub Release (see §B). The dataplatform repo (or a dedicated Power BI DevOps pipeline) downloads this artifact and deploys the TMDL via:

- **Option A:** Fabric REST API / Power BI ALM Toolkit (programmatic deployment)
- **Option B:** `fabric-cicd` Python package (Microsoft's official CI/CD tool for Fabric)
- **Option C:** Manual import into Power BI Desktop for local development

> **Status:** This deliverable is concept-level. Packaging format, deployment mechanism, and CI/CD integration will be refined in a subsequent iteration once the gold projector output stabilises.

---

### B. Versioning & Release Pipeline (Tag-Triggered)

#### Version Management

The ontology hub uses semantic versioning tracked in `VERSION.json`:

```json
{
  "version": "1.3.0",
  "toolkit_version": "0.14.0"
}
```

#### Release Trigger

A **tag push** (`v*`) triggers the release pipeline. This ensures:
- Releases are intentional (not every merge creates a release)
- The version tag maps 1:1 to a specific projection state
- The dataplatform can pin to an exact, immutable revision

#### Release Workflow (ontology-hub repo)

```yaml
# .github/workflows/release.yml (ontology-hub)
name: Release Projections

on:
  push:
    tags: ["v*"]

permissions:
  contents: write

jobs:
  project-and-release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          submodules: true

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install toolkit
        run: pip install kairos-ontology-toolkit

      - name: Run projections (all targets)
        run: |
          kairos-ontology project \
            --ontologies ontology-hub/model/ontologies \
            --shapes ontology-hub/model/shapes \
            --target all

      - name: Validate projections
        run: |
          kairos-ontology validate \
            --ontologies ontology-hub/model/ontologies \
            --shapes ontology-hub/model/shapes

      - name: Package Power BI semantic model
        run: |
          cd ontology-hub/output/medallion/powerbi
          zip -r ../../../../powerbi-semantic-model.zip .

      - name: Create GitHub Release
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          TAG="${GITHUB_REF#refs/tags/}"
          gh release create "$TAG" \
            powerbi-semantic-model.zip \
            --title "$TAG" \
            --generate-notes
```

#### Consumption Flow

```
ontology-hub (feature branch) → PR → main → tag v1.3.0 → Release pipeline
                                                                ↓
                                              ┌─────────────────┼────────────────────┐
                                              ↓                                      ↓
                               Deliverable 1: dbt                    Deliverable 2: Power BI
                               (git tag via dbt deps)                (zip from Release assets)
                                              ↓                                      ↓
                               dataplatform: packages.yml            Power BI DevOps pipeline
                               revision: v1.3.0 → dbt deps          downloads + deploys TMDL
```

#### Version Pinning & Upgrades

1. **dbt package:** Dataplatform pins `revision: v1.3.0` in `packages.yml`. To upgrade: change the tag, run `dbt deps`.
2. **Power BI package:** Pipeline downloads the specific release asset by tag. To upgrade: update the release tag reference.
3. **Optional automation:** A Renovate/Dependabot-style bot in the dataplatform repo can auto-create PRs when new ontology-hub releases appear.

---

### C. Feedback Loop: Gap Detection → GitHub Issues

When dataplatform developers identify ontology gaps (e.g., "we need a `billingFrequency` property on `ServiceEngagement` for the Logic App integration"):

1. **Manual path:** Developer creates a GitHub Issue on `Cnext-eu/pkfbofidi-ontology-hub` using a structured issue template (e.g., "Ontology Gap Request") with fields:
   - Domain affected (party, client, engagement, etc.)
   - Layer affected (ontology class/property, SHACL shape, silver-ext annotation, mapping)
   - Missing concept description
   - Business justification / use case in dataplatform
   - Suggested change (optional)
   - Link to dataplatform PR/issue that surfaced the gap

2. **Automated path (future):** A GitHub Actions workflow in the dataplatform repo runs after `dbt build`:
   - Compares compiled dbt manifest against Fabric Warehouse metadata
   - Detects schema drift (columns/tables in warehouse but not in projections)
   - Auto-creates a GitHub Issue on the ontology-hub repo via `gh issue create --repo Cnext-eu/pkfbofidi-ontology-hub`

3. **Issue template** lives in the ontology-hub repo at `.github/ISSUE_TEMPLATE/ontology-gap-request.yml`.

---

### D. Copilot Cloud Agent: Automated Implementation

#### Concept

When a gap request issue is created on the ontology-hub, the **GitHub Copilot cloud agent** can be assigned to automatically implement the change. The agent uses the ontology-hub's `.github/copilot-instructions.md` and Kairos skills to produce a high-quality implementation — without requiring a human to manually code the ontology change.

#### How It Works

```
dataplatform dev creates issue → ontology-hub issue (labeled `copilot-implement`)
                                         ↓
                              Assign issue to @copilot
                                         ↓
                              Copilot agent activates:
                                • Reads issue description
                                • Reads .github/copilot-instructions.md
                                • Uses Kairos skills (modeling, validation, projection)
                                • Implements change (edit .ttl, add extensions, etc.)
                                         ↓
                              Commits to copilot/<issue-number>-<slug> branch
                                         ↓
                              Human reviews branch → manually opens PR when satisfied
```

#### Prerequisites

| Requirement | Details |
|-------------|---------|
| Copilot plan | Copilot Business or Enterprise on the ontology-hub repo |
| Permissions | Copilot agent needs write access to create `copilot/*` branches |
| Skills | `.github/copilot-instructions.md` + `.github/skills/` must be present (already scaffolded by toolkit) |
| No auto-PR | Agent commits to branch only — no PR is created automatically |

#### Triggering the Agent

**Option 1 — Manual assignment (recommended initially):**
- A maintainer reviews the issue and assigns it to `@copilot` via the GitHub UI
- The agent activates, creates a workspace, and begins implementation

**Option 2 — Label-triggered (future automation):**
- When a label `copilot-implement` is added to an issue, a workflow assigns `@copilot`
- This can be combined with a triage step (human adds label after review)

```yaml
# .github/workflows/assign-copilot.yml (ontology-hub) — future automation
name: Assign Copilot Agent

on:
  issues:
    types: [labeled]

jobs:
  assign:
    if: github.event.label.name == 'copilot-implement'
    runs-on: ubuntu-latest
    steps:
      - name: Assign issue to Copilot
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh issue edit ${{ github.event.issue.number }} \
            --repo ${{ github.repository }} \
            --add-assignee "@copilot"
```

#### Kairos Skills Available to the Agent

The ontology-hub repo (scaffolded by the toolkit) includes these skills in `.github/skills/`:

| Skill | What the agent uses it for |
|-------|---------------------------|
| `kairos-ontology-modeling` | Adding/modifying classes, properties, relationships in .ttl files |
| `kairos-ontology-validation` | Validating syntax + SHACL after changes |
| `kairos-medallion-silver` | Understanding silver-ext annotation requirements |
| `kairos-medallion-gold` | Understanding gold-ext annotation requirements |
| `kairos-projection-generation` | Running projections to verify output |
| `kairos-medallion-staging` | Creating/updating bronze vocabulary descriptions |

#### Agent Behaviour Expectations

- The agent creates a branch named `copilot/<issue-number>-<short-description>`
- It commits one or more changes (ontology edits, extension files, updated projections)
- It does **NOT** create a PR automatically (deliberate design choice for human oversight)
- A maintainer reviews the branch, potentially refines, then opens a PR manually
- The PR references the original issue for traceability

#### Why No Auto-PR?

- Ontology changes affect multiple downstream systems (dbt, Power BI, search indexes)
- A human should verify the agent's interpretation of the gap request
- The review step ensures naming conventions, domain boundaries, and annotation rules are respected
- Once confidence in agent quality grows, auto-PR can be enabled as a future enhancement

---

### E. Implementation Todos

| # | Task | Where | Details |
|---|------|-------|---------|
| 1 | Create GitHub Issue template | ontology-hub | `.github/ISSUE_TEMPLATE/ontology-gap-request.yml` for structured gap requests |
| 2 | Document integration guide | ontology-hub | `docs/dataplatform-integration.md` — how to consume both deliverables, version pinning, feedback loop |
| 3 | Example `packages.yml` | in docs | Show dbt git package with subdirectory pointing to medallion dbt output |
| 4 | Add release workflow | ontology-hub | Tag-triggered GitHub Actions: run projections → validate → package Power BI zip → create Release |
| 5 | Verify dbt project name | ontology-hub | Ensure `dbt_project.yml` name works well as a dbt package name for cross-project `ref()` |
| 6 | Configure Copilot agent access | ontology-hub | Ensure Copilot Business/Enterprise is enabled, agent can create `copilot/*` branches |
| 7 | Add `copilot-implement` label | ontology-hub | Create the label + optional assign-copilot workflow |
| 8 | Refine Power BI package format | future | Define exact zip structure, deployment script, and Fabric CI/CD integration |
| 9 | Schema drift detection | future | CI job in dataplatform comparing dbt manifest vs warehouse; auto-creates issues |
| 10 | Auto-PR for Copilot agent | future | Once confidence is high, allow agent to open draft PRs |

---

### F. Considerations

**dbt project naming:** The current `dbt_project.yml` uses `name: 'service_project'`. For cross-project `ref()` calls (e.g., `ref('service_project', 'party')`), this name should be descriptive. Consider renaming to `pkfbofidi_ontology` or `ontology_models` so refs are clear in the dataplatform project.

**Private repo access:** Since both repos are in Cnext-eu, the git package URL works if the CI runner has access (SSH key or GitHub token). Document this in the integration guide.

**Version compatibility:** Document which ontology-hub release is compatible with which dataplatform version. The `projection-report.json` and per-domain manifests provide toolkit version and generation timestamps for traceability.

**Copilot agent quality:** The agent's effectiveness depends heavily on the quality of issue descriptions and available Kairos skills. Well-structured issue templates (with domain, layer, and business justification) give the agent enough context to produce correct implementations. Start with simple additive changes (new properties, new SHACL constraints) before attempting complex refactoring.

**Two-deliverable versioning:** Both deliverables (dbt + Power BI) are versioned together under the same release tag. If independent versioning is needed in the future, consider splitting into separate release assets with their own manifests.
