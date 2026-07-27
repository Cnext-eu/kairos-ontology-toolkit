---
name: kairos-execute-validate
description: Validate ontology syntax, SHACL, mappings, and canonical compile diagnostics.
---

# Execute Validation

Validation is read-only unless the user explicitly requests a report file.

1. Resolve hub, ontology, catalog, and optional SHACL scope.
2. Run `kairos-ontology validate` with the requested syntax/SHACL/consistency options under
   `KAIROS_SKILL_CONTEXT=1` and report exact findings.
3. For every v5 bound domain, run
   `kairos-ontology compile <domain> --check --format json` and preserve ordered source-located
   CompilePlan diagnostics without reclassifying them.
4. Distinguish ontology validation from compile validity and runtime validation. No one result
   implies release eligibility.
5. Recommend the owning design skill for fixes; do not edit TTL without the appropriate skill.

Do not create lifecycle state, projection-readiness evidence, or release-gate evidence. Preserve
source analysis, ontology/reference inventory, version diagnostics, and compiler diagnostics.
