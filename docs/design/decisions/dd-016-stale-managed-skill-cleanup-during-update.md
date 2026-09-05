# DD-016: Stale Managed Skill Cleanup During Update

**Status:** Accepted
**Date:** 2026-05-14
**Affects:** `cli/main.py` update command
**Implementation:** Stale skill scan after managed-file sync in `update()`

### Context

When the toolkit renames or removes a skill from the scaffold, the `update`
command previously only added/updated files — it never removed stale skills.
This left orphaned skill directories in hub repos (e.g., `kairos-toolkit-update`
persisting when the scaffold renamed it to `kairos-ontology-toolkit-ops`).

### Decision

After syncing managed files, `update` scans `.github/skills/` for directories
whose `SKILL.md` contains the managed marker (`kairos-ontology-toolkit:managed`)
but whose name is NOT in the current scaffold skills list. These are removed.

| Skill type | Has managed marker? | In scaffold? | Action |
|------------|-------------------|--------------|--------|
| Current toolkit skill | ✅ | ✅ | Updated normally |
| Renamed/removed toolkit skill | ✅ | ❌ | **Deleted** |
| User custom skill | ❌ | ❌ | Left untouched |

### `--check` Mode

In `--check` mode, stale skills are reported but not removed, and the exit
code is non-zero (same as outdated/missing files).

### Rationale

- Safe: only removes files the toolkit created (marker-based identification)
- Automatic: no manual list of removed skills to maintain
- Consistent: `update` is already the explicit user action for syncing
