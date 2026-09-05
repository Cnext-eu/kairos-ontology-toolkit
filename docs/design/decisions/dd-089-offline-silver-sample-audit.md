# DD-089: Offline silver sample audit

**Status:** Accepted
**Date:** 2026-06-22
**Affects:** `src/kairos_ontology/silver_sample_audit.py`, `cli/main.py`,
dbt/silver projection QA, design and packaging skills
**Implementation:** `kairos-ontology audit-silver-samples`

### Context

Generated dbt silver models can be parsed offline, but parse/compile does not
prove that mappings and transforms preserve source semantics. Full validation
against actual bronze data belongs in the downstream dataplatform, but waiting
until then delays feedback on obvious mapping risks such as missing samples,
incompatible casts, cross-source format mismatches, or SQL artifacts that do not
trace back to mapped properties.

### Decision

Introduce an offline advisory **silver sample audit**. The command reads source
vocabulary samples, SKOS mappings, and generated dbt SQL from the ontology hub.
It emits structured YAML and Markdown findings without requiring dbt profiles,
warehouse credentials, network access, or real bronze tables.

The audit is non-blocking by default. It may be made blocking in CI with
`--fail-on warning|error`, but its findings remain advisory because source
samples are not equivalent to full production data.

### Rationale

This creates a low-cost pre-handoff QA layer. It improves hub-side feedback while
preserving the dataplatform as the authority for executed dbt runs, data tests,
row counts, referential integrity, and production distributions.

### Consequences

- Projection users can run `kairos-ontology audit-silver-samples` after dbt
  projection and before releasing/consuming the package.
- Findings are scoped to available sample values and generated artifacts.
- Dataplatform validation remains required for actual bronze data correctness and
  SQL engine behavior.

### Amendment (2026-08-12): v5 EntityBindings as a second mapping source (issue #348)

The audit was written against the v4 RDF-authored `model/mappings/` SKOS surface only. It
never read `integration/bindings/*.binding.yaml` (v5 EntityBindings, DD-133), so on a v5-only
hub it found zero mapped columns and — because `sample_coverage_ratio` special-cased a
zero denominator to `1.0` — printed an unqualified `✅ ... (100% coverage)` for a hub it had
not looked at.

`run_silver_sample_audit` now takes an optional `bindings_dir`/`hub_root` and resolves v5
mappings via the compiler's own `resolve_scope` + `adapt_binding` (`core/compiler/kernel.py`,
`core/compiler/adapter.py`) — the exact functions that turn one `EntityBinding` into
column-level `ColumnMappingFact`s for compilation — rather than re-deriving source-relation or
expression resolution. The resulting facts are folded into the same `mapping_context()` facade
(`core/projections/dbt/mapping_bind.py`) the v4 path already produces, so the rest of the
audit (sample-shape, cross-source, and SQL-lineage checks) is unchanged. `ResolvedRelation`
resolves a binding's source column to a synthesized `{table_uri}/{name}` symbol rather than the
real bronze `SourceColumn` URI, so the join back to persisted samples matches on the real
`(table_uri, column_name)` pair instead of URI equality. A physical column mapped on both
surfaces at once (mid v4-to-v5 migration) is counted once, not twice.

`sample_coverage_ratio` now returns `None`, not `1.0`, when `mapped_columns == 0`; the CLI
prints an explicit `⚠ ... nothing was audited` line naming both authoring surfaces searched
instead of a `✅` success line, and adds a `no_mapping_surface_found` warning finding so
`--fail-on warning` (the recommended CI setting) treats an inert audit as a failure — the same
"a command that checked nothing must not emit the success string of a command that checked
something" rule raised by #309 and #332.

### Amendment (2026-08-20): contracted virtual outputs are not physical Bronze columns (#581)

An EntityBinding selecting `source.dbtModel` maps the model contract's virtual output columns.
Those symbols are intentionally absent from the physical Bronze source vocabularies, so treating
their absence as `missing_source_column` was a category error. The audit now retains contracted
output metadata while adapting each binding and emits `contracted_output_not_evaluated` at info
severity when no persisted sample exists for that virtual output. Evidence names only the model,
SQL/contract paths, output column, contributing source-system identifiers, and whether transitive
`source()`/`ref()` lineage was fully traceable; it never includes SQL text or sample values.
Arbitrary SQL still is not executed offline, and real missing physical columns remain errors.
