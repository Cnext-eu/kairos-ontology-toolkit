# Archive — historical documentation

Everything in this folder is **frozen history**. These documents are superseded
specs, one-off fix notes, early design explorations, and a completed
implementation tracker. They are kept for provenance and context only — they are
**not** current guidance and may contradict the live docs.

For current documentation, start at the [Documentation Map](../README.md).

## Where to find the live equivalents

| If you came here for… | Go to |
|------------------------|-------|
| Architectural decisions | [design/toolkit-design-decisions.md](../design/toolkit-design-decisions.md) (the DD-NNN log) |
| MDM design & specs | [mdm/](../mdm/) |
| How to use the toolkit | [USER_GUIDE.md](../USER_GUIDE.md) |
| DDD governance decision | DD-091 in the [design decision log](../design/toolkit-design-decisions.md) |

## Notable contents

- **`evidence-led-modeling/`** — an implementation tracker for the evidence-led,
  accelerator-first modeling approach. Slices 0–4 were implemented; slices 5–8
  (`slice-5-pbi-fitgap` … `slice-8-rollout-upstream`) were **never started**.
  The folder is archived as historical **per owner decision**, not because the
  work completed.
- Superseded MDM deep-dives (`MDM Deepdive.md`, `mdmhub.md`) — replaced by
  [mdm/](../mdm/).
- Toolkit improvement specs, migration notes, and dbt/skill redesign explorations
  that have since landed or been superseded by DD-NNN entries.
- `ddd-governance-implementation-plan.md` — completed; the canonical record is
  DD-091 in the design decision log.

> Some documents in this folder reference each other by sibling filename. Those
> links are intentional and remain valid within the archive.
