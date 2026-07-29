# V5 Demonstration Guide

## Objective

Show how canonical ontology/source TTL and one closed EntityBinding produce one explainable,
deterministic `CompilePlan`, then demonstrate downstream consumption. Use only synthetic,
PII-free source metadata and values.

## Suggested 45-minute flow

| Time | Segment | Outcome |
|---|---|---|
| 0–10 | Explain the clean-break contract | One source of execution authority |
| 10–20 | Review ontology, source vocabulary, and binding | Traceable authored inputs |
| 20–30 | Run check, explain, and emit | Stateless deterministic compilation |
| 30–40 | Inspect dbt and optional Gold/MDM artifacts | Same-plan consumers |
| 40–45 | Show downstream pin/build workflow | Clear producer/consumer ownership |

## Live commands

```bash
uv run kairos-ontology compile customer --check
uv run kairos-ontology compile customer --explain --format json
uv run kairos-ontology compile customer --emit
```

Point out that check/explain are write-free, emit is manifest-owned and atomic, and compile
success is not deployment or release publication.

## Inputs to show

```text
model/ontologies/customer.ttl
integration/sources/sample-crm/sample-crm.vocabulary.ttl
integration/bindings/sample-crm-customer.binding.yaml
integration/transforms/dbt/models/     # optional ordinary SQL/YAML
model/extensions/                      # optional Gold/MDM policy only
```

Do not present claims, preparation, SKOS mapping, Silver-extension, lifecycle/readiness, or
release-evidence files as current authority.

## Downstream step

Show an immutable artifact/revision pin, then:

```bash
dbt deps
dbt parse
dbt build
dbt test
```

Generated files are never hand-edited. Compiler diagnostics return to the hub owner;
connection, runtime, deployment, and data-test failures remain with the dataplatform owner.
