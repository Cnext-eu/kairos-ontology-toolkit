# DD-217: Gold projection is controllable at the column

**Status:** Accepted
**Date:** 2026-09-04
**Affects:** `scaffold/kairos-ext.ttl` (new `kairos-ext:goldExcludeColumn`),
`core/projections/dbt/policy_specs.py`, `core/projections/dbt/policy_bind.py`,
`core/projections/dbt/policy_normalize.py`, `core/projections/dbt/gold_shape.py`, new
`tests/test_gold_column_exclusion.py`
**Issue:** #703

### Context

A Gold dimension mirrored its Silver model's column set unconditionally: `gold_shape._columns`
iterated `model.columns` with no predicate, and the only existing controls — `goldInclude` /
`goldIncludeImports` — claim imported *classes* for projection, not columns.

So directly identifying personal data that reaches Silver for legitimate operational use also
reached Gold and the Power BI semantic model, with no authorable way to stop it. On the reporting
hub that was `contact_name`/`contact_email`/`contact_phone` in `party_contact`, and
`contact_email`/`contact_phone` again in `acme_party`, ending up in a `gold_party` DDL.

Every available workaround was worse than a column filter: unbinding the fields removes them from
Silver too and breaks operational consumers that legitimately need them; dropping the dimension
loses `contact_reference`, `contact_role` and `job_title` with it and does nothing for the other
table; and `kairos-ext:securityPolicy` does work but demands a complete fail-closed policy with
roles, entitlement source, identity mapping, positive and negative tests and imported test
evidence before anything emits — which is the right tool for role-based hiding, not for "this
column should never leave Silver".

### Decision

One authored annotation, `kairos-ext:goldExcludeColumn "Table.column"`, repeatable on the
`owl:Ontology` resource, read into `GoldProductFact` → `GoldProductSpec` and applied in
`_columns`. Table matching folds case, mirroring `_table_aliases`.

**Fail-closed**, mirroring `security.missing-column-binding`: a value that excluded nothing is
rejected as `gold.unknown-excluded-column`. The whole value of the term is that a column stays
out, so a stale entry after a Silver rename, or a typo, must not read as "successfully excluded"
while the column is emitted again. Validation needs a matched-set collected during shaping rather
than an inspection of the emitted tables, because a correctly excluded column is absent from those
for exactly the same reason a misspelt one is.

**Deliberately not driven by the GDPR scan**, which the issue offers as an alternative. That scan
lives in `core/validator.py`, parses its own graph from raw Turtle, is imported by no compiler or
Gold module, and its result is not threaded onto `CompilePlan` — so honouring it here would mean
making the compiler depend on the validator. Keeping exclusion authored also keeps it reviewable
in the same place as the rest of the Gold product, and does not silently change what an existing
hub emits.

### Consequences

PII can be kept out of a Gold product without unbinding it from Silver, dropping a dimension, or
standing up a full security policy. A hub that authors nothing is unaffected: the filter is inert
until a value is present, and `tests/test_gold_column_exclusion.py` pins that.

This is a projection boundary, not access control. A column excluded here is absent from the Gold
model entirely, so there is nothing for a role to be granted later — that remains
`kairos-ext:securityPolicy`'s job, and the vocabulary comment says so.
