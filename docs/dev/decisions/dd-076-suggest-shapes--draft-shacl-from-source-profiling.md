# DD-076: `suggest-shapes` — draft SHACL from source profiling

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `src/kairos_ontology/suggest_shapes.py` (new),
`src/kairos_ontology/cli/main.py`, `.github/skills/kairos-execute-validate/SKILL.md`,
`.github/skills/kairos-help/SKILL.md`
**Implementation:** `suggest_shapes.build_shapes_graph()` / `suggest_shapes()`;
`suggest-shapes` CLI command; entry in `_SKILL_COVERED_COMMANDS`.

### Context

SHACL shapes were entirely hand-written — there was no generator. Source
profiling metadata (datatype, nullability, `kairos-bronze:distinctCount`,
samples) already encodes most of a basic shape, so the blank-page cost was
avoidable.

### Decision

Add a deterministic `suggest-shapes` command that builds a **DRAFT** SHACL graph
(via rdflib, never string concatenation) from a bronze vocabulary:
- `sh:datatype` always; `sh:pattern` only when one `FORMAT_PATTERNS` entry
  matches all samples; `sh:minCount 1` only from `nullable:false`; `sh:in` only
  when a reliable `distinctCount` ≤ `--enum-distinct-max` fully matches the
  sampled distinct set **and the column is not PII**. No sample-derived
  min/max ranges.
- Output defaults to `output/shapes-draft/<name>.ttl` — **outside**
  `model/shapes/` and with a `.ttl` (not `.shacl.ttl`) suffix — so
  `validator.py`'s recursive `**/*.shacl.ttl` glob does **not** auto-load drafts.
- Refuses to overwrite without `--force`; reuses the DD-075 `_samples` masking
  policy (PII never enumerated, masked in comments).

### Rationale

A reviewed-draft workflow (generate → curate → move into `model/shapes/`) gives
leverage without letting machine guesses silently become enforced constraints.
Writing outside the loaded shapes dir is the safety mechanism that makes
"draft" real. Gating `sh:in`/`sh:minCount` on reliable metadata (not raw
5-row samples) avoids over-constraining.

### Consequences

- New skill-gated CLI command (owned by `kairos-execute-validate`); emits the
  soft skill-gate warning unless `KAIROS_SKILL_CONTEXT=1`.
- Drafts are advisory and require manual promotion into `model/shapes/`; nothing
  is enforced until a human moves and renames the file.
- `kairos-bronze:distinctCount` is the reliability signal for enums; absent it,
  the command emits only an advisory "possible enum (unverified)" comment.
  *(Amended 2026-08-15, see below: distinctCount alone is NOT the signal — it
  must carry `distinctScope="table"`.)*

### Amendment (2026-08-15): `sh:in` requires full-table distinct evidence (#424, DD-156)

"distinctCount is the reliability signal for enums" is falsified for windowed
profiling. On a real hub, 82% of 217 generated `sh:in` enums were single-value
and several were provably wrong (`booking_status` → only `"TO_REQUEST"` of 5
real values): the flatfile path counted distincts inside an n≤1000 (and
sample-persisted n=5) window, and `suggest-shapes` treated that as population
truth. DD-156 gives the graph the evidence to tell the difference; this
amendment makes `suggest-shapes` read it:

- **distinctCount is trusted for `sh:in` only when the table asserts
  `kairos-bronze:distinctScope="table"`.** Sample-scoped evidence
  (`distinctScope="sample"`) and legacy evidence (scope absent — vocabulary
  predates DD-156) produce **advisory comments only**, never a constraint:
  - saturated window (`distinctCount >= rowsSampled`): the evidence cannot
    distinguish an enum from an open value set;
  - window below the enum floor (`rowsSampled < DEFAULT_ENUM_MIN_ROWS` = 100):
    re-import with a larger `--max-rows` or profile the warehouse table;
  - unsaturated ≥100-row window with `distinctCount ≤ --enum-distinct-max`:
    "possible enum … not verified against full data";
  - legacy (scope absent, distinctCount present): "regenerate the source
    vocabulary with import-source".
- **Temporal (`xsd:date`/`dateTime`/`time`), decimal/float/double, boolean, and
  UUID columns are never enumerated**, regardless of scope. Boolean `sh:in`
  adds nothing over `sh:datatype` and brittle lexical forms cause false
  violations; UUID detection uses `kairos-bronze:formatHint == "uuid"` OR the
  sample-derived format pattern — load-bearing because SQL Server
  `uniqueidentifier` maps to `xsd:string`. Integer stays eligible (integer
  status codes are legitimate enums). These columns get no enum comment either
  (`sh:datatype` already carries the signal).
- **Floor rule, precedence pinned:** when the table's true cardinality
  (`kairos-bronze:rowCount`) is KNOWN, `sh:in` additionally requires
  `rowCount >= DEFAULT_ENUM_MIN_ROWS` (100, shared with `enrich_vocabulary`).
  When `rowCount` is absent but `distinctScope="table"` is explicitly asserted
  (warehouse-shaped evidence), the floor does NOT apply — the scope assertion
  itself is the trust anchor.
- Unchanged: PII columns are never enumerated; `sh:in` still requires
  `0 < distinctCount ≤ --enum-distinct-max` and the ≤5 persisted samples to
  cover the full distinct set (the values come from the samples).

Consequence for existing hubs: legacy vocabularies produce advisories instead
of enums until regenerated (`import-flatfile` + `import-source`); capped
flatfile imports never produce `sh:in`. The suggestions this suppresses are
exactly the ones the old rule fabricated.
