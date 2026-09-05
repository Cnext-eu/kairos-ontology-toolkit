# DD-216: The declared Silver contract gets its own diagram

**Status:** Accepted
**Date:** 2026-09-04
**Affects:** new `core/projections/contract_erd_projector.py`, `core/projector.py` (new
`TargetSpec("contract-erd", "architecture/contract-erd", ...)`, a `contracts_dir` parameter threaded
to the dispatch), new `tests/test_contract_erd_projector.py`, `tests/test_target_registry.py`
**Issue:** #698

### Context

DD-213 places the declared contract "between the ontology (meaning) and the bindings (source
fulfilment)". Both neighbours have a diagram — `architecture/erd/<domain>-erd.mmd` for the ontology,
`medallion/dbt/docs/diagrams/<domain>/<domain>-erd.mmd` for emitted Silver. The contract had none,
which made it the only layer a consumer had to read as raw YAML, and it is the layer that *is* the
published promise.

The emitted-Silver ERD does not cover it: the two describe different things. For one real party
entity the emitted diagram carried fifteen columns in adapter-physical types, five of them machinery
(`<model>_sk`, `_source_identity_ref`, `_loaded_at`, a DQ match-count), against the ten
canonical-typed columns actually promised. The emitted view also cannot express what the contract
adds — `requirement`, declared nullability, `stability`, `closed`, per-column deprecation — and it
hides cross-domain reach behind `_sk` columns.

### Decision

A new `contract-erd` projection target, registered beside `ddd` and `erd` so
`projection_target_choices()`/`projection_targets_for_all()` pick it up with no separate CLI wiring.
It reads the **authored contract document** (`model/contracts/<domain>.contract.yaml`) via
`load_silver_contract`, never a `CompilePlan`: the promise is what was declared, so a contract no
binding currently fulfils must still render. `CompilePlan` does not carry the `SilverContract`
anyway — only `scope.contract_paths` — so a projection target is a far cheaper seam than a compiler
artifact, which would additionally have to join `_planned_artifact_paths` and the emit manifest.

`erDiagram` rather than the canonical target's `classDiagram`, by DD-212's own reasoning: a contract
describes a physical Silver table, which has no class hierarchy. `requirement`, nullability and
deprecation render in the quoted attribute comment; `stability` and `closed` in a per-entity comment;
a relationship whose target is not declared in this domain is labelled `[external]`, since
cross-domain reach is precisely what the emitted ERD hides.

An ungoverned domain emits nothing — adopting a contract is opt-in (DD-213 §6), so a hub without one
must not start producing empty diagrams. A contract that fails to load raises: `run_projections`
already catches per domain and prints `✗ Failed`, so the operator is told rather than silently given
no diagram.

### Consequences

The published promise is reviewable as a picture, including the three things only the contract knows
(`requirement`, `stability`, `closed`). One more entry appears in every `--target all` run, but only
for domains that have adopted a contract.

Two rendering constraints from #698 were re-tested against `mmdc` 11.12.0 rather than taken on
report. A **bare `%%`** line does fail the `erDiagram` parser outright, with a line number reported
post-comment-stripping that points at the wrong line — so every comment this projector emits is
guaranteed non-empty by a helper. The same issue's claim that **CRLF** breaks the parser does **not**
reproduce; a fully CRLF `.mmd` renders fine. LF output is still guaranteed, but on determinism
grounds (`determinism.write_text_lf`), not renderability — the docstrings asserting otherwise are
corrected.
