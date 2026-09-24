### Changed (model change for hubs with an approved calendar)
- **`dim_date` is now keyed on `full_date`, so Power BI recognises it as a date table.** The
  semantic model put `isKey` on the Int64 `date_key` while every calendar role
  relationship joined `full_date`, so the table never counted as a date table (BPA
  `MODEL_SHOULD_HAVE_A_DATE_TABLE`). `isKey` now sits on the DateTime `full_date`. The
  warehouse is unchanged: the DDL, the ERD and the dbt tests still key on `date_key`. In
  Fabric this re-keys `dim_date`; republish the model after upgrading (DD-238).
- **Calendar columns render like every other table's.** Each now carries
  `summarizeBy: none`, so year and month numbers no longer default to Sum, and a
  deterministic lineageTag, so a calendar column is the same object across emits.
  `month_name` sorts by `month_number` instead of alphabetically. Hubs without an approved
  calendar are unaffected.
