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

- `import-tmdl` writes an Engineering Pack and a Concept Mapping template here, plus a
  **report usage** summary for every `*.Report` folder in the export that has pages. Usage
  answers what a model inventory cannot: which of a model's ~90 measures a report actually
  *places on a visual*, and which attributes people filter on. Counts only — never visual
  definitions, positions, filter values, titles, images or themes.
- `insights.yaml` is **authored**, not imported: personas, the questions they need
  answered, the KPI that answers each, and the canonical measures and dimensions it needs.
  `emit-gold` checks every `confirmed` insight against the emitted product, reports what is
  missing, and writes an insight brief beside the semantic model for whoever builds the
  report. `kairos-design-gold` walks you through writing it, using the harvested usage as
  the starting evidence.
- A modeler fills in `reference_model_match` in the concept-mapping YAML.
- `design-landscape` reads the filled matches as an **advisory** `bi_weight` signal
  that may only re-rank the `demanded-but-unbound` backlog — it never changes a
  class's classification.
- `kairos-design-domain` and `kairos-design-gold` treat it as demand, never as
  business authority.

## Privacy

Never commit credentials, connection strings, raw personal data, or proprietary
report content. Redact or synthesize any persisted values.
