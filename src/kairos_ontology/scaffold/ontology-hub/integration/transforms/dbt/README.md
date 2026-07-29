# Contracted dbt Transformations

Use this directory for relational logic that cannot be represented safely
by the closed EntityBinding scalar-expression grammar, such as joins, windows,
rankings, aggregations, fallback rules, JSON expansion, and grain changes.

Authoritative inputs follow the dbt project layout:

```text
models/intermediate/<area>/<model>.sql
models/intermediate/<area>/<model>.yml
macros/<area>/<hub-or-domain>__<macro>.sql
tests/<area>/assert_<model>_<behavior>.sql
```

Name single-source intermediate models `int_<source>__<entity>` and multi-source
survivorship models `int_merged__<entity>`. Atomic per-source `stg_<source>__<entity>`
models may feed the final contracted `int_*` model referenced by `source.dbtModel`.

The model properties YAML is the physical output contract. Include every output column and
type plus the minimal `meta.kairos` target, grain, physical key, and adapter metadata. Use
`kairos-develop-dbt-transformation` for the SQL/YAML contract workflow.

After changing a contract:

1. Point an entity binding `source.dbtModel` directly at the SQL and YAML paths.
2. Run `kairos-ontology compile <domain> --check`.
3. Review the resulting `CompilePlan` with `compile --explain`.

Do not place credentials, raw PII, proprietary sample values, or hard-coded physical
database/schema names in these files.
