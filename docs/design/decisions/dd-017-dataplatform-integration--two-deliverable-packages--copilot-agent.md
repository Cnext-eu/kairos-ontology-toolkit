# DD-017: Dataplatform Integration — Two Deliverable Packages + Copilot Agent

**Status:** Accepted
**Date:** 2026-04-30
**Affects:** scaffold workflows, issue templates, CLI `init`/`new-repo` commands
**Implementation:** `scaffold/github-workflows/release-projections.yml`, `assign-copilot.yml`, `copilot-setup-steps.yml`, `scaffold/github-issue-templates/ontology-gap-request.yml`, `cli/main.py`

### Context

The ontology-hub generates medallion projections (dbt models, Power BI TMDL, DDL) that
a downstream **dataplatform** repo needs to consume. There was no defined integration
mechanism — no release pipeline, no feedback loop for gap requests, and no automation
for implementing ontology changes requested by the dataplatform team.

### Decision

Introduce a **two-deliverable packaging model** with a **tag-triggered release pipeline**
and **Copilot coding agent automation** for gap-request implementation:

| Component | Mechanism |
|-----------|-----------|
| **Deliverable 1: dbt package** | Consumed via `dbt deps` with git package + `revision:` tag pin |
| **Deliverable 2: Power BI semantic model** | Zip artifact attached to GitHub Release (TMDL files) |
| **Release pipeline** | Tag-triggered (`v*`) workflow: project → validate → package → GitHub Release |
| **Feedback loop** | Structured issue template (`ontology-gap-request.yml`) for cross-repo gap requests |
| **Copilot agent** | Label `copilot-implement` → assign `@copilot` → agent implements → draft PR |
| **Agent environment** | `copilot-setup-steps.yml` installs Python + toolkit + Node.js |

### Scaffold Files Added

| File | Purpose |
|------|---------|
| `github-workflows/release-projections.yml` | Tag-triggered release: projections + validate + zip + GitHub Release |
| `github-workflows/assign-copilot.yml` | Label-triggered: assigns `@copilot` to implement gap requests |
| `github-workflows/copilot-setup-steps.yml` | Agent development environment (Python 3.12, toolkit, Node.js) |
| `github-issue-templates/ontology-gap-request.yml` | Structured form: domain, layer, description, justification |

### Key Design Choices

1. **Copilot creates a draft PR** (not "no PR") — this is native agent behaviour and
   cannot be suppressed. The draft PR is the review mechanism.

2. **`copilot-setup-steps.yml` is critical** — without it, the agent cannot install the
   toolkit, validate ontologies, or run projections. The job MUST be named
   `copilot-setup-steps` for GitHub to recognise it.

3. **Cross-repo issue creation is the dataplatform's responsibility** — the ontology-hub
   only receives issues. The dataplatform repo uses a PAT or GitHub App to create issues
   on the ontology-hub via `gh issue create --repo`.

4. **Label-triggered assignment is optional** — maintainers can assign `@copilot` directly
   from the GitHub UI. The workflow adds automation for teams preferring label-based triage.

5. **Both deliverables share a single version tag** — if independent versioning is needed
   later, the release workflow can be split.

### Rationale

- **dbt deps** is the native, standard mechanism for dbt package consumption (vs git submodules)
- **Tag-triggered** releases are intentional (not every merge creates a release)
- **Copilot agent** reduces human effort for routine ontology changes (add property, add constraint)
- **Issue templates** enforce structured gap requests — giving the agent clear context
- **`copilot-setup-steps.yml`** follows GitHub's official best practice for agent environment config

### Consequences

- Hub repos must have Copilot Business/Enterprise for the agent features
- The Power BI package format is concept-level; deployment tooling will be refined later
- The `copilot-implement` label must be created manually in new repos (not auto-created by scaffold)
