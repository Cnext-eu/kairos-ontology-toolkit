# DD-214: Sample redaction is opt-in at import; the pre-send scan advises instead of refusing

**Status:** Accepted
**Date:** 2026-09-01
**Affects:** `extract-schema`, `import-source`, `import-flatfile`, `analyse-sources`, `source-privacy`,
`audit-column-coverage`, `suggest-shapes`, kairos-design-source
**Implementation:** `core/extract_schema.py`, `core/import_source.py`, `core/import_flatfile.py`,
`core/source_privacy.py`, `core/column_coverage_audit.py`, `cli/sources.py`, `cli/shared.py`
**Supersedes:** DD-075's unconditional framing, DD-166's refusal, and the condition DD-205's
authorization rested on

### Context

DD-075 established sample masking, DD-166 gated values before they leave the hub, and DD-205
permitted raw values to reach the LLM **on the explicit condition** that committed artifacts stay
redacted -- which is why `.import/raw-samples/` is gitignored while `integration/sources/**` is
committed.

Against real client data the control cost more than it bought:

- A 74-table client bronze profile was refused over **2197 NULLs across 136 columns, with zero
  real values among them** -- a NULL in a PII-named column convicted on the column name alone, with a
  verdict `--fix` could not clear. Worse, the refusal fired mid-write: 77 files created and 76
  modified before it aborted, leaving the hub's source directory partially imported.
- Money, datetime and business-ID columns reached the vocabulary TTL with **zero** sample evidence,
  mislabelled `kind=phone` (issue #680) -- while the real values sat unredacted in the sibling
  `.samples.yaml` in the same directory, so nothing was protected.

Sample values are the evidence binding design reads: they are how an author tells a governed code
list from free text, and how a canonical property and datatype get chosen. Destroying them because a
detector was wrong about the column is a bad trade, and the detector is wrong often -- by design,
since DD-075 chose to accept over-redaction as the cost of never under-redacting.

### Decision

Redaction becomes **opt-in** on every import path: `extract-schema`, `import-source` and
`import-flatfile` all take `--redact-pii`, defaulting to off. `extract-schema`'s released
`--no-redact-pii` (#672) stays as an accepted no-op, since it now asks for the default.

`analyse-sources` keeps its pre-send scan and its paths-and-kinds-only reporting, but **advises
instead of refusing**. Refusing is no longer coherent: a hub that deliberately keeps raw samples
would otherwise be unable to run the command at all.

Both halves are load-bearing and neither alone delivers the behaviour. `extract-schema`'s default is
what stops redaction at the warehouse boundary -- `import-source` cannot recover a value already
tokenized upstream, because the vocabulary's `sampleValues` are derived from `<table>.samples.yaml`
rows. Conversely gating `import-source` is what recovers the *false-positive* damage, since money and
date values already survive `extract-schema`'s per-value pass (which receives `column_types`, so the
issue-302 exemptions apply) and were destroyed later by `sanitize_vocabulary_graph`.

Artifacts always state the policy that actually ran (`policy: none`), and carry **no policy version**
when no policy ran -- recording the version of a policy that did not execute is the same
overstatement DD-075's first amendment exists to prevent.

### Consequences

**Accepted, explicitly.** Committed artifacts under `integration/sources/**` may now contain raw
client PII and enter the client's git history. That is the exact condition DD-205 relied on, which is
why this record supersedes it rather than amending it. Sample values may also reach the configured AI
provider unredacted.

**No automated control remains.** `run_source_privacy` has two call sites in `src/`; `validate` has
no sample-value check (`core/validator.py`'s GDPR scan is *name*-based, over ontology properties);
and no scaffolded workflow runs `import-source`, `import-flatfile`, `analyse-sources` or
`source-privacy`. Nothing will go red. `source-privacy` remains available as a deliberate audit and
`--fix` step.

**Four consequences were not obvious and are handled in code:**

1. *Redaction and its assertions are one unit.* `assert_source_data_private`,
   `sanitize_vocabulary_graph`'s residual raise and `assert_no_unredacted_sample_pii` are
   post-conditions, not independent gates. Skipping the redaction while keeping the assert raises
   `SamplePrivacyError` on the raw values and kills the import.
2. *`source-privacy` needed an acknowledgement path.* It never read `sample_privacy.policy`, so
   opting out would have left it permanently red with no way to say the exposure was intended, and
   the new advisory firing on every run forever. Findings in artifacts that **declare**
   `policy: none` are now reported as acknowledged rather than as failures. Only an explicit
   declaration counts: a missing `sample_privacy` block is *not* consent, since hand-authored and
   pre-policy artifacts have none either.
3. *`--emit-seed` is refused without `--redact-pii`.* Seed CSVs are not gitignored, and the emitted
   copy under `ontology-hub-publish/medallion/dbt/` is explicitly **un**-ignored and packaged into a
   GitHub Release -- so raw rows would leave the repository entirely.
4. *The `" | "` sample delimiter became injectable.* Redaction tokens are delimiter-safe by
   construction (`_component` strips `|`), so this never mattered while every published value was a
   token. Raw client text is not safe: a value containing the separator would split into sample
   values that were never in the source, indistinguishable from real ones, across all four consumers
   that split it. `join_sample_values` now substitutes the separator inside values -- deliberately
   lossy in one character run, versus fabricating data. `enumValues` also gained the
   `distinct_samples` cap that `sampleValues` always had.

**One exposure is recorded rather than fixed.** `suggest-shapes` was protected only by redaction.
`is_pii_column` is *deliberately* weaker than the persistence detector -- DD-075's second amendment
keeps location awareness out of it, and a test pins `is_pii_column("latitude")` False, so that the
redactor and the datatype-blind residual gate cannot disagree. Widening it would break the invariant
it exists to protect. So coordinates and PII embedded in free text can now reach advisory
`Example values:` comments in suggested shapes. `--no-sample-values` suppresses examples entirely.

`audit-column-coverage` is the exception that still redacts unconditionally: its sample value goes to
stdout and `--format json`, landing in terminals, agent transcripts and CI logs -- destinations no
hub controls. It redacts per-value rather than blanking, so the issue-302 exemptions keep money,
dates and identifiers intact and only a genuine detection becomes a token.

### Out of scope

`import-source`'s mid-write non-atomicity is a separate latent defect. Turning redaction off removes
the common trigger but not the defect: any future raising gate can still leave a half-imported hub.
