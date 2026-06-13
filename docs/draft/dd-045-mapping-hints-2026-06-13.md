# DD-045: Mapping Hints for `propose-alignment` — Design Proposal

## Status

**Status:** Proposed (revised after rubber-duck challenge)  
**Date:** 2026-06-13  
**Affects:** `propose_alignment.py`, `cli/main.py`, `kairos-design-mapping` skill  
**Dependencies:** DD-043 (propose-alignment), DD-044 (inventories + specializations)  
**History:** An earlier draft proposed a new `propose-mapping` command that merged
alignment + transform/SKOS generation and deprecated `propose-alignment`. That
proposal was rejected after design review — see "Rejected Alternative" below.

---

## Context

The source-to-domain mapping pipeline today:

```
1. analyse-sources    (OpenAI API)  → *-affinity.yaml    — classify tables → domains
2. propose-alignment  (OpenAI API)  → *-alignment.yaml   — align columns → ref properties
3. design-mapping     (GH Copilot)  → model/mappings/*.ttl — reason + validate + write SKOS TTL
```

`propose-alignment` produces alignment categories (exact/semantic/partial/custom)
but **not** the SKOS predicates or SQL transforms the final TTL needs. The
`design-mapping` skill (GitHub Copilot, interactive) re-derives those from scratch.

### The pain point

The `design-mapping` skill has Copilot reason about every column match and every
transform inside the interactive conversation. This reasoning is:
- **Uncontrolled** — no versioned prompt, no temperature, context window shared
  with conversation history.
- **Repetitive** — the alignment work was already partly done by `propose-alignment`.

### What we want

Give `design-mapping` a richer starting point (SKOS predicate + transform
suggestions) **without** pretending the LLM can author production SQL unaided, and
**without** breaking the separate pre-modeling role of `propose-alignment`.

---

## Decision

### 1. Keep `propose-alignment`. Do not deprecate it.

`propose-alignment` is a **pre-modeling** artifact (`propose_alignment.py:3-8`,
DD-043). The `design-domain` skill reads `*-alignment.yaml` to pre-populate the
Source Evidence Table — "what properties do sources suggest the domain needs?"
(`kairos-design-domain/SKILL.md:369-381`). This is a different lifecycle stage
than producing mapping TTL and must be preserved.

### 2. Add an opt-in `--include-mapping-hints` flag

```bash
kairos-ontology propose-alignment --include-mapping-hints
```

When enabled, each column alignment gains **non-authoritative hint** fields. The
default (flag off) output is unchanged — preserving the pre-modeling contract.

### 3. Hint fields (column-level)

```yaml
columns:
  - column: IsActive
    data_type: bit
    ref_class: Client
    ref_property: isActive
    alignment: exact            # existing
    confidence: 0.9             # existing
    # --- mapping hints (new, only when --include-mapping-hints) ---
    transform_hint: "CAST(source.IsActive AS BOOLEAN)"
    transform_confidence: 0.6
    requires_human_confirmation: true
    transform_rationale: "Target range boolean; source type bit"
```

> **No `skos_hint`.** The SKOS predicate is a mechanical relabel of the existing
> `alignment` category (`exact`→`exactMatch`, `semantic`/`partial`→`closeMatch`,
> `custom`→none). It carries no information the alignment field doesn't already
> hold, so the `design-mapping` skill derives it directly from `alignment` during
> its reasoning. Emitting it as a hint would add a redundant, authoritative-looking
> field — and the only non-mechanical case (`partial` → `closeMatch` vs
> `narrowMatch`) is exactly where human judgement matters, so a deterministic
> default there risks rubber-stamping. See "Considered and dropped" below.

**Critical rule:** `transform_hint` is a *suggestion*, always carrying
`requires_human_confirmation: true` unless it is a trivial passthrough
(`source.Col` with matching types). The `design-mapping` skill MUST confirm every
non-trivial transform with the user.

### 4. Structural hints (table-level)

Real mappings have structural patterns the LLM can *flag candidates* for but not
decide alone. These appear as advisory hints, not committed mappings:

```yaml
structural_hints:
  - type: split_candidate
    source_table: tblClient
    discriminator_column: Type
    sampled_values: [0, 1, 2]
    target_class_candidates: [CorporateClient, SoleProprietorClient, IndividualClient]
    requires_human_confirmation: true
    rationale: "Low-cardinality discriminator with samples; 3 sibling subclasses exist"

  - type: dedup_candidate
    source_table: tblRelation
    natural_key_column: ClientID
    ordering_column_candidates: [ModifiedDate, CreatedDate]
    requires_human_confirmation: true
```

Supported hint types: `split_candidate`, `merge_candidate`, `dedup_candidate`,
`multi_target_candidate`. Each is advisory and must be confirmed.

### 5. SKOS predicate derivation (no hint field — skill-derived)

The SKOS predicate is **not** emitted as a hint. The `design-mapping` skill derives
it directly from the existing `alignment` category during its reasoning:

| Alignment category | SKOS predicate (skill-derived) | Transform expectation |
|--------------------|-------------------------------|----------------------|
| `exact` (same type) | `exactMatch` | passthrough `source.Col` (no confirmation needed) |
| `exact` (type differs) | `exactMatch` | `CAST(...)` hint (confirm) |
| `semantic` | `closeMatch` | reformatting hint (confirm) |
| `partial` | `closeMatch` / `narrowMatch` — **human-confirmed** | flag for human (confirm) |
| `custom` | none — needs new property first | no transform |

This is a trivial relabel that requires no precomputation, and the `partial` row is
deliberately left to the human to refine (`closeMatch` vs `narrowMatch`).

### 6. `design-mapping` skill stays reasoning + validation

The skill is **not** reduced to a YAML→TTL serializer. It still:
1. Reads the bronze vocabulary and domain ontology independently (existing Gate 4).
2. Loads `*-alignment.yaml` hints if present.
3. Presents, per column: hint value + source evidence + target ontology evidence +
   confidence + whether the transform is machine-suggested or human-confirmed.
4. Confirms every non-trivial transform and every structural hint with the user.
5. Writes TTL only after confirmation (existing Gate 5).

Hints **accelerate** the conversation; they do not replace the human's semantic
validation.

---

## Rationale

### Why hints, not authoritative transforms?

The source parser only exposes column name, data type, nullable, and samples
(`analyse_sources.py:88-126`). Real transforms encode business policy the LLM
cannot infer reliably:

- `CAST(source.IsActive AS BOOLEAN)` — source boolean encoding
  (`adminpulse-to-client.ttl:42-43`)
- `UPPER(TRIM(source.NationalID))` — normalization policy (`86-87`)
- `defaultValue "'unknown@acme.example'"` — business default (`38-40`)
- `source.Type = 0/1/2` split filters — discriminator semantics (`10-20`)
- dedup `ORDER BY ModifiedDate DESC` — record selection policy (`55-58`)

Marking these `requires_human_confirmation` keeps the human accountable for SQL
that lands in production silver tables.

### Why keep propose-alignment's existing output as the default?

Deprecating or restructuring it would couple "what should the domain model
contain?" (`design-domain`) with "how do I generate mapping TTL?"
(`design-mapping`). These are separate stages (DD-043). The flag is additive.

### Why not the new `propose-mapping` command?

See Rejected Alternative.

### Considered and dropped: a `skos_hint` field

An earlier version of this proposal emitted `skos_hint` (the SKOS predicate) as a
column-level field. It was dropped because:

1. **Zero added information.** It is a pure function of the existing `alignment`
   category already present in the YAML (`exact`→`exactMatch`,
   `semantic`/`partial`→`closeMatch`, `custom`→none). The `design-mapping` skill
   reads `alignment` anyway and relabels it in one trivial step — precomputing it
   saves nothing.
2. **Risks the rubber-stamp failure mode.** The only non-mechanical case
   (`partial` → `closeMatch` vs `narrowMatch`) is precisely where human SKOS
   judgement is needed. Emitting an authoritative-looking default there biases the
   human toward accepting it — the same weakened-gate concern that sank the
   rejected `propose-mapping` design.
3. **Contract clutter.** Every extra field is one more thing the skill must explain
   and the human must mentally discount, with no payoff.

The two hint types retained — `transform_hint` (grounded in a real `data_type` vs
property-range comparison) and `structural_hints` (split/dedup/multi-target
candidates) — each surface signal the alignment output does **not** already contain.

---

## Rejected Alternative: new `propose-mapping` command

The original DD-045 draft proposed a `propose-mapping` command with internal
two-phase routing (Phase A: route table→class; Phase B: map columns), a new
`*-mapping-proposal.yaml` format, deprecation of `propose-alignment`, and a
"validate only" `design-mapping` skill. Rejected because:

1. **Transforms-as-truth overreach.** It treated LLM-generated SQL transforms as
   "ready for TTL." The LLM lacks the evidence to author them safely.
2. **Schema under-expressiveness.** Its one-table-one-target schema could not
   represent split (1 table → N classes), multi-target (1 column → N properties),
   composite `sourceColumns`, or per-target filters/dedup — patterns the dbt
   projector already supports (`medallion_dbt_projector.py:514-613`).
3. **Broke pre-modeling.** Deprecating `propose-alignment` would break the
   `design-domain` Source Evidence Table workflow.
4. **Premature optimization.** Two-phase routing targets a FIBO-500-class problem
   already mitigated by `silverInclude` whitelisting (DD-021/DD-044) and the
   existing 18-class surfacing cap (`analyse_sources.py:34-38`).
5. **Weakened gates.** "Validate only" risks turning human confirmation into
   rubber-stamping of LLM output.
6. **Negative cost/benefit.** New module + command + schema + tests + deprecation
   + fallback merely relocates complexity.

If real hubs later demonstrate that enriched alignment is insufficient, a proposal
YAML can be revisited — but only with a schema redesigned first to support split,
merge, multi-target, composite `sourceColumns`, per-target filters, dedup,
defaults, and table-level SKOS predicates.

---

## Consequences

- **Modified:** `src/kairos_ontology/propose_alignment.py` — add hint generation
  behind `--include-mapping-hints`; default output unchanged.
- **Modified:** `cli/main.py` — add the flag to the `propose-alignment` command.
- **Modified:** `kairos-design-mapping` skill (+ scaffold copy) — consume hints,
  keep reasoning + validation, confirm all non-trivial transforms.
- **Unchanged:** `analyse-sources`, all projectors, `design-domain` consumption of
  the default alignment output, all other skills.
- **Tests:** unit tests for hint generation (skos_hint mapping, transform passthrough
  vs cast, structural hint detection); scenario test that `--include-mapping-hints`
  emits confirmable hints for acme-hub adminpulse→client without changing default
  output.

### Open questions to resolve during planning

1. Should structural-hint detection (split/dedup) live in `propose-alignment` or
   stay entirely in the `design-mapping` skill's reasoning? (Leaning: lightweight
   candidate detection in the command, full decision in the skill.)
2. Do we measure realistic post-whitelist inventory sizes first to confirm the
   18-class cap + whitelisting is sufficient (closes the two-phase-routing
   question for good)?
3. Trivial-passthrough rule: exact rule for when `requires_human_confirmation`
   can be `false` (same logical type + exact name match only?).
