# BI / report demand evidence

This folder holds **Power BI / TMDL analysis** imported with
`kairos-ontology import-tmdl`. It is **downstream demand evidence**, not a canonical
input source. It describes how the business already reports on the data — valuable
signal for ontology and Gold design — but it never defines source relations or
canonical entities.

```text
discovery/
├── core-concepts-conformance.yaml   # business-discovery demand (DD-090)
└── bi/                              # this folder — Power BI / TMDL demand evidence
    ├── <model>-engineering-pack.md   # table/column/measure inventory
    └── <model>-concept-mapping.yaml  # reference-model alignment (fill in
                                       # reference_model_match by hand)
```

## Import

```
kairos-ontology import-tmdl <pbip.zip | SemanticModel/ | file.tmdl>
```

The default output is this folder. Do **not** import TMDL under
`integration/sources/` — a Power BI model is not a source system and must never be
bound as a source relation in an `EntityBinding`.

## How it is used

- `import-tmdl` writes an Engineering Pack and a Concept Mapping template here.
- A modeler fills in `reference_model_match` in the concept-mapping YAML.
- `design-landscape` reads the filled matches as an **advisory** `bi_weight` signal
  that may only re-rank the `demanded-but-unbound` backlog — it never changes a
  class's classification.
- `kairos-design-domain` and `kairos-design-gold` treat it as demand, never as
  business authority.

## Privacy

Never commit credentials, connection strings, raw personal data, or proprietary
report content. Redact or synthesize any persisted values.
