### Added
- **A conformed dimension can be shared across Gold products (issue #829, DD-228).** A new
  `gold.shared_domains` list in `kairos.yaml` names the domains several products may claim:

  ```yaml
  gold:
    shared_domains: [party, reference-data]
    products:
      - name: shipment-performance
        domains: [consignment, party, reference-data]
      - name: financial-performance
        domains: [billing, party, reference-data]
  ```

  DD-222 fixed the one-owner rule on *domains*, while the thing that must not be duplicated
  is a *table*. Those coincide for a fact-bearing domain and diverge for a dimension-only
  one — which is exactly what a conformed dimension is. A hub that needed `party` in two
  products had to choose between one product absorbing everything, or shipping a model
  whose customer slicer has no customer table.

  Sharing is **declared, never inferred**. Guessing it from a domain having no facts would
  mean that adding the first fact silently re-materializes all of its tables in every
  consuming product — a change in physical layout with no edit to say so.

- **`emit-gold` reports which tables a product builds and which it reads.** The issue's
  explicit ask. The product report carries `materialized_by: {domain, shared: true}`, the
  DDL block names the owning domain, and the emit prints the split:

  ```
  1 table(s) built by this product, 1 read as shared:
      dim_customer (owned by party)
  ```

### Notes
- **The materialization premise in the issue was wrong, and worth recording.** A Gold dbt
  model is emitted per *domain*, to `models/gold/<domain>/<table>.sql`, by that domain's
  own `compile --emit`; products exist only in the Power BI lane. So a conformed dimension
  was always built exactly once, and sharing changes only which semantic models may read
  it. That is why this change is as small as it is.
- A shared table keeps its own domain's `goldSchema`, so both products' TMDL partitions
  name `gold_party` and point at the one physical relation. Verified end-to-end rather
  than assumed — it is the assumption that would otherwise produce a model silently
  reading the wrong schema, discovered in Fabric.
- `emit-gold <shared-domain>` now fails with `gold.domain-shared-across-products` naming
  every product that reads it, rather than picking one arbitrarily.
- A genuine table-name collision still fails: sharing relaxes *who materializes* a table,
  not whether two different tables may carry one name.
- Undeclared sharing still fails with DD-222's original message, which now also names
  `gold.shared_domains` as the way to say otherwise.
