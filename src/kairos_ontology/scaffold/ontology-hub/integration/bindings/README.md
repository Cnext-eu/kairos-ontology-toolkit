# Entity bindings

Each `*.binding.yaml` file is the sole source-to-canonical execution authority for one source
relation or one ordinary contracted dbt model. Multi-source entities use separate bindings
with an explicit conformance contract.

Validate a domain without writing output:

```bash
kairos-ontology compile <domain> --check
```

Unknown fields and unresolved source columns or ontology terms are rejected.
Bindings never contain raw SQL and do not replace ontology or source-vocabulary TTL.
