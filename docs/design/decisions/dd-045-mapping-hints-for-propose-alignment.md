# DD-045: Mapping Hints for `propose-alignment`

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `propose_alignment.py`, `cli/main.py`, `kairos-design-mapping` skill, `kairos-design-source` skill
**Implementation:** `src/kairos_ontology/propose_alignment.py` (hint functions + `include_mapping_hints`), `src/kairos_ontology/cli/main.py` (`--include-mapping-hints`)

### Context

The `design-mapping` skill (GitHub Copilot, interactive) re-derives every SKOS
predicate and SQL transform from scratch inside the conversation, even though
`propose-alignment` already performed the hard semantic column→property matching in
the prior step. This re-derivation is uncontrolled (no versioned prompt, shares the
conversation context window) and repetitive. We want to give `design-mapping` a
richer starting point **without** pretending the LLM can author production SQL
unaided, and **without** breaking the separate pre-modeling role of
`propose-alignment` (its default `*-alignment.yaml` feeds `design-domain`'s Source
Evidence Table — DD-043).

### Decision

1. **Keep `propose-alignment`; do not deprecate it.** Add an opt-in
   `--include-mapping-hints` flag. The default output is **byte-unchanged**,
   preserving the `design-domain` pre-modeling contract.

2. **Deterministic, non-authoritative hints** when the flag is on:
   - Column-level `transform_hint` derived from logical-type compatibility:
     passthrough (`source.Col`) for exact-name + same-logical-type matches; a
     `CAST(...)` candidate when types differ; flag-only when type is unclear.
     Every non-trivial hint carries `requires_human_confirmation: true`; only an
     exact-name + same-logical-type passthrough may set it `false`.
   - Table-level `structural_hints` (`split_candidate`, `dedup_candidate`,
     `merge_candidate`, `multi_target_candidate`) detected by lightweight
     heuristics. All advisory, all require confirmation.

3. **No `skos_hint` field.** The SKOS predicate is a trivial relabel of the existing
   `alignment` category, so the `design-mapping` skill derives it itself. Emitting
   it would add a redundant, authoritative-looking field whose only non-mechanical
   case (`partial` → `closeMatch` vs `narrowMatch`) is exactly where human judgement
   matters — risking rubber-stamping.

4. **`design-mapping` stays reasoning + validation.** Hints accelerate the
   conversation; Gates 4 (read bronze + ontology independently) and 5 (confirm every
   non-trivial transform and structural hint) still apply.

### Rationale

| Alternative | Why rejected |
|-------------|-------------|
| New `propose-mapping` command (LLM authors transforms + deprecates propose-alignment) | LLM can't author production SQL safely (parser only exposes name/type/nullable/samples); one-table-one-target schema can't express split/merge/multi-target; deprecation breaks `design-domain` pre-modeling; weakened gates; negative cost/benefit |
| Emit a `skos_hint` field | Pure relabel of `alignment`; redundant; authoritative-looking default risks rubber-stamping |
| Make transforms authoritative | Transforms encode business policy (encodings, defaults, dedup ordering) the parser cannot infer; must stay human-confirmed |

This applies the deterministic / promptable / judgment tiering documented in
`docs/instruction-guides/context-engineer-methodology-guide.md`: SKOS derivation and
type comparison are deterministic (Tier 1), transform/structural candidates are
advisory (Tier 2 shape), and the final transform/split decision stays human (Tier 3).

### Consequences

- `ColumnAlignment` gains optional `transform_hint`, `transform_confidence`,
  `requires_human_confirmation`, `transform_rationale`; `TableAlignment` gains
  `structural_hints`. Serialized only when populated → default output unchanged.
- `run_propose_alignment()` gains `include_mapping_hints` (default `False`);
  `propose-alignment` CLI gains `--include-mapping-hints`.
- `kairos-design-mapping` and `kairos-design-source` skills (both copies) updated to
  consume hints while keeping confirmation gates.
- Tests: `tests/test_propose_alignment_hints.py` (unit) and
  `tests/scenarios/test_scenario_mapping_hints.py` (acme-hub adminpulse→client,
  including a regression guard that default output has no hint keys).
