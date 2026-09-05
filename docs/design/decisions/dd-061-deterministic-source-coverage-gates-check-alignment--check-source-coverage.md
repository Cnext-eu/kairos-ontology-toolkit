# DD-061: Deterministic Source-Coverage Gates (check-alignment + check-source-coverage)

**Status:** Superseded by DD-094 on 2026-07-21
**Date:** 2026-06-13
**Affects:** `kairos-design-domain` skill (Step 0a.2), `kairos-design-silver` +
`kairos-execute-project` skills, `propose-alignment` output (alignment YAML
`schema_version` 1 → 2), two new read-only CLI commands
**Implementation:** `src/kairos_ontology/alignment_coverage.py`,
`src/kairos_ontology/source_coverage.py`, `check-alignment` +
`check-source-coverage` commands in `src/kairos_ontology/cli/main.py`,
`write_alignment_output` in `src/kairos_ontology/propose_alignment.py`

> **Supersession note:** DD-094 retires alignment YAML and makes the Claim
> Registry plus canonical completeness facts authoritative. The source-coverage
> intent survives in the current `check-claims` / `check-source-coverage` views;
> the alignment-YAML authority and `check-alignment` path described below are
> historical.

### Context

Reference-model coverage is protected by a **deterministic blocking gate**
(DD-047 `check-inventory`): a modeler cannot proceed until every reference TTL has
a fresh materialized inventory. Source coverage had **no equivalent gate**. The
modeling skill's Step 0a.2 treated a missing `{domain}-alignment.yaml` as
*advisory* ("instruct the user to run `propose-alignment`"), and nothing verified
that the modeled ontology actually represented every source table assigned to a
domain.

This asymmetry let a real shortcut slip through silently: in a client hub the
modeler hand-read 2 of ~67 tables that the affinity reports assigned to the
`party` domain, because `propose-alignment` had never been run (no
`*-alignment.yaml` files existed at all) and nothing blocked.

A naive fix — "gate the Source Evidence Table" — is **not feasible** at
`check-inventory` fidelity: that table is unstructured markdown in a session file
and cannot be deterministically parsed for completeness. The structured artifacts
that *can* be checked are the affinity reports, the alignment YAML, and the
mapping TTLs.

### Decision

Add **two deterministic, AI-free CLI gates**, each modeled on `check-inventory`
(hard-block by default, `--warn-only` escape hatch, read-only → **not** added to
the soft skill-gate set):

1. **`check-alignment`** (pre-modeling input completeness) — for every domain in
   `_analysis/*-affinity.yaml` (schema_version 2, which enumerates every
   `(system, table)` per domain), require a `{domain}-alignment.yaml` that
   **covers all** the domain's tables and is **fresh**. Classification:
   *missing / incomplete / stale* (blocking), *unverifiable / orphan* (warn),
   *ok*. To support freshness, `write_alignment_output` now stores a
   `source_sha256` digest of the affinity `(system, table)` set and bumps the
   alignment `schema_version` 1 → 2; pre-existing v1 files (no hash) classify as
   **unverifiable** (warn, non-blocking) so existing hubs do not hard-break on
   upgrade. Wired as a hard gate in `kairos-design-domain` Step 0a.2.

2. **`check-source-coverage`** (pre-silver output completeness) — compares the
   affinity-assigned `(system, table)` set for each in-scope domain against the
   source tables actually mapped to a domain entity. A table is **covered** when
   its bronze table URI — or any of its column URIs (`kairos-bronze:sourceTable` /
   `belongsToTable`) — is the subject of a SKOS match in `model/mappings/*.ttl`.
   Uncovered tables are blocking. Wired as a mandatory pre-flight before silver in
   `kairos-design-silver` and `kairos-execute-project`.

### Rationale

Both gates operate on **committed, structured** data (affinity YAML, alignment
YAML, bronze vocab + mapping TTLs), so "did propose-alignment cover every domain
table, and is it still fresh?" and "is every domain table mapped before silver?"
become objective set-difference + hash questions — exactly the property that makes
`check-inventory` reliable. The unstructured Source Evidence Table is deliberately
**not** the gate target. Reusing the hard-block-with-`--warn-only` shape keeps the
operator experience consistent across all deterministic gates.

### Consequences

- The exact client-hub shortcut is now caught: zero alignment files →
  `check-alignment` blocks immediately; a partially-mapped domain →
  `check-source-coverage` blocks before silver.
- `propose-alignment` output is versioned (`schema_version` 2) and carries a
  freshness hash; re-running it after sources change is detectable as *stale*.
- Existing v1 alignment files remain valid (reported as *unverifiable* until
  regenerated) — no forced migration.
- Two new read-only commands join `check-inventory` / `coverage-report` as
  skill-gate-exempt deterministic helpers.
