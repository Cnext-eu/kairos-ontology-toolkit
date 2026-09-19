### Added
- **`import-tmdl` now proposes a `reference_model_match` per table (issue #762).**
  Concept-mapping worksheets shipped 100% empty and nothing downstream infers the field by
  design, so on a hub with a large legacy estate `design-landscape` reported no BI weight
  at all until hundreds of rows were triaged by hand — 368 on the reported hub, across 18
  PBIP exports. The report-usage packs already rank fields and measures by real placement;
  the concept mapping is the only bridge from those to accelerator classes, and it started
  blank.

  The proposal reuses `class_anchoring.rank_candidates`, the same deterministic, lexical,
  explainable matcher `suggest-anchor` uses. No LLM: `design-landscape` performs no
  classification of its own by design, and a confident-looking score from an opaque
  similarity would make the modeller's judgement harder rather than easier. Only an
  unambiguous winner above the "qualified form" tier is proposed — a tie is the modelling
  judgement this pass exists to support, not to pre-empt. A BI role prefix (`d_`, `f_`) is
  stripped first, since it encodes table role and never the concept's name.

### Changed
- **A proposed match is not counted as BI weight until confirmed.** It is written as
  `action: candidate` alongside `match_confidence` and `match_reason`, and
  `design-landscape` reports it as awaiting confirmation rather than as evidence. BI weight
  exists to say what the business actually reports on; letting a name guess vote on that
  would invert its meaning. Confirming a proposal is far cheaper than authoring one, which
  is where the saving is.
