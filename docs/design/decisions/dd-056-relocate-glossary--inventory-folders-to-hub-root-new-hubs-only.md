# DD-056: Relocate Glossary & Inventory Folders to Hub Root (New Hubs Only)

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `init`, `new-repo`, `migrate`, `generate-inventory`, `check-inventory`,
hub scaffold layout, design skills (discovery/domain/mapping/source/help/setup-init)
**Implementation:** `src/kairos_ontology/cli/main.py`,
`src/kairos_ontology/scaffold/ontology-hub/businessdiscovery/` (moved),
skills (both copies), `CHANGELOG.md`

### Context

Two hub folders lived under `model/`: the company business glossary
(`model/glossary/`, DD-048) and the materialized reference-model inventories
(`model/inventory/`, DD-044/DD-054). Neither is part of the **domain model** itself —
the glossary is a business-discovery artifact (a SKOS overlay) and the inventory is an
unpacked, read-only view of the reference models. Nesting them under `model/` (which
holds the authored ontologies, shapes, extensions, mappings) blurred that distinction.

### Decision

Move both folders up to the hub root and rename them to reflect their purpose:

| Old | New |
|-----|-----|
| `ontology-hub/model/glossary/` | `ontology-hub/businessdiscovery/` |
| `ontology-hub/model/inventory/` | `ontology-hub/referencemodels-unpacked/` |

`init`/`new-repo` scaffolding, the `generate-inventory`/`check-inventory` default
paths, and all design skills now use the new locations. The `migrate` command creates
the new inventory directory name for layout consistency.

Scope is **new hubs only** — no automatic relocation of existing-hub data. Existing
hubs move the two folders manually (the inventory can simply be regenerated with
`generate-inventory`).

### Rationale

The names are self-describing: `businessdiscovery/` pairs with the
`.sessions-design/businessdiscovery-*.md` session files and the repo-root
`.import/businessdiscovery/` inputs, and `referencemodels-unpacked/` makes clear the
folder is a derived/unpacked view rather than authored model content. Limiting the
change to new hubs avoids destructive moves in existing repos; an explicit
auto-migration was rejected as out of scope and risky for committed data.

### Consequences

- New hubs no longer have `model/glossary/` or `model/inventory/`.
- `referencemodels-unpacked/` continues to hold **both** hub-ontology and
  reference-model inventories (single-folder behaviour unchanged; only the path moved).
- Existing hubs keep working only after a manual move/regeneration; the CHANGELOG
  documents the manual step.
