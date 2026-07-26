# Virtual-source column IRI convention and migration

New dbt contract vocabularies mint columns as:

```text
{virtual_source_iri}__{percent-encoded-column-name}
```

The stable `__` separator is part of Turtle `PN_LOCAL`, unlike `/`, so a namespace
ending immediately before the table local name can use values such as
`virtual:orders__order_id`. Contract column names are dbt identifiers
(`[A-Za-z_][A-Za-z0-9_]*`); percent encoding remains deterministic for API callers.

Legacy `{virtual_source_iri}/{percent-encoded-column-name}` full IRIs continue to
resolve. Ordinary `sync-dbt-contracts` preserves column identities already present in
a managed vocabulary and therefore does not silently migrate a hub.

The compatibility contract is vocabulary-led: an existing legacy vocabulary and its
legacy mappings continue to bind and project, while a new vocabulary uses only `__`
IRIs. The toolkit does not invent slash aliases for a newly generated vocabulary, so a
mixed new-vocabulary/old-mapping state fails resolution instead of binding ambiguously.
Run the migration while the legacy vocabulary is present; it changes the vocabulary and
all discovered mapping references in one reviewed operation.

Preview migration:

```text
kairos-ontology migrate-column-iris --hub ontology-hub
```

Apply only after reviewing the old/new IRI and file list:

```text
kairos-ontology migrate-column-iris --hub ontology-hub --apply \
  --backup-dir ../ontology-hub-column-iri-backup
```

Apply requires a new backup directory outside the hub and refuses to overwrite an
existing backup. The migration parses and rewrites source and mapping RDF with
`rdflib`, preserves unrelated triples, detects target collisions before writing, and
is idempotent.
