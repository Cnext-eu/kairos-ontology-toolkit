# DD-244: An LLM prompt states what it omits

**Status:** Accepted
**Date:** 2026-09-26
**Affects:** `propose-alignment`, `draft-gap-decisions`, `analyse-sources`, `scaffold-domain --ai`, the `prompt` projection, `explain-term`, `show-class-inventory`
**Issue:** #937
**Implementation:** `core/prompt_context.py`, `core/propose_alignment.py`, `core/gap_decisions.py`, `core/analyse_sources.py`, `cli/setup.py`, `core/projections/prompt_projector.py`, `cli/inspection.py`

### Context

DD-243 found the prompts to be the largest way a partial view of an ontology becomes a wrong
conclusion, even where the terms came from the closure index:

- The alignment prompt cut each reference class to 60 properties, own properties first, so
  the inherited ones — the ones from the modules the class imports — were dropped first,
  and nothing said so. The response schema's enum was built from the whole pool, so the
  model could answer with a property it was never shown. The code's own comment recorded
  the result: "no listed Vessel property corresponds…" becoming a false blueprint gap.
- The gap-decision prompts then presented "no reference-model property" as a fact.
- The table-classification prompt cut each domain to 18 class labels sorted by URI, so an
  imported module's classes could crowd out the domain's own, and did not say it had cut.
- `scaffold-domain --ai` sent the import IRIs and no imported classes, then asked for class
  stubs, which produced the local copies `ontology_integrity` later warns about. It called
  the SDK directly, outside tracing and redaction.
- The `prompt` projection reported `truncated: false` while leaving out every imported
  class, because it asked the index for the local classes only.
- `explain-term` and `show-class-inventory` printed `[]` for fields the chosen profile
  never populates (#937): `owl:inverseOf` under RDFS reads as "declares no inverse".

The removal of the alignment prompt's provenance block in commit `9d5cfa88` was right for
what it removed — closure hashes, a selection rule, a constant "omitted modules: none",
"not anything a model can act on" — and it is the test this decision applies: a
disclosure is one line, appears only when something was cut, and tells the model what to
do about it.

### Decision

1. **A prompt that lists ontology terms renders them through `core.prompt_context`** and
   uses its two pieces: `truncate_class_pool`, which cuts a pool and reports what it cut,
   and `disclosure_line`, which is empty when nothing was cut and otherwise says: "N
   further class(es) and M further propert(y/ies) in scope are not listed. If nothing
   listed fits, answer null; do not conclude the concept is absent from the reference
   model." `tests/test_prompt_context_contract.py` holds every builder to the import.
2. **The alignment prompt, its response schema and its pair check share the shown pool.**
   Inherited properties are marked `(inherited)`; a cut class says "… N more not listed"
   on the class and the prompt ends with the disclosure line; `qualified_property_names`
   and `enforce_class_property_pairs` are built from the same cut pool, so an answer
   outside the prompt is unrepresentable rather than merely detectable.
   `ALIGNMENT_POOL_CONTRACT` is 3.
3. **The gap-decision prompts say what the aligner saw**: "no match among the reference
   properties it was shown … absence from its list is not absence from the reference
   model." Rendering the candidate class's properties there needs the closure in scope and
   is recorded as the remaining gap in the AI-prompt inventory.
4. **The classification prompt lists a domain's own classes first** and says "(+N more not
   listed)" when capped; the accelerator path sorts by name before its cap so the prompt
   is stable across runs.
5. **`scaffold-domain --ai` renders the classes its imports provide** through
   `render_class_context` and tells the model to subclass, not redeclare; it calls
   `create_chat_completion`.
6. **The `prompt` projection reports `truncated: true` and the omitted modules** when it
   leaves imported classes out, and builds relationships from the index so `owl:unionOf`
   and `schema:domainIncludes` domains appear.
7. **`explain-term` prints `not_carried_by_profile`** — the record's fields the chosen
   profile never fills — plus the `coverage` map and `unattached_property_domains`;
   `show-class-inventory --all` keeps each domain's slice metadata. This closes #937: an
   empty tuple can now be read.

### Consequences

- The alignment prompt changes, so recorded alignments are stale by contract
  (`pool_contract`); the next `propose-alignment` run re-aligns. On a 15-domain client hub
  the before/after is measured in the PR: the count of `blueprint-gap` dispositions and of
  `ref_property` values outside the shown set (the latter is now zero by construction).
- Glossary `rdfs:seeAlso` links are read as RDF, so a prefixed name counts; the glossary
  parse is inventoried under DD-243 as `glossary`.
- Rejected: restoring the full provenance block. It failed the "can the model act on it"
  test for the reason the `9d5cfa88` comment gives.
- Rejected: widening the alignment pool instead of disclosing the cut. The cut exists for
  the provider's schema budget; honesty about it is cheaper than a larger prompt.
