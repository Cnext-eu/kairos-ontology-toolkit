# Source vocabularies

Each source subdirectory contains the authoritative source-vocabulary TTL used by the v5
compiler. It describes relations, columns, types, nullability, and redacted metadata; it is
not generated output.

```text
sources/
├── sample-crm/
│   ├── sample-crm.vocabulary.ttl
│   └── README.md
└── sample-erp/
    └── sample-erp.vocabulary.ttl
```

Import or refresh source metadata with `import-source` or `import-flatfile`, review the
result, then reference a relation from exactly one EntityBinding. Complex relational logic
belongs in ordinary contracted dbt SQL/YAML referenced by `source.dbtModel`.

Never commit credentials, raw personal data, internal connection strings, or proprietary
samples. Use synthetic values or redact persisted examples.
