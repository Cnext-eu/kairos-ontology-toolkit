# DD-063: Deterministic SKOS Glossary Builder (`build-glossary`)

**Status:** Accepted (grouping amended 2026-09-20)
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
aggregates `extracted_terms` into deduplicated SKOS concepts (grouped by normalized
`prefLabel` — see the amendment below; originally grouped by `linked_iri`), and emits
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

---

### Amendment — 2026-09-20: group by `prefLabel`, never by `linked_iri`

**What changed.** The original rule keyed a concept on its `linked_iri` where one was
present, falling back to the normalized `prefLabel`. It now always groups by the
normalized `prefLabel`, and `linked_iri` is carried as a cross-reference only.

**Why.** Making the IRI the group key made it the concept's *identity*, and a business
glossary exists precisely because many business words map onto few canonical classes.
Found on a real hub ([#909](https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/909)):
sixteen party roles — cargo broker, freight forwarder, ship owner, ship manager, ship
operator, shipping agent, charterer and others — each with its own authored definition,
all legitimately carried the same `TradeParty` IRI. They collapsed into one concept
labelled with whichever term was processed last, and the other fifteen prefLabels and
definitions were discarded, not even retained as `skos:altLabel`. The glossary went from
**164 concepts to 82 by adding the links the `kairos-design-discovery` skill instructs**.

The trap was that the safe action and the documented action were opposites: omitting
`linked_iri` preserved the terms, and supplying it — the only way a term reaches the
`anchor-tables` prompt — destroyed them.

**Why label is the right identity.** Several concepts referring to one class is exactly
what `rdfs:seeAlso` means; it is a reference, not an identifier. Synonyms already have a
home in `altLabel`, and grouping by label still merges the same term recorded across two
documents, which is the deduplication the original decision wanted.

**Consequence.** A concept's local name is now derived from its label rather than from the
IRI fragment, with a numeric suffix where two distinct labels would otherwise slug alike —
the same collapse one level down, at serialisation time. Hubs that already hold a
generated glossary will see local names change on the next `build-glossary` run, and will
see more concepts where terms had been silently merged. Nothing else about the emitted
graph changes.

A hand-authored glossary was never affected: a human writes one concept per term with its
own IRI and its own `rdfs:seeAlso`. Only the generator collapsed them.

