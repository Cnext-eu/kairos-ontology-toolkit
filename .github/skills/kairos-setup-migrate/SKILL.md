---
name: kairos-setup-migrate
description: >
  Distinguish mechanical flat-layout migration from the required clean v5
  authoring rebuild.
---

# Layout Migration and V5 Rebuild

The retained `kairos-ontology migrate` command only moves files from the flat
folder layout into grouped `model/`, `integration/`, and `output/medallion/`
directories. It does not convert legacy semantic or execution metadata to v5.

Before running it, use `--check`, review every planned move, and preserve a clean
Git rollback point. Invoke it only when the requested outcome is mechanical
layout reorganization. It does not make an older hub v5-compatible.

V5 semantic authoring is a clean break. There is no dual-format hub or automated
contract upgrade path. For a v5 conversion, never mutate the old hub in place:

1. Create a fresh v5 repository with `kairos-setup-init`.
2. Inventory reusable business terminology, source schemas, OWL concepts, and SHACL constraints in
   the old repository.
3. Re-author accepted source vocabularies under `integration/sources/` and canonical meaning under
   `model/ontologies/`; validate every Turtle input.
4. Replace old mapping/execution metadata with closed
   `integration/bindings/*.binding.yaml` EntityBinding documents.
5. Move complex relational logic into ordinary contracted dbt SQL and properties YAML under
   `integration/transforms/dbt/models/`, referenced by `source.dbtModel`.
6. Run `compile --check`, review `compile --explain`, and emit into the fresh `output/` tree.
7. Compare business semantics and downstream dbt/platform tests before cutover.

Keep the old repository immutable for audit and rollback. Do not copy derived output or obsolete
execution metadata into the new hub.
