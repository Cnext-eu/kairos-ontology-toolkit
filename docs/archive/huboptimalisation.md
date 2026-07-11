# Hub optimisation: reporting-informed draft model

## Problem

The hub lifecycle can become too incremental when reporting concepts, measures,
relationships, and cross-domain dependencies are discovered separately inside each
domain, silver, and gold design pass.

This is evidence-driven, but it delays the first coherent draft model and creates
repeated back-and-forth across data domains.

## Enhancement

Add a reporting-informed draft-model step backed by the claim extraction evidence
workflow.

The step creates advisory draft model evidence packs from:

- Power BI / TMDL semantic models: facts, dimensions, measures, relationships,
  keys, hierarchies, filters, and commonly used fields;
- business-discovery glossary: confirmed business terms and synonyms;
- source affinity reports and source mappings when available;
- existing claim registries when available.

The output is **not** a `*-silver-ext.ttl` seed. It is a read-only planning report:

- one all-domain summary YAML;
- per-domain draft evidence YAML files;
- a Markdown report;
- one cross-domain Mermaid ERD-style view.

## Methodology placement

The canonical lifecycle remains:

`discovery -> source -> domain -> mapping -> claims -> silver -> gold -> validate -> project`

The draft-model report is used in two passes:

1. **Early intake** after source analysis and before domain design. Uses only
   evidence that can exist at that point: source affinity, TMDL, glossary, and
   any resumed claims.
2. **Post-mapping fit-gap** in the existing claims phase. Reconciles reporting
   demand with mappings, approved/source-backed claims, and passthrough decisions.

## Guardrails

- TMDL / Power BI is advisory, not authoritative.
- TMDL joins become relationship questions, not approved FKs or natural keys.
- Measures and report calculations feed gold review, not domain ontology
  properties.
- No claim is auto-approved.
- No ontology TTL or silver extension TTL is written.
- The ERD is visual planning output only; it is not projection input.

## Draft output per domain

For each detected data domain, the report should show:

- candidate classes or imported reference-model classes to consider;
- likely local ontology gaps or specialization candidates;
- source/TMDL/glossary evidence supporting each candidate;
- relationship questions, including TMDL semantic-model joins;
- natural-key and FK questions for silver review;
- measure/fact/dimension candidates for gold review;
- mapping gaps and source coverage gaps;
- suggested dispositions: claim, specialize, passthrough, skip, gap,
  gold-candidate,
  or defer.

Domains without ontology files still receive an evidence pack and next-action
recommendation, but no TTL is written.

## Visual view

The report includes one cross-domain ERD-style Mermaid diagram. Nodes are grouped
or labelled by data domain and show evidence status where possible:

- source-backed;
- TMDL-only;
- glossary-supported;
- mapping-backed;
- claim-approved;
- unresolved.

This gives reviewers a visual draft of the whole proposed model before approving
domain, silver, or gold design decisions.

## Data-product vertical slice

For a quick report pack or semantic-model exercise, use a **data-product vertical
slice** instead of a direct source-to-gold shortcut.

The slice captures demand under:

`model/planning/data-products/{product}/contract.yaml`

The contract is planning input only and must declare `projection_authority:
false`. A product-scoped draft report can then filter the evidence:

```bash
kairos-ontology draft-model-report --contract model/planning/data-products/sales/contract.yaml
```

The command writes advisory artifacts in the same product folder:

- `data-product-plan.yaml`
- `data-product-report.md`
- `data-product-erd.mmd`
- `domains/*.yaml`

The product plan narrows the agenda for mapping, silver, and gold design. It does
not approve claims, write TTL, or feed projectors. Measures become
`gold-annotation-needed` only after the underlying concept is claim-backed or
mapping-backed; otherwise they remain claim/domain gaps.
