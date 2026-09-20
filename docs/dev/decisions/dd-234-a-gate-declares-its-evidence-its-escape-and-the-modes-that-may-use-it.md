# DD-234: A gate declares its evidence, its escape, and the modes that may use it

**Status:** Accepted
**Date:** 2026-09-20
**Affects:** new `core/gates.py` (registry, `EnforcementMode`, `enforcement_provenance`),
new `cli/gates.py` (`gates` command, `escape_option`), `cli/main.py` (`--mode`),
`core/alignment_report.py` (`alignment_evidence_gaps`, `sources_imported`,
`AlignmentReport.unreadable`), `cli/compile.py` (evidence gate, `_gate_failure`),
`core/propose_alignment.py` and `core/anchor_tables.py` (`enforcement:` block),
seventeen escape-flag declarations across eight CLI modules,
`.claude/skills/kairos-flow-autopilot/SKILL.md`, new `tests/test_gate_registry.py`,
new `tests/test_alignment_evidence_gate.py`
**Issue:** [#886](https://github.com/Cnext-eu/kairos-ontology-toolkit/issues/886) — filed
from a dogfood session (2026-09-20) that worked a real client hub from import to silver,
after the operator observed that "too much can be bypassed."

### Context

The toolkit had gates from DD-148 onward and no statement of what a gate *is*. Each one
was defensible on its own; the aggregate was weaker than any of its parts, in three
specific ways measured on one real hub.

**Gates were evidence-conditional, not requirement-conditional.** The DD-169 column gate
is the strongest check in the pipeline. Varying only whether its input was readable:

| state of `integration/sources/_analysis/` | DD-169 reported |
|---|---|
| healthy | **661** undecided columns |
| one `*-alignment.yaml` malformed | **405** — 256 columns silently gone |
| directory deleted | **0 — gate passed clean** |

No exception was raised in any of the three. `build_alignment_report` treats unreadable
or absent input as *no evidence*, and no evidence means no undecided columns, which means
the gate is satisfied. The cheapest way past the strongest gate in the toolkit was to not
generate its evidence.

**And they failed open on exception, deliberately.** Both DD-180 and DD-169 were wrapped
in `except Exception: ... = []` with the comment "never fail a compile on the guard
itself". The intent was sound — a broken guard must not break an unrelated compile — and
the effect was that "the guard crashed" and "the guard passed" produced identical output.

**Sixteen escape hatches shared no contract.** `--allow-downgrade`,
`--allow-fallback-output`, `--allow-unresolved`, `--degraded` (×4), `--skip-protection`,
`--skip-refmodels`, `--skip-tmdl-validation` (×2), `--without-anchors`,
`--without-discovery` (×2), `--no-schema-catalogue-screen` (×2), `--no-source-evidence`.
Each individually justified; collectively there was no answer to *which of these may an
autonomous run use, which are safe in CI, and which leave a trace*. One of them — a
fourth `--degraded`, on `resolve-ontology` — had no help text at all and was found only
by the AST scan written for this decision.

`--without-discovery` is the instructive case, because it was the *best* of them: it
blocks rather than warns, and its code comment explains why. Even so, the fact that it
was used was printed to a terminal and written into no artifact, so a `*-alignment.yaml`
produced with it was afterwards indistinguishable from a grounded one.

### Decision

**1. A gate asserts its evidence exists before evaluating it. Absent or unreadable
evidence fails the gate.** `alignment_evidence_gaps` is what `compile` consults ahead of
DD-180 and DD-169, so the table above now reads `661 / error / error`.

Scoped to hubs that have imported sources, and reported hub-wide. A domain with no
`*-alignment.yaml` of its own is deliberately *not* reported: a domain may legitimately
have no source tables behind it, and a gate that stops such a compile would be wrong in a
way the operator cannot fix. A gate that cries wolf is switched off, and these block.

**2. A gate that cannot be evaluated has not passed.** The two fail-open wrappers now
return `gate.evaluation-failed` naming the gate and carrying the exception, so a toolkit
defect is distinguishable from a malformed hub file — and from success.

**3. Three enforcement modes, declared once rather than judged per command.**

| mode | escapes that downgrade a result | selected by |
|---|---|---|
| `interactive` | permitted — a human is reading the warning | default |
| `autopilot` | **refused** at parse time | `--mode autopilot`, `KAIROS_MODE` |
| `ci` | **refused** at parse time | `--mode ci`, `KAIROS_MODE` |

The modes differ in one thing — what happens when a gate is unresolved — and the
difference is about *who is watching*, not about how important the check is. This
generalises what `kairos-flow-autopilot` already did for the AI provider to every gate,
and turns "an autopilot run must not pass that flag" from a request in a skill file into
something the toolkit enforces.

**4. A gate registry, in code, one declaration each.** `GATES` carries the id, rule, the
evidence globs it reads, its escape, and the modes that escape is permitted in. It buys
three things that could not be had before: `kairos-ontology gates` printing the whole
set; escape classification a reviewer can audit without reading the implementation; and
one place where mode policy is applied instead of sixteen.

**5. Escapes are declared, not written.** `escape_option("<gate id>", "--flag", ...)`
replaces `click.option` for a gate escape, so the flag and its classification are the
same edit. An unknown gate id raises at import time, because a typo would otherwise
produce a flag that is silently unenforced — exactly the state this ends.

**6. An escape is recorded in the artifact.** `*-alignment.yaml` and `table-anchors.yaml`
carry an `enforcement:` block naming the mode and the flags used. Emitted only when there
is something to say, so a clean interactive run's output is byte-identical to what the
previous toolkit version wrote.

This is the argument the AI-provenance header already makes — *an artifact that is partly
a model's suggestion has to say so on its face, where anyone opening the file will see
it, rather than only in a run log nobody keeps* — applied to enforcement rather than
authorship.

### Consequences

The default mode is `interactive` and every current default is unchanged, so an existing
human workflow behaves exactly as before. What changed unconditionally is items 1 and 2:
a hub with imported sources and unreadable alignment evidence no longer compiles. That is
the point, and it is the one part of this decision that can stop a run which previously
succeeded — a run which previously succeeded by not looking.

`UNGATED_FLAGS` is a set of claims, not a suppression list: each entry asserts that
bypassing the flag costs a reviewer nothing, with the reason. `--force`, `--no-cache` and
`--no-sample-values` are there; the last is the clearest case, since it errs toward less
data leaving the hub, which is the opposite of an escape.

The escape ledger is process-global state rather than a threaded parameter. The
alternative was passing a mode and an escape list down through every command body into
`propose_alignment`'s generation chain — a far larger diff across code with nothing to do
with enforcement, which each new command would have to remember to join. The cost is that
`escapes_used()` is only correct within one CLI process, which is the lifetime the
artifact is written in.

An unrecognised `KAIROS_MODE` resolves to `interactive` rather than raising. Loose is the
safe direction here: a typo cannot silently tighten a pipeline into failing, and cannot
take down a command that would otherwise have worked.

### Alternatives considered

**Make `build_alignment_report` strict.** Rejected. It is a report and should keep
degrading gracefully — one broken file must not sink a hub-wide coverage picture. The
assertion belongs in the gate that consumes it, which is where it now is.

**Remove the escape hatches.** Rejected. They exist for real situations; the problem was
that they were unrecorded and unclassified, not that they existed. Every one of them
survives, in `interactive` mode, to a human who means it.

**Blanket refusal of all escapes in the strict modes.** Rejected as the kind of rule that
gets a mode abandoned. `--allow-downgrade` is a legitimate recovery action in every
context, and `--skip-protection` is an honest statement about org permissions rather than
a judgement about the model. Per-gate `escape_modes` says which is which, and the
rationale field makes the call reviewable.

**Enforce with a check inside each command body.** Rejected in favour of a parse-time
callback bound to the registry. A body-level check is a thing a new command can forget;
`escape_option` cannot be forgotten, because declaring the flag *is* registering it, and
`tests/test_gate_registry.py` refuses an escape-shaped flag declared any other way.

**A `--mode` flag per command rather than on the root group.** Rejected: mode is a
property of the run, not of the invocation, and sixteen per-command copies would
reproduce the fragmentation this decision exists to end.
