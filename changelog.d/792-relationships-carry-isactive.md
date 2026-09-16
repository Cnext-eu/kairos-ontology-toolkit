### Fixed
- **The emitted semantic model has one active filter path between any two tables (issue #792).**
  Power BI allows only one, and the projector emitted every relationship active — not one carried
  `isActive: false` — while routinely emitting several date roles on one fact and snowflake
  shortcuts alongside the multi-hop paths they duplicate. The model was unloadable in Fabric and
  in Desktop, and the service reports one offending pair per attempt, so on the product that
  surfaced this, finding all 21 ambiguities of 50 relationships would have cost 21 publish round
  trips. The projector now treats the relationships as an undirected graph and deactivates every
  edge beyond a spanning forest, in one offline pass, in a fixed priority order that never
  deactivates a business relationship in favour of a date role. A deactivated relationship stays
  in the model and is reachable from DAX with `USERELATIONSHIP`. A product with no ambiguity emits
  byte-identical output.
- **A measure can reference `dim_date`.** `_column_by_property` resolved column dependencies only
  against the product's tables, and the calendar is synthesized by the renderer rather than shaped
  as one — so `dim_date.full_date` was unresolvable and any measure declaring it failed with
  `measure.missing-column-dependency`. That is the dependency a `USERELATIONSHIP` measure needs,
  so without this the fix above would have deactivated relationships while making the only
  workaround uncompilable.

### Added
- **`kairos-ext:goldPrimaryRelationship` declares which path stays active.** Which date role is
  active is not cosmetic — time intelligence follows it, so it is the product's fiscal semantics.
  The projector picks deterministically rather than failing closed, so existing hubs keep
  publishing, and reports every deactivated relationship in the Gold product report under
  `deactivated_relationships` so a silent pick cannot change a report's meaning unreviewed.
  Author `"Table.column -> Table.column"` on the `owl:Ontology` resource to decide it yourself;
  repeatable, and fail-closed on a value naming no emitted relationship
  (`gold.unknown-primary-relationship`). See DD-226.

### Changed
- **Role-playing date relationships are shaped rather than invented during rendering.** They were
  built directly into `relationships.tmdl` by the renderer, so they never appeared in the shaped
  relationship set and nothing reasoning over the model could see them — which is why the
  ambiguity they cause went undetected. Their emitted names are unchanged: in Fabric a renamed
  relationship is a new object, not an edit.
