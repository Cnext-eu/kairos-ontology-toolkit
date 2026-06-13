---
name: kairos-setup-init
description: >
  Step-by-step guide for creating a brand-new Kairos ontology hub repository
  from scratch using the CLI. Covers repo naming, bootstrapping, and initial
  validation. Only for new repo creation — NOT for ontology design or domain
  modeling.
---

# Quickstart — New Ontology Hub

> **🔒 Skill context:** Before running any `kairos-ontology` /
> `python -m kairos_ontology` command in this skill, set the sentinel env var so
> the CLI knows it runs inside a skill and suppresses its skill-gate warning:
> - PowerShell: `$env:KAIROS_SKILL_CONTEXT = "1"`
> - bash/zsh: `export KAIROS_SKILL_CONTEXT=1`

This guide walks through creating a brand-new ontology hub repo for a client
or project using the **kairos-ontology-toolkit** CLI.

> **CRITICAL:** Always use the `kairos-ontology` CLI commands (`new-repo`,
> `init`) to create the repo and scaffold files.  **Do NOT manually create
> or edit scaffold files** (.gitignore, README.md, shapes/README.md,
> copilot-instructions.md, skills, etc.).  The CLI creates everything
> automatically in a single command with no user confirmation needed.

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — Python package manager
  (`irm https://astral.sh/uv/install.ps1 | iex` on Windows,
  `curl -LsSf https://astral.sh/uv/install.sh | sh` on Linux/macOS)
- **Git** — installed and configured
- **[GitHub CLI (`gh`)](https://cli.github.com/)** — installed and authenticated
  (`gh auth login`)
- **kairos-ontology-toolkit** — installed automatically by `uv sync`

> **Tip:** In hub repos, run toolkit commands with `uv run kairos-ontology <command>`.
> This automatically uses the repo's isolated `.venv` without manual activation.

---

## 1. Repository naming convention

Every ontology hub repo follows the pattern:

```
<client-or-project>-ontology-hub
```

| Input | Resulting repo name |
|-------|-------------------|
| contoso | `contoso-ontology-hub` |
| acme-logistics | `acme-logistics-ontology-hub` |
| northwind traders | `northwind-traders-ontology-hub` |

Rules:
- Lowercase, hyphen-separated words.
- Always ends with `-ontology-hub`.
- No underscores, no uppercase, no special characters.

---

## 2. Create the repo (one command)

> **Run from outside any git repository.**  `cd` to the directory where you
> keep your repos first (e.g., `cd ~/projects`).  If the CLI detects you're
> inside a git repo it will error with clear instructions on how to fix it.

The repo is **always created on GitHub** (cloud) — never local-only.

### Cnext-eu repos (default)

For repos under the **Cnext-eu** organisation (the default `--org`), always
use the template — just run the bare command:

```bash
python -m kairos_ontology new-repo contoso
```

This uses the `kairos-app-template` template by default, which includes
CI workflows, standard labels, and branch protection.  **Do NOT pass
`--template ""`** — always keep the default template for Cnext-eu repos.

### External / third-party repos

For repos under a different GitHub org, skip the template since they won't
have access to it:

```bash
python -m kairos_ontology new-repo contoso --org Acme-Corp --template ""
```

### What `new-repo` creates

The command creates the GitHub repo, clones it, overlays the hub scaffold,
commits, and pushes — all in one step.  It does NOT ask for domains.

```
contoso-ontology-hub/
├── .github/
│   ├── copilot-instructions.md
│   ├── skills/                          # AI skills for Copilot
│   └── workflows/managed-check.yml
├── ontology-hub/
│   ├── README.md                        # Company context + domain overview
│   ├── model/                           # Domain model (ontology-centric)
│   │   ├── ontologies/
│   │   │   └── _master.ttl              # Master ontology (imports all domains)
│   │   ├── shapes/
│   │   ├── extensions/                  # *-silver-ext.ttl projection annotations
│   │   └── mappings/                    # Source-to-domain SKOS + kairos-map: mappings
│   ├── integration/                     # Source system integration
│   │   └── sources/                     # Source system docs + bronze vocab
│   └── output/                          # All projection outputs (committed)
│       ├── medallion/
│       │   ├── silver/
│       │   ├── gold/
│       │   └── dbt/
│       ├── neo4j/
│       ├── azure-search/
│       ├── a2ui/
│       └── prompt/
├── ontology-reference-models/           # Populated automatically by update-referencemodels.ps1
├── .gitignore
├── pyproject.toml                       # kairos-ontology-toolkit dependency
└── README.md
```

### CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--description TEXT` | auto | Short description for README / pyproject |
| `--path PATH` | current dir | Parent directory to create the repo in |
| `--org TEXT` | `Cnext-eu` | GitHub organisation |
| `--private / --public` | private | Repo visibility |
| `--company-domain TEXT` | `<name>.com` | Company domain for namespaces |
| `--template TEXT` | `kairos-app-template` | GitHub template. Keep default for Cnext-eu |
| `--ref-models-version` | latest | Git ref for reference models |

---

## 3. Set up the development environment

```bash
cd contoso-ontology-hub
.\setup-env.ps1          # Windows (PowerShell)
# or
./setup-env.sh           # Linux / macOS / CI
```

This uses `uv sync` to create an isolated `.venv` and install the
`kairos-ontology-toolkit` (from the `.whl` pinned in `pyproject.toml`).

Run toolkit commands without manual activation:

```bash
uv run kairos-ontology validate
uv run kairos-ontology project --target dbt
```

Or activate the venv for interactive work:

```bash
.\.venv\Scripts\Activate.ps1   # Windows
source .venv/bin/activate       # Linux / macOS
```

The hub's `pyproject.toml` includes a `[tool.kairos]` section with a
`channel` setting (default `"stable"`). To test pre-release toolkit
versions, change it to `"preview"` and run `uv run kairos-ontology update --upgrade`.

> **Why venvs?** Each hub repo gets its own isolated Python environment,
> preventing toolkit version conflicts between hub repos on the same machine.

---

## 4. Add your first domain

`new-repo` created the scaffold on `main`.  Now add the first domain — still
on `main` since this is initial setup:

```bash
python -m kairos_ontology init --company-domain contoso.com --domain customer
```

- `--company-domain` is **required** — sets the namespace base
  (`https://contoso.com/ont/`).
- `--domain` creates a starter `.ttl` file.  You can run `init` again later
  with a different `--domain` to add more.

The `init` command also creates `ontology-hub/README.md` (company context)
and `ontology-hub/model/ontologies/_master.ttl` (imports all domains) if they
don't exist yet.

Commit the scaffold to `main`:

```bash
git add . && git commit -m "chore: initial hub setup with customer domain" && git push
```

---

## 5. Edit the domain (on a feature branch)

From here on, **always work on a feature branch**.
Use the SC-feature-branch skill or:

```bash
git checkout -b ontology/customer-domain
```

Edit `ontology-hub/model/ontologies/customer.ttl` — see the
kairos-design-domain skill for design guidance.  At minimum ensure:

- `owl:Ontology` with `rdfs:label` and `owl:versionInfo`
- At least one `owl:Class` with `rdfs:label` and `rdfs:comment`
- Properties with `rdfs:domain`, `rdfs:range`, and `rdfs:label`
- HTTPS namespace: `https://contoso.com/ont/customer#`

---

## 6. Validate and project

```bash
python -m kairos_ontology validate
python -m kairos_ontology project
```

Fix any errors before proceeding.  Output lands in
`ontology-hub/output/<target>/`.

---

## 7. Add more domains (repeat)

```bash
python -m kairos_ontology init --company-domain contoso.com --domain order
```

Then update `_master.ttl` to import the new domain and add it to the
domain overview table in `ontology-hub/README.md`.

---

## 8. Push and create PR

```bash
git add .
git commit -m "ontology: add customer domain"
git push -u origin HEAD
gh pr create --base main --fill
```

Or use the SC-merge-pr skill.  Never push directly to `main`.

---

## 9. Next steps — the design→execute lifecycle

Creating the repo and a first domain is just the **Setup** phase. From here,
follow the recommended **Fresh Hub Lifecycle** (DD-040). Invoke the skill for
each phase rather than running raw CLI commands — the design skills add
interactive checkpoints and pre-flight checks.

```
discovery → source → domain → mapping → silver → gold → validate → project → diagnose → consume
```

| Phase | Invoke skill | Produces |
|-------|--------------|----------|
| Design — discovery | **kairos-design-discovery** | Company context + business glossary (`businessdiscovery/`) |
| Design — source | **kairos-design-source** | Bronze vocabulary (`*.vocabulary.ttl`) |
| Design — domain | **kairos-design-domain** | OWL classes + properties |
| Design — mapping | **kairos-design-mapping** | SKOS source→domain mappings |
| Design — silver | **kairos-design-silver** | `*-silver-ext.ttl` annotations |
| Design — gold | **kairos-design-gold** | `*-gold-ext.ttl` annotations |
| Execute — validate | **kairos-execute-validate** | Syntax + SHACL check |
| Execute — project | **kairos-execute-project** | All output artifacts |
| Diagnose | **kairos-diagnose-status** | Completeness / gap report |

> **Minimal first pass:** model a domain (**kairos-design-domain**), validate
> (**kairos-execute-validate**), then project the `prompt` / `neo4j` / `a2ui`
> targets (**kairos-execute-project**) — these need no extensions or mappings.
> Layer on source/mapping/silver/gold for the `dbt`, `silver`, and `powerbi`
> targets. See the **kairos-help** skill's *Fresh Hub Lifecycle* section for the
> full walkthrough.

---

## Quick reference

| Task | Command |
|------|---------|
| Create new hub repo | `python -m kairos_ontology new-repo <name>` |
| Init hub + first domain | `python -m kairos_ontology init --company-domain <domain> --domain <domain>` |
| Validate | `python -m kairos_ontology validate` |
| Project (all) | `python -m kairos_ontology project` |
| Project (single) | `python -m kairos_ontology project --target prompt` |
| Silver layer DDL | `python -m kairos_ontology project --target silver` (needs `*-silver-ext.ttl` in `model/extensions/`) |
| Test catalog | `python -m kairos_ontology catalog-test --catalog ontology-reference-models/catalog-v001.xml` |
