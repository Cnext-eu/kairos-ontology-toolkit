# DD-085: OKF phase logs replace interactive `.sessions-design` logs

**Status:** Accepted
**Date:** 2026-06-20
**Affects:** `cli/main.py`, design skill instructions, scaffold skill copies,
`kairos-help`, `kairos-diagnose-status`, `tests/test_init.py`
**Implementation:** scaffold and skill cleanup following DD-080

### Context

DD-080 introduced the OKF continuation-state bundle at
`ontology-hub/.kairos-state/` and explicitly states that `.kairos-state/` is the
only state system going forward. The migration was partial: phase skills gained
OKF read/proposal headers, but their hard gates and session-management sections
still required bespoke interactive `.sessions-design/{phase}-*.md` logs. New hubs
also still scaffolded `.sessions-design/`, leaving two competing places for the
same design-session memory.

### Decision

Use `.kairos-state/phases/...` OKF phase logs as the **only required interactive
design-session state** for discovery, source, domain, mapping, silver, and gold
skills. Superseded interactive phase logs move to `.kairos-state/_archive/` when a
user starts fresh. Do not create `.sessions-design/` for new hubs.

Existing `.sessions-design/*.md` files are historical only. There is no automatic
migration helper; when resuming an existing hub, a user or skill may manually
summarize relevant open questions and decisions into the appropriate OKF phase log.

This does **not** migrate the separate machine/audit surfaces:

- `.sessions-design-import/` remains the import-results audit log location for
  source-import commands.
- `.sessions-projection/` remains the projection-run report location.

### Rationale

Keeping both interactive `.sessions-design` logs and OKF phase logs creates
conflicting prerequisites and split resume anchors. OKF already provides
per-instance phase logs, frontmatter status, xrefs, and a shared continuation
index owned by `kairos-flow`; duplicating the same state in `.sessions-design`
adds drift without adding capability. Avoiding automatic migration keeps the
change simple and prevents LLM-generated summaries from rewriting historical
session evidence.

### Consequences

- Design skills must require their OKF phase log before changing design artifacts.
- `init` and `new-repo` scaffold `.kairos-state/` phase directories and no longer
  scaffold interactive `.sessions-design/`.
- Documentation and diagnostics refer to `.sessions-design` only as legacy
  historical context, not as current design state.
- Existing hubs are backward-readable by humans, but current continuation state is
  maintained in `.kairos-state/`.
