# Business Discovery — per-document extractions

This folder holds **one extraction file per source document** processed during
business discovery. Each file is a structured record of *what was extracted from
which document*, so provenance travels with the hub and reruns stay incremental.

It is written by the **kairos-design-discovery** skill (Phase 1 / Phase 4) and is
backed by the deterministic `kairos-ontology discovery-status` command, which
reports which documents are new, changed, or already processed.

## Why per-document files?

When raw artifacts are dropped in `.import/businessdiscovery/`, discovery needs to
know:

- **What was extracted from where** — full provenance for every term.
- **Which documents are new or changed** — so a rerun only reprocesses what
  actually changed instead of re-reading everything.

Each document is hashed (`source_sha256`); on a rerun, `discovery-status` compares
the stored hash to the current file to classify it as **up to date**, **changed**,
or **new (unprocessed)**.

## File convention

```
businessdiscovery/_extractions/{slug}.extraction.yaml
```

`{slug}` is the slugified source filename **including its extension** (so
`Abbreviations.pdf` → `abbreviations-pdf.extraction.yaml`, avoiding collisions
between same-stem documents).

```yaml
version: "1.0"
source_file: Abbreviations.pdf
source_path: .import/businessdiscovery/Abbreviations.pdf
source_sha256: <hex digest of the raw document bytes>
processed_at: 2026-06-13T17:00:00+00:00
strategy: company-terminology-v1          # extractor/strategy label (versioned)
summary: >-
  One-paragraph summary of the document and what was pulled from it.
extracted_terms:
  - altLabel: HBL
    prefLabel: Transport Document
    definition: ...
    category: documentation               # domain / category bucket
    company_specific: true                # true = company-specific, false = generic industry
    source_locator: page 3 diagram        # optional: page/slide/image locator
    evidence_type: diagram                # optional: text | image | ocr | diagram | screenshot
    linked_iri: https://example.com/ont/logistics#TransportDocument   # optional
visual_evidence:                          # optional; summarize, never embed raw images
  - locator: page 3 / slide 7 / screenshot.png
    visual_type: process_diagram          # process_diagram | org_chart | screenshot | table | scanned_text | other
    extracted_text:
      - HBL
      - Customer Portal
    observed_entities:
      - Transport Document
      - Shipment
    notes: Diagram appears to show how house bills flow through the portal.
    confidence: medium                    # high | medium | low
notes: ...                                # optional free text
status: processed                         # processed | partial | skipped
```

The schema is **generic**. Company-specific terminology extraction is the worked
example, not a hard requirement — adapt `strategy` and `extracted_terms` to the
discovery focus at hand. Use `visual_evidence` for screenshots, diagrams, scanned
PDF pages, embedded slide images, and other image-heavy artifacts. Do not store raw
images or sensitive screenshot data in extraction YAML; summarize the observed
business evidence only.

## How it is used

- `discovery-status` lists new/changed documents so the skill processes only those.
- The confirmed terms still flow into `{company}-glossary.ttl` (Phase 2); these
  extraction files are the **provenance trail** behind that glossary.

## ⚠️ Sensitive content

These files may summarize confidential business information. Keep the hub repository
**private**, and do **not** store secrets, credentials, or personal data (PII).
