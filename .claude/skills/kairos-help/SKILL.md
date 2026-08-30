---
name: kairos-help
description: Orientation to Kairos v5 authored inputs, canonical compilation, commands, and skills.
---

# Kairos Help

## 👋 Welcome to the Kairos Ontology Toolkit

**Purpose:** Kairos helps your organization agree on one shared definition of your business data —
like what a "customer," "invoice," or "product" really means — and then automatically turns that
shared understanding into working data pipelines, reports, dashboards, and search tools. Instead of
every team defining things their own way, Kairos keeps everyone aligned on one source of truth and
keeps all downstream systems consistent with it, automatically.

### 🔄 Lifecycle stages

| Stage | What happens |
|---|---|
| **1. Orient** | Get oriented or check the health of your project. |
| **2. Setup** | Set up a new project or configure an existing one. |
| **3. Discover** | Agree on business terms and context together. |
| **4. Design** | Connect source systems, define shared business concepts, and describe how data maps between them. |
| **5. Validate** | Check that everything is correct and consistent. |
| **6. Compile / Execute** | Generate the resulting pipelines and artifacts, and review the results. |
| **7. Consume** | Connect the generated output to downstream systems that will use it. |
| **(Toolkit)** | Maintain or release the toolkit itself — for internal maintainers only. |

### 🧰 Skills reference

| Skill | Purpose | Example prompt |
|---|---|---|
| `kairos-help` | Orientation to Kairos v5 | "What is Kairos and how do I get started?" |
| `kairos-diagnose-status` | Read-only hub diagnostic | "Show me the current state of my hub." |
| `kairos-setup-init` | Create a fresh v5 hub | "Scaffold a new ontology hub called acme-hub." |
| `kairos-setup-config` | Configure hub layout | "Add a new source folder to kairos.yaml." |
| `kairos-setup-migrate` | Migrate flat-layout hubs | "Migrate my old hub to the v5 layout." |
| `kairos-design-discovery` | Capture business context/terms | "Document what 'customer churn' means for this domain." |
| `kairos-design-source` | Import/document source schemas | "Import the schema for our billing Postgres table." |
| `kairos-design-domain` | Design OWL classes/properties | "Add an Invoice class with an issuedDate property." |
| `kairos-design-mapping` | Author EntityBinding YAML | "Bind the billing.invoices table to the Invoice entity." |
| `scaffold-binding` | Auto-scaffold first-draft bindings | "Generate a skeleton binding for the crm.organisations table." |
| `fit-report` | Inspect property coverage before mapping | "Show me which Invoice properties my data already populates." |
| `inverse-scan` | Find candidate source tables for a class | "Which source tables have columns matching Invoice properties?" |
| `kairos-develop-dbt-transformation` | Complex contracted dbt SQL | "Write a dbt model to dedupe invoice line items." |
| `kairos-design-gold` | Design Gold/BI products | "Create a Gold model for monthly invoice summaries." |
| `kairos-design-mdm` | Author MDM policy | "Define survivorship rules for duplicate customers." |
| `kairos-execute-validate` | Validate syntax/SHACL/bindings | "Check my ontology and bindings for errors." |
| `kairos-execute-project` | Compile check/explain/emit | "Compile the billing domain and show diagnostics." |
| `kairos-execute-report` | Review bindings and compile explain | "Show me a report of all EntityBindings." |
| `kairos-setup-dataplatform` | Scaffold downstream dbt repo | "Set up a new dbt repo to consume compiled output." |
| `kairos-package-dataplatform` | Consume artifacts downstream | "Wire the billing dbt package into our platform repo." |
| `kairos-toolkit-dev` | Develop the toolkit itself | "Add a new CLI flag to the compile command." |
| `kairos-toolkit-ops` | Release/update managed files | "Bump the toolkit version and sync scaffold files." |
| `SC-merge-pr` | Open/merge a PR | "Open a PR to merge this feature branch." |
| `SC-document` | Manage Outline wiki docs | "Update the wiki page for our ontology conventions." |

## Technical reference

Kairos v5 turns authored source schemas, OWL meaning, and closed EntityBinding YAML into one
immutable CompilePlan and deterministic downstream artifacts.

## Authoritative inputs

- `model/ontologies/<domain>.ttl`: canonical OWL meaning
- `model/shapes/`: optional SHACL
- `integration/sources/<source>/*.ttl`: physical source schema and redacted samples
- `integration/bindings/*.binding.yaml`: sole source-to-canonical execution authority
- `integration/transforms/dbt/models/`: ordinary contracted dbt SQL/YAML for complex logic
- `decisions/` (`ontology-hub/decisions/`): OKF Decision Log for durable rationale of
  material ontology choices
- `kairos.yaml`: namespace, catalog, adapters, and selected roots
- `../ontology-hub-publish/`: derived artifacts only (sibling of the hub)
- `CICD.md` / `CONTRIBUTING.md`: managed branching, review, validation, promotion,
  rollback, and hotfix guidance for this repository

Never read a raw `.ttl`/`.rdf`/`.owl` file as text; use `resolve-ontology`, `show-class-inventory`,
`list-class-properties`, or `explain-term` if semantic detail is needed.

## Canonical commands

```powershell
kairos-ontology compile <domain> --check --format json
kairos-ontology compile <domain> --explain --format json
kairos-ontology compile <domain> --emit --confirm-emit
kairos-ontology decision new
kairos-ontology validate
```

Use `kairos-design-source`, `kairos-design-domain`, and `kairos-design-mapping` to author inputs;
`kairos-develop-dbt-transformation` for ordinary contracted dbt models; `kairos-design-gold` and
`kairos-design-mdm` for optional consumers; `kairos-execute-validate` for validation; and
`kairos-toolkit-ops` for managed files, versions, and reference models. Use
`kairos-ontology decision new` for material ontology-decision rationale; `validate` lints an
existing Decision Log bundle.

A successful compile means the selected inputs can produce a CompilePlan. Run downstream dbt,
adapter, deployment, and data tests separately.
