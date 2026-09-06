# DD-221: Gold rendering defaults hide technical columns, mark keys, and carry descriptions

**Status:** Accepted
**Date:** 2026-09-05
**Affects:** `core/projections/dbt/gold_render.py` (`_table_tmdl`),
`core/projections/dbt/gold_shape.py` (`_is_hidden_by_role`, `_check_hidden_columns`),
`core/projections/dbt/gold_specs.py`, `core/projections/dbt/gold_materialize.py`,
`core/projections/dbt/policy_bind.py`, `core/projections/dbt/policy_normalize.py`,
`core/projections/dbt/policy_specs.py`, `scaffold/kairos-ext.ttl` (new
`kairos-ext:goldHideColumn`), new `tests/test_gold_rendering_defaults.py`
**Issue:** #744 (part 2)

### Context

The emitted TMDL handed a report author every column flat. A `dim_customer` opened in
Desktop with `customer_sk`, `country_sk`, `_source_identity_ref`, `_loaded_at` and
`_kairos_fk_7b0570479f48_match_count` sitting in the field list beside `customer_name` —
eight columns of which four are machinery. No column was marked as the table's key. And
the ontology's `rdfs:comment`, already carried all the way to
`GoldPhysicalColumnPlan.comment`, was dropped at the last step: only measures got a `///`
doc comment, so the best documentation the hub owns never reached the tooltip a report
author actually reads.

None of this was authored policy, so none of it was fixable in a hub. It is what the
projection emits by default, and the defaults were wrong.

### Decision

**Technical columns are hidden by Silver column role, not by name.** A column is hidden
when its role is `source-identity`, `surrogate-join-key`, `entity-iri`, `audit` or
`history`. Name matching was rejected: the SCD history flag is authorable and defaults to
`is_current` with no leading underscore, so a `_` prefix rule misses it, while a business
column may legitimately end in `_sk`.

**`foreign-key` is decided on provenance, not role.** The compiler gives that one role to
two different kinds of column on the same table: the DD-133 generated `{target}_sk` and
its DD-109 `_kairos_fk_*_match_count` sibling, which are machinery, and the DD-107 mapped
column the join reads from — `country_code` — which is business data a report author will
slice by. A mapped column carries a `property:` provenance tag and a generated one never
does, so provenance separates them exactly. A role-only rule would have hidden
`country_code`, and did, until an emit against the v5 fixture showed it.

`business`, `business-natural-key`, `integration-identity` and `mastered-identifier` stay
visible: those are the values a business user recognises.

**Hiding is presentation, not a boundary.** A hidden column is still in the model. It
carries its relationships, answers DAX, and can still be granted or denied by a security
role. That is what makes hiding safe as a default where excluding would not be.
`goldExcludeColumn` (DD-217) removes a column from the product; `goldHideColumn` only
keeps it out of the field list; `securityPolicy` remains the access-control tool. Three
terms, three jobs.

**`kairos-ext:goldHideColumn "Table.column"`** is the authored escape hatch for the
remaining case — a business-looking column this product does not want browsed. Repeatable
on the `owl:Ontology` resource, wired exactly like `goldExcludeColumn`, case-insensitive
on the table, and fail-closed as `gold.unknown-hidden-column`. Fail-closed for the same
reason as DD-217: a stale value after a Silver rename must not read as "successfully
hidden" while the column is back in the field list. Hiding a column that is already
excluded also fails, because two annotations fighting over one column is an authoring
mistake worth hearing about.

**`isKey` is emitted only where the key is provably unique**: a dimension or bridge whose
primary key column has role `surrogate-join-key`. `_primary_key` falls back to "first
non-nullable column, else first column" when a table has no surrogate, which on a fact can
land on a repeated value — and Power BI rejects a non-unique `isKey` at *refresh*, in the
workspace, not at validation time in CI. Trusting that fallback would move a failure from
a test run to a client's Fabric workspace.

**Column descriptions are emitted as `///`.** No new plumbing: the comment already reached
the physical plan.

### Consequences

Every existing hub's TMDL changes on the next emit. That is the point, and it is safe: the
TOM SDK validates the result, and hidden columns keep working. Paths, manifests and the
`.SemanticModel` layout are untouched.

Deliberately **not** in this decision, and left for their own: `rdfs:label` as the column
name (every authored DAX expression and `measureColumnDependency` references the
snake_case identifier today, so renaming is a dependency-resolution change, not a render
change), `sortByColumn`, `dataCategory`, hierarchies, and table-level descriptions
(`shape.py` overwrites the class comment with boilerplate, so there is nothing worth
emitting without extra plumbing).

The multi-domain Gold product from the same issue — product scope, cross-domain
relationships, the reversal of #661's stance — is a separate decision, recorded when it
ships.
