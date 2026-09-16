# DD-227: The "one" side of a relationship needs a declared unique key

**Status:** Accepted
**Date:** 2026-09-16
**Affects:** `core/projections/dbt/gold_shape.py` (new `_has_unique_key_evidence`,
`_shape_relationships`, `_resolve_ambiguous_paths`), `core/projections/dbt/gold_specs.py`
(`GoldRelationshipSpec.inactive_reason`), `core/projections/dbt/gold_render.py`
(`gold_product_report`), `tests/test_gold_relationship_activation.py`
**Issue:** #794. **Builds on DD-226.**

### Context

Analysis Services requires the "one" side of a many-to-one relationship to be unique, and
enforces it **when it builds the relationship index** — not at validation. So a model with
a non-unique key publishes successfully, refreshes green, answers any measure that stays on
one table, and fails on the first query whose plan traverses the relationship:

```
Column <key> in Table <fact> contains a duplicate value <value> and this is not allowed
for columns on the one side of a many-to-one relationship.
```

Nothing offline caught it. `package-powerbi-release` reported OK, TOM validation reported
no failures, and the model published and refreshed. It can look entirely healthy and still
be broken.

`_shape_relationships` checked only `if not target.primary_key` — that a key exists, never
that it is unique. And `_primary_key` does not consult a declared key at all: it walks a
role priority list (`surrogate-join-key`, `integration-identity`, `business-natural-key`,
`source-identity`) and then falls back to *"first non-nullable column, else first column"*.

This is not hypothetical. The toolkit's own `invoice` fixture emitted:

```tmdl
relationship <guid>
	fromColumn: fact_invoice_line.invoice_sk
	toColumn: fact_invoice._source_system
```

`_source_system` is the source system's name — the same value on every row of a source.
`_table_tmdl` already refused to mark such a column `isKey`, with a comment explaining this
exact failure mode (DD-221). Nothing applied the same caution to the relationship endpoint.

### Decision

**A relationship endpoint needs a declared single-column `SilverKeySpec`** on the target's
Silver model — its `primary_key` or one of its `unique_keys`. Checked for *every* target,
not just facts: the defect is in `_primary_key`'s fallback, which is role-shaped, not
fact-shaped, so scoping the check to facts would leave the same hole on a dimension with no
role-priority column.

Two things deliberately do not count as evidence:

- a **composite** key, because `GoldTableSpec.primary_key` is a single `str` and cannot
  represent one, so a composite grain says nothing about this single-column endpoint;
- a **predicated** key — an SCD2 grain carrying `is_current = 1` is unique only among
  current rows — unless the emitted table applies the same filter, which it does only when
  `dimension_exposure` is current-only.

**Emitted inactive, not refused.** An unproven relationship is a modelling smell, not
necessarily an error, and failing closed would block hubs that publish today. Inactive keeps
the model loadable and every other query working, and `gold_product_report` names each one
with a `reason` so it is reviewable rather than silent.

**An unproven edge never claims a place in the spanning forest.** DD-226's union-find pass
now skips relationships already deactivated, so an unsound edge cannot displace a sound one
between the same pair of tables.

`GoldRelationshipSpec.inactive_reason` distinguishes the two causes: `ambiguous-path`
(DD-226) and `unproven-key` (here).

### Rationale

The evidence needed was already in hand. `_shape_relationships` receives
`silver_models: dict[str, SilverModelSpec]`, and `SilverModelSpec` has carried
`primary_key`, `unique_keys` and `grain` as typed `SilverKeySpec` values since DD-110.

`kairos-ext:factGrain` is deliberately *not* used: it is `rdfs:range xsd:string`, free text,
emitted only as a comment. The issue frames the check around the fact's declared grain, but
that declaration cannot be parsed and is not the evidence required.

One caution recorded from the field report: `DISTINCTCOUNT` on the offending column reported
no duplicates while a `SUMMARIZE`-based count over the same column found many. A DAX
uniqueness probe against a published model is not reliable verification — which is the
argument for checking the declared contract offline rather than probing afterwards.

### Consequences

- The `invoice` fixture's fact-to-fact relationship is now emitted inactive. That is the
  defect being fixed, not a regression: the relationship could never have answered a query.
- Deactivating it also removed an ambiguous path, so a two-role calendar on those tables now
  leaves *both* roles active — the two tables are in different components. Cycle is an
  over-approximation of ambiguity, and this is where that shows.
- A hub whose relationship targets all carry declared surrogate keys is unaffected.
- The check cannot see uniqueness that is true in the data but undeclared. That is the
  intended trade: the contract is the evidence, and a hub that wants the relationship active
  declares the key.
- Not addressed here: `_primary_key`'s fallback still *chooses* a poor key, and the dbt
  `unique` test and ERD `PK` marker are still emitted against it. Narrowing that choice
  would change emitted output for hubs that are merely unproven rather than wrong, so it
  belongs in its own change.
