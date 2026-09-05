# DD-157: Domain ownership surfacing and demand-evidence routing

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** `domain-coverage`, `kairos-ontology next`, `validate` (warning path), kairos-design-domain skill
**Implementation:** `src/kairos_ontology/core/domain_coverage.py` (`--explain`/`--owns` cores),
`core/next_actions.py` + `core/hub_inspection.py` (`triage-concept-mapping` observation/action),
`core/evidence_loaders.py` (`scan_concept_mapping_worksheets`, shared with `core/design_landscape.py`),
`core/reference_modules.py` (`surplus_managed_import` warning), `cli/inspection.py`,
`.github/skills/kairos-design-domain/SKILL.md` + scaffold copy

### Context

Two dogfooding findings with the same shape — **the toolkit knows, the design loop never asks**:

- **#418 (near-miss):** an author modeled transport-order concepts in the `consignment` domain. The
  blueprint's `data-domains.yaml` states per domain what it `owns` and `does_not_own`, and
  `analyse-sources` already loads that text — but only into an LLM prompt no design author ever sees.
  Nothing in the prescribed kairos-design-domain loop surfaces or checks ownership; a misplaced class
  passes every gate. Post-DD-155 the *missing*-import case is caught; the undetected residue is the
  **surplus** import (the author adds the other domain's module import, satisfying completeness while
  crossing an ownership boundary).
- **#421:** `import-tmdl` generated Engineering Packs and concept-mapping worksheets for a real hub's BI
  models; all **24 of 24** worksheet tables still had an empty `reference_model_match`. Two deterministic
  consumers already exist — `design-landscape` (advisory `bi_weight` + unfilled count) and
  `draft-model-report` (reads `domain`/`reference_model_match`/`action`) — but no skill text and no `next`
  action routes anyone to the artifacts, and the design skill's inputs mislabeled them as "optional
  TMDL/PBIP … supplied by the user" when the toolkit itself writes them to `integration/discovery/bi/`.

Principle from the adversarial round: **routing first, machinery second, no new write obligations for the
design skill.**

### Decision

1. **Routing text (skill, both copies).** Authoritative input #5 names `integration/discovery/bi/` as
   toolkit-written BI demand evidence, required reading when present; Gate 2 makes the conditional concrete
   (read the whole model on a first pass — the worksheet `domain` field is typically unfilled); step 4
   cites the concept-mapping worksheet + Engineering Pack as the source of the evidence matrix's
   "Downstream demand" column and names the two deterministic consumers. The skill is explicitly told
   **never to fill** the worksheet. DD-147's rule is reaffirmed: BI evidence is demand, never business
   authority; the "Treating TMDL or Gold demand as business authority" anti-pattern stays.
2. **`next` advisory (`triage-concept-mapping`).** A hub-level observation (total worksheet tables /
   unfilled `reference_model_match`) computed by ONE shared helper,
   `evidence_loaders.scan_concept_mapping_worksheets` — which rglobs both `integration/discovery/bi/` and
   the legacy `integration/sources/` location — consumed by both `design-landscape` (its gap message is
   unchanged) and `gather_hub_input_snapshot`, so the two counts can never diverge. The derived action is
   routed to **kairos-design-source** (it owns the import-tmdl lifecycle; kairos-design-domain is forbidden
   from filling the worksheet), status `human_decision_required`, advisory-only, exit 0 (DD-137). Proposal
   `SCHEMA_VERSION` 3→4.
3. **`domain-coverage --explain <domain>`.** Prints the domain's name, OWNS / DOES NOT OWN boundaries, and
   its blueprint module imports — the data `build_domain_coverage_report` already loaded and discarded. No
   accelerator blueprint → clean informational notice; unknown domain → the valid id list. Always exit 0
   (the command's existing contract, also required by the executable-skill test's no-refmodels fixture).
   domain-coverage `SCHEMA_VERSION` 1→2 (the CLI JSON envelope gains optional `explain`/`owns` payloads).
4. **`domain-coverage --owns <ClassName>`.** Reverse ownership lookup with **no closure parsing**: the
   materialized `referencemodels-unpacked/*-inventory.yaml` classes carry `provenance.source_identity`
   (the asserting module's ontology IRI) → matched to a managed profile via
   `load_accelerator_module_config` (both `ontology_iri` and `catalog_uri`, hash-namespace legacy forms
   normalized) → owning domain **list** via the blueprint activations (ownership can be plural).
   Case-insensitive on the class name; specified outputs: inventories missing → "run generate-inventory
   first"; class in no managed module, module assigned to no domain, and same-name-in-multiple-modules all
   say so explicitly. (Deliberately NOT `belongs_to_domains`: it exists only on the parse-all-closures slow
   path — the DD-044 inventory fast path returns early without it.)
5. **Gate-3 ownership step (skill).** A confirmation **step, not a gate** — `owns`/`does_not_own` is free
   text no validator can enforce: before authoring, run `--explain` (and `--owns` for the primary entity)
   and, if another domain owns the concept, stop and switch domains rather than authoring here.
6. **Surplus-import warning (deterministic safety net).** Inside
   `validate_external_term_imports`: **surplus = authored direct `owl:imports` ∩ managed-module IRIs −
   plan requirement IRIs** (a module required in any form — activation, authored term use, accepted
   transitive — is additionally excluded by requirement module id, so an alias-form import of a required
   module can't false-positive). Managedness is matched against `context.config.profiles`, NOT
   `context.modules` — a scoped (init-gate) context may not have the module resolved. The
   `surplus_managed_import` diagnostic names the module and the domain(s) the blueprint assigns it to (or
   "no domain"). Warning severity: it flows through the validator's existing warning path with **zero
   validator edits**, and the DD-155 registration gate inherits it non-blockingly. It structurally cannot
   fire on required imports, cross-module term-use imports (those ARE requirements), `_master.ttl`
   (excluded upstream by `_is_domain_ontology`), or init-added imports (activation set ⊆ requirements).

### Rejected alternatives

- **Fill the worksheet during design (kairos-design-domain).** Violates the skill's
  persist-only-the-accepted-patch charter and guard-scope footprint; per-model worksheet vs per-domain
  slice granularity mismatch; and the worksheet's free-text `domain` field is validated against nothing —
  `draft-model-report`'s `_normalise_domain` slugs it as-is, so filled-during-design values would
  manufacture phantom report domains (a live mini-#418). If wanted later: a separate triage pass under
  kairos-design-source with `domain` validated against canonical ids.
- **Subclass-parent-walk ownership heuristic** (flag a local class whose reference parent lives in a module
  the domain doesn't activate). False-positives on designed-for cross-module reuse: the DD-070 pool,
  pattern-library `mode_bindings`, and `STUB (deferred-relationship)` targets. The surplus-import warning
  is sharper and purely set-algebraic.
- **Per-domain "BI demand mapped n/m" column on domain-coverage.** Chicken-and-egg: attributing worksheet
  rows to a domain needs the very `domain` field that is unfilled; a hub-level count in `next` carries the
  same signal without inventing attribution.

### Consequences

- The design loop now sees ownership at the moment it matters (Gate 3) and gets a deterministic backstop
  (`surplus_managed_import`) for the one case DD-155 cannot catch; both are advisory/warning-level —
  nothing new blocks.
- `kairos-ontology next` surfaces untriaged BI demand and routes it to the skill that owns the lifecycle;
  consumers of the proposal JSON must accept `schema_version` 4 and the new `bi_concept_mappings` input.
<!--
~ SPDX-License-Identifier: Apache-2.0
~ Copyright 2026 Cnext.eu
-->
