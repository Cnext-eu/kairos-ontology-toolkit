# Silver-First Mapping — Shipped Reference Design

**Status:** Implemented and promoted from proposal to shipped reference design  
**Originally drafted:** 2026-07-19  
**Reconciled with implementation:** 2026-07-21  
**Scope:** Deterministic target-first Silver design and release governance  
**Canonical decisions:** DD-090, DD-094, DD-095, DD-096, DD-101, DD-102

This file remains at its original path so existing links continue to work. It is
no longer a roadmap: the behavior below is implemented. Section 11 lists the
small set of genuinely deferred items.

## 1. Shipped lifecycle

Silver is a deterministic projection of encoded knowledge. Discovery conformance
can propose target concepts before source mappings exist, but it cannot approve
or materialize them.

```text
validated discovery conformance (DD-090)
        │
        ▼
deterministic proposed claims (DD-095)
        │
        ▼
explicit human / invocation-scoped fleet decision
        │
        ▼
approved Claim Registry authority (DD-094)
        │
        ├── claims-to-silver-ext managed synchronization
        │
        ▼
mapping-free aspirational dbt stub (opt-in, DD-096)
        │
        ├── status/check-release: not bound, not release-eligible (DD-101)
        │
        ▼
committed SKOS source mapping
        │
        ▼
same generated path becomes a bound model; strict release may pass
```

Approval is deliberately outside `derive-claims`: a committed conformance
outcome is evidence for a proposal, not a governance decision.

## 2. Discovery conformance is a proposed-only driver

DD-090 defines and validates
`integration/discovery/core-concepts-conformance.yaml`. DD-095 consumes a valid
artifact as one deterministic, AI-free evidence stream:

| Conformance outcome | Proposed disposition |
|---|---|
| `conforms` | `claim` |
| `conforms-with-rename` | `claim` plus rename evidence |
| `partial` | `specialize` |
| `deviates` | `gap` plus deviation evidence |
| `not-applicable` | no proposal |

All tiers participate, including `optional`. Every new or refreshed candidate
remains `status: proposed`; human-curated decisions survive reruns. This is the
precise meaning of conformance remaining non-authoritative/warn-only: it can
deterministically create evidence-backed candidates, but it never silently
changes a claim to `approved`.

## 3. One materialization authority

The Claim Registry at `model/claims/{domain}-claims.yaml` is the single
governance authority (DD-094). The retired alignment YAML is not a parallel
runtime input. A class-like claim is materialization-eligible only when:

- `status == approved`;
- `type` is `class` or `reference_data`;
- `disposition` is `claim` or `specialize`; and
- it has a governed class URI.

`proposed`, `rejected`, `deferred`, and `deprecated` claims do not emit
aspirational stubs. Proposal evidence also never counts as source mapping
coverage; only committed SKOS mappings or complete governed replacement
evidence can bind a model.

For approved imported classes, `claims-to-silver-ext` deterministically owns the
managed `owl:imports` and `kairos-ext:silverInclude` blocks. Authored Turtle
outside those blocks is preserved. Retired inline managed layouts require the
explicit migration from DD-100; ordinary synchronization does not migrate them.

DD-094 supersedes DD-061's alignment-YAML authority. Its useful source coverage
intent survives through the canonical completeness facts and the current
`check-claims` / `check-source-coverage` views.

## 4. Target-first, bind-later

`aspirational` is derived, never persisted:

```text
approved + materialization-eligible + not folded + no source binding
    = aspirational / release-blocking
```

With `project --target dbt --emit-aspirational-stubs`, DD-096 emits a stable
zero-row model at the normal Silver path:

- `materialized='view'`;
- tag `kairos_aspirational_stub`;
- derived `meta.is_aspirational=true`;
- structural and ontology-property columns, typed from Silver annotations,
  XSD ranges, or the established fallback;
- `where 1 = 0`.

The schema YAML is generated with the stub. Empty-model tests can therefore pass
vacuously; artifact existence and schema parseability are not evidence that the
model is bound or release-ready.

Stub emission is opt-in and byte-gated. The aspirational/release classification
itself is independent of the flag, so `status`, `check-release`, and
`project --strict` still identify an approved unbound target when no stub file is
emitted.

## 5. Binding and output reconciliation

A committed table-to-class SKOS mapping supplies the physical binding. On the
next projection, the same model path is rendered as a source-backed model; it is
not copied, patched, or hand-edited.

The dbt projection manifest records toolkit-owned files. Re-projection removes
obsolete manifest-owned stubs when a claim becomes ineligible or stub emission
is disabled, while preserving non-managed authored files. Generated output is
never an authority.

## 6. Four distinct completion facts

DD-101 resolves the empty-stub false-green problem by keeping these facts
separate:

| Fact | Meaning / authority |
|---|---|
| **schema-valid** | The ontology class and generated schema/model are structurally valid; dbt parse can succeed for an empty stub. |
| **bound** | Canonical `BindingAnalysis` found a physical source binding. |
| **data-valid** | Read from the persisted validation report; never inferred from a stub or a dbt schema test. |
| **release-eligible** | No approved materialization-eligible class remains aspirational, and the composed blockers are clear. |

`status --format json` exposes per-domain
`bound_classes`, `aspirational_classes`, and `release_eligible`, plus validation
`data_valid` when objectively known. These are recomputed from committed
authorities rather than read from generated `meta.is_aspirational`.

`check-release` is the read-only composition of existing claim, source coverage,
extension sync, canonical binding, validation, and projection facts. Its blocker
is the union of those evaluators; it does not invent or persist a new policy.
`project --strict` remains the enforcement point for a projection/release run and
fails while any approved eligible class is unbound.

## 7. Determinism and provenance

The projection input includes ontology, Silver extension, mappings, source
vocabularies, SHACL, claims, conformance selection, contracted dbt models,
reference-model closure, target platform, and projection configuration.

Generated timestamps are injected through the deterministic context
(`KAIROS_GENERATED_AT` / `SOURCE_DATE_EPOCH`) rather than sampled per artifact.
RDF iteration and output paths are stably ordered. Given identical encoded
inputs, toolkit version, and deterministic context, re-projection produces the
same managed path set and bytes. SQL/schema provenance records the ontology,
ontology version, toolkit version, generated time, and source/domain IRIs where
available.

The only supported handwritten SQL boundary is a contracted transformation
under `integration/transforms/dbt/` (DD-092), which is itself a governed input.

## 8. Five-phase dbt implementation

DD-102 makes the implementation boundary explicit:

```text
bind → normalize → shape → materialize → render
```

- **bind** commits the ext-merged graph, sources, mappings, contracts, and
  canonical `SourceBindings`;
- **normalize** derives FK descriptors, physical naming, and the canonical
  `BindingAnalysis` from those exact bindings;
- **shape** creates source, Silver, schema, Gold, coverage, and macro artifacts;
- **materialize** owns release metadata and project configuration;
- **render** assembles and validates immutable shaped inputs without rereading
  RDF or reclassifying policy.

This phase split changes no public path contract. Compatibility facades remain
in `medallion_dbt_projector.py`.

## 9. Negative guarantees

- Conformance and `derive-claims` never approve.
- A proposed claim never gains aspirational materialization authority.
- A zero-row stub never counts as bound, data-valid, or release-eligible.
- `meta.is_aspirational` is output metadata, not an input.
- Generated output is never hand-edited or reverse-engineered into claims.
- Source coverage is not satisfied by proposal evidence.
- `check-release` and `status` do not reimplement binding rules.
- Core still does not import the MDM package.

## 10. Authoritative scenario

`tests/scenarios/test_scenario_silver_first_e2e.py` copies `acme-hub` and proves
the complete sequence without mutating committed scenario authorities:

1. conformance validation and deterministic proposed-only derivation;
2. an explicit approved fixture as the human-governance transition;
3. managed claim-to-extension synchronization;
4. mapping-free typed stubs and blocked release;
5. fixture-selected source mappings;
6. same-path stub replacement by bound models;
7. strict release eligibility;
8. stable provenance, paths, bytes, and real dbt parse/compile tooling.

## 11. Truly deferred

The core stub-to-bind lifecycle is shipped. Only these extensions remain
deferred:

- optional promotion to dbt `contract.enforced` once pre-binding type guarantees
  are sufficient;
- the advisory client-vs-industry drift report;
- per-claim release waivers (the current rule blocks every approved eligible
  unbound class);
- optional LLM evidence reconciliation/tie-breaking;
- further extraction of the retained large leaf render helpers identified by
  DD-102.

None of these deferred items is required for the implemented conformance →
proposal → approval → stub → binding → strict-release path.
