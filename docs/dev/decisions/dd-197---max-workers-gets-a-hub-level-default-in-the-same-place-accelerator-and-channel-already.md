# DD-197: --max-workers gets a hub-level default, in the same place accelerator and channel already live

**Status:** Accepted
**Date:** 2026-08-19
**Affects:** `cli/shared.py` (`_read_hub_max_workers`), `cli/sources.py` (`analyse-sources`, `propose-alignment`)
**Issue:** #562 (Problem 1)

### Context

`analyse-sources` and `propose-alignment` both expose `--max-workers`,
bounding the per-table LLM call thread pool. Fine as a one-off flag, but a
hub had no way to set its own default once — every invocation needed the
flag retyped, unlike `accelerator` and `channel`, which already live in
`[tool.kairos]` in the hub's `pyproject.toml` with an explicit-flag >
hub-config > default precedence.

### Decision

New `_read_hub_max_workers(hub_root)` reads `[tool.kairos].max_workers`
with the same dual-candidate lookup `resolve_hub_accelerator_detailed`
(DD-125) already uses (`hub_root/pyproject.toml` then
`hub_root.parent/pyproject.toml`). Both CLI options change their default
from a hardcoded `16` to `None`, resolved as: explicit `--max-workers` >
`[tool.kairos].max_workers` > `_CLI_DEFAULT_MAX_WORKERS` (16, unchanged).
A present but invalid value (non-integer, boolean, zero, or negative) is a
configuration error and raises — unlike an absent key, a wrong one must
not look like "not set".

### Consequences

A hub can now set its own concurrency default once. Honest, pre-existing
gap this does not fix, named rather than hidden: `core/_concurrency.py`'s
own `DEFAULT_MAX_WORKERS = 8` (the library default for direct callers
bypassing the CLI) has always been unreachable for CLI users, since both
commands already hardcoded `16` before this change — that split stays as
it was; this DD only adds a config-level override on top of the existing
CLI default.
