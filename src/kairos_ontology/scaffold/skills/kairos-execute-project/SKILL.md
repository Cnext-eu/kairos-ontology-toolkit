---
name: kairos-execute-project
description: Generate downstream artifacts from canonical ontology and CompilePlan inputs.
---

# Execute Project

Use the v5 compiler as the only Silver/dbt authority.

1. Discover the requested domain and confirm `model/bindings/<domain>.yaml` exists.
2. Run the non-writing diagnostic gate:

   ```powershell
   $env:KAIROS_SKILL_CONTEXT=1
   kairos-ontology compile <domain> --check --format json
   ```

3. Stop on any ordered compiler error and report its code, message, and source location.
4. Explain before writing when review is requested:
   `kairos-ontology compile <domain> --explain --format json`.
5. Emit atomically with `kairos-ontology compile <domain> --emit <directory>`.
6. Gold and MDM remain optional downstream consumers of the same typed CompilePlan. For
   graph-oriented non-Silver targets still registered by `project`, use their explicit target
   through this skill; never route dbt or Silver through legacy project orchestration.

Do not create lifecycle/readiness/release reports or persistent phase state. Compiler diagnostics
are the sole projection preflight for v5 bindings; a successful compile is not runtime or release
certification.
