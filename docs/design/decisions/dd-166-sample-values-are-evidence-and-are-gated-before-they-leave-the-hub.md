# DD-166: Sample values are evidence, and are gated before they leave the hub

**Status:** Accepted
**Date:** 2026-08-16
**Affects:** `analyse-sources`, `propose-alignment`, `import-flatfile`, `import-source`
**Implementation:** `core/analyse_sources.py`, `core/import_flatfile.py`, `core/import_source.py`,
`core/propose_alignment.py`, `cli/sources.py`

### Context

`analyse-sources` sends sample values from every column to a third-party LLM. The module
contained no privacy check: redaction happened earlier, at import and via
`source-privacy`, and the send step relied on that ordering. Ordering is not a control.

Separately, capture was five values per column, and the alignment step showed three. That
is too few to tell a governed code list from free text, which is the judgement alignment
exists to make.

### Decision

`analyse-sources` runs the privacy scan and refuses on any finding, reporting paths and
kinds only, never the offending value.

Capture rises to twenty **distinct** values. Three separate caps had to move, each of which
made the previous fix a no-op: four hardcoded five-value slices in `import_source` that took
the first five rather than five distinct; a single `DEFAULT_SAMPLE_SIZE` in `import_flatfile`
governing both column values and whole sample rows; and finally the real one — column values
were stripped from the schema YAML on write, with the TTL deriving its values from the five
sample rows instead.

That last point is the substantive change. Stripping the values *was* the privacy control:
they had never been sanitized. They now pass through the same `redact_sample_rows` detector
as rows — reused rather than reimplemented, each value becoming a one-cell row — and are
published. Redaction collapses distinct values to identical tokens, so they are deduped
again: a PII column contributes one masked token, not twenty copies.

Row samples stay at five and stay out of the schema YAML. A row correlates every column of
one real record; a column value does not. Conflating the two under one constant is what hid
the distinction.

Affinity keeps three values (`MAX_AFFINITY_SAMPLES`): it classifies a table into a domain and
needs a type hint, not a distribution. Alignment gets twenty. The asymmetry is asserted in a
test so it cannot drift.

### Consequences

On 75 real tables, 34% of 3,410 columns now carry more than the old cap and 604 hold the full
twenty, with `source-privacy` clean across 227 artifacts. Note for reviewers: legal entity
names (`companies.name`) are correctly *not* PII and are now sent twenty at a time. That is
commercial confidentiality, not GDPR, and is a separate control if the business wants one.
