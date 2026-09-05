# Design a domain

**Skill:** `kairos-design-domain`

A domain is one `model/ontologies/<domain>.ttl` file: one independently deployable set of
canonical meaning. The filename is the domain identifier.

## Scaffold

```bash
kairos-ontology scaffold-domain --domain billing --label "Billing"
```

`--from-blueprint` starts from an accelerator blueprint instead of an empty file.

## Conventions the compiler relies on

- One domain per file; classes `PascalCase`, properties `camelCase`.
- Every file declares an `owl:Ontology` with `rdfs:label` and `owl:versionInfo`.
- A property's local name becomes the physical Silver column name, so **renaming a
  property renames a column** downstream. Name deliberately; DD-213 introduces a declared
  contract that decouples the two.

## Inspect without reading the file

```bash
kairos-ontology show-class-inventory --domain billing
kairos-ontology list-class-properties "https://acme.example/ont/billing#Invoice"
kairos-ontology explain-term "https://acme.example/ont/billing#Invoice"
```

Use these rather than opening the `.ttl`. Reading serialised RDF as text does not reveal
inherited properties, imported terms, or inverse relations (DD-103).

## Align to reference models

```bash
kairos-ontology propose-alignment --domains billing
kairos-ontology coverage-report
```

Alignment is advisory: it suggests reference-model terms your domain could adopt. Adopt
deliberately — an equivalence you did not mean is harder to remove later than to skip now.

## Verify

```bash
kairos-ontology validate --domain billing
```

## Next

[Bind a source to an entity](bind-a-source-to-an-entity.md).
