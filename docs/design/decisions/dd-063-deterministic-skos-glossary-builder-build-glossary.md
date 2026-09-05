# DD-063: Deterministic SKOS Glossary Builder (`build-glossary`)

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `src/kairos_ontology/glossary_builder.py`, `src/kairos_ontology/cli/main.py` (`build-glossary`), `kairos-design-discovery` skill
**Implementation:** `build_glossary()` + helpers in `glossary_builder.py`; `build_glossary_cmd` in `cli/main.py`

### Context

The `kairos-design-discovery` skill (Phase 2) captures a company's
alternative/business terminology as structured records in per-document extraction
files (`businessdiscovery/_extractions/*.extraction.yaml`, DD-060). Each
`extracted_terms` entry already carries `altLabel`, `prefLabel`, `definition`,
`category`, `company_specific` and a resolved `linked_iri`.

To turn those records into the company glossary TTL, the skill instructed the
agent to **hand-write a one-off `rdflib` script every run**. That serialization is
purely mechanical and identical each time, yet being agent-authored it was
non-deterministic, untestable, and risked drift (PascalCase local names,
`rdfs:seeAlso` vs `skos:relatedMatch`, splitting/grouping, deduping altLabels).
This mirrors the bookkeeping that DD-060 already moved out of the skill into a
deterministic, unit-tested module.

### Decision

Add a deterministic, AI-free `kairos-ontology build-glossary` command backed by a
new `glossary_builder.py` module. It reads the confirmed extraction files,
aggregates `extracted_terms` into deduplicated SKOS concepts (grouped by
`linked_iri`, else normalized `prefLabel`), and emits
`businessdiscovery/{company}-glossary.ttl` as a SKOS `ConceptScheme` overlay via
`rdflib` (never string concatenation). `linked_iri` becomes `rdfs:seeAlso`, or
`skos:relatedMatch` when the term sets `link_relation: relatedMatch` (e.g. a
reference-model cross-reference). Company name/domain and the glossary namespace
(`https://{company-domain}/glossary#`) are auto-detected from the hub `README.md`
and overridable via flags.

The *judgement* (prefLabel choice, IRI resolution, multi-IRI splitting, term
confirmation) stays interactive in the skill; only the TTL writing is delegated to
the command. Like `discovery-status` and the `check-*` gates, `build-glossary` is a
deterministic helper and is **not** in `_SKILL_COVERED_COMMANDS` (no soft
skill-gate warning).

### Rationale

Splitting "decide" (agent) from "serialize" (toolkit) yields consistent, testable,
idempotent output and removes a recurring source of agent-authored variance. It
keeps the glossary an overlay (Gate 4 — the domain `.ttl` is never touched) and
reuses the existing extraction schema as the single source of truth.

### Consequences

- The discovery skill now calls `build-glossary` instead of hand-writing Python.
- Glossary serialization is unit-tested (`tests/test_glossary_builder.py`) and
  reruns are idempotent.
- The extraction schema gains an optional `link_relation` field
  (`seeAlso` default | `relatedMatch`).
