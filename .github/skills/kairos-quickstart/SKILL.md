---
name: kairos-quickstart
description: >
  Step-by-step guide for creating a new Kairos ontology hub repository.
  Covers repo naming, CLI bootstrapping, first domain, validation, and projections.
  Usable by both humans and AI assistants.
---

# Quickstart — New Ontology Hub

This guide walks through creating a brand-new ontology hub repo for a client
or project using the **kairos-ontology-toolkit** CLI.

> **CRITICAL:** Always use the `kairos-ontology` CLI commands (`new-repo`,
> `init`) to create the repo and scaffold files.  **Do NOT manually create
> or edit scaffold files** (.gitignore, README.md, shapes/README.md,
> copilot-instructions.md, skills, etc.).  The CLI creates everything
> automatically in a single command with no user confirmation needed.

## Prerequisites

- **Python 3.12+** with `pip`
- **Git** — installed and configured
- **[GitHub CLI (`gh`)](https://cli.github.com/)** — installed and authenticated
  (`gh auth login`)
- **kairos-ontology-toolkit** — `pip install kairos-ontology-toolkit`

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
kairos-ontology new-repo contoso
```

This uses the `kairos-app-template` template by default, which includes
CI workflows, standard labels, and branch protection.  **Do NOT pass
`--template ""`** — always keep the default template for Cnext-eu repos.

### External / third-party repos

For repos under a different GitHub org, skip the template since they won't
have access to it:

```bash
kairos-ontology new-repo contoso --org Acme-Corp --template ""
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
│   ├── ontologies/
│   │   └── _master.ttl                  # Master ontology (imports all domains)
│   ├── shapes/
│   ├── mappings/
│   └── output/                          # Gitignored
├── ontology-reference-models/           # Git submodule
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
| `--ref-models-version` | latest | Git ref for reference-models submodule |

---

## 3. Install the hub's dependencies

```bash
cd contoso-ontology-hub
pip install -e .
```

This installs the `kairos-ontology-toolkit` as a dependency of the hub and
makes the `kairos-ontology` CLI available in the hub's context.

---

## 4. Add your first domain

`new-repo` created the scaffold on `main`.  Now add the first domain — still
on `main` since this is initial setup:

```bash
kairos-ontology init --company-domain contoso.com --domain customer
```

- `--company-domain` is **required** — sets the namespace base
  (`https://contoso.com/ont/`).
- `--domain` creates a starter `.ttl` file.  You can run `init` again later
  with a different `--domain` to add more.

The `init` command also creates `ontology-hub/README.md` (company context)
and `ontology-hub/ontologies/_master.ttl` (imports all domains) if they
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

Edit `ontology-hub/ontologies/customer.ttl` — see the
kairos-ontology-modeling skill for design guidance.  At minimum ensure:

- `owl:Ontology` with `rdfs:label` and `owl:versionInfo`
- At least one `owl:Class` with `rdfs:label` and `rdfs:comment`
- Properties with `rdfs:domain`, `rdfs:range`, and `rdfs:label`
- HTTPS namespace: `https://contoso.com/ont/customer#`

---

## 6. Validate and project

```bash
kairos-ontology validate
kairos-ontology project
```

Fix any errors before proceeding.  Output lands in
`ontology-hub/output/<target>/`.

---

## 7. Add more domains (repeat)

```bash
kairos-ontology init --company-domain contoso.com --domain order
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

## Quick reference

| Task | Command |
|------|---------|
| Create new hub repo | `kairos-ontology new-repo <name>` |
| Init hub + first domain | `kairos-ontology init --company-domain <domain> --domain <domain>` |
| Validate | `kairos-ontology validate` |
| Project (all) | `kairos-ontology project` |
| Project (single) | `kairos-ontology project --target prompt` |
| Test catalog | `kairos-ontology catalog-test --catalog ontology-reference-models/catalog-v001.xml` |
