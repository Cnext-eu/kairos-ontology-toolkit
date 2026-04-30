---
name: kairos-toolkit-development
description: >
  Developer guide for modifying, extending, and releasing the kairos-ontology-toolkit.
  Covers project structure, CLI commands, scaffold system, projectors, service,
  tests, managed-file stamping, and release process.
---

# Toolkit Development Skill

You are working on the **kairos-ontology-toolkit** itself — the Python package
that provides the `kairos-ontology` CLI and FastAPI service for managing
OWL/Turtle ontologies.

## Project structure

```
src/kairos_ontology/
├── __init__.py              # Package version (__version__)
├── cli/main.py              # Click CLI — all commands live here
├── ontology_ops.py          # CRUD operations on rdflib Graphs
├── validator.py             # Syntax + SHACL validation
├── projector.py             # Orchestrates projection generation
├── catalog_utils.py         # OASIS XML catalog import resolution
├── projections/             # One module per projection target
│   ├── medallion_dbt_projector.py
│   ├── medallion_silver_projector.py
│   ├── medallion_gold_projector.py
│   ├── neo4j_projector.py
│   ├── azure_search_projector.py
│   ├── a2ui_projector.py
│   ├── prompt_projector.py
│   ├── report_projector.py
│   └── skos_utils.py        # SKOS synonym parsing
├── scaffold/                # Templates + static files for init/new-repo
│   ├── copilot-instructions.md
│   ├── pyproject.toml.template
│   ├── README.md.template
│   ├── gitignore.template
│   ├── update-referencemodels.ps1
│   ├── github-workflows/managed-check.yml
│   ├── ontology-hub/
│   │   ├── README.md.template           # Company context ({company_name}, {company_domain})
│   │   ├── ontologies/starter.ttl.template
│   │   ├── ontologies/master.ttl.template
│   │   ├── ontologies/README.md
│   │   ├── shapes/README.md
│   │   └── mappings/README.md
│   └── skills/                          # Skills installed into hub repos
│       ├── kairos-hub-setup/SKILL.md
│       ├── kairos-ontology-modeling/SKILL.md
│       ├── kairos-ontology-validation/SKILL.md
│       ├── kairos-projection-generation/SKILL.md
│       ├── kairos-toolkit-ops/SKILL.md
│       ├── SC-feature-branch/SKILL.md
│       └── SC-merge-pr/SKILL.md
└── templates/               # Jinja2 templates for projections
    ├── dbt/
    ├── neo4j/
    ├── azure-search/
    ├── a2ui/
    └── prompt/

service/app/                 # FastAPI service (optional install)
├── main.py                  # App factory, CORS, health check
├── config.py                # Pydantic settings
├── routers/
│   ├── chat.py              # POST /api/chat (SSE streaming)
│   ├── ontology.py          # GET /api/ontology/query, POST change/apply
│   ├── projection.py        # POST /api/project
│   └── validation.py        # POST /api/validate
└── services/
    ├── github_service.py    # GitHub API client
    ├── local_service.py     # Local file operations
    └── sdk_service.py       # Copilot SDK integration

tests/                       # Toolkit tests (pytest)
tests/service/               # Service endpoint tests
```

## Code conventions

- Python 3.12+.  Line length 100 (black + ruff).
- `rdflib.Graph` for all RDF operations — never concatenate TTL strings.
- Async for FastAPI endpoints; sync for core toolkit and CLI.
- Entry point: `kairos-ontology = "kairos_ontology.cli.main:cli"` (Click).

## CLI commands (cli/main.py)

| Command | Key options | Purpose |
|---------|-------------|---------|
| `init` | `--domain`, `--company-domain` (required), `--force` | Scaffold hub in cwd |
| `new-repo` | `NAME`, `--company-domain`, `--org`, `--template` | Create full GitHub repo |
| `validate` | `--syntax`, `--shacl`, `--consistency`, `--catalog` | Validate ontologies |
| `project` | `--target`, `--namespace`, `--catalog` | Generate projection artifacts |
| `catalog-test` | `--catalog`, `--ontology` | Test import resolution |
| `update` | `--check` | Refresh managed files to current version |

### Adding or modifying a CLI command

1. Commands are Click functions in `src/kairos_ontology/cli/main.py`.
2. Use `@cli.command()` and `@click.option()`/`@click.argument()`.
3. Mock `subprocess.run` in tests — the CLI shells out to `git` and `gh`.
4. Print status with emoji prefixes: `✓` success, `⏭` skipped, `⚠` warning.

## Scaffold system

### Template placeholders

| Placeholder | Source | Used in |
|-------------|--------|---------|
| `{repo_name}` | `_slugify(name)` | pyproject.toml.template, README.md.template |
| `{description}` | `--description` option | pyproject.toml.template, README.md.template |
| `{domain}` | `--domain` option | starter.ttl.template |
| `{label}` | Title-cased domain | starter.ttl.template |
| `{company_name}` | Derived from company_domain | hub README.md.template, master.ttl.template |
| `{company_domain}` | `--company-domain` option | hub README, master.ttl, starter.ttl |

Templates use simple `str.replace()`, not Jinja2.  Projection templates use
Jinja2 (under `src/kairos_ontology/templates/`).

### Managed-file stamping

Toolkit-owned files (copilot-instructions.md, SKILL.md files) carry a version
marker so `kairos-ontology update` can detect and refresh them.

```
<!-- kairos-ontology-toolkit:managed v1.2.0 -->
```

Key functions:
- `_stamp_managed(content, version)` — insert/replace marker after YAML front-matter.
- `_get_managed_version(content)` — extract version from marker.
- `_copy_managed(src, dst)` — copy + stamp.
- `_managed_scaffold_map()` — returns `{relative_path: scaffold_source}` for all managed files.

When adding a new managed file:
1. Add the source in `src/kairos_ontology/scaffold/`.
2. Add the mapping in `_managed_scaffold_map()`.
3. Copy via `_copy_managed()` in both `init()` and `new_repo()`.
4. The `update` command will automatically pick it up.

### Adding a new scaffold file

**Static file** (not managed, not templated):
1. Add file to `src/kairos_ontology/scaffold/`.
2. Use `shutil.copy2(src, dst)` in `init()` and `new_repo()`.

**Template file** (has placeholders):
1. Add file with `.template` suffix to scaffold directory.
2. In `init()` and `new_repo()`, read → replace placeholders → write.
3. Do NOT mark as managed (templates are one-time generation).

**Managed file** (toolkit-owned, auto-updatable):
1. Add file to scaffold, add to `_managed_scaffold_map()`.
2. Use `_copy_managed()` for installation.
3. Users can override, but `kairos-ontology update` will refresh them.

## Projection system

### Architecture

`projector.py` → discovers `.ttl` files → loads via rdflib → delegates to
target-specific modules in `projections/` → renders Jinja2 templates from
`templates/`.

### Adding a new projection target

1. Create `src/kairos_ontology/projections/{target}_projector.py`.
2. Implement a function `generate(graph, namespace, output_path, domain)`.
3. Create Jinja2 templates in `src/kairos_ontology/templates/{target}/`.
4. Register the target in `projector.py`'s target dispatch.
5. Add the output directory to the scaffold structure (in `init()` and
   `new_repo()`).
6. Add tests in `tests/test_projector.py`.
7. Update `kairos-projection-generation` skill (both copies).

### Projection targets

| Target | Output | Template |
|--------|--------|----------|
| dbt | `{domain}/models/silver/{class}.sql` + `schema.yml` | `templates/dbt/` |
| neo4j | `{domain}-schema.cypher` | `templates/neo4j/` |
| azure-search | `{domain}/indexes/{domain}-index.json` | `templates/azure-search/` |
| a2ui | `{domain}/schemas/{domain}-message-schema.json` | `templates/a2ui/` |
| prompt | `{domain}-context.json` + detailed variant | `templates/prompt/` |
| silver | DDL + ALTER + Mermaid ERD | *(no template — inline SQL)* |
| powerbi | Star schema DDL + TMDL + DAX + ERD | *(no template — inline)* |

## Validation system

`validator.py` provides:
- `validate_content(ontology_str, shapes_str, do_syntax, do_shacl)` → dict
- `run_validation(ontologies_path, shapes_path, ...)` → prints + JSON report

Validation levels: syntax (rdflib parse), SHACL (pySHACL), consistency (placeholder).

## FastAPI service

Optional install group (`pip install -e ".[service]"`).

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check |
| `/api/config` | GET | Dev mode flag |
| `/api/ontology/query` | GET | List/search classes |
| `/api/ontology/change` | POST | Propose ontology diff |
| `/api/ontology/apply` | POST | Create PR with changes |
| `/api/validate` | POST | Validate domain from repo |
| `/api/validate/content` | POST | Validate raw TTL |
| `/api/project` | POST | Generate artifacts |
| `/api/chat` | POST | SSE chat with Copilot SDK |

Auth: `Authorization: Bearer <token>` header → GitHub API.

## Testing

### Conventions

- Tests in `tests/` for core toolkit, `tests/service/` for API.
- Use `CliRunner` (Click) for CLI tests, `mock.patch("...subprocess.run")`.
- Fixtures in `tests/conftest.py`: `sample_ontology`, `ontology_files`, etc.
- Run: `python -m pytest tests/ -v --tb=short`.

### What to test when changing...

| Changed area | Test file | What to assert |
|--------------|-----------|----------------|
| CLI command | `tests/test_init.py` | Exit code, created files, printed output |
| Scaffold template | `tests/test_init.py` | File content after init/new-repo |
| Validator | `tests/test_validator.py` | Syntax/SHACL pass/fail, error messages |
| Projector | `tests/test_projector.py` | Output files exist, content correctness |
| Managed files | `tests/test_init.py` | Stamping, update --check, version drift |
| Service endpoint | `tests/service/test_*.py` | HTTP status, response body |

### Running tests

```bash
# All tests
python -m pytest tests/ -v --tb=short

# Specific file
python -m pytest tests/test_init.py -v

# With coverage
python -m pytest tests/ --cov=kairos_ontology --cov-report=term-missing
```

## Skills system

Skills live in TWO places — keep them in sync:

| Location | Purpose |
|----------|---------|
| `.github/skills/kairos-*/SKILL.md` | Used by Copilot in THIS repo |
| `src/kairos_ontology/scaffold/skills/kairos-*/SKILL.md` | Installed into hub repos |

When modifying a skill, update BOTH copies.  The scaffold copy is the source
of truth for hub repos.

### Adding a new skill

1. Create `src/kairos_ontology/scaffold/skills/{skill-name}/SKILL.md`.
2. Mirror to `.github/skills/{skill-name}/SKILL.md`.
3. The skill is auto-installed by `init()` and `new_repo()` via the skills
   loop that iterates `_SCAFFOLD_DIR / "skills"`.
4. It becomes a managed file automatically (the skills loop uses `_copy_managed`).

## Release process

1. Ensure clean working tree (`git status`).
2. Run `.\release.ps1` (Windows) or `./release.sh` (Linux/macOS).
3. Select Patch / Minor / Major.
4. Script bumps version in `pyproject.toml` and `src/kairos_ontology/__init__.py`.
5. Builds with Poetry, commits, tags `vX.Y.Z`, pushes.
6. CI publishes to PyPI.

### Version locations

- `pyproject.toml` → `[tool.poetry] version`
- `src/kairos_ontology/__init__.py` → `__version__`
- Managed-file stamps → `<!-- kairos-ontology-toolkit:managed vX.Y.Z -->`

All three must stay in sync.  The release script handles the first two.
Managed stamps are applied at install time (from `__version__`).

## Dependencies

| Package | Purpose |
|---------|---------|
| `rdflib` | RDF graph parsing, SPARQL |
| `pySHACL` | SHACL validation |
| `Jinja2` | Projection templates |
| `click` | CLI framework |
| `fastapi` | Service (optional) |
| `github-copilot-sdk` | Chat integration (optional) |

## Common development workflows

### Add a CLI option

1. Add `@click.option()` to the command in `cli/main.py`.
2. Pass parameter through to the function body.
3. Update tests in `test_init.py` — add the option to ALL existing invocations
   if it's required.
4. Run `python -m pytest tests/test_init.py -v`.

### Modify a scaffold template

1. Edit the `.template` file in `src/kairos_ontology/scaffold/`.
2. If it introduces new placeholders, wire them in `init()` and `new_repo()`.
3. Add a test asserting the placeholder is replaced in output.

### Add a projection target

1. Create projector module + Jinja2 templates.
2. Register in `projector.py`.
3. Add output dir to scaffold.
4. Add tests + update projection skill.

### Update a managed skill

1. Edit `src/kairos_ontology/scaffold/skills/{name}/SKILL.md`.
2. Copy to `.github/skills/{name}/SKILL.md`.
3. Hub repos get the update via `kairos-ontology update`.
