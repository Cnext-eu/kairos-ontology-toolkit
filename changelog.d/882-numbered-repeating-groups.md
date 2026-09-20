### Fixed
- **The gap gate groups `ADDRESS1..3` the way it already grouped `ADDRESS_1..3`.** Family
  grouping split column names on separators and camel boundaries but not on a
  letter-to-digit boundary, so a numbered repeating group collapsed into one decision
  only when the legacy schema happened to separate the index. On one hub that meant a
  14-slot repeating group arrived as fourteen separate decisions about one concept while
  an underscore-separated pair beside it arrived as one. A trailing digit run is now read
  as an index — narrowly, so that a standard's number (`ISO6346`), a short code (`A1`)
  and digits inside a name (`CO2EMISSIONS`) are left alone, and the existing coherence
  guards still apply.
