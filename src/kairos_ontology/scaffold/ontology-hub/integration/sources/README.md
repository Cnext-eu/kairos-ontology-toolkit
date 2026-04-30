# Sources — Source System Reference Documentation

This folder is the formal location for managing **source system reference
documentation**. The files stored here inform the creation of bronze vocabulary
TTL files in the `bronze/` folder.

## Purpose

Before you can model a bronze vocabulary for a source system you need to
understand its structure: tables, columns, data types, API endpoints, and sample
payloads. Collect that reference material here so it is versioned alongside the
ontology and available to every team member.

## Folder structure

Each source system gets its **own subfolder**, named in **lowercase with
hyphens**:

```
sources/
├── README.md                        ← this file
├── adminpulse/
│   ├── README.md                    ← system description & contacts
│   ├── adminpulse-api-spec.yaml     ← OpenAPI / Swagger spec
│   ├── adminpulse-sample.json       ← sample API response
│   └── notes.md                     ← observations, gotchas
├── erp-navision/
│   ├── README.md
│   ├── navision-ddl.sql             ← SQL DDL export
│   ├── navision-sample.csv          ← sample data extract
│   └── notes.md
└── source-system-template/
    └── README.md                    ← copy this when adding a new system
```

## What to put in a source subfolder

| File type | Examples | Notes |
|-----------|----------|-------|
| **API specs** | OpenAPI YAML/JSON, WSDL, GraphQL schema | Machine-readable preferred |
| **SQL DDL exports** | `CREATE TABLE` scripts, ER diagrams | Export from the source DB |
| **Sample data** | JSON payloads, CSV extracts, XML samples | Anonymised — no real PII |
| **Documentation** | Vendor docs, data dictionaries, PDF exports | Keep concise and relevant |
| **Notes** | `notes.md` with observations, caveats | Free-form team knowledge |

> **Important:** Never commit real credentials, tokens, or personally
> identifiable information into this folder. Anonymise or redact sample data
> before committing.

## From sources to bronze vocabulary

The bronze vocabulary TTL files in `bronze/` are **derived from** the reference
docs stored here. Use the **`kairos-ontology-medallion-source`** Copilot skill to
generate or update a bronze vocabulary from source documentation:

1. Place your source reference files in `sources/<system-name>/`.
2. Invoke the `kairos-ontology-medallion-source` skill.
3. The skill reads the source docs and produces (or updates) the corresponding
   bronze vocabulary TTL in `bronze/`.

## Adding a new source system

1. Copy `sources/source-system-template/` to `sources/<system-name>/`.
2. Fill in the template README with system details.
3. Add your reference files (API specs, DDL, samples).
4. Commit and push.
