# dbt contract identity evidence

Run dbt tests in a configured warehouse, then capture the actual results:

```text
kairos-ontology capture-dbt-contract-evidence \
  --run-results target/run_results.json --manifest target/manifest.json
kairos-ontology sync-dbt-contracts
```

The generated `contract-identity.json` is tied to the canonical contract content hash.
Contract YAML, SQL, grain key, declared tests, CDC bindings, decisions, or replacement
lineage changes make prior evidence stale. Declared tests alone are not passing evidence.
Both artifacts must come from one invocation and carry matching invocation IDs and dbt
versions. An ordinary standard v12 manifest is sufficient: current model SQL is checked using
its `original_file_path`, `raw_code`, and dbt SHA-256 checksum; current contract YAML semantics
and exact generic, singular, and unit-test definitions are checked against standard manifest
fields. No custom manifest mutation or post-run hash is required. Unbound or v1 evidence is
rejected.
