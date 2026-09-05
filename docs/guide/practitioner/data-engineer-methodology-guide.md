# Data Engineer Methodology — Kairos v5

## Authority

Data engineering starts from five possible authored inputs:

1. canonical domain/reference ontology TTL;
2. authoritative source-vocabulary TTL;
3. one closed EntityBinding per source relation or contracted dbt model;
4. optional ordinary contracted dbt SQL/YAML for relational complexity; and
5. optional Gold/MDM policy TTL.

No authored preparation policy, SKOS mapping authority, Silver extension, lifecycle/readiness
state, or release-evidence registry participates in v5 compilation.

## Workflow

1. Import and review source metadata with `import-source` or `import-flatfile`. Persist
   only redacted or synthetic samples. Optionally capture Power BI/TMDL analysis with
   `import-tmdl` as **demand evidence** under `integration/discovery/bi/` — never a source.
2. Confirm ontology classes/properties and source relation/column types.
3. Create one EntityBinding for each source relation or contracted dbt model.
4. Put joins, windows, aggregation, JSON expansion, fallback rules, and grain changes in
   ordinary dbt SQL plus authoritative model YAML.
5. Select `fabric` or `databricks` in `kairos.yaml`.
6. Check and explain before emission:

   ```bash
   uv run kairos-ontology compile customer --check
   uv run kairos-ontology compile customer --explain --format json
   ```

7. Emit atomically:

   ```bash
   uv run kairos-ontology compile customer --emit
   ```

8. Pin emitted artifacts immutably downstream and run `dbt deps`, `dbt parse`,
   `dbt build`, and `dbt test`.

## Review checklist

- Binding grain, source identity, load mode, and relationships are explicit.
- Incremental/SCD policy is complete; no runtime behavior is inferred.
- Expressions use the closed deterministic grammar; raw SQL stays in ordinary dbt models.
- `compile --explain` shows the expected source, target, adapter, and planned paths.
- Generated files are unchanged on repeated equivalent emission.
- No credential, personal data, internal URL, or proprietary sample is committed.
- Compile success is not described as runtime validation, deployment, or release publication.

V5 provides no v4 compatibility or conversion workflow. Rebuild older hubs from the lean
scaffold and port only current canonical intent.
