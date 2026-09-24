# DD-237: import-tmdl reads Power BI models with the TOM SDK and requires dotnet

**Status:** Accepted
**Date:** 2026-09-24
**Affects:** `import-tmdl` (`core/import_tmdl.py`), new `core/tmdl_tom_reader.py`, the bundled
`tmdl_validator_tool` (`--inventory`), `core/tmdl_parser.py` (kept for `harvest-gold`),
removed `core/tmdl_crosscheck.py`, CI (`setup-dotnet`), README prerequisites,
`kairos-design-source` skill
**Issue:** #879

### Context

`import-tmdl` read Power BI TMDL with a hand-rolled line-and-regex parser (about 600
lines). Three of the four bugs filed in one dogfood session were bugs the real engine does
not have:
- a flat layout read as zero tables (#874);
- fenced DAX stored as the fence (#875);
- an export missing its table files read as a well-formed empty model (#807).

The toolkit already bundled the Microsoft TOM SDK, but only for validating TMDL it
generated. #901 added a cross-check (option 3 on #879): read with the parser, and when
`dotnet` is present ask TOM too and warn on a disagreement. That detects a bad reading but
does not fix it, and it keeps two readers alive. The remaining question was whether
`dotnet` may become a prerequisite for BI import. That is a product call, not a technical
one, and it was made on #879: make it required.

### Decision

`import-tmdl` reads every model through `TmdlSerializer.DeserializeDatabaseFromFolder`, the
engine Power BI Desktop and Fabric use. The bundled tool's `--inventory` mode emits the
full reading:
- tables with columns, measures, partitions and annotations;
- relationships with their endpoints;
- model properties.

`core/tmdl_tom_reader.py` maps that reading onto the existing `tmdl_parser` dataclasses, so
the engineering pack and concept mapping keep their shape.

- **No fallback.** Without `dotnet`, `import-tmdl` fails with the install instruction. A
  fallback reader nobody tests is where two readings quietly diverge.
- **A refused export is an error.** If TOM refuses an export, Power BI Desktop refuses it
  too, so importing it anyway produced evidence about a model nobody can open. In a batch,
  a refused model is skipped with a warning and counted as partial, so `--fail-on-partial`
  still governs the exit code. The command fails only when every model is refused.
- **Declared tables are still checked.** TOM accepts a `ref table` pointer to a table the
  export does not contain, so the reader still compares `model.tmdl`'s declared tables
  against what TOM read (#807).
- **A lone `.tmdl` table file** is staged as the only table of a stub model, since TOM reads
  folders.
- **The cross-check is removed.** With one reader there is nothing to compare.

### Consequences

- The .NET 8 SDK is a prerequisite for BI import. The first run builds the bundled reader
  once, which needs NuGet access. README and the `kairos-design-source` skill say so, and CI
  installs .NET explicitly so the reader's tests cannot skip silently.
- Exports that are not valid TMDL are rejected. The old test fixtures were such an export:
  `compatibilityLevel` in `model.tmdl`, no `model` header. The parser had accepted them.
- `harvest-gold` still parses the TMDL the toolkit itself generated with `tmdl_parser`. That
  path reads well-formed, self-produced text and is out of scope here.
- Gold TMDL validation (`emit-gold`, `package-powerbi-release`) keeps its existing
  contract: a missing `dotnet` is reported and never blocks.
