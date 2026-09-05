# Bind a source to an entity

**Skill:** `kairos-design-mapping`

One `integration/bindings/*.binding.yaml` maps **one** source relation (or one contracted
dbt model) to **one** canonical entity. It is the sole source-to-canonical execution
authority: it contains no raw SQL, and it does not replace the ontology or the source
vocabulary.

## 1. See what the data can actually populate

```bash
kairos-ontology fit-report --class Invoice --domain billing --source crm
kairos-ontology inverse-scan --class Invoice --domain billing
```

`fit-report` shows which properties of a class this source can fill. `inverse-scan` goes
the other way: which source tables look like candidates for a class. Doing this first
avoids authoring a binding that turns out to be mostly unmapped.

## 2. Scaffold a first draft

```bash
kairos-ontology scaffold-binding --system crm --table invoices \
  --target-class Invoice --domain billing
```

`--list-unscaffolded` shows relations with no binding yet. `--archetype` starts from a
known shape and `--list-archetypes` shows what is available. `--dry-run` prints instead of
writing.

## 3. Iterate against the compiler

```bash
kairos-ontology compile billing --check
kairos-ontology compile billing --explain --format json
```

`--check` validates and writes nothing; `--explain` shows the normalised plan the compiler
derived. Run both while authoring. The binding schema is *closed* — unknown fields,
unresolved source columns and unresolved ontology terms are all rejected — so most
mistakes surface here rather than downstream.

## 4. Check nothing was silently left behind

```bash
kairos-ontology audit-column-coverage
kairos-ontology alignment-report
```

`audit-column-coverage` is advisory: it lists source columns carrying real data that no
binding references. `alignment-report` gives a reason per unmapped column.

## If the logic does not fit

A binding cannot express joins, deduplication, or a change of grain. That is a boundary,
not a limitation to work around in YAML. See
[Write a contracted dbt model](write-a-contracted-dbt-model.md).

## Next

[Compile and emit](compile-and-emit.md), or
[add a second source to a class](add-a-second-source-to-a-class.md).
