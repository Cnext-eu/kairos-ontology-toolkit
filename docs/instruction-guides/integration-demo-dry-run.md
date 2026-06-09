# Integration Demo Dry Run (Dapr + Logic Apps + Azure Functions)

Use this sequence in an ontology-hub repository to generate and smoke-check integration artifacts before the Tuesday demo.

## 1) Generate integration targets from your ontology

Run from the ontology-hub root (the folder that contains `model/` and `output/`).

```bash
uv run python - <<'PY'
from pathlib import Path
from kairos_ontology.projector import run_projections

hub = Path('.')
ontologies = hub / 'model' / 'ontologies'
catalog = hub / 'catalog-v001.xml'
output = hub / 'output'

for target in ('dapr', 'logic-apps', 'azure-functions'):
    print(f'\n=== Generating {target} ===')
    run_projections(
        ontologies_path=ontologies,
        catalog_path=catalog,
        output_path=output,
        target=target,
    )
PY
```

## 2) Verify generated artifacts exist

The scenario tests (Step 3) automate this check. For a quick manual scan:

```bash
find output -type f \( -path '*/dapr/*' -o -path '*/logic-apps/*' -o -path '*/azure-functions/*' \) | sort
```

Check that each domain has at least:

- Dapr: `components/`, `mappings/`, `app/`, `docker-compose.yaml`, `README.md`
- Logic Apps: `<system>/workflow.json`, `connections.json`, `host.json`, `local.settings.json`, `README.md`
- Azure Functions: `function_app.py`, `mapper.py`, `silver_client.py`, `host.json`, `local.settings.json`, `requirements.txt`, `README.md`

## 3) Run projector tests in toolkit repo (optional confidence check)

The toolkit ships two levels of test coverage for these targets:

**Unit tests** — validate generator logic with synthetic graphs:

```bash
uv run pytest tests/test_dapr_projector.py tests/test_logic_apps_projector.py tests/test_azure_functions_projector.py -q
```

**Scenario tests** — run the full pipeline against the acme-hub and assert the
expected file tree, valid JSON/YAML, and syntactically correct Python output:

```bash
uv run pytest tests/scenarios/test_scenario_projection.py::TestDaprOutputTree \
              tests/scenarios/test_scenario_projection.py::TestLogicAppsOutputTree \
              tests/scenarios/test_scenario_projection.py::TestAzureFunctionsOutputTree \
              -v -m ""
```

The scenario tests are the recommended gate before a demo — they cover all three
targets end-to-end against real acme-hub ontologies and mappings.

## 4) Target-specific smoke checks

### Dapr

From generated domain folder:

```bash
docker compose up --build
```

### Logic Apps Standard

From generated domain folder:

> **Note:** Logic Apps Standard uses the Azure Functions Core Tools runtime but
> requires the Logic Apps extension (`Microsoft.Azure.Workflows.WebJobs.Extension`).
> Install via `func extensions install` or use the
> [Azure Logic Apps Standard local project template](https://learn.microsoft.com/azure/logic-apps/create-standard-workflows-visual-studio-code).

```bash
func start
```

POST sample payload to trigger endpoint and confirm transform + silver write actions.

### Azure Functions

From generated domain folder:

```bash
pip install -r requirements.txt
func start
curl -X POST http://localhost:7071/api/<system>/ingest -H "Content-Type: application/json" -d '{"name":"Acme"}'
```

## 5) Demo readiness gate

Treat the run as demo-ready when all are true:

- Artifact generation succeeds for all three targets.
- Route/trigger executes with a sample payload.
- At least one mapped entity is transformed and sent to silver endpoint.
- No unresolved placeholder settings remain for the demo environment.
