---
name: kairos-develop-dbt-transformation
description: >
  Interactive, evidence-grounded workflow for creating and updating contracted
  advanced dbt transformations that feed generated Kairos Silver models. Use for
  joins, windows, rankings, aggregations, JSON expansion, fallback rules, or grain
  changes that exceed normal SKOS mapping expressions. NOT for ordinary mappings
  (kairos-design-mapping) or merely running projections (kairos-execute-project).
---

# Develop Contracted dbt Transformation

Create or update a handwritten dbt intermediate model while preserving the Kairos
semantic boundary:

- dbt SQL owns executable relational logic;
- dbt contract YAML owns physical output columns and types;
- ontology and glossary own business meaning;
- SKOS owns virtual-source-to-domain meaning;
- Silver extensions own semantic natural keys, SK/FK/SCD policy;
- `meta.kairos.decisions` owns rationale, evidence, confidence, and approval;
- dbt unit/data tests provide executable evidence; and
- generated Silver remains the public ontology-aligned model.

This skill is **interactive by default**. Never generate a complete transformation and
silently approve its grain, identity, mappings, or Silver policy.

## Hard gates

1. **Evidence before SQL.** Read the relevant glossary, ontology, sources, mappings,
   Silver extensions, and existing dbt artifacts before proposing a contract.
2. **Grain before columns.** Obtain explicit approval of the semantic target, row grain,
   entity-versus-association choice, identity, overlap, deduplication, and survivorship.
3. **Contract before implementation.** Approve output columns/types, physical key columns,
   adapter support, decisions, and tests before writing SQL.
4. **No invented inputs.** Every source column, relationship, and business rule needs a
   supporting artifact. Mark gaps and assumptions; do not hide them in SQL.
5. **No semantic bypass.** Route ontology changes to `kairos-design-domain`, mappings to
   `kairos-design-mapping`, and SK/FK/SCD policy to `kairos-design-silver`.
6. **Preserve authored SQL.** Show a diff and obtain approval before replacing or
   substantially restructuring an existing custom model.
7. **No weakened acceptance.** Never remove tests, loosen a contract, or lower decision
   confidence merely to make validation pass.
8. **No sensitive context.** Do not place credentials, raw PII, proprietary sample values,
   or internal connection details in prompts, SQL comments, fixtures, decisions, or logs.

## Design fleet mode

Fleet mode is active only when the user explicitly requests fleet, autopilot, or
AI-approved design decisions for this task.

In fleet mode:

- retain every phase and validation gate;
- record rationale, confidence, and evidence for every AI-made checkpoint;
- use `status: ai_approved`, never `developer_approved` or `stakeholder_approved`;
- mask sample evidence and avoid proprietary content; and
- stop for low confidence, grain/identity ambiguity, governance-sensitive rules,
  destructive replacement, licensing concerns, or PII risk.

## Lifecycle state

Store resumable state at:

```text
ontology-hub/.kairos-state/phases/dbt-transformation/<model>.md
```

Create the file before writing transformation artifacts. Use OKF frontmatter:

```yaml
---
type: kairos-phase-log
phase: dbt-transformation
instance: <model>
status: in-progress
last_updated: <ISO-8601 timestamp>
---
```

Record:

- target class and approved grain;
- semantic natural-key properties and physical key columns;
- selected source tables/models;
- evidence inventory;
- approved decision IDs and statuses;
- files created or updated;
- semantic-skill handoffs;
- synchronization/projection/validation results;
- unresolved questions; and
- the next safe action.

Do not edit `.kairos-state/status.md`; `kairos-flow` owns global continuation state.

## Phase 1 — Preflight and evidence packet

1. Locate the hub from the current directory.
2. Read the phase log if it exists and offer to resume.
3. Confirm these inputs exist:
   - `businessdiscovery/` glossary and approved business context;
   - `model/ontologies/`;
   - `integration/sources/` vocabularies and available profiling metadata;
   - `model/mappings/`;
   - `model/extensions/*-silver-ext.ttl`;
   - `integration/transforms/dbt/` when updating an existing model.
4. Select one transformation and one semantic target.
5. Build a bounded evidence packet containing only relevant:
   - glossary concepts and definitions;
   - ontology classes/properties/relationships/ranges;
   - masked source column evidence and analysis;
   - existing mappings and confidence;
   - Silver key/FK/SCD annotations and claims;
   - existing custom SQL/contracts/macros/tests;
   - generated virtual vocabulary and projection reports;
   - manifest dependencies when available; and
   - selected adapter and approved package constraints.
6. Report missing, conflicting, or inferred evidence separately.

If source or domain evidence is incomplete, stop and route to the owning design skill.

## Phase 2 — Grain and identity checkpoint

Present and approve:

| Decision | Required content |
|---|---|
| Semantic target | Existing class, proposed class, or association |
| Row grain | One precise sentence beginning “one row per…” |
| Semantic key | Ontology properties identifying the row |
| Physical key | Contract output columns realizing the semantic key |
| Source overlap | Whether branches can represent the same business entity |
| Deduplication | Partition, ordering, and tie behavior |
| Survivorship | Winning values where identities overlap |
| Null policy | Behavior for every key component |

Do not proceed while the target might be the wrong entity or association.

If the ontology must change, invoke `kairos-design-domain` and resume after validation.

## Phase 3 — Contract and decision checkpoint

Propose the dbt contract before SQL:

- model name and description;
- `table`, `view`, or supported `incremental` materialization;
- every output column name, type, description, and required test;
- `meta.kairos.target_class`;
- stable `meta.kairos.virtual_source_iri`;
- approved grain sentence;
- supported adapters (`fabric`, `databricks`);
- physical natural-key columns;
- approved required packages/macros; and
- `meta.kairos.decisions`.

For each non-trivial rule, record:

```yaml
- id: route-fallback
  statement: Use booking route, then stops, then shipment header.
  evidence:
    - artifact: businessdiscovery/glossary.ttl
      subject: https://example.com/glossary#ShippingRoute
  confidence: high
  status: proposed
  implemented_by:
    model: int_shipment_conformed
  verified_by:
    - unit_test_route_fallback
```

Rules:

- `ai_inferred` is not an approval state; unapproved inference is `proposed`.
- Approved states require actor and timestamp.
- Evidence paths are repository-relative.
- RDF subjects must exist in the referenced artifact.
- `implemented_by` names a dbt model, never an internal CTE.
- `verified_by` names existing or planned dbt tests.
- Decision text is descriptive metadata, never executable configuration.

Wait for approval before creating or replacing the contract.

## Phase 4 — Implement SQL and tests

Place authoritative inputs under:

```text
integration/transforms/dbt/
  models/intermediate/<area>/<model>.sql
  models/intermediate/<area>/<model>.yml
  macros/<area>/<hub-or-domain>__<macro>.sql
  tests/<area>/assert_<model>_<behavior>.sql
```

Implementation rules:

- use `source()` and `ref()`, never hard-coded physical relations;
- keep source normalization, joins, windows, aggregation, fallback, and grain formation in
  the custom model;
- emit canonical business values rather than final Silver SK/FK/IRI values;
- prefix custom macros with `<hub-or-domain>__`;
- never use the reserved `kairos_` prefix;
- use only toolkit-approved package dependencies;
- write adapter-portable SQL or explicit adapter dispatch for Fabric and Databricks;
- alias joined inputs so dbt unit tests can mock them;
- add unit tests for windows, ranking, fallback, complex cases, and regressions;
- add data tests for key uniqueness/non-nullness, accepted values, relationships, grain,
  and fan-out;
- omit raw sensitive values from fixtures; and
- preserve existing user-authored structure unless replacement was approved.

Show the proposed diff and update the phase log.

## Phase 5 — Synchronize semantic surfaces

1. Set `KAIROS_SKILL_CONTEXT=1`.
2. Run:

   ```text
   kairos-ontology sync-dbt-contracts
   ```

3. Inspect the generated managed vocabulary under
   `integration/sources/custom-transformations/`.
4. Invoke `kairos-design-mapping` to map the virtual table and columns through SKOS.
5. Invoke `kairos-design-silver` to confirm `silverSourceRef`, semantic natural key,
   SCD policy, and supported FKs.
6. If either skill changes the semantic target or identity, return to Phase 2 and update
   the contract rather than forcing the previous design.
7. Run `sync-dbt-contracts --check` after semantic handoffs.

Never hand-edit the managed virtual vocabulary.

## Phase 6 — Project and validate

For each required platform:

1. Invoke `kairos-execute-project` or run the skill-managed projection flow with:

   ```text
   kairos-ontology project --target dbt --platform <fabric|databricks>
   ```

2. Validate:

   ```text
   kairos-ontology validate-dbt --platform <fabric|databricks>
   ```

3. Distinguish:
   - contract, SQL, Jinja, dependency, manifest, and reference failures: fix and rerun;
   - credential, driver, network, or warehouse-introspection failures: record as
     environment-blocked;
   - runtime grain/data failures: require a configured warehouse and do not claim
     production readiness without them.
4. Confirm the generated Silver wrapper references the custom model and owns only the
   approved SK/IRI/SCD/FK behavior.
5. Update decision/test references and repeat synchronization if the contract changed.

## Completion gate

The transformation is ready for review when:

- grain and identity are approved;
- contract and decision metadata validate;
- the managed vocabulary is synchronized;
- SKOS mappings and Silver policy passed their owning skill gates;
- custom resources are self-contained and collision-free;
- Fabric and Databricks parse successfully;
- compile succeeds or is explicitly environment-blocked;
- unit/data tests exist for every recorded decision;
- no secrets, PII, or proprietary fixtures are present; and
- the phase log contains no unresolved blocking question.

Warehouse-backed tests remain required before production publication even when toolkit
offline validation is complete.
