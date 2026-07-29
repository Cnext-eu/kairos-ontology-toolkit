---
name: kairos-develop-dataplatform
description: Introspect a dbt source and return reviewed source metadata to a v5 hub.
---

# Develop Dataplatform Sources

Use the scaffolded dbt macro; there is no `kairos-ontology extract-schema` command.

1. Configure `_sources.yml` and a local dbt profile without committing credentials.
2. Run:

   ```bash
   dbt run-operation extract_source_schema \
     --args '{source_name: "sample_system"}' \
     --profiles-dir .dbt
   ```

3. Save the emitted YAML under a reviewed local `extracted/` directory.
4. Redact personal/proprietary values and connection details.
5. From the ontology hub, invoke the source-design workflow and run the retained
   `kairos-ontology import-source --from <yaml> --system <name>` command.
6. Review the resulting source-vocabulary TTL and bind each selected relation with one closed
   EntityBinding.

The dataplatform owns connections and runtime dbt validation. The hub owns source vocabulary,
binding, and compiler diagnostics. Do not create a second evidence/readiness registry.
