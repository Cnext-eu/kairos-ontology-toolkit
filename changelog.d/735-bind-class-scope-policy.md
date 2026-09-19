### Fixed
- **`owl:Thing` no longer widens the dbt source scope (issue #735).** The ancestor walk in
  `_active_source_inputs` had no upper bound, unlike every other guarded class walk in the
  tree. A hub asserting `rdfs:subClassOf owl:Thing` put it in scope, and any property
  declaring `rdfs:domain owl:Thing` — a common symptom of a missing `owl:imports` — then
  matched every class at once.

### Changed
- **The three ways `_active_source_inputs` consumes `class_uris` are now documented and
  deliberate**, under the #729 policy (*traverse for compatibility, exact for identity*).
  Contracts and table mappings answer "does this domain own this?", which does not
  inherit, and stay exact. The property filter answers "could a class in scope carry
  this?", which does, and traverses up.

  The widened set was previously consulted only in the *fallback arm* of the column
  filter, so whether the ancestor walk had any effect depended on whether a source column
  happened to be registered — not a semantic distinction. It now scopes the property
  filter itself, which is what it was for.
- The inline walk is replaced by the promoted `projections.shared.class_ancestors` — the
  ninth hand-rolled `rdfs:subClassOf` walker found in the #729 inventory, now the eighth.

### Notes
- This path is live on the **Gold** side: `medallion_gold_projector` calls `bind_sources`.
  The issue scopes itself to the legacy graph-driven projector, which is not the whole
  story.
