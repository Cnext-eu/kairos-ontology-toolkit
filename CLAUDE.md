# kairos-ontology-toolkit

CLI toolkit that turns OWL/Turtle ontologies into production-ready data artifacts — dbt models, Neo4j schemas, Azure Search indexes, Dapr apps, Logic Apps workflows, Azure Functions, and more.

## Commands

```bash
# Run tests (always use uv run — direct python -m pytest picks up wrong venv)
uv run pytest                        # fast suite only (slow marker excluded by default)
uv run pytest -m slow                # include slow QA checks
uv run pytest tests/test_dapr_projector.py -q   # single file

# Lint / format
uv run ruff check src tests
uv run black src tests

# CLI
kairos-ontology --help
kairos-ontology project --ontologies model/ontologies --output output --target dapr
kairos-ontology validate --ontologies model/ontologies --all
kairos-ontology init --domain acme --company-domain acme.example
kairos-ontology analyse-sources --sources integration/sources --output output
```

## Architecture

```
src/kairos_ontology/
  projector.py              # Target router — registers all valid targets, calls projections/
  projections/
    shared.py               # Shared RDF namespaces (KAIROS_EXT, KAIROS_INT) + merge_ext_graph()
    mapping_parser.py       # SKOS → mapping dict parser (shared by integration/dapr/n8n/LA/AF)
    integration_projector.py  # Layer 1: target-agnostic mapping JSON per source×entity
    dapr_projector.py         # Layer 2a: Dapr components + Python app + docker-compose
    n8n_projector.py          # Layer 2b: n8n importable workflow JSON
    logic_apps_projector.py   # Layer 2c: Logic Apps Standard workflow.json per source
    azure_functions_projector.py  # Layer 2d: Python v2 Azure Functions app
    medallion_dbt_projector.py    # Medallion: bronze→silver→gold dbt models
    medallion_silver_projector.py
    medallion_gold_projector.py
  cli/main.py               # Click CLI entry point
  scaffold/                 # Hub scaffold templates (kairos-int.ttl, copilot-instructions.md)
  templates/                # Jinja2 templates for dbt

tests/
  scenarios/acme-hub/       # Full synthetic hub: client + invoice + logistics domains,
                            # 4 source systems (adminpulse, billingpro, crmsystem, logisticspro)
  scenarios/conftest.py     # Shared fixtures: HUB_ROOT, _load_ontology(), MAPPINGS_DIR, SOURCES_DIR
  scenarios/test_scenario_projection.py  # End-to-end: run_projections() against acme-hub
```

## Valid projection targets

`dbt`, `neo4j`, `azure-search`, `a2ui`, `prompt`, `silver`, `gold`, `report`, `integration`, `dapr`, `n8n`, `logic-apps`, `azure-functions`, `all`

Integration targets (`integration`, `dapr`, `n8n`, `logic-apps`, `azure-functions`) all call `generate_integration_artifacts()` first (Layer 1), then wrap the output.

## Extension files

| File pattern | Used by |
|---|---|
| `*-silver-ext.ttl` | `silver`, `dbt`, and all integration targets (naturalKey, scdType) |
| `*-gold-ext.ttl` | `gold`, `dbt` |
| `*-integration-ext.ttl` | `integration`, `dapr`, `n8n` (kairos-int: annotations) |

`kairos-int:` vocabulary (`scaffold/kairos-int.ttl`): `loadStrategy`, `batchSize`, `errorStrategy`, `retryPolicy`, `schedule`, `incrementalWatermark`, `preLoadHook`, `postLoadHook`, `deadLetterTopic`. Dapr uses `schedule` for input binding cron and `retryPolicy` to generate `components/resiliency.yaml`.

## Gotchas

- **Always use `uv run pytest`** — the project venv is `.venv/`; running via system Python or a mismatched venv silently uses wrong deps.
- **`slow` tests are excluded by default** (`addopts = "-m 'not slow'"` in pyproject.toml). Run with `-m slow` explicitly for full QA.
- **Integration scenario tests use module-scoped fixtures** — `projected_hub` copies acme-hub to a tmp dir and runs `run_projections(target="all")` once per session. Don't add state-mutating setup that breaks parallelism.
- **No `catalog-v001.xml` in acme-hub** — `run_projections()` falls back gracefully when the catalog path doesn't exist.
- **`_safe_identifier()`** exists in both `dapr_projector.py` and `azure_functions_projector.py` to sanitize source system names (e.g. `erp-core` → `erp_core`) for Python identifiers and Dapr handler names.
- **All Layer 2 projectors return `dict[str, str]`** (`{file_path: content}`). The file paths are relative to an output root — `projector.py` writes them via `_write_artifacts()`.
