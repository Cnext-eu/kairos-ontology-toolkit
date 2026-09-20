### Fixed
- **Hub-local extension properties reach the binding candidate pool again.**
  `hub_local_properties` read the property IRI from a `uri` key; `SemanticIndex` names it
  `property_uri`. The lookup therefore returned nothing at all, however correctly a hub
  had authored its properties — a 155-column table dropped from 74 mapped fields back to
  1, silently. Introduced when the function moved onto the DD-103 canonical loader, and
  invisible because every other test of the binding generator mocks it. Object properties
  are now excluded too: they need a relationship entry, not a scalar field.
