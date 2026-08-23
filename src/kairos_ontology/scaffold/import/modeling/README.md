# Modeling — toolkit-managed, git-tracked records

This directory holds **structured, toolkit-managed records** about ontology modeling
itself — distinct from raw client evidence under `.import/businessdiscovery/`, which is
free-form and stays gitignored. Everything under `.import/modeling/` is **tracked in
git**: these are OKF-style records with their own id/status/provenance, not disposable
exports, so they belong in the repository's history alongside the decisions and models
they inform.

> **Location:** like `.import/businessdiscovery/`, this folder lives at the
> **repository root**, a sibling of `ontology-hub/` — it is **not** under
> `ontology-hub/`.

## Subfolders

- **`feedback/`** — modeling-feedback knowledge-snippet records (`HUB-FB-*.md`), a
  lighter-weight, OKF-style sibling of the hub Decision Log. See
  `feedback/README.md` and `kairos-ontology feedback --help`.
- **`knowledge-inputs/`** *(reserved)* — OKF business-knowledge / model-input files: an
  upcoming append-based convention for capturing confirmed business knowledge and model
  inputs as separate, dated files, following the same append-only rule as every other
  record type here (see below).

## Append-only convention

Every record type under `.import/modeling/` is **append-only**: a contribution is a new,
dated file (e.g. `HUB-FB-20260823-<token>.md`), never an edit to a file already
committed. Corrections or follow-ups are new files that reference the original, not
in-place rewrites. This keeps the provenance trail behind decisions, glossaries, and
downstream models stable — they cite a specific record, and that record's content never
changes under them.
