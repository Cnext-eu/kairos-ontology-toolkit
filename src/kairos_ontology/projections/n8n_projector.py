# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""n8n projector — generates importable n8n workflow JSON from integration mappings.

Produces n8n workflow definitions that use webhook triggers → mapping transforms
→ database writes, consuming the same integration mapping JSON as the Dapr projector.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .uri_utils import camel_to_snake

logger = logging.getLogger(__name__)


def generate_n8n_artifacts(
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
    """Generate n8n workflow JSON artifacts.

    Generates the integration mapping JSON (Layer 1) and wraps it with
    n8n workflow definitions: webhook trigger → set node (transform) →
    database write node.

    Returns:
        Dictionary of {file_path: content} for all generated artifacts.
    """
    from .integration_projector import generate_integration_artifacts

    domain = ontology_name or "domain"
    artifacts: dict[str, str] = {}

    # Generate Layer 1 mappings first
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

    # Copy mapping files
    for file_key, content in mapping_artifacts.items():
        if file_key.endswith("-mapping.json") or file_key.endswith("manifest.json"):
            n8n_key = f"{domain}/mappings/{Path(file_key).name}"
            artifacts[n8n_key] = content

    # Parse mapping files to build workflows
    workflow_entries = []
    for file_key, content in mapping_artifacts.items():
        if not file_key.endswith("-mapping.json"):
            continue
        try:
            mapping = json.loads(content)
            workflow_entries.append(mapping)
        except (json.JSONDecodeError, KeyError):
            pass

    # Generate one workflow per source system
    systems: dict[str, list[dict]] = {}
    for entry in workflow_entries:
        system = entry.get("source", {}).get("system", "source")
        systems.setdefault(system, []).append(entry)

    for system, system_mappings in systems.items():
        workflow = _build_n8n_workflow(domain, system, system_mappings)
        artifacts[f"{domain}/workflows/{system}-workflow.json"] = json.dumps(
            workflow, indent=2, ensure_ascii=False
        )

    # Generate README
    artifacts[f"{domain}/README.md"] = _generate_readme(domain, systems)

    return artifacts


def _build_n8n_workflow(
    domain: str, system: str, mappings: list[dict],
) -> dict[str, Any]:
    """Build an n8n workflow definition for a source system."""
    nodes = []
    connections: dict[str, Any] = {}
    x_pos = 250
    y_start = 300

    # Webhook trigger node
    webhook_node = {
        "parameters": {
            "httpMethod": "POST",
            "path": f"{domain}/{system}",
            "responseMode": "responseNode",
        },
        "id": _node_id(0),
        "name": f"{system} Webhook",
        "type": "n8n-nodes-base.webhook",
        "typeVersion": 1,
        "position": [x_pos, y_start],
    }
    nodes.append(webhook_node)

    # Function node to route by entity
    x_pos += 250
    router_node = {
        "parameters": {
            "functionCode": _router_code(mappings),
        },
        "id": _node_id(1),
        "name": "Route by Entity",
        "type": "n8n-nodes-base.function",
        "typeVersion": 1,
        "position": [x_pos, y_start],
    }
    nodes.append(router_node)
    connections[f"{system} Webhook"] = {
        "main": [[{"node": "Route by Entity", "type": "main", "index": 0}]]
    }

    # Per-entity: Set node (transform) → Postgres node (write)
    x_pos += 250
    entity_y = y_start - (len(mappings) - 1) * 100
    prev_outputs = []

    for i, mapping in enumerate(mappings):
        entity = mapping.get("metadata", {}).get("entity", f"Entity{i}")
        snake = camel_to_snake(entity)
        y = entity_y + i * 200

        # Set node — applies column mappings
        set_node_name = f"Map {entity}"
        set_node = {
            "parameters": {
                "values": {
                    "string": _mapping_set_values(mapping),
                },
                "options": {},
            },
            "id": _node_id(2 + i * 2),
            "name": set_node_name,
            "type": "n8n-nodes-base.set",
            "typeVersion": 1,
            "position": [x_pos, y],
        }
        nodes.append(set_node)
        prev_outputs.append(
            {"node": set_node_name, "type": "main", "index": 0}
        )

        # Postgres write node
        silver_table = mapping.get("target", {}).get(
            "silver_table", f"silver_{domain}.{snake}"
        )
        write_node_name = f"Write {entity}"
        write_node = {
            "parameters": {
                "operation": "insert",
                "table": silver_table,
                "columns": ", ".join(
                    cm["target_property"]
                    for cm in mapping.get("column_mappings", [])
                ),
            },
            "id": _node_id(3 + i * 2),
            "name": write_node_name,
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 1,
            "position": [x_pos + 250, y],
            "credentials": {
                "postgres": {"id": "1", "name": "Silver Warehouse"},
            },
        }
        nodes.append(write_node)
        connections[set_node_name] = {
            "main": [[{"node": write_node_name, "type": "main", "index": 0}]]
        }

    # Router → all Set nodes
    connections["Route by Entity"] = {"main": [prev_outputs]}

    # Response node
    resp_node = {
        "parameters": {
            "respondWith": "json",
            "responseBody": '{"status": "processed"}',
        },
        "id": _node_id(100),
        "name": "Response",
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1,
        "position": [x_pos + 500, y_start],
    }
    nodes.append(resp_node)

    return {
        "name": f"{domain} — {system} Integration",
        "nodes": nodes,
        "connections": connections,
        "active": False,
        "settings": {},
        "tags": [
            {"name": domain},
            {"name": "kairos-integration"},
        ],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node_id(index: int) -> str:
    """Generate a stable node ID."""
    return f"node-{index:04d}"


def _router_code(mappings: list[dict]) -> str:
    """Generate JS code for the entity router function node."""
    cases = []
    for m in mappings:
        entity = m.get("metadata", {}).get("entity", "Entity")
        src_table = m.get("source", {}).get("table", "")
        cases.append(f"  // {src_table} → {entity}")

    cases_str = "\n".join(cases)
    return f"""// Route incoming records to the correct entity transformation.
// Entity mappings:
{cases_str}
//
// Routing logic: inspect record keys or add a header/field for entity type.
return items;
"""


def _mapping_set_values(mapping: dict) -> list[dict[str, str]]:
    """Build n8n Set node values from column mappings."""
    values = []
    for cm in mapping.get("column_mappings", []):
        source = cm["source_column"]
        target = cm["target_property"]
        transform = cm.get("transform")

        if transform:
            expression = f'={{{{$json["{source}"]}}}}'
        else:
            expression = f'={{{{$json["{source}"]}}}}'

        values.append({
            "name": target,
            "value": expression,
        })
    return values


def _generate_readme(domain: str, systems: dict) -> str:
    """Generate a README for the n8n output."""
    workflows = []
    for system, mappings in systems.items():
        entities = [m.get("metadata", {}).get("entity", "?") for m in mappings]
        workflows.append(
            f"- **{system}**: {', '.join(entities)} "
            f"→ `workflows/{system}-workflow.json`"
        )

    workflows_str = "\n".join(workflows)
    return f"""# n8n Integration Workflows — {domain}

Auto-generated by kairos-ontology-toolkit.

## Workflows

{workflows_str}

## Import

1. Open your n8n instance
2. Go to **Workflows** → **Import from File**
3. Select the `workflows/*.json` files

## Configuration

After import, configure:
- **Webhook paths** — adjust base URL if needed
- **Database credentials** — point `Silver Warehouse` to your silver layer
- **Activation** — toggle workflows to active when ready

## Mapping Files

The `mappings/` directory contains the integration mapping JSON files.
These define column-level transformations and are referenced by the workflows.
"""
