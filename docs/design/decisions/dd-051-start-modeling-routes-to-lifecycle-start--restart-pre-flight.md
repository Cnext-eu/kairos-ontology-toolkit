# DD-051: Start-Modeling Routes to Lifecycle Start & Restart Pre-flight

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `copilot-instructions.md` (both copies), `kairos-design-domain` skill (both copies)
**Implementation:** `.github/copilot-instructions.md`, `.github/skills/kairos-design-domain/SKILL.md` (+ scaffold copies via `scripts/sync_dev_skills.py`)

### Context

`kairos-design-domain` is **data-first**: Gate 6 / the Source Evidence Table
(Step 0c) require imported, analysed source evidence before any class/property may
be proposed. But two routing/UX gaps remained:

1. The Copilot **instructions** mapped "Model / design …" straight to
   `kairos-design-domain` with no framing that domain modeling is a **mid-lifecycle**
   step (`discovery → source → domain → …`). On a fresh hub, "start modeling" could
   send a user into the modeling skill with an empty `integration/sources/`.
2. When **restarting/extending** an existing model, nothing reminded the user that
   **additional source systems** might need importing first. Step 0a only handled a
   missing `_analysis/` directory, implicitly assuming `integration/sources/` was
   already populated.

### Decision

Add lifecycle framing + pre-flight guidance (deliberately **guidance, not a new
blocking gate** — Gate 6 remains the hard constraint):

1. **Instructions.** The "Modeling skill" section and routing guide now state that
   domain modeling follows discovery + source, and that "start modeling" means
   **beginning the modeling lifecycle**. On a fresh hub the agent **auto-hands off**
   to `kairos-design-source` (offering `kairos-design-discovery`) first; when sources
   already exist it runs an explicit source-completeness check.
2. **Skill pre-flight.** `kairos-design-domain` gains a **"Pre-flight checks
   (lifecycle position)"** block, run before any modeling:
   - **P2a (fresh / empty `integration/sources/`): auto-hand off.** Invoke
     `kairos-design-source` (offer `kairos-design-discovery`) to import
     (`import-source` / `import-flatfile`, incl. Parquet) + `analyse-sources`, then
     resume modeling. Start-modeling is treated as the lifecycle entry, not a jump
     into class design.
   - **P2b (sources exist): MANDATORY always-on Source-Completeness Checkpoint.**
     On **every** modeling start where sources exist — **first pass or
     restart/extension** — the agent must list the imported/analysed source systems
     and explicitly ask whether **additional/other** sources need importing before
     building the Source Evidence Table. If yes → route to `kairos-design-source` +
     `analyse-sources`; if complete → continue. Wired into "Session Management → On
     start" (Continue/Review) and cross-referenced from Step 0a.

> **Refinement (2026-06-13, same day):** P2b supersedes the original restart-only
> "Mode B" — the completeness question is now posed on the **first modeling pass
> too**, closing the gap where some-but-not-all sources had been analysed. P2a was
> strengthened from "advise" to an **auto-handoff** to the source skill.

### Consequences

- Users starting on a fresh hub are auto-routed into the lifecycle start instead of
  an evidence-less modeling session, reducing invented classes (the failure mode
  Gate 6 guards against).
- The completeness question now fires on **every** modeling start (not just
  restart), so partially-imported source sets are surfaced before modeling.
- The mandatory **question** is always posed; the user's **answer** is not
  hard-blocked (Gate 6 remains the hard evidence constraint).
- No behavioural/code change — instructions + skill guidance only, distributed to
  hubs via the sync-managed scaffold copies. Parity is enforced by
  `tests/test_scaffold_sync.py`.
