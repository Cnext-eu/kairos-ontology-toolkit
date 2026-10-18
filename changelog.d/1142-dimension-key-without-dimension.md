### Added
- **Gold flags a fact key whose class is bound but has no dimension (#1142).** A foreign key
  whose target class a domain of the product binds in Silver, but which no Gold table
  carries, used to be listed with every other dead column under `unresolved_relationships`,
  and the advice there ("add the owning domain to the product") did not apply: the domain was
  already there. It is now the practice `semantic-model.dimension-key-without-dimension`
  (`gold.dimension-key-without-dimension`, a warning), reported by `compile --check` and
  `emit-gold`. Resolve it by adding the dimension with `kairos-ext:goldTableName`, removing
  the key with `kairos-ext:goldExcludeColumn`, or recording a `kairos-ext:practiceException`
  on the column. In a product without the target's domain, such an exception is deferred
  rather than reported unused, so a shared domain can carry it. The product report's
  `unresolved_relationships` is unchanged, and `emit-gold`'s unresolved-relationship warning
  now lists only keys whose owning domain is missing.

### Fixed
- **`goldExcludeColumn` can remove a foreign key whose target is not in the product (#1142).**
  It failed with `gold.relationship-column-not-emitted`, and `goldExcludeRelationship` needs
  a target table, so a dead key could not be removed at all.
