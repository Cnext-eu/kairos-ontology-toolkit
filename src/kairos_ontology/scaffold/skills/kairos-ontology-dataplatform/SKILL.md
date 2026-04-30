---
name: kairos-ontology-dataplatform
description: >
  Guide for consuming ontology-hub projection outputs in a downstream dataplatform
  repository. Covers dbt package consumption (via dbt deps), Power BI semantic model
  deployment, version pinning, release pipeline, and the feedback loop for gap requests.
---

# Kairos Dataplatform Integration Skill

You help users set up and manage the integration between an **ontology-hub** repo
(which generates medallion projections) and a downstream **dataplatform** repo
(which consumes those projections for data pipelines, BI models, and reporting).

## Before you start

0. **Quick toolkit version check** — run `python -m kairos_ontology update --check` once
   at the start of the session. If it reports outdated files, run
   `python -m kairos_ontology update` and commit the refresh before doing any other work.

## Key Principle: Ontology-Hub is the Producer

```
ontology-hub (producer)              dataplatform (consumer)
┌────────────────────────┐           ┌────────────────────────┐
│ model/ontologies/*.ttl │           │ dbt_project.yml        │
│ model/extensions/      │           │ packages.yml ──────┐   │
│ integration/sources/   │           │ models/ (custom)   │   │
│ integration/mappings/  │           │ dbt_packages/ ◄────┘   │
│                        │           │   └── ontology_hub/    │
│ output/medallion/dbt/  │ ────────► │       ├── models/      │
│ output/medallion/powerbi/ │ ─────► │       └── analyses/    │
└────────────────────────┘           │ infra/ (Bicep/TF)      │
         │                           └────────────────────────┘
         │ GitHub Release (v1.3.0)
         └── powerbi-semantic-model.zip
```

- **Projections run ONLY in the ontology-hub** — it has the toolkit, ontologies, shapes,
  extensions, and mappings. The dataplatform does NOT need the toolkit installed.
- The dataplatform is a **pure consumer** — it pins to a release tag and runs `dbt deps`.

---

## Deliverable 1: dbt Package (Data Pipeline Models)

### What's included

The dbt output at `ontology-hub/output/medallion/dbt/` is a complete dbt project:

```
output/medallion/dbt/
├── dbt_project.yml
├── packages.yml           # dbt_utils, dbt_expectations
├── models/
│   ├── silver/
│   │   ├── _sources.yml   # Bronze table references
│   │   └── {domain}/
│   │       ├── {entity}.sql
│   │       └── _{domain}__models.yml
│   └── gold/
│       └── {domain}/
│           ├── dim_{entity}.sql
│           └── fact_{entity}.sql
└── analyses/
    └── {domain}/
        ├── {domain}-silver-ddl.sql
        ├── {domain}-silver-alter-fk.sql
        ├── {domain}-gold-ddl.sql
        └── {domain}-gold-alter-fk.sql
```

### Consumption via `dbt deps`

In the dataplatform repo's `packages.yml`:

```yaml
# dataplatform/packages.yml
packages:
  - git: "https://github.com/{org}/{ontology-hub-repo}.git"
    revision: v1.3.0   # pinned to ontology-hub release tag
    subdirectory: ontology-hub/output/medallion/dbt
```

Then run:

```bash
dbt deps    # Downloads the package into dbt_packages/
dbt build   # Builds all models (including ontology-generated ones)
```

### Cross-project `ref()` usage

Reference ontology-generated models from your custom dataplatform models:

```sql
-- Reference an ontology-generated silver model
SELECT * FROM {{ ref('ontology_hub', 'party') }}

-- Extend with custom business logic
SELECT
    p.*,
    custom_score
FROM {{ ref('ontology_hub', 'client') }} p
LEFT JOIN {{ ref('custom_scoring') }} cs ON p.client_sk = cs.client_sk
```

> **Note:** The first argument to `ref()` is the dbt project name from the
> ontology-hub's `dbt_project.yml` (`name:` field). Verify this matches.

### Transitive dependencies

The ontology-hub's `packages.yml` declares `dbt_utils` and `dbt_expectations`.
When consumed via `dbt deps`, these are resolved automatically — no need to
duplicate them in the dataplatform's `packages.yml`.

---

## Deliverable 2: Power BI Semantic Model

### What's included

The gold projector outputs TMDL files at `ontology-hub/output/medallion/powerbi/`:

```
output/medallion/powerbi/
├── {Domain}.SemanticModel/
│   └── definition/
│       ├── model.tmdl
│       ├── tables/          # dim_*, fact_*, bridge_*
│       ├── relationships/
│       ├── roles/           # RLS roles (GDPR-driven)
│       ├── perspectives/
│       └── calculationGroups/
├── master-gold-erd.mmd
├── {domain}-gold-ddl.sql
└── {domain}-gold-alter-fk.sql
```

### Consumption

The Power BI package is released as a **zip artifact** attached to the GitHub Release:

```bash
# Download from a specific release
gh release download v1.3.0 --pattern "powerbi-semantic-model.zip" \
  --repo {org}/{ontology-hub-repo}
unzip powerbi-semantic-model.zip -d semantic-model/
```

Deployment options:
- **fabric-cicd** Python package (Microsoft's official CI/CD tool)
- **Fabric REST API** / Power BI ALM Toolkit (programmatic)
- **Power BI Desktop** import (local development)

> **Status:** This deliverable's packaging and deployment mechanism is being refined.

---

## Version Management & Release Pipeline

### Semantic versioning

The ontology-hub uses semantic versioning tracked in `VERSION.json`:

```json
{ "version": "1.3.0", "toolkit_version": "0.14.0" }
```

### Tag-triggered release

A **tag push** (`v*`) triggers the release pipeline (`.github/workflows/release-projections.yml`):

1. Checkout repo (with submodules)
2. Install toolkit (`pip install kairos-ontology-toolkit`)
3. Run all projections (`kairos-ontology project --target all`)
4. Validate ontologies (`kairos-ontology validate`)
5. Package Power BI output as zip
6. Create GitHub Release with artifacts

### Upgrading in the dataplatform

```yaml
# Before (old version)
- git: "https://github.com/{org}/{hub-repo}.git"
  revision: v1.2.0
  subdirectory: ontology-hub/output/medallion/dbt

# After (new version)
- git: "https://github.com/{org}/{hub-repo}.git"
  revision: v1.3.0   # ← update this
  subdirectory: ontology-hub/output/medallion/dbt
```

Then: `dbt deps && dbt build && dbt test`

### Optional: automated upgrade PRs

Use Renovate or Dependabot to auto-create PRs in the dataplatform repo when new
ontology-hub releases appear.

---

## Feedback Loop: Gap Requests

When the dataplatform team discovers a missing concept (property, class, annotation):

### 1. Create a gap request issue

Use the structured issue template on the ontology-hub repo
(`.github/ISSUE_TEMPLATE/ontology-gap-request.yml`):

- **Domain affected** — which ontology domain
- **Layer affected** — class, property, SHACL, silver-ext, gold-ext, mapping
- **Description** — what's missing
- **Justification** — why it's needed (use case in dataplatform)
- **Suggested change** — optional Turtle snippet

### 2. Cross-repo issue creation (from dataplatform CI)

```bash
# In a dataplatform GitHub Actions workflow:
gh issue create \
  --repo {org}/{ontology-hub-repo} \
  --title "[Gap] Add billingFrequency to ServiceEngagement" \
  --template "ontology-gap-request.yml" \
  --body "..."
```

> Requires a PAT or GitHub App token with `issues: write` on the ontology-hub.

### 3. Copilot agent automation

When the issue is labeled `copilot-implement`:
1. The `assign-copilot.yml` workflow assigns `@copilot`
2. Copilot reads the issue + `.github/copilot-instructions.md` + Kairos skills
3. Copilot implements the change (edits .ttl, adds extensions, runs validation)
4. Copilot opens a **draft PR** for human review
5. Maintainer reviews, refines if needed, and merges

---

## Setup Checklist (for new ontology-hub repos)

These files are automatically scaffolded by `kairos-ontology init` or `kairos-ontology new-repo`:

| File | Purpose |
|------|---------|
| `.github/workflows/release-projections.yml` | Tag-triggered release pipeline |
| `.github/workflows/assign-copilot.yml` | Label-triggered Copilot agent assignment |
| `.github/workflows/copilot-setup-steps.yml` | Agent environment (Python + toolkit) |
| `.github/ISSUE_TEMPLATE/ontology-gap-request.yml` | Structured gap request form |

### Manual steps after scaffold:

1. **Create the `copilot-implement` label** on the ontology-hub repo (GitHub UI → Issues → Labels)
2. **Verify dbt project name** in `output/medallion/dbt/dbt_project.yml` — this is used in cross-project `ref()` calls
3. **Configure repo access** — ensure the dataplatform CI runner can clone the ontology-hub (SSH key or PAT)
4. **Enable Copilot** — Copilot Business/Enterprise must be enabled for the agent features

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `dbt deps` fails with auth error | Ensure CI runner has access to the ontology-hub repo (PAT or SSH key) |
| Cross-project `ref()` not found | Check the `name:` field in the ontology-hub's `dbt_project.yml` matches your ref |
| Stale models after ontology change | Update `revision:` in `packages.yml` to the new release tag, re-run `dbt deps` |
| Copilot agent doesn't activate | Verify Copilot Business/Enterprise is enabled and `copilot-setup-steps.yml` exists |
| Power BI zip empty | Ensure gold extensions (`*-gold-ext.ttl`) exist in `model/extensions/` |
