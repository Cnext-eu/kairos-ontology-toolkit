### Fixed
- **The reference rollup no longer accuses a correct mapping of hallucinating (issue
  #523).** It deduplicated reference classes by **local name**, so where two imported
  modules each declare a `Terminal` with different property sets, the two collapsed and a
  property carried by only one copy was reported as `hallucinated_properties`.

  That is a false accusation of model error — close to the worst kind of bad signal,
  because it directs review at a working mapping and away from real defects. On the
  reported hub it was investigated as a strict-schema gap before the duplicate name was
  found. It also under-reported coverage, scoring a legitimately mapped column as unmapped.

  The rollup is now keyed on the class URI. An ambiguous local name is resolved the way
  the aligner already resolves it — to whichever same-named class actually declares the
  property — so the two components no longer disagree about the same data. Display names
  stay bare while unique and are qualified with the module (`tic/locations:Terminal`) when
  not, rather than merged.

### Added
- **`foreign_properties` separates a misassignment from an invention.** A property that
  exists elsewhere in the closure but not on this class is a different finding from one
  that exists nowhere, and only the second is a hallucination. They call for different
  responses, and the report now says which it is.
