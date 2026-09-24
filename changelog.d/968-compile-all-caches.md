### Performance
- **`compile --all` no longer re-reads unchanged inputs for every domain (#968).** On a
  15-domain hub, `compile --all --check` went from 91 s to 57 s, with byte-identical
  output. The emit path, which runs the same analysis, benefits the same way.
  - The disposition ledger was parsed twice per domain. `load_dispositions` is now
    memoised per process, keyed on each ledger file's path, modification time and size,
    so a write in the same run is still seen.
  - The same bronze source `.ttl` files were parsed once per domain (187 times on that
    hub). They are now parsed once per process, with the same key.
  - The YAML reads on the compile path (bindings, contracts, dbt sources, the alignment
    report, the conformance artifact, the Silver projector) use PyYAML's C loader when it
    is available, as the ledger already did.
