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

1. Inspect the supplied CSV, Excel, Parquet, extracted YAML, DDL, API schema, or existing TTL, and
   enumerate every source available for import (each `.input/` file or per-source subfolder, each
   extracted schema YAML, or DDL) so the full candidate set is known before importing anything.
2. When more than one source is available, ask the user whether to import all sources in one batch
   or select a subset. In fleet mode, default to importing every candidate and record the decision
   with its rationale.
3. Set `KAIROS_SKILL_CONTEXT=1` before skill-owned CLI calls.
4. For flat files, run `kairos-ontology import-flatfile --from <path> --system <name>`. Directory
   mode only reads the top level (non-recursive); pass `--recursive` for a nested export tree.
   Legacy `.xls` is recognized but never readable — ask the user to convert to `.xlsx` first.
5. For extracted schema YAML, run
   `kairos-ontology import-source --from <path> --system <name>`.
6. For a batch, run the matching import command once per selected source (or point `--from` at a
   parent directory where the CLI already accepts one). Continue past a single source failure so the
   remaining sources still import, and record each failure and its reason.
7. Review relation names, column names, physical types, nullability, keys, descriptions, and
   redacted samples. Never expose credentials or unredacted sensitive values.
8. Parse every generated Turtle file with `rdflib`; use `kairos-ontology validate` through
   `kairos-execute-validate` when ontology or SHACL checks are required.
9. After the batch completes, show a short report listing which sources were imported (name and
   the generated `integration/sources/<source>/` path) and which remain un-imported or failed, with
   the reason. Confirm the remaining set with the user before continuing.
10. Once sources are settled, offer to import any Power BI / TMDL analysis the user has as **demand
    evidence, not a source**. Run `kairos-ontology import-tmdl <pbip.zip | SemanticModel/ |
    file.tmdl>`; it lands an Engineering Pack and a Concept Mapping template under
    `integration/discovery/bi/`. Never place it under `integration/sources/` or bind it as a source
    relation — it informs ontology and Gold design only. Fold each imported or skipped BI input into
    the same report from step 9.
11. When semantic source analysis is requested, select and disclose the AI provider immediately
    before the call, obtain invocation-scoped consent, and run `analyse-sources`. Report provider,
    authentication mode, and variable names only—never secret values. Preserve deterministic
    imports when AI analysis is skipped.
12. Hand authoritative source relations to `kairos-design-mapping`, which authors closed
    `integration/bindings/*.binding.yaml` documents.

Do not author canonical classes here. Do not create execution policy in RDF. Complex relational
logic belongs in an ordinary contracted dbt SQL model plus dbt properties YAML under
`integration/transforms/dbt/models/`, referenced by `source.dbtModel` in an EntityBinding.
