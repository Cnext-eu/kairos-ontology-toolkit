# Historical: virtual-source column IRI migration

> **V4 historical record.** The `migrate-column-iris` and `sync-dbt-contracts` commands
> described by the original document were retired by the DD-133 clean break. This page is
> retained only to explain old repository history; it is not an executable v5 procedure.

V4 synchronized dbt vocabularies used a `__` separator to make contract column IRIs valid
Turtle local names. Some older hubs used slash-delimited IRIs and had a one-shot migration.

V5 has no compatibility or migration path for those vocabularies. Rebuild the source
vocabulary and closed EntityBinding in a fresh v5 hub. Do not attempt to preserve v4 mapping
or virtual-source authority.
