# DD-134: Immutable, Reversible Unreleased Toolkit Testing

**Status:** Accepted
**Date:** 2026-07-27
**Affects:** `update` CLI, hub `pyproject.toml` / `uv.lock`, managed-file refresh,
toolkit operations and release guidance
**Implementation:** `src/kairos_ontology/cli/main.py` (`update --test-ref`,
`update --restore`, test-ref state and dependency transaction helpers)

### Context

Testing toolkit work in a real hub previously required publishing a formal
pre-release or manually editing dependency pins. A mutable branch pin was not
reproducible, while manual restoration could resolve to a different release or
lose the exact prior source. Same-version test commits also risked skipping the
managed-file refresh, especially around Windows executable locking.

### Decision

`update --test-ref <branch-or-sha>` resolves the GitHub ref before mutation and
accepts only its immutable 40-character commit SHA. It rewrites every PEP 508
toolkit dependency while preserving extras, locks and syncs, and forces managed
files to refresh from the tested commit. The existing release channel remains
unchanged; testing creates no tag, release asset, version bump, or CHANGELOG
entry.

The hub records the requested ref, resolved SHA, and exact prior dependency
source in temporary, visible `[tool.kairos.test-ref]` metadata. `--restore`
restores that exact source, removes the metadata, relocks/resyncs, and refreshes
released managed files. Nested sessions and restore without valid metadata are
rejected. `--upgrade`, `--test-ref`, and `--restore` are mutually exclusive.

Dependency-file changes are transactional: failures restore the original
`pyproject.toml` and `uv.lock` bytes. Windows reuses the detached self-update
helper from DD-057, including forced refresh and its transcript.

### Rationale

Resolving mutable names once combines convenient branch testing with a
reviewable, reproducible pin. Saving the source rather than only a channel or
version guarantees exact restoration. Reusing the established transaction and
Windows refresh mechanisms avoids a second, platform-specific update path.

### Consequences

- During a test, expected hub drift is limited to dependency files and
  toolkit-managed `.github` files (plus the normally ignored Windows refresh
  transcript); ordinary channel selection is unaffected.
- Hubs retain visible restore authority until a successful `--restore`.
- GitHub/`gh` access is required for ref resolution, and Windows users must wait
  for the detached helper before testing or reviewing the final diff.
- Failed synchronous resolution, locking, syncing, scheduling, or refresh does
  not leave a partially changed dependency state. A detached Windows-helper
  failure remains recoverable from its transcript and the saved restore state.
