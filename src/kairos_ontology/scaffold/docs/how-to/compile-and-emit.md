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
kairos-ontology compile billing --emit --confirm-emit
```

`--check` and `--explain` combine. `--emit` is mutually exclusive with both and requires
`--confirm-emit`, so a design-time session cannot emit by accident.

Compile every domain at once with `--all`. That is a wall-clock optimisation, not a
semantic one: each domain still compiles independently and is emitted atomically; they
only share the process's read-only parse caches.

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
