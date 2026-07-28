# CLdN Ontology Hub — Design Decision Specs

Small, evidence-grounded record of canonical modeling decisions for this hub.
Rationale lives here (not in the TTL) so a future ontology refresh cannot drop the *why*.
The ontology states *what is true*; this log states *why we chose it and what we rejected*.

Format follows the accelerator `decision-log.md` pattern (ID / Status / Rationale / Evidence).
Hub decisions belong here; the accelerator log is a managed reference-model file.

---

## HUB-DD-001 — Equipment domain uses MMT/Equipment only (not DCSA/Equipment)

| Field | Value |
|---|---|
| Domain | `equipment` (`ontology-hub/model/ontologies/equipment.ttl`) |
| Status | **Accepted** |
| Date | 2026-07-28 |
| Confidence | High |

### Context / Finding

The logistics accelerator blueprint activates **both** `mmt/equipment` and
`dcsa/equipment` reference modules for the `equipment` domain
(`accelerator-packs/logistics/.../client-hub-blueprint/data-domains.yaml`).
The activation-driven managed-import check therefore expects an `owl:imports` for
`<https://www.kairosflow.ai/ont/dcsa/equipment>`, and its absence is reported as a
`missing_managed_import` error.

Source evidence contradicts a DCSA/Equipment alignment:

- **DCSA/Equipment** models **ISO 6346 ocean containers** only — `Container`
  (+ Dry/Reefer/Tank/FlatRack/OpenTop/Platform), with a **mandatory** `containerNumber`
  (cardinality 1), `isoEquipmentCode`, `sealNumber`, SOLAS `verifiedGrossMass`,
  reefer `temperatureSetting`.
- **Qargo `resources`** (the source behind `equipment:Unit`) is a **RoRo trailer/chassis
  fleet**: `resource_type` enum → `FULL_TRAILER` (e.g. `testchassis…`);
  `compatible_container_types` → `[]`; **no** container number, ISO code, seal, VGM,
  or reefer-temperature columns.

A `FULL_TRAILER`/chassis is **not** an ISO ocean container.

### Decision

Keep `equipment:Unit ⊑ mmt-eq:TransportEquipment` and import **only**
`mmt/equipment`. Do **not** import or subclass under `dcsa/equipment`.
Treat the resulting `missing_managed_import` as an **accepted degraded warning**;
the clean validation run is:

```powershell
uv run kairos-ontology validate --degraded
```

`compile --check` is unaffected (the check is degradable, not a hard error).

### Alternatives rejected

| Option | Why rejected |
|---|---|
| **Subclass `Unit ⊑ dcsa-eq:Container`** | Semantically wrong and source-infeasible — inherits mandatory `containerNumber` (cardinality 1) the RoRo source cannot populate. |
| **Bare `owl:imports <dcsa/equipment>` (no subclassing)** | Clears the check but is a **dead import** (imported, unused) and re-introduces DD-133 prefix ambiguity (`:`), requiring a compensating root `@prefix` declaration for no modeling benefit. |
| **Change the accelerator blueprint** | Blueprint is a managed reference-model asset; a hub-local model choice should not force a shared-asset change. Revisit only if the blueprint is corrected upstream via `kairos-toolkit-ops`. |

### Evidence

- `ontology-hub/model/ontologies/equipment.ttl` — imports `mmt/equipment` only.
- `ontology-hub/integration/sources/qargo/vocabulary/resources.vocabulary.ttl` —
  `resource_type` enum (`FULL_TRAILER`), `compatible_container_types = []`.
- `ontology-reference-models/.../DCSA/current/shared-kernel/equipment/equipment.ttl` —
  ISO-container model with mandatory `containerNumber`.
- `ontology-reference-models/accelerator-packs/logistics/.../data-domains.yaml` —
  `equipment` activates `mmt/equipment` + `dcsa/equipment`.
- Related: accelerator `LOG-BP-005 Equipment model` ("preserve distinct grains").

### Consequences

- Validation must be run with `--degraded` to pass cleanly; the non-degraded report
  will continue to list `missing_managed_import` for `dcsa/equipment`.
- If CLdN later handles genuine ISO ocean containers, revisit with a scoped
  `Container` subclass grounded in new source evidence.
