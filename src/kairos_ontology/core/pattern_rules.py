# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Toolkit-owned coverage ledger over the reference-models pattern library (#280 follow-up).

The pattern library declares ``normativity.naming: normative``, writes MUST rules, and names
anti-patterns with a ``rejection_reason``. Nothing in this toolkit enforces any of it. That
on its own is a defensible state — most of those rules are human judgement. What is *not*
defensible is that the state was **unrecorded**: issue #280 was exactly the
``silently-dropped-relationship`` anti-pattern, named in prose by the library, checked by no
code, and absent from every list, so nobody could see it was missing.

This module is the artifact that makes that absence visible. It is a **ledger, not a gate**:

* it enforces nothing and can fail no build;
* it decides nothing about a hub's ontology — it only describes the toolkit's own reach.

Totality
--------
:func:`coverage_entries` maps every *normative unit* the library publishes onto exactly one
of three classifications:

``enforced_by``
    A toolkit check exists. The entry records the diagnostic code, its ``home``, and the
    ``rejection_reason`` the check stands for.
``not_enforceable``
    A human or semantic judgement the toolkit cannot make, with a concrete reason.
``unrecognized_shape``
    The toolkit has no rule registered for this unit. This is the **forward-compatibility
    bucket**: reference models release on their own cadence, so a newly published
    anti-pattern, a renamed convention, or an entirely new top-level block lands here and
    shows up in ``list-patterns --coverage`` rather than vanishing the way #280 did.

The registry below is **toolkit-owned**. A reference model cannot grant itself enforcement by
declaring something normative; only a check in this repo, recorded here, counts.

Enumeration is deliberately driven off the **raw parsed mapping** (:meth:`Pattern.to_payload`,
which flattens :attr:`Pattern.extra` back in), never off the loader's promoted dataclass
fields. Enumerating promoted fields would test ``pattern_loader``'s field list rather than the
library: a normative block published under a key the loader does not promote — ``naming_rule``
is one today — would be silently outside the ledger while coverage looked complete.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .pattern_loader import Pattern

#: A toolkit check exists for this unit.
ENFORCED = "enforced_by"

#: No toolkit check can exist for this unit; the reason is recorded per entry.
NOT_ENFORCEABLE = "not_enforceable"

#: The toolkit has no rule registered for this unit (new, renamed, or reshaped upstream).
UNRECOGNIZED = "unrecognized_shape"

#: Closed set of ledger classifications. Every enumerated unit maps to exactly one.
CLASSIFICATIONS: tuple[str, ...] = (ENFORCED, NOT_ENFORCEABLE, UNRECOGNIZED)

#: Lower bound on ``enforced_by`` entries, asserted by the totality tests.
#:
#: Without it the totality assertion passes vacuously against an empty registry — every unit
#: would classify as ``not_enforceable``/``unrecognized_shape`` and the ledger would look
#: complete while recording that the toolkit checks nothing. Raise this when a check lands.
MINIMUM_ENFORCED_UNITS = 2

#: Top-level ``pattern.yaml`` keys that carry no normative unit, with the reason each is
#: exempt. Being on this list is a toolkit judgement exactly like ``not_enforceable`` is, so
#: it is stated here rather than hidden in a filter expression: these keys describe *context*
#: (what problem, when it applies, which gap it closes) or ship *input tables* the library
#: itself declares advisory. Anything not on this list and not in :data:`RULE_BEARING_KEYS`
#: becomes an ``unrecognized_shape`` entry.
DESCRIPTIVE_KEYS: dict[str, str] = {
    "id": "the pattern's own identifier",
    "problem": "prose statement of the problem, not a rule",
    "applicability": "prose scope statement, not a rule",
    "normativity": "declares which blocks are normative; it is metadata about rules, not a rule",
    "closes_gap": "cross-reference to reference-models gap-analysis ids",
    "participants": (
        "declared advisory by the patterns that ship it (normativity.participants: advisory); "
        "an input table naming candidate class URIs, not a rule over a hub"
    ),
    "mode_bindings": (
        "a mode -> reservation-target -> module lookup table, validated upstream by "
        "reference-models' own validate_archetypes.py check 6, not a rule over a hub"
    ),
}


@dataclass(frozen=True)
class _KeySpec:
    """How to enumerate normative units out of one top-level ``pattern.yaml`` key."""

    #: Ledger ``kind`` for units produced from this key.
    kind: str
    #: Candidate keys inside a list entry, in priority order, holding the unit's stable id.
    id_keys: tuple[str, ...] = ()
    #: Candidate keys holding a short human label for the unit.
    label_keys: tuple[str, ...] = ()
    #: When set, the whole value is a single unit (prose rules, conditional allowances).
    scalar: bool = False


#: Top-level keys that carry normative units, and how to enumerate them.
#:
#: ``naming_rule`` and ``physical_simplification`` live in :attr:`Pattern.extra` — they are
#: reached only because enumeration walks the raw payload.
RULE_BEARING_KEYS: dict[str, _KeySpec] = {
    "naming_conventions": _KeySpec(
        kind="naming_convention",
        id_keys=("element", "link", "qualifier"),
        label_keys=("convention", "property", "rule", "start_or_arrival"),
    ),
    "anti_patterns": _KeySpec(
        kind="anti_pattern",
        id_keys=("id",),
        label_keys=("description",),
    ),
    "grain_collisions": _KeySpec(
        kind="grain_collision",
        id_keys=("against",),
        label_keys=("reason",),
    ),
    "naming_rule": _KeySpec(kind="naming_rule", scalar=True),
    "physical_simplification": _KeySpec(kind="physical_simplification", scalar=True),
}


@dataclass(frozen=True)
class RuleVerdict:
    """The toolkit's recorded position on one normative unit."""

    classification: str
    #: ``enforced_by`` only: the diagnostic code a hub actually sees.
    diagnostic_code: str = ""
    #: ``enforced_by`` only: which subsystem owns the check (e.g. ``compiler``).
    home: str = ""
    #: ``enforced_by`` only: the library ``rejection_reason`` the check stands for, recorded
    #: here so a reword upstream shows up as drift instead of silently redefining the check.
    rejection_reason: str = ""
    #: ``not_enforceable`` only: why no check can exist.
    reason: str = ""
    #: Supporting file references or citations for the verdict.
    evidence: tuple[str, ...] = ()


def _enforced(
    code: str, *, home: str, rejection_reason: str, evidence: tuple[str, ...] = ()
) -> RuleVerdict:
    return RuleVerdict(
        classification=ENFORCED,
        diagnostic_code=code,
        home=home,
        rejection_reason=rejection_reason,
        evidence=evidence,
    )


def _judgement(reason: str, *, evidence: tuple[str, ...] = ()) -> RuleVerdict:
    return RuleVerdict(classification=NOT_ENFORCEABLE, reason=reason, evidence=evidence)


#: Shared reasons, so units that are unenforceable for the *same* cause say so identically.
_ADVISORY_PARTICIPANTS = (
    "the rule's subject is a class named only in the pattern's participants[] block, which "
    "the pattern itself declares advisory (normativity.participants: advisory); the toolkit "
    "has no way to know which hub class is the order, leg, or reservation. The logistics "
    "accelerator's relationship-registry.yaml, the only machine-readable place that could "
    "bind them, ships 'relationships: []'."
)
_ADVISORY_EVIDENCE = (
    "blueprints/patterns/multimodal-order-leg/pattern.yaml: normativity.participants: advisory",
    "accelerator-packs/logistics/current/blueprint/relationship-registry.yaml: relationships: []",
)
_UNBOUND_PLACEHOLDER = (
    "the convention is a placeholder template with no bound subject: nothing in a hub "
    "declares which class is the '<Dimension>' or which property plays the role, so the "
    "toolkit cannot tell a violation from an unrelated name."
)

#: The toolkit's position on every normative unit the published library ships today, keyed by
#: ``(pattern_id, kind, unit_id)``. A unit with no entry here classifies as
#: ``unrecognized_shape`` — that is the point of the bucket, not an oversight.
RULE_REGISTRY: dict[tuple[str, str, str], RuleVerdict] = {
    # ---------------------------------------------------------------- deferred-relationship
    ("deferred-relationship", "anti_pattern", "silently-dropped-relationship"): _enforced(
        "safety.relationship-endpoint",
        home="compiler",
        rejection_reason=(
            "Data loss, not simplification — the relationship was observed in the source."
        ),
        evidence=(
            "core/compiler/adapter.py: emits binding.object-property-in-fields for an object "
            "property authored under fields:",
            "core/compiler/kernel.py: _adapter_safety_diagnostic remaps it to "
            "safety.relationship-endpoint, and _binding_safety_diagnostics mirrors the same "
            "rule pre-adapter (rule_id DD-133-safety)",
        ),
    ),
    ("deferred-relationship", "anti_pattern", "source-column-named-interim-property"): _judgement(
        "deciding that an interim scalar is named after its source column rather than after "
        "the eventual relationship requires knowing the eventual relationship's name — which, "
        "by this pattern's own applicability, does not exist yet because the target class is "
        "not conformant. A source column name is also frequently the correct canonical name.",
    ),
    ("deferred-relationship", "naming_convention", "eventual_object_property"): _judgement(
        "the convention is the bare placeholder '<relationship>'; naming the eventual object "
        "property is the modelling decision itself, with no derivable token rule to check.",
    ),
    ("deferred-relationship", "naming_convention", "interim_scalar_property"): _judgement(
        "the MUST ('derivable from the eventual object property name by appending Reference') "
        "is relative to a property that does not exist in the hub yet — the pattern applies "
        "precisely while the target class is unresolved, so there is no second name to derive "
        "from at check time.",
    ),
    # ------------------------------------------------------------------- governed-code-list
    ("governed-code-list", "naming_convention", "governed_code_list_class"): _judgement(
        _UNBOUND_PLACEHOLDER,
    ),
    ("governed-code-list", "naming_convention", "raw_source_value"): _judgement(
        _UNBOUND_PLACEHOLDER,
    ),
    ("governed-code-list", "naming_convention", "link_to_governed_code"): _judgement(
        "the 'has<Dimension>Code' link convention scores zero against the authoritative "
        "ontology the pattern library itself ships and cites, and is unsatisfiable wherever "
        "two properties range over one code list, so a check would report the vendored "
        "standard as non-conformant. " + _UNBOUND_PLACEHOLDER,
        evidence=(
            "authoritative-ontologies/IATA/current/IATA-1R-DM-Ontology.ttl: 47 object "
            "properties range over an onerecord code-list class and none is named "
            "has<Dimension>Code",
            "authoritative-ontologies/IATA/current/IATA-1R-DM-Ontology.ttl: :currency and "
            ":currencyUnit both rdfs:range codes:CurrencyCode; :chargeCode and "
            ":carrierChargeCode both rdfs:range codes:ChargeCode — one 'has<Dimension>Code' "
            "name cannot cover two properties over one dimension",
        ),
    ),
    ("governed-code-list", "anti_pattern", "raw-string-as-classification-of-record"): _judgement(
        "requires deciding that a governed dimension *should* exist for this string — a "
        "judgement about whether the value is genuinely sourced from several systems and "
        "whether cross-source disagreement matters here. Nothing a hub declares says so.",
    ),
    ("governed-code-list", "anti_pattern", "implicit-survivorship"): _judgement(
        "survivorship is a stated per-dimension business rule; hubs declare no survivorship "
        "rule anywhere the toolkit reads, so 'whichever source loads last wins' is "
        "indistinguishable from an intentional single-source load.",
    ),
    ("governed-code-list", "grain_collision", "#0"): _judgement(
        "prose about source-noun versus canonical grain: deciding whether a column named "
        "'status' carries current state, a temporal observation, or a lifecycle event is the "
        "modelling judgement itself.",
    ),
    # ----------------------------------------------------------------- multimodal-order-leg
    ("multimodal-order-leg", "naming_convention", "order-identity"): _judgement(
        _ADVISORY_PARTICIPANTS, evidence=_ADVISORY_EVIDENCE
    ),
    ("multimodal-order-leg", "naming_convention", "order-to-ordering-party"): _judgement(
        _ADVISORY_PARTICIPANTS, evidence=_ADVISORY_EVIDENCE
    ),
    ("multimodal-order-leg", "naming_convention", "order-to-leg"): _judgement(
        _ADVISORY_PARTICIPANTS, evidence=_ADVISORY_EVIDENCE
    ),
    ("multimodal-order-leg", "naming_convention", "order-to-consignment"): _judgement(
        _ADVISORY_PARTICIPANTS, evidence=_ADVISORY_EVIDENCE
    ),
    ("multimodal-order-leg", "naming_convention", "leg-to-reservation"): _judgement(
        _ADVISORY_PARTICIPANTS, evidence=_ADVISORY_EVIDENCE
    ),
    ("multimodal-order-leg", "naming_convention", "leg-to-movement"): _judgement(
        _ADVISORY_PARTICIPANTS, evidence=_ADVISORY_EVIDENCE
    ),
    ("multimodal-order-leg", "naming_rule", "naming_rule"): _judgement(
        "multi-clause prose ('never name a property or class on the order after a transport "
        "mode') whose subject is the advisory participants[] block. " + _ADVISORY_PARTICIPANTS,
        evidence=_ADVISORY_EVIDENCE,
    ),
    ("multimodal-order-leg", "anti_pattern", "mode-subclass-on-order"): _judgement(
        _ADVISORY_PARTICIPANTS, evidence=_ADVISORY_EVIDENCE
    ),
    ("multimodal-order-leg", "anti_pattern", "order-subclasses-mode-standard"): _judgement(
        _ADVISORY_PARTICIPANTS, evidence=_ADVISORY_EVIDENCE
    ),
    ("multimodal-order-leg", "anti_pattern", "order-to-reservation-shortcut"): _judgement(
        _ADVISORY_PARTICIPANTS, evidence=_ADVISORY_EVIDENCE
    ),
    ("multimodal-order-leg", "anti_pattern", "order-absorbs-domain-properties"): _judgement(
        "requires classifying each property as cargo, customs, document, or financial — a "
        "semantic judgement with no declared source. " + _ADVISORY_PARTICIPANTS,
        evidence=_ADVISORY_EVIDENCE,
    ),
    ("multimodal-order-leg", "anti_pattern", "document-as-reservation"): _judgement(
        "requires deciding that a hub class *is* the carrier reservation and that another "
        "*is* a transport document. " + _ADVISORY_PARTICIPANTS,
        evidence=_ADVISORY_EVIDENCE,
    ),
    ("multimodal-order-leg", "anti_pattern", "project-cargo-as-mode"): _judgement(
        "'project cargo modelled as a branch of the mode axis' is a statement about modelling "
        "intent; the mode axis is not declared anywhere machine-readable in a hub.",
        evidence=_ADVISORY_EVIDENCE,
    ),
    (
        "multimodal-order-leg",
        "grain_collision",
        "https://www.kairosflow.ai/ont/dcsa/booking#Booking",
    ): _judgement(
        "a grain-collision entry states that two models describe different grains; it is "
        "authoring guidance about what not to merge, not a ban on any triple the toolkit can "
        "look for. Relating to the cited IRI is legitimate and common.",
    ),
    (
        "multimodal-order-leg",
        "grain_collision",
        "https://www.kairosflow.ai/ont/bsp/commercial#SalesOrder",
    ): _judgement(
        "a grain-collision entry states that two models describe different grains; it is "
        "authoring guidance about what not to merge, not a ban on any triple the toolkit can "
        "look for.",
    ),
    (
        "multimodal-order-leg",
        "grain_collision",
        "https://www.kairosflow.ai/ont/tic/handling-operations#Order",
    ): _judgement(
        "a grain-collision entry states that two models describe different grains; it is "
        "authoring guidance about what not to merge, not a ban on any triple the toolkit can "
        "look for.",
    ),
    (
        "multimodal-order-leg",
        "grain_collision",
        "https://www.kairosflow.ai/ont/mmt/documents#TransportInstructions",
    ): _judgement(
        "a grain-collision entry states that two models describe different grains; it is "
        "authoring guidance about what not to merge, not a ban on any triple the toolkit can "
        "look for.",
    ),
    # ------------------------------------------------------------- qualified-role-assignment
    ("qualified-role-assignment", "naming_convention", "role_assignment_class"): _judgement(
        "'<Identity>RoleAssignment' presupposes a decision the toolkit cannot make: which "
        "class is the durable identity and which usage of it is a role. " + _UNBOUND_PLACEHOLDER,
    ),
    ("qualified-role-assignment", "naming_convention", "link_to_identity"): _judgement(
        _UNBOUND_PLACEHOLDER,
    ),
    ("qualified-role-assignment", "naming_convention", "link_to_context"): _judgement(
        _UNBOUND_PLACEHOLDER,
    ),
    ("qualified-role-assignment", "naming_convention", "role_value_property"): _judgement(
        "'hasRole' is a fixed token, but the rule is that the *role value* property carries "
        "it; nothing declares which property holds a role value, so the toolkit can neither "
        "find a violation nor distinguish an unrelated 'hasRole' from a conforming one.",
    ),
    ("qualified-role-assignment", "physical_simplification", "physical_simplification"): (
        _judgement(
            "an explicitly conditional allowance: it turns on whether the first slice needs "
            "role history, whether an identity ever holds conflicting roles concurrently, and "
            "whether the flags are documented as a projection — three facts about intent, not "
            "about the artifact.",
        )
    ),
    ("qualified-role-assignment", "anti_pattern", "subclass-identity-by-role"): _judgement(
        "requires knowing that the superclass is a durable identity and the subclass is a "
        "role rather than a genuine specialisation; 'Shipper subClassOf Party' and a "
        "legitimate taxonomy are structurally identical.",
    ),
    (
        "qualified-role-assignment",
        "anti_pattern",
        "equal-labels-treated-as-equivalent",
    ): _judgement(
        "the rule turns on 'without checking grain' — a judgement about whether the author "
        "checked, not about the triple. Flagging cross-namespace owl:equivalentClass here would "
        "fire on a documented practice: the logistics accelerator's BLUEPRINT.md tells authors "
        "to add owl:equivalentClass when cross-model *querying* is needed, and DD-032 covers "
        "local equivalents of reference-model classes. Note the scope: that is a downstream "
        "graph-query concern. The compiler does not read owl:equivalentClass at all — anchoring "
        "for inherited properties and relationship endpoints is rdfs:subClassOf only (#730), "
        "and the validator says so per triple (class_equivalence_not_a_compile_anchor).",
        evidence=(
            "accelerator-packs/logistics/client-hub-blueprint/BLUEPRINT.md: 'Equivalence later "
            "| Add owl:equivalentClass only if cross-model querying is needed'",
            "docs/dev/toolkit-design-decisions.md: DD-032 reference-model alignment",
            "core/semantic_index.py: surfaces OWL.equivalentClass under the kairos-design/owl-rl "
            "profiles only; core/compiler loads the rdfs profile and never reads it",
        ),
    ),
    # grain_collisions for qualified-role-assignment now key by the `against` IRI
    # (5 role-bearing party parents + 2 DCSA location role classes).
    (
        "qualified-role-assignment",
        "grain_collision",
        "https://www.kairosflow.ai/ont/bsp/party#TradeParty",
    ): _judgement(
        "a role-bearing party parent with a trade (buy-ship-pay) context; not the durable "
        "identity. Identifying which hub class is 'the durable identity' is the judgement.",
    ),
    (
        "qualified-role-assignment",
        "grain_collision",
        "https://www.kairosflow.ai/ont/mmt/party#TransportParty",
    ): _judgement(
        "a role-bearing party parent with a transport-operations context; not the durable "
        "identity. Identifying which hub class is 'the durable identity' is the judgement.",
    ),
    (
        "qualified-role-assignment",
        "grain_collision",
        "https://www.kairosflow.ai/ont/dcsa/party#ShippingParty",
    ): _judgement(
        "a role-bearing party parent with a container-shipping context; not the durable "
        "identity. Identifying which hub class is 'the durable identity' is the judgement.",
    ),
    (
        "qualified-role-assignment",
        "grain_collision",
        "https://www.kairosflow.ai/ont/imo/party#MaritimeParty",
    ): _judgement(
        "a role-bearing party parent with a maritime/regulatory context; not the durable "
        "identity. Identifying which hub class is 'the durable identity' is the judgement.",
    ),
    (
        "qualified-role-assignment",
        "grain_collision",
        "https://www.kairosflow.ai/ont/tic/party#TerminalParty",
    ): _judgement(
        "a role-bearing party parent with a terminal-operations context; not the durable "
        "identity. Identifying which hub class is 'the durable identity' is the judgement.",
    ),
    (
        "qualified-role-assignment",
        "grain_collision",
        "https://www.kairosflow.ai/ont/dcsa/locations#PortOfLoading",
    ): _judgement(
        "DCSA specialises Location by shipment role; whether a hub's location classes "
        "materialise roles as places is a modelling judgement.",
    ),
    (
        "qualified-role-assignment",
        "grain_collision",
        "https://www.kairosflow.ai/ont/dcsa/locations#PortOfDischarge",
    ): _judgement(
        "DCSA specialises Location by shipment role; whether a hub's location classes "
        "materialise roles as places is a modelling judgement.",
    ),
    # ----------------------------------------------------------------------- temporal-quartet
    ("temporal-quartet", "naming_convention", "requested"): _judgement(
        "the convention gives the preferred name for a *role* (the requested start of an "
        "activity); nothing in a hub declares that a given timestamp plays that role, so a "
        "check can only compare tokens it has no reason to expect.",
    ),
    ("temporal-quartet", "naming_convention", "planned"): _judgement(
        "the convention gives the preferred name for a role no hub artifact declares; see "
        "the 'requested' row.",
    ),
    ("temporal-quartet", "naming_convention", "estimated"): _judgement(
        "the convention gives the preferred name for a role no hub artifact declares; see "
        "the 'requested' row.",
    ),
    ("temporal-quartet", "naming_convention", "actual"): _judgement(
        "the convention gives the preferred name for a role no hub artifact declares; see "
        "the 'requested' row.",
    ),
    ("temporal-quartet", "naming_rule", "naming_rule"): _judgement(
        "the MUST ('never substitute a synonym') is open-ended while the prose names only "
        "three example tokens, so any implementation would be a guess at the real rule; and a "
        "token ban on 'due' would fire on the reference models themselves.",
        evidence=(
            "derived-ontologies/BSP/current/financial/financial.ttl declares dueDate; "
            "WCO customs, IMO maritime-security and MMT consignment each declare a "
            "*DueDate property",
        ),
    ),
    ("temporal-quartet", "anti_pattern", "synonym-for-estimated-or-requested"): _enforced(
        "temporal_quartet_synonym_ban",
        home="validator",
        rejection_reason=(
            "This is the exact naming drift this pattern was shipped normative to stop."
        ),
        evidence=(
            "core/validator.py: _check_temporal_quartet_synonyms, called from "
            "validate_naming_conventions when a temporal-quartet pattern.yaml is resolvable "
            "via --ref-models",
            "blueprints/patterns/temporal-quartet/pattern.yaml: banned_name_tokens, "
            "applies_to_ranges and a closed exemptions[] list now resolve the two "
            "objections this entry used to record",
        ),
    ),
    ("temporal-quartet", "anti_pattern", "overwrite-actual-in-place"): _judgement(
        "the defect is a *mutation over time* — a correction overwriting an earlier literal. "
        "A static artifact holds one state; observing this needs two loads compared at "
        "runtime, which no authoring-time or compile-time check sees.",
    ),
}


@dataclass(frozen=True)
class CoverageEntry:
    """One normative unit and the toolkit's recorded position on it."""

    pattern: str
    key: str
    kind: str
    unit: str
    label: str
    classification: str
    diagnostic_code: str = ""
    home: str = ""
    rejection_reason: str = ""
    reason: str = ""
    evidence: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON/YAML-friendly dict, omitting fields that do not apply."""
        payload: dict[str, Any] = {
            "pattern": self.pattern,
            "key": self.key,
            "kind": self.kind,
            "unit": self.unit,
            "classification": self.classification,
        }
        if self.label:
            payload["label"] = self.label
        for name in ("diagnostic_code", "home", "rejection_reason", "reason"):
            value = getattr(self, name)
            if value:
                payload[name] = value
        if self.evidence:
            payload["evidence"] = list(self.evidence)
        return payload


@dataclass(frozen=True)
class CoverageLedger:
    """The total ledger over one pattern library, plus everything that made it partial."""

    entries: tuple[CoverageEntry, ...]
    warnings: tuple[str, ...] = ()
    patterns_seen: tuple[str, ...] = ()
    stale_registry_entries: tuple[str, ...] = ()
    quality_warnings: tuple[str, ...] = field(default=())

    @property
    def totals(self) -> dict[str, int]:
        """Return unit counts per classification (all classifications always present)."""
        counts = {name: 0 for name in CLASSIFICATIONS}
        for entry in self.entries:
            counts[entry.classification] = counts.get(entry.classification, 0) + 1
        counts["units"] = len(self.entries)
        return counts

    def to_payload(self) -> dict[str, Any]:
        """Return a JSON/YAML-friendly dict for ``list-patterns --coverage``."""
        return {
            "patterns": list(self.patterns_seen),
            "totals": self.totals,
            "minimum_enforced_units": MINIMUM_ENFORCED_UNITS,
            "units": [entry.to_payload() for entry in self.entries],
            "descriptive_keys": dict(DESCRIPTIVE_KEYS),
            "stale_registry_entries": list(self.stale_registry_entries),
            "warnings": list(self.warnings),
        }


def _text(value: Any) -> str:
    """Return a single-line, trimmed rendering of a YAML scalar-ish value."""
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    return " ".join(str(value).split())


def _unit_id(entry: Any, spec: _KeySpec, index: int) -> str:
    """Return a stable id for one list entry under a rule-bearing key.

    Prefers a declared id key. Prose entries (``grain_collisions`` ships bare strings in two
    published patterns) have nothing stable to key on, so they fall back to ``#<index>``:
    reordering them re-buckets them as ``unrecognized_shape``, which is loud and visible
    rather than silent.
    """
    if isinstance(entry, Mapping):
        for name in spec.id_keys:
            value = _text(entry.get(name))
            if value:
                return value
    return f"#{index}"


def _unit_label(entry: Any, spec: _KeySpec) -> str:
    if isinstance(entry, Mapping):
        for name in spec.label_keys:
            value = _text(entry.get(name))
            if value:
                return value
        return ""
    return _text(entry)


def _classify(pattern_id: str, kind: str, unit_id: str) -> RuleVerdict:
    verdict = RULE_REGISTRY.get((pattern_id, kind, unit_id))
    if verdict is not None:
        return verdict
    return RuleVerdict(
        classification=UNRECOGNIZED,
        reason=(
            "no toolkit rule is registered for this unit — it is new, renamed, or reshaped "
            "upstream. Classify it in core/pattern_rules.py (this is the bucket that keeps a "
            "newly published rule visible instead of absent)."
        ),
    )


def _entry_for(pattern_id: str, key: str, kind: str, unit_id: str, label: str) -> CoverageEntry:
    verdict = _classify(pattern_id, kind, unit_id)
    return CoverageEntry(
        pattern=pattern_id,
        key=key,
        kind=kind,
        unit=unit_id,
        label=label,
        classification=verdict.classification,
        diagnostic_code=verdict.diagnostic_code,
        home=verdict.home,
        rejection_reason=verdict.rejection_reason,
        reason=verdict.reason,
        evidence=verdict.evidence,
    )


def enumerate_units(pattern: Pattern) -> list[CoverageEntry]:
    """Return one ledger entry per normative unit declared by *pattern*.

    Walks :meth:`Pattern.to_payload` — the **raw** parsed mapping with ``extra`` flattened
    back in — so a normative block under a key the loader does not promote still produces
    entries, and a top-level key the toolkit has never seen produces an ``unrecognized_shape``
    entry instead of disappearing.
    """
    entries: list[CoverageEntry] = []
    payload = pattern.to_payload()
    for key in sorted(payload):
        value = payload[key]
        if key in DESCRIPTIVE_KEYS:
            continue
        spec = RULE_BEARING_KEYS.get(key)
        if spec is None:
            entries.append(
                CoverageEntry(
                    pattern=pattern.id,
                    key=key,
                    kind="unknown_key",
                    unit=key,
                    label=_text(value)[:160],
                    classification=UNRECOGNIZED,
                    reason=(
                        f"top-level key '{key}' is neither a known rule-bearing block nor a "
                        "declared descriptive key. Reference models publish independently, so "
                        "a new block lands here rather than vanishing; classify it in "
                        "core/pattern_rules.py."
                    ),
                )
            )
            continue
        if spec.scalar:
            if value in (None, "", [], {}):
                continue
            entries.append(
                _entry_for(pattern.id, key, spec.kind, key, _text(value)[:160]),
            )
            continue
        if not isinstance(value, Sequence) or isinstance(value, str | bytes):
            if value in (None, "", {}):
                continue
            entries.append(
                CoverageEntry(
                    pattern=pattern.id,
                    key=key,
                    kind=spec.kind,
                    unit=key,
                    label=_text(value)[:160],
                    classification=UNRECOGNIZED,
                    reason=(
                        f"'{key}' is published as {type(value).__name__} but the toolkit "
                        "enumerates it as a list of entries; its units cannot be identified."
                    ),
                )
            )
            continue
        for index, item in enumerate(value):
            entries.append(
                _entry_for(
                    pattern.id,
                    key,
                    spec.kind,
                    _unit_id(item, spec, index),
                    _unit_label(item, spec),
                )
            )
    return entries


def coverage_entries(patterns: Iterable[Pattern]) -> list[CoverageEntry]:
    """Return the total ledger entries for *patterns*, sorted for stable output."""
    entries: list[CoverageEntry] = []
    for pattern in patterns:
        entries.extend(enumerate_units(pattern))
    return sorted(entries, key=lambda e: (e.pattern, e.key, e.unit))


def stale_registry_entries(patterns: Iterable[Pattern]) -> list[str]:
    """Return registry keys with no matching unit in *patterns*.

    A stale key means the toolkit records a position on a rule the library no longer
    publishes — including, for an ``enforced_by`` key, a check whose justification has
    quietly disappeared. Advisory only; nothing fails on it.
    """
    seen = {(e.pattern, e.kind, e.unit) for e in coverage_entries(patterns)}
    return sorted(
        f"{pattern}/{kind}/{unit}"
        for (pattern, kind, unit) in RULE_REGISTRY
        if (pattern, kind, unit) not in seen
    )


def _drift_warnings(entries: Iterable[CoverageEntry], patterns: Iterable[Pattern]) -> list[str]:
    """Warn when an enforced unit's published ``rejection_reason`` no longer matches ours."""
    published: dict[tuple[str, str], str] = {}
    for pattern in patterns:
        for item in pattern.to_payload().get("anti_patterns") or []:
            if isinstance(item, Mapping):
                published[(pattern.id, _text(item.get("id")))] = _text(item.get("rejection_reason"))
    warnings: list[str] = []
    for entry in entries:
        if entry.classification != ENFORCED or not entry.rejection_reason:
            continue
        live = published.get((entry.pattern, entry.unit))
        if live is not None and live != _text(entry.rejection_reason):
            warnings.append(
                f"Pattern '{entry.pattern}': anti_pattern '{entry.unit}' is recorded as "
                f"enforced by {entry.diagnostic_code}, but its published rejection_reason has "
                f"changed since the check was registered (published: {live!r})."
            )
    return warnings


def build_ledger(
    patterns: Sequence[Pattern], quality_warnings: Sequence[str] = ()
) -> CoverageLedger:
    """Assemble the coverage ledger for a loaded pattern library.

    *quality_warnings* are :func:`pattern_loader.load_patterns`' own warnings. They belong in
    the ledger rather than only on stderr: a pattern that was skipped or shipped hollow is
    *absent* from the ledger, so coverage would otherwise read as complete over a library
    that is quietly short a pattern.
    """
    entries = coverage_entries(patterns)
    warnings = list(quality_warnings) + _drift_warnings(entries, patterns)
    return CoverageLedger(
        entries=tuple(entries),
        warnings=tuple(warnings),
        patterns_seen=tuple(p.id for p in patterns),
        stale_registry_entries=tuple(stale_registry_entries(patterns)),
        quality_warnings=tuple(quality_warnings),
    )
