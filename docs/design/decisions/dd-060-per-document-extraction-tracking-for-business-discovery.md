# DD-060: Per-Document Extraction Tracking for Business Discovery

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `kairos-design-discovery` skill, `.import/businessdiscovery/`,
`ontology-hub/businessdiscovery/_extractions/`, new `discovery-status` CLI command
**Implementation:** `src/kairos_ontology/discovery_extraction.py`,
`discovery-status` command in `src/kairos_ontology/cli/main.py`,
`.github/skills/kairos-design-discovery/SKILL.md` (Phase 1 / Phase 4) + scaffold copy

### Context

Business discovery reads raw artifacts (PDFs, decks, notes) dropped in
`.import/businessdiscovery/` and extracts company-specific terminology. There was **no
record of what was extracted from which document** and **no way to tell which documents
are new or unprocessed** when more are added later. On a rerun the skill re-read
everything with no provenance and no incremental signal — terminology could be lost or
silently duplicated, and there was no audit trail behind the glossary.

### Decision

Introduce **per-document extraction files** plus a deterministic, hash-based status
command, mirroring the inventory-freshness pattern (DD-047):

- For every processed document, the discovery skill writes one
  `ontology-hub/businessdiscovery/_extractions/{slug}.extraction.yaml` recording the
  `source_sha256`, a summary, the extraction `strategy`, and the `extracted_terms`
  (with a `company_specific` flag). `{slug}` is the slugified source filename **including
  its extension**, so same-stem documents (`report.pdf` vs `report.docx`) never collide.
- A new **`discovery-status`** CLI command (backed by `discovery_extraction.py`) scans
  the import folder, compares each document's current hash to the stored
  `source_sha256`, and classifies it **unprocessed / changed / up-to-date / orphan**.
  Informational by default; `--strict` exits non-zero when there is work to do.
- The skill (Phase 1 + Phase 4) runs `discovery-status` and processes **only** new or
  changed documents, leaving up-to-date ones untouched.

The AI extraction itself stays in the skill; only the deterministic bookkeeping is
implemented in code so it is unit-testable. `discovery-status` is a read-only helper and
is **not** added to the soft skill-gate set (consistent with `check-inventory` /
`generate-inventory`).

### Rationale

Reusing the proven `compute_source_hash` freshness model keeps behaviour consistent and
cheap (no AI for the "what changed?" question). Per-document files give full provenance
that travels with the hub in git, and the hash-based diff makes reruns incremental
instead of re-reading the whole corpus. Storing the files under
`ontology-hub/businessdiscovery/_extractions/` (next to the glossary output) keeps the
provenance committed alongside the deliverable it explains.

### Consequences

- Discovery now has an auditable trail: every glossary term can be traced to a source
  document and its extraction file.
- Adding new artifacts is a cheap, detectable event (`discovery-status` flags them); only
  the delta is reprocessed.
- New hubs get a `businessdiscovery/_extractions/` folder + README via `init`/`new-repo`;
  existing hubs get it via the on-demand `mkdir` in `write_extraction` and the scaffold
  README on `update`.
- The extraction schema is intentionally generic — company-terminology extraction is the
  worked example, not a hard requirement.

### Amendment (2026-08-14): `status` becomes load-bearing, and content is linted

Three gaps in this design surfaced together during an unattended delivery run (#416, #417).

**`status` was documented and read nowhere.** The schema defines
`status: processed | partial | skipped`, and the design's whole posture is that partial coverage should be
recorded honestly rather than overstated. But no code read the field: `discovery-status` validated
`source_path` and `source_sha256` only, and printed one unqualified success line. On a real hub 23 of 56
records were legitimately `partial` — long documents where only decision-bearing sections were read — and
that judgment was invisible to every gate. The schema offered an honesty mechanism that nothing consumed.
`status` is now read and reported.

**The gate validated provenance, not content.** A record whose `strategy` and `summary` were literally
`TODO` with `extracted_terms: []`, but whose path and digest were correct, passed `discovery-status --strict`.
For interactive use that is minor; for an unattended run these records **are** the deliverable — the thing a
human is asked to trust instead of watching the run — and an empty stub was indistinguishable from real work.
Content is now linted, generalising the principle already established for the glossary TTL (DD-103 amendment,
#288): scaffold-provided or placeholder content is not authored evidence.

**Severity is deliberately asymmetric.** Extraction content findings **warn** and are `--strict`-eligible;
they never error. `partial` is an author's judgment with no automated remedy, and a hub carrying 23 honest
partials must not acquire 23 unclearable errors — the same advisory rationale recorded for `catalog-test`.
New findings route into a **separate** strict-eligible property rather than the existing work signal:
widening that would have made `--strict` unconvergeable on such a hub, recreating precisely the
non-converging loop that #405 reports, and would have counted already-processed documents as needing work.

**Duplicate documents are now detected.** The status check hashes each staged document, but never compared
digests *across* documents; 7 of 56 tracked documents on the same hub were byte-identical and were reported as
7 independent units of work. Duplicates are reported **additively** — a duplicate with no extraction record
still needs processing, so the work count is unchanged. Note the digest was previously computed only for
already-matched records, so this costs one full read per unmatched document; that cost is accepted knowingly.

**Consequence for `build-glossary`.** It read `extracted_terms` from every record regardless of `status`, so a
`skipped` record's terms landed in the company glossary. Harmless while `status` was inert; a contradiction the
moment it became load-bearing. `skipped` records are now excluded and the count surfaced; `partial` records are
still included, because partial coverage is coverage.

**Still open.** This DD names `kairos-design-discovery` (Phase 1 / Phase 4) as the producer of extraction
records, but no skill currently references `discovery-status`, `_extractions/`, or `build-glossary` at all —
the producer contract is undocumented in the place meant to produce it.

### Amendment (2026-07-22): recursive discovery + provenance-based matching

The original implementation scanned only the **top level** of
`.import/businessdiscovery/` (`iter_discovery_documents` used `Path.iterdir()`) and matched
each document to its extraction purely by a **basename-derived filename**. Documents placed
in subfolders were therefore invisible, and any extraction already written for a nested
source was reported as an **orphan** even though its `source_path`, `source_sha256`, and
schema were valid.

`discovery-status` now:

- discovers documents **recursively**, skipping READMEs and dotfiles at every depth and any
  file under a dot-prefixed directory, ordered by normalized source-relative POSIX path;
- treats a document's **normalized source-relative path** as its canonical identity and
  matches extractions primarily by normalized `source_path` provenance (tolerating the
  documented relative form, absolute paths, and Windows separators), falling back to the
  legacy basename filename and then the path-derived nested filename — so **existing records
  are preserved and never renamed**;
- assigns **collision-safe** filenames to *new* nested records
  (`{path-slug}-{sha1(rel)[:8]}.extraction.yaml`) so identical filenames in different folders
  and slug-colliding paths stay distinct while extraction files remain flat; and
- adds a **conflict** classification when more than one extraction claims the same source
  path.

`source_path` (not `source_file`) is authoritative for nested identity, and new records
should store the repository-relative form `.import/businessdiscovery/<nested/path>`.
