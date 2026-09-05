# Create a hub

**Skill:** `kairos-setup-init`

A hub holds authored inputs only — meaning, source schemas, and the bindings between them.
Generated artifacts land in a *sibling* directory, never inside the hub.

## In an existing, empty directory

```bash
kairos-ontology init --company-domain acme.example --domain party
```

`--company-domain` is required: it is the namespace base, so classes resolve under
`https://acme.example/ont/`. `--domain` is optional and scaffolds a starter ontology file.

Add `--adapter databricks` if the warehouse is Databricks; the default is
`fabric-warehouse`. The value lands in `kairos.yaml` and decides the SQL dialect the
compiler emits, so it is worth setting correctly now rather than after a first release.

## As a new GitHub repository

```bash
kairos-ontology new-repo acme-hub --company-domain acme.example
```

This additionally runs `git init`, creates the remote, and configures branch protection on
`main`.

## What you get

```
kairos.yaml                        namespace, adapter, selected roots
model/ontologies/<domain>.ttl      canonical meaning
model/shapes/                      optional SHACL
integration/sources/               source-system vocabularies
integration/bindings/              one closed EntityBinding per source relation
integration/transforms/dbt/models/ contracted dbt SQL for logic a binding cannot express
decisions/                         durable rationale
../ontology-hub-publish/           generated output, sibling of the hub
```

## Verify

```bash
kairos-ontology update --check
```

This must exit 0 on a hub that was just created: it confirms every toolkit-managed file is
present and current, and it is the same check `managed-check.yml` runs on every pull
request.

Do **not** expect `kairos-ontology validate` to pass yet. It fails on a fresh hub with
"No business discovery evidence found" — that gate is deliberate, and clearing it is the
next step.

## Next

[Capture business context](capture-business-context.md).
