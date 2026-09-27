### Fixed
- **A measure that activates an inactive relationship with `USERELATIONSHIP` can now be
  authored.** The shape checks resolve an inactive role-playing or ambiguous-path relationship
  by asking for "a USERELATIONSHIP measure", but that measure never compiled. USERELATIONSHIP
  names both ends of a relationship, the far end (`dim_date[full_date]`, or a dimension key)
  must be declared as a column dependency, and every declared column counted towards the
  measure's home table, so compile failed with `measure.ambiguous-home-table`. A column used
  only as a USERELATIONSHIP argument no longer decides the home table. The same column read
  as a value elsewhere in the expression still does.
