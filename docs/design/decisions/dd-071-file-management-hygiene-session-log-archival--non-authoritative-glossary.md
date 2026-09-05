# DD-071: File-management hygiene: session-log archival + non-authoritative glossary

**Status:** Accepted
**Date:** 2026-06-14
**Affects:** `src/kairos_ontology/glossary_builder.py`, design-skill SKILL.md
files (`kairos-design-{domain,discovery,mapping,silver,gold,source}`,
`kairos-diagnose-status`) + scaffold copies
**Implementation:** `_NON_AUTHORITATIVE_NOTE` stamp in `build_glossary_graph`;
`.sessions-design/_archive/` convention documented in the design skills.

### Context

Two independent housekeeping issues shipped alongside #166. (H1) The design
skills already offered "Start fresh (previous archived)" but **no archive folder
or move mechanism was defined** — a fresh start could leave or overwrite the old
log. (H2) The business-discovery glossary (`{company}-glossary.ttl`, DD-063) is
**initial inspiration only** — it is not updated during modeling and its
`seeAlso`/`relatedMatch` links may go stale by design — but nothing in the
artifact said so, risking future sessions treating it as a binding source to
reconcile.

### Decision

- **H1.** Define `ontology-hub/.sessions-design/_archive/`. When a user picks
  "Start fresh" in any design skill that keeps `.sessions-design/*.md` logs,
  **move** the existing log there (preserving the filename, optionally
  timestamp-suffixed) before creating the new one — never silently delete.
  `kairos-diagnose-status` ignores `_archive/` when locating the most recent
  session log.- **H2.** Stamp every generated glossary `skos:ConceptScheme` with a constant
  `rdfs:comment` **and** `skos:editorialNote` disclaimer
  (`_NON_AUTHORITATIVE_NOTE`) stating the glossary is non-authoritative
  inspiration whose links are not reconciled during modeling. Document the status
  in `kairos-design-discovery` (owner) and reference it from
  `kairos-design-domain`.

### Rationale

Both are low-risk, additive conventions that prevent data loss (H1) and
prevent a generated inspiration artifact from being mistaken for a maintained
mapping (H2). The glossary disclaimer is constant text emitted for every build,
so it needs no configuration.

### Consequences

- H1 is primarily a documented skill convention (no enforced CLI move); the
  archive folder is git-ignorable like the rest of `.sessions-design/`.
- H2 adds two triples to every glossary; a `test_glossary_builder.py` assertion
  guards their presence.

### Amendment (3.21.0) — automated projection-log archival

The H1 convention is now **enforced in code for projection session logs**. When a
projection run writes new per-domain logs into `.sessions-projection/`
(`projection-{domain}-*.md` and `dbt-{domain}-*.md`), any pre-existing logs for
the in-scope domains are first **moved** into `.sessions-projection/_archive/`
(collision-safe `-{n}` suffix; never deleted) by
`_archive_prior_projection_logs()` in `projector.py`, called from
`_run_projection`. This mirrors the design-session `_archive/` convention but
removes the manual step for projection logs. `kairos-diagnose-status` ignores the
`_archive/` subfolder for `.sessions-projection` as well.
