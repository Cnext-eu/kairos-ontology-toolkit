### Fixed
- **The generated Gold `dim_date` now builds on `fabric-warehouse` (#776).** Four constructs in
  one compiler-generated file, none of them portable, and the first failure hid the rest.
  `dbt_utils.date_spine` expands with a trailing `ORDER BY`; dbt-fabric's table materialization
  creates a view as an intermediate step and T-SQL rejects `ORDER BY` in a view without `TOP`, so
  the model failed even though it declares `materialized='table'`. Behind it: `EXTRACT` is not a
  T-SQL function, and `is_holiday` was rendered as `boolean` -- a type Fabric does not have --
  while the DDL for the very same table already said `BIT`. A fourth defect had not been reached
  yet: `cast(<date> as varchar)` uses style 0 on T-SQL and yields `Sep 09 2026`, so the
  `replace(..., '-', '')` that built `date_key` removed nothing and the outer cast to `bigint`
  failed; on Databricks the same expression is invalid because `varchar` needs a length, so
  `date_key` was broken on both adapters. The calendar model is now rendered per adapter, the
  same way the Gold DDL renderer beside it already was. `dim_date` is the product calendar, so a
  hub lost year-on-year, week and prior-period comparison everywhere until it built.
