# DD-047: Deterministic Inventory Freshness Pre-flight Gate

**Status:** Accepted
**Date:** 2026-06-13
**Affects:** `inventory.py`, `cli/main.py`, `kairos-design-domain` skill (both copies)
**Implementation:** `src/kairos_ontology/inventory.py` (`compute_source_hash`, `source_sha256` envelope field, `check_inventories`), `src/kairos_ontology/cli/main.py` (`check-inventory` command)

### Context

DD-046 made reference-model subclass properties visible during domain modeling by
reading the DD-044 materialized inventories (`model/inventory/*.yaml`). But that
visibility is only as good as the inventory: the `design-domain` skill's "prefer
inventories" guidance was a **soft** instruction with no enforcement. A modeler
could proceed against a **missing** inventory (falling back to raw TTL, which hides
subclass closure) or a **stale** inventory (reference models changed since the YAML
was generated), silently reintroducing the exact duplication DD-046 set out to
prevent. The skill's "mandatory" language lived on the checkpoints, but nothing
deterministically verified the inventory was present and current.

### Decision

Add a deterministic, code-level pre-flight gate:

1. **Provenance hash** — `generate_inventory()` now stores `source_sha256` (SHA-256
   of the source TTL bytes) in the inventory envelope.
2. **`check_inventories()`** — classifies every source TTL as `ok`, `missing`
   (has classes but no inventory → blocking), `stale` (stored hash ≠ current →
   blocking), `unverifiable` (pre-DD-047 inventory with no hash → warn), or `orphan`
   (inventory with no source → warn). Class-less TTLs are skipped (mirrors
   `generate-inventory`).
3. **`kairos-ontology check-inventory`** — CLI wrapper that exits non-zero on
   missing/stale; `--strict` also fails on unverifiable; `--warn-only` never blocks.
4. **Skill hard gate** — `design-domain` Step 0c.1b now opens with a 🚦 pre-flight
   instructing the LLM to run `check-inventory` and **STOP** (propose nothing) until
   it passes, regenerating + committing the inventory if needed.

### Rationale

The enforcement is deterministic (Tier 1) — a content-hash comparison, reproducible
and unit-testable — rather than relying on the LLM to honor a soft "prefer
inventories" hint (which is exactly the kind of judgment that should not gate
correctness). Storing a content hash, not an mtime, makes the check robust across
git clones where timestamps are meaningless. Backward compatibility is preserved:
inventories generated before DD-047 lack the hash and are reported as `unverifiable`
(warn, not block) unless `--strict` is used. The gate is still *invoked* by the
skill (the skill harness has no Python entry point), but the pass/fail decision is
now made by code, not by the model.

### Consequences

- Inventory envelope gains `source_sha256` (optional; `None` for graph-sourced
  inventories). Existing readers ignore unknown keys.
- New CLI command `check-inventory`; `design-domain` skill (both copies) gains the
  pre-flight gate at Step 0c.1b.
- Tests: `tests/test_inventory_freshness.py` (hash, `check_inventories`
  classification, CLI exit codes for fresh/missing/warn-only/strict).
- A true blocking gate still depends on the operator/agent actually running
  `check-inventory`; CI hubs may additionally wire it as a pipeline step.

### Amendment (2026-08-14): read-only sources that change wholesale (DD-152, proposed)

Under DD-152 reference models resolve from a shared, versioned, out-of-repo cache. Source ontologies
become **read-only** and stop changing file-by-file: they change **wholesale**, at the moment a hub
resolves a different reference-models version. The mechanism of this gate survives that intact; its
classification guidance and its remedy do not.

**Unchanged.** `compute_source_hash` and the `source_sha256` envelope field are indifferent to where the
source lives — bytes are bytes, and a cache path hashes exactly like a repo path. The `ok`/`stale`
distinction, the deterministic content-hash-not-mtime rationale, `--strict`/`--warn-only`, and the
non-zero exit on missing/stale all stand.

**`stale` changes cause and remedy.** Under vendoring, `stale` meant "a source TTL in this repo was
edited or refreshed", and the Decision's step 4 remedy — regenerate the inventory and commit it —
addressed one or a few files. Under DD-152 nothing edits a source in place; instead **every** inventory
reclassifies to `stale` simultaneously the first time a hub runs against a new cached version. The
`design-domain` Step 0c.1b 🚦 gate must say this, or a routine reference-models bump reads to an operator
(and to an LLM) as N independent failures rather than one expected upgrade step. The remedy is a
deliberate bulk regeneration performed *as part of* the version upgrade, and it is the inventories that
get committed — the sources no longer can be.

**`unverifiable` must not absorb resolution failures.** It means exactly one thing: a pre-DD-047
inventory with no stored hash. It must never be reached because a source could not be *found*. A source
that the cache or catalog fails to resolve is a resolution failure and must surface as one (a
`missing_import`/resolver diagnostic), because `unverifiable` only warns and `--strict` is the sole thing
that escalates it — classifying an unresolvable source as `unverifiable` would convert DD-152's principal
hazard, silent partial closure resolution, into a warning nobody reads. `check_inventories` should be
explicit that an unresolvable source root is a hard error, not a classification.

**`orphan` gains a second legitimate cause.** An inventory with no source now also occurs when the newly
resolved reference-models version no longer publishes that module. Still warn rather than block, but the
message should distinguish "the source was removed from this hub" from "the upstream version dropped it",
since the second is normal during an upgrade and the first is not.

**Addition: stamp the reference-models identity in the envelope.** `generate_inventory()` should record
the reference-models identity it was generated against — the resolved version/ref, and the commit from
`FETCH_PROVENANCE.json` where available — alongside `source_sha256`. Optional and additive, `None` for
graph-sourced inventories, and safe on the same compatibility argument `source_sha256` itself relied on
(existing readers ignore unknown keys). It buys two things: `check-inventory` can report "40 inventories
are stale because this hub moved from v1.15.0 to v1.16.0" instead of 40 unexplained hash mismatches, and
— once the models are no longer committed — the envelope becomes the **only durable record in the hub of
which reference-model bytes the model was authored against**. The stamp must not participate in inventory
filenames or in `_closure_hash` inputs; DD-152's additive-only overlay requirement exists precisely so
those stay byte-stable across the move, and an envelope field that fed either would defeat it.

**Still true.** The pass/fail decision remains code-level and deterministic, and a truly blocking gate
still depends on the operator, agent or CI pipeline actually invoking `check-inventory`.

**Status of this amendment.** DD-152 is `Proposed`; none of the above applies until it is Accepted.

### Amendment (2026-08-14): the `unbuildable` classification, and why it deliberately weakens a gate

This gate had no bucket for *"this source cannot be built at all"*. A source whose closure fails to resolve
was collapsed into one of two existing buckets, both **blocking**: into `missing`, because
`_source_has_classes` deliberately returned `True` when it could not parse a file ("treat as having classes
so the check surfaces it"), or into `stale`, when regeneration raised during the freshness comparison. Both
are indistinguishable from *"you forgot to regenerate"*.

That mattered because `check-inventory`'s remediation names exactly one command — `generate-inventory` — and
for these sources that command **cannot help**. The user is told to run a fix that reports success and clears
nothing, so the pair `check-inventory` → `generate-inventory` → `check-inventory` never converges (#405).
The reporter was accurate about severity and wrong about cause.

**Decision.** Add an `unbuildable` classification: a source that was enumerated but cannot be parsed or have
its closure resolved. It is **non-blocking by default and `--strict`-eligible**, exactly mirroring
`unverifiable`, and `check-inventory` selects a third remediation message naming the real remedy — fix the
source TTL — rather than the generic one.

**This is a deliberate weakening of a gate, and the rationale is ownership, not convenience.**
`iter_reference_inventory_sources` enumerates the **vendored** reference-models tree. A hub author cannot fix
an unparseable TTL in there, and a gate that blocks on it blocks every hub that resolves that version, with
no available remedy. That is the same reasoning already recorded for `catalog-test` — fail only for what the
hub author owns and can fix — and for `init`'s pre-generation loop, where a source TTL's failure "only
reduces coverage, never aborts". A hub that genuinely wants CI teeth escalates with `--strict`.

**What did not change.** `unverifiable` keeps its single meaning (a pre-DD-047 inventory with no stored hash)
and must not absorb build failures. Freshness still compares `closure_hash` only. Both `is_blocking`
properties explicitly exclude `unbuildable`; `has_warnings` includes it. `scope_inventory_report` and
`classify_domain_scope` compose it, so the domain-scoped check remains the authority for a given design and
an out-of-scope unbuildable source stays out of scope.
