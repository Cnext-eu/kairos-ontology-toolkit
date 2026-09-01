---
name: kairos-develop-dataplatform
description: Introspect a dbt source and return reviewed source metadata to a v5 hub.
---

# Develop Dataplatform Sources

Use the `kairos-ontology extract-schema` CLI command. It connects with the dbt profile's
own credentials and produces real row counts, sample values, and JSON structure detection
in one pass — richer than the scaffolded `extract_source_schema` dbt macro, which is kept
only as a zero-dependency fallback for environments that can't install `pyodbc`.

**Sample values are written as-is unless you pass `--redact-pii` (DD-214).** Redaction used
to be unconditional; it is now opt-in, because the detector's false positives destroyed the
sample evidence downstream binding design reads. Pass `--redact-pii` for a source known to
carry personal data. `--emit-seed` requires it, because seed CSVs are committed and packaged
into releases.

1. Configure `_sources.yml` and a local dbt profile without committing credentials.
2. Run:

   ```bash
   # add --redact-pii if this source carries personal data
   kairos-ontology extract-schema \
     --profile <profile_name> --target dev \
     --schema <schema_name> --system sample_system \
     --profiles-dir .dbt
   ```

   If `pyodbc` isn't available, fall back to the scaffolded macro instead:

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
