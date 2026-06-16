# Slice 6 — Change management & contract versioning

**Status:** ✅ done · **Depends on:** 2, 4 · **Gates:** 8

## Goal

Make new systems / new fields safe: they expand silver, never silently mutate it.
Extends the minimal contract semantics defined in Slice 0B.

## Scope

- **`source-delta-report`** — compare a new/changed source system against
  approved claims + mappings; classify each delta (per methodology §13.2):
  maps-to-existing-class, new-claim-candidate, new-column→property, passthrough,
  new-reference-list, new-relationship, semantic-conflict, changed key/type/grain.
  Emit an impact report (expected silver table/column/FK additions, breaking
  changes, required approvals).
- **Contract version policy** — silver/gold contract metadata + version rules
  (per methodology §13.5): additive → minor, changed meaning/type/key/grain →
  major, mapping-only → patch. Backward-compat tactics (additive columns,
  deprecation metadata, compatibility views, aliases, deprecate-before-remove).

## Affected modules

`source_coverage.py` / new `source_delta.py`, `claim_registry.py`
(`silver_impact` + contract fields), silver/gold projectors (version metadata),
`cli/main.py`.

## Tests

- [x] delta classification across all §13.2 delta types
- [x] impact report flags breaking vs additive correctly
- [x] version bump hints match the change taxonomy

## Acceptance criteria

- [x] A new source produces an impact report before projection changes merge.
- [x] Breaking changes are distinguishable from additive ones.
- [x] version + CHANGELOG + ruff + tests.

## Risks / notes

- Invariant to enforce: "new evidence may expand silver, but must not silently
  mutate existing silver."

## Delivered (2026-06-16)

Slice 6 landed one **advisory**, deterministic, AI-free CLI command plus a registry
contract-version anchor (DD-EL-8), operationalizing methodology §13.

### `source-delta-report`

Compares a source system's bronze vocabulary against the approved Claim Registry +
SKOS mappings (plus optional affinity hints and an optional baseline vocabulary diff),
classifies each candidate delta (§13.2), emits a markdown impact report (§13.4), and
suggests a silver/gold contract version bump (§13.5) with backward-compatibility
tactics (§13.6). It is **exempt from the skill soft-gate** like `import-tmdl`,
`coverage-report`, `pbi-source-fit-gap`, and `tmdl-to-gold-ext`.

**Options:**

| Option | Meaning |
|---|---|
| `--system TEXT` (required) | bronze vocabulary stem to evaluate |
| `--sources PATH` | sources directory |
| `--mappings PATH` | SKOS mappings directory |
| `--claims-dir PATH` | claim registry directory |
| `--analysis-dir PATH` | optional affinity hints |
| `--baseline PATH` | optional prior vocabulary file/dir for change detection |
| `--domain TEXT` (repeatable) | optional; limits approved-claim context |
| `--output PATH` | optional; else stdout |
| `--fail-on-breaking` | flag; exit non-zero when any breaking delta is found (CI hook) |

**Delta taxonomy → impact → version bump:**

| Delta type | Impact class | Version bump |
|---|---|---|
| `maps-to-existing-class` | mapping-only | patch |
| `new-column-to-property` | mapping-only | patch |
| `new-claim-candidate` | additive | minor |
| `passthrough-candidate` | additive | minor |
| `new-reference-list` | additive | minor |
| `new-relationship` | additive | minor |
| `changed-type` (backward-compatible widening, e.g. `int→bigint`, `nvarchar(50)→nvarchar(100)`) | additive | minor |
| `semantic-conflict` | breaking | major |
| `changed-type` (non-widening) | breaking | major |
| `changed-key` | breaking | major |
| `changed-grain` | breaking | major |
| `removed-column` | breaking | major |

Suggested-bump precedence: any breaking → **major**, else any additive → **minor**,
else any mapping-only → **patch**, else **none**.

### Registry `contract:` block

`ClaimRegistry` gains an optional top-level block recording the current silver/gold
contract versions:

```yaml
contract:
  silver_version: "1.2.0"
  gold_version: "1.0.0"
```

Both keys are optional; the block is omitted entirely when unset (byte-stable for
registries without it) and preserved across regeneration merges. `source-delta-report`
reads this block and suggests the next version.

### Scope note (DD-EL-8)

Projector (silver/gold) version-metadata **emission is deferred** for this slice — it
is not in the acceptance criteria and would risk destabilizing the projection test
suite. The contract version lives in the registry `contract:` block and is
surfaced/suggested by `source-delta-report`; emitting it into projector output is
future work.
