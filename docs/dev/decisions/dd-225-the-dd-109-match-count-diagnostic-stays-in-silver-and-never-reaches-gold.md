# DD-225: The DD-109 match-count diagnostic stays in Silver and never reaches Gold

**Status:** Accepted
**Date:** 2026-09-16
**Affects:** `core/projections/dbt/gold_shape.py` (`_columns`, new
`_is_match_count_diagnostic`, new `_emitted_primary_key`),
`core/projections/dbt/normalize.py` (dead branch removed),
`tests/test_gold_rendering_defaults.py`, `tests/test_downstream_compile_consumers.py`,
`tests/test_gold_column_exclusion.py`
**Issue:** #793. **Supersedes DD-221 in part.**

### Context

DD-109 gives every temporal lookup a `_kairos_fk_<hash>_match_count` column recording how
many parent rows the lookup matched. DD-221 decided these were machinery and *hid* them
from the report author's field list, on the explicit principle that "hiding is
presentation, not a boundary" — a hidden column stays in the model, carries its
relationships and answers DAX.

That principle is sound, and it is exactly what broke. A hidden column still has to
**exist in the physical table**, and it did not.

There is one `CompilePlan` but two `GoldTableSpec` objects, shaped at different ages:

1. `shape.py` shapes `gold_product` inside `shape_project()`, before the diagnostics exist.
2. `kernel.py`'s `_project_relationship_match_counts` then appends them to
   `silver_models` and `replace()`s the shaped project — **without re-shaping
   `gold_product`**, which is now permanently stale.
3. `compile --emit` renders the Gold dbt models from that stale spec (`render.py`), so
   `models/gold/**.sql` never selected the columns.
4. `emit-gold` re-shapes from the augmented `silver_models`
   (`medallion_gold_projector.py`), so the TMDL, the Gold DDL and the ERD all declared
   them.

dbt builds the table. So the semantic model declared 45 columns across 20 tables that the
Delta table never had, and a Direct Lake refresh failed with a Delta protocol violation.
Neither offline gate could see it: `pbip_validate` never reads TMDL, and `tmdl_validate`
only proves the TMDL deserializes.

### Decision

**The diagnostic is excluded from the Gold projection, not hidden.** It is filtered in
`gold_shape._columns()` — the single function every Gold writer derives from — so the dbt
model, the DDL, the TMDL, the ERD and the schema YAML agree by construction rather than by
coincidence.

**Identified by the `rule:DD-109-temporal-fk` provenance tag, not by name and not by
role.** Two producers emit these columns with *different* provenance: the kernel tags
`relationship:<uri>` and the shaper tags `property:<uri>`. Only the rule tag is common to
both. Name matching would also work, but provenance is exact and follows DD-221's own
provenance-over-name principle.

**Explicitly not `_is_hidden_by_role`.** That predicate matches any `foreign-key` column
without a `property:` tag, which is deliberately *both* this diagnostic **and** the DD-133
generated `{target}_sk` surrogate — the column relationships join on. Filtering Gold on it
would strip every surrogate key and destroy the model.

**DD-221 is superseded only here.** Its rule that `foreign-key` is decided on provenance
rather than role stands unchanged, and still governs hiding the generated `{target}_sk`.
What changes is the disposition of this one column: excluded, not hidden.

**A table's primary key must be a column the product emits.** `_primary_key` read the raw
Silver model while `_columns` returns a filtered set, and nothing reconciled the two. That
was already a latent DD-217 hole — exclude a surrogate and the key names a column Gold does
not contain — and every consequence was silent: `_shape_relationships` points `toColumn` at
a missing column, while `isKey`, the dbt `unique` test and the ERD `PK` marker just stop
appearing. `_emitted_primary_key` now fails closed with `gold.primary-key-not-emitted`.

### Rationale

Silver is where a data-quality signal belongs and where it remains: the Silver models
select it, the Silver DDL declares it, and the Gold product report still records it under
`silver_authority.registry_columns`. Nothing is lost, and the Gold layer stops carrying a
column no report author could see, no measure referenced, and no physical table contained.

Excluding is also the only option that is robust to the underlying staleness. Making the
dbt models select the columns would have fixed the symptom while leaving two
differently-aged specs in place, so the next column injected after shaping would reopen the
same hole silently.

### Consequences

- The Gold Delta tables are narrower: on the reporting hub that surfaced this, 45 fewer
  columns across 20 tables.
- Every hub's Gold output changes bytes on the next emit — TMDL, Gold DDL, ERD and schema
  YAML lose the columns. `models/gold/**.sql` does **not** change, because it never had
  them, and that asymmetry is the signature of the bug.
- The structural cause — `shaped.gold_product` going stale in
  `_project_relationship_match_counts` — is **not** fixed here. It is now inert, because
  the only thing injected after shaping is the thing Gold ignores. A cross-path parity test
  (`test_the_two_gold_emit_paths_agree_on_every_table_column_set`) asserts the property
  directly, so a future post-shape injection fails loudly instead of shipping two
  disagreeing artifacts.
- A hub that authored `goldExcludeColumn` against its table's primary key now fails closed
  where it previously emitted a dangling relationship endpoint.
