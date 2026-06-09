# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Azure Functions projector — generates Python Azure Functions app from integration mappings.

Produces a Python v2 programming model function app with HTTP-triggered functions
per source system, a shared mapper module, host.json, and local.settings.json.
Each function reads the integration mapping JSON at runtime to transform source
records into silver-layer entities.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .uri_utils import camel_to_snake

logger = logging.getLogger(__name__)


def generate_azure_functions_artifacts(
    classes: list,
    graph,
    template_dir,
    namespace: str,
    ontology_name: str = None,
    ontology_metadata: dict = None,
    sources_dir: Path = None,
    mappings_dir: Path = None,
    silver_ext_path: Path = None,
    **kwargs,
) -> dict[str, str]:
    """Generate Azure Functions Python v2 artifacts.

    Generates the integration mapping JSON (Layer 1) then wraps it with
    an Azure Functions app: one HTTP-triggered function per source system,
    a shared mapper module, and standard Functions configuration files.

    Returns:
        Dictionary of {file_path: content} for all generated artifacts.
    """
    from .integration_projector import generate_integration_artifacts

    domain = ontology_name or "domain"
    artifacts: dict[str, str] = {}

    mapping_artifacts = generate_integration_artifacts(
        classes=classes,
        graph=graph,
        template_dir=template_dir,
        namespace=namespace,
        ontology_name=ontology_name,
        ontology_metadata=ontology_metadata,
        sources_dir=sources_dir,
        mappings_dir=mappings_dir,
        silver_ext_path=silver_ext_path,
    )

    systems: dict[str, list[dict]] = {}
    for file_key, content in mapping_artifacts.items():
        if file_key.endswith("-mapping.json") or file_key.endswith("manifest.json"):
            fn_key = f"{domain}/mappings/{Path(file_key).name}"
            artifacts[fn_key] = content

        if file_key.endswith("-mapping.json"):
            try:
                mapping = json.loads(content)
                system = mapping.get("source", {}).get("system", "source")
                systems.setdefault(system, []).append(mapping)
            except (json.JSONDecodeError, KeyError):
                pass

    artifacts[f"{domain}/function_app.py"] = _generate_function_app(domain, systems)
    artifacts[f"{domain}/mapper.py"] = _generate_mapper()
    artifacts[f"{domain}/silver_client.py"] = _generate_silver_client(domain)
    artifacts[f"{domain}/host.json"] = _generate_host()
    artifacts[f"{domain}/local.settings.json"] = _generate_local_settings(domain)
    artifacts[f"{domain}/requirements.txt"] = _generate_requirements()
    artifacts[f"{domain}/README.md"] = _generate_readme(domain, systems)

    return artifacts


# ---------------------------------------------------------------------------
# App generators
# ---------------------------------------------------------------------------

def _generate_function_app(domain: str, systems: dict[str, list[dict]]) -> str:
    """Generate the main function_app.py with one HTTP function per source system."""
    function_blocks = []
    for system in sorted(systems.keys()):
        safe_system = _safe_identifier(system)
        mappings = systems[system]
        entity_list = [
            {
                "entity": m.get("metadata", {}).get("entity", "Entity"),
                "mapping_file": f"mappings/{system}-{camel_to_snake(m.get('metadata', {}).get('entity', 'entity'))}-mapping.json",
            }
            for m in mappings
        ]
        entity_list_repr = json.dumps(entity_list, indent=8)
        function_blocks.append(f'''
@app.route(route="{system}/ingest", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
def ingest_{safe_system}(req: func.HttpRequest) -> func.HttpResponse:
    """Ingest data from {system} and write transformed records to silver layer."""
    try:
        record = req.get_json()
    except ValueError:
        return func.HttpResponse("Invalid JSON body", status_code=400)

    entity_mappings = {entity_list_repr}

    results = []
    for em in entity_mappings:
        mapping = mapper.load_mapping(em["mapping_file"])
        if mapper.matches_source(record, mapping):
            transformed = mapper.transform(record, mapping)
            silver_client.write(em["entity"], transformed)
            results.append(em["entity"])
            logger.info("Processed %s record for %s", em["entity"], "{system}")

    if not results:
        logger.warning("No matching mapping found for {system} record")

    return func.HttpResponse(
        json.dumps({{"processed": results, "source": "{system}"}}),
        mimetype="application/json",
        status_code=200,
    )
''')

    functions_str = "\n".join(function_blocks)
    entity_names = ", ".join(
        f'"{m.get("metadata", {}).get("entity", "Entity")}"'
        for mappings in systems.values()
        for m in mappings
    )

    return f'''"""Azure Functions app for {domain} domain.

Auto-generated by kairos-ontology-toolkit. Customize as needed.

Entities: {entity_names or "none"}
"""

import json
import logging
import os

import azure.functions as func

import mapper
import silver_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
{functions_str}
'''


def _generate_mapper() -> str:
    """Generate the shared mapper module (mirrors the Dapr mapper pattern)."""
    return '''"""Generic mapping engine — reads integration mapping JSON at runtime.

Auto-generated by kairos-ontology-toolkit.
"""

import json
from pathlib import Path
from typing import Any


_cache: dict[str, dict] = {}


def load_mapping(mapping_path: str) -> dict:
    if mapping_path not in _cache:
        mapping_file = Path(mapping_path)
        if not mapping_file.is_absolute():
            app_root = Path(__file__).resolve().parent
            candidate = app_root / mapping_file
            mapping_file = candidate if candidate.exists() else mapping_file
        with open(mapping_file, encoding="utf-8") as f:
            _cache[mapping_path] = json.load(f)
    return _cache[mapping_path]


def matches_source(record: dict, mapping: dict) -> bool:
    mapped_cols = {cm["source_column"] for cm in mapping.get("column_mappings", [])}
    return bool(mapped_cols & set(record.keys()))


def transform(record: dict, mapping: dict) -> dict[str, Any]:
    result: dict[str, Any] = {}

    for cm in mapping.get("column_mappings", []):
        source_col = cm["source_column"]
        target_prop = cm["target_property"]

        if source_col in record:
            value = record[source_col]
            transform_expr = cm.get("transform")
            if transform_expr:
                value = _apply_transform(value, transform_expr)
            result[target_prop] = value
        elif cm.get("default_value") is not None:
            result[target_prop] = cm["default_value"]

    result["_source_system"] = mapping.get("source", {}).get("system", "unknown")
    result["_source_table"] = mapping.get("source", {}).get("table", "unknown")
    result["_entity"] = mapping.get("metadata", {}).get("entity", "unknown")

    return result


def _apply_transform(value: Any, transform_expr: str) -> Any:
    if not transform_expr or value is None:
        return value
    expr = transform_expr.strip()
    s = str(value)
    if expr.startswith("TRIM("):
        return s.strip()
    if expr.startswith("UPPER("):
        return s.upper()
    if expr.startswith("LOWER("):
        return s.lower()
    if "TRIM(UPPER(" in expr:
        return s.strip().upper()
    return value
'''


def _generate_silver_client(domain: str) -> str:
    return f'''"""Silver layer HTTP client.

Auto-generated by kairos-ontology-toolkit. Points at the silver API configured
via the SILVER_API_URL and SILVER_API_KEY environment variables.
"""

import json
import logging
import os
from typing import Any

import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

_BASE_URL = os.environ.get("SILVER_API_URL", "https://<your-silver-api>.azurewebsites.net/api")
_API_KEY = os.environ.get("SILVER_API_KEY", "")
_DOMAIN = "{domain}"


def write(entity: str, record: dict[str, Any]) -> None:
    """POST a transformed record to the silver layer API."""
    url = f"{{_BASE_URL}}/{{_DOMAIN}}/{{entity.lower()}}"
    body = json.dumps(record).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={{
            "Content-Type": "application/json",
            "Authorization": f"Bearer {{_API_KEY}}",
        }},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            logger.debug("Silver write %s → %s %s", entity, resp.status, url)
    except urllib.error.HTTPError as exc:
        logger.error("Silver write failed for %s: %s %s", entity, exc.code, exc.reason)
        raise
'''


def _generate_host() -> str:
    return json.dumps(
        {
            "version": "2.0",
            "logging": {
                "applicationInsights": {
                    "samplingSettings": {"isEnabled": True, "excludedTypes": "Request"}
                }
            },
            "extensionBundle": {
                "id": "Microsoft.Azure.Functions.ExtensionBundle",
                "version": "[4.*, 5.0.0)",
            },
        },
        indent=2,
    )


def _generate_local_settings(domain: str) -> str:
    return json.dumps(
        {
            "IsEncrypted": False,
            "Values": {
                "AzureWebJobsStorage": "UseDevelopmentStorage=true",
                "FUNCTIONS_WORKER_RUNTIME": "python",
                "SILVER_API_URL": "https://<your-silver-api>.azurewebsites.net/api",
                "SILVER_API_KEY": "<your-api-key>",
            },
        },
        indent=2,
    )


def _generate_requirements() -> str:
    return "azure-functions>=1.21.0\n"


def _generate_readme(domain: str, systems: dict[str, list[dict]]) -> str:
    systems_text = "\n".join(f"- `{s}`" for s in sorted(systems)) or "- (none)"
    entity_rows = []
    for system, mappings in sorted(systems.items()):
        for m in mappings:
            entity = m.get("metadata", {}).get("entity", "Entity")
            entity_rows.append(f"- `{system}` -> `{entity}`")
    entities_text = "\n".join(entity_rows) or "- (none)"

    return f"""# Azure Functions Integration Artifacts - {domain}

Auto-generated by kairos-ontology-toolkit.

## Included source systems

{systems_text}

## Mapped entities

{entities_text}

## Structure

- `function_app.py`: HTTP routes per source system
- `mapper.py`: Runtime integration mapping engine
- `silver_client.py`: Silver API writer
- `mappings/`: Integration mapping JSON files
- `host.json`, `local.settings.json`, `requirements.txt`

## Local dry run

1. Install dependencies:
   `pip install -r requirements.txt`
2. Start Azure Functions host:
   `func start`
3. Call one system route with a sample payload:
   `curl -X POST http://localhost:7071/api/<system>/ingest -H "Content-Type: application/json" -d '{{"name":"Acme"}}'`

## Notes

- Set `SILVER_API_URL` and `SILVER_API_KEY` in `local.settings.json`.
- Mapping files are shared with other integration projectors.
"""


def _safe_identifier(value: str) -> str:
    """Make a Python-safe identifier fragment from arbitrary source system names."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", value)
