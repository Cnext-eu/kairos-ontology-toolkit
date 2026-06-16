# Evidence-led modeling — decision log (to merge into `toolkit-design-decisions.md`)

These entries follow the standard `DD-NNN` template but live here while the
evidence-led / accelerator-first work is on a feature track. DD numbers are
**placeholders** (`DD-EL-N`); assign final sequential `DD-NNN` numbers and move
these into `docs/design/toolkit-design-decisions.md` (and its Index) at merge.

---

## DD-EL-1: Claim Registry replaces alignment YAML as the governance source of truth

**Status:** Accepted
**Date:** 2026-06-15
**Affects:** `model/claims/{domain}-claims.yaml` (new), `{domain}-alignment.yaml`
(retired), `propose_alignment.py`, `alignment_coverage.py`, silver/dbt projectors,
`check-alignment` / `check-source-coverage`, evidence-led design skills
**Implementation:** Slice 0B schema → Slice 1 migration → Slice 2 projector
authority. Spec: `docs/implementation/evidence-led-modeling/0b-claim-registry-schema-v1.md`

### Context

The evidence-led accelerator-first methodology needs a single governed artifact
that records *which concepts are approved to materialize*, with evidence,
ownership, dispositions, and silver-contract impact. The existing
`{domain}-alignment.yaml` carries the proposal data but is an AI-output artifact,
not a governance record, and there is no approval lifecycle. Maintaining both an
alignment file and a registry would create a dual source-of-truth.

### Decision

Introduce a per-domain **Claim Registry** at `model/claims/{domain}-claims.yaml`
(schema v1) as the single hand-governed source of truth. **Retire**
`{domain}-alignment.yaml` via a one-way deterministic migration; once a domain has
a claims file, the legacy alignment file is rejected with a migration message (no
dual path). The registry covers every guarantee the alignment path provided
(per-(system,table,column) coverage snapshot, freshness hashes, algorithm/prompt
version, anchor state, custom-column triage, table/column-granular evidence) — the
parity appendix in `00-index.md` gates Slice 1.

### Rationale

One governed file with an explicit `status` lifecycle (proposed → approved → …)
and `disposition` vocabulary (claim / specialize / passthrough / skip / gap) gives
reviewable, GitHub-PR-based governance. Reusing the alignment backend functions
(coverage, freshness, anchor state) preserves all existing guarantees while
avoiding double-path logic. Golden + parity + negative migration tests enforce
fidelity.

### Consequences

- Slice 1 cannot merge until parity tests prove the registry preserves every
  alignment guarantee.
- `propose-alignment` output becomes migration input, not a parallel artifact.
- Custom-column triage values map: `model`→`specialize`/`claim`,
  `silver-passthrough`→`passthrough`, `skip`→`skip`.
- Claim ids are stable and never reused; deletions become `deprecated`.

### Slice 1 implementation note (2026-06-15)

The cutover unified the two retired gates into a single **`check-claims`** command
(backend `claim_coverage.py`): bucket priority `missing > invalid > incomplete >
stale > unverifiable > ok`, blocking on missing/invalid/incomplete/stale/
duplicate-approved + (unless `--no-source-coverage`) unmapped tables, with
`--strict` additionally blocking on undecided (`proposed`) claims and `--warn-only`
overriding to exit 0. Leftover `*-alignment.yaml` files are a hard error regardless
of `--warn-only`. `alignment_coverage.py` was purged of all alignment-YAML reader
machinery and now exposes only the reused affinity/freshness primitives and triage
heuristics (still imported by `claim_coverage`, `source_coverage`, and
`propose_alignment`). The module keeps its name despite the narrowed role.

---

## DD-EL-2: A1 — generate `owl:imports` from approved claims (defer import-all / C2)

**Status:** Accepted
**Date:** 2026-06-15
**Affects:** domain `owl:imports`, generated `silverInclude` / `silverIncludeImports`,
silver/dbt projectors, catalog wiring
**Implementation:** Slice 2 (import generation). Evidence:
`docs/implementation/evidence-led-modeling/slice-0a-closure-spike.md`

### Context

The accelerator-first concept (C2) proposed importing the **full** accelerator
pack into every hub and policing the large unclaimed surface with a no-bypass
projector. The Slice 0A spike measured this against acme-hub.

### Decision

Adopt **A1**: each domain's `owl:imports` (and accelerator sub-pack selection) is
**generated from approved class claims** plus their required closure. The full
import-all-then-suppress design (C2) is **deferred**, to be reconsidered only if a
dedicated real large-closure spike (catalog-resolved, fibo/CLdN-scale, many shared
ranges) clears both projection wall-time and FK-leak.

### Rationale

Slice 0A confirmed claim-driven suppression of unclaimed **imported** classes
leaks no FKs (`refp:Address`, `refp:ShipOperator` clean — correctness PASS), but
acme-hub structurally cannot follow `owl:imports` without a catalog (logistics
parsed to 26 triples) and is too small for a perf signal — so C2's *motivating*
risk (full-closure load + leak at scale) is **unmeasured and unresolved**. A1
removes the risk by construction: importing only claimed closures means there is
no large unclaimed surface to police, no perf cliff, and no
"access-control-over-`owl:imports`" smell.

### Consequences

- Slice 2 simplifies to *generate imports*, not *suppress* them.
- The DD-021 no-bypass mechanism is retained in code but dormant.
- A future large-closure spike is the only gate that can revive C2.

---

## DD-EL-3: A2-lite + local-class governance (registry single source, surfaces generated & reviewable)

**Status:** Accepted
**Date:** 2026-06-15
**Affects:** thin client ontology TTL, silver/gold extension TTL, `model/claims/`,
projector generation
**Implementation:** Slices 2–4. Spec:
`docs/implementation/evidence-led-modeling/0b-claim-registry-schema-v1.md` §1

### Context

Two coupled questions: (A2) should the Claim Registry be the *only* hand-authored
artifact, generating both extension annotations and thin-ontology stubs? And
(Slice 0A Finding 3) are **local** thin-ontology classes claim-gated, given DD-021
only governs *imported* classes (acme-hub materialized local `VesselCarrier` /
`ActiveMarker` regardless of claims)?

### Decision

- **A2-lite:** the Claim Registry is the single **governance** source of truth, and
  derived surfaces (domain `owl:imports`, `silverInclude` claims, thin-ontology
  `specialize` stubs) are **generated** from approved claims — but the thin
  ontology and silver/gold extension TTL files remain **first-class, reviewable PR
  artifacts**, not hidden intermediates. Full collapse is rejected for v1.
- **Finding 3 — implicit-claim-with-record:** a class authored in the thin client
  (domain-namespace) ontology is **implicitly approved** (authoring = claiming),
  but the registry still carries an auto-generated `origin: authored`,
  `status: approved` claim for it. Only **imported** (accelerator/reference-model)
  classes require an *explicit* claim to materialize.

### Rationale

Keeping reviewable TTL preserves the ontology diff reviewers rely on and avoids
over-coupling the registry schema to projector internals, while still giving a
single governance source and GitHub-PR-based change control. Implicit-claim-with-
record closes the governance gap surfaced in 0A: every materialized table — local
or imported — has exactly one registry row, so coverage/parity stay complete.

### Consequences

- Generators must (re)produce extension + thin-ontology files from claims and keep
  them in sync; a deterministic check flags hand-edits that materialize a class
  with no approved claim (Slice 2).
- The registry must auto-emit `origin: authored` claims for local classes so
  parity tooling sees them.
- Reviewers see both the registry change and the generated TTL diff in the PR.

---

## DD-EL-4: Slice 2 — claims deterministically drive `owl:imports` + `silverInclude`; silver/dbt/powerbi projection gated on claim/projection sync

**Status:** Accepted
**Date:** 2026-06-15
**Affects:** domain `owl:imports`, `{domain}-silver-ext.ttl` (`kairos-ext:silverInclude`),
`model/claims/{domain}-claims.yaml`, `claim_projection_sync.py` (new),
`claims-to-silver-ext` CLI command (new), `check-claims` sync gate, `projector.py`
authority gate (silver/dbt/powerbi), foundation/thin-ontology scaffold
**Implementation:** Slice 2 (projection vertical slice). Realizes DD-EL-2 (A1) and
DD-EL-3 (A2-lite). Spec: `docs/implementation/evidence-led-modeling/slice-2-projection.md`

### Context

DD-EL-2 adopted **A1** (claims drive imports) and DD-EL-3 adopted **A2-lite**
(registry is the single governance source; derived TTL surfaces stay reviewable),
but until Slice 2 no code closed the loop from approved claims to materialized
output. The registry governed *what is approved* while the projection surfaces
(domain `owl:imports`, `silverInclude`) were still hand-authored, so nothing
guaranteed the two stayed in sync. DD-021's no-bypass mechanism existed in code but
was dormant (DD-EL-2), and import-all/no-bypass suppression (C2) was deferred.

### Decision

Make projection surfaces a deterministic function of approved imported class
claims, and gate materialization on their being in sync:

- A new `claim_projection_sync` module deterministically derives, from **approved
  imported** class claims, (1) the domain ontology's external `owl:imports` set and
  (2) per-class `kairos-ext:silverInclude` assertions in `{domain}-silver-ext.ttl`.
  It can evaluate drift (`evaluate_projection_sync`) or rewrite the surfaces
  (`apply_projection_sync`).
- A new **`claims-to-silver-ext`** CLI command generates/regenerates the imports +
  `silverInclude` surfaces from approved claims; `--check-only` reports drift and
  exits 1 without writing.
- **`check-claims`** gains a claim↔projection **sync gate** (with `--no-extension-sync`
  to skip) that blocks when imports / `silverInclude` drift from approved claims, or
  when a `silverIncludeImports` bulk-bypass flag is present.
- The **projector** enforces an **authority gate**: for silver/dbt/powerbi targets,
  if `model/claims/{domain}-claims.yaml` exists, projection of that domain FAILS
  (records a projection error) when the claim-derived imports/includes are out of
  sync — keeping DD-021's no-bypass guarantee but making materialization
  claim-driven.
- The starter domain-ontology scaffold imports a thin `_foundation` ontology
  (`foundation.ttl.template`), per A2-lite's thin-ontology scaffold.

### Rationale

Deriving `owl:imports` and `silverInclude` from approved claims realizes A1 by
construction — only claimed closures are imported, so there is no large unclaimed
surface to police and no import-all/no-bypass suppression. Retaining DD-021 as a
claim-driven authority gate (rather than retiring it) preserves the "no class
materializes without an approved claim" guarantee while keeping the registry the
single governance source. Keeping the surfaces as reviewable TTL (regenerated by
`claims-to-silver-ext`, validated by `check-claims --no-extension-sync` off by
default) honours DD-EL-3's A2-lite reviewability requirement.

### Consequences

- Hand-edits that drift imports / `silverInclude` away from approved claims are
  caught by `check-claims` and block silver/dbt/powerbi projection.
- `claims-to-silver-ext` is the canonical regeneration path after approving claims;
  `--check-only` makes drift a CI signal.
- DD-021 is no longer dormant — it is the claim-authority gate for materialization.
- New hubs scaffold a thin per-domain ontology importing `_foundation`.

### Slice 2 implementation note (2026-06-15)

Slice 2 landed the claim→projection loop: the deterministic
`claim_projection_sync` module (derive imports + `silverInclude` from approved
imported claims; evaluate or apply), the new `claims-to-silver-ext` CLI command
(regenerate surfaces; `--check-only` reports drift and exits 1), the `check-claims`
claim↔projection sync gate (`--no-extension-sync` to skip; blocks on drift or a
`silverIncludeImports` bulk bypass), and the projector authority gate that fails
silver/dbt/powerbi projection of a claims-governed domain when imports/includes are
out of sync. Scaffold gained `foundation.ttl.template` and the starter domain
ontology now `owl:imports` the thin `_foundation` ontology (A2-lite). This realizes
A1 (claims drive imports) while retaining DD-021 as a claim-driven gate.

---

## DD-EL-5: Slice 3 — derive-claims deterministic multi-source evidence aggregation

**Status:** Accepted
**Date:** 2026-06-15
**Affects:** `model/claims/{domain}-claims.yaml`, new `derive_claims.py`,
`derive-claims` CLI command (new), `claim_registry.merge_preserving_decisions`,
`_concurrency.py` / `_cache.py`, evidence-led design skills
(`kairos-design-source`, `kairos-execute-project`)
**Implementation:** Slice 3 (richer evidence aggregation). Pure enhancement on top
of the Slice 1/2 path. Spec:
`docs/implementation/evidence-led-modeling/slice-3-derive-claims.md`

### Context

After Slice 1 the Claim Registry is the governance source of truth and after
Slice 2 approved claims deterministically drive projection. But authoring
candidate claims is still largely a hand exercise: the evidence needed to propose
them is scattered across several already-produced artifacts (`analyse-sources`
affinity reports, `propose-alignment` column→property output, `import-tmdl`
concept-mapping dispositions, SKOS mapping TTL, and sample-derived signals). The
semantically-hard LLM work that interprets sources already happened **upstream**
in `analyse-sources` (affinity) and `propose-alignment` (column→property), and
`propose-alignment` already writes `{domain}-claims.yaml`. What is missing is a
single step that joins those evidence streams into a richer candidate claim set so
a human curates rather than hand-authors.

### Decision

Add a new **`derive-claims`** CLI command: a **deterministic, AI-free** aggregator
that merges/enriches the existing Claim Registry with additional deterministic
evidence streams and attaches **multiple `evidence_sources` per claim**. It is a
pure enhancement on top of the working Slice 1/2 path and never blocks it.

`derive-claims` joins five evidence streams deterministically on
`(system, table[, column])` and ref_class/ref_property names:

1. **Existing claims registry** (base, from `propose-alignment`/`migrate`) —
   preserves prior candidates and any human curation.
2. **`analyse-sources` affinity** (`integration/sources/_analysis/*-affinity.yaml`)
   — table→domain routing; corroborates class claims and creates new `proposed`
   class candidates for affinity tables that have no alignment anchor yet
   (`{domain}-affinity-{system}-{table}`).
3. **`import-tmdl` concept-mapping**
   (`integration/sources/powerbi/*-concept-mapping.yaml`) —
   `reference_model_match` + `action` (use|specialize|new_class|skip);
   corroborates matching class claims; `new_class` actions become `proposed` gap
   candidates **only when a single domain is being processed**.
4. **SKOS mappings** (`model/mappings/*.ttl`) — `skos:*Match` bronze→domain links
   attached as `skos_mapping` evidence to matching class/property claims.
5. **Sample-derived signals** — enum-candidate / FK-shape signals attached as
   `sample_signal` evidence.

**C4 guard — all derived/new claims are `status: proposed`, never auto-`approved`.**
Probabilistic evidence (affinity/alignment/concept-mapping) must never masquerade
as approval. Human decisions are preserved across re-runs via the existing
`merge_preserving_decisions()` in `claim_registry.py`. Conflicting evidence is
**surfaced** (low-confidence proposed claims / rationale notes), never silently
resolved.

For parity with the AI commands `derive-claims` reuses the shared helpers:
`_concurrency.map_concurrent` (`--max-workers`, default 8; 1 = serial, parallel
per-domain) and the `_cache` sidecar (`--force` bypasses; cache file at
`<analysis-dir>/.cache/derive-claims.json`). It is a skill-managed command in the
soft skill-gate set, so it emits the skill-gate warning unless
`KAIROS_SKILL_CONTEXT=1`.

### Rationale

The hard interpretation already happened upstream, so this step is **pure
deterministic plumbing**: a reproducible join with no model variance and no token
spend. Keeping it AI-free makes re-runs free, fast, and diffable, and keeps the
strong (anchored alignment) vs weak (affinity-only) evidence distinguishable in
the registry. Reusing `merge_preserving_decisions()` guarantees human dispositions
survive re-aggregation, and reusing `_concurrency`/`_cache` gives operational
parity (flags, cache semantics, per-domain parallelism) with `analyse-sources` /
`propose-alignment` without inventing a new execution model.

**Cost banner deliberately omitted.** `derive-claims` does **not** call
`_cost.print_cost_warning` because nothing is billed — it issues no LLM calls.
Printing a cost banner for a free deterministic command would train users to
ignore the banner where it actually matters (the paid AI commands), so the
omission is intentional, not an oversight.

### Consequences

- One command turns already-produced customer assets (affinity, alignment,
  concept-mapping, SKOS, samples) into a richer candidate claim set, reducing
  hand-authoring before human curation/approval.
- No claim is ever auto-approved; the approval gate (`check-claims`) is unchanged.
- Evidence granularity is preserved: each claim can carry multiple
  `evidence_sources`, keeping strong vs weak evidence visible.
- A future opt-in **`--llm-reconcile`** flag (LLM tie-breaking / rationale
  synthesis, **with** a cost banner) is explicitly **deferred** to a later slice —
  noted as future work, not implemented here.

---

## DD-EL-6: Slice 4 — MDM/reference-data rules + ownership hardening live in `check-claims`

**Status:** Accepted
**Date:** 2026-06-15
**Affects:** `model/claims/{domain}-claims.yaml` (new registry fields), `claim_registry.py`
(`ReferenceData` / `Deviation` / `OwnershipOverride` dataclasses, `validate_registry`,
`merge_preserving_decisions` / `HUMAN_CURATED_FIELDS`), `claim_coverage.py`
(`check_claims_coverage` + `ClaimCheckReport`), `data-domains.yaml` consumption,
`check-claims` CLI (`--no-mdm-anchor` / `--no-ownership`), evidence-led design skills
(`kairos-design-source`, `kairos-execute-project`)
**Implementation:** Slice 4 (MDM/reference-data rules + ownership hardening). Realizes the
MDM-first concept (C6). Spec:
`docs/implementation/evidence-led-modeling/slice-4-mdm-ownership.md`

### Context

After Slices 1–2 the Claim Registry governs *what is approved to materialize* and approved
claims deterministically drive projection, but the registry had no vocabulary for
reference/master data, cross-domain ownership exceptions, or client-native deviation
records, and `check-claims` enforced none of the MDM-first / ownership rules the
methodology requires (§5.4 MDM anchors, §11.2 passthrough promotion, §12/§14 deviation log,
§14 ownership boundaries). Broad domain claims could be approved before their reference-data
anchors (conformed dimensions, code lists, natural keys) were even known; a claim could
silently cross another data-domain's `data-domains.yaml` boundary; client-native (`gap`)
classes could land with no recorded owner/reason; and high-use passthrough fields had no
promotion-review signal.

### Decision

Add the reference-data / ownership vocabulary to the registry **as YAML-registry fields**
(not kairos-ext TTL annotations — these are governance metadata, so `kairos-ext.ttl` needs
no change), and enforce the rules **inside the single `check-claims` governance gate** rather
than as separate CLI commands or in structural `validate_registry`:

- **Schema additions (`claim_registry.py`):** new `ReferenceData`
  (`authority_system` / `code_system` / `key` / `scd_type`), `Deviation`
  (`reason` / `owner` / `gap_request`), and `OwnershipOverride` (`owner` / `rationale`)
  dataclasses, plus `Claim` fields `reference_data`, `mdm_anchor`, `deviation`,
  `ownership_override`, and `passthrough_reviewed`. All `to_dict`/`from_dict` omit
  None/default keys so the byte-stable golden output is preserved. `validate_registry`
  gains light **structural** checks only (warn if `reference_data`/`mdm_anchor` set on a
  non-`reference_data` claim; error if an `ownership_override` lacks owner or rationale).
  `merge_preserving_decisions` / `HUMAN_CURATED_FIELDS` preserve the new curated fields
  across re-runs.
- **Four governance checks (`claim_coverage.py`), reported via `ClaimCheckReport`:**
  - **MDM-anchor gate (§5.4):** a *broad domain claim* is an approved class claim with
    disposition claim/specialize. If a domain has broad claims **and** declared
    `mdm_anchor` reference-data claims still `proposed` → `anchor_pending` (**BLOCKING**).
    If broad claims but **no** declared anchors → `anchor_missing` (**WARNING**) — pragmatic
    per §5.4 ("anchors must be *known*, not fully implemented").
  - **deviation-log (§12/§14):** approved `gap` (client-native) claims lacking a deviation
    record (owner + reason) → `deviation_missing` (**BLOCKING**).
  - **ownership-boundary (§14):** approved claims whose `class_uri` starts with another
    data-domain's `uris` prefix (from `data-domains.yaml`) and not the registry's own
    domain → `ownership_conflicts` (**BLOCKING**) unless an `ownership_override`
    (owner + rationale) is present.
  - **passthrough-review (§11.2):** high-use passthrough claims (evidence spans ≥2 source
    systems, OR a powerbi measure/slicer/filter/hierarchy/join/fk/sample_signal evidence
    type, OR any evidence carries a `measure`) not yet `passthrough_reviewed` →
    `passthrough_review` (**WARNING**).
- **Shared-conformed-dimension escape hatch:** cross-file same-URI approved claims now route
  to `shared_dimensions` (**WARNING**) instead of `duplicate_approved` (**BLOCKING**) when
  either claim carries an `ownership_override` — the documented owner+rationale that lets a
  conformed dimension be shared across domains.
- **CLI:** `check-claims` gains `--no-mdm-anchor` and `--no-ownership` to skip those gates.

### Rationale

`check-claims` is the **one** deterministic governance gate, so the MDM/ownership rules
belong there ("ownership checks are the gate's responsibility", per the validator
docstring): a single gate means one place a reviewer/CI consults for *may this materialize?*,
no fragmented governance across multiple commands, and no risk of a separate command being
skipped. Keeping the new fields as YAML-registry metadata (not TTL annotations) reflects that
they are *governance* facts, not ontology semantics, so the reviewable ontology diff and
`kairos-ext.ttl` are untouched. Splitting MDM-anchor into a **blocking** `anchor_pending`
(anchors declared but undecided) vs a **warning** `anchor_missing` (no anchors declared)
keeps the gate pragmatic per §5.4 — it forces anchors to be *known* without demanding every
reference table be fully implemented before broad claims can proceed. The `ownership_override`
escape hatch makes conformed-dimension sharing an explicit, owned, reviewable decision rather
than either a hard block or a silent duplicate. Structural well-formedness stays in
`validate_registry`; the *policy* judgement (what crosses a boundary, what needs an anchor)
stays in the gate.

### Consequences

- Broad domain claims cannot be approved-and-shipped before their reference-data anchors are
  at least known; undocumented cross-domain or client-native claims block the gate until an
  owner/rationale or deviation record is supplied.
- Conformed dimensions are shareable across domains, but only via an explicit
  `ownership_override` (owner + rationale) that downgrades the cross-file duplicate to a
  `shared_dimensions` warning.
- High-use passthrough fields surface a `passthrough_review` warning until a human marks
  `passthrough_reviewed`, nudging promotion review without blocking.
- `--no-mdm-anchor` / `--no-ownership` give a deliberate, named bypass for hubs not yet doing
  MDM governance; golden registry output is unchanged because all new fields are omitted when
  default.

---

## DD-EL-7: Slice 5 — Power BI/source fit-gap simulation + gold seed (PBI as evidence, not authority)

**Status:** Accepted
**Date:** 2026-06-16
**Affects:** new `pbi_fit_gap.py`, `tmdl_parser.py` (additive hierarchy parsing),
`import_tmdl.py`, new `pbi-source-fit-gap` and `tmdl-to-gold-ext` CLI commands,
`cli/main.py`, `integration/reports/{domain}-claim-fit-gap.md` (advisory output),
`model/extensions/{domain}-gold-ext.candidate.ttl` (candidate seed), evidence-led
design/execute skills (`kairos-design-gold`, `kairos-execute-project`, `kairos-help`)
**Implementation:** Slice 5 (Power BI/source fit-gap & gold seed). Realizes the
Power BI-as-evidence guardrail (concept C7, methodology §3.5, §7). Spec:
`docs/implementation/evidence-led-modeling/slice-5-pbi-fitgap.md`

### Context

Most engagements arrive with an existing Power BI estate that encodes real reporting
demand, but the methodology is explicit that **Power BI is evidence, not authority**
(§3.5): copying an as-is PBI model into gold would let probabilistic reporting habits
masquerade as governed source-backed claims. After Slices 1–4 the Claim Registry
governs *what is approved to materialize* and approved claims drive projection, but
there was no tooling to (a) reconcile existing reporting demand against approved
source supply, or (b) bootstrap gold-layer measure/hierarchy annotations from validated
reporting assets without auto-adopting them. Methodology §7 (Power BI/source fit-gap
simulation) and §7.3 (the finding/meaning/action table) describe exactly this
reconciliation; Slice 5 implements it as advisory tooling.

### Decision

Add two **advisory** CLI commands. Neither approves claims and neither mutates governed
artifacts; both are **exempt from the skill soft-gate** like `import-tmdl` and
`coverage-report` (not added to `_SKILL_COVERED_COMMANDS`).

- **`pbi-source-fit-gap SOURCE`** — `SOURCE` is a PBIP zip / SemanticModel folder /
  standalone `.tmdl` file. Options: `--domain` (required; which `{domain}-claims.yaml`
  to compare), `--claims-dir` (default auto-detect `model/claims/`), `--model`
  (optional TMDL model-name filter), `--output/-o` (default
  `integration/reports/{domain}-claim-fit-gap.md`). It compares the PBI model against
  the approved Claim Registry and writes a markdown fit-gap report classifying every
  PBI field / measure / relationship as one of:
  - `fit` — covered by an approved, source-backed claim;
  - `gap` — reporting demand with a claim but no source supply, or no approved claim;
  - `defer` — visible PBI artifact with no claim (needs a decision);
  - `reject` — hidden PBI artifact with no claim (legacy);
  - `passthrough-dependency` — a measure depends on a field whose claim disposition is
    passthrough → review for promotion.
  It also lists **source supply without reporting demand** (approved source-backed
  claims with no PBI usage). It is **advisory**: it always exits 0 even when gaps exist
  (only real errors exit non-zero).
- **`tmdl-to-gold-ext SOURCE`** — seeds a **candidate** gold-layer extension TTL for the
  `kairos-design-gold` skill to review/confirm (human-confirmed, never auto-applied).
  Options: `--domain` (required), `--namespace` (optional; auto-derived from the domain
  claims' `class_uri` namespace when `--claims-dir` is given), `--claims-dir`, `--model`,
  `--output/-o` (default `model/extensions/{domain}-gold-ext.candidate.ttl`). It emits
  `kairos-ext:measureExpression` + `kairos-ext:measureFormatString` from PBI measures and
  `kairos-ext:hierarchyName` + `kairos-ext:hierarchyLevel` from PBI hierarchies as
  candidate annotations, with a header comment marking the file as a human-confirm
  candidate.

**Deterministic, AI-free linkage.** The claim↔PBI join is pure plumbing with no model
variance: a claim links to a PBI artifact via its `tmdl_concept_mapping` evidence; a
claim is **source-backed** when it carries an evidence type in `{source_table,
source_column, affinity, skos_mapping, sample_signal}` bound to a system; a field is
**passthrough** when its claim disposition is `passthrough`. The TMDL parser gains
**additive** hierarchy extraction (name + ordered levels) to feed the gold seed; no
existing parse behavior changes. **No new `kairos-ext:` annotations are introduced** —
all four annotations already exist in `kairos-ext.ttl`.

### Rationale

The fit-gap report **informs** claims; it never approves them, and the gold seed is
**candidate-only**. Making both commands advisory (exit 0 on gaps) and the seed a
human-confirm candidate enforces the §3.5 guardrail at the tooling level: the engineer
cannot accidentally turn an as-is PBI model into governed gold without going through the
`kairos-design-gold` review and the claim-approval gate. Keeping the linkage
deterministic and AI-free (joining already-produced `tmdl_concept_mapping` and claim
evidence) makes re-runs free, fast, and diffable, and keeps strong (source-backed) vs
weak (reporting-only) evidence visible. Exempting both from the skill soft-gate matches
`import-tmdl`/`coverage-report`: they are read-only evidence/seed producers, not
governed mutating steps, so a soft-gate warning would be noise. Reusing the existing
gold annotations (no `kairos-ext.ttl` change) keeps the reviewable ontology surface and
vocabulary untouched.

### Consequences

- Engineers get an advisory, reproducible reconciliation of reporting demand (PBI)
  against approved source supply, mapped directly to methodology §7.3's
  finding/meaning/action guidance, without any risk of auto-approving claims.
- Gold design can be bootstrapped from existing PBI measures/hierarchies as a reviewable
  candidate TTL, accelerating `kairos-design-gold` without bypassing human confirmation.
- Because both commands are advisory and exempt from the soft-gate, they fit naturally
  into the evidence-gathering phase alongside `import-tmdl`; CI/governance gates
  (`check-claims`, projector authority) are unaffected.
- Power BI remains *evidence, not authority*: nothing in this slice can promote a PBI
  artifact into a governed claim or applied gold extension on its own.

---

## DD-EL-8: Slice 6 — Change management: deterministic source-delta report + registry contract version; projector emission deferred

**Status:** Accepted
**Date:** 2026-06-16
**Affects:** new `source_delta.py`, `claim_registry.py` (optional top-level
`contract:` block), new `source-delta-report` CLI command, `cli/main.py`,
`integration/reports/{system}-source-delta.md` (advisory output), evidence-led
source/silver/help skills (`kairos-design-source`, `kairos-design-silver`,
`kairos-help`)
**Implementation:** Slice 6 (Change management & contract versioning). Realizes the
change-management guardrail (methodology §13). Spec:
`docs/implementation/evidence-led-modeling/slice-6-change-management.md`

### Context

New source systems and new fields are expected over the life of an engagement. The
methodology is explicit that they should enter as **evidence and candidate deltas, not
automatic model changes**, under the core rule (§13):

> New evidence may expand silver, but must not silently mutate existing silver.

After Slices 1–5 the Claim Registry governs *what is approved to materialize* and
approved claims drive projection, but there was no tooling to (a) reconcile a
new/changed source's bronze vocabulary against the approved claims + mappings, (b)
classify each candidate delta as additive vs breaking, or (c) decide a silver/gold
contract version bump. Methodology §13.2 (candidate delta types), §13.4 (impact report),
§13.5 (versioning) and §13.6 (backward-compatibility tactics) describe exactly this flow;
Slice 6 implements it as advisory tooling plus a registry contract-version anchor.

### Decision

Add one **advisory**, deterministic, AI-free CLI command and one registry field. Neither
approves claims nor mutates governed artifacts; the command is **exempt from the skill
soft-gate** like `import-tmdl`, `coverage-report`, `pbi-source-fit-gap`, and
`tmdl-to-gold-ext` (not added to `_SKILL_COVERED_COMMANDS`).

- **`source-delta-report`** — compares a source system's bronze vocabulary against the
  approved Claim Registry + SKOS mappings (plus optional affinity hints and an optional
  baseline vocabulary diff), classifies each candidate delta per §13.2, emits a markdown
  impact report per §13.4, and suggests a silver/gold contract version bump per §13.5 with
  backward-compatibility tactics per §13.6. Options: `--system` (required; the bronze
  vocabulary stem to evaluate), `--sources`, `--mappings`, `--claims-dir`,
  `--analysis-dir` (optional affinity), `--baseline` (optional prior vocabulary file/dir
  for change detection), `--domain` (optional, repeatable; limits approved-claim context),
  `--output` (optional; else stdout), and `--fail-on-breaking` (flag; exit non-zero when
  any breaking delta is found — a CI hook).

  **Deterministic delta → impact → version mapping:**

  | Delta type | Impact class | Version bump |
  |---|---|---|
  | `maps-to-existing-class` | mapping-only | patch |
  | `new-column-to-property` | mapping-only | patch |
  | `new-claim-candidate` | additive | minor |
  | `passthrough-candidate` | additive | minor |
  | `new-reference-list` | additive | minor |
  | `new-relationship` | additive | minor |
  | `changed-type` (backward-compatible widening, e.g. `int→bigint`, `nvarchar(50)→nvarchar(100)`) | additive | minor |
  | `semantic-conflict` | breaking | major |
  | `changed-type` (non-widening) | breaking | major |
  | `changed-key` | breaking | major |
  | `changed-grain` | breaking | major |
  | `removed-column` | breaking | major |

  Suggested-bump precedence: any breaking → **major**, else any additive → **minor**, else
  any mapping-only → **patch**, else **none**.

- **Registry `contract:` block.** `ClaimRegistry` gains an optional top-level block:

  ```yaml
  contract:
    silver_version: "1.2.0"
    gold_version: "1.0.0"
  ```

  Both keys are optional and the block is omitted entirely when unset (byte-stable for
  registries that never set it) and preserved across regeneration merges. It records the
  current silver/gold contract versions that `source-delta-report` reads and bumps.

**Projector version-metadata emission is deferred.** Emitting the contract version into
silver/gold projector output is **not** part of this slice. The contract version lives in
the registry `contract:` block and is surfaced/suggested by `source-delta-report` only.

### Rationale

Keeping the delta classification deterministic and AI-free (joining already-produced
bronze vocabulary, claims, mappings, optional affinity, and an optional baseline diff)
makes re-runs free, fast, and diffable, and keeps additive vs breaking changes
unambiguous. The fixed delta → impact → version mapping turns §13.2/§13.5 directly into
a reproducible suggestion the engineer can act on, while `--fail-on-breaking` gives CI a
single hook to block silent breaking changes — operationalizing the core invariant.

Storing the contract version in the registry `contract:` block rather than emitting it
into projector output now is a deliberate scope decision: projector emission is not in
this slice's acceptance criteria and would risk destabilizing the projection test suite
(every silver/gold golden output would change). The registry is already the governed
source of truth the report reads and bumps, so it is the natural home for the contract
version; emitting into projector output is future work. Making the command advisory and
exempt from the skill soft-gate matches the other read-only evidence producers
(`import-tmdl`, `coverage-report`, `pbi-source-fit-gap`, `tmdl-to-gold-ext`): a soft-gate
warning would be noise on a non-mutating step.

### Consequences

- A new or changed source produces a reproducible impact report (expected silver
  table/column/FK additions, breaking changes, required approvals) *before* any projection
  change merges, mapped directly to methodology §13.4.
- Breaking changes are clearly distinguished from additive ones, and the suggested contract
  version bump follows the fixed §13.5 mapping; `--fail-on-breaking` lets CI enforce the
  "must not silently mutate existing silver" invariant.
- The registry gains a byte-stable, optional contract-version anchor preserved across
  regeneration merges, without disturbing registries that don't use it.
- Because projector emission is deferred, the projection test suite is unaffected by this
  slice; surfacing the contract version in projector output remains tracked future work.

---

## DD-EL-9: Slice 7 — Thin-chat skill interaction modes + decision-packet convention; concise default; presentation-only (C10 guard)

**Status:** Accepted
**Date:** 2026-06-16
**Affects:** evidence-led design skills (`kairos-design-discovery`,
`kairos-design-source`, `kairos-design-domain`, `kairos-design-mapping`,
`kairos-design-silver`, `kairos-design-gold`) and `kairos-help` (§11, canonical
home); their `scaffold/skills/*` mirrors. **No backend/runtime code** beyond the
`__version__` bump — this is a skills/docs slice.
**Implementation:** Slice 7 (Skills thin-chat redesign + scaffold sync). Realizes
concept C10. Spec:
`docs/implementation/evidence-led-modeling/slice-7-skills-thin-chat.md`

### Context

The evidence-led skills are orchestrators that walk a user through discovery →
source → domain → mapping → silver → gold checkpoints. As the methodology matured
they accumulated verbose in-chat explanation: methodology restated every
invocation, long checkpoint write-ups, and end-of-phase chat recaps. Concept C10
proposed moving that verbosity *out of chat into versioned artifacts* (TTL,
`.sessions-design/` session files, the Claim Registry) so the chat carries only
decisions. The flagged risk was that a "decision packet" UX could degenerate into
**building a workflow engine in markdown** — duplicating orchestration logic that
belongs in deterministic CLI commands.

### Decision

Apply a shared **thin-chat presentation convention** across all `kairos-design-*`
skills, defined canonically once in **`kairos-help` §11** ("Skill interaction modes
& decision packets") and referenced (not re-explained) by each design skill via a
tailored "Interaction Modes & Decision Packets" section.

- **Four interaction modes:**
  - `guided` — the former verbose behaviour (full explanation in chat).
  - `concise` — the **new documented default**: minimal chat, decisions surfaced as
    packets, detail in artifacts.
  - `silent-artifact` — write straight to artifacts with minimal chat; still stops
    at blocking decisions (never auto-confirms — see below).
  - `review-only` — summarize the current state / proposed diffs without advancing.

- **Decision-packet schema.** Each checkpoint emits one compact packet:

  ```yaml
  summary:           # one-line what-this-is
  requires_decision: # the single thing the user must decide (or null)
  options:           # enumerated choices when a decision is required
  artifact:          # path to the full detail (TTL / .sessions-design / registry)
  mode:              # active interaction mode
  ```

  Chat renders only the decision rows; full detail goes to the repo /
  `.sessions-design/` / the Claim Registry.

- **Shared thin-chat rules:** state the methodology **once** (then link to
  `kairos-help`), emit **one packet per checkpoint**, end each phase with
  **PR-ready diffs** ("files changed; review in the PR") rather than a long chat
  recap, and prefer **artifacts over transcript**. The **no-autopilot rule is
  preserved**: `silent-artifact` reduces chatter but **never auto-confirms a
  blocking decision** — blocking checkpoints still require explicit user approval.

- **C10 guard — presentation-only.** These modes and packets are a **presentation
  layer over the existing checkpoints**, not a new orchestration/workflow engine.
  Any real branching or computed logic stays in **deterministic CLI** commands
  (CLI-does-the-work); skills remain thin wrappers and must not reimplement
  orchestration in prose.

### Rationale

Moving verbose explanation into versioned artifacts makes the durable record
reviewable in PRs and diffable over time, while the chat stays focused on the one
decision each checkpoint actually needs. Defining the convention once in
`kairos-help` §11 and linking from each skill avoids drift and keeps the skills
thin. Making `concise` the default right-sizes the common path without removing the
`guided` walkthrough for new users or `review-only`/`silent-artifact` for
experienced ones. The C10 guard is the load-bearing constraint: by scoping the work
to presentation over *existing* checkpoints — and explicitly forbidding new
orchestration logic in markdown — the slice captures the UX win without the
workflow-engine-in-prose risk, deferring any genuine branching to deterministic CLI.

### Consequences

- All `kairos-design-*` skills share one mode vocabulary and packet format, with
  `concise` as the default; the canonical definition lives in `kairos-help` §11.
- Each checkpoint produces a compact decision packet; verbose detail lands in
  artifacts (TTL, `.sessions-design/`, Claim Registry), and phases end with PR-ready
  diffs instead of chat recaps.
- The no-autopilot guarantee is unchanged: blocking decisions still require explicit
  approval; `silent-artifact` only suppresses non-decision chatter.
- Because the slice is presentation-only, no orchestration logic was added to the
  skills; real branching remains the responsibility of deterministic CLI commands
  (C10 guard upheld). No runtime code changed beyond the version bump.

---

## DD-EL-10: Slice 8 — Methodology promotion + 4.0.0-rc1 consolidation; everything kept in-repo

**Status:** Accepted
**Date:** 2026-06-16
**Affects:** `docs/methodology/accelerator-first-modeling.md` (new, canonical),
`docs/design/toolkit-design-decisions.md` (DD-080 consolidation),
`kairos-design-discovery` (MDM-first anchors), `kairos-package-dataplatform`
(claim-driven consumption notes), `CHANGELOG.md` (consolidation),
`src/kairos_ontology/__init__.py` (`__version__`)
**Implementation:** Slice 8 (Docs, DD consolidation, rollout & upstream). Spec:
`docs/implementation/evidence-led-modeling/slice-8-rollout-upstream.md`

### Context

Slices 0A–7 delivered the evidence-led, accelerator-first methodology as working
code + skills, each with a `DD-EL-N` decision on this feature track and an interim
`__version__` bump (the branch reached 4.6.0 while `main` is 3.24.1). Slice 8
promotes the methodology from draft to canonical and consolidates the decisions.
Per project direction (2026-06-16), the whole feature track ships as one release
candidate and nothing is pushed to other repositories yet.

### Decision

1. **Promote** the methodology to a canonical doc
   (`docs/methodology/accelerator-first-modeling.md`) reflecting the **measured**
   slice reality (A1 default, C2 deferred, A2-lite surfaces, MDM gate, contract
   versioning, thin-chat modes), not the original hypothesis.
2. **Consolidate** the per-slice decisions as **DD-080** in the canonical design
   log, cross-referencing DD-EL-1..10 (this entry included); keep the `DD-EL-N`
   entries as history.
3. **MDM-first discovery** — `kairos-design-discovery` captures reference/master-
   data anchors early; **dataplatform consumption notes** added to
   `kairos-package-dataplatform`.
4. **Version freeze to `4.0.0-rc1`.** Set `__version__ = "4.0.0-rc1"` and fold the
   interim `4.0.0`–`4.6.0` CHANGELOG sections into a single `[4.0.0-rc1]` section.
   No further version bumps for this track.
5. **No cross-repo push.** Rollout to downstream hubs is **documented, not
   executed** (no production domains here); upstream follow-ups (skill Gate-6
   relaxation, scaffold foundation template, routing updates) are **drafted in the
   methodology doc, not filed** as issues/PRs.

### Rationale

A single consolidated DD + a canonical methodology doc keep the design log
navigable without duplicating ~650 lines of per-slice rationale. Collapsing the
interim minor bumps into `4.0.0-rc1` matches the intent that the entire v4 work is
one release candidate of 4.0.0, and avoids advertising phantom 4.1–4.6 releases.
Keeping rollout and upstream work in-repo respects the boundary that this toolkit
repo does not own downstream hubs or filed-issue tracking for this cut.

### Consequences

- `docs/methodology/accelerator-first-modeling.md` is the canonical entry point;
  DD-080 is the design-log anchor.
- The release candidate is `4.0.0-rc1`; pre-releases are exempt from the
  CHANGELOG-match CI gate, and the branch version differs from `main` (3.24.1) so
  `version-check` passes.
- Downstream rollout and upstream issue filing are deferred follow-ups, tracked in
  methodology §11–§12.

---

> **Note:** the placeholder `DD-EL-N` numbers in this log are reassigned to real
> sequential `DD-NNN` numbers when merged into
> `docs/design/toolkit-design-decisions.md`.
