# DD-079: dbt cross-table warning conflates inherited vs own properties (issue #181)

**Status:** Accepted
**Date:** 2026-06-15
**Affects:** `src/kairos_ontology/projections/medallion_dbt_projector.py`
**Implementation:** `_gen_silver_models` (cross-table classification), `write_dbt_session_log` (`## ℹ️ Info` section), `tests/scenarios/test_scenario_dbt.py::TestCrossTableWarnings`

### Context

When a subtype is claimed as its own silver table (`Child ⊂ Parent`, single
source `tblChild`), `_gen_silver_models` scopes the model's columns to the
subtype's primary table — inherited parent attributes that live on the parent's
table are deliberately excluded (resolving them would require a JOIN). The
cross-table detector, however, flagged **every** mapped property whose domain was
the class **or any ancestor** when its column was not in the primary table. As a
result, each excluded-by-design inherited property emitted a
`Cross-table reference … may need a JOIN` ⚠️ warning — 40+ noise warnings per
subtype — drowning out genuinely actionable own-class cross-table mappings.

### Decision

Classify each cross-table mapped property by its **direct** `rdfs:domain`:

- **own** — direct domains include the class URI → keep the per-column ⚠️ warning
  (a genuine JOIN candidate). Own-precedence: a property declared on the class
  stays a warning even if it is also declared on an ancestor.
- **inherited** — direct domains intersect only ancestors → reclassify
  warning → **info** and collapse all inherited props into **one** consolidated
  ℹ️ note per class, surfaced under a new `## ℹ️ Info` section of the dbt session
  log (and threaded via `entity_metadata["info_notes"]`, so no
  `_gen_silver_models` return-signature change).

RDF permits multiple `rdfs:domain` values, so domains are read with
`graph.objects(prop, RDFS.domain)` and filtered to `URIRef` (blank-node /
`owl:unionOf` domain expressions are ignored, as before). The `## ✅ No issues`
banner now also requires no info notes.

### Rationale

The inherited columns were already excluded on purpose; warning about them is
misleading and noisy. Surfacing a single consolidated, clearly-informational note
preserves discoverability (the user can still choose to enrich the subtype via a
JOIN) without polluting the actionable warning channel or the report's warning
counts.

### Consequences

- WARNING-log volume and projection-report warning counts drop sharply for
  subtype-as-own-table models.
- A new `## ℹ️ Info` session-log section appears when inherited cross-table props
  are detected.
- `_get_class_and_parents` still follows a single `subClassOf` chain (pre-existing
  limitation, shared with column extraction so classification stays consistent
  with what was actually excluded) — multiple inheritance is out of scope here.
