### Performance
- **`compile --all --emit` and `emit-gold` are about twice as fast (#598).** Measured on a
  15-domain hub. The output is byte-identical.

  | Command | Before | After |
  |---|---|---|
  | `compile --all --emit`, warm | 54.6 s | 21.6 s |
  | `compile --all --emit`, cold (no `.cache/`, as in CI) | 57.6 s | 28.3 s |
  | `emit-gold`, 15-domain product | 23.5 s | 10.2 s |

  The run log's new per-gate spans (#1011) located the repeated work:
  - **One emit transaction per domain instead of three.** A domain's own, shared and
    dependency manifests were three emits, and each one staged and swapped the whole dbt
    project. They are now one transaction (`emit_artifact_batch`), which commits all three
    or none. A failing third manifest can no longer leave the first two committed.
  - **Shared ontology modules are parsed once per command.** Every domain re-parsed the
    same imported modules, and so did the reference-corpus walk: 630 parses of about 140
    files. Parsed graphs are now kept in memory for the run, keyed on each file's content
    hash.
  - **One prefix map per ontology closure.** It was rebuilt for every class and property
    it labelled, 2,204 times.
  - **Binding coverage is read once per hub state.** The hub-wide set of bound source
    tables was re-read for each domain, which meant 690 YAML parses of 46 bindings.
  - **Fewer path resolutions during emit.** Emit checks no longer resolve the same target
    root, or the same parent directory, for every file.

  Every new cache lives only for one command and is keyed on file content, so an edited
  input is always a miss. The only caches that persist between runs are the existing
  content-addressed ones under `.cache/`.
