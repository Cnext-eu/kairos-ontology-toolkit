### Fixed
- **A many-to-many bridge now lets a filter on its far endpoint reach the fact.** Every
  relationship was emitted single-direction, so in Fact -> DimA <- Bridge -> DimB a slicer
  on DimB stopped at the bridge and the model returned wrong numbers for that path. The
  bridge's edge towards its fact-side endpoint (a fact, or the dimension a fact joins) is
  now emitted `crossFilteringBehavior: bothDirections`, with the BPA annotation recording
  that it was checked. When no single endpoint is on the fact side the projector does not
  guess: it leaves the bridge single-direction and lists it under
  `undecided_bridge_filters` in the product report. Numbers through a bridge path change,
  from wrong to right; models without bridges are byte-identical (DD-238).

### Added
- **`kairos-ext:goldRelationshipCrossFilter "Table.column -> Table.column = both|single"`**
  decides one relationship's filter direction, fail-closed on an edge the product does not
  emit. Bidirectional edges and why are listed under `bidirectional_relationships` in the
  product report.

### Notes
- Bridge edges keep TOM's many-to-one default. `bridgeCardinality` describes the relation
  between the two endpoints, not either edge, and rendering it onto an edge would declare the
  endpoint's unique key non-unique. `relyOnReferentialIntegrity` is deliberately not emitted
  on Databricks: a unique key does not prove every fact-side key resolves, and Silver leaves
  an unmatched key null, which an inner join would silently drop (DD-238).
