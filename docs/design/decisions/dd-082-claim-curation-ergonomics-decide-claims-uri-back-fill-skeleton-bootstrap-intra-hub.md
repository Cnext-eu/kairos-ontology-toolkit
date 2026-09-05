# DD-082: Claim-curation ergonomics: `decide-claims`, URI back-fill, skeleton bootstrap, intra-hub imports (issue #190)

**Status:** Accepted
**Date:** 2026-06-20
**Affects:** `src/kairos_ontology/decide_claims.py` (new),
`claim_projection_sync.py`, `migrate_claims.py`, `cli/main.py`,
`kairos-design-domain` skill
**Implementation:** issue #190 (items 1–5, 7); item 6 split to issue #191

### Context

Curating `*-claims.yaml` and running `claims-to-silver-ext` on a real hub
(`cldn-ontology-hub`, party domain, 1183 claims) surfaced one hard blocker plus
several workflow-friction gaps:

1. Intra-hub shared bases (`_foundation.ttl`, `_master.ttl`) were flagged as
   `extra owl:imports` and stripped, because `_collect_hub_domain_bases` skipped
   every `_`-prefixed file.
2. There was no CLI to query or bulk-curate claim `status`/`disposition` — the
   skill told users to curate but provided no command, so they hand-edited YAML
   (producing huge, unreviewable diffs).
3. `migrate-claims` always left `class_uri`/`property_uri` empty, but the validator
   requires those URIs before an anchored claim can be approved.
4. `claims-to-silver-ext` silently refused to bootstrap a domain whose ontology /
   `*-silver-ext.ttl` files did not yet exist (it set `status.error` and wrote
   nothing).
5. The MDM-anchor warning gave no concrete example of how to satisfy it.

### Decision

Keep `*-claims.yaml` as the canonical, **git-tracked** source of truth — no
database (in-memory or on-disk). The runtime already loads the full registry into
memory; a DB would sacrifice git-diff governance (DD-094) without solving the real
gap, which is a missing **query + bulk-update API**. Address each item:

- **Intra-hub imports (item 1):** `_collect_hub_domain_bases` now treats any
  `owl:Ontology`-declaring `*.ttl` under `model/ontologies/` (including
  `_`-prefixed shared bases) as an allowed intra-hub base; it only skips
  `-ext.ttl` extension surfaces. Such imports are neither flagged nor stripped.
- **`decide-claims` (items 2/3):** new `decide_claims.py` provides a pure,
  AI-free query layer (`select_claims` with status/disposition/type/origin/id-glob/
  column-glob selectors) and a bulk-status mutator (`apply_decisions`) that honors
  `STATUS_TRANSITIONS` and reports skipped/invalid transitions. The CLI writes back
  through the existing canonical `write_registry` (deterministic `safe_dump`,
  `width=100`), so curation diffs stay minimal — no new serializer needed (item 3
  was solved by routing through the existing one).
- **URI back-fill (item 4):** `migrate-claims` loads the reference-model inventory
  and resolves `class_uri`/`property_uri` at claim-creation time. Ambiguous names
  (same name → multiple URIs) stay null rather than guessing; resolved/unresolved
  counts are printed. `--no-resolve-uris` is an escape hatch.
- **Skeleton bootstrap (item 5):** `claims-to-silver-ext` scaffolds a minimal valid
  `owl:Ontology` skeleton (with provenance header and inferred hub base / foundation
  import) for any missing ontology or `*-silver-ext.ttl`, then proceeds with the
  normal sync. `--no-scaffold` disables it.
- **MDM-anchor warning (item 7):** the warning now prints a concrete
  `mdm_anchor: true` reference_data claim example and points to the skill /
  `--no-mdm-anchor`.

### Consequences

- Shared foundation/master bases survive projection sync; multi-domain hubs no
  longer lose their intra-hub imports.
- Claim curation is a reviewable, scriptable CLI flow with minimal diffs.
- Anchored claims migrated from alignment can be approved without manual URI lookup.
- A fresh domain can be bootstrapped end-to-end from claims alone.
- **Out of scope:** the destructive whole-graph rdflib rewrite of projection
  surfaces (item 6) is tracked separately as **issue #191**; the scaffolded
  provenance header can still be stripped by that rewrite when approved imported
  claims exist, which #191 will address.
