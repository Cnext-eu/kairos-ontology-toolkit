### Fixed
- **`validation-report.json` no longer embeds absolute machine-local paths (issue #822).**
  Every `file` entry carried the resolved path of the ontology file — leaking the
  developer's filesystem layout into an artifact routinely pasted into issues, PRs and
  support threads, and causing the report to ping-pong between contributors on any hub that
  deliberately tracks it. Paths are now rendered against the repo root with forward slashes
  (`ontology-hub/model/ontologies/customs.ttl`), matching how the drift gate and the dbt
  ref scan already report, and clickable in a pull request.

  Twelve emission sites, including the `shacl.semantic_context` dict **keys**, which are
  file paths too and would otherwise have left the report internally inconsistent.

  `run_validation` is a documented library entry point with direct callers, so the new
  `repo_root` argument defaults to off and their output is unchanged; the CLI passes it.
