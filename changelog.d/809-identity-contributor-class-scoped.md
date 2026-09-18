### Fixed
- **Two EntityBindings may bind one `source.relation` to different canonical classes
  (issue #809).** The documented "one source table, several canonical entities" pattern
  failed `compile --check`: `_normalize_identities` kept its relation-to-identity-ref
  lookup keyed on the physical `table_uri` alone, so when two bindings shared a relation
  whichever was processed last silently overwrote the other's entry, and one class was
  then attributed the other's identity contributor. It surfaced as
  `safety.type-incompatible` / `identity.source-contributor-mismatch` pointing at a
  binding that was in fact correct, and the only workaround was a contracted dbt
  passthrough model per class — pure ceremony with no transformation in it — purely to
  mint distinct `virtual_source_iri` values. The lookup is now keyed by
  `(class, relation)`, matching the neighbouring `available_columns` map.
