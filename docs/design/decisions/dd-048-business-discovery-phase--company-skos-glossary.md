# DD-048: Business Discovery Phase & Company SKOS Glossary

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** new `kairos-design-discovery` skill (both copies), `kairos-design-mapping`, `kairos-design-domain`, `kairos-help`, `kairos-setup-init`, `copilot-instructions.md` (both copies), `cli/main.py` (`init` + `new-repo`), scaffold (`import/businessdiscovery/`, `ontology-hub/model/glossary/`)
**Implementation:** `.github/skills/kairos-design-discovery/SKILL.md`, `src/kairos_ontology/scaffold/skills/kairos-design-discovery/SKILL.md`, `src/kairos_ontology/cli/main.py`, `src/kairos_ontology/scaffold/ontology-hub/model/glossary/`, `src/kairos_ontology/scaffold/import/businessdiscovery/`

> **Update 2026-06-13:** the repo-root artifacts folder was renamed from
> `.imports/` (plural) to **`.import/`** (singular); the dotless scaffold source
> folder is correspondingly `scaffold/import/`. All references below use the
> new name.

### Context

Modeling previously started at source/domain design with no structured capture of
*who the company is* or *how they talk about their business*. Two gaps mattered:
(1) company context (what they do, business model, offerings) was never written
down to ground naming/modeling decisions; (2) business-specific terminology — acute
in freight forwarding/logistics, where industry terms carry different in-house
meanings — was lost, even though it is exactly what makes source-to-domain mapping
accurate. Capturing those alternative names directly on the domain ontology would
pollute the canonical model.

### Decision

Introduce **business discovery** as the first phase of the design lifecycle, owned by
a new interactive skill **`kairos-design-discovery`**:

1. **Phase 1 — company research:** read drop-in artifacts plus optional public web
   research; synthesize a confirmed company-context summary.
2. **Phase 2 — terminology capture:** record the company's alternative names in a
   **SKOS glossary** (`skos:prefLabel` = canonical term, `skos:altLabel` = the
   business's name(s)), linked to the domain by **IRI reference only**
   (`rdfs:seeAlso`) — the domain `.ttl` is never modified.

Two artifact locations (both git-committed):

- **Raw artifacts** → `.import/businessdiscovery/` at the **repository root**
  (alongside `ontology-reference-models/`, since both are *imported inputs* rather
  than hub deliverables — NOT under `ontology-hub/`).
- **Synthesized context** → `ontology-hub/.sessions-design/businessdiscovery-*.md`
  (hub-scoped, like all design session logs).
- **Glossary** → `ontology-hub/model/glossary/{company}-glossary.ttl`.

`kairos-design-mapping` loads the glossary and uses `skos:altLabel` matches as
**advisory, user-confirmed candidates** for column→property mapping.
`kairos-design-domain` reads the context/glossary as background only (Gate 6
source-grounding is unchanged). The canonical Fresh Hub Lifecycle becomes
`discovery → source → domain → mapping → silver → gold → validate → project →
diagnose → consume`.

### Rationale

A SKOS **overlay** keeps alternative names out of the canonical ontology while still
making them machine-readable for tooling (and reusable later by projections such as
azure-search synonyms or prompt). Placing `.import/` at the repo root reuses the
existing `ontology-reference-models/` precedent for imported inputs and keeps the
hub deliverable tree clean. Discovery is interactive/no-autopilot because company
facts and glossary terms require human confirmation; web-sourced claims stay marked
inferred until approved.

### Consequences

- `kairos-ontology init` and `new-repo` now create `.import/businessdiscovery/`
  (repo root) and `ontology-hub/model/glossary/` and install the glossary template +
  READMEs.
- New skill is distributed via the scaffold; routing/no-autopilot/lifecycle tables
  updated in both `copilot-instructions.md` copies and the help/setup-init skills.
- Tests: `tests/test_init.py` asserts the new directories + skill for `init` and
  `new-repo`; a glossary-template TTL parse test guards the scaffold sample.
