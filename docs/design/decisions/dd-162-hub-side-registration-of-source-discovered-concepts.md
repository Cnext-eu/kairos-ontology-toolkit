# DD-162: Hub-side registration of source-discovered concepts

**Status:** Accepted

**Date:** 2026-08-15

**Affects:** `src/kairos_ontology/core/registered_concepts.py` (new),
`src/kairos_ontology/core/conformance_artifact.py`,
`src/kairos_ontology/core/design_landscape.py`,
`src/kairos_ontology/core/hub_inspection.py`,
`src/kairos_ontology/core/next_actions.py`, `src/kairos_ontology/cli/sources.py`,
`kairos-design-source` skill

**Implementation:** `register-concept`

### Context

Issue #505 reported three mechanisms that could stop an ontology domain being modeled. Two
turned out not to exist as described:

- The archetype tier `not_applicable` (Layer A) is **not in the published tier enum at all** —
  `VALID_TIERS = ("required", "recommended", "optional")`. Ref-models #82 was closed for exactly
  that reason. Layer A is moot.
- The `not-applicable` *outcome* (Layer C) is real and is handled by issue #507: source-evidence
  aware judgments, `core/conformance_evidence.py`.

The third (Layer B) is real and had no answer. **A business concept that exists in the source
data but has no entry in the archetype catalog is invisible to the entire system.** Discovery
only ever iterates the catalog, so such a concept cannot be judged, cannot carry a
`likely_domains` tag, never reaches `design-landscape`, and never becomes an authored domain.
On the CLdN hub roughly ten BI-relevant concepts sat in that hole: planning zones, tariff
scales, empty-unit lifecycle, distance/toll matrix, order source attribution.

DD-160 surfaced the *domain*-level version of this gap (`unassigned_source_tables`, and the
`not-modeled`/`deferred` statuses). It has no concept-level counterpart, and no way to record
that a specific concept belongs.

### Decision

Add hub-side concept registration, answering the four questions #505 left open:

1. **Human confirmation is required.** A registration records `decided_by`; an `ai`/`autopilot`
   registration with `needs_confirmation: true` or no `confidence` is an open question and
   blocks `compile`/`validate` through the existing `check_discovery_gate`, exactly like an
   unresolved archetype judgment (DD-148). Adding a concept the blueprint deliberately omitted
   is a strictly *larger* authority than judging one it included, so it cannot be gated more
   weakly.
2. **Persisted in its own artifact**, `integration/discovery/registered-concepts.yaml`, with its
   own `schema_version`, and mirrored by `discovery-conformance build` into a **sibling**
   `registered_concepts` list in the conformance artifact. Deliberately *not* merged into
   `core_concepts`: `validate_artifact`'s coverage/identity checks (#308) require every
   `core_concepts` entry to be a real concept of the resolved archetype's catalog, and
   `concept_set_hash` staleness would fire on every registration. **Registering a concept must
   not make the archetype look wrong.** A URI present in both is an error.
3. **The archetype schema is not extended.** Registration is hub-side only; the reference-models
   repo is untouched. The archetype catalog stays a stable shared contract across every hub that
   uses it, and adding a concept to one hub never requires a cross-repo release. A URI already in
   the catalog is *rejected* for registration — it belongs in `core_concepts` with a real
   discovery judgment, and registering it would route it around the coverage checks.
4. **Counted separately, never folded into the archetype total**, so archetype-conformance
   percentages stay comparable across hubs. Registered concepts are excluded from the artifact's
   `scorecard` for the same reason #507 kept `by_evidence` out of it: `validate_artifact`
   recomputes that scorecard and compares it for equality against the stored one.

Registered concepts always carry tier `optional`: the source data argued them into scope, no
blueprint recommended them, and any other tier would misrepresent an obligation nobody made.
`--source-evidence` and `--rationale` are both mandatory — registration is a claim about source
data, and an unevidenced or unexplained claim is a guess the next reader cannot check.

`design_landscape` synthesizes a class record for each registered concept. This is required, not
cosmetic: the report's join skips any URI the activated accelerator modules do not declare, and
a registered concept is outside those modules by construction — without it, the concept would be
silently absent from the very backlog it exists to appear in.

### Rationale

The alternatives each fail on one of the four questions. Extending the archetype schema makes
one hub's business concept everyone's contract change. Writing registrations into `core_concepts`
makes the archetype's own coverage and staleness checks fail on correct hubs. Skipping human
confirmation grants AI a larger authority for inventing a concept than DD-148 grants it for
judging one. Folding registrations into the scorecard makes conformance percentages
incomparable across hubs, which is the number the scorecard exists to provide.

### Consequences

- A concept outside the archetype catalog can be recorded, gated, surfaced in
  `design-landscape`, and routed by `kairos-ontology next` (`model-registered-concept`).
- Registration records that a concept *belongs* and names its evidence. It does not model or
  bind it: authoring the class stays a `kairos-design-domain` decision.
- The conformance artifact gains an optional `registered_concepts` key. Absent in every existing
  artifact, and absence is indistinguishable from empty, so no artifact on disk is invalidated.
- `register-concept` is gated to `kairos-design-source`, not `kairos-design-discovery`: the
  registration is proposed from `analyse-sources`' own unassigned-table output.
