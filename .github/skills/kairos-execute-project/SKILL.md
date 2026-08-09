---
name: kairos-execute-project
description: >
  Thin v5 execution wrapper for stateless compile check, explain, and atomic emit.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# Execute Project

Use `compile` directly; do not add orchestration around it.

1. Resolve the hub root from `kairos.yaml`, choose one domain, and verify at least
   one `integration/bindings/*.binding.yaml` selects it in `metadata.domain`.
2. Check without writing:

   ```powershell
   $env:KAIROS_SKILL_CONTEXT = "1"
   uv run kairos-ontology compile <domain> --check --format json
   ```

3. On failure, report every ordered diagnostic with code, message, and source
   location. Do not emit.
4. When review is requested, run
   `uv run kairos-ontology compile <domain> --explain --format json` and present
   normalized entities, sources, grain, identity, relationships, capabilities,
   and planned artifact paths.
5. After a successful check and explicit output-path confirmation, run
   `uv run kairos-ontology compile <domain> --emit --confirm-emit`. `--confirm-emit`
   is required alongside `--emit` — this is the one skill that legitimately
   passes it.
6. Verify the command succeeded and report emitted paths from the current result.

Compiler input is the authored ontology, source/dbt contracts, and closed
`EntityBinding` documents. Compiler output is derived and must not be edited by
this skill. A successful compile is not a deployment or runtime-test verdict.
