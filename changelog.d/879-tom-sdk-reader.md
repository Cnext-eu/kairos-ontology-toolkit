### Changed (BREAKING for BI import)
- **`import-tmdl` reads Power BI models with the Microsoft TOM SDK, and needs the .NET 8
  SDK (DD-237, #879).** It used to read TMDL with a hand-rolled parser that got flat
  layouts (#874), fenced DAX (#875) and partial exports (#807) wrong. It now uses the
  engine Power BI Desktop and Fabric use. The engineering pack and concept mapping keep
  their shape.
  - **No .NET SDK:** `import-tmdl` fails with the install instruction. There is no
    fallback reader.
  - **An export the SDK refuses** is one Desktop would refuse too, so it is an error,
    not a thin reading. In a batch, a refused model is skipped with a warning and counted
    as partial: `--fail-on-partial` still decides the exit code, and the command fails
    only when every model is refused.
  - **Declared but missing tables** (`ref table` pointers to tables the export lacks)
    are still named, as before.
  - **The first run builds the bundled reader once**, which needs NuGet access.
  - **The parser-vs-SDK cross-check from #901 is removed:** with one reader there is
    nothing to compare. `harvest-gold` still reads the toolkit's own generated TMDL with
    the old parser.
