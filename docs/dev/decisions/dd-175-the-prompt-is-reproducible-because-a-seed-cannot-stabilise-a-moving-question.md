# DD-175: The prompt is reproducible, because a seed cannot stabilise a moving question

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `propose-alignment`, `analyse-sources`, every reference-model consumer
**Implementation:** `core/ontology_loader.py` (`stable_value`), `core/semantic_index.py`, `core/analyse_sources.py`, `core/ontology_ops.py`, `core/propose_alignment.py` (`_sorted_terms`)

### Context

Seeding every LLM stage (DD-174) moved party-domain stability from 62% to 77%, not to
100%. The residual was ours, not the provider's: the prompt was different on every run.

Two independent causes, both invisible in review because both look like ordinary code:

`Graph.value()` returns an *arbitrary* object when a term carries more than one. It takes
whatever graph iteration yields first, and that order differs between processes.
Reference-model classes routinely carry several `rdfs:comment` triples — a local
definition plus one pulled in through the import closure — so the same class described
itself differently each run. Measured on the live catalog: 46 of 2,706 resolved terms
changed their comment between two consecutive runs. `ontology_ops._first_literal` was the
same defect wearing a different name; there is no "first" when iteration order is
undefined.

Separately, `parse_source_vocabulary` collected a table's columns into a `set` of
`URIRef` and iterated it. `URIRef` hashes as a string, so iteration order is randomised
per process. All five party-domain table prompts differed between two processes, and 70
of 352 prompt lines differed for `companies` alone.

### Decision

`stable_value` lands in `ontology_loader` — the DD-103 canonical loader — and is used by
`semantic_index`, `analyse_sources` and `ontology_ops`, so every consumer stabilises from
one definition. It prefers an `en` literal, then breaks ties lexically. This is a
tie-break, not a merge: where several definitions genuinely apply, one is chosen, always
the same one.

Reference-model classes and properties are ordered by `_sorted_terms` on `(name, uri)`,
keeping own and inherited properties in separate groups because the prompt relies on that
distinction. Source tables and columns are sorted by URI; the bronze vocabulary records no
column ordinal, so that is the available deterministic order.

Restriction reads (`owl:onProperty`, `owl:onClass`) keep `Graph.value`: those are
functional by OWL semantics, so an arbitrary pick is the only pick.

### Consequences

`read_reference_terms` now hashes identically across four consecutive processes (2,706
terms), and all five party table prompts hash identically across three. Stability rose to
80%.

The remaining gap is provider-side and not ours to close: on the real 23 KB alignment
prompt a fixed seed yields three distinct completions from both `gpt-5.5` and
`gpt-5.6-terra`, where the same seed on a short prompt is byte-identical. That is what
motivated DD-177. A stable prompt is still the precondition — it is what makes a stable
answer mean anything.
