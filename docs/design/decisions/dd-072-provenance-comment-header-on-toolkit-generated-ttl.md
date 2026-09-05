# DD-072: Provenance comment header on toolkit-generated TTL

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `src/kairos_ontology/_provenance.py` (new),
`src/kairos_ontology/import_source.py`, `src/kairos_ontology/glossary_builder.py`,
`src/kairos_ontology/cli/main.py` (`init` / `new-repo` scaffold writers),
`kairos-design-domain` + `kairos-setup-config` SKILL.md (+ scaffold copies)
**Implementation:** `provenance_comment()` / `prepend_provenance()` /
`strip_provenance()` in `_provenance.py`; call sites in the generators above.

### Context

When the toolkit deterministically writes a `.ttl` artifact (source vocabulary,
SKOS glossary, scaffold starter ontologies) the file carried no trace of *what
produced it* — no toolkit version, no generation date, no generator name. That
makes it hard to tell a hand-edited file from a regenerated one, or to know which
toolkit version emitted a given artifact when debugging.

### Decision

Add a shared `_provenance` helper that emits a small **Turtle comment header**
(lines starting with `#`) stamping the toolkit version, a UTC generation
timestamp, the generator name and a short edit-policy note. Prepend it to:

- **Generated TTL** (`Do not edit — regenerate`): source vocabulary
  (`generate_vocabulary_ttl`, `generate_vocabulary_per_table`,
  `merge_with_existing`) and the SKOS glossary (`write_glossary_graph`).
- **Scaffold TTL** (`safe to edit`): `_master.ttl` and per-domain `{domain}.ttl`
  written by `init` / `new-repo`.

The header is **plain comments only** — it adds no RDF triples, so `rdflib`
ignores it on re-parse and it cannot affect SHACL validation, merge, or
projection. `prepend_provenance` is idempotent (it strips a prior toolkit header
before stamping a fresh one), so regenerating never stacks headers. The same
helper is exposed for the design skills to stamp hand-authored ontology/SHACL
files; the convention is documented in `kairos-design-domain` and
`kairos-setup-config`.

### Rationale

Comments over RDF triples keeps the change zero-risk for every downstream reader
(validate/projections read triples only). A single shared helper avoids drift
across generators and gives skills one reusable entry point.

### Consequences

- The timestamp makes a regenerated file differ on every run (git-diff churn even
  when the triples are unchanged). Accepted as the cost of recording generation
  time; the idempotent prepend keeps it to a single header. If churn becomes a
  problem we can switch to date-only or make the timestamp opt-out.
- No projection logic or extension annotation changed, so no scenario-test
  updates were required; graph-based tests are unaffected (comments ignored on
  parse). New/extended unit tests live in `test_provenance.py`,
  `test_import_source.py`, `test_glossary_builder.py`, and `test_init.py`.
