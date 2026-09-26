# DD-243: Ontology meaning is read from the import closure, and a test inventories every single-file parse

**Status:** Accepted
**Date:** 2026-09-26
**Affects:** every reader of a domain or reference ontology; every AI prompt that lists ontology terms; the managed skills; `SemanticIndex`
**Issue:** #937 (partly)
**Implementation:** `tests/test_dd103_closure_boundary.py`, `tests/test_prompt_context_contract.py`, `tests/test_skill_ontology_access.py`, `docs/dev/dd103-single-file-parse-inventory.json`, `docs/dev/ai-prompt-inventory.json`, `core/prompt_context.py`, `core/semantic_index.py`

### Context

DD-103 made `load_ontology` the single semantic-loading API: it resolves the catalog-backed
`owl:imports` closure and builds a versioned `SemanticIndex` over it. A domain `.ttl` read on
its own is missing what it imports — parent classes, inherited properties, `owl:unionOf`
domains, `schema:domainIncludes`, and everything the reference models say about the classes it
specializes.

DD-103 stated the contract but nothing enforced it. An audit at `ff58bb38` (2026-09-26) found:

- Four user-facing readers parse one file and report its classes as the whole story:
  `report_projector.generate_domain_overview_report` (`project --target report`),
  `coverage_report` (properties by literal `rdfs:domain`, no inheritance, no DD-131),
  `validator.validate_gdpr` (an inherited PII property is invisible), and
  `ontology_integrity.check_reference_model_shadowing` (direct imports only).
- The alignment prompt reads the closure index but cuts each class to 60 properties with the
  inherited ones dropped first, discloses nothing, and lets the model answer with a property
  it was never shown; the gap-decision prompt then presents "no reference-model property" as
  fact. The `scaffold-domain --ai` prompt sends import IRIs and no imported classes.
- The design skills carry the rule "never read a raw `.ttl` as text" in their anti-pattern
  lists, while their working steps say "read the import closure" and name no command. Only
  `copilot-instructions.md` says why.
- `SemanticIndex` fills `inherited_properties` only under a transitive profile and the design
  fields (`equivalent_classes`, `restrictions`, `inverse_properties`, ...) only under a design
  profile, and returns an empty tuple otherwise — indistinguishable from "declares none" (#937).

None of this was caught by a test, so the next reader, prompt or skill would repeat it.

### Decision

1. **Ontology meaning is read through `load_ontology` and the closure's `semantic_index`.**
   A direct rdflib parse of a `.ttl` is for syntax, an IRI, the authored `owl:imports`, what
   one file *declares* (by documented design), or a non-ontology input (Bronze vocabulary,
   mapping, SHACL, extension, overlay, glossary). Every such call site in production code is
   listed in `docs/dev/dd103-single-file-parse-inventory.json` with one of those reasons.
   `tests/test_dd103_closure_boundary.py` scans the package and fails on a parse with no row
   and on a row with no parse. A reader that still takes meaning from one file is a row with
   reason `single-file-semantics` and the decision that tracks it; the row is deleted when
   the reader is fixed.
2. **A prompt that lists ontology terms renders them through `core.prompt_context`.** The
   helper reads the closure index, lists direct properties then inherited ones marked with
   their origin, records exactly what it showed so a response schema can match it, and, only
   when it had to cut, adds one line the model can act on ("N further classes and M further
   properties in scope are not listed; if nothing listed fits, answer null"). Every
   chat-completion call site is listed in `docs/dev/ai-prompt-inventory.json`;
   `tests/test_prompt_context_contract.py` fails on an unlisted site and on a listed site that
   shows ontology terms without importing the helper or naming its gap. DD-244 wires the
   existing builders.
3. **`SemanticIndex.carries(field)` and `coverage`** say which profile-dependent fields the
   index's profile populates (`PROFILE_COVERAGE`, pinned to `build_semantic_index`'s switches
   by test). A consumer reads such a field only after asking; `slice()` metadata carries the
   map so a CLI reader can say "not carried by this profile" instead of printing `[]`.
4. **A managed skill that talks about `model/ontologies` or the import closure names at least
   one of `show-class-inventory`, `list-class-properties`, `explain-term`, `resolve-ontology`
   and carries the rule.** `tests/test_skill_ontology_access.py` enforces it, with a known-gap
   list the skills follow-up empties and nothing may extend.

### Consequences

- A contributor adding `Graph().parse(domain_ttl)` gets a failing test that names
  `load_ontology`; adding a prompt builder gets one that names `prompt_context`. That is the
  answer to "how do we keep new code from doing this again".
- The four known readers are inventoried, not yet fixed; the readers follow-up
  (report projector via `run_projections`' already-loaded results, coverage report with
  inherited properties and DD-131, GDPR over own-namespace classes with inherited properties,
  shadowing against the transitive closure) removes their rows. `check_unused_imports` and
  `suggest-anchor` deliberately stay on direct imports: `reference_modules` requires a direct
  `owl:imports` for every referenced module, so "used transitively" is not a legal state.
- `analyse_sources._resolve_module_classes`, naming-convention lints, `class_disposition` and
  `field_mapping_report` read one file by documented design and are inventoried as such.
- `to_dict()` is unchanged: it feeds closure hashes and determinism baselines. Coverage rides
  on `slice()` metadata and the `carries()` method only.
- Rejected: denying the `Read` tool on `model/ontologies/**` in the hub's Claude settings.
  #659 removed that because `Edit` needs a prior `Read`, making domain authoring impossible.
  Files stay readable; the closure-aware path is made the obvious one (the skills follow-up)
  and, later, a tool (DD-245).
- Amends DD-103 by adding the enforcement it lacked; does not change its contract.
- Supersedes the two earlier guards for the same rule, retired with the readers
  follow-up: `tests/test_ttl_access_boundary.py` (2026-08; top-level `core/*.py` only, a
  per-module allowlist, no reasons) and the module allow-list in
  `tests/test_semantic_loading_boundary.py` (a `.parse(` string grep over `core/**`). Every
  module they listed is a row in the inventory, which is per function and gives a reason;
  three guards for one rule would drift.
