### Added
- **`kairos-ext:measureDisplayName` gives a measure the name report users see.** Measures
  were named by their `measureId` (e.g. `'invoice.total-amount'`) in the field list. The
  display name now names the measure in the model, while `measureId` stays the stable key
  and still seeds the lineageTag, so Fabric treats a rename as an edit. Without one the
  measure keeps its ID as its name, byte-identical. Another measure's DAX must reference it
  by the display name; a reference by ID fails with `gold.dax-measure-reference-by-id` and
  names the reference to write. Invalid or colliding names fail
  (`gold.measure-display-name-invalid`, `gold.measure-display-name-collision`).

### Fixed
- **Measures carry their `dataType`.** `measureDataType` was mandatory past `intent` but only
  reached the product report. It now renders in the TMDL (`currency` as decimal,
  `percentage` as double).
- **A multi-line `measureExpression` no longer breaks the model.** It was written inline and
  unescaped, so its second line was read as a property. It is now emitted as a TMDL
  triple-backtick block, which TOM deserializes and `harvest-gold` reads back unchanged.
- The scaffold's example measure and the acme scenario now show the best-practice form: a
  display name and table-qualified column references (DD-238).
