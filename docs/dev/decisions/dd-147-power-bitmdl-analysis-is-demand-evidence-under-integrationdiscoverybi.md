# DD-147: Power BI/TMDL analysis is demand evidence under integration/discovery/bi

**Status:** Accepted
**Date:** 2026-08-10

### Context

`import-tmdl` parses Power BI PBIP/TMDL semantic models into an Engineering Pack and a
Concept Mapping template. This is **downstream demand evidence** — how the business already
reports on its data — and `design-landscape` consumes it strictly as an advisory `bi_weight`
signal that may only re-rank the `demanded-but-unbound` backlog, never as a canonical input
source or a class-classification input (DD's C1 guard).

Despite that, the command's default output was `integration/sources/powerbi/`, physically
placing BI evidence under `integration/sources/` where authored source vocabularies live.
That location invited treating a Power BI model as a source system and binding it as a source
relation in an `EntityBinding`, contradicting the intended demand-evidence semantics.

### Decision

Relocate Power BI/TMDL analysis to the demand/discovery tree:

- `import-tmdl --output` defaults to **`integration/discovery/bi/`** (a sibling of the DD-090
  `core-concepts-conformance.yaml` demand artifact), never `integration/sources/`. That path is
  resolved against the **hub root**, not the current working directory (issue #296): the original
  cwd-relative default created a stray top-level `integration/` tree outside `ontology-hub/`
  whenever the command was run from the repository root — which is the natural place to run it,
  since raw BI exports are kept there. An explicit `--output` is still honoured verbatim.
- Only the two derived artifacts are written into the hub. A PBIP archive is expanded in a
  temporary directory, never into the output folder (issue #296): the archive carries the whole
  report — report definitions, local settings, M expressions with server names — and that folder's
  own README forbids committing connection strings or proprietary report content. In-place
  extraction also accumulated stale members across re-runs, since `extractall` never prunes.
- `design-landscape` reads concept-mapping BI weight from `integration/discovery/bi/**` first,
  and still reads the legacy `integration/sources/**` location for back-compat.
- `draft-model-report --tmdl-dir` auto-detects `integration/discovery/bi/`, falling back to the
  legacy `integration/sources/powerbi/` when present.
- `init`/`new-repo` scaffold the folder with a README stating BI/TMDL is demand evidence, not a
  source.
- The `kairos-design-source` import skill offers a Power BI/TMDL import step **after** sources,
  explicitly as demand evidence landing under `integration/discovery/bi/` — never a source.

### Consequences

- Additive and backward-compatible: existing hubs with mappings under
  `integration/sources/powerbi/` continue to work via the legacy read/fallback paths.
- The physical layout now matches the semantics: a Power BI model can no longer be mistaken for
  an authored source relation.
