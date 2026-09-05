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
#: v3 adds three observation sets in one batch: source-sample-coverage evidence
#: (``source_samples`` / ``SourceSampleObservation``, issue #298), the
#: ``discovery_conformance``/``discovery_gate_satisfied`` fields mirrored into the rendered
#: ``discovery:`` status line and JSON payload (issue #310), and the DD-047 materialized
#: reference-inventory freshness gate (``inventory_status``, issue #321).
#: v4 adds the BI concept-mapping worksheet observation (``bi_concept_mappings`` /
#: ``BiConceptMappingObservation``) and the ``triage-concept-mapping`` action routed to
#: kairos-design-source (issue #421, DD-157): import-tmdl's demand evidence was generated
#: and then never routed to anyone.
#: v5 adds the source-affinity domain-coverage observation (``source_domain_coverage`` /
#: ``SourceDomainCoverageObservation``) and its two actions ``model-data-driven-domain``
#: and ``bind-deferred-domain`` (issue #496/#498, DD-160): affinity analysis and the
#: binding inventory both existed but were never joined, so a domain holding real source
#: data with nothing bound was invisible outside a hand-written report.
#: v6 adds the registered-concept observation (``registered_concepts_unbound``) and its
#: ``model-registered-concept`` action routed to kairos-design-domain (issue #505 Layer B,
#: DD-162): registration records that a source-discovered concept belongs, but nothing routed
#: anyone to actually model and bind it.
#: v7 adds the source-disposition observation (``source_dispositions`` /

#: ``SourceDispositionObservation``) and its blocking ``record-source-disposition`` action

#: routed to kairos-design-source (DD-164). ``validate`` already hard-failed on an

#: undecided source table, but no skill step and no next action ever proposed recording

#: one -- the only gate in the flow enforced without being asked for, which is how a hub

#: reached 70 outstanding decisions before anyone was told.

SCHEMA_VERSION = 7


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


class DiscoveryConformanceStatus(str, Enum):
    """Observed state of the discovery conformance artifact (DD-148).

    A defensible presence/validity observation, same spirit as :class:`InputStatus` —
    never "complete". The real hard gate lives in ``kairos-ontology compile``/``validate``
    (``check_discovery_gate()``); this is only the advisory signal mirrored into
    ``kairos-ontology next``.
    """

    NOT_RUN = "not_run"
    VALID = "valid"
    INVALID = "invalid"
    UNRESOLVED_FLEET = "unresolved_fleet"


class SourceSampleStatus(str, Enum):
    """Observed coverage of source-vocabulary sample evidence (issue #298).

    A defensible presence observation over ``kairos-bronze:sampleValues``, same spirit as
    :class:`InputStatus` — never "complete". A schema with no sample evidence at all is a
    real risk signal: mapping confidence built on schema names alone, with zero real data
    ever inspected.
    """

    NOT_APPLICABLE = "not_applicable"
    NONE = "none"
    PARTIAL = "partial"
    FULL = "full"


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
    "resolve-discovery-open-questions": "kairos-design-discovery",
    "design-source": "kairos-design-source",
    # DD-164: the table-grain scope decision belongs to the source lifecycle owner. It is
    # the one gate `validate` enforced with no step proposing it.
    "record-source-disposition": "kairos-design-source",
    # #421/DD-157: worksheet triage belongs to the import-tmdl lifecycle owner
    # (kairos-design-source), NOT to kairos-design-domain, whose charter forbids
    # filling the worksheet during a design slice.
    "triage-concept-mapping": "kairos-design-source",
    # #496/#498, DD-160: a domain with source data but no ontology is a modeling
    # decision (design-domain); one that is modeled but unbound is a binding decision
    # (design-mapping). Splitting them keeps each action routed to the skill that can
    # actually act on it.
    "model-data-driven-domain": "kairos-design-domain",
    "bind-deferred-domain": "kairos-design-mapping",
    # #505 Layer B: registration records that a concept belongs and names its source
    # evidence; authoring the class is still a domain-design decision.
    "model-registered-concept": "kairos-design-domain",
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
    passthrough_count: int = 0
    canonical_count: int = 0


@dataclass(frozen=True, slots=True)
class SourceSampleObservation:
    """Observed source-vocabulary sample-evidence coverage (issue #298).

    ``tables_total`` is every ``kairos-bronze:SourceTable`` discovered across authored
    source vocabulary TTL; ``tables_with_samples`` is the subset where at least one column
    carries a ``kairos-bronze:sampleValues`` predicate.
    """

    status: SourceSampleStatus = SourceSampleStatus.NOT_APPLICABLE
    tables_with_samples: int = 0
    tables_total: int = 0


@dataclass(frozen=True, slots=True)
class BiConceptMappingObservation:
    """Observed triage state of import-tmdl's concept-mapping worksheets (issue #421).

    ``tables_total`` counts every table entry across ``*-concept-mapping.yaml``
    worksheets (current ``integration/discovery/bi/`` and the legacy
    ``integration/sources/`` location).

    ``tables_untriaged`` is the subset with no ``action`` recorded — the actual
    backlog, and what the recommendation gates on. ``tables_unfilled`` is the subset
    with no ``reference_model_match``; it is carried for context but must not drive a
    recommendation, because ``action: skip`` and ``action: new_class`` both leave it
    empty as their correct terminal state (issue #687).

    The zero-valued default is the no-observation state, so existing constructor call
    sites never start reporting a spurious action (same precedent as
    ``inventory_status``).
    """

    tables_total: int = 0
    tables_unfilled: int = 0
    tables_untriaged: int = 0


@dataclass(frozen=True, slots=True)
class SourceDispositionObservation:
    """Source tables with no recorded outcome -- bound or explicitly disposed (DD-164).

    ``validate`` hard-fails on these, and until now **nothing proposed recording them**:
    DD-164 was the only gate in the flow with no skill step and no next action, so the
    first an operator heard of it was a red validate late in a run. On the hub that
    prompted this, 70 tables were outstanding at once.

    Recording an outcome is a human decision -- "this table is not business data", "this
    is deferred" -- so this is advisory and blocking, never auto-applied. It is distinct
    from the *column*-grain gap gate (DD-169/DD-186, ``draft-gap-decisions``): this asks
    whether the table is in scope at all.

    All-zero is the no-observation default, so existing constructor call sites derive no
    action -- the same precedent as ``bi_concept_mappings`` and ``source_domain_coverage``.
    """

    tables_total: int = 0
    tables_undecided: int = 0

    @property
    def coverage(self) -> float:
        """Fraction with any recorded outcome. 1.0 when there is nothing to decide."""
        if self.tables_total <= 0:
            return 1.0
        return (self.tables_total - self.tables_undecided) / self.tables_total


@dataclass(frozen=True, slots=True)
class SourceDomainCoverageObservation:
    """Domains holding real source data that the hub has not modeled or bound (DD-160).

    Derived from the join of the persisted ``*-affinity.yaml`` source assignments against
    the authored ontologies and bindings. ``not_modeled`` are candidate domains to add;
    ``deferred`` and ``blocked`` are modeled domains whose source data has nowhere to
    land yet. ``unassigned_tables`` counts source tables the affinity pass could assign to
    no domain at all -- the strongest "the ontology has no home for this" signal.

    All-empty is the no-observation default (no affinity reports were found), so existing
    constructor call sites never start reporting a spurious action -- same precedent as
    ``inventory_status`` and ``bi_concept_mappings``.
    """

    not_modeled: tuple[str, ...] = ()
    deferred: tuple[str, ...] = ()
    unassigned_tables: int = 0


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
    #: Presence of the unified emitted dbt project
    #: (ontology-hub-publish/medallion/dbt/dbt_project.yml).
    #: This is the only defensible emitted-output observation; it never implies freshness or
    #: that the current CompilePlan produced it.
    emitted_dbt_project: InputStatus = InputStatus.MISSING
    #: Configured adapter from kairos.yaml, used only to render the validate-dbt command.
    adapter: str = ""
    #: Validity of the discovery conformance artifact, when present (DD-148).
    discovery_conformance: DiscoveryConformanceStatus = DiscoveryConformanceStatus.NOT_RUN
    #: Source-vocabulary sample-evidence coverage (issue #298).
    source_samples: SourceSampleObservation = SourceSampleObservation()
    #: DD-047 materialized reference-inventory freshness (issue #321). PRESENT by default
    #: so existing constructor call sites (tests, callers that never observed this) do not
    #: silently start reporting a spurious blocking gate.
    inventory_status: InputStatus = InputStatus.PRESENT
    #: BI concept-mapping worksheet triage state (issue #421, DD-157). The zero default
    #: is the no-observation state — no action is derived from it.
    bi_concept_mappings: BiConceptMappingObservation = BiConceptMappingObservation()
    #: Source-affinity vs modeled/bound domain coverage (issue #496/#498, DD-160). The
    #: all-empty default is the no-observation state.
    source_domain_coverage: SourceDomainCoverageObservation = SourceDomainCoverageObservation()
    #: Registered source-discovered concepts with no EntityBinding yet (#505 Layer B). Zero
    #: default is the no-observation state, so existing constructor call sites derive no
    #: action -- same precedent as ``bi_concept_mappings``.
    registered_concepts_unbound: int = 0
    #: Source tables with no recorded outcome (DD-164). All-zero is the no-observation
    #: state; ``validate`` fails on a non-zero undecided count.
    source_dispositions: SourceDispositionObservation = SourceDispositionObservation()


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


def discovery_gate_satisfied(snapshot: HubInputSnapshot) -> bool:
    """True when DD-148 discovery evidence exists via either signal (glossary TTL or artifact).

    Single source of truth for both the rationale text and the status rendering (#310).
    """
    return (
        snapshot.discovery is InputStatus.PRESENT
        or snapshot.discovery_conformance is not DiscoveryConformanceStatus.NOT_RUN
    )


def _hub_level_actions(snapshot: HubInputSnapshot) -> list[NextAction]:
    actions: list[NextAction] = []
    if snapshot.discovery is InputStatus.UNREADABLE:
        actions.append(
            _action(
                "design-discovery",
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale="businessdiscovery/ is present but unreadable; resolve access.",
                command="kairos-ontology (invoke kairos-design-discovery)",
                priority=5,
            )
        )
    elif snapshot.discovery is InputStatus.MISSING:
        # DD-148: kairos-ontology compile/validate accept EITHER an authored
        # businessdiscovery/*.ttl glossary (this check) OR a conformance artifact
        # (discovery_conformance) as evidence discovery ran — only block here when
        # neither exists.
        no_conformance_either = not discovery_gate_satisfied(snapshot)
        actions.append(
            _action(
                "design-discovery",
                ActionStatus.BLOCKING
                if no_conformance_either
                else ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale=(
                    (
                        "No business discovery evidence found — neither an authored "
                        "businessdiscovery/*.ttl glossary (prose notes in that folder "
                        "don't satisfy DD-048) nor a discovery conformance artifact "
                        "(DD-148). kairos-ontology compile/validate now hard-fail on "
                        "this — run kairos-design-discovery before design proceeds."
                    )
                    if no_conformance_either
                    else (
                        "No authored businessdiscovery/*.ttl glossary found (prose "
                        "notes in that folder don't satisfy DD-048), though a "
                        "discovery conformance artifact exists and satisfies the "
                        "compile/validate gate (DD-148). Still recommended for full "
                        "business-terminology alignment."
                    )
                ),
                command="kairos-ontology (invoke kairos-design-discovery)",
                priority=10,
                blocking=no_conformance_either,
            )
        )
    if snapshot.discovery_conformance is DiscoveryConformanceStatus.UNRESOLVED_FLEET:
        actions.append(
            _action(
                "resolve-discovery-open-questions",
                ActionStatus.BLOCKING,
                rationale=(
                    "The discovery conformance artifact was produced under fleet mode "
                    "(DD-088) and has unresolved AI-decided concept judgments (DD-148). "
                    "kairos-ontology compile/validate hard-fail until a human confirms "
                    "them via kairos-design-discovery."
                ),
                command="kairos-ontology discovery-conformance validate",
                priority=25,
                blocking=True,
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
    if snapshot.source_samples.status is SourceSampleStatus.NONE:
        actions.append(
            _action(
                "design-source",
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale=(
                    f"integration/sources/ has {snapshot.source_samples.tables_total} "
                    "table(s) but none carry a kairos-bronze:sampleValues predicate — "
                    "sample evidence is completely absent. Mapping confidence built on "
                    "schema names alone, with no real data ever inspected. Re-import with "
                    "real sample data before proceeding."
                ),
                command="kairos-ontology (invoke kairos-design-source)",
                priority=21,
            )
        )
    elif snapshot.source_samples.status is SourceSampleStatus.PARTIAL:
        missing = snapshot.source_samples.tables_total - snapshot.source_samples.tables_with_samples
        actions.append(
            _action(
                "design-source",
                ActionStatus.OPTIONAL,
                rationale=(
                    f"{missing} of {snapshot.source_samples.tables_total} source table(s) "
                    "carry no kairos-bronze:sampleValues. Consider re-importing those "
                    "tables with real sample data for complete mapping evidence."
                ),
                command="kairos-ontology (invoke kairos-design-source)",
                priority=22,
            )
        )
    # Gated on tables_untriaged, not tables_unfilled: `action: skip` and
    # `action: new_class` are complete triage outcomes that leave
    # reference_model_match empty forever, so the old gate could never retire and kept
    # this the top recommendation on a 91%-decided hub (issue #687).
    if snapshot.bi_concept_mappings.tables_untriaged > 0:
        observation = snapshot.bi_concept_mappings
        actions.append(
            _action(
                "triage-concept-mapping",
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale=(
                    f"{observation.tables_untriaged} of {observation.tables_total} BI "
                    "concept-mapping table(s) under "
                    "integration/discovery/bi/*-concept-mapping.yaml record no "
                    "action — import-tmdl generated demand evidence a human never "
                    "triaged. Record use | specialize | new_class | skip on each. "
                    "Rows matched to a class feed two deterministic consumers: "
                    "design-landscape (advisory bi_weight) and draft-model-report. "
                    "Triage belongs to the import-tmdl lifecycle (kairos-design-source); "
                    "it stays demand evidence, never business authority (DD-147)."
                ),
                command="kairos-ontology (invoke kairos-design-source)",
                priority=23,
            )
        )
    coverage = snapshot.source_domain_coverage
    if coverage.not_modeled:
        actions.append(
            _action(
                "model-data-driven-domain",
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale=(
                    f"{len(coverage.not_modeled)} domain(s) have source tables assigned by "
                    "analyse-sources but no ontology under model/ontologies/: "
                    f"{', '.join(coverage.not_modeled)}"
                    + (
                        f"; plus {coverage.unassigned_tables} source table(s) assigned to no "
                        "domain at all"
                        if coverage.unassigned_tables
                        else ""
                    )
                    + ". This is real source data with no canonical home. Modeling it is a "
                    "human decision — the blueprint deliberately scopes which domains exist "
                    "(DD-149/DD-150), so adding one is a design call, not an automatic step."
                ),
                command="kairos-ontology domain-coverage",
                priority=24,
            )
        )
    if snapshot.source_dispositions.tables_undecided:
        obs = snapshot.source_dispositions
        actions.append(
            _action(
                "record-source-disposition",
                # HUMAN_DECISION_REQUIRED rather than BLOCKING: `validate` does block on
                # it (hence blocking=True), but the reason it cannot be automated is that
                # "is this table in scope" is a judgement, not a derivable fact.
                ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale=(
                    f"{obs.tables_undecided} of {obs.tables_total} source table(s) have no "
                    f"recorded outcome ({obs.coverage:.0%} decided). `validate` fails on this "
                    "(DD-164), and nothing in the flow proposed it until now — which is how a "
                    "hub reached 70 outstanding decisions before anyone was told. Each table "
                    "needs a human call: bound to a domain, or explicitly disposed as "
                    "not-business-data, deferred, or a blueprint gap. This is the table-grain "
                    "question 'is this in scope at all', not the column-grain gap gate."
                ),
                command=(
                    "kairos-ontology source-disposition list --undecided   # then, per table:\n"
                    "  kairos-ontology source-disposition set --system <s> --table <t> "
                    "--disposition <not-business-data|deferred|blueprint-gap> "
                    '--rationale "<why>"'
                ),
                priority=23,
                blocking=True,
            )
        )
    if snapshot.registered_concepts_unbound:
        actions.append(
            _action(
                "model-registered-concept",
                ActionStatus.RECOMMENDED,
                rationale=(
                    f"{snapshot.registered_concepts_unbound} source-discovered concept(s) are "
                    "registered (#505) but no EntityBinding targets them. Registration records "
                    "that the concept belongs and names the source evidence; it does not model "
                    "or bind it. Author the class in a domain ontology, then bind it."
                ),
                command="kairos-ontology design-landscape --format json",
                priority=26,
            )
        )
    if coverage.deferred:
        affected = list(coverage.deferred)
        actions.append(
            _action(
                "bind-deferred-domain",
                ActionStatus.RECOMMENDED,
                rationale=(
                    f"{len(affected)} modeled domain(s) have source tables assigned but no "
                    f"EntityBinding: {', '.join(affected)}. Silver models cannot carry data "
                    "for a domain nothing binds."
                ),
                command="kairos-ontology domain-coverage",
                priority=25,
            )
        )
    if not snapshot.domains:
        discovery_blocks = (
            snapshot.discovery is InputStatus.MISSING
            and snapshot.discovery_conformance is DiscoveryConformanceStatus.NOT_RUN
        ) or snapshot.discovery_conformance is DiscoveryConformanceStatus.UNRESOLVED_FLEET
        actions.append(
            _action(
                "design-domain",
                ActionStatus.BLOCKING if discovery_blocks else ActionStatus.HUMAN_DECISION_REQUIRED,
                rationale=(
                    "No canonical ontology or binding domain found yet. Author a canonical "
                    "OWL/Turtle domain model to begin."
                    + (
                        " Blocked on discovery (DD-148) — resolve it first."
                        if discovery_blocks
                        else ""
                    )
                ),
                command="kairos-ontology (invoke kairos-design-domain)",
                priority=30,
                blocking=discovery_blocks,
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
                        f"[{name}] {diagnostic.code}: {diagnostic.message} ({diagnostic.location})"
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
                    "ontology-hub-publish/medallion/dbt is present but unreadable; resolve "
                    "access before running the offline dbt gate."
                ),
                command="kairos-ontology validate-dbt",
                priority=500,
            )
        ]
    if snapshot.emitted_dbt_project is not InputStatus.PRESENT:
        return []
    if not any(domain.compile_status is CompileStatus.PASSED for domain in snapshot.domains):
        return []

    return [
        _action(
            "validate-dbt",
            ActionStatus.OPTIONAL,
            rationale=(
                "An emitted dbt project exists at ontology-hub-publish/medallion/dbt. Optionally "
                "run the hub-wide offline gate (deps → parse → manifest → compile); it needs no "
                "warehouse and is not a runtime/release guarantee."
            ),
            command="kairos-ontology validate-dbt",
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
