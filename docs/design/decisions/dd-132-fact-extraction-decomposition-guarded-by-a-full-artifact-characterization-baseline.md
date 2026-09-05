# DD-132: Fact-Extraction Decomposition Guarded by a Full-Artifact Characterization Baseline

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** `core/projections/medallion_dbt_projector.py`,
`core/projections/dbt/policy_normalize.py`, `tests/scenarios/`
**Implementation:** decomposed helpers in `medallion_dbt_projector.py`
(`_extract_silver_model_facts` / `_extract_schema_model_facts`) and
`_index_preparation_policies()` in `policy_normalize.py`; guarded by
`tests/scenarios/test_scenario_dbt_characterization.py` against the frozen
`tests/scenarios/fixtures/dbt_artifact_baseline.json`, regenerated deliberately via
`tests/scenarios/regenerate_dbt_artifact_baseline.py`.

### Context

The medallion dbt fact-extraction functions had grown large and multi-purpose,
making them hard to read and risky to change. A pure refactor (extracting smaller
helpers) must not alter a single byte of generated dbt output, but the existing
behavioural scenario tests only assert individual columns/warnings/SQL fragments —
they cannot detect subtle artifact drift or emission-order changes across the whole
artifact map.

### Decision

1. Decompose the large fact-extraction / preparation-normalization functions into
   smaller single-purpose helpers with no change to emitted artifacts.
2. Add a **characterization test** that pins the *complete* generated artifact set
   (all file paths + byte content, plus the non-file `__coverage_data__` /
   `__release_data__` / `__unbound_eligible__` facts) for the acme-hub client,
   invoice, and logistics scenarios as one ordered sequence (file and non-file keys
   interleaved in true emission order) against a frozen SHA-256 baseline.
3. Ship an explicit `regenerate_dbt_artifact_baseline.py --write` script so an
   *intentional* output change is a deliberate, reviewable act, never silent drift.

### Rationale

A byte-and-order-level baseline is the strongest possible guard for a
behaviour-preserving refactor: any accidental drift fails loudly, while intentional
changes remain possible through a documented regeneration path. Keeping the baseline
as one interleaved sequence preserves the real file/non-file emission ordering that
splitting into separate lists would silently discard.

### Consequences

- The fact-extraction refactor is provably output-neutral for the covered scenarios;
  future projector edits that change any artifact byte or ordering fail the
  characterization test until the baseline is deliberately regenerated and reviewed.
- Interoperates with DD-131: the `effective_domain_classes` domain resolution is
  behaviour-preserving for the single-domain acme-hub properties, so the baseline is
  unchanged by that logic.
