# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Pure, stateless readiness proposer for ``kairos-ontology next`` (DD-137).

This module contains **no I/O and no persisted state**. It turns an already-gathered,
in-memory :class:`HubInputSnapshot` into a deterministic :class:`NextActionProposal`.

It is deliberately NOT a lifecycle/status planner (that subsystem was retired in
DD-135/DD-136). It never infers discovery, source, or business *completeness* from file
presence. It reports only defensible observations — authored input present/missing/
unreadable, the canonical compiler status and ordered diagnostics, and authored optional
policy that is present — and emits ``human_decision_required``/``indeterminate`` for any
step whose completion cannot be proven from authored inputs. The proposal is advisory: it
is recomputed every run, is never authority, and never replaces the compiler.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

#: Bumped when the machine-readable proposal contract changes.
#: v2 adds the optional ``validate-dbt`` gate action and the emitted-dbt-project observation.
SCHEMA_VERSION = 2


class InputStatus(str, Enum):
    """Defensible presence observation for an authored input (never "complete")."""

    PRESENT = "present"
    MISSING = "missing"
    UNREADABLE = "unreadable"


class CompileStatus(str, Enum):
    """Canonical compiler status for a domain."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"
    UNAVAILABLE = "unavailable"


class ActionStatus(str, Enum):
    """Why an action appears and how strongly it is proposed."""

    RECOMMENDED = "recommended"
    BLOCKING = "blocking"
    HUMAN_DECISION_REQUIRED = "human_decision_required"
    INDETERMINATE = "indeterminate"
    OPTIONAL = "optional"


#: Single authority mapping stable action kinds to the owning skill. Skills consume this
#: mapping instead of re-encoding their own routing decision tree (DD-137).
ACTION_SKILLS: dict[str, str] = {
    "design-discovery": "kairos-design-discovery",
    "design-source": "kairos-design-source",
    "design-domain": "kairos-design-domain",
    "author-binding": "kairos-design-mapping",
    "develop-dbt": "kairos-develop-dbt-transformation",
    "run-check": "kairos-execute-validate",
    "fix-diagnostic": "kairos-execute-validate",
    "validate": "kairos-execute-validate",
    "compile-emit": "kairos-execute-project",
    "validate-dbt": "kairos-execute-validate",
    "review-gold": "kairos-design-gold",
    "review-mdm": "kairos-design-mdm",
}


@dataclass(frozen=True, slots=True)
class DiagnosticView:
    """A flattened, JSON-stable view of one canonical compiler diagnostic."""

    code: str
    message: str
    severity: str
    location: str
    rule_id: str


@dataclass(frozen=True, slots=True)
class DomainSnapshot:
    """Observed state of one domain (no completeness claims)."""

    domain: str
    ontology: InputStatus
    has_bindings: bool
    binding_count: int
    compile_status: CompileStatus
    diagnostics: tuple[DiagnosticView, ...] = ()
    gold_policy: InputStatus = InputStatus.MISSING
    mdm_policy: InputStatus = InputStatus.MISSING


@dataclass(frozen=True, slots=True)
class HubInputSnapshot:
    """Defensible, in-memory observations of a hub's authored inputs."""

    hub_root: str
    discovery: InputStatus
    sources: InputStatus
    dbt_transforms: InputStatus
    shapes: InputStatus
    domains: tuple[DomainSnapshot, ...] = ()
    ontology_only_domains: tuple[str, ...] = ()
    binding_only_domains: tuple[str, ...] = ()
    compile_ran: bool = True
    #: Presence of the unified emitted dbt project (output/medallion/dbt/dbt_project.yml).
    #: This is the only defensible emitted-output observation; it never implies freshness or
    #: that the current CompilePlan produced it.
    emitted_dbt_project: InputStatus = InputStatus.MISSING
    #: Configured adapter from kairos.yaml, used only to render the validate-dbt command.
    adapter: str = ""


@dataclass(frozen=True, slots=True)
class NextAction:
    """One derived, advisory next action. Ordered but never a stored todo."""

    kind: str
    status: ActionStatus
    rationale: str
    command: str
    skill: str
    domain: str | None = None
    target: str | None = None
    priority: int = 0
    blocking: bool = False


@dataclass(frozen=True, slots=True)
class NextActionProposal:
    """Deterministic, recomputed proposal. Advisory only — never persisted (DD-137)."""

    schema_version: int
    hub_root: str
    actions: tuple[NextAction, ...]
    summary: str


def _action(
    kind: str,
    status: ActionStatus,
    *,
    rationale: str,
    command: str,
    priority: int,
    domain: str | None = None,
    target: str | None = None,
    blocking: bool = False,
) -> NextAction:
    return NextAction(
        kind=kind,
        status=status,
        rationale=rationale,
        command=command,
        skill=ACTION_SKILLS[kind],
        domain=domain,
        target=target,
        priority=priority,
        blocking=blocking,
    )


def _sort_key(action: NextAction) -> tuple[int, str, str, str]:
    return (action.priority, action.domain or "", action.kind, action.target or "")


def _hub_level_actions(snapshot: HubInputSnapshot) -> list[NextAction]:
    actions: list[NextAction] = []
    if snapshot.discovery is InputStatus.UNREADABLE:
        actions.append(
            _action(
                "design-discovery",
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale="integration/discovery/ is present but unreadable; resolve access.",
                command="kairos-ontology (invoke kairos-design-discovery)",
                priority=5,
            )
        )
    elif snapshot.discovery is InputStatus.MISSING:
        actions.append(
            _action(
                "design-discovery",
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale=(
                    "No authored business-discovery context found. Completeness cannot be "
                    "inferred from files; confirm and capture business terms."
                ),
                command="kairos-ontology (invoke kairos-design-discovery)",
                priority=10,
            )
        )
    if snapshot.sources is InputStatus.UNREADABLE:
        actions.append(
            _action(
                "design-source",
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale="integration/sources/ is present but unreadable; resolve access.",
                command="kairos-ontology (invoke kairos-design-source)",
                priority=15,
            )
        )
    elif snapshot.sources is InputStatus.MISSING:
        actions.append(
            _action(
                "design-source",
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale=(
                    "No authored source vocabularies found. Import and document source "
                    "schemas before or alongside canonical design."
                ),
                command="kairos-ontology (invoke kairos-design-source)",
                priority=20,
            )
        )
    if not snapshot.domains:
        actions.append(
            _action(
                "design-domain",
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale=(
                    "No canonical ontology or binding domain found yet. Author a canonical "
                    "OWL/Turtle domain model to begin."
                ),
                command="kairos-ontology (invoke kairos-design-domain)",
                priority=30,
            )
        )
    return actions


def _domain_actions(domain: DomainSnapshot, compile_ran: bool) -> list[NextAction]:
    actions: list[NextAction] = []
    name = domain.domain
    base = 100

    if domain.ontology is InputStatus.UNREADABLE:
        actions.append(
            _action(
                "design-domain",
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale=f"Ontology for '{name}' is present but unreadable; resolve access.",
                command=f"kairos-ontology (invoke kairos-design-domain) [{name}]",
                priority=base,
                domain=name,
            )
        )
        return actions
    if domain.ontology is InputStatus.MISSING:
        actions.append(
            _action(
                "design-domain",
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale=(
                    f"Domain '{name}' is referenced by binding(s) but has no "
                    f"model/ontologies/{name}.ttl. Author the canonical ontology."
                ),
                command=f"kairos-ontology (invoke kairos-design-domain) [{name}]",
                priority=base + 5,
                domain=name,
            )
        )
        return actions

    if not domain.has_bindings:
        actions.append(
            _action(
                "author-binding",
                ActionStatus.RECOMMENDED,
                rationale=(
                    f"Ontology '{name}' has no EntityBinding yet. Author a closed binding "
                    "mapping a source relation to a canonical entity."
                ),
                command=f"kairos-ontology (invoke kairos-design-mapping) [{name}]",
                priority=base + 10,
                domain=name,
            )
        )
        return actions

    if not compile_ran or domain.compile_status is CompileStatus.NOT_RUN:
        actions.append(
            _action(
                "run-check",
                ActionStatus.INDETERMINATE,
                rationale=(
                    f"Compile check was not run for '{name}', so downstream readiness is "
                    "indeterminate. Run the canonical check for authoritative status."
                ),
                command=f"kairos-ontology compile {name} --check --format json",
                priority=base + 15,
                domain=name,
            )
        )
        return actions

    if domain.compile_status is CompileStatus.UNAVAILABLE:
        actions.append(
            _action(
                "run-check",
                ActionStatus.INDETERMINATE,
                rationale=(
                    f"Compile status for '{name}' is unavailable in this environment; "
                    "re-run the check to obtain authoritative diagnostics."
                ),
                command=f"kairos-ontology compile {name} --check --format json",
                priority=base + 15,
                domain=name,
            )
        )
        return actions

    if domain.compile_status is CompileStatus.FAILED:
        for diagnostic in domain.diagnostics:
            if diagnostic.severity.lower() not in {"error"}:
                continue
            actions.append(
                _action(
                    "fix-diagnostic",
                    ActionStatus.BLOCKING,
                    rationale=(
                        f"[{name}] {diagnostic.code}: {diagnostic.message} "
                        f"({diagnostic.location})"
                    ),
                    command=f"kairos-ontology compile {name} --check --format json",
                    priority=base + 20,
                    domain=name,
                    target=diagnostic.code,
                    blocking=True,
                )
            )
        if not actions:
            actions.append(
                _action(
                    "fix-diagnostic",
                    ActionStatus.BLOCKING,
                    rationale=(
                        f"Compile check failed for '{name}'. Review the ordered diagnostics."
                    ),
                    command=f"kairos-ontology compile {name} --check --format json",
                    priority=base + 20,
                    domain=name,
                    blocking=True,
                )
            )
        return actions

    # compile_status is PASSED
    actions.append(
        _action(
            "compile-emit",
            ActionStatus.RECOMMENDED,
            rationale=(
                f"'{name}' passes the canonical compile check. Emit artifacts when ready; "
                "a passing check is not a downstream runtime/release guarantee."
            ),
            command=f"kairos-ontology compile {name} --emit",
            priority=base + 30,
            domain=name,
        )
    )
    if domain.gold_policy is InputStatus.PRESENT:
        actions.append(
            _action(
                "review-gold",
                ActionStatus.OPTIONAL,
                rationale=(
                    f"An authored Gold product policy exists for '{name}'. Optionally review "
                    "and regenerate the Gold product; correctness is not auto-proven."
                ),
                command=f"kairos-ontology (invoke kairos-design-gold) [{name}]",
                priority=base + 40,
                domain=name,
            )
        )
    if domain.mdm_policy is InputStatus.PRESENT:
        actions.append(
            _action(
                "review-mdm",
                ActionStatus.OPTIONAL,
                rationale=(
                    f"An authored MDM policy exists for '{name}'. Optionally review the "
                    "design-time MDM policy consumed from the CompilePlan."
                ),
                command=f"kairos-ontology (invoke kairos-design-mdm) [{name}]",
                priority=base + 45,
                domain=name,
            )
        )
    return actions


def _emit_gate_actions(snapshot: HubInputSnapshot) -> list[NextAction]:
    """Optionally surface the offline dbt parse/compile gate (DD-137, opt-in).

    This is advisory and never a mandatory sequential step: the snapshot cannot prove the
    emitted project is fresh or that the current CompilePlan produced it. It appears only when
    an emitted dbt project is observed and at least one domain currently passes the check.
    """
    if snapshot.emitted_dbt_project is InputStatus.UNREADABLE:
        return [
            _action(
                "validate-dbt",
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale=(
                    "output/medallion/dbt is present but unreadable; resolve access before "
                    "running the offline dbt gate."
                ),
                command="kairos-ontology validate-dbt --platform <fabric|databricks>",
                priority=500,
            )
        ]
    if snapshot.emitted_dbt_project is not InputStatus.PRESENT:
        return []
    if not any(
        domain.compile_status is CompileStatus.PASSED for domain in snapshot.domains
    ):
        return []
    platform = snapshot.adapter or "<fabric|databricks>"
    return [
        _action(
            "validate-dbt",
            ActionStatus.OPTIONAL,
            rationale=(
                "An emitted dbt project exists at output/medallion/dbt. Optionally run the "
                "hub-wide offline gate (deps → parse → manifest → compile); it needs no "
                "warehouse and is not a runtime/release guarantee."
            ),
            command=f"kairos-ontology validate-dbt --platform {platform}",
            priority=500,
        )
    ]


def _summarize(actions: tuple[NextAction, ...]) -> str:
    if not actions:
        return "No next action derived: authored inputs present and all domains compile."
    top = actions[0]
    blocking = sum(1 for item in actions if item.blocking)
    lead = f"Recommended next: [{top.kind}] {top.rationale}"
    if blocking:
        lead += f" ({blocking} blocking diagnostic action(s))."
    return lead


def propose_next_actions(snapshot: HubInputSnapshot) -> NextActionProposal:
    """Return a deterministic, advisory next-action proposal from *snapshot*.

    Pure function: no I/O, no persisted state. Identical snapshots always yield an
    identical proposal (stable ordering and content).
    """
    actions: list[NextAction] = list(_hub_level_actions(snapshot))
    for domain in snapshot.domains:
        actions.extend(_domain_actions(domain, snapshot.compile_ran))
    actions.extend(_emit_gate_actions(snapshot))
    ordered = tuple(sorted(actions, key=_sort_key))
    return NextActionProposal(
        schema_version=SCHEMA_VERSION,
        hub_root=snapshot.hub_root,
        actions=ordered,
        summary=_summarize(ordered),
    )
