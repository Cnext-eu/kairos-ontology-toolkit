# Power BI / TMDL exports — imported artifacts

Drop **Power BI semantic models and report exports** for this client here. They are
read by `kairos-ontology import-tmdl`, which turns them into the demand evidence the
ontology and Gold layers are designed against.

> **Location:** this folder lives at the **repository root** (`.import/powerbi/`),
> beside `.import/businessdiscovery/` — it holds *imported inputs*, not hub
> deliverables. It is **not** under `ontology-hub/`.

## What to put here

- A `<Model>.SemanticModel/` folder (the Fabric git-integration shape: `definition/`
  with `model.tmdl`, `relationships.tmdl`, `tables/*.tmdl`)
- A flat export folder — `model.tmdl` with the `<table>.tmdl` files beside it rather
  than under `definition/tables/`. Both shapes are read.
- A `<Project>.pbip` pointer **together with** the `.Report/` and `.SemanticModel/`
  folders it names. A pointer on its own cannot be read, because the content it points
  at is not there.
- The `.Report/` folders too, where you have them: they say which measures and fields
  reports actually place on a visual, which is the ranking `kairos-design-gold` uses.

One folder per model. Do not nest several exports under a shared wrapper folder and do
not rename the model folders — the export's own name becomes the artifact's name.

## How it is used

```bash
kairos-ontology import-tmdl .import/powerbi/<YourModel>.SemanticModel
```

writes, per model, into `ontology-hub/integration/discovery/bi/`:

- `<Model>-engineering-pack.md` — table, column and measure inventory, with each
  measure's DAX, for a human to read before designing;
- `<Model>-concept-mapping.yaml` — one row per table, for a modeller to triage
  `use | specialize | new_class | skip`.

Those rows then feed `design-landscape`'s `bi_weight` and `draft-model-report`.

## This is demand evidence, never business authority

A Power BI model records what the business currently *measures*, which is strong
evidence about what matters and weak evidence about what things *are* — it is shaped by
what the warehouse happened to expose. Use it to rank and to challenge, never as the
definition of a concept (DD-147). The concept-mapping worksheet is where a modeller
records that judgement; until they do, a row counts for nothing.

## Untriaged exports are reported

`kairos-ontology validate` fails when an export staged here has no engineering pack in
`integration/discovery/bi/` — staged-but-unused business evidence is the one thing the
pipeline cannot re-derive for itself, so it is not allowed to pass silently (DD-233).
`kairos-ontology discovery-status` lists what is outstanding.

## ⚠️ Sensitive content

A semantic model can carry row-level security rules, connection strings, and business
logic that is itself confidential. Keep the hub repository **private**, and do not
commit credentials or personal data.
