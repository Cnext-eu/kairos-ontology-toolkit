# DD-150: Reference-models owns the tier enum; the toolkit derives ontology tier (Amends DD-146)

**Status:** Accepted
**Date:** 2026-08-10
**Context:** #276 Q1–Q4/Q5/Q3/Q6, merged with the remaining half of #262

### Context

#275 added paired contract tests after a reference-models `pattern.yaml` shipped unparseable and
survived two minor versions. #276 then raised six design questions those tests surfaced but did not
answer. Read against the code and a v1.14.0 checkout, four were not open questions:

- `validate_artifact` rejected any tier outside the hardcoded `VALID_TIERS`, so publishing the
  proposed `not_applicable` tier would invalidate every artifact carrying it. Worse,
  `compute_scorecard` seeded buckets from `VALID_TIERS` and skipped anything else, so such a concept
  was counted in `total` but dropped from every bucket — a scorecard that under-reports silently.
- `freight-forwarder` already declares the blueprint module `required`, and `blueprints/ontology/`
  is at 0.1.0 on its own cadence, yet `_derived_ontology_version` only scanned
  `derived-ontologies/`, so a `Blueprint` pin resolved to `None` and was skipped silently.
- The pattern library's `mode_bindings` / `grain_collisions` already reached the CLI JSON via
  `to_payload()`'s `extra` flatten; only the `kairos-design-domain` prose was narrow.

### Decision

**Tier enum (Q4/Q5).** Reference-models owns `$defs/tier`; `load_valid_tiers()` resolves it from the
checkout at runtime with `VALID_TIERS` as an offline fallback, mirroring `load_outcome_codes`. It
never raises, because the schema is a soft-skip everywhere else in that module.

**Scorecard counting is self-describing, not enum-driven.** `compute_scorecard` seeds `by_tier` from
the supplied tiers **union the tiers actually present**, and never skips a concept — so `total`
always equals the sum of `by_tier`. `validate_artifact` compares scorecards with **empty buckets
normalised away**, which removes an ambient-state dependency that naive injection would have
introduced: an artifact built against a 4-tier checkout and validated against the 3-tier fallback
differs only in an empty bucket, and previously failed with a misleading "'scorecard' contradicts
'core_concepts'" the user could not act on. Net: the tier enum governs *acceptance* only.

A coverage-denominator semantics mapping was **considered and rejected** — no coverage percentage or
denominator exists anywhere in the toolkit, so it would have been designing for absent logic.

**Ontology tier (Q3).** Derived from the path the catalog resolves a module to
(`blueprints/ontology/` → `blueprint`, `derived-ontologies/` → `derived`,
`authoritative-ontologies/` → `authoritative`), reusing the resolution `build_concept_graph` already
performs. Surfaced as **`ontology_tier`** in `discovery-conformance load` — never as `tier`, which in
that same dict already means the *conformance* obligation level. This is what lets a consumer tell
"subclassing a blueprint class is expected" from "subclassing a derived, mode-bound class outside its
mode is the error to flag".

**Pattern surfacing (Q1/Q2).** `grain_collisions` is promoted to a first-class `Pattern` field (all
five published patterns ship it). `mode_bindings`, `participants` and `naming_rule` stay in `extra`:
they already reach consumers through the payload flatten, and promoting a key only one pattern
declares would make the other four emit an empty placeholder in the exact payload an LLM reads. The
substantive change is `kairos-design-domain` prose, now covering four surfaces — normative naming,
**structural** anti-patterns, per-mode `mode_bindings` (`modelled` → bind, `extension-point` → do not
invent a class, `pattern-only` → pattern alone), and `grain_collisions` as do-not-subclass boundaries.

### Rejected alternatives

- **Keep `VALID_TIERS` authoritative and hand-add `not_applicable`** — keeps the duplication #275
  could only detect, and needs a toolkit release per upstream tier. Rejected.
- **Promote `mode_bindings`/`participants` to fields** — churn with negative value (see above).
- **A `module_profiles`/legacy-profile warning in `reference_modules.py` (Q6)** — that module has no
  warning-level diagnostic precedent (every `ModuleDiagnostic` in it is an `error`), so this meant
  either breaking every hub importing the blueprint module through a bare `uri:` or inventing an
  untested severity path — for a fix reference-models owns. Recorded as an ask instead.

### Consequences

- Additive and backward-compatible; all `valid_tiers` parameters default to the existing constant.
- `test_valid_tiers_matches_the_published_schema` (#275) is **superseded**: strict equality is now a
  false alarm, since an added tier is handled at runtime. Replaced by two sharper tests — the
  published enum must *resolve*, and the fallback must never contain a tier the published enum has
  **dropped** (offline, we would keep accepting a retired tier).
- A companion contract test now pins `design_landscape`'s hardcoded `CONFIRMED_DISCOVERY_OUTCOMES` /
  `NON_EVIDENCE_DISCOVERY_OUTCOMES` against the published `outcome-codes.yaml`. `load_outcome_codes`
  never hardcoded the *list*, but those *semantics* were literals with no test — a published rename
  would have left them matching nothing, with green CI.
- The unpinned-blueprint-module warning is **payload-only, never stderr**: until reference-models
  publishes a `Blueprint` pin it fires on every load of an affected archetype and a hub designer
  cannot act on it.
- **`classify_ontology_tier` is a heuristic, not a contracted signal.** Reference-models' directory
  layout is not in the contract table, so a reorganisation would silently degrade every module to
  `unknown` and disable the blueprint warning. `tests/test_refmodels_contract.py` pins the three
  prefixes against a real checkout so this fails loudly, and an explicit tier declaration is the
  standing ask.
- Reference-models asks: publish a `Blueprint` key in `ontology_versions`; declare ontology tier
  explicitly; add `blueprints/patterns/_schema/pattern.schema.json`; relocate
  `attestation.schema.json` to a pack-neutral path; state the intended obligation semantics when
  adding `not_applicable`. DD-146's `temporal-quartet` finding is **resolved** — all five published
  patterns parse in v1.14.0.
