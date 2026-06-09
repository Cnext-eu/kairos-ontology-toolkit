# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Dapr projector — generates Dapr components and app stubs from integration mappings.

Produces Dapr binding components (input/output), pub/sub, state store configs,
and a Python app skeleton that uses the integration mapping JSON files to
transform source data into silver-layer entities.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .uri_utils import camel_to_snake

logger = logging.getLogger(__name__)


def generate_dapr_artifacts(
    classes: list,
    graph,
    template_dir,
    namespace: str,
    ontology_name: str = None,
    ontology_metadata: dict = None,
    sources_dir: Path = None,
    mappings_dir: Path = None,
    silver_ext_path: Path = None,
    integration_ext_path: Path = None,
    **kwargs,
) -> dict[str, str]:
    """Generate Dapr component and app artifacts.

    Generates the integration mapping JSON (Layer 1) and then wraps it with
    Dapr-specific components and a Python app skeleton.

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
        integration_ext_path=integration_ext_path,
    )

    # Collect mapping files and extract source systems + entities
    systems: set[str] = set()
    entities: list[dict[str, str]] = []
    system_schedules: dict[str, str] = {}
    system_retry_policies: dict[str, str] = {}

    for file_key, content in mapping_artifacts.items():
        if file_key.endswith("-mapping.json"):
            # Copy mapping into dapr output under mappings/
            dapr_key = f"{domain}/mappings/{Path(file_key).name}"
            artifacts[dapr_key] = content

            try:
                mapping = json.loads(content)
                system = mapping.get("source", {}).get("system", "source")
                entity = mapping.get("metadata", {}).get("entity", "Entity")
                systems.add(system)
                entities.append({"system": system, "entity": entity})

                # Extract integration metadata for Dapr config
                int_meta = mapping.get("integration", {})
                schedule = int_meta.get("schedule")
                if schedule and system not in system_schedules:
                    system_schedules[system] = schedule
                retry = int_meta.get("retry_policy")
                if retry and system not in system_retry_policies:
                    system_retry_policies[system] = retry
            except (json.JSONDecodeError, KeyError):
                pass
        elif file_key.endswith("manifest.json"):
            artifacts[f"{domain}/mappings/manifest.json"] = content

    # Generate Dapr components
    for system in sorted(systems):
        schedule = system_schedules.get(system)
        artifacts[f"{domain}/components/binding-{system}.yaml"] = _input_binding(
            system, schedule=schedule,
        )
    artifacts[f"{domain}/components/binding-silver.yaml"] = _output_binding(domain)
    artifacts[f"{domain}/components/statestore.yaml"] = _state_store()
    artifacts[f"{domain}/components/pubsub.yaml"] = _pubsub()

    # Generate resiliency policy if retry annotations present
    if system_retry_policies:
        artifacts[f"{domain}/components/resiliency.yaml"] = _resiliency_policy(
            system_retry_policies
        )

    # Generate app
    artifacts[f"{domain}/app/app.py"] = _generate_app(domain, entities)
    artifacts[f"{domain}/app/mapper.py"] = _generate_mapper()
    artifacts[f"{domain}/app/requirements.txt"] = _generate_requirements()

    # Docker compose for local dev
    artifacts[f"{domain}/docker-compose.yaml"] = _generate_docker_compose(domain)

    return artifacts


# ---------------------------------------------------------------------------
# Dapr component generators
# ---------------------------------------------------------------------------


def _input_binding(system: str, schedule: str = None) -> str:
    sched = schedule or "@every 5m"
    return f"""apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: {system}
spec:
  type: bindings.cron
  version: v1
  metadata:
    - name: schedule
      value: "{sched}"
  # Replace with your actual binding type:
  # bindings.azure.cosmosdb, bindings.postgresql, bindings.azure.eventhubs, etc.
  # See: https://docs.dapr.io/reference/components-reference/supported-bindings/
"""


def _output_binding(domain: str) -> str:
    return f"""apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: silver-warehouse
spec:
  type: bindings.postgresql
  version: v1
  metadata:
    - name: connectionString
      secretKeyRef:
        name: silver-connection
        key: connectionString
  # Configure for your silver layer target:
  # bindings.azure.cosmosdb, bindings.postgresql, bindings.azure.storage.queues, etc.
  # Domain: {domain}
"""


def _state_store() -> str:
    return """apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: statestore
spec:
  type: state.redis
  version: v1
  metadata:
    - name: redisHost
      value: "localhost:6379"
    - name: redisPassword
      value: ""
  # Used for deduplication via natural keys.
  # Replace with your state store: state.azure.cosmosdb, state.postgresql, etc.
"""


def _pubsub() -> str:
    return """apiVersion: dapr.io/v1alpha1
kind: Component
metadata:
  name: entity-events
spec:
  type: pubsub.redis
  version: v1
  metadata:
    - name: redisHost
      value: "localhost:6379"
    - name: redisPassword
      value: ""
  # Replace with your pub/sub: pubsub.azure.servicebus.topics, pubsub.kafka, etc.
"""


def _resiliency_policy(retry_policies: dict[str, str]) -> str:
    """Generate a Dapr resiliency policy from kairos-int:retryPolicy annotations."""
    policies = []
    targets = []
    for system, policy_str in sorted(retry_policies.items()):
        # Parse structured string: maxRetries=3,backoff=exponential,initialDelay=1s
        parts = dict(
            p.split("=", 1)
            for p in policy_str.split(",")
            if "=" in p
        )
        max_retries = parts.get("maxRetries", "3")
        backoff = parts.get("backoff", "exponential")
        initial_delay = parts.get("initialDelay", "1s")
        policies.append(
            f"      {system}Retry:\n"
            f"        policy: constant\n"
            f"        duration: {initial_delay}\n"
            f"        maxRetries: {max_retries}"
        )
        targets.append(
            f"      {system}:\n"
            f"        retry: {system}Retry"
        )

    policies_block = "\n".join(policies)
    targets_block = "\n".join(targets)
    return f"""apiVersion: dapr.io/v1alpha1alpha1
kind: Resiliency
metadata:
  name: integration-resiliency
spec:
  policies:
    retries:
{policies_block}
  targets:
    components:
{targets_block}
"""


# ---------------------------------------------------------------------------
# App generators
# ---------------------------------------------------------------------------


def _generate_app(domain: str, entities: list[dict[str, str]]) -> str:
    """Generate the main Dapr app entry point."""
    handler_imports = []
    for e in entities:
        system = e["system"]
        entity = e["entity"]
        snake = camel_to_snake(entity)
        handler_imports.append(
            f"# Handler: {system} → {entity}\n"
            f"# Mapping: mappings/{system}-{snake}-mapping.json"
        )

    handlers_comment = "\n".join(handler_imports) if handler_imports else "# No mappings found"

    systems_list = sorted({e["system"] for e in entities})
    binding_handlers = []
    for system in systems_list:
        system_entities = [e for e in entities if e["system"] == system]
        entity_cases = []
        for e in system_entities:
            snake = camel_to_snake(e["entity"])
            entity_cases.append(
                f'        "{e["entity"]}": "mappings/{system}-{snake}-mapping.json",'
            )
        cases_str = "\n".join(entity_cases)
        binding_handlers.append(f"""
@app.binding('{system}')
def on_{system}_data(request):
    \"\"\"Handle incoming data from {system}.\"\"\"
    record = json.loads(request.text())
    # Determine entity from record context or route all through mapper
    entity_mappings = {{
{cases_str}
    }}
    for entity_name, mapping_file in entity_mappings.items():
        mapping = mapper.load_mapping(mapping_file)
        if mapper.matches_source(record, mapping):
            result = mapper.transform(record, mapping)
            # Write to silver via output binding
            dapr_client.invoke_binding('silver-warehouse', 'create', json.dumps(result))
            # Publish entity event
            dapr_client.publish_event('entity-events', entity_name, json.dumps(result))
            logger.info("Processed %s record for %s", entity_name, '{system}')
            break
""")

    handlers_str = "\n".join(binding_handlers)

    return f'''"""Dapr integration app for {domain} domain.

Auto-generated by kairos-ontology-toolkit. Customize as needed.

{handlers_comment}
"""

import json
import logging

from dapr.clients import DaprClient
from dapr.ext.grpc import App

import mapper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = App()
dapr_client = DaprClient()
{handlers_str}

if __name__ == '__main__':
    app.run(50051)
'''


def _generate_mapper() -> str:
    """Generate the generic mapper module."""
    return '''"""Generic mapping engine — reads integration mapping JSON at runtime.

Auto-generated by kairos-ontology-toolkit.
"""

import json
from pathlib import Path
from typing import Any


_cache: dict[str, dict] = {}


def load_mapping(mapping_path: str) -> dict:
    """Load and cache a mapping JSON file."""
    if mapping_path not in _cache:
        with open(Path(mapping_path), encoding="utf-8") as f:
            _cache[mapping_path] = json.load(f)
    return _cache[mapping_path]


def matches_source(record: dict, mapping: dict) -> bool:
    """Check if a record matches the source defined in the mapping."""
    # Simple check: if the record has keys matching mapped source columns
    mapped_cols = {cm["source_column"] for cm in mapping.get("column_mappings", [])}
    record_keys = set(record.keys())
    return bool(mapped_cols & record_keys)


def transform(record: dict, mapping: dict) -> dict[str, Any]:
    """Apply column→property mapping transforms to a source record.

    Returns a dict with target property names as keys.
    """
    result: dict[str, Any] = {}

    for cm in mapping.get("column_mappings", []):
        source_col = cm["source_column"]
        target_prop = cm["target_property"]

        if source_col in record:
            value = record[source_col]
            # Apply transform if specified
            transform_expr = cm.get("transform")
            if transform_expr:
                value = _apply_transform(value, transform_expr)
            result[target_prop] = value
        elif cm.get("default_value") is not None:
            result[target_prop] = cm["default_value"]

    # Add metadata
    result["_source_system"] = mapping.get("source", {}).get("system", "unknown")
    result["_source_table"] = mapping.get("source", {}).get("table", "unknown")
    result["_entity"] = mapping.get("metadata", {}).get("entity", "unknown")

    return result


def _apply_transform(value: Any, transform_expr: str) -> Any:
    """Apply a kairos-map:transform expression to a value.

    Supports common patterns:
    - TRIM({value})
    - UPPER({value})
    - CAST({value} AS <type>)
    - Custom expressions are passed through as-is
    """
    if not transform_expr or value is None:
        return value

    expr = transform_expr.strip()
    str_val = str(value)

    if expr.startswith("TRIM("):
        return str_val.strip()
    elif expr.startswith("UPPER("):
        return str_val.upper()
    elif expr.startswith("LOWER("):
        return str_val.lower()
    elif "TRIM(UPPER(" in expr:
        return str_val.strip().upper()

    # Default: return original value (transform is SQL-level, not runtime)
    return value
'''


def _generate_requirements() -> str:
    return """# Dapr integration app dependencies
dapr>=1.14.0
dapr-ext-grpc>=1.14.0
"""


def _generate_docker_compose(domain: str) -> str:
    return f"""# Local development: Dapr sidecar + app for {domain} domain
# Auto-generated by kairos-ontology-toolkit

version: "3.8"

services:
  {domain}-app:
    build:
      context: ./app
      dockerfile: Dockerfile
    ports:
      - "50051:50051"
    volumes:
      - ./mappings:/app/mappings:ro
    depends_on:
      - redis

  {domain}-dapr:
    image: "daprio/daprd:latest"
    command:
      - "./daprd"
      - "--app-id"
      - "{domain}-integration"
      - "--app-port"
      - "50051"
      - "--app-protocol"
      - "grpc"
      - "--resources-path"
      - "/components"
    volumes:
      - ./components:/components:ro
    network_mode: "service:{domain}-app"
    depends_on:
      - {domain}-app

  redis:
    image: "redis:7-alpine"
    ports:
      - "6379:6379"
"""
