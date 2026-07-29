# Source system

Rename this folder to a lowercase, hyphenated system identifier.

## Reviewed metadata

| Field | Value |
|---|---|
| System identifier | `sample-system` |
| Owning team | _team name, not an individual's contact details_ |
| Source type | _API, database, or file_ |
| Contract version | _version or date_ |

Keep authoritative source-vocabulary TTL in this folder. Supporting DDL/OpenAPI/schema
material may be included only when redistribution is allowed and secrets, personal data,
internal URLs, and proprietary samples have been removed.

## Workflow

1. Import reviewed schema metadata with `import-source` or `import-flatfile`.
2. Review the generated vocabulary TTL and redact persisted examples.
3. Create one closed EntityBinding for each selected relation.
4. Run `kairos-ontology compile <domain> --check`.

Do not store credentials or connection strings. Use synthetic sample values.
