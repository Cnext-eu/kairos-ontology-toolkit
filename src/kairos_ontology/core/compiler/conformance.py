# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic multi-source conformance planning for v5 EntityBindings (DD-133)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .bindings import EntityBinding, UnionPolicy
from .result import CompileDiagnostic, CompileError, SourceLocation
from .scope import ProvenanceInput


@dataclass(frozen=True, slots=True)
class ConformanceTypeContract:
    """Resolved canonical types used to compare one binding with its peers."""

    grain: tuple[str, ...]
    identity: tuple[str, ...]
    properties: tuple[tuple[str, str], ...]
    #: ``(property, canonical type label)`` for each mapped field whose expression is a
    #: plain source column, carrying **bounded type parameters** -- ``string(50)`` rather
    #: than ``string``. Held separately from ``properties`` above, which deliberately
    #: compares type *kind* only and must keep doing so: widening its comparison would
    #: newly reject long-standing ungoverned groups on a width difference alone.
    #: An entry is omitted when the expression is not a bare column (a function or CASE
    #: has no single source width to speak of) or the source type declares no parameter.
    property_parameters: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ConformanceSourceFact:
    """One canonically ordered source participating in a conformance group."""

    binding_name: str
    binding_path: str
    source: str
    source_precedence: int
    grain: tuple[tuple[str, str], ...]
    identity_strategy: str
    identity: tuple[tuple[str, str], ...]
    properties: tuple[tuple[str, str], ...]
    provenance_inputs: tuple[ProvenanceInput, ...]


@dataclass(frozen=True, slots=True)
class ConformanceGroupFact:
    """Validated policy and sources for one canonical target class."""

    group: str
    target_class: str
    conflict: str
    union: UnionPolicy
    sources: tuple[ConformanceSourceFact, ...]


@dataclass(frozen=True, slots=True)
class ConformancePlan:
    """Immutable, deterministic multi-source conformance plan."""

    groups: tuple[ConformanceGroupFact, ...] = ()
    provenance_inputs: tuple[ProvenanceInput, ...] = ()


def _source_ref(binding: EntityBinding) -> str:
    if binding.source.relation:
        return f"relation:{binding.source.relation}"
    if binding.source.dbt_model is not None:
        return f"dbt:{binding.source.dbt_model.name}"
    return ""


def _location(binding: EntityBinding, pointer: str = "/conformance") -> SourceLocation:
    return SourceLocation(path=binding.source_path, pointer=pointer)


def _diagnostic(
    binding: EntityBinding,
    code: str,
    message: str,
    pointer: str = "/conformance",
) -> CompileDiagnostic:
    return CompileDiagnostic(
        code=code,
        message=message,
        location=_location(binding, pointer),
        rule_id="DD-133 §3c",
    )


def _binding_key(binding: EntityBinding) -> tuple[str, str, str]:
    return (binding.source_path, binding.name, _source_ref(binding))


def _canonical_inputs(inputs: Iterable[ProvenanceInput]) -> tuple[ProvenanceInput, ...]:
    unique = {(item.name, item.content): item for item in inputs}
    return tuple(unique[key] for key in sorted(unique))


def _validate_contract_shape(
    binding: EntityBinding,
    contract: ConformanceTypeContract,
) -> list[CompileDiagnostic]:
    diagnostics: list[CompileDiagnostic] = []
    expected_properties = sorted(field.property for field in binding.fields)
    actual_properties = sorted(property_ for property_, _ in contract.properties)
    if len(contract.grain) != len(binding.grain.columns):
        diagnostics.append(
            _diagnostic(
                binding,
                "conformance.grain-contract-incomplete",
                "resolved grain types must cover every authored grain column",
                "/grain/columns",
            )
        )
    if len(contract.identity) != len(binding.identity.source_key):
        diagnostics.append(
            _diagnostic(
                binding,
                "conformance.identity-contract-incomplete",
                "resolved identity types must cover every authored source key column",
                "/identity/sourceKey",
            )
        )
    if actual_properties != expected_properties or len(set(actual_properties)) != len(
        actual_properties
    ):
        diagnostics.append(
            _diagnostic(
                binding,
                "conformance.property-contract-incomplete",
                "resolved property types must cover each mapped property exactly once",
                "/fields",
            )
        )
    return diagnostics


_CONFORMANCE_RESOLUTION_HINT = (
    "raw multi-source conformance requires identical grain/identity/property type-kinds "
    "across every binding in the group; if sources are structurally heterogeneous, "
    "normalize them in a contracted dbt intermediate and bind once instead — see "
    "kairos-develop-dbt-transformation/SKILL.md's 'Two reconciliation strategies for "
    "int_merged__<entity>' (issue #286)"
)


def _compare_group_contracts(
    canonical: EntityBinding,
    binding: EntityBinding,
    canonical_contract: ConformanceTypeContract,
    contract: ConformanceTypeContract,
    *,
    governed: bool = False,
) -> list[CompileDiagnostic]:
    diagnostics: list[CompileDiagnostic] = []
    if contract.grain != canonical_contract.grain:
        diagnostics.append(
            _diagnostic(
                binding,
                "conformance.grain-incompatible",
                f"grain/type contract differs from binding '{canonical.name}' — "
                f"{_CONFORMANCE_RESOLUTION_HINT}",
                "/grain/columns",
            )
        )
    if (
        binding.identity.strategy != canonical.identity.strategy
        or contract.identity != canonical_contract.identity
    ):
        diagnostics.append(
            _diagnostic(
                binding,
                "conformance.identity-incompatible",
                f"identity strategy/type contract differs from binding '{canonical.name}' — "
                f"{_CONFORMANCE_RESOLUTION_HINT}",
                "/identity",
            )
        )
    # Bounded type parameters are compared on the properties the two bindings share, and
    # *regardless* of `governed` (issue #681). The union takes its width from its branches,
    # so two branches that genuinely disagree -- varchar(50) against varchar(100) -- have no
    # single width the union can carry, and it would otherwise fall back to an unbounded
    # type: the exact silent widening this check exists to prevent. Scoped to the shared
    # properties because a governed partial source legitimately omits some, and to entries
    # both sides parameterize because an absent parameter means "unknown", not "unbounded".
    canonical_parameters = dict(canonical_contract.property_parameters)
    for prop, label in contract.property_parameters:
        other = canonical_parameters.get(prop)
        if other and label and other != label:
            diagnostics.append(
                _diagnostic(
                    binding,
                    "conformance.type-parameter-incompatible",
                    (
                        f"property '{prop}' resolves to '{label}' here but '{other}' in "
                        f"binding '{canonical.name}'; a conformance union carries one "
                        "width for the column, so reconcile the sources with a contracted "
                        f"dbt model via source.dbtModel — {_CONFORMANCE_RESOLUTION_HINT}"
                    ),
                    "/fields",
                )
            )
    # DD-213: for a contract-governed class the identical-property-set rule is *replaced* by
    # contract conformance -- each binding's properties must be a subset of the contract,
    # every required one covered, and each gap declared under `unmapped:`. Holding peers to
    # each other as well would forbid exactly the case the contract makes safe: a genuinely
    # partial source joining an established group. Grain and identity comparisons stay in
    # force; the contract makes them redundant rather than wrong, so they cost nothing and
    # keep working for ungoverned classes on the same code path.
    if not governed and tuple(sorted(contract.properties)) != tuple(
        sorted(canonical_contract.properties)
    ):
        diagnostics.append(
            _diagnostic(
                binding,
                "conformance.property-incompatible",
                f"property/type contract differs from binding '{canonical.name}' — "
                f"{_CONFORMANCE_RESOLUTION_HINT}",
                "/fields",
            )
        )
    return diagnostics


def build_conformance_plan(
    bindings: Iterable[EntityBinding],
    *,
    type_contracts: Mapping[str, ConformanceTypeContract],
    provenance_inputs: Mapping[str, tuple[ProvenanceInput, ...]],
    governed_classes: frozenset[str] = frozenset(),
) -> ConformancePlan:
    """Validate and canonically plan bindings that share a target class.

    The function is graph-free and write-free. It raises :class:`CompileError` with
    deterministic source-located diagnostics and never attempts v4 coercion.
    """
    ordered = tuple(sorted(bindings, key=_binding_key))
    diagnostics: list[CompileDiagnostic] = []

    for binding in ordered:
        if binding.api_version != "kairos.eu/v5":
            diagnostics.append(
                _diagnostic(
                    binding,
                    "conformance.api-version",
                    "multi-source conformance accepts only kairos.eu/v5 bindings",
                    "/apiVersion",
                )
            )
        if not _source_ref(binding):
            diagnostics.append(
                _diagnostic(
                    binding,
                    "conformance.source-missing",
                    "a conformance binding must reference exactly one source",
                    "/source",
                )
            )

    by_target: dict[str, list[EntityBinding]] = defaultdict(list)
    by_group: dict[str, list[EntityBinding]] = defaultdict(list)
    for binding in ordered:
        by_target[binding.target_class].append(binding)
        if binding.conformance is not None:
            by_group[binding.conformance.group].append(binding)

    for target, members in sorted(by_target.items()):
        if len(members) < 2:
            continue
        groups = {item.conformance.group for item in members if item.conformance is not None}
        for binding in members:
            if binding.conformance is None:
                diagnostics.append(
                    _diagnostic(
                        binding,
                        "conformance.group-required",
                        f"multiple bindings target '{target}'; every binding must declare conformance",
                    )
                )
        if len(groups) != 1:
            for binding in members:
                if binding.conformance is not None:
                    diagnostics.append(
                        _diagnostic(
                            binding,
                            "conformance.group-mismatch",
                            f"bindings targeting '{target}' must declare one identical group",
                            "/conformance/group",
                        )
                    )

    groups_to_plan: list[ConformanceGroupFact] = []
    all_provenance: list[ProvenanceInput] = []
    for group_name, members in sorted(by_group.items()):
        members = sorted(
            members,
            key=lambda item: (
                item.conformance.source_precedence if item.conformance else 0,
                _source_ref(item),
                item.name,
                item.source_path,
            ),
        )
        targets = {item.target_class for item in members}
        if len(targets) != 1:
            for binding in members:
                diagnostics.append(
                    _diagnostic(
                        binding,
                        "conformance.target-mismatch",
                        f"conformance group '{group_name}' spans multiple target classes",
                        "/target/class",
                    )
                )
            continue
        if len(members) < 2:
            diagnostics.append(
                _diagnostic(
                    members[0],
                    "conformance.group-single-source",
                    f"conformance group '{group_name}' must contain at least two sources",
                    "/conformance/group",
                )
            )
            continue

        canonical = members[0]
        canonical_policy = canonical.conformance
        assert canonical_policy is not None
        seen_precedence: dict[int, EntityBinding] = {}
        seen_sources: dict[str, EntityBinding] = {}
        valid_contracts: dict[str, ConformanceTypeContract] = {}

        for binding in members:
            policy = binding.conformance
            assert policy is not None
            source = _source_ref(binding)
            if source in seen_sources:
                diagnostics.append(
                    _diagnostic(
                        binding,
                        "conformance.source-duplicate",
                        f"source '{source}' already has binding '{seen_sources[source].name}'",
                        "/source",
                    )
                )
            else:
                seen_sources[source] = binding
            if policy.source_precedence in seen_precedence:
                diagnostics.append(
                    _diagnostic(
                        binding,
                        "conformance.precedence-duplicate",
                        f"sourcePrecedence {policy.source_precedence} is already used by "
                        f"binding '{seen_precedence[policy.source_precedence].name}'",
                        "/conformance/sourcePrecedence",
                    )
                )
            else:
                seen_precedence[policy.source_precedence] = binding
            if policy.conflict != canonical_policy.conflict:
                diagnostics.append(
                    _diagnostic(
                        binding,
                        "conformance.conflict-incompatible",
                        f"conflict action differs from binding '{canonical.name}'",
                        "/conformance/conflict",
                    )
                )
            if policy.union != canonical_policy.union:
                diagnostics.append(
                    _diagnostic(
                        binding,
                        "conformance.union-incompatible",
                        f"union/deduplication policy differs from binding '{canonical.name}'",
                        "/conformance/union",
                    )
                )
            if (binding.load.mode, binding.load.scd) != (
                canonical.load.mode,
                canonical.load.scd,
            ):
                diagnostics.append(
                    _diagnostic(
                        binding,
                        "conformance.load-incompatible",
                        f"load mode/SCD differs from binding '{canonical.name}'",
                        "/load",
                    )
                )
            relationship_shape = tuple(
                (
                    item.property,
                    item.target,
                    item.cardinality,
                    item.mode,
                    item.missing_parent,
                    item.ambiguous_parent,
                    item.external_reference,
                )
                for item in binding.relationships
            )
            canonical_relationship_shape = tuple(
                (
                    item.property,
                    item.target,
                    item.cardinality,
                    item.mode,
                    item.missing_parent,
                    item.ambiguous_parent,
                    item.external_reference,
                )
                for item in canonical.relationships
            )
            if relationship_shape != canonical_relationship_shape:
                diagnostics.append(
                    _diagnostic(
                        binding,
                        "conformance.relationship-incompatible",
                        f"relationship contract differs from binding '{canonical.name}'",
                        "/relationships",
                    )
                )
            if policy.union.mode == "deduplicate":
                valid_dedup_keys = {
                    binding.identity.source_key,
                    binding.identity.business_key,
                }
                if policy.union.deduplicate_by not in valid_dedup_keys:
                    diagnostics.append(
                        _diagnostic(
                            binding,
                            "conformance.dedup-identity-incompatible",
                            "deduplicateBy must equal the sourceKey or non-empty businessKey",
                            "/conformance/union/deduplicateBy",
                        )
                    )
            contract = type_contracts.get(binding.name)
            if contract is None:
                diagnostics.append(
                    _diagnostic(
                        binding,
                        "conformance.type-contract-missing",
                        "resolved grain, identity, and property types are required",
                        "/conformance",
                    )
                )
            else:
                valid_contracts[binding.name] = contract
                diagnostics.extend(_validate_contract_shape(binding, contract))
            if not provenance_inputs.get(binding.name):
                diagnostics.append(
                    _diagnostic(
                        binding,
                        "conformance.provenance-missing",
                        "at least one content-addressed provenance input is required",
                        "/source",
                    )
                )

        canonical_contract = valid_contracts.get(canonical.name)
        if canonical_contract is not None:
            for binding in members[1:]:
                contract = valid_contracts.get(binding.name)
                if contract is not None:
                    diagnostics.extend(
                        _compare_group_contracts(
                            canonical,
                            binding,
                            canonical_contract,
                            contract,
                            governed=canonical.target_class in governed_classes,
                        )
                    )

        member_paths = {member.source_path for member in members}
        if not any(item.location.path in member_paths for item in diagnostics):
            source_facts = tuple(
                ConformanceSourceFact(
                    binding_name=binding.name,
                    binding_path=binding.source_path,
                    source=_source_ref(binding),
                    source_precedence=binding.conformance.source_precedence,
                    grain=tuple(zip(binding.grain.columns, valid_contracts[binding.name].grain)),
                    identity_strategy=binding.identity.strategy,
                    identity=tuple(
                        zip(
                            binding.identity.source_key,
                            valid_contracts[binding.name].identity,
                        )
                    ),
                    properties=tuple(sorted(valid_contracts[binding.name].properties)),
                    provenance_inputs=_canonical_inputs(provenance_inputs[binding.name]),
                )
                for binding in members
            )
            group_provenance = [
                item for source in source_facts for item in source.provenance_inputs
            ]
            all_provenance.extend(group_provenance)
            groups_to_plan.append(
                ConformanceGroupFact(
                    group=group_name,
                    target_class=canonical.target_class,
                    conflict=canonical_policy.conflict,
                    union=canonical_policy.union,
                    sources=source_facts,
                )
            )

    if diagnostics:
        raise CompileError(diagnostics)
    return ConformancePlan(
        groups=tuple(sorted(groups_to_plan, key=lambda item: (item.target_class, item.group))),
        provenance_inputs=_canonical_inputs(all_provenance),
    )
