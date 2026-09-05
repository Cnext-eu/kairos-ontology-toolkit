# DD-196: Archived reference-model snapshots are excluded from resolution unconditionally

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `analyse_sources.resolve_reference_models` (and every caller, incl. `coverage_report.run_coverage_report`)
**Issue:** #566 (supersedes kairos-ontology-referencemodels#108, closed as not a referencemodels defect)

### Context

`coverage-report` produced a resolver warning listing 53 property-domain
assertions across 14 modules that "could not be attached to any class" —
filed initially against the reference-models repo (#108) under the
assumption the live `.ttl` files were missing `owl:imports`. That
assumption was wrong: every one of the 53 traces to a file under
`derived-ontologies/<vendor>/archive/<old-version>/...`, never `current/`.
The live files already declare the correct imports (added by
referencemodels commit `a449ab2`, v1.32.0); the archived snapshots
legitimately predate that fix, by that repo's own documented
archive-before-fix convention. Because an archived file shares its live
module's permanent IRI, `_warn_unattached_property_domains`'s bucketing by
module lumped the resolved, historical defect onto the live module's label.

`resolve_reference_models` already accepted an `exclude_patterns` parameter
for exactly this class of exclusion, but no default existed and
`run_coverage_report` never supplied one — so the coverage-report path
walked `archive/**` unconditionally. The reference-models repo's own
equivalent structural check (`scripts/validate_structure.py` check 10)
already skips any path with an `archive` segment, unconditionally, for the
identical reason — this toolkit's resolver was the one place that hadn't
caught up.

### Decision

`resolve_reference_models` now excludes any TTL whose path (relative to
the resolution root) contains an `archive` segment, unconditionally —
before caller-supplied `exclude_patterns` even run, and with no way to opt
back in. Matched on a literal path segment (`"archive" in
path.relative_to(root).parts`), not a glob, so it is robust regardless of
vendor folder layout.

### Consequences

Every caller of `resolve_reference_models` (`coverage_report.py` and any
future caller) is fixed at once, not just the one call site that surfaced
the bug. An archived TTL can never again masquerade as evidence of a live
defect. `kairos-ontology-referencemodels#108` closes as not a defect in
that repo.
