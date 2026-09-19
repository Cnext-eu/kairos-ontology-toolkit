### Fixed
- **`validate --ddd` no longer reports an orphan overlay as passing (issue #848).** A
  `*-ddd-ext.ttl` whose filename matches no domain ontology was validated against an
  **empty graph** and printed a green tick. So a typo in an overlay filename silently
  disabled validation for that overlay, and the run-level summary counted it as validated.

  The shapes that would have caught it cannot fire: `AggregateRootTargetShape` confirms a
  class is present in the merged domain graph, and with an empty domain graph there is
  nothing to confirm against.

  An overlay with no matching domain ontology is now a failure naming the file that was
  looked for:

  ```
  ❌ clint-ddd-ext.ttl
     no domain ontology at model/ontologies/clint.ttl -- an overlay is validated merged
     with the ontology its filename names, so this one was not validated at all. Rename
     the overlay to match its domain, or remove it.
  ```

### Changed
- **SHACL is skipped for an orphan overlay rather than run against nothing.** Before, an
  overlay using `kairos-ddd:aggregateRoot` failed rule 4 with *"must point to an owl:Class
  present in the merged domain graph"* — which reads as a modelling error in the overlay
  when the real cause is that the file is orphaned, sending the reader to entirely the
  wrong place. That message is now replaced, not merely accompanied. The projection-leak
  scan still runs, because it reads the overlay alone and stays meaningful.
- The summary line reads `Checked N DDD overlay(s)` rather than `Validated N`, which was
  the specific claim an orphan made false.

### Notes
- A deliberately orphaned overlay — for example a hub-level `_contexts-ddd-ext.ttl` for
  shared `BoundedContext` declarations — used to validate "successfully" by accident,
  which made an unsupported pattern look supported. It now fails, which is the honest
  answer until such a pattern is actually designed.
- Overlays that do match an ontology are unaffected; the shipped `acme-hub` overlays pass
  unchanged.
