### Fixed
- **Tagged releases now work on GitHub Enterprise Server (issue #773).**
  `release-projections.yml` set `GH_TOKEN` but not `GH_HOST`, so `gh` fell back to
  inspecting the git remote, did not recognise a non-`github.com` hostname and gave up —
  *after* compile, emit, validation and packaging had all succeeded. No release object was
  created and the artifacts the job had just built were discarded with the runner. The host
  is now derived from `GITHUB_SERVER_URL`, which is correct on both github.com and GHES.
- **An RC tag now publishes as a pre-release.** GitHub does not infer pre-release status
  from a tag name, so `v0.2.0-rc.1` published as a normal release — which defeats cutting
  an RC, and misleads a consumer that pins by release.
- **Managed workflows no longer re-resolve dependencies on every command (issue #771).**
  Each workflow ran `uv sync --locked` in its own step and then invoked `uv run` up to six
  more times; because the toolkit and reference models are pinned as direct URLs rather
  than registry packages, every one of those was a fresh network fetch of the wheel
  metadata. A single job made roughly seven round trips where one would do, and any of them
  could catch a transient upstream error and fail the run — with a misleading message
  naming the URL, which reads as "the URL is corrupt" rather than "the registry blipped".
  Every invocation now passes `--no-sync`, and the one `uv sync` that was missing
  `--locked` has it.
- **`KAIROS_SKILL_CONTEXT` is set for the whole workflow, not one step of five (issue
  #721).** Every other skill-managed command printed a "prefer the skill in your AI coding
  session" advisory into CI logs, where there is no session to redirect to and no skill to
  prefer — and it implied the run had skipped validation gates that adjacent steps perform
  explicitly. Setting it at workflow level also means a step added later inherits it rather
  than silently regressing.

### Notes
- Hubs and dataplatforms on the previous generation of any of these four workflows are
  offered an automatic refresh rather than being reported as locally customized: the
  outgoing bytes are recorded under `scaffold/superseded-workflows/`. Only `pr-validate.yml`
  had a recorded history before this change, so `full-validate.yml`, `managed-check.yml`
  and `release-projections.yml` gain one.
