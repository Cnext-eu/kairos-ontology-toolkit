# Business Discovery — imported artifacts

Drop **raw business-context artifacts** for this client/company here. They are
read by the **kairos-design-discovery** skill (Phase 1) to understand how the
company operates before any modeling or mapping begins.

> **Location:** this folder lives at the **repository root** (`.import/`),
> alongside `ontology-reference-models/` — it holds *imported inputs*, not hub
> deliverables. It is **not** under `ontology-hub/`.

## What to put here

- Meeting notes / workshop write-ups
- Company decks and PowerPoints (exported to PDF/text where possible)
- Product / service brochures, "about us" exports
- Process descriptions, internal terminology lists
- Anything that explains **how this specific company operates** — especially
  where they use industry terms (freight forwarding, logistics, …) with their
  own meaning.

## How it is used

1. **kairos-design-discovery** reads these artifacts (plus public web research)
   and synthesizes a confirmed company-context summary into
   `ontology-hub/.sessions-design/businessdiscovery-{date}.md`.
2. It captures the company's **alternative names** as a SKOS glossary in
   `ontology-hub/businessdiscovery/{company}-glossary.ttl`.
3. The glossary then helps **kairos-design-mapping** match source columns to
   domain properties.

## ⚠️ Sensitive content

These files may contain confidential business information. Keep the hub repository
**private**, and do **not** commit secrets, credentials, or personal data (PII).
Sanitize artifacts before adding them where possible.
