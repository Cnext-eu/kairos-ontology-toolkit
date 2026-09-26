---
name: kairos-execute-project
description: >
  Thin v5 execution wrapper for stateless compile check, explain, and atomic emit.
---
<!-- kairos-ontology-toolkit:managed v2.35.0 -->

# Execute Project

Use `compile` directly; do not add orchestration around it.

1. Resolve the hub root from `kairos.yaml`, choose the domain you are working on,
   and verify at least one `integration/bindings/*.binding.yaml` selects it in
   `metadata.domain`.
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
5. After a successful check and explicit output-path confirmation, emit:

   ```powershell
   uv run kairos-ontology compile --all --emit --confirm-emit
   ```

   Emit **every** domain, not just the one you changed. A domain's provenance
   records the hash of every authored file in its transitive import closure, so
   editing one domain's `.ttl` or contract makes the committed output of every
   domain that imports it — directly or transitively — stale. A per-domain emit
   succeeds silently and CI's drift gate, which runs exactly this command, then
   fails with a large hash-only diff that reads like a serious failure when nothing
   is actually wrong.

   `uv run kairos-ontology compile <domain> --emit --confirm-emit` is correct only
   on a single-domain hub, or when you have confirmed no other domain imports what
   you changed. The command warns you when it rewrote an input other domains record.

   `--confirm-emit` is required alongside `--emit` — this is the one skill that
   legitimately passes it.
6. Verify the command succeeded and report emitted paths from the current result.
7. Review what the emit reported from its run log, not from scrolled console output. The
   command's last line names it (`Run log: .kairos/logs/<utc>-compile-<id>.jsonl`):

   ```powershell
   uv run kairos-ontology logs show --group-by code   # every finding, with counts
   uv run kairos-ontology logs show                   # per domain and gate, with durations
   ```

   After a failed emit, the default view shows which domain and which gate refused
   (`refused`) or failed (`error`), with the diagnostics under it. Quote those codes; do
   not re-run the emit to see them again.

## Diagram and documentation targets (`project`)

`project` is not `compile`: it draws and documents, and reads no CompilePlan.

```powershell
$env:KAIROS_SKILL_CONTEXT = "1"
uv run kairos-ontology project --target erd --target ddd   # class diagrams + architecture layer
uv run kairos-ontology project --target contract-erd       # declared Silver contract ERDs
```

`--target` repeats: one run with several targets parses every ontology once, which is why CI
runs `erd` and `ddd` together. `project` also keeps a run log: a target that fails for one
domain is reported there as `projection.domain-failed` (`logs show`).

`erd` and `ddd` write under `ontology-hub-publish/architecture/`, a **tracked, drift-gated**
lane: CI regenerates both and diffs them, so run them after any ontology, overlay, contract or
binding change and commit the result; `git add` new files, because the gate does not see
untracked additions. `contract-erd` writes beside the contracts in
`ontology-hub/model/contracts/diagrams/`.

`ddd` writes, for every hub with a class, `architecture/ddd/ubiquitous-language.ttl` and
`architecture/ddd/concept-guide.md` (DD-232), and for a hub with a DDD overlay also
`architecture/ddd/contexts/*.mmd`, `contexts/design-notes.md` and the per-domain
`<domain>-aggregate-overview.mmd` / `<domain>-ddd-report.md` (DD-230). Sample values in the
concept guide are off unless `kairos.yaml` says `projections.concept_guide.samples: true`.
Every generated `.mmd` opens with `layout: elk` frontmatter (#855); a hub whose renderer
predates Mermaid 10.5 sets `projections.mermaid_layout: none`.

Compiler input is the authored ontology, source/dbt contracts, and closed
`EntityBinding` documents. Read the ontology only through `show-class-inventory` or
`explain-term`, never a `.ttl` as text (DD-103). Compiler output is derived and must not be edited by
this skill — including temporary or workaround edits meant to unblock a failing
test and "revert later"; if emitted output looks wrong, fix the authored input and
re-emit. A successful compile is not a deployment or runtime-test verdict.
Any release-relevant emitted output belongs in the same hub pull request as the
authored change that produced it — see `CICD.md`.
