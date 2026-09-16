### Fixed
- **`kairos-execute-project` now emits the whole hub, and says why (issue #796).** The skill
  prescribed `compile <domain> --emit --confirm-emit`, and `compile --all` appeared in no skill at
  all — while CI's drift gate runs `compile --all --emit --confirm-emit`. So the documented local
  workflow and the gate that judges it disagreed by construction. On any hub with more than one
  domain that reliably produced stale committed output: a domain's provenance records the hash of
  every authored file in its transitive import closure, so editing one domain's `.ttl` or contract
  invalidates the recorded provenance of every domain that imports it, directly or transitively.
  The emit succeeded, reported success, and the staleness surfaced minutes later in CI as a large
  hash-only diff — no SQL, model or contract-output differences — that reads like a serious
  failure when nothing is actually wrong. `docs/toolkit/how-to/compile-and-emit.md` and the
  scaffolded `CICD.md` say the same thing; the how-to's claim that `--all` is "a wall-clock
  optimisation, not a semantic one" was true of `--check` and wrong of `--emit`.

### Added
- **A partial emit reports the domains it left stale.** `compile <domain> --emit --confirm-emit`
  now compares every other domain's recorded input digests against the working tree and names the
  ones whose committed output no longer matches:

  ```
  ✓ party: emitted 47 artifact(s) to ...
  ! 8 other domain(s) record authored inputs that have changed since they were emitted;
    their committed output is now stale: booking, consignment, equipment, ...
    run: kairos-ontology compile --all --emit --confirm-emit
  ```

  The toolkit already held everything needed to say this — each `metadata/<domain>.provenance.json`
  enumerates its inputs with their digests, so it is a lookup rather than an inference. Silent
  under `--all` (which has just refreshed everything), silent under `--quiet`, and silent when an
  input cannot be read, because a false alarm would train people to ignore the warning. The same
  fact appears in `--format json` as `stale_dependent_domains`. It never fails the command: the
  output that was written is correct, just incomplete.
