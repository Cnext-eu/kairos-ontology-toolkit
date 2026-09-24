# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""The gate registry and enforcement modes (DD-234).

A *gate* is a check that blocks the pipeline until a human decides something. The
toolkit has had gates since DD-148; what it has not had is a statement of what a gate
*is*, so each one was negotiated separately and the aggregate came out weaker than any
of its parts. Three properties were missing and are supplied here.

**A gate is enumerable.** Before this module the only way to find out what could block a
run, and what could unblock it, was to read sixteen ``click.option`` declarations across
eight CLI files. :data:`GATES` is that list, in one place, and ``kairos-ontology gates``
prints it.

**An escape is classified.** Every escape hatch was individually justified and
collectively unaccountable: nothing said which of them an autonomous run may use, which
are safe in CI, or which leave a trace. :attr:`Gate.escape_modes` answers the first two
per gate, and :func:`escapes_used` the third.

**A gate's evidence is a requirement.** :attr:`Gate.requires` names the artifacts a gate
reads. A gate that computes its verdict from absent evidence is not passing, it is
uninformed -- see :func:`kairos_ontology.core.alignment_report.alignment_evidence_gaps`,
which is what closed the hole this module was written for.

Deliberately not a rule engine. Nothing here evaluates a gate; the gates live where they
always did, next to the data they read. This module declares them, so the *policy* around
them -- may this run escape, and what does the artifact record -- has one home instead of
sixteen.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum

__all__ = [
    "EnforcementMode",
    "Gate",
    "GATES",
    "UNGATED_FLAGS",
    "MODE_ENV_VAR",
    "active_mode",
    "escape_permitted",
    "escapes_used",
    "enforcement_provenance",
    "gate_by_id",
    "gate_for_escape",
    "record_escape",
    "refusal_message",
    "reset_enforcement_state",
    "set_active_mode",
]


class EnforcementMode(str, Enum):
    """How strictly this run treats a gate it cannot clear.

    The modes differ in one thing only -- what happens when a gate is unresolved -- and
    the difference is about *who is watching*, not about how important the check is.

    ``interactive`` is a human at a terminal who can read a warning, weigh it, and pass
    an escape flag on purpose. ``autopilot`` is an agent delivering a client hub with
    nobody reading the scrollback, where a downgrade is indistinguishable from success
    and therefore has to be a stop. ``ci`` is a pipeline whose only output is an exit
    code.
    """

    INTERACTIVE = "interactive"
    AUTOPILOT = "autopilot"
    CI = "ci"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: Environment variable selecting the mode, for a CI job or an agent harness that cannot
#: pass a root flag to every invocation. ``--mode`` beats it when both are given.
MODE_ENV_VAR = "KAIROS_MODE"

#: Every mode. Used for the gates that are escapable anywhere.
_ANY_MODE: tuple[EnforcementMode, ...] = (
    EnforcementMode.INTERACTIVE,
    EnforcementMode.AUTOPILOT,
    EnforcementMode.CI,
)

#: A human at a terminal only.
_HUMAN_ONLY: tuple[EnforcementMode, ...] = (EnforcementMode.INTERACTIVE,)

#: A human, or a pipeline that has made the same call deliberately in its config.
_HUMAN_OR_CI: tuple[EnforcementMode, ...] = (
    EnforcementMode.INTERACTIVE,
    EnforcementMode.CI,
)


@dataclass(frozen=True, slots=True)
class Gate:
    """One declared check, its evidence, and the flag that gets past it."""

    #: Stable dotted identifier, matching the diagnostic code where the gate emits one.
    id: str
    #: The design decision this gate enforces, or "" for a gate with no DD behind it.
    rule_id: str
    #: One line, in the terms the operator will meet it in.
    summary: str
    #: CLI commands that evaluate this gate.
    commands: tuple[str, ...] = ()
    #: The flag that bypasses it, or "" for a gate with no escape at all.
    escape: str = ""
    #: Modes in which :attr:`escape` is accepted. Refused everywhere else.
    escape_modes: tuple[EnforcementMode, ...] = _HUMAN_ONLY
    #: Hub-relative globs of the evidence the gate reads. Empty when the gate computes
    #: its own answer rather than reading an artifact.
    requires: tuple[str, ...] = ()
    #: What absent or unreadable :attr:`requires` evidence means. ``"fail"`` is the
    #: DD-234 default: a gate never passes on evidence it could not read. ``"skip"`` is
    #: for a gate whose evidence is genuinely optional.
    on_missing_evidence: str = "fail"
    #: Why the escape exists. Rendered by ``gates --verbose``; the point is that a
    #: reviewer can judge the classification without reading the implementation.
    escape_rationale: str = ""

    def permits_escape(self, mode: EnforcementMode) -> bool:
        """Whether this run's mode may use :attr:`escape`."""
        return bool(self.escape) and mode in self.escape_modes


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------

#: Every gate in the toolkit, with its evidence and its escape.
#:
#: Ordered by pipeline stage, because that is the order an operator meets them in and
#: the order in which one gate's escape becomes the next gate's missing evidence: a run
#: that took ``--without-discovery`` at anchoring produces source-shaped anchors, which
#: is what ``alignment.table-unanchored`` then has to judge.
GATES: tuple[Gate, ...] = (
    Gate(
        id="setup.reference-models-required",
        rule_id="",
        summary=(
            "A hub needs the reference-model package before it can align anything "
            "against a canonical vocabulary."
        ),
        commands=("init",),
        escape="--skip-refmodels",
        escape_modes=_HUMAN_OR_CI,
        escape_rationale=(
            "Installing the dependency later is a normal bootstrap order, and an "
            "air-gapped CI job may vendor it by another route."
        ),
    ),
    Gate(
        id="setup.branch-protection",
        rule_id="DD-010",
        summary="A new hub repository gets branch protection on main.",
        commands=("new-repo",),
        escape="--skip-protection",
        escape_modes=_HUMAN_OR_CI,
        escape_rationale=(
            "Requires admin rights on the org, which the operator may genuinely not "
            "have. Failing the whole scaffold over it would be worse."
        ),
    ),
    Gate(
        id="discovery.glossary-required",
        rule_id="DD-171",
        summary=(
            "Anchoring and alignment are grounded in the business's own vocabulary, "
            "not in source column names."
        ),
        commands=("anchor-tables", "propose-alignment"),
        escape="--without-discovery",
        escape_modes=_HUMAN_ONLY,
        requires=("businessdiscovery/*.ttl",),
        escape_rationale=(
            "A hub genuinely early in its life has no glossary yet, and the operator "
            "may want source-shaped output to look at. An agent delivering a hub has "
            "no such excuse -- the glossary is the client's own words, and it is what "
            "the run is supposed to be for."
        ),
    ),
    Gate(
        id="discovery.glossary-not-emptied",
        rule_id="DD-234",
        summary=(
            "build-glossary never replaces a glossary that holds concepts with one that "
            "holds none."
        ),
        commands=("build-glossary",),
        escape="--allow-empty",
        escape_modes=_HUMAN_ONLY,
        requires=("businessdiscovery/_extractions/*.extraction.yaml",),
        on_missing_evidence="fail",
        escape_rationale=(
            "Emptying a glossary on purpose is a legitimate human act -- starting "
            "discovery over, say. An agent that meets this has run the serializer before "
            "the extraction step, and the fix is to run extraction, not to overwrite the "
            "client's own vocabulary (#906)."
        ),
    ),
    Gate(
        id="discovery.source-evidence",
        rule_id="",
        summary=(
            "Conformance judgments are made against the hub's own source analysis, "
            "not against the concept list alone."
        ),
        commands=("discovery-conformance judgments-template",),
        escape="--no-source-evidence",
        escape_modes=_HUMAN_ONLY,
        escape_rationale=(
            "The command is legitimately runnable outside a hub, where there is no "
            "source analysis to join."
        ),
    ),
    Gate(
        id="discovery.unresolved-judgment",
        rule_id="DD-148",
        summary=(
            "Every archetype-conformance judgment is resolved before the domains it "
            "covers can be modelled."
        ),
        commands=("discovery-conformance validate", "discovery-conformance build"),
        escape="--allow-unresolved",
        escape_modes=_HUMAN_ONLY,
        requires=("integration/discovery/*-conformance.yaml",),
        escape_rationale=(
            "Inspecting a half-finished artifact on purpose. The flag's own help "
            "already says unresolved is unsafe everywhere including CI, so this is "
            "the registry agreeing with it rather than a new restriction."
        ),
    ),
    Gate(
        id="sources.schema-catalogue-screen",
        rule_id="",
        summary=(
            "A table that catalogues the source's own schema is not business data and "
            "is screened out before anchoring."
        ),
        commands=("anchor-tables", "propose-alignment"),
        escape="--no-schema-catalogue-screen",
        escape_modes=_HUMAN_ONLY,
        escape_rationale=(
            "Overruling a false positive in the screen, which is a judgement about "
            "this client's schema that only a human is in a position to make."
        ),
    ),
    Gate(
        id="alignment.anchors-required",
        rule_id="DD-185",
        summary=(
            "Alignment runs against resolved anchors, so affinity stays a prior "
            "rather than becoming a hard constraint."
        ),
        commands=("propose-alignment",),
        escape="--without-anchors",
        escape_modes=_HUMAN_ONLY,
        requires=("integration/sources/_analysis/hub.table-anchors.yaml",),
        escape_rationale=(
            "Reproducing pre-DD-185 behaviour to compare against. Its own help "
            "explains why the result is worse; an autonomous run should not be "
            "choosing the worse one."
        ),
    ),
    Gate(
        id="alignment.fallback-only-domain",
        rule_id="",
        summary=(
            "A domain whose every table was fallback-only is skipped, so a "
            "placeholder never reaches the tree as a real proposal."
        ),
        commands=("propose-alignment",),
        escape="--allow-fallback-output",
        escape_modes=_HUMAN_ONLY,
        escape_rationale=(
            "Seeing the shape of the output for a domain with no reference model yet. "
            "The result is explicitly not a proposal, which is exactly the thing an "
            "unattended run must not write into the tree."
        ),
    ),
    Gate(
        id="alignment.evidence-missing",
        rule_id="DD-234",
        summary=(
            "The column and anchor gates read the alignment output. Absent or "
            "unreadable, that is uninformed, not clean."
        ),
        commands=("compile",),
        requires=("integration/sources/_analysis/dom-*.alignment.yaml",),
        escape_rationale="",
    ),
    Gate(
        id="alignment.table-unanchored",
        rule_id="DD-180",
        summary=(
            "A table with no reference class and no recorded disposition blocks the "
            "compile: none of its columns can map well."
        ),
        commands=("compile",),
        requires=("integration/sources/_analysis/dom-*.alignment.yaml",),
    ),
    Gate(
        id="alignment.gap-column-undecided",
        rule_id="DD-169",
        summary=(
            "A source column carrying real business data with no canonical home and "
            "no recorded decision blocks the compile."
        ),
        commands=("compile",),
        requires=(
            "integration/sources/_analysis/dom-*.alignment.yaml",
            "integration/sources/_analysis/table-dispositions.yaml",
        ),
    ),
    Gate(
        id="ontology.integrity",
        rule_id="DD-163",
        summary="A domain's ontology passes integrity before its binding compiles.",
        commands=("compile",),
    ),
    Gate(
        id="ontology.import-closure-complete",
        rule_id="",
        summary=(
            "Semantic validation and projection run against a complete import "
            "closure, or say on the artifact that they did not."
        ),
        commands=("validate", "project", "init", "resolve-ontology"),
        escape="--degraded",
        escape_modes=_HUMAN_ONLY,
        escape_rationale=(
            "Mid-authoring, an incomplete closure is the normal state and blocking on "
            "it would make the command useless. The result is already marked "
            "import_complete=false, which is the best-behaved escape in the toolkit -- "
            "it is recorded in the artifact, not only on the terminal."
        ),
    ),
    Gate(
        id="import.evidence-unconsumed",
        rule_id="DD-233",
        summary=(
            "Client evidence staged under .import/ that nothing downstream has read "
            "fails validate."
        ),
        commands=("validate",),
        escape="--degraded",
        escape_modes=_HUMAN_ONLY,
        escape_rationale=(
            "Shares --degraded with the closure gate, because it is reported in the "
            "same integrity block. Noted here rather than hidden: one flag answering "
            "for two gates is the kind of thing this registry exists to make visible."
        ),
    ),
    Gate(
        id="gold.tmdl-structural-validation",
        rule_id="",
        summary=(
            "Generated TMDL is checked with the TOM SDK before it is emitted or "
            "packaged, whenever dotnet is available."
        ),
        commands=("emit-gold", "package-powerbi-release"),
        escape="--skip-tmdl-validation",
        escape_modes=_HUMAN_OR_CI,
        on_missing_evidence="skip",
        escape_rationale=(
            "Already a no-op without dotnet on PATH, so the flag only matters where "
            "the check could have run. Permitted in CI because a pipeline may "
            "deliberately validate in a separate job."
        ),
    ),
    Gate(
        id="toolkit.version-downgrade",
        rule_id="",
        summary="An upgrade does not silently move the toolkit pin backwards.",
        commands=("update",),
        escape="--allow-downgrade",
        escape_modes=_ANY_MODE,
        escape_rationale=(
            "Pinning back to a known-good version is a legitimate recovery action in "
            "every context, including an unattended one. The gate exists to stop it "
            "happening by accident, not to stop it happening."
        ),
    ),
)


#: Flags that look like an escape and are not, with the reason.
#:
#: The AST test in ``tests/test_gate_registry.py`` requires every escape-shaped flag in
#: the CLI to be either a registered :class:`Gate` escape or listed here. That is the
#: mechanism stopping the registry from quietly going out of date: adding
#: ``--skip-something`` to a command fails the suite until it is classified.
#:
#: Being on this list is a claim that bypassing the flag costs the operator nothing a
#: reviewer would want recorded -- speed, output verbosity, or overwriting a file they
#: named themselves. A claim about a flag that does not exist is not a classification,
#: so the same test requires every entry here to match a flag actually declared in the
#: CLI; two speculative entries were removed when that check was written.
UNGATED_FLAGS: dict[str, str] = {
    "--allow": (
        "A per-invocation allowlist for `guard-scope --check-since`, which is advisory "
        "(it narrows what a reviewer reads and blocks nothing), and which is visible in "
        "the invocation that used it."
    ),
    "--force": (
        "Cache bypass or file overwrite, depending on the command. Re-running work and "
        "overwriting a destination the operator named are not correctness decisions."
    ),
    "--force-managed": "Hidden maintenance flag for toolkit-managed file rewrites.",
    "--no-cache": "Performance. Forces a clean reparse; the answer is unchanged.",
    "--no-compile": (
        "`next` is advisory (DD-137) and reports downstream readiness as indeterminate "
        "when this is passed, so the weakened result says so itself."
    ),
    "--no-redact-pii": "Deprecated no-op, accepted so existing scripts keep working.",
    "--no-sample-values": (
        "Suppresses masked example values from the output (DD-075). Errs toward less "
        "data leaving the hub, which is the safe direction -- the opposite of an escape."
    ),
}


_BY_ID = {gate.id: gate for gate in GATES}
_BY_ESCAPE: dict[str, list[Gate]] = {}
for _gate in GATES:
    if _gate.escape:
        _BY_ESCAPE.setdefault(_gate.escape, []).append(_gate)


def gate_by_id(gate_id: str) -> Gate | None:
    """The registered gate with this id, or ``None``."""
    return _BY_ID.get(gate_id)


def gate_for_escape(flag: str) -> Gate | None:
    """The gate *flag* escapes, or ``None`` if it escapes none.

    ``--degraded`` answers for two gates (see :data:`GATES`); this returns the first,
    which is the one whose refusal message reads correctly for either.
    """
    found = _BY_ESCAPE.get(flag)
    return found[0] if found else None


def gates_for_escape(flag: str) -> tuple[Gate, ...]:
    """Every gate *flag* escapes, in registry order."""
    return tuple(_BY_ESCAPE.get(flag, ()))


# ---------------------------------------------------------------------------
# Mode and the escape ledger
# ---------------------------------------------------------------------------


@dataclass
class _EnforcementState:
    """Process-local enforcement state for one CLI invocation.

    Module state rather than a threaded parameter, deliberately and with a cost. The
    alternative is passing a mode and an escape list down through every command body
    into ``propose_alignment``'s generation chain, which is a far larger diff across
    code that has nothing to do with enforcement, and which each new command would have
    to remember to participate in.

    The cost is that :func:`escapes_used` is only correct within one CLI process.
    :func:`reset_enforcement_state` exists so a test, or an embedder invoking commands
    in-process, can put it back.
    """

    mode: EnforcementMode | None = None
    escapes: list[str] = field(default_factory=list)


_STATE = _EnforcementState()


def set_active_mode(mode: EnforcementMode | str | None) -> None:
    """Pin this run's mode. ``None`` returns to resolving from the environment."""
    _STATE.mode = EnforcementMode(mode) if mode is not None else None


def active_mode() -> EnforcementMode:
    """This run's mode: the pinned value, else :data:`MODE_ENV_VAR`, else interactive.

    An unrecognised environment value resolves to ``interactive`` rather than raising.
    A typo in ``KAIROS_MODE`` should not take down a command that would otherwise have
    worked -- and the loose direction is the current, unchanged behaviour, so a typo
    cannot silently *tighten* a pipeline into failing either.
    """
    if _STATE.mode is not None:
        return _STATE.mode
    raw = (os.environ.get(MODE_ENV_VAR) or "").strip().lower()
    try:
        return EnforcementMode(raw)
    except ValueError:
        return EnforcementMode.INTERACTIVE


def escape_permitted(flag: str, mode: EnforcementMode | None = None) -> bool:
    """Whether *flag* may be used in *mode* (default: this run's mode).

    An unregistered flag is permitted: this function answers for gates, and a flag that
    escapes no gate is not this module's business. The registry cannot drift far,
    because the AST test refuses an unclassified escape-shaped flag.
    """
    gates = gates_for_escape(flag)
    if not gates:
        return True
    resolved = mode if mode is not None else active_mode()
    # Every gate the flag answers for has to permit it. --degraded covers two, and the
    # stricter one wins: a flag is only as escapable as the tightest thing it opens.
    return all(gate.permits_escape(resolved) for gate in gates)


def refusal_message(flag: str, mode: EnforcementMode | None = None) -> str:
    """Why *flag* is refused, and what the operator has to do instead.

    A refusal that does not name the human decision it needs is an obstacle rather than
    a control -- the same rule ``GAP_RESOLUTIONS`` follows for the DD-169 gate.
    """
    resolved = mode if mode is not None else active_mode()
    gates = gates_for_escape(flag)
    if not gates:
        return ""
    names = ", ".join(gate.id for gate in gates)
    rules = sorted({gate.rule_id for gate in gates if gate.rule_id})
    rule_note = f" ({', '.join(rules)})" if rules else ""
    permitted = sorted({m.value for gate in gates for m in gate.escape_modes})
    lines = [
        f"{flag} is refused in {resolved.value} mode.",
        f"  It bypasses: {names}{rule_note}",
        f"  {gates[0].summary}",
        f"  Permitted in: {', '.join(permitted) or 'no mode'}",
    ]
    rationale = next((gate.escape_rationale for gate in gates if gate.escape_rationale), "")
    if rationale:
        lines.append(f"  Why it exists: {rationale}")
    lines.append(
        "  Resolve the gate itself, or re-run interactively if a human is making "
        "this call."
    )
    return "\n".join(lines)


def record_escape(flag: str) -> None:
    """Note that *flag* was used, for :func:`enforcement_provenance`.

    Recorded even for a flag that escapes no registered gate. An artifact saying what
    was passed is more useful than one saying what this module happened to classify,
    and the classification can change after the artifact is written.
    """
    if flag not in _STATE.escapes:
        _STATE.escapes.append(flag)


def escapes_used() -> tuple[str, ...]:
    """Escape flags recorded so far in this process, in the order first seen."""
    return tuple(_STATE.escapes)


def reset_enforcement_state() -> None:
    """Clear the pinned mode and the escape ledger."""
    _STATE.mode = None
    _STATE.escapes.clear()


def enforcement_provenance() -> dict[str, object]:
    """The ``enforcement:`` block a generated artifact carries (DD-234 §2.4).

    The same argument the AI-provenance header makes for authorship, applied to
    enforcement: an artifact produced under an escape has to say so on its face, where
    the reviewer opening the file six months later will see it, rather than only on the
    terminal that produced it. A ``*-alignment.yaml`` written with ``--without-discovery``
    was otherwise indistinguishable afterwards from a grounded one.

    Returns ``{}`` on a clean interactive run, so an unaffected artifact stays
    byte-identical to what the previous toolkit version wrote.
    """
    mode = active_mode()
    escapes = escapes_used()
    if mode is EnforcementMode.INTERACTIVE and not escapes:
        return {}
    block: dict[str, object] = {"mode": mode.value}
    if escapes:
        block["escapes_used"] = list(escapes)
    return block
