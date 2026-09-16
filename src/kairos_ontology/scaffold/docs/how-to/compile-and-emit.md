# Compile and emit

**Skill:** `kairos-execute-project`

Compilation is stateless and deterministic: the same authored inputs always produce the
same artifacts.

## The three modes

```bash
# Validate. Writes nothing.
kairos-ontology compile billing --check

# Show the normalised plan the compiler derived. Writes nothing.
kairos-ontology compile billing --explain --format json

# Produce artifacts. The only side-effecting mode.
# Emit every domain: see "Emit the whole hub" below.
kairos-ontology compile --all --emit --confirm-emit
```

`--check` and `--explain` combine. `--emit` is mutually exclusive with both and requires
`--confirm-emit`, so a design-time session cannot emit by accident.

## Emit the whole hub

For `--check` and `--explain`, `--all` is a wall-clock optimisation: each domain is
analysed independently and they only share the process's read-only parse caches.

For `--emit` on a hub with more than one domain it is **not** optional. A domain's
provenance records the hash of every authored file in its transitive import closure,
so editing one domain's `.ttl` or contract invalidates the recorded provenance of
every domain that imports it, directly or transitively. Emitting only the domain you
changed succeeds, reports success, and leaves the rest of the committed tree stale:

```bash
kairos-ontology compile --all --emit --confirm-emit
```

This is exactly what CI's drift gate runs. A partial emit therefore shows up minutes
later as a large hash-only diff — no SQL, model or contract-output differences, just
`sha256` entries and rolled-up `provenanceHash` values — which reads like a serious
failure when nothing is actually wrong.

A per-domain `compile <domain> --emit --confirm-emit` is correct on a single-domain
hub, or when nothing else imports what you changed. The command tells you when that
is not the case: it names the domains whose recorded inputs this emit just rewrote.

## Where output goes

`../ontology-hub-publish/medallion/dbt`, a **sibling** of the hub. The location is fixed
and not configurable. Emission is manifest-owned and atomic: `.kairos-compile-manifest.*.json`
records every file the compiler owns, so a re-emit prunes what is no longer generated and
refuses to overwrite a file it does not own.

## Check what produced the output

Each emit writes `metadata/<domain>.provenance.json` (DD-218): toolkit version, adapter,
the compile provenance hash, and a sha256 for every authored input in the build. Compare
the hash against a previous release to see whether anything real changed, then read the
per-input digests to see *which* input moved — usually faster than diffing generated SQL.

## Verify

```bash
kairos-ontology validate
kairos-ontology compile --all --check
kairos-ontology validate-dbt
```

A successful compile means the inputs can produce a CompilePlan. It is **not** evidence
that dbt runs, that a release was published, or that anything was deployed. Those are
separate, and none of them is implied.

## Next

[Consume from a dataplatform](consume-from-a-dataplatform.md).
