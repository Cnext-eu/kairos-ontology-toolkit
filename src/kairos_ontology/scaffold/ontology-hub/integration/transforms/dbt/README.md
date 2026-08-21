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
seeds/<name>.csv
seeds/<name>.yml                          # optional column docs
```

Name single-source intermediate models `int_<source>__<entity>` and multi-source
survivorship models `int_merged__<entity>`. Atomic per-source `stg_<source>__<entity>`
models may feed the final contracted `int_*` model referenced by `source.dbtModel`.

The model properties YAML is the physical output contract. Include every output column and
type plus the minimal `meta.kairos` target, grain, physical key, and adapter metadata. Use
`kairos-develop-dbt-transformation` for the SQL/YAML contract workflow.

## Seeds

Use `seeds/` for small, static, hand-maintained reference data that belongs in version
control rather than in a warehouse source — country codes, currency lists, status or code
mapping tables. Author it as a CSV; do not create a source vocabulary for it.

- The file **stem is the dbt resource name**. `seeds/country_codes.csv` is targeted by
  `{{ ref('country_codes') }}` from any authored model, exactly like a model is.
- The stem **must not collide with any model stem**, authored or generated. dbt resolves
  `ref()` in a single resource namespace, so two resources sharing one name make the
  generated project fail to parse; the compiler and the bundle both fail closed on it.
- The CSV must be **UTF-8** with a **non-empty header row**. A cp1252 export fails the
  compile as an unresolved dependency, not as a crash.
- `seeds/<name>.yml` (or `.yaml`) is an optional sibling holding column documentation and
  tests. It is dbt's plain `seeds:` properties form and **must not carry `meta.kairos`** —
  a seed is not a bindable virtual source, so it has no output contract to declare:

  ```yaml
  version: 2
  seeds:
    - name: country_codes
      description: ISO 3166-1 alpha-2 reference list.
      columns:
        - name: alpha_2
          description: Two-letter country code.
  ```

A seed reached by a selected model's `ref()` closure joins the compile plan as a leaf and is
emitted under `seeds/` in the generated project, with its sibling properties YAML alongside.
Seeds are never text-scanned for `ref()`/`source()` calls.

`update` does not backfill hub directories — only `init` and `new-repo` create them. An
existing hub must `mkdir integration/transforms/dbt/seeds` itself before authoring the first
seed. That is expected, not a bug.

After changing a contract:

1. Point an entity binding `source.dbtModel` directly at the SQL and YAML paths.
2. Run `kairos-ontology compile <domain> --check`.
3. Review the resulting `CompilePlan` with `compile --explain`.

After adding or renaming a seed:

1. Confirm the stem collides with no model stem, and that the CSV is UTF-8 with a header row.
2. Run `kairos-ontology validate-dbt-contracts` — it reports unmatched seed docs, unreadable
   seeds, and seed/model name collisions.
3. Run `kairos-ontology compile <domain> --check` for every domain whose closure `ref()`s it.

Do not place credentials, raw PII, proprietary sample values, or hard-coded physical
database/schema names in these files.
