# DD-069: propose-alignment plausibility & address review flags (issues #167/#168)

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `propose_alignment.py`, `alignment_coverage.py`, `cli/main.py`,
`kairos-design-mapping` skill
**Implementation:** `src/kairos_ontology/propose_alignment.py`
(`_review_column_alignment`, `_detect_address_part`, `ColumnAlignment.review`),
`src/kairos_ontology/alignment_coverage.py` (`collect_review_columns`,
`AlignmentCheckReport.review_columns`)

### Context

`propose-alignment` scopes its reference-property candidate set **per target
domain**. When a source table is classified into a domain that lacks a concept
(e.g. `party`, which imports only `*/party` modules), columns whose true match
lives in a sibling module fall through — and worse, the LLM **force-fits** them
onto unrelated in-domain scalars. Observed on the CLdN hub:
`SHIPPER_STREET → partyName`, `SHIPPER_ZIP → registrationNumber`,
`FCPAYABLEIND → partyIdentifier`. These structurally implausible maps passed
silently, polluting the matched set and misleading downstream mapping
(issues #167, #168). Cross-module candidate support (#166) is the broader fix
and is **out of scope** here.

### Decision

Add a deterministic, no-LLM **review pass** that runs on the main thread during
table assembly (after sidecar-cache retrieval; the cached raw LLM `result` dict
is never mutated). For each mapped column it sets `review: true` + a precise
`review_reason` when a rule fires — **the mapping is kept, only flagged**:

- **#167 address-part** — `_detect_address_part` fires on strong evidence only
  (unambiguous tokens `street`/`postalCode`/`addressLine*`/`houseNumber`, or a
  weak token `city`/`country`/`zip` together with an address qualifier such as
  `shipper`/`billing`). An address-part column mapped to a **non-address**
  property is flagged; mapped to an address-flavoured property it is exempt.
  The `review_reason` is **generic** — it does not hardcode
  `reference-data#Address`/`hasAddress` (that is #166's job).
- **#168 plausibility** — boolean source → identity/name property;
  financial-flavoured column (`iban`/`bic`/`currency`/…) → generic identity
  property (`partyIdentifier`/`registrationNumber`/`partyName`, with specific
  identifiers like `taxIdentifier`/`vatNumber` excluded); and no shared
  name token between column and property **plus** confidence below
  `REVIEW_MIN_CONFIDENCE` (0.6).

`check-alignment` collects flagged columns into a **report-only**
`review_columns` section that **never blocks** — kept separate from the #164
custom-column `--strict` gate. Output is strictly additive: when no rule fires
the YAML is byte-identical to pre-DD-069. The optional `address_candidate`
structural hint is emitted only under `--include-mapping-hints`.

### Rationale

An earlier proposal **reclassified** address columns into `custom_columns`. A
rubber-duck review rejected it: that would (a) create false `--strict` blockers
because reclassified columns enter the #164 triage queue, (b) distort
reference-rollup matched/custom counts, and (c) break the byte-identical
default-output contract (a scenario fixture legitimately maps a `Country`
column). Flagging-not-reclassifying makes #167 and #168 one consistent
mechanism, keeps the gate non-blocking, and preserves the additive contract.
Strong-evidence address detection and the numeric-identifier carve-out
(`ClientID` int → `partyIdentifier` is **not** flagged) keep false positives low.

### Consequences

- Existing fresh alignment files carry no flags until regenerated
  (`--force` / a changed affinity set), consistent with the freshness model.
- `review`/`review_reason`/`address_candidate` are YAML fields, not `kairos-ext:`
  annotations — no `kairos-ext.ttl` change.
- Deferred to #166: offering the shared `reference-data#Address` class as a real
  candidate so flagged address columns can be mapped via `Party → hasAddress`.
