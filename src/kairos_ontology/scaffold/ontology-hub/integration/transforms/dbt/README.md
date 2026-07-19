# Contracted dbt Transformations

Use this directory for advanced source-conformance logic that cannot be represented safely
as ordinary SKOS mapping expressions, such as joins, windows, rankings, aggregations,
fallback rules, JSON expansion, and grain changes.

Authoritative inputs follow the dbt project layout:

```text
models/intermediate/<area>/<model>.sql
models/intermediate/<area>/<model>.yml
macros/<area>/<hub-or-domain>__<macro>.sql
tests/<area>/assert_<model>_<behavior>.sql
```

The model properties YAML is the physical output contract. Include every output column and
type plus `meta.kairos` target, grain, physical key, adapter, dependency, and decision
metadata. Use `kairos-develop-dbt-transformation` for the interactive evidence and approval
workflow.

After changing a contract:

1. Run `kairos-ontology sync-dbt-contracts`.
2. Map the generated virtual source with `kairos-design-mapping`.
3. Confirm `silverSourceRef` and key/FK/SCD policy with `kairos-design-silver`.
4. Project and run `kairos-ontology validate-dbt`.

Do not place credentials, raw PII, proprietary sample values, or hard-coded physical
database/schema names in these files.
