# Documentation Map

This folder holds the reference documentation for the **Kairos Ontology Toolkit**.
Use this page as the entry point.

## Live documentation

| Area | What's here |
|------|-------------|
| [USER_GUIDE.md](USER_GUIDE.md) | Complete walkthrough & reference for using the toolkit |
| [RELEASING.md](RELEASING.md) | Release process (version bump, tagging, GitHub Release) |
| [design/](design/) | Canonical architecture decisions |
| [mdm/](mdm/) | Master Data Management (MDM) hub design & specs |
| [instruction-guides/](instruction-guides/) | Methodology guides for practitioners |
| [demo/](demo/) | Demo walkthrough |
| [archive/](archive/) | Frozen historical material — see the note below |

### design/

The authoritative decision log plus companion deep-dives:

- [toolkit-design-decisions.md](design/toolkit-design-decisions.md) — the ADR log
  (**DD-NNN**). This is the single source of truth for architectural choices.
- `dd-014` … `dd-065` — companion documents expanding on specific DD entries
  (architecture, silver relationship types, SCD-aware dbt, reference-model
  alignment, extensions, bronze introspection, source-schema spec, skill
  lifecycle, AI pre-modeling performance).

### mdm/

All Master Data Management documentation, consolidated:

- [mdmhubdesignv2.md](mdm/mdmhubdesignv2.md) — the MDM hub architecture spec.
- [mdm-design-decisions.md](mdm/mdm-design-decisions.md) — MDM-specific decisions.
- [user-stories.md](mdm/user-stories.md) — MDM epics & user stories.
- [mdm-navigator-spec.md](mdm/mdm-navigator-spec.md) — MDM Navigator UI spec.

### instruction-guides/

- [context-engineer-methodology-guide.md](instruction-guides/context-engineer-methodology-guide.md)
- [data-engineer-methodology-guide.md](instruction-guides/data-engineer-methodology-guide.md)

## Archive

[`archive/`](archive/) contains **historical** documents — superseded specs,
one-off fix notes, early design explorations, and a completed implementation
tracker. They are kept for provenance only and are **not** current guidance.
See [archive/README.md](archive/README.md) for what lives there and where the
live equivalents are.
