# DD-075: Sample-grounded mapping evidence (masked example values + transform compatibility)

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `src/kairos_ontology/core/_samples.py`,
`src/kairos_ontology/core/source_privacy.py`,
`src/kairos_ontology/core/import_flatfile.py`,
`src/kairos_ontology/core/extract_schema.py`,
`src/kairos_ontology/core/import_source.py`,
`src/kairos_ontology/core/propose_alignment.py`, `src/kairos_ontology/cli/main.py`,
`src/kairos_ontology/validator.py`, `.github/skills/kairos-design-mapping/SKILL.md`
**Implementation:** `_samples.py` (`is_pii_column`, `value_is_pii_shaped`,
`mask_value`, `example_values`, opaque persistence redaction);
`source-privacy [--fix]`; `ColumnAlignment.example_values` /
`ColumnAlignment.transform_compat`; `_parses_as()` / `_transform_compat_note()`;
`run_propose_alignment(include_sample_values=True)`; `--no-sample-values` CLI flag.

### Context

Source **sample values** (5 rows captured at import, stored as bronze
`kairos-bronze:sampleValues`) were the strongest available evidence for a
column→property mapping but were never surfaced to the mapper. They were used
only for enum/format enrichment, affinity analysis, and alignment prompts —
never presented as decision evidence during `kairos-design-mapping`, and never
used to sanity-check a proposed `CAST(...)` transform.

### Decision

- **`example_values` is on by default** in `propose-alignment` output (the user
  directive: "too valuable to be opt-in"). The mapping skill's Phase 2 table now
  carries a **mandatory** masked Examples column.
- **PII is always masked.** A shared policy module (`_samples.py`) is the single
  source of truth: a column is PII if its name keyword-matches, its mapped
  property keyword-matches, it is `gdpr_protected`, or its values are PII-shaped
  (email/IBAN/phone/long-digit regex). PII values are masked length-preservingly
  (`jo***@***.com`) and never enumerated. `validator.PII_KEYWORDS` now imports
  from `_samples` to avoid drift.
- **Persisted samples use opaque typed redaction, not display masking.** Before
  source YAML or Bronze RDF is written, a detected value is replaced as a whole
  with a token such as
  `<redacted kind=email source=contacts.email datatype=varchar(255)>`. The token
  retains source context but no original characters and no hash. Detection is
  recursive for row/JSON values and idempotent for existing tokens.
- **Supported residual findings block publication.** Source writers sanitize before
  persistence and verify that no supported raw pattern remains. Existing artifacts
  are checked or deterministically rewritten with `source-privacy --fix`; reports
  identify only path/table/column/kind/count.
- **`transform_compat`** is an advisory note (`"N/M sample values are non-numeric
  — CAST may NULL/fail"`) emitted only for numeric/bool CAST targets. It never
  raises confidence, never auto-sets review, and never blocks.
- **No `schema_version` bump.** Both fields are additive and emitted only when
  populated, so existing v2 alignment files and the freshness gate are unaffected.

### Rationale

Real values disambiguate mappings far better than names/types alone and let the
modeler catch encoding traps before writing SQL. Forcing the feature on (vs.
opt-in) maximises that value; masking PII unconditionally keeps the committed
artifacts safe. Persist-time opaque redaction closes the earlier gap where raw
sample values could enter version control before display masking.
Keeping `transform_compat` advisory respects the toolkit's warning-tolerant,
human-confirmed mapping flow.

### Consequences

- `propose-alignment` output now contains masked example values by default;
  `--no-sample-values` / `include_sample_values=False` suppresses them.
- The Examples column is for transient display only — skills must never copy raw
  values into committed TTL/comments/session logs.
- New source artifacts persist supported detected patterns only as opaque,
  source-aware tokens. Non-PII examples remain available as semantic evidence.
- Existing generated YAML and vocabulary TTL can be remediated with the
  deterministic, value-free `source-privacy --fix` workflow.
- Detection is deliberately bounded to supported patterns and PII-related column
  names; this policy does not claim universal discovery of sensitive information.

### Amendment (2026-08-14): the bound must be stated in the output, not only here

The consequence above — "does not claim universal discovery" — was recorded in this document and **not** in
the command. `source-privacy` printed `✅ Source sample artifacts are privacy-safe for supported patterns.`,
which names no patterns, so a reader could not tell which ones. The concrete case that surfaced it (#415): a
road-haulage export where three address components were correctly redacted while `CoordinateLatitude` /
`CoordinateLongitude` persisted at six decimal places (~0.1 m) in the same row — the address recoverable by
reverse-geocoding the two columns beside it, under an unqualified all-clear.

**Decision.** A clean result now states its coverage: the number of artifacts scanned, the redaction kinds
actually looked for, and the known gap. The kind list is **derived from the detectors** (`DETECTED_PII_KINDS`,
built from the same table `_kind_from_name` iterates) rather than maintained beside them, because a
hand-written coverage list would eventually claim detection the code does not have — which is the failure this
amendment exists to prevent, one level up.

**The detector itself is deliberately deferred** to #423, not skipped. Three separate mechanisms make the
obvious implementations wrong, and each is recorded there: blanket-redacting decimals would regress #302
(whose exemption is value-shape, not datatype — gating on datatype was explicitly rejected); a range-only rule
breaks existing fixtures, since `3.14159265358979` and `0.123456789` are both valid latitudes; and precision
reduction cannot work through `is_redaction_token`, the sole idempotence mechanism, without forcing a 2-decimal
threshold — roughly 1.1 km, which still identifies a rural facility. A privacy gate must be binary; "coarser"
is not "safe".

Stating the bound is therefore the honest interim: the guarantee is unchanged, but it is no longer
overstated at the point of use.

### Second amendment (2026-08-15): the deferred coordinate detector ships (#423)

The interim above ends: the persistence path now detects geographic coordinates by **pairing the column
name with the value shape**, which is what the three recorded wrong-fix mechanisms all lacked. The detector
never touches declared datatypes (the #302 exemption stays value-shape; the residual gate receives no
`column_types`, so a datatype-keyed rule would make the redactor and the gate disagree — the exact failure
`test_redacted_rows_pass_the_persistence_gate` pins), and it is binary: a matched value is replaced with an
opaque `<redacted kind=location …>` token, never coarsened.

**Shipped.**
- **Tokens** (full-word matches via `_name_tokens` only, never substrings): `latitude` → [-90, 90];
  `longitude`, `lng` → [-180, 180]; `coordinate(s)` or multiple location tokens → the union range
  [-180, 180], because a generic coordinate column can hold either axis.
- **Value shape**: a numeric literal whose **string form carries a fractional part**
  (`_NUMERIC_LITERAL_RE`'s fraction group — not `float.is_integer()`, which would exempt real coordinates
  like `51.0`) inside the applicable range; or a comma-separated `"lat,lon"` pair whose two parts both
  satisfy that rule within the union range (a common single-column export format that would otherwise
  silently escape).
- **Containment**: the check lives in `detect_sample_pii_kind` (persistence path), between the name-keyword
  and nested/text checks — name kinds keep priority (`health_latitude` stays `health`) and shaped values in
  location columns are still caught. It is **not** in `_kind_from_name`, so `is_pii_column` and the
  display/suggestion paths (`propose_alignment`, `suggest_shapes`) gain no location awareness; tests pin
  `is_pii_column("latitude")` False. Nested `{"latitude": 51.33}` values are detected because
  `_kind_from_nested`'s dict branch now routes through `detect_sample_pii_kind`, which also makes the
  redactor and every residual gate provably share one classifier.
- `"location"` enters `DETECTED_PII_KINDS` derived from the token table (`_LOCATION_TOKEN_RANGES`), never
  hand-appended — the same discipline the first amendment established for the coverage report.

**Deferred.**
- The abbreviations `lat`, `lon`, `geo`: as bare tokens they false-positive on `latency`/`geo_score`-class
  names once range-filtered values appear beside them; they move to the sibling-address follow-on of #423
  (which can use row context to disambiguate).
- WKT geometries (`POINT(4.12 51.33)`) and other structured spatial encodings.

`SAMPLE_PRIVACY_VERSION` bumps "1" → "2" as **inert bookkeeping** — nothing reads it back and no migration
keys on it; it only records which policy generated an artifact. Existing hubs therefore keep persisted
coordinates until `source-privacy --fix` is run once.
