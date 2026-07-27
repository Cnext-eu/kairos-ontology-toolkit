---
name: kairos-develop-dbt-transformation
description: >
  Interactive v5 workflow for ordinary dbt SQL and properties YAML when an
  EntityBinding needs a contracted relational or grain-changing source model.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# Develop a Contracted dbt Transformation

Use this skill only when a direct relation plus closed scalar binding expressions
cannot express the required result. The outputs are ordinary dbt SQL and
properties YAML under `integration/transforms/dbt/models/`.

## Design fleet mode (DD-088)

Default is interactive. Confirm source relations, business meaning, output grain,
key columns, relational logic, fallback behavior, output columns/types, adapter
scope, tests, and the exact patch before writing.

An explicit AI-approved override applies only to this skill invocation and is
never inherited. Record rationale, confidence, and evidence for every AI-approved
checkpoint. Stop for ambiguity, low confidence, policy-sensitive choices,
destructive changes, or proprietary/PII risk.

## Workflow

1. Read the target ontology, source vocabulary, PII-safe samples, current binding,
   and existing dbt project files.
2. Confirm one output row grain and its physical key columns.
3. Present the proposed `source()`/`ref()` graph, relational operations, null and
   error behavior, deterministic ordering, and adapter assumptions. Obtain the
   active mode's checkpoint decision.
4. Author SQL with `source()` and `ref()`; do not hard-code physical relation names.
5. Author `version: 2` properties YAML with `config.contract.enforced: true`, every
   output column name/type, focused dbt tests, and `meta.kairos` containing grain,
   `grain_key`, target class, `virtual_source_iri`, and supported adapters. The
   legacy-named IRI identifies the contracted model output only; do not generate a
   separate virtual-source artifact or registry.
6. Validate with the dbt commands already configured by the project. Fix parse,
   contract, compile, and focused test failures before handoff.
7. Return to **kairos-design-mapping**. Set `source.dbtModel.name`, `sqlPath`, and
   `contractPath`; make binding grain and source key exactly match the contracted
   `grain_key`.
8. Run the stateless binding feedback loop:

   ```powershell
   $env:KAIROS_SKILL_CONTEXT = "1"
   uv run kairos-ontology compile <domain> --check --format text
   uv run kairos-ontology compile <domain> --explain --format text
   ```

The dbt output contract is physical source authority. It does not define canonical
ontology meaning, and this skill does not emit generated Kairos artifacts.
