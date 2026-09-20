# DD-229: Strategic DDD design lives in one hub-wide file; overlays annotate classes

**Status:** Accepted
**Date:** 2026-09-20
**Affects:** `core/ddd.py` (`STRATEGIC_FILE_NAME`, `find_strategic_file`,
`validate_strategic_file`, `audit_ddd_consistency`, `build_merged_graph`/`validate_ddd_overlay`
`strategic_path`), `scaffold/kairos-ddd.ttl` (1.1.0: `SubdomainType` + individuals,
`subdomainType`, `invariant`), `scaffold/kairos-ddd-shapes.shacl.ttl` (rules 8–11),
`core/projections/ddd_projector.py`, `validate --ddd`, `project --target ddd`,
`tests/test_ddd.py`, `tests/scenarios/test_scenario_ddd.py`
**Issue:** #846 (validation half; the diagram half is DD-230)

### Context

DD-091 gave the DDD overlay one file per domain, `{domain}-ddd-ext.ttl`, validated merged with
that domain's ontology and nothing else (`core/ddd.py::build_merged_graph`). A bounded context is
the one construct in that vocabulary that deliberately cuts *across* domain ontologies — that is
what distinguishes it from the one-TTL-per-domain partition — and the per-domain graph could not
hold it. Two consequences showed up the first time a real hub authored four overlays over five
contexts:

1. **Every `BoundedContext` had to be redeclared in every overlay that referenced it.**
   `ContextRelationshipShape` requires both endpoints to be typed `kairos-ddd:BoundedContext`
   *in the merged graph*, and the merged graph held one overlay. Idempotent in RDF, but
   hand-maintained: a label changed in one copy and not the others rendered inconsistently, and
   nothing checked that the copies agreed.
2. **The per-domain context map was misleading, not merely partial.** Edges rendered only for
   the overlay that declared them, so `party-ddd-report.md` printed *"No context relationships
   declared"* while `consignment-ddd-report.md` showed the whole map.

The vocabulary was also thin where a context engineer works. It had no way to say which
contexts are the business's core and which are generic, and no home for an aggregate's
invariants beyond free-prose `designNote` (the "what this does not give us" table in the hub's
own design note). And `kairos-ddd:boundedContext` silently accepted a second value and a typo:
an unresolvable context IRI rendered as a new, unlabelled box.

The obvious fix — merge *all* overlays into every validation graph — has a known hazard: an
author who then drops a redeclaration gets a working diagram and a validator that still passes
per-domain, until someone else's overlay changes. Merging everything makes the diagram tolerant
and the validation blind.

### Decision

**Strategic and tactical design are two kinds of file.**

- **One hub-wide strategic file**, `model/extensions/ddd-contexts-ext.ttl`, holds the
  `BoundedContext` individuals (label, `subdomainType`, `publishedLanguage`, `designNote`) and
  the `ContextRelationship` individuals. It is validated on its own — syntax, leak scan, SHACL
  over strategic + vocabulary — and then merged into **every** overlay's validation graph and
  into the projector's graph, so an overlay references a context by IRI and never redeclares it.
  It refuses class-level tactical predicates (`tacticalPattern`, `aggregateRoot`, `invariant`):
  there is no domain graph there to check them against.
- **One tactical overlay per domain**, `{domain}-ddd-ext.ttl`, annotates that domain's own
  classes: `boundedContext`, `tacticalPattern`, `aggregateRoot`, `invariant`, `designNote`, and
  the context-specific language — `skos:scopeNote`, `skos:example`, `skos:altLabel` — which
  adds language on top of the canonical `rdfs:label`/`rdfs:comment` and never redefines it (R1).

**The filename escapes the overlay glob on purpose.** `ddd-contexts-ext.ttl` does not end in
`-ddd-ext.ttl`, so `discover_ddd_overlays` never treats it as the overlay of a domain called
`ddd-contexts` and #848's orphan check never fires on it. The `-ext.ttl` suffix keeps it inside
the extensions convention every other overlay family uses; no compile-side glob
(`*-gold-ext.ttl`, `*-silver-ext.ttl`) can match it.

**Backward compatible.** A hub that still declares contexts inside its overlays merges nothing
extra and validates as before. The new hub-wide audit tells it what to move.

**Vocabulary 1.1.0.** `kairos-ddd:SubdomainType` with `CoreDomain`, `SupportingSubdomain`,
`GenericSubdomain`, assigned via `subdomainType` on a context; `kairos-ddd:invariant`,
repeatable prose on a class. Both documentation only. An invariant's *enforceable* form stays
where enforcement lives — a SHACL shape in `model/shapes/` or a `DataQualityRule` in the
binding — and the property's own comment says so, so nobody mistakes the prose for a gate.

**Four new shapes and one audit.** Rule 8: a `boundedContext` value must be a declared
`BoundedContext`. Rule 9: at most one `boundedContext` per element — a shared concept is a
Shared Kernel edge on the map, not a second membership. Rule 10: `subdomainType` is closed.
Rule 11: a relationship joins two *different* contexts. What no per-file shape can see is a
Python audit over every file together, `audit_ddd_consistency`, reported by `validate --ddd`:

| Code | Level | Meaning |
|---|---|---|
| `ddd.context-redeclared` | warning | one context IRI declared in several files, labels agree — move it to the strategic file |
| `ddd.context-label-conflict` | error | same IRI, different labels — the reports would render two names for one context |
| `ddd.class-in-two-contexts` | error | two files place one class in different contexts |
| `ddd.tactical-in-strategic-file` | error | class-level predicates in `ddd-contexts-ext.ttl` |

These are validation diagnostics, not compile diagnostics, so they are recorded here and in
`docs/dev/cli-behaviour-notes.md` rather than in `diagnostic-codes.md`, whose catalogue is scanned
from `core/compiler/` (the DD-164 `disposition.*` codes have the same home).

**The per-domain report shows the contexts that domain participates in** — those its overlay
declares or assigns classes to — and the edges touching them, not every context in the hub.
The hub-wide context map is DD-230's job.

### Consequences

A context engineer declares a context once and its label agrees everywhere by construction.
Moving an existing hub over is mechanical: cut the `BoundedContext` and `ContextRelationship`
blocks out of the overlays into the strategic file **together** — a strategic file whose
relationships name contexts still declared only in overlays fails rule 6 on its own, by design,
because the strategic file has to stand alone.

The DDD firewall is unchanged: `compile` still opens exactly one extension file per domain
(`{domain}-gold-ext.ttl`), the leak scan runs over the strategic file too, and nothing here can
alter a contract, a Silver model, a Gold table or an ERD.

Rejected: merging all overlays into every validation graph (tolerant diagram, blind validator —
the hazard above); a reserved overlay name such as `_hub-ddd-ext.ttl` (matches the glob, needs a
special case in the orphan check, and reads as a domain); a SHACL-only design for the cross-file
checks (a per-file shape cannot see a second file); putting `invariant` in the domain ontology
(R1 keeps DDD concerns out of the canonical TTL; the ontology carries meaning, the overlay
carries design).

Amends DD-091: the lifecycle step *optional DDD overlay* now has a strategic and a tactical half;
DD-091's `**Implementation:**` paths are updated to the v5 module layout.
