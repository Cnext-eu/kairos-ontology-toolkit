---
name: kairos-execute-validate
description: Validate ontology syntax, SHACL, bindings, and canonical compile diagnostics.
---

# Execute Validation

Validation is read-only unless the user explicitly requests an output file.

1. Resolve hub, ontology, catalog, and optional SHACL scope.
2. Set `KAIROS_SKILL_CONTEXT=1` and run `kairos-ontology validate` with the requested
   syntax, SHACL, or consistency options. Report exact findings.
3. Parse each closed `integration/bindings/*.binding.yaml` against the packaged EntityBinding
   schema by running `kairos-ontology compile <domain> --check --format json`.
4. Preserve ordered, source-located compiler diagnostics without changing their severity.
5. Distinguish ontology validity, binding compilation, and runtime dbt/platform testing.
6. Route fixes to the owning source, ontology, mapping, Gold, or MDM skill.

Passing compile diagnostics do not parse the emitted dbt project. After all domains emit
into the unified `ontology-hub-publish/medallion/dbt`, offer the opt-in, hub-wide offline gate
`kairos-ontology validate-dbt --platform <fabric|databricks>` (runs once for the whole
project, not per domain). It performs offline `deps → parse → manifest → compile` against the
adapter matching the emitted platform; `dbt deps` still needs package/network availability, but
warehouse credentials are not required. This closes the loop between canonical compilation and a
parseable dbt project without running warehouse tests.

The canonical compiler is the authority for entity resolution, typed expressions, contracts,
relationships, adapters, and artifact planning. Do not edit Turtle without the ontology skill.
