# DD-160: Source-affinity domain coverage and relationship proposal

**Status:** Accepted
**Date:** 2026-08-15
**Affects:** `domain-coverage`, `audit-column-coverage`, `kairos-ontology next`, `compile --check`,
`propose-relationships` (new), kairos-design-domain + kairos-design-mapping skills
**Implementation:** `core/domain_coverage.py` (`load_source_affinity`,
`load_source_affinity_tables`, `_classify`), `core/propose_relationships.py` (new),
`core/column_coverage_audit.py`, `core/compiler/kernel.py`
(`_unrealized_relationship_diagnostics`), `core/next_actions.py` +
`core/hub_inspection.py`, `cli/inspection.py`, `cli/sources.py`

### Context

Five issues from one dogfooding run (#491, #493, #494, #496, #498) turned out to share a single
root cause: **the toolkit already held the evidence, and never joined it up.**

- `analyse-sources` assigns every discovered source table a data domain and persists it in
  `integration/sources/_analysis/*-affinity.yaml`. Nothing ever compared that against the
  authored ontologies and bindings, so a domain holding real source data with nothing bound was
  invisible to every command. The hand-written Stage-4 report claimed two domains had "no
  eligible source tables found"; the affinity files said 2 and 4 tables respectively.
- The accelerator blueprint's `data-domains.yaml` declares `cross_domain_relationships` — 24 for
  the logistics pack — each naming an exact `property_uri` with its domain/range class URIs. It
  was consumed **only** by the legacy v2 report template (`report_projector.py`), never by the v5
  binding path. The hub shipped 27 bindings with `relationships: []`.
- `analyse_sources` blanks `domain` when the LLM assignment fails, and every consumer skipped
  empty-domain rows, so those tables appeared in **no artifact at all** (#492/#500's "12 entirely
  untracked tables").
- `UnboundTableFinding` carried no row count, so the autopilot's own "unbound tables over 1000
  rows" reporting rule was literally unevaluable.

### Decision

1. **`domain-coverage` joins source affinity against ontologies and bindings.** Each row gains
   `source_tables`, `source_tables_secondary` and a derived `status`: `bound`, `deferred`
   (modeled, source data, nothing bound — the "relax this domain" signal), `not-modeled` (source
   data, no ontology — the "add this domain" signal), or `no-eligible-sources` (genuinely empty,
   and the only status that justifies silence). Absent affinity reports yield `None`, never `0`:
   an unrun analysis must never read as "no source data exists". `SCHEMA_VERSION` 2 to 3.
2. **Unassigned source tables are surfaced, not dropped.** `domain-coverage` reports them as
   `unassigned_source_tables`, and `load_affinity_reports` now logs the count it skips. That
   loader still skips them for *alignment* — alignment picks candidate classes from a domain, and
   there is none — but the skip is no longer silent.
3. **`propose-relationships` (new, advisory, exit 0).** The object property is read from the
   blueprint bridge or from a hub `owl:ObjectProperty` (via the DD-103 canonical loader, `rdfs`
   profile, so inherited relationships count), never guessed. Join columns are matched by exact
   normalized name equality against the parent's `identity.sourceKey`. Cross-domain parents get a
   draft DD-138 `externalReference`. Everything non-derivable is an explicit sentinel.
   Endpoint matches are labelled `uri` or `local-name`, because a hub routinely authors its own
   class in its own namespace and a URI-only match discards nearly every declared bridge.
4. **`relationship.unrealized-technical-field` (warning).** Emitted when a binding carries
   `technicalFields` with `purpose: relationship` and no `relationships:` entry. Warning, not
   error: the FK really is materialized and staging carriers ahead of an unbound parent is
   legitimate. Emitted *outside* the blocking path, and the `_binding_safety_diagnostics` call
   site now blocks only on ERROR severity so a future non-error diagnostic there cannot silently
   block a binding.
5. **`audit-column-coverage` gains DD-156 row evidence, `--format json`, and cross-domain
   candidates.** An unknown true count renders `?` and a capped window `N+ (sampled)`, never a
   plain number. Cross-domain candidates come from the affinity pass's own `secondary_domains`.
6. **Routed through `kairos-ontology next`** (`model-data-driven-domain` to
   kairos-design-domain, `bind-deferred-domain` to kairos-design-mapping), so an interactive
   client-hub user gets the signal without the autopilot. Proposal `SCHEMA_VERSION` 4 to 5.

### Rejected alternatives

- **Name-matching leftover columns to other domains' properties** (the first attempt at #489's
  detector). `scaffold_binding`'s measured candidate ladder matches **zero** columns on its
  exact-equality rung against a real 3,087-column corpus, so this reports nothing while looking
  authoritative. The affinity pass's `secondary_domains` already states the same thing with
  evidence — 56 of 79 tables carry one in the dogfooding hub.
- **A `blocked` status derived from counting a domain's own `owl:DatatypeProperty`.** Answering
  "are this domain's classes bindable?" honestly needs the DD-103 semantic index per domain,
  which an always-exit-0 advisory table must not pull in; counting only local declarations
  would over-flag any domain whose properties are inherited. `plan-sources` already warns about a
  zero-datatype target class at the moment an author actually picks one (#484).
- **Persisting a deferred-source manifest** (#492). v5 is stateless by construction (DD-133); the
  v4 Claim Registry was deliberately deleted. Recompute via `domain-coverage` /
  `audit-column-coverage`; the *rationale* for a deferral belongs in the hub Decision Log (DD-141).

### Consequences

- The design loop now measures source coverage at Gate 1 instead of discovering it during
  binding, and `analyse-sources` must be run before `domain-coverage` can say anything about
  sources (it says so explicitly rather than reporting zeros).
- Consumers of the `next` proposal JSON must accept `schema_version` 5; `domain-coverage`
  consumers must accept 3.
- `compile --check` gains its second non-error diagnostic ever (after
  `safety.prefix-ambiguous`). Any freshly `scaffold-binding`-generated binding raises it, which is
  correct: the scaffolder writes the carrier and expects a human follow-up.
