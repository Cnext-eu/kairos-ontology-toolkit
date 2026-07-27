---
name: kairos-design-silver
description: >
  Retired v5 compatibility redirect. Author physical load, identity,
  relationship, and quality policy in a closed EntityBinding instead.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# Silver Design Is Folded into EntityBinding

This skill has no v5 authoring surface and writes no files. Canonical semantics
belong in `model/ontologies/<domain>.ttl`; physical materialization policy belongs
in `integration/bindings/*.binding.yaml`; complex relational logic belongs in
ordinary dbt SQL and properties YAML.

Route the request as follows:

- canonical class/property meaning → **kairos-design-domain**;
- grain, identity, load/SCD, field expressions, relationships, or quality checks
  → **kairos-design-mapping**;
- joins, windows, aggregation, ranking, deduplication, JSON expansion, fallback,
  or a grain-changing model → **kairos-develop-dbt-transformation**;
- artifact check, explanation, or emission → **kairos-execute-project**.

Do not create a separate Silver policy document. The closed `EntityBinding` and
the stateless compiler are the complete v5 materialization contract.

## Design fleet mode (DD-088)

Default is interactive in the destination design skill. Preserve all mandatory
checkpoints before accepting ontology, binding, or dbt changes. An explicit
AI-approved override applies only to this skill invocation and is never inherited
by the destination skill; start that skill in interactive mode unless the user
explicitly grants a new override. Record rationale, confidence, and evidence for
each AI-approved choice, and stop for ambiguity, low confidence,
policy-sensitive choices, destructive changes, or proprietary/PII risk.
