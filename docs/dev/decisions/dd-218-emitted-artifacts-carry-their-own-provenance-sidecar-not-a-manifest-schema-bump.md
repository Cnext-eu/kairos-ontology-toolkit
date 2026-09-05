# DD-218: Emitted artifacts carry their own provenance sidecar, not a manifest schema bump

**Status:** Accepted
**Date:** 2026-09-05
**Affects:** `core/compiler/provenance.py` (new), the emitted `metadata/*.provenance.json`
artifact in both the Silver and Gold lanes, and `cli/compile.py` / `cli/emit_gold.py` at
their `emit_artifacts` call sites. No change to the emit manifest.
**Implementation:** `core/compiler/provenance.py`, `tests/test_compile_provenance.py`

### Context

`.kairos-compile-manifest.*.json` records one sha256 per file *written*. It records
nothing about what those bytes were computed *from*: no ontology revision, no binding
digests, no toolkit version, no adapter. `_manifest_bytes` serialises exactly
`{"files": [...], "schema": ...}`.

A dataplatform repository is a different repository with a different owner
(`docs/guide/CONSUMING_COMPILE_PLAN.md`). When a generated model misbehaves, its owner's first
question is "which ontology and which bindings produced this, and are they the ones I
pinned?" Today the artifact cannot answer; the answer has to be reconstructed from the Git
revision that happened to be pinned in `packages.yml`.

Extending the manifest was the obvious fix and is wrong twice over:

1. **The manifest is a closed document.** `_parse_manifest` rejects any top-level key
   outside `{"files", "schema"}`, so an added key fails closed on an older toolkit *even
   at the same schema string* -- and `cli/compile.py` parses every
   `.kairos-compile-manifest.*.json` in the target, so one unreadable manifest fails an
   unrelated domain's emit. A hub and its dataplatform can legitimately run different
   toolkit versions against the same publish tree, so the downgrade direction is real.
   Both branches were untested before this decision; `tests/test_compiler_emit.py` now
   pins them.
2. **There is no single manifest to put it in.** Emission writes four -- domain, shared,
   contracted-dependency and gold -- over disjoint artifact sets, and the shared manifest
   is last-writer-wins across domains. Provenance placed there would describe whichever
   domain happened to emit last.

### Decision

Emit provenance as an ordinary compiler artifact,
`metadata/<domain>.provenance.json` (and `metadata/<domain>-gold.provenance.json` for the
Gold lane), carrying the schema id `kairos.eu/compile-provenance/v1`, the domain,
`apiVersion`, namespace, adapter, toolkit version, the `BuildScope` provenance hash, and
one `{name, sha256}` entry per resolved input.

It is domain-owned, so it lands in the domain manifest and is content-hashed there like
any other file -- the manifest keeps its exact shape and its job. It reuses
`BuildScope.provenance_hash()` rather than inventing a second identity, and orders inputs
by `(name, content)` so the sidecar reads as an itemisation of that hash rather than a
differently-ordered second view of it (#600).

No timestamp and no Git revision. DD-133 validation requirement 10 forbids wall-clock in
artifact content; a Git SHA is unavailable in `core` by design, is not a pure function of
the inputs (a dirty worktree still has a HEAD), and is weaker evidence than the per-input
digests.

### Consequences

Re-emitting unchanged inputs rewrites byte-identical provenance, so the determinism
contract and the parity fingerprint are untouched. Every emit gains one small file per
domain per lane.

The sidecar is *evidence*, not a gate: nothing verifies it against anything yet. Gate B in
[DD-213](dd-213-the-silver-contract-is-declared-not-derived--bindings-conform-to-it.md) --
comparing a candidate release against its predecessor -- is the consumer that would give
it teeth, and remains unbuilt.

Rejected: a manifest schema v2, for the two reasons above; and threading `BuildScope` into
`emit_artifacts`, which would have changed three signatures plus the Gold lane to deliver
the same bytes.
