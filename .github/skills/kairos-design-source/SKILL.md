---
name: kairos-design-source
description: Import, document, redact, and analyse source-system schemas for v5 hubs.
---

# Kairos Source Design

Create authoritative Bronze inputs under `integration/sources/<source>/`. Source vocabularies and
redacted samples describe physical relations and columns; they do not define canonical entities.

## Design fleet mode (DD-088)

Default is interactive. An explicit fleet override applies only to this skill invocation and is
never inherited. Record rationale, confidence, and input references for every AI-approved choice.
Stop for ambiguous semantics, low confidence, secrets, PII, proprietary data, or destructive changes.

## Workflow

1. Inspect the supplied CSV, Excel, Parquet, extracted YAML, DDL, API schema, or existing TTL.
2. Set `KAIROS_SKILL_CONTEXT=1` before skill-owned CLI calls.
3. For flat files, run `kairos-ontology import-flatfile --from <path> --system <name>`.
4. For extracted schema YAML, run
   `kairos-ontology import-source --from <path> --system <name>`.
5. Review relation names, column names, physical types, nullability, keys, descriptions, and
   redacted samples. Never expose credentials or unredacted sensitive values.
6. Parse every generated Turtle file with `rdflib`; use `kairos-ontology validate` through
   `kairos-execute-validate` when ontology or SHACL checks are required.
7. When semantic source analysis is requested, select and disclose the AI provider immediately
   before the call, obtain invocation-scoped consent, and run `analyse-sources`. Report provider,
   authentication mode, and variable names only—never secret values. Preserve deterministic
   imports when AI analysis is skipped.
8. Hand authoritative source relations to `kairos-design-mapping`, which authors closed
   `integration/bindings/*.binding.yaml` documents.

Do not author canonical classes here. Do not create execution policy in RDF. Complex relational
logic belongs in an ordinary contracted dbt SQL model plus dbt properties YAML under
`integration/transforms/dbt/models/`, referenced by `source.dbtModel` in an EntityBinding.
