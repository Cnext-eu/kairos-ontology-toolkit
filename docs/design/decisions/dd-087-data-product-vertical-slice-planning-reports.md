# DD-087: Data-product vertical-slice planning reports

**Status:** Accepted
**Date:** 2026-06-21
**Affects:** `src/kairos_ontology/draft_model_report.py`, `cli/main.py`, design skills
**Implementation:** `kairos-ontology draft-model-report --contract ...`

### Context

Some hubs need a quick path from source evidence to a Power BI semantic model for
one report pack or data product. A naive direct source-to-gold workflow would
bypass domain, mapping, claim, silver, and gold design gates and would create a
fourth authority beside the claim registry.

### Decision

Extend the DD-086 draft-model report with a **data-product vertical slice** mode.
The user captures report demand in
`model/planning/data-products/{product}/contract.yaml`, and the command emits a
product-scoped planning view under the same folder:

- `data-product-plan.yaml`;
- `data-product-report.md`;
- `data-product-erd.mmd`;
- `domains/{domain}.yaml`.

All artifacts must declare or inherit `projection_authority: false`. The command
is deterministic, AI-free by default, and derives product triage from the DD-086
evidence statuses (`claim-approved`, `mapping-backed`, `source-backed`,
`tmdl-only`, etc.) rather than introducing a competing evidence vocabulary.

### Rationale

This keeps report-first delivery fast while preserving the canonical lifecycle.
The product slice narrows the agenda for mapping, silver, and gold design; it
does not approve claims, write TTL, or feed projectors. Gold scoping should use
the existing `kairos-ext:perspective` annotation after user confirmation instead
of creating a separate semantic-model grouping mechanism.

### Consequences

- Product contracts live under `model/planning/`, not the governed model
  authority area.
- `gold-only` is not a valid bypass category. The report uses
  `gold-annotation-needed` only when an item is already claim-backed or
  mapping-backed.
- Mapping, silver, and gold skills may consume product plans as scoped agendas,
  but still require explicit confirmation before writing TTL.
- Projectors and validators ignore data-product planning artifacts.
