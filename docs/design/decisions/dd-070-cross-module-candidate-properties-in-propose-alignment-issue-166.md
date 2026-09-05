# DD-070: Cross-module candidate properties in propose-alignment (issue #166)

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `src/kairos_ontology/propose_alignment.py`,
`src/kairos_ontology/analyse_sources.py`, `src/kairos_ontology/cli/main.py`,
`.github/skills/kairos-design-mapping/SKILL.md` (+ scaffold copy)
**Implementation:** `--cross-module` / `--accelerator` on `propose-alignment`;
two-pool prompt + `ref_class_id` + `cross_module_matches` in
`run_propose_alignment`; `load_accelerator_uri_modules` in `analyse_sources.py`.

### Context

`propose-alignment` scoped the candidate reference-model pool to the **home
domain's** `domain_uris` only. A column whose true match lives in a sibling /
shared accelerator module — e.g. an `Address` class in `reference-data`,
`PaymentTerms` in `financial`, a shared `currency` property — could not be
matched and was **force-fit** onto an unrelated home-domain scalar
(`SHIPPER_STREET → partyName`). DD-069 (#167/#168) added deterministic review
flags that *detect* these implausible maps, but the column was still force-fit
because the correct class was not in the candidate pool. #166 is the fix: widen
the pool so cross-module properties can be matched, and tag each match with its
owning module.

### Decision

Opt-in, accelerator-scoped, **two-pool** design behind a new `--cross-module`
flag (default OFF, so default output is byte-identical):

1. **Scope source — require `--accelerator`.** The property pool is the UNION of
   the accelerator's data-domain `imports[].uri` (via a new
   `load_accelerator_uri_modules` that preserves the `uri ↔ module` pairing
   `load_data_domains` loses). No silent affinity-union fallback — table-less
   shared modules (the Address case) are invisible to affinity reports, so
   `--cross-module` without a resolvable accelerator errors with guidance.
2. **Two separate candidate pools.** `table_ref_classes` = home domain only →
   STEP 1 (table→class); `property_ref_classes` = widened accelerator pool →
   STEP 2 (column→property). The LLM must classify the *table* only from home
   candidates while a *column* may match a property on any pooled class. The
   property shortlist adds the top cross-module classes scored by column-token
   overlap (bounded; the unbounded full-inventory retry is disabled in
   cross-module mode as a cost guard).
3. **Stable class identity.** Each class records `source_uri`, `module`, and a
   stable `ref_class_id` (`<module>:<Class>`); dedup is keyed on `uri#name`, not
   bare name, so same-named classes across modules stay distinct.
4. **Additive, module-first output.** A matched non-home class adds `ref_module`
   (+ `ref_module_uri`, `belongs_to_domain(s)`) to its column — emitted only when
   set. The home `reference_rollup` is untouched; cross-module matches go in a
   separate `cross_module_matches` section keyed by module/class.
5. **Params-aware freshness.** `alignment_params_sha256` (covering
   cross_module/accelerator/pool signature) is persisted; the domain-level skip
   requires **both** the affinity hash and the params hash to match, and the
   per-table cache key is extended so cross-module results never collide with
   home-only ones.

### Rationale

A rubber-duck review rejected a single shared candidate list (the LLM would
classify the *table* as `Address`/`PaymentTerms`), a default-on behaviour change
(breaks the byte-identical contract and scenario fixtures), and an affinity-union
fallback (misses table-less shared modules — the exact Address case). The two-pool
+ require-accelerator + stable-`ref_class_id` design fixes the force-fit without
distorting coverage or changing default output. Imports are limited to the
explicitly-listed accelerator URIs (no `owl:imports` following → no FIBO blowup).

### Consequences

- `ref_module` / `cross_module_matches` / `alignment_params_sha256` are
  alignment-YAML fields, not `kairos-ext:` annotations — no `kairos-ext.ttl`
  change.
- Cross-module runs cost more (wider prompts) but are bounded by the shortlist
  caps and the disabled retry.
- `alignment_coverage.py` reads only known keys via `.get()`, so it tolerates the
  new fields unchanged.
