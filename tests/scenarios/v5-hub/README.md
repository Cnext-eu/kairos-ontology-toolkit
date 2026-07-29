# V5 customer hub

Confirmed business context: customers are identified by the CRM customer key and reference a
country code maintained by the same source. The bounded canonical slice is inspired by common
party/reference-data models but is authoritative only for this synthetic scenario.

The fixture contains only current authoritative inputs: ontology and source-vocabulary TTL,
closed EntityBinding YAML, and an ordinary contracted dbt model. Optional Gold/MDM policy is
covered by the sibling `v5-governed-hub`. Neither fixture contains claims, preparation policy,
lifecycle state, readiness/evidence registries, release baselines, legacy mapping authority, or
generated output.

All source metadata and values are synthetic and contain no personal data.
