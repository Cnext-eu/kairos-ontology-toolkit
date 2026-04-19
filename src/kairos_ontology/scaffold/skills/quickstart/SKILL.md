---
name: quickstart
description: >
  Step-by-step guide for creating a new Kairos ontology hub repository.
  Covers repo naming, CLI bootstrapping, first domain, validation, and projections.
  Usable by both humans and AI assistants.
---

# Quickstart — New Ontology Hub

This guide walks through creating a brand-new ontology hub repo for a client
or project using the **kairos-ontology-toolkit** CLI.

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

## 2. Bootstrap a new repo (one command)

```bash
pip install kairos-ontology-toolkit

kairos-ontology new-repo contoso --domain customer
```

This creates a ready-to-use Git repository:

```
contoso-ontology-hub/
├── .github/
│   ├── copilot-instructions.md
│   └── skills/                          # AI skills for Copilot
├── ontology-hub/
│   ├── ontologies/customer.ttl          # Starter domain
│   ├── shapes/
│   ├── mappings/
│   └── output/                          # Gitignored
├── ontology-reference-models/
│   ├── authoritative-ontologies/
│   ├── derived-ontologies/
│   └── catalog-v001.xml
├── .gitignore
├── pyproject.toml                       # kairos-ontology-toolkit dependency
└── README.md
```

### CLI options

```bash
kairos-ontology new-repo <NAME> [OPTIONS]

Options:
  --domain TEXT          First ontology domain to scaffold (e.g., "customer").
  --description TEXT     Short description for README / pyproject.
  --path PATH            Parent directory (default: current directory).
  --org TEXT             GitHub organisation (default: Cnext-eu).
  --private / --public   Repo visibility (default: private).
```

The command always creates a GitHub repo under the given `--org` and pushes
the initial commit.  Requires the [GitHub CLI (`gh`)](https://cli.github.com/)
to be installed and authenticated.

---

## 3. Install dependencies

```bash
cd contoso-ontology-hub
pip install -e .
```

This installs `kairos-ontology-toolkit` and makes the `kairos-ontology` CLI
available. The repo itself has no Python code — just ontology files and config.

---

## 4. Define your first domain

Edit `ontology-hub/ontologies/customer.ttl`:

```turtle
@prefix : <http://contoso.example.org/ontology/customer#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<http://contoso.example.org/ontology/customer> a owl:Ontology ;
    rdfs:label "Customer"@en ;
    rdfs:comment "Customer domain ontology for Contoso"@en ;
    owl:versionInfo "0.1.0" .

:Customer a owl:Class ;
    rdfs:label "Customer"@en ;
    rdfs:comment "A person or organisation that purchases goods or services"@en .

:customerName a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Name"@en .

:customerEmail a owl:DatatypeProperty ;
    rdfs:domain :Customer ;
    rdfs:range xsd:string ;
    rdfs:label "Customer Email"@en .
```

---

## 5. Validate

```bash
kairos-ontology validate
```

Fix any syntax or SHACL errors before proceeding.

---

## 6. Generate projections

```bash
# Quick check — prompt context
kairos-ontology project --target prompt

# All targets
kairos-ontology project
```

Output lands in `ontology-hub/output/<target>/`.

---

## 7. Add more domains

Each domain is a separate `.ttl` file:

```bash
# Create another domain manually or use init in the repo
touch ontology-hub/ontologies/order.ttl
```

Domains can reference each other via `owl:imports`.

---

## 8. Commit and collaborate

```bash
git checkout -b feature/add-customer-domain
git add .
git commit -m "Add customer domain ontology"
git push -u origin feature/add-customer-domain
```

Open a PR for review. The Copilot skills installed in `.github/skills/` will
help reviewers and AI assistants understand the ontology structure.

---

## Quick reference

| Task | Command |
|------|---------|
| Create new hub repo | `kairos-ontology new-repo <name> --domain <domain>` |
| Init in existing repo | `kairos-ontology init --domain <domain>` |
| Validate | `kairos-ontology validate` |
| Project (all) | `kairos-ontology project` |
| Project (single) | `kairos-ontology project --target prompt` |
| Test catalog | `kairos-ontology catalog-test --catalog ontology-reference-models/catalog-v001.xml` |
