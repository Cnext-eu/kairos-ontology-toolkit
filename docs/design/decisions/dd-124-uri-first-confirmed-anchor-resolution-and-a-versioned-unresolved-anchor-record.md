# DD-124: URI-First Confirmed-Anchor Resolution and a Versioned Unresolved-Anchor Record

**Status:** Accepted
**Date:** 2026-07-26
**Affects:** `core/anchor_resolution.py` (new), `core/unresolved_anchors.py` (new),
`core/propose_alignment.py`, `core/migrate_claims.py`, `core/claim_registry.py`,
`cli/main.py` (`propose-alignment`)
**Implementation:** `resolve_table_anchor`, `align_table(anchor_override=...)`,
`_process_table`'s anchor-resolution wiring in `_propose_alignments`

### Context

`propose-alignment` chose a table's reference-model class anchor purely from the LLM's
semantic guess (with a lexical name-similarity fallback when that guess was invalid), even
when the business had already **confirmed** — via the `kairos-design-discovery` Core
Concepts Conformance artifact (DD-090; `outcome: conforms` / `conforms-with-rename` +
`rename_to`) — exactly which reference-model concept a business term identifies. Both the
LLM path and the similarity fallback could silently converge on the "nearest" class even
when that confirmed evidence was itself ambiguous (e.g. two archetypes' concepts sharing
one business alias), permanently masking the disagreement instead of surfacing it for
resolution. Property/custom claims were also generated per-column independent of whether
the table's own class anchor was trustworthy, so an unreliable anchor still produced
concrete property claims downstream.

### Decision

A new pure module, `anchor_resolution.py`, builds a **confirmed alias index** from the
conformance artifact (the only input treated as authoritative here — the discovery
glossary remains "inspirational only, not reconciled" and is never consulted for anchor
resolution) and resolves a table's affinity-derived `likely_entity` against it *before* any
class selection runs, with three outcomes: `"confirmed"` (exactly one confirmed URI, present
in the table's candidate class pool — wins over any LLM/lexical guess),
`"ambiguous"` (the confirmed evidence itself names more than one distinct concept URI for
the same alias — never collapsed to the nearest one), or `"none"` (falls through to the
existing, unchanged LLM/lexical path).

`align_table` gained an `anchor_override: str | None` parameter: when the anchor resolves
to `"confirmed"`, `_process_table` passes the resolved class name through, forcing
`ref_class`/`ref_class_status="confirmed"`/`ref_class_confidence=1.0` regardless of what the
model itself proposes (columns without their own LLM-proposed `ref_class` still inherit
this confirmed class as their default). When the anchor is `"ambiguous"`, the table is
short-circuited *before* any LLM call or cache lookup: it is written with
`ref_class_status="unresolved"`, empty `column_alignments`, and the existing F6
column-reconciliation passthrough loop is skipped for it — so an unresolved anchor produces
**zero** property or custom-column claims, never a silent guess. The ambiguous result is
never cached, so a later conformance-artifact correction re-resolves fresh.

A second new pure module, `unresolved_anchors.py`, defines a versioned `UnresolvedAnchor`
record (stable `id` derived from domain/system/table, `status` of `"open"` or `"resolved"`,
`candidate_uris`, human-readable `evidence`, and an optional `resolved_uri`/`resolved_by`)
kept in a separate `{domain}-unresolved-anchors.yaml` file alongside (never inside) the
Claim Registry — decisions about an anchor's identity are provenance/evidence, not claims.
Existing records merge with each run's fresh ones (`merge_preserving_anchor_resolutions`),
so a human resolution recorded in this file is read back and honored by
`_process_table` on the next run (converting the ambiguity to a synthetic `"confirmed"`
result), without needing to touch the alignment source or wait for the conformance artifact
itself to be corrected. The file is written only when non-empty and only alongside an
actual claims-registry write, so hubs that never trigger the feature see no new file.

`CoverageTable` (Claim Registry) gained a sparse `likely_entity_uri` field, populated from
the anchor resolution and preferred over the existing name-based `uri_index` lookup in
`migrate_claims.py` when present. `VALID_ANCHOR_STATES` grew `"confirmed"`/`"unresolved"`.
A new **warning-level** (never error-level) `validate_registry()` check flags imported
`claim`/`specialize` records missing a resolvable `class_uri`/`property_uri` for their type,
without breaking existing error-level-only consumers. `propose_alignment_cmd` auto-detects
the hub's conformance artifact path (mirroring the existing `conformance_validate` command)
and passes it through; a hub with no artifact sees fully unchanged behavior.

### Rationale

Anchoring on the confirmed Core Concepts Conformance artifact — rather than glossary
aliases or model confidence — keeps exactly one human-governed source of truth for "this
business term is this concept," consistent with DD-090's own authority boundary. Treating
ambiguous confirmed evidence as a *first-class, versioned, out-of-band record* rather than
either an error or a silent pick preserves the human decision's provenance and lets it be
resolved once and reused, instead of forcing the same disambiguation choice on every run.
Blocking property-claim generation on an unresolved table anchor prevents a large volume of
claims from being built against a foundation (`ref_class`) the pipeline itself doesn't trust
yet. Keeping the new record in its own file (not inside the Claim Registry) preserves the
Registry's existing contract — every record in it is either a claim or its
generation-outcome telemetry — rather than overloading it with a third, structurally
different kind of open question.

### Consequences

- New files: `src/kairos_ontology/core/anchor_resolution.py`,
  `src/kairos_ontology/core/unresolved_anchors.py`, and a new
  `{domain}-unresolved-anchors.yaml` artifact per domain (written only when at least one
  anchor is or was ambiguous).
- `TableAlignment` gained `likely_entity_uri`/`anchor_candidate_uris`; `DomainAlignment`
  gained `unresolved_anchors`; both are sparse/backward-compatible in
  `alignment_to_dict()` output.
- `CoverageTable.likely_entity_uri` and the `"confirmed"`/`"unresolved"` anchor states are
  additive to the Claim Registry schema; existing registries without them continue to load
  unchanged (tolerant loading verified against the pre-existing "good registry" fixture).
- A domain whose *only* tables are unresolved-anchor tables is gated behind
  `--allow-fallback-output` exactly like any other all-fallback domain
  (DD-121) — an unresolved anchor's synthetic outcome is `fallback_only`, not a distinct
  gate.
- Out of scope for this change: surfacing `unresolved_anchors` in `check-claims`/
  `claim_check_result.py` output. This was deliberately deferred to avoid colliding with
  concurrent claim-gates work (DD-122/DD-123) on that same surface. **Followed up in
  DD-128**, which classifies an unresolved-anchor table's deliberate zero coverage as its
  own non-blocking `check-claims` facet instead of a blocking F6 column omission.
- New tests: `tests/test_anchor_resolution.py`, `tests/test_unresolved_anchors.py`, and
  `TestUriAnchorContract`/`TestUriAnchorContractIntegration` classes added to
  `tests/test_claim_registry.py`, `tests/test_migrate_claims.py`, and
  `tests/test_propose_alignment.py`. All new fixtures use generic accelerator-style class
  names, not Booking/TransportOrder/DCSA-specific ones.
