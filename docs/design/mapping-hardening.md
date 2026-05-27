# Plan: Structured Source-to-Domain Mapping Skill (Mapping Hardening)

## Problem Statement

The current mapping workflow is unstructured and prone to "hallucination":
- Copilot guesses column-to-property mappings without confirmation
- No checkpoints or validation gates before writing mapping TTL files
- No session persistence or decision audit trail
- No systematic table-by-table walkthrough with the user
- The `kairos-ontology-mapping-report` skill only *generates reports* — it doesn't *guide the creation* of mappings

This contrasts sharply with `kairos-ontology-modeling` which has:
- Hard gates (no TTL without confirmed naming)
- Session files with decision records
- Source-grounded proposals (must read bronze vocab first)
- One domain per turn
- Explicit user confirmation at every step

## Challenge / Critique

### ✅ Valid points (keep as-is)
1. The problem is real — mapping hallucination is the #1 quality issue
2. Session file prerequisite is essential for audit trail
3. Phased workflow (scope → table alignment → column mapping → validate) is sound
4. Confidence levels and "out of scope" as valid answer are good UX
5. Relationship table showing skill pipeline flow is clear

### ⚠️ Issues to address

| # | Issue | Impact | Fix |
|---|-------|--------|-----|
| 1 | **"One source system per turn" is too strict** | Prevents batch kickoff of simple 1-table sources; user must wait N turns for N sources | Change to "one source per **session**" — allow multiple tables within one source per turn, but never mix source systems |
| 2 | **Phase 2 presents ALL columns at once** | For wide tables (50+ columns) this floods the user with an unreadable wall | Add chunking: present columns in groups of 10–15, grouped by data type or prefix similarity |
| 3 | **No "auto-approve high confidence" mode** | Forces user to confirm every obvious mapping (e.g. `weight` → `weight`) even at 100% confidence | Add a fast-track rule: if ALL of these are true → auto-approve: exact name match, same data type, High confidence. Still show them but as "auto-approved" |
| 4 | **Session file location** — `.sessions-mapping/` is a new directory | Proliferates session dirs (already have `-modeling` and `-projection`) | Reuse `.sessions-mapping/` but ensure `init`/`new-repo` commands create it |
| 5 | **Missing: transform vocabulary** | The proposal shows `CASE WHEN > 0` but doesn't define what transform expressions are valid | Define supported transforms: `source.{col}` (passthrough), `CAST(...)`, `CASE WHEN`, `COALESCE`, `UPPER/LOWER/TRIM`, `CONCAT`. Reference kairos-map: vocabulary |
| 6 | **Todo #6 "Delete ad-hoc mappings"** is hub-specific | Does not belong in a toolkit feature plan — it's an action for a specific hub | Remove from implementation todos |
| 7 | **No mention of mapping types** | The proposal only shows `skos:exactMatch` but the toolkit supports `exactMatch`, `closeMatch`, `broadMatch`, `narrowMatch`, `relatedMatch` with different semantics | Include match type guidance: when to use each, and how it affects dbt generation |
| 8 | **copilot-instructions.md update scope** | Proposal says "add routing entry + mapping prerequisite note" — prerequisite note is unnecessary (pre-flight is now in projection skill) | Only add routing entry, no prerequisite callout |

### 🔧 Improvements to incorporate

1. **Match type decision tree** — Add to Phase 2:
   - Exact name + same type → `skos:exactMatch`
   - Similar name, needs transform → `skos:closeMatch` + `kairos-map:transform`
   - Source column covers broader concept → `skos:broadMatch`
   - Source column is subset → `skos:narrowMatch`

2. **Unmapped column classification** — Don't just say "skipped". Classify as:
   - `operational` (audit cols, ETL metadata)
   - `deprecated` (known dead columns)
   - `out-of-scope` (valid data, but not in domain model)
   - `gap` (should be in domain model → feeds back to modeling skill)

3. **Coverage threshold gate** — After Phase 3, if domain property coverage < 50%, warn and suggest reviewing the domain ontology (maybe properties are missing).

## Revised Implementation Todos

1. **Create the skill file** — `.github/skills/kairos-ontology-mapping/SKILL.md`
2. **Copy to scaffold** — `src/kairos_ontology/scaffold/skills/kairos-ontology-mapping/SKILL.md`
3. **Update copilot-instructions.md** — add routing entry only
4. **Add `.sessions-mapping/` to init/new-repo** — in CLI `main.py` directory lists
5. **Add `.sessions-mapping/` to .gitignore scaffold** — keep session files out of commits
6. **Run tests** — verify packaging tests pass

## Key Design Principles (revised)

- **Never guess** — every mapping must cite source evidence (column name, data type)
- **Confidence levels** — High/Medium/Low, with auto-approve for High + exact match
- **User drives decisions** — Copilot proposes, user confirms (except auto-approved)
- **Audit trail** — session file records every decision for traceability
- **Chunked presentation** — max 15 columns per confirmation block
- **Incremental** — map one table at a time, validate, then proceed
- **Out-of-scope is a valid answer** — with classification (operational/deprecated/gap)
- **Match type matters** — use the right SKOS predicate, not just exactMatch for everything
