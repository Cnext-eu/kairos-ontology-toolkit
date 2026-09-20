# DD-231: Every hub class is bound or carries a recorded disposition once the ledger is adopted

**Status:** Accepted
**Date:** 2026-09-20
**Affects:** new `core/class_disposition.py`, new `cli/class_disposition.py`
(`kairos-ontology class-disposition init|set|list|clear`), `core/validator.py:run_validation`
(block after DD-164's), `integration/discovery/class-dispositions.yaml` (new authored ledger),
`tests/test_class_disposition.py`
**Issue:** #847 (the class-side sibling of #492's manifest request and the authored-declaration
counterpart to #496)

### Context

Source **tables** have a disposition ledger (DD-164): an unbound, undisposed table is an error,
not an omission. Ontology **classes** had the opposite, and the asymmetry was undefended. An
`owl:Class` no `EntityBinding` targets never enters the CompilePlan — `build_contract_document`
iterates `plan.bindings`, and `CompilePlan` carries no class inventory — so it is silently absent
from the contract, from Silver, from the ERDs and from Gold. Not an error, not a warning, no
diagnostic code anywhere in `core/compiler/`.

That silence is correct as a *compile* behaviour: the ontology is allowed to run ahead of its
sources, and making it an error would break every ontology-first workflow. The gap is that there
was **nowhere to record the intent**. "Not bound yet, deliberately, because X" could only be
inferred from `design-landscape`'s `demanded-but-unbound` / `no-evidence` classification, which
persists nothing, always exits 0, and cannot distinguish "deliberately deferred" from "forgotten".

The population that makes this bite is a context engineer's logical model carried into the
ontology as a deliberate superset of Silver (DD-229, DD-230): dozens of authored, meaningful
classes, intentionally unbound until source evidence exists. One hub managed its single such
class with a hand-written decision record; that does not scale to several dozen. DD-164's own
rejected-alternatives table already made the argument one level up: *an opt-in flag is not run
by the pipeline that needs it, and the gap is in `validate`.*

### Decision

**A class-level ledger, `integration/discovery/class-dispositions.yaml`**, beside the other
class-IRI-keyed discovery artifacts. Entries: `class` (IRI), `domain`, `disposition`,
`rationale`, `decided_by`, optional `evidence`; sorted by IRI for stable diffs.

**The population is what the hub declares in its own namespaces**: every `owl:Class` a domain file
declares as a subject under its own `owl:Ontology` IRI, with each domain file parsed alone. A
reference-model IRI re-declared locally for a label — the style `kairos-design-domain`
recommends, and what `erd_projector._declared_classes` deliberately includes for drawing — is
*not* in the population: it is not the hub's class to dispose of, and demanding a decision for it
would be attrition, not governance.

**Derived first, authored second.** `bound` when an EntityBinding's `target.class` resolves to
the class; `bound-via-subclass` when a hub-local subclass is bound (the parent's data flows
through the child). Deliberately **no `bound-via-superclass`**: a bound `Party` does not settle
unbound `Customer` / `Supplier` subclasses, because bindings carry no discriminator; for those the
answer is one of the authored dispositions. The closed authored set: `deferred` (rationale
required), `architecture-only` (rationale required — the population DD-229 creates),
`abstract` (a grouping superclass never instantiated on its own).

**Adoption is opt-in, then binding.** While the ledger file is absent, every undecided class is a
*warning* in `validate`, so no existing hub goes red on upgrade. Creating the ledger —
`class-disposition init`, or the first `set` — is the adoption act; from then on an undecided
class is an *error*, degradable with `--degraded` exactly like DD-164
(`validator.py`'s `if disposition_errors and not degraded:` pattern). Same shape as adopting a
Silver contract (DD-213 §6: present ⇒ authoritative). DD-164 chose enforcement on day one; this
decision does not, because the class population is every hub's whole ontology and the hubs that
exist today authored it under the old rule.

**Four defects of the source ledger are not reproduced.** A malformed ledger *raises*
(`ClassDispositionError`, reported by `validate` as `class-disposition.malformed-ledger`) rather
than reading as `{}` and turning a corrupt file into a wall of "undecided" errors pointing at the
wrong problem — `registered_concepts.read_registered`'s reasoning. `decided_by` is closed in core
(`user`, `ai`, `autopilot`), not only in the CLI's `click.Choice`. `clear` is a command, with
`--class`, `--disposition`, `--decided-by` and `--dry-run`, so an agent's blanket answers can be
withdrawn without touching a human's. `list --undecided` exists and is the one command the
remediation text names.

**Diagnostics** (validation codes, recorded here and in `cli-behaviour-notes.md`, not in
`diagnostic-codes.md`):

| Code | Level | Meaning |
|---|---|---|
| `class-disposition.undecided-class` | warning → error once the ledger exists | neither bound nor disposed |
| `class-disposition.unknown-value` | error | disposition outside the closed set |
| `class-disposition.missing-rationale` | error | `deferred` / `architecture-only` without a reason |
| `class-disposition.unknown-decider` | error | `decided_by` outside `user` / `ai` / `autopilot` |
| `class-disposition.stale` | warning | a recorded disposition for a class a binding now targets |
| `class-disposition.unknown-class` | warning | an entry for a class no domain file declares |
| `class-disposition.malformed-ledger` | error | the file cannot be trusted |

The DD-230 design notes show the disposition beside each class's Silver status, so the
architecture view says *why* a box is empty, not only that it is.

### Consequences

A context engineer records "architecture only" once per class and the class stops looking
forgotten to everyone else; a data engineer sees in the ledger and the design notes which classes
are theirs to bind and which are not. Binding a class flips it to `bound` with no ledger edit,
and a disposition left behind becomes a `stale` warning rather than a lie.

Rejected: enforcing on day one (every existing hub with an unbound authored class goes red on
upgrade, for a rule it never authored under); `bound-via-superclass` (bindings carry no
discriminator; a bound parent says nothing about an unbound child); including re-declared
reference-model IRIs in the population (not the hub's class to decide); a `--strict` flag
(DD-164's own rejection: an opt-in flag is not run by the pipeline that needs it); a decision
record per class (does not scale, and `design-landscape` cannot read it); persisting the derived
`bound` status in the ledger (a derived fact written down goes stale silently — the DD-133 /
#492 argument).
