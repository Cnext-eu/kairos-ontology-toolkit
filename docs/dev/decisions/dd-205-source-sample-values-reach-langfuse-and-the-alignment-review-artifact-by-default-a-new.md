# DD-205: Source sample values reach Langfuse and the alignment review artifact by default; a new raw-sample channel feeds the alignment prompt itself

**Status:** Accepted
**Date:** 2026-08-20
**Affects:** `_send_samples`/`_MASKED` (`core/tracing.py`); `example_values` PII gate (`core/propose_alignment.py`); new `core/raw_samples.py`; writer hooks in `core/import_source.py`/`core/import_flatfile.py`; reader/overlay + cache key in `core/propose_alignment.py`; `kairos-design-domain`/`kairos-design-mapping` SKILL.md Gates (toolkit + scaffold copies)
**Issue:** #562 (Problems 3 and 4)
**Authorization:** explicit, maintainer-directed default flips — including unmasking real client sample values to the configured LLM provider and to Langfuse by default — requested and reconfirmed after this session's security review flagged the raw-sample channel as a data-exfiltration-shaped pattern. Recorded here plainly rather than softened, per that review: this is a deliberate privacy tradeoff the maintainer chose, not an oversight.

### Context

Three independent places along the alignment pipeline redacted or masked
real sample values by default, each added at a different time for a
locally-reasonable reason, with the cumulative effect of starving the
alignment LLM call, the human reviewer, and the Langfuse trace alike of the
signal that most helps diagnose a bad mapping:

1. **Langfuse tracing** (`core/tracing.py`, DD-184) masked the `| samples:
   ...` block in every traced prompt/response unless
   `KAIROS_LANGFUSE_SEND_SAMPLES=1` was set.
2. **`example_values`** (`core/propose_alignment.py`, DD-075) — a field
   written into `*-alignment.yaml` *after* the LLM already responded, for a
   human reviewer or a design skill to read — always masked PII-shaped
   values via `is_pii_column`, with no toggle.
3. **The alignment prompt itself never saw an un-redacted value at all.**
   `_format_source_columns` reads sample values from the committed
   `<system>.vocabulary.ttl`'s `sampleValues` literal, which
   `import_source.py`/`import_flatfile.py` permanently redact once, at
   import time (`source_privacy.sanitize_source_data` /
   `redact_sample_rows`). There is only one on-disk representation of a
   committed sample value, and it is redacted before the LLM call — no
   toggle could un-redact it after the fact, because the raw value was
   never persisted anywhere the prompt-building code could read it back
   from.

Issue #562 asked, explicitly and after a maintainer authorization exchange,
for all three defaults to flip: an operator can still opt out of any of
them, but none should require an operator to *find* the toggle first.

### Decision

**Problem 3 (Langfuse):** `_send_samples()` in `core/tracing.py` flips to
default-on; `KAIROS_LANGFUSE_SEND_SAMPLES=0` masks the sample block instead.
Tracing itself is still off unless a hub configures Langfuse credentials at
all — this only changes what a hub that has already opted into tracing also
sends.

**Problem 4, part 1 (`example_values`):** the `is_pii_column` masking gate
in `propose_alignment.py` is itself now conditioned on the *same* new
env var introduced for part 2 below (`KAIROS_ALIGNMENT_SEND_RAW_SAMPLES`,
default on) — off restores the original always-masked behavior exactly.

**Problem 4, part 2 (the actual LLM prompt) — the larger feature, built to
the full scope authorized rather than only the narrower `example_values`
fix:** a new module, `core/raw_samples.py`, adds a second, gitignored
on-disk channel (`.import/raw-samples/<system>.json`, alongside the
already-gitignored `.import/businessdiscovery/` convention) that captures
sample values *before* redaction, at the same import step that has always
redacted the committed vocabulary/source-dir artifacts. Writer hooks sit in
`import_source.py::run_import_source` and
`import_flatfile.py::run_import_flatfile`, at the one choke point each
already had where the pre-redaction data was still in scope. `propose_alignment.py`
overlays these raw values onto a table's `columns` list — read via
`get_raw_columns` — immediately after `get_columns()`, before the per-table
cache key is computed; because the cache key already hashes
`columns[].samples`, toggling the setting invalidates the cache key as a
consequence of *where* the overlay runs, not a separate fix. `KAIROS_ALIGNMENT_SEND_RAW_SAMPLES`
(default on) governs the whole channel end to end: off means the writer
does not create the file at all — not merely "the reader will ignore it" —
so an operator who wants no raw PII ever written to local disk gets that by
turning the setting off *before* importing.

The committed vocabulary TTL / source-dir samples files remain permanently
redacted regardless of this setting; only the new sidecar and, downstream
of it, the LLM prompt and `example_values`, are affected.

Both `kairos-design-domain` and `kairos-design-mapping` SKILL.md Gates
(toolkit `.github/skills/` copies and their scaffold-shipped twins) gain a
sentence: `example_values` can no longer be trusted as pre-redacted by
default, and the skill itself must apply masked/redacted/synthetic
treatment before such a value reaches any generated artifact or
conversation — the trust boundary these Gates previously assumed moved.

### Consequences

Client sample values now reach the configured LLM provider (via the raw-
samples overlay) and, if a hub has Langfuse configured, a third-party
Langfuse host, by default — this is the deliberate tradeoff named in
**Authorization** above, not a side effect. `example_values` in a freshly
generated `*-alignment.yaml` can carry real names/emails/identifiers; any
consumer of that artifact (human or skill) must treat it accordingly.
Turning any of the three settings off independently restores exactly the
prior behavior for that one channel. A hub that never sets
`KAIROS_ALIGNMENT_SEND_RAW_SAMPLES` to anything gets the new default
silently the moment it upgrades and re-imports — there is no migration
warning, matching how every other default-value change in this toolkit
already behaves.
