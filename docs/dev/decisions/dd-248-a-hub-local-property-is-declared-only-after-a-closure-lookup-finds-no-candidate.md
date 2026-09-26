# DD-248: A hub-local property is declared only after a closure lookup finds no candidate

**Status:** Accepted
**Date:** 2026-09-26
**Affects:** `propose-alignment`, `alignment-report`, `draft-gap-decisions`; then `validate`, `scaffold-extensions`, `generate-bindings`, `find-term`, the MCP `find_term` tool and the kairos-design-domain skill
**Issue:** #1051
**Implementation:** `core/closure_lookup.py`, `core/propose_alignment.py`, `core/alignment_report.py`, `core/gap_decisions.py`, `core/prompt_context.py`; later PRs: `core/hub_namespace.py`, `core/ontology_integrity.py`, `core/extension_stubs.py`, `cli/scaffold_extensions.py`, `core/generate_bindings.py`, `core/find_term.py`

### Context

A hub accumulates local properties that duplicate properties its domains already import.
Measured on a 15-domain client hub on 2026-09-26:

- The gap pipeline. `propose-alignment` shows the model at most 12 classes and 60
  properties per class; the domain closures hold 1,400 to 1,650 properties. A column whose
  property sits on the thirteenth class, or past the sixtieth property, is answered
  `custom`, reported as `no-reference-property`, and `draft-gap-decisions` drafts
  `registered-extension` for it because the aligner had also drafted a local property.
  `--suggest` sends the model no reference property at all, and `--accept-proposals` takes
  every draft. Result: 204 of 223 open names proposed as extensions; a lexical
  cross-check found 41 exact and 57 near same-name properties in the own closure.
- The design path. The hub's 241 hand-authored local properties include 11 with an exact
  same-name closure property and about 20 near-duplicates (`documentTypeCode` beside
  `documentType`, `shippedOnBoardDateTime` beside `shippedOnBoardDate`); 9 carry
  `rdfs:subPropertyOf`. `integrity.local-property-shadows-reference-model` catches the
  exact name only, as a warning, and no skill step says "look the closure up by name".
- Nothing enforces the namespace. `scaffold-extensions` derives it by heuristic with an
  `example.com` fallback and accepts any `--namespace`; a property declared in a hub file
  under a reference IRI is silently dropped by every hub-wide check; `generate-bindings`
  defines "hub-local" as "not in the anchor class's module", which also matches a
  property inherited from a second reference module.

Two shortlist defects compounded the first point: the class scorer only looked at the
first 60 properties, so a class whose only lexical match was inherited never reached the
shortlist; and the DD-244 disclosure line never counted the classes the shortlist cut.

### Decision

1. **One deterministic lookup, `core/closure_lookup.py`, shared by every consumer.** A
   column name is normalised (vendor prefix stripped when most columns share it,
   camel/snake split, abbreviations expanded) and matched against every property in the
   closure. *Exact* is equality of normalised name or label. *Near* is a token-subset
   match after dropping structural tokens (`has`, `of`), with at most two extra tokens on
   the longer side and the shorter side supplying at least half the tokens; the string
   similarity is reported for ranking, never used as the gate, because similarity alone
   accepts `eventReference` for `agentReference`. A name
   made only of generic tokens (`code`, `typeCode`) matches exactly or not at all. Output
   is ordered by score then IRI, so a run is reproducible. A hit is a candidate to
   confirm, not a mapping. A consumer with a reviewer in between (the alignment file,
   the gap sheet, `find-term`) takes every admissible match; one that acts on its own
   (the integrity warning, a skipped render) applies the precision floor 0.8, measured
   live: every real duplicate scored 0.84 or more, the noise 0.78 or less, and the
   hub's warning count went from 109 to 39.
2. **A candidate is a reason of its own.** Every custom column is looked up after the
   model answers; the candidates travel on the column (`closure_candidates`) into the
   alignment file, and `alignment-report` counts them as
   `closure-candidate-not-shown`, first in the reason order and a gap reason, so a hub
   sees how much of its gap list is a prompt-pool artefact. The class scorer sees every
   property and the disclosure line counts the classes the shortlist cut
   (`ALIGNMENT_POOL_CONTRACT` 4, so recorded alignments re-run once).
3. **The gap sheet never drafts an extension over a candidate.** The rule proposes
   nothing and names the candidates; the suggest prompts render them through
   `prompt_context.render_closure_candidates` and forbid `registered-extension` unless
   the reasoning says why the candidate does not fit; `--accept-proposals` holds an entry
   with candidates whose proposal is `registered-extension` or empty
   (`held-for-closure-candidate`). The `deferred` fallback would bury a one-line mapping
   answer, so it is withheld too.
4. **A targeted second pass, not a wider pool.** For a table whose custom columns have
   candidates, `propose-alignment` makes one further call with the anchor pinned, only
   those columns, and only the candidate classes with the candidate properties listed
   first, so the cut cannot drop them. Off with `--no-closure-retry`. (Second PR.)
5. **A hub file declares terms only under its own `owl:Ontology` IRI, and "hub-local"
   means "in a hub namespace".** `core/hub_namespace.py` is the one reader of the hub's
   ontology IRIs; `scaffold-extensions` refuses a reference or placeholder namespace and
   skips a property the class's closure already has (`--force` overrides);
   `generate-bindings` classifies by hub namespace; `validate` reports
   `integrity.local-property-resembles-reference-property` (warning) and
   `integrity.property-outside-hub-namespace` (degradable error for a reference
   module's namespace, warning for a sibling hub domain; a namespace that is neither is
   left alone, since a prefix that is the parent path of the ontology IRI is an older
   valid convention). `find-term` and the MCP `find_term` tool
   expose the same lookup, and the design-domain skill requires it before any property
   is proposed: reuse, or `rdfs:subPropertyOf` with a reason, or a recorded reason why
   no candidate fits. (Third PR.)

### Consequences

- Recorded alignments are stale by contract and re-run once after upgrade. Measured on
  the same hub with this decision in place (gpt-5.5, 109 tables, 2026-09-26): 113 gap
  columns are `closure-candidate-not-shown`; the retry mapped 93 of the 207 columns
  that had a candidate (45 %); `--accept-proposals` held 13 names for a human; after
  `--suggest` the model still proposed `registered-extension` for 8 of the 17 candidate
  names, so the hold, not the prompt wording, is the guard that matters.
- Existing hubs gain advisory warnings for near-duplicate local properties (about 20 on
  the measured hub) and no namespace errors: every local property there is already in the
  client namespace.
- Rejected: widening the alignment pool (DD-244's reasoning stands) and matching on bare
  string similarity (too noisy to be an integrity warning). Rejected: promoting an exact
  lexical match to a mapping without a model or a human, because `code` matches `code`
  on every class.
