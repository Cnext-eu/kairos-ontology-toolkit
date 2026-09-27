### Fixed
- **`fit-report` counts an object property a binding realizes through `relationships:`.**
  It read only a binding's `fields:`, and an object property can never be there
  (`binding.object-property-in-fields`). So every relationship a binding realized was still
  reported unpopulated. A hub that bound a value object in its own binding and linked it,
  as the compiler advises, saw no change in the report. Such a property is now listed as
  populated, with a source like `relationship -> party:Address on address_id`. In text
  output, the unpopulated count splits datatype from object properties. Each unpopulated
  object property is marked with how to reach it: bind the range class and add a
  `relationships:` entry.
