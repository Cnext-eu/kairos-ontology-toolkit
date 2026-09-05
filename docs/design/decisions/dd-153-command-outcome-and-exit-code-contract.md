# DD-153: Command Outcome and Exit-Code Contract

**Status:** Accepted
**Date:** 2026-08-14
**Affects:** every CLI command that reports partial success; `core/command_outcome.py`,
`generate-inventory`, `check-inventory`, `import-flatfile`, `propose-alignment`, `scaffold-system`
**Implementation:** `src/kairos_ontology/core/command_outcome.py`, `cli/inspection.py`
(`generate_inventory_cmd`, `check_inventory_cmd`), `core/inventory.py` (`InventoryCheckReport`)

### Context

Partial-failure policy was decided per command, so two commands facing the same question gave opposite
answers, and there were **76 hand-rolled `raise SystemExit(...)` sites** across `cli/` with no documented
rule about which code to use. Thirteen already used exit 2 for "cannot locate or parse the inputs"; fifteen
comparable sites used 1. Nothing recorded which was correct.

The concrete failure that forced this (#405): `generate-inventory` printed
`✅ Generated 78 inventory file(s)` and exited **0** while three sources failed to build and a fourth was
skipped by a filename collision — the collision even printing `❌` in a command that then reported success.
`written` was the only counter the command kept, so the summary line had no denominator to divide by. In an
unattended run the exit code is the entire signal, and it did not distinguish "78 generated cleanly" from
"78 generated, 4 lost, and the next command will refuse to proceed".

#408 proposed the invariant `exit == 0 ⟺ failed == []`, naming `import-flatfile` as the reference semantics.
Those two are incompatible: `import-flatfile` deliberately exits **0** on partial failure and 1 only on total
failure. A per-command `failure_policy` flag was considered and rejected — it does not resolve the ambiguity,
it relocates it to whoever sets the flag, and it mis-classifies `import-flatfile`, which is legitimately both.

### Decision

Blocking-ness is **intrinsic to the outcome, not a property of the command**:

```
is_blocking =
      no artifact produced for any requested target     # total failure
   or an explicitly-named target failed                 # a directly-named input always fails fast
   or (strict and advisory_findings)                    # the escalation axis
```

This generalises a shape the codebase already used — `blocking = report.is_blocking or (strict and
report.unverifiable)`. `CommandOutcome` carries `succeeded` / `skipped` / `failed` plus per-target
`attempted` / `produced` / `failed` counts, and exposes named `is_blocking` and `has_warnings` properties so
no CLI re-derives the rule inline. A target's `total_failure` requires **both** attempts and failures, so an
empty or wholly-skipped target is never mistaken for a broken one.

Exit codes:

- **0** — every attempted target produced its artifact. `skipped` never affects the code.
- **0 + a `⚠` line** — partial failure where output was still written. The summary always carries the
  denominator (`78 generated, 3 failed, 1 skipped`).
- **1** — the command did not do what was asked: total failure, an explicitly-named target failed, or an
  escalation gate (`--strict`, `--fail-on`) was crossed.
- **2** — the inputs to attempt the work could not be located or parsed.

Two invariants, both testable, and the second was being violated:

- `exit != 0` ⟹ at least one `❌`/`⛔` line was printed.
- a `❌` line was printed ⟹ `exit != 0`.

### Rejected alternatives

- **Per-command `failure_policy ∈ {blocking, advisory}`.** Mis-classifies `import-flatfile`, which is both,
  and turns an unclassified failure into a configuration question.
- **Make every partial failure blocking.** Would render `generate-inventory` unconvergeable: it enumerates the
  vendored reference-models tree, which a hub author cannot repair, so a single unparseable upstream TTL would
  block every hub resolving that version. Ownership is the test — fail for what the author can fix.
- **A machine-readable failure manifest** written by the generator and read by the checker. Solves the
  remediation-text problem but adds an artifact and a staleness question; the `unbuildable` classification
  (DD-047 amendment) achieves the same result inside the existing report.

### Consequences

- `generate-inventory` now exits 1 when it produced nothing from a non-empty source set, or on a DD-054
  collision, and prints a denominator summary. A single unbuildable vendored source stays advisory.
- `import-flatfile`'s documented behaviour is unchanged — partial reads still exit 0 — and it now expresses
  that through the shared rule rather than a local convention.
- Migrating the remaining hand-rolled `SystemExit` sites is deliberately incremental. The behaviour-changing
  subset is the ~15 input-resolution sites that should move from 1 to 2; the rest is a mechanical swap and can
  follow. Until then the contract is documented but not uniformly enforced, which is an honest description of
  the state rather than a claim of completion.
- Any new command reporting more than one outcome should return a `CommandOutcome` rather than hand-rolling an
  exit, so the invariants above hold by construction.
