# Contracted dbt output identity

Synchronized dbt contracts emit a typed `kairos-dbt:ContractIdentity` at
`{virtual_source_iri}/contract-identity`. It is a DD-108 source/output authority only:
it does not establish domain or enterprise business identity.

The resource records the model and virtual table, ordered grain columns, replacement
lineage, decision evidence/status, required uniqueness/non-null checks, optional canonical
CDC output bindings, and a SHA-256 hash of the identity-relevant contract plus SQL.

Declared dbt tests are not passing evidence. After executing tests against a configured
warehouse, capture the actual dbt artifacts:

```text
kairos-ontology capture-dbt-contract-evidence \
  --run-results target/run_results.json \
  --manifest target/manifest.json
kairos-ontology sync-dbt-contracts
```

Evidence is written to
`integration/transforms/dbt/evidence/contract-identity.json`. Only passing dbt `unique`,
`not_null`, or `dbt_utils.unique_combination_of_columns` results are accepted. Missing or
stale evidence blocks with `identity.contract-unverified`. Changes to contract fields, SQL,
grain key, tests, CDC bindings, decisions, or source replacements change the content hash.

Capture requires `run_results.json` and `manifest.json` from the same dbt invocation:
both must provide equal, non-empty `metadata.invocation_id` and `metadata.dbt_version`.
The standard v12 manifest must contain exactly one model node at the current
`original_file_path`. Its dbt SHA-256 checksum and `raw_code` must match the current SQL.
Standard model fields must match the current contract YAML semantics, including descriptions,
meta, config/contract, columns, data types, and constraints. Current generic tests, singular
tests that reference the model, and unit-test definitions must have exact standard manifest
nodes; required generic and singular test results must pass in the matching invocation.

No custom manifest fields or post-run hashes are required or accepted. Missing, ambiguous,
stale, or mismatched artifacts are rejected without replacing existing evidence. Evidence v1
is intentionally not trusted; rerun and capture to produce v2 evidence.

New synchronized columns use the canonical `__` IRI separator. Existing slash-delimited
column IRIs remain valid and ordinary synchronization preserves them.
