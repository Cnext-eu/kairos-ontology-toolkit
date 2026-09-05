# Import a source system

**Skill:** `kairos-design-source`

Produces `integration/sources/<system>/<system>.vocabulary.ttl` — the authoritative
description of what physically exists: relations, columns, types, nullability, and
redacted sample metadata. It is an authored input, not generated output, and the compiler
rejects a binding that references a column it does not declare.

## From a live database

```bash
kairos-ontology import-source --from "<connection>" --system crm
```

Useful flags:

- `--dry-run` — see what would be written before writing it.
- `--split-tables` — one file per relation instead of one per system.
- `--enum-threshold N` — treat a low-cardinality column as an enumeration.
- `--redact-pii` — redact sample values at import. **Opt-in** since DD-214: the pre-send
  scan advises rather than refuses, so this is a decision you make, not a default you
  inherit.

## From flat files

Drop CSV or Excel into `.input/`, then:

```bash
kairos-ontology import-flatfile --from .input/crm --system crm
kairos-ontology import-source --from .input/crm --system crm
```

`import-flatfile` infers structure; `import-source` turns it into the bronze vocabulary
TTL. `--max-rows` and `--sample-size` bound the work on large extracts.

## Verify

```bash
kairos-ontology show-source-schema --system crm
```

`kairos-ontology validate` covers source vocabularies too, but only once the hub has
discovery evidence — see [Capture business context](capture-business-context.md).

## Before you commit

Never commit credentials, raw personal data, connection strings, or proprietary samples.
Use synthetic values, or redact persisted examples. Most of `.import/` is gitignored for
this reason, but `.import/modeling/` is deliberately tracked — check what you are adding.

## Next

[Design a domain](design-a-domain.md), or if the canonical model already exists,
[bind a source to an entity](bind-a-source-to-an-entity.md).
