# DD-086: Reporting-informed draft-model planning report

**Status:** Accepted
**Date:** 2026-06-21
**Affects:** `src/kairos_ontology/draft_model_report.py`, `import_tmdl.py`,
`derive_claims.py` evidence workflow, `cli/main.py`, design skills
**Implementation:** `kairos-ontology draft-model-report`

### Context

Real hubs with TMDL/Power BI evidence, glossary terms, source affinity, mappings,
and claim registries can discover high-value reporting concepts late and repeatedly
across domain, silver, and gold design. The first proposal was to generate a silver
seed, but that would drift from evidence-led claim governance and could turn BI joins
into approved natural keys or FKs too early.

### Decision

Add a deterministic, AI-free `draft-model-report` command that extends the claim
extraction evidence workflow with richer TMDL/reporting evidence and emits a
read-only draft model planning report:

- one all-domain summary YAML;
- per-domain draft evidence YAML files;
- a Markdown report;
- one cross-domain Mermaid ERD-style view.

The report is advisory (`projection_authority: false`). It may contain candidate
classes, relationship questions, natural-key/FK questions, gold measure candidates,
mapping gaps, glossary matches, and next actions, but it never approves claims,
writes ontology TTL, or writes silver extension annotations.

The methodology uses it in two passes:

1. early intake after source analysis, before domain design, using only evidence
   available at that point (affinity, TMDL, glossary, resumed claims);
2. post-mapping fit-gap in the existing claims phase, reconciling reporting demand
   with mappings, approved/source-backed claims, and passthrough decisions.

The canonical lifecycle order remains `discovery -> source -> domain -> mapping ->
claims -> silver -> gold -> validate -> project`.

### Rationale

This keeps the useful visual "draft model" experience while avoiding a fourth
claim-like source of truth. Claim state remains in `model/claims/{domain}-claims.yaml`,
projection-facing TTL remains controlled by approved claims and the silver skill,
and TMDL relationships remain questions until source/stakeholder evidence confirms
their semantics.

### Consequences

- Users get an all-domain ERD-style view before committing to domain TTL.
- TMDL concept mappings now carry `domain` and measure metadata to support routing
  and gold review.
- Skills can consume the draft as an agenda, but must still require explicit user
  confirmation before modeling, silver annotations, or gold semantics.
- Future Slice 5 work (`pbi-source-fit-gap`, `tmdl-to-gold-ext`) should reuse this
  evidence/reporting backbone rather than introduce a competing reconciler.
