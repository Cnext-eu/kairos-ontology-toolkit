# DD-103: Canonical ontology closure and versioned semantic index

**Status:** Accepted
**Date:** 2026-07-21
**Affects:** ontology loading, catalogs, inventories, validation, projection, alignment,
reporting, status, prompt context, and managed design skills
**Implementation:** `core/ontology_loader.py`, `core/semantic_index.py`, compatibility
facades in `core/catalog_utils.py`, and consumer-specific adapters

### Context

Semantic consumers currently parse different ontology subsets: one file, root plus direct
imports, caller-merged graphs, or materialized single-file inventories. This makes
validation, design, alignment, projection, and LLM context disagree about term identity,
inheritance, provenance, and import completeness. Missing imports are warnings, so a
plausible artifact can be produced from partial knowledge.

### Decision

`load_ontology()` is the single public semantic-loading API. It resolves the complete
catalog-backed `owl:imports` closure with deterministic worklists and cycle guards and
returns a graph, import manifest, structured diagnostics, completeness flag, closure hash,
and versioned semantic index.

Every `owl:imports` edge is required by default. Callers may classify exact import URIs as
optional through explicit loader policy. `file://` imports are unsupported required imports
unless explicitly optional. Missing required imports fail closed; explicit degraded mode
returns `complete=false` and must be disclosed by every resulting report or artifact.
The legacy `load_graph_with_catalog()` facade temporarily opts into degraded mode to
preserve warning-and-continue behavior while consumers migrate.

Closure hashes sort manifest records and hash ontology version, source bytes, and stable
source identity. Identity is the declared ontology IRI, otherwise the import URI, and for
an IRI-less root only, a POSIX path relative to a declared identity root. Absolute paths,
timestamps, and traversal order never enter the hash.

Supported semantic profiles are explicit:

- `asserted`: parsed triples from the complete import closure;
- `rdfs`: transitive class/property hierarchy and supported domain/range consequences;
- `kairos-design`: RDFS plus Kairos-used equivalence, inverse, individual, restriction,
  intersection, and union constructs;
- `owl-rl`: opt-in standards-based OWL RL materialization.

Semantic-index and inventory schemas are independently versioned. Full URI is the sole
identity key; local names are display data. Every derived fact records asserted/inferred
and source/import provenance. Syntax-only validation remains a direct single-file parse.

Imported semantic breadth never widens physical projection breadth. Claims and extension
policy remain the reviewed materialization allow-list.

### Rationale

A complete, deterministic closure makes every consumer reason over the same evidence.
Explicit profiles avoid claiming unrestricted OWL DL support. Fail-closed defaults prevent
silent partial semantics, while the temporary lenient facade allows incremental migration
without breaking existing hubs.

### Consequences

- Semantic consumers must declare a profile and may no longer parse domain/reference
  ontologies independently.
- Existing inventory schema 1.1 requires a one-time explicit regeneration before
  closure-hash freshness is enforced.
- SHACL and projection become stricter when migrated; missing-import diagnostics and
  explicit degraded mode are part of that user-visible transition.
- Catalog/import cycles terminate deterministically and remain visible in diagnostics.
- Structured CLI inspection and prompt slices replace raw Turtle interpretation for
  semantic decisions.
- The v5 `EntityBinding` compiler resolves bound-class properties through this semantic
  index under the `rdfs` profile so subclass-inherited, cross-namespace imported properties
  are bindable without local redeclaration; see the DD-108 amendment (2026-07-28). Per the
  breadth principle above, such inherited properties are physically materialized only when a
  binding field explicitly binds them.

### Amendment (2026-08-14): the agent-facing boundary, and its limits

DD-103 above is a decision about the toolkit's own loading API. The scaffolded
`.claude/settings.json` is a separate, previously undocumented artifact invented to make that
decision hold for one agent runtime. It was never described here, and its original form denied
only `*.ttl` — while the toolkit itself treats `.rdf` as a first-class ontology serialisation
(`core/validator.py`, `core/projector.py` both glob `**/*.rdf` alongside `**/*.ttl`) and a fetched
reference-model tree is 297 `.rdf` files to 112 `.ttl`. The majority of raw ontology was therefore
outside the boundary. Recording the boundary properly:

- **Covered serialisations** are `.ttl`, `.rdf` and `.owl` — the set in `_EXTENSION_FALLBACK`
  (`core/catalog_utils.py`). `.n3`/`.nt`/`.jsonld`/`.trig` are loadable in principle but absent from
  every published tree; add them when they appear rather than pre-emptively.
- **Deliberate carve-outs.** `.json` stays readable: the reference-model tree carries 19 JSON
  *Schemas* consumed by `core/archetype_loader.py` and `core/binding_archetypes.py`, and no JSON-LD
  ontologies exist in it. `.xml` stays readable because the only match is
  `ontology-reference-models/catalog-v001.xml`, which an agent must read to register a domain.
  Bronze source vocabularies under `integration/sources/` and the business-glossary template also
  stay readable — they are required design inputs, not reference ontology.
- **Rule anchoring is load-bearing and was wrong.** A `./`-prefixed permission path anchors to the
  *current working directory*, not the project root, and this toolkit deliberately supports being run
  from inside `ontology-hub/` (DD-064). Rules are now emitted in both `/`-anchored and `./`-anchored
  form so the boundary cannot be escaped by choice of cwd.
- **`Grep(...)` rules may be inert.** Permission matching is documented against `Read`/`Edit` only,
  with `Read` covering search tools on a best-effort basis. Rather than rely on that, both prefixes
  are emitted; the redundancy is intentional and should not be "tidied" away without measuring the
  installed runtime first.
- **This is a guardrail, not a sandbox.** Permission rules scope *tool names*, so shell access
  (`cat`, `Get-Content`, `git show`) still reaches every one of these files, and a subprocess's
  `open()` is unaffected — which is precisely why the toolkit's own in-process rdflib reads keep
  working under a maximal deny list. Agents other than Claude Code are bound only by the prose
  prohibition carried in `copilot-instructions.md` and the design skills.
- **Propagation.** The file cannot use the managed-marker mechanism, because the marker is an HTML
  comment and settings JSON that fails validation is rejected *as a whole* — a stamped marker would
  silently void every rule. `update` therefore recognises previously-shipped generations by SHA-256
  and replaces only those, leaving a hand-extended file untouched with an advisory. A hub that
  predates a boundary change and has local edits will not converge on its own, by design.
