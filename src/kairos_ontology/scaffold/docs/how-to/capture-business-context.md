# Capture business context

**Skill:** `kairos-design-discovery`

Discovery comes before ontology and binding design, and it is not optional: `validate`
fails on a hub with no discovery evidence —

```
No business discovery evidence found (neither businessdiscovery/*.ttl nor
integration/discovery/core-concepts-conformance.yaml) — run kairos-design-discovery first.
```

That gate exists because a canonical model built without agreeing what the business means
first is a model of one person's assumptions. Discovery is where the terms get confirmed.

## What it produces

Evidence under `integration/discovery/` and `businessdiscovery/`: confirmed concepts, the
company glossary, and a conformance record showing which core concepts this hub covers.

## Check where you stand

```bash
kairos-ontology discovery-status
kairos-ontology discovery-conformance summarize
```

`discovery-status` reports what evidence exists. `--strict` turns warnings into a failing
exit code; `--warn-only` does the opposite. The `discovery-conformance` group has the
verbs that build and review the record — `build`, `judge`, `review`, `confirm`,
`validate`, `list-archetypes`.

## Register a confirmed concept

```bash
kairos-ontology register-concept --label "Invoice" --domain billing \
  --rationale "Confirmed with finance: one per issued document, not per line" \
  --decided-by finance-team
```

`--needs-confirmation` records a concept that is not yet agreed, so the gap stays visible
instead of being quietly assumed. `--source-evidence` and `--reference` attach where the
definition came from.

## Build the glossary

```bash
kairos-ontology build-glossary --company-name Acme --company-domain acme.example
```

Produces the SKOS company glossary from confirmed extractions (DD-062). The glossary is an
input to alignment later, not decoration.

## Verify

```bash
kairos-ontology discovery-status --strict
kairos-ontology validate
```

`validate` should now get past the discovery gate. If it still reports no evidence, the
extraction directory is not where the command is looking — check `--extraction-dir` and
`--import-dir`.

## Next

[Import a source system](import-a-source-system.md), then
[design a domain](design-a-domain.md).
