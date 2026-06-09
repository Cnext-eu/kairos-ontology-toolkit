# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Logic Apps projector — generates Logic Apps Standard workflow definitions.

Produces Logic Apps Standard workflow.json, connections.json, and host.json
from integration mappings. Each source system becomes a stateful workflow
with an HTTP trigger → mapping transform → silver layer write topology.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .uri_utils import camel_to_snake

logger = logging.getLogger(__name__)


def generate_logic_apps_artifacts(
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
    """Generate Logic Apps Standard artifacts.

    Generates the integration mapping JSON (Layer 1) then wraps it with
    Logic Apps Standard workflow definitions: HTTP trigger → parse mapping
    → transform → HTTP connector write to silver API.

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
            la_key = f"{domain}/mappings/{Path(file_key).name}"
            artifacts[la_key] = content

        if file_key.endswith("-mapping.json"):
            try:
                mapping = json.loads(content)
                system = mapping.get("source", {}).get("system", "source")
                systems.setdefault(system, []).append(mapping)
            except (json.JSONDecodeError, KeyError):
                pass

    for system, mappings in sorted(systems.items()):
        workflow_dir = f"{domain}/{system}"
        artifacts[f"{workflow_dir}/workflow.json"] = _generate_workflow(system, mappings, domain)

    artifacts[f"{domain}/connections.json"] = _generate_connections(domain)
    artifacts[f"{domain}/host.json"] = _generate_host()
    artifacts[f"{domain}/local.settings.json"] = _generate_local_settings(domain)
    artifacts[f"{domain}/README.md"] = _generate_readme(domain, systems)

    return artifacts


# ---------------------------------------------------------------------------
# Workflow generators
# ---------------------------------------------------------------------------

def _generate_workflow(system: str, mappings: list[dict], domain: str) -> str:
    """Generate a Logic Apps Standard stateful workflow for one source system."""
    entity_transforms = []
    for mapping in mappings:
        entity = mapping.get("metadata", {}).get("entity", "Entity")
        snake = camel_to_snake(entity)
        mapping_file = f"mappings/{system}-{snake}-mapping.json"
        cols = mapping.get("column_mappings", [])
        set_expressions = {
            cm["target_property"]: f"@{{{_col_expression(cm)}}}"
            for cm in cols
            if cm.get("target_property") and cm.get("source_column")
        }
        entity_transforms.append({
            "entity": entity,
            "mapping_file": mapping_file,
            "set_expressions": set_expressions,
        })

    actions: dict[str, Any] = {
        "Parse_body": {
            "type": "ParseJson",
            "inputs": {
                "content": "@triggerBody()",
                "schema": {
                    "type": "object",
                    "properties": {},
                },
            },
            "runAfter": {},
        }
    }

    prev_action = "Parse_body"
    for et in entity_transforms:
        entity = et["entity"]
        action_name = f"Transform_{entity}"
        write_name = f"Write_{entity}_to_silver"

        actions[action_name] = {
            "type": "Compose",
            "inputs": {prop: expr for prop, expr in et["set_expressions"].items()}
            or {"_raw": "@body('Parse_body')"},
            "runAfter": {prev_action: ["Succeeded"]},
            "description": f"Apply {et['mapping_file']} field mappings",
        }

        actions[write_name] = {
            "type": "Http",
            "inputs": {
                "method": "POST",
                "uri": f"@{{parameters('silverApiUrl')}}/{domain}/{camel_to_snake(entity)}",
                "headers": {
                    "Content-Type": "application/json",
                    "Authorization": "@{concat('Bearer ', parameters('silverApiKey'))}",
                },
                "body": f"@outputs('{action_name}')",
            },
            "runAfter": {action_name: ["Succeeded"]},
        }

        prev_action = write_name

    workflow = {
        "definition": {
            "$schema": "https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#",
            "contentVersion": "1.0.0.0",
            "parameters": {
                "silverApiUrl": {
                    "type": "string",
                    "defaultValue": "https://<your-silver-api>.azurewebsites.net/api",
                    "metadata": {"description": f"Base URL of the silver layer API for {domain}"},
                },
                "silverApiKey": {
                    "type": "securestring",
                    "defaultValue": "",
                    "metadata": {"description": "Bearer token for silver API authentication"},
                },
            },
            "triggers": {
                f"When_{system}_data_received": {
                    "type": "Request",
                    "kind": "Http",
                    "inputs": {
                        "schema": {
                            "type": "object",
                            "properties": {},
                        }
                    },
                }
            },
            "actions": actions,
            "outputs": {},
        },
        "kind": "Stateful",
    }

    return json.dumps(workflow, indent=2)


def _col_expression(cm: dict) -> str:
    """Build a Logic Apps expression for a column mapping."""
    col = cm.get("source_column", "")
    transform = cm.get("transform", "")
    base = f"body('Parse_body')?['{col}']"

    if not transform:
        return base
    t = transform.strip().upper()
    if t.startswith("TRIM("):
        return f"trim({base})"
    if t.startswith("UPPER("):
        return f"toUpper({base})"
    if t.startswith("LOWER("):
        return f"toLower({base})"
    return base


def _generate_connections(domain: str) -> str:
    return json.dumps(
        {
            "managedApiConnections": {},
            "serviceProviderConnections": {
                "serviceBus": {
                    "parameterValues": {
                        "connectionString": "@appsetting('ServiceBus_ConnectionString')"
                    },
                    "serviceProvider": {"id": "/serviceProviders/serviceBus"},
                    "displayName": f"{domain}-servicebus",
                },
                "sql": {
                    "parameterValues": {
                        "server": "@appsetting('SqlServer_Server')",
                        "database": "@appsetting('SqlServer_Database')",
                        "username": "@appsetting('SqlServer_Username')",
                        "password": "@appsetting('SqlServer_Password')",
                    },
                    "serviceProvider": {"id": "/serviceProviders/sql"},
                    "displayName": f"{domain}-sql",
                },
            },
        },
        indent=2,
    )


def _generate_host() -> str:
    return json.dumps(
        {
            "version": "2.0",
            "extensionBundle": {
                "id": "Microsoft.Azure.Functions.ExtensionBundle.Workflows",
                "version": "[1.*, 2.0.0)",
            },
            "extensions": {
                "workflow": {"settings": {"Runtime.FlowRetentionDays": "90"}}
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
                "FUNCTIONS_WORKER_RUNTIME": "node",
                "APP_KIND": "workflowApp",
                "ProjectDirectoryPath": domain,
                "ServiceBus_ConnectionString": "<your-service-bus-connection-string>",
                "SqlServer_Server": "<your-sql-server>.database.windows.net",
                "SqlServer_Database": "<your-database>",
                "SqlServer_Username": "<username>",
                "SqlServer_Password": "<password>",
            },
        },
        indent=2,
    )


def _generate_readme(domain: str, systems: dict[str, list[dict]]) -> str:
    systems_text = "\n".join(f"- `{s}`" for s in sorted(systems)) or "- (none)"
    entity_rows = []
    for system, mappings in sorted(systems.items()):
        for m in mappings:
            entity = m.get("metadata", {}).get("entity", "Entity")
            entity_rows.append(f"- `{system}` -> `{entity}`")
    entities_text = "\n".join(entity_rows) or "- (none)"

    return f"""# Logic Apps Integration Artifacts - {domain}

Auto-generated by kairos-ontology-toolkit.

## Included source systems

{systems_text}

## Mapped entities

{entities_text}

## Structure

- `<system>/workflow.json`: Logic Apps Standard workflow per source system
- `connections.json`: Service provider connections
- `host.json`, `local.settings.json`
- `mappings/`: Integration mapping JSON files

## Local dry run

1. Configure `local.settings.json` placeholders.
2. Start Logic Apps Standard host from this directory:
   `func start`
3. POST sample payload to the generated HTTP trigger endpoint and verify silver write action output.

## Notes

- `workflow.json` files are stateful by default.
- Mapping files are shared with other integration projectors.
"""
