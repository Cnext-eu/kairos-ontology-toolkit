### Changed
- **`read_reference_terms` now carries each class's property names (issue #524).** The
  loader flattened classes and properties into one list and dropped the link between them,
  so any caller needing "which properties does this class carry" had to resolve the closure
  a second time. `build_class_catalog` did exactly that for #519's anchor tie-break, and
  `propose_alignment` independently built its own indices for #517/#520 — the same
  relationship derived three times from two loaders.

  It is carried on `ReferenceTerm.property_names` now, which is where the loader already
  knew it. The duplicate resolution in `anchor_tables` is gone.

### Performance
- **`build_class_catalog` is roughly 3× faster.** Measured on the committed reference-model
  fixture (1271 classes): **22.9s → 7.2s**.

### Notes
- The property sets are now **strictly more complete**: on that fixture, 0 classes lose a
  property and 71 gain one. The second pass resolved only the modules that contributed a
  class copy, while the loader resolves each module's full `owl:imports` closure (the
  canonical DD-103 path), so the old narrower set was an artifact of the workaround. More
  properties can only strengthen #519's overlap-based tie-break, never weaken it — but it
  is a behaviour change, recorded here rather than left to be discovered.
