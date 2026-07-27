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
type plus the minimal `meta.kairos` target, grain, physical key, and adapter metadata. Use
`kairos-develop-dbt-transformation` for the SQL/YAML contract workflow.

After changing a contract:

1. Point an entity binding `source.dbtModel` directly at the SQL and YAML paths.
2. Run `kairos-ontology compile <domain> --check`.
3. Confirm key/FK/SCD policy with `kairos-design-silver`.

Do not place credentials, raw PII, proprietary sample values, or hard-coded physical
database/schema names in these files.
