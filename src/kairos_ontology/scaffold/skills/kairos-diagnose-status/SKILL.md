---
name: kairos-diagnose-status
description: >
  Perform a stateless ontology-hub diagnostic using source/ontology/reference inventory,
  version diagnostics, and canonical CompilePlan diagnostics.
---

# Ontology Hub Diagnostic

Produce a read-only report. Do not create lifecycle state, readiness reports, or a release verdict.

1. Inspect source analysis under `integration/sources/`.
2. Inventory domain ontologies, reference imports, bindings, and output artifacts.
3. Preserve update/version diagnostics and report managed-file drift separately.
4. Discover domains from `model/bindings/*.yaml`, then run for each domain:

   ```powershell
   $env:KAIROS_SKILL_CONTEXT=1
   kairos-ontology compile <domain> --check --format json
   ```

5. Treat the returned ordered CompilePlan diagnostics as the machine authority for binding,
   expression, adapter, conformance, temporal, relationship, and artifact-planning failures.
6. Report facts in sections: sources, ontology/reference inventory, bindings, compile
   diagnostics, outputs, and recommended next skill.

A passing compile check establishes only that the selected domain can compile. It does not imply
runtime validation or release eligibility. Never recreate legacy status, projection-readiness,
lifecycle-gate, or release-evaluator logic.
