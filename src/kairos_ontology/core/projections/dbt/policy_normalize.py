# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Pure DD-106--DD-115 effective-policy normalization and validation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import TypeVar

from ..uri_utils import camel_to_snake
from .diagnostics import (
    Diagnostic,
    DiagnosticCollector,
    EvaluationResult,
    EvaluationStatus,
    ExecutionMode,
    Prerequisite,
)
from .policy_specs import (
    AdapterCapability,
    AdapterEvidenceSpec,
    AdapterEvidenceStatus,
    AdapterName,
    AdapterSupportFact,
    ApprovedDeviationSpec,
    AuditPolicySpec,
    AuthoredValuesFact,
    BackfillAction,
    BridgeCardinality,
    BranchDeleteAction,
    BranchLateArrivalAction,
    BranchRelationship,
    BusinessIdentityPolicy,
    CalendarFact,
    CalendarProfileSpec,
    CanonicalHashPolicySpec,
    CanonicalTypeKind,
    CanonicalTypeSpec,
    CapabilityRequirementSpec,
    ChangeDetectionStrategy,
    CollisionAction,
    ConflictAction,
    ContributionLineageRelationSpec,
    ContributionLineageSpec,
    CorrectionAction,
    CdcOperation,
    CdcOrderingSpec,
    DataQualityRuleFact,
    DataQualityRuleSpec,
    DeleteAction,
    DimensionExposure,
    DimensionVersionBinding,
    DqAction,
    DqCategory,
    DqCheckKind,
    DqExpressionSpec,
    DqParameterSpec,
    DqResultStatus,
    DqRuntimeFieldSpec,
    DqRuntimeResultContractSpec,
    DqSeverity,
    DqToleranceKind,
    DqToleranceSpec,
    DrivingSourceMode,
    DrivingSourceSpec,
    EffectiveValue,
    EntityIdentityFact,
    EntityIdentitySpec,
    EntityIriMode,
    ExactEquivalenceSpec,
    FactType,
    GoldProductFact,
    GoldProductProfileRegistry,
    GoldProductProfileSpec,
    GoldProductSpec,
    GoldProfileName,
    GoldTablePolicyFact,
    GoldTablePolicySpec,
    GoldTableRole,
    HistorySpec,
    IdentityRoleSpec,
    IdentityStrategy,
    IncrementalPolicyFact,
    IncrementalPolicySpec,
    IntegrationIdentityPolicy,
    IntervalBoundary,
    IriPolicy,
    KeyScope,
    LateArrivalAction,
    LineageSpec,
    LookbackUnit,
    LookbackWindowSpec,
    LookupCardinality,
    MasteredIdentityPolicy,
    MeasureDependencySpec,
    MeasureFact,
    MeasureLifecycle,
    MeasureSpec,
    MedallionPolicyFacts,
    MedallionPolicySpec,
    MdmRoutingSpec,
    MultiSourcePolicyFact,
    MultiSourcePolicySpec,
    NamingConvention,
    NormalizationSpec,
    ParentAction,
    PerspectiveSpec,
    PolicyIssue,
    PolicyProvenance,
    PolicySource,
    QuarantineEffectSpec,
    ReplayAction,
    SchemaEvolutionAction,
    SchemaEvolutionSpec,
    Scd2TimeBasis,
    ScdType,
    SecurityFact,
    SecurityPolicySpec,
    SilverColumnAuthoritySpec,
    SilverColumnRole,
    SilverModelAuthoritySpec,
    SilverRuntimeAuthoritySpec,
    SourceIdentityPolicy,
    SourcePrecedenceMode,
    SourcePrecedenceSpec,
    SurrogateIdentityPolicy,
    TemporalMode,
    TemporalRelationshipFact,
    TemporalRelationshipSpec,
    TimestampOrigin,
    TimestampRole,
    TimestampSemanticSpec,
    TimestampSourceSpec,
)
from .mapping_specs import SourceMappings
from .specs import (
    BoundSilverModel,
    ColumnSpec,
    ContractFact,
    ForeignKeyPolicy,
    ModelOutcome,
    SilverModelKind,
    SourceSystemFact,
)

E = TypeVar("E", bound=Enum)
_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NULL_EXPRESSION = re.compile(r"^\s*cast\s*\(\s*null\b", re.I)
_DECIMAL = re.compile(r"^(?:decimal|numeric)\((\d+),\s*(\d+)\)$", re.I)
_SIZED_TEXT = re.compile(r"^(?:var)?(?:n)?char\((\d+)\)$", re.I)
_LOOKBACK = re.compile(r"^([1-9][0-9]*)\s+(hours|days)$", re.I)
_DECLARED_SOURCE_TYPE = re.compile(
    r"^\s*([a-zA-Z0-9_]+)\s*(?:\(\s*([0-9]+|max)\s*(?:,\s*([0-9]+)\s*)?\))?\s*$",
    re.I,
)
_XSD_TYPE_KINDS = {
    "http://www.w3.org/2001/XMLSchema#anyURI": CanonicalTypeKind.STRING,
    "http://www.w3.org/2001/XMLSchema#boolean": CanonicalTypeKind.BOOLEAN,
    "http://www.w3.org/2001/XMLSchema#date": CanonicalTypeKind.DATE,
    "http://www.w3.org/2001/XMLSchema#dateTime": CanonicalTypeKind.TIMESTAMP,
    "http://www.w3.org/2001/XMLSchema#decimal": CanonicalTypeKind.DECIMAL,
    "http://www.w3.org/2001/XMLSchema#double": CanonicalTypeKind.FLOAT64,
    "http://www.w3.org/2001/XMLSchema#float": CanonicalTypeKind.FLOAT64,
    "http://www.w3.org/2001/XMLSchema#int": CanonicalTypeKind.INT32,
    "http://www.w3.org/2001/XMLSchema#integer": CanonicalTypeKind.INT64,
    "http://www.w3.org/2001/XMLSchema#long": CanonicalTypeKind.INT64,
    "http://www.w3.org/2001/XMLSchema#normalizedString": CanonicalTypeKind.STRING,
    "http://www.w3.org/2001/XMLSchema#short": CanonicalTypeKind.INT16,
    "http://www.w3.org/2001/XMLSchema#string": CanonicalTypeKind.STRING,
    "http://www.w3.org/2001/XMLSchema#time": CanonicalTypeKind.TIME,
    "http://www.w3.org/2001/XMLSchema#token": CanonicalTypeKind.STRING,
}

_CANONICAL_KIND_ALIASES = {kind.value: kind for kind in CanonicalTypeKind}


class PolicyNormalizationError(ValueError):
    """An actionable, deterministic authored-policy failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        rule_id: str,
        resource_uri: str = "",
        predicate_uri: str = "",
    ) -> None:
        self.code = code
        self.rule_id = rule_id
        self.resource_uri = resource_uri
        self.predicate_uri = predicate_uri
        stage = (
            "preparation"
            if code.startswith("prep.")
            else (
                "identity"
                if code.startswith(("identity.", "lineage."))
                else (
                    "runtime"
                    if code.startswith(("incremental.", "runtime.", "hash."))
                    else (
                        "temporal_fk"
                        if code.startswith(("temporal.", "fk.", "foreign-key."))
                        else (
                            "adapter"
                            if code.startswith(("adapter.", "capability."))
                            else (
                                "quality"
                                if code.startswith(("dq.", "quality."))
                                else "gold" if code.startswith("gold.") else "normalization"
                            )
                        )
                    )
                )
            )
        )
        owner_skill = {
            "preparation": "kairos-design-source",
            "identity": "kairos-design-silver",
            "runtime": "kairos-design-silver",
            "temporal_fk": "kairos-design-silver",
            "adapter": "kairos-execute-validate",
            "quality": "kairos-design-silver",
            "gold": "kairos-design-gold",
        }.get(stage, "kairos-execute-validate")
        self.diagnostic = Diagnostic(
            code=code,
            message=message,
            rule_id=rule_id,
            resource_uri=resource_uri,
            predicate_uri=predicate_uri,
            stage=stage,
            owner_skill=owner_skill,
            evidence=tuple(
                item
                for item in (
                    f"resource:{resource_uri}" if resource_uri else "",
                    f"predicate:{predicate_uri}" if predicate_uri else "",
                    f"rule:{rule_id}",
                )
                if item
            ),
            remediation=f"Resolve {code} with {owner_skill}.",
        )
        location = resource_uri or "<project>"
        predicate = f" ({predicate_uri})" if predicate_uri else ""
        super().__init__(f"{code}: {message} at {location}{predicate} [{rule_id}]")


@dataclass(frozen=True, slots=True)
class PolicyNormalizationStages:
    """Partial stage results produced by preparation/identity collection."""

    preparation: EvaluationResult[tuple[object, ...]]
    identity: EvaluationResult[tuple[EntityIdentitySpec, ...]]
    runtime: EvaluationResult[object]
    foreign_keys: EvaluationResult[object]
    mapping: EvaluationResult[object] = field(
        default_factory=lambda: EvaluationResult(status=EvaluationStatus.PASSED)
    )
    adapter: EvaluationResult[object] = field(
        default_factory=lambda: EvaluationResult(status=EvaluationStatus.PASSED)
    )
    quality: EvaluationResult[object] = field(
        default_factory=lambda: EvaluationResult(status=EvaluationStatus.PASSED)
    )
    gold: EvaluationResult[object] = field(
        default_factory=lambda: EvaluationResult(status=EvaluationStatus.PASSED)
    )

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return tuple(
            sorted(
                (
                    *self.preparation.diagnostics,
                    *self.identity.diagnostics,
                    *self.runtime.diagnostics,
                    *self.foreign_keys.diagnostics,
                    *self.mapping.diagnostics,
                    *self.adapter.diagnostics,
                    *self.quality.diagnostics,
                    *self.gold.diagnostics,
                ),
                key=lambda item: item.sort_key,
            )
        )


class PolicyCollectionError(ValueError):
    """Collected preparation/identity blockers with typed stage availability."""

    def __init__(
        self,
        stages: PolicyNormalizationStages,
        partial_value: MedallionPolicySpec | None = None,
    ) -> None:
        self.stages = stages
        self.partial_value = partial_value
        self.diagnostics = stages.diagnostics
        first = self.diagnostics[0]
        self.code = first.code
        self.rule_id = first.rule_id
        self.resource_uri = first.resource_uri
        self.predicate_uri = first.predicate_uri
        location = first.resource_uri or "<project>"
        predicate = f" ({first.predicate_uri})" if first.predicate_uri else ""
        super().__init__(
            f"{first.code}: {first.message} at {location}{predicate} [{first.rule_id}]"
        )


def _error(
    code: str,
    message: str,
    fact: AuthoredValuesFact | None,
    rule_id: str,
    *,
    resource_uri: str = "",
) -> PolicyNormalizationError:
    return PolicyNormalizationError(
        code,
        message,
        rule_id=rule_id,
        resource_uri=fact.resource_uri if fact is not None else resource_uri,
        predicate_uri=fact.predicate_uri if fact is not None else "",
    )


def _single(
    fact: AuthoredValuesFact | None,
    label: str,
    rule_id: str,
) -> str:
    if fact is None or not fact.values:
        raise _error(
            "policy.missing-value",
            f"{label} is required",
            fact,
            rule_id,
        )
    if len(fact.values) != 1:
        raise _error(
            "policy.contradictory-values",
            f"{label} must have exactly one value; found {fact.values!r}",
            fact,
            rule_id,
        )
    value = fact.values[0].strip()
    if not value:
        raise _error(
            "policy.empty-value",
            f"{label} cannot be empty",
            fact,
            rule_id,
        )
    return value


def _optional_single(
    fact: AuthoredValuesFact | None,
    label: str,
    rule_id: str,
) -> str | None:
    if fact is None:
        return None
    return _single(fact, label, rule_id)


def _many(
    fact: AuthoredValuesFact | None,
    label: str,
    rule_id: str,
    *,
    required: bool = True,
    split_commas: bool = False,
) -> tuple[str, ...]:
    if fact is None or not fact.values:
        if required:
            raise _error("policy.missing-value", f"{label} is required", fact, rule_id)
        return ()
    values: list[str] = []
    for raw in fact.values:
        candidates = raw.split(",") if split_commas else (raw,)
        values.extend(item.strip() for item in candidates if item.strip())
    result = tuple(dict.fromkeys(values))
    if required and not result:
        raise _error("policy.empty-value", f"{label} cannot be empty", fact, rule_id)
    return result


def _provenance(
    fact: AuthoredValuesFact,
    rule_id: str,
    *,
    source: PolicySource = PolicySource.AUTHORED,
    evidence: tuple[str, ...] = (),
) -> PolicyProvenance:
    return PolicyProvenance(
        source=source,
        rule_id=rule_id,
        resource_uri=fact.resource_uri,
        predicate_uri=fact.predicate_uri,
        evidence=evidence,
    )


def _effective(
    value: object,
    fact: AuthoredValuesFact,
    rule_id: str,
    *,
    source: PolicySource = PolicySource.AUTHORED,
    evidence: tuple[str, ...] = (),
) -> EffectiveValue:
    return EffectiveValue(value, _provenance(fact, rule_id, source=source, evidence=evidence))


def _default(value: object, rule_id: str, evidence: str) -> EffectiveValue:
    return EffectiveValue(
        value,
        PolicyProvenance(
            source=PolicySource.DEFAULT,
            rule_id=rule_id,
            evidence=(evidence,),
        ),
    )


def _enum(
    fact: AuthoredValuesFact,
    enum_type: type[E],
    label: str,
    rule_id: str,
) -> EffectiveValue[E]:
    raw = _single(fact, label, rule_id)
    try:
        value = enum_type(raw)
    except ValueError as exc:
        supported = ", ".join(item.value for item in enum_type)
        raise _error(
            "policy.unsupported-value",
            f"unsupported {label} {raw!r}; expected one of: {supported}",
            fact,
            rule_id,
        ) from exc
    return _effective(value, fact, rule_id)


def _bool(fact: AuthoredValuesFact, label: str, rule_id: str) -> EffectiveValue[bool]:
    raw = _single(fact, label, rule_id).lower()
    if raw not in {"true", "false"}:
        raise _error(
            "policy.unsupported-value",
            f"{label} must be the boolean true or false, not {raw!r}",
            fact,
            rule_id,
        )
    return _effective(raw == "true", fact, rule_id)


def _text(
    fact: AuthoredValuesFact,
    label: str,
    rule_id: str,
    *,
    source: PolicySource = PolicySource.AUTHORED,
) -> EffectiveValue[str]:
    return _effective(_single(fact, label, rule_id), fact, rule_id, source=source)


def _texts(
    fact: AuthoredValuesFact | None,
    label: str,
    rule_id: str,
    *,
    required: bool = True,
    split_commas: bool = False,
) -> EffectiveValue[tuple[str, ...]]:
    if fact is None:
        if required:
            raise _error("policy.missing-value", f"{label} is required", fact, rule_id)
        return _default((), rule_id, f"No {label} was authored.")
    return _effective(
        _many(
            fact,
            label,
            rule_id,
            required=required,
            split_commas=split_commas,
        ),
        fact,
        rule_id,
    )


def _canonical_type(fact: AuthoredValuesFact, rule_id: str) -> EffectiveValue[CanonicalTypeSpec]:
    raw = _single(fact, "canonical target type", rule_id).strip().lower()
    decimal = _DECIMAL.fullmatch(raw)
    if decimal:
        precision, scale = (int(value) for value in decimal.groups())
        if precision < 1 or precision > 38 or scale < 0 or scale > precision:
            raise _error(
                "prep.invalid-decimal",
                f"decimal precision/scale is invalid: {raw!r}",
                fact,
                rule_id,
            )
        value = CanonicalTypeSpec(
            CanonicalTypeKind.DECIMAL,
            precision=precision,
            scale=scale,
        )
        return _effective(value, fact, rule_id)

    text = _SIZED_TEXT.fullmatch(raw)
    if text:
        length = int(text.group(1))
        if length < 1:
            raise _error(
                "prep.invalid-string-length",
                f"string length must be positive: {raw!r}",
                fact,
                rule_id,
            )
        return _effective(
            CanonicalTypeSpec(CanonicalTypeKind.STRING, length=length),
            fact,
            rule_id,
        )

    aliases = {
        "string": CanonicalTypeKind.STRING,
        "varchar": CanonicalTypeKind.STRING,
        "nvarchar": CanonicalTypeKind.STRING,
        "boolean": CanonicalTypeKind.BOOLEAN,
        "bool": CanonicalTypeKind.BOOLEAN,
        "bit": CanonicalTypeKind.BOOLEAN,
        "smallint": CanonicalTypeKind.INT16,
        "int16": CanonicalTypeKind.INT16,
        "int": CanonicalTypeKind.INT32,
        "integer": CanonicalTypeKind.INT32,
        "int32": CanonicalTypeKind.INT32,
        "bigint": CanonicalTypeKind.INT64,
        "int64": CanonicalTypeKind.INT64,
        "float": CanonicalTypeKind.FLOAT64,
        "double": CanonicalTypeKind.FLOAT64,
        "float64": CanonicalTypeKind.FLOAT64,
        "date": CanonicalTypeKind.DATE,
        "time": CanonicalTypeKind.TIME,
        "timestamp": CanonicalTypeKind.TIMESTAMP,
        "datetime": CanonicalTypeKind.TIMESTAMP,
        "datetime2": CanonicalTypeKind.TIMESTAMP,
        "binary": CanonicalTypeKind.BINARY,
        "varbinary": CanonicalTypeKind.BINARY,
        "json": CanonicalTypeKind.JSON,
        "variant": CanonicalTypeKind.JSON,
    }
    kind = aliases.get(raw)
    if kind is None:
        supported = ", ".join(item.value for item in CanonicalTypeKind)
        raise _error(
            "prep.unsupported-type",
            f"unsupported canonical type {raw!r}; expected one of: {supported}",
            fact,
            rule_id,
        )
    return _effective(CanonicalTypeSpec(kind), fact, rule_id)


def _safe_identifier(fact: AuthoredValuesFact, label: str, rule_id: str) -> EffectiveValue[str]:
    value = _single(fact, label, rule_id)
    if not _SAFE_NAME.fullmatch(value):
        raise _error(
            "prep.unsafe-identifier",
            f"{label} {value!r} is not a portable unquoted identifier",
            fact,
            rule_id,
        )
    return _effective(value, fact, rule_id)


def _source_type(value: str) -> CanonicalTypeSpec | None:
    match = _DECLARED_SOURCE_TYPE.fullmatch(value)
    if match is None:
        return None
    base, first, second = match.groups()
    aliases = {
        "bigint": CanonicalTypeKind.INT64,
        "binary": CanonicalTypeKind.BINARY,
        "bit": CanonicalTypeKind.BOOLEAN,
        "bool": CanonicalTypeKind.BOOLEAN,
        "boolean": CanonicalTypeKind.BOOLEAN,
        "char": CanonicalTypeKind.STRING,
        "date": CanonicalTypeKind.DATE,
        "datetime": CanonicalTypeKind.TIMESTAMP,
        "datetime2": CanonicalTypeKind.TIMESTAMP,
        "decimal": CanonicalTypeKind.DECIMAL,
        "double": CanonicalTypeKind.FLOAT64,
        "float": CanonicalTypeKind.FLOAT64,
        "image": CanonicalTypeKind.BINARY,
        "int": CanonicalTypeKind.INT32,
        "integer": CanonicalTypeKind.INT32,
        "json": CanonicalTypeKind.JSON,
        "money": CanonicalTypeKind.DECIMAL,
        "nchar": CanonicalTypeKind.STRING,
        "ntext": CanonicalTypeKind.STRING,
        "numeric": CanonicalTypeKind.DECIMAL,
        "nvarchar": CanonicalTypeKind.STRING,
        "real": CanonicalTypeKind.FLOAT64,
        "smallint": CanonicalTypeKind.INT16,
        "string": CanonicalTypeKind.STRING,
        "text": CanonicalTypeKind.STRING,
        "time": CanonicalTypeKind.TIME,
        "timestamp": CanonicalTypeKind.TIMESTAMP,
        "tinyint": CanonicalTypeKind.INT16,
        "uniqueidentifier": CanonicalTypeKind.STRING,
        "varbinary": CanonicalTypeKind.BINARY,
        "varchar": CanonicalTypeKind.STRING,
        "variant": CanonicalTypeKind.JSON,
        "xml": CanonicalTypeKind.STRING,
    }
    kind = aliases.get(base.lower())
    if kind is None:
        return None
    if kind is CanonicalTypeKind.DECIMAL:
        return CanonicalTypeSpec(
            kind,
            precision=int(first) if first and first.lower() != "max" else 18,
            scale=int(second) if second is not None else 4,
        )
    if kind is CanonicalTypeKind.STRING and first and first.lower() != "max":
        return CanonicalTypeSpec(kind, length=int(first))
    return CanonicalTypeSpec(kind)


def _target_type(value: str) -> CanonicalTypeSpec | None:
    if not value:
        return None
    if value in _XSD_TYPE_KINDS:
        return CanonicalTypeSpec(_XSD_TYPE_KINDS[value])
    kind = _CANONICAL_KIND_ALIASES.get(value.strip().lower())
    if kind is not None:
        return CanonicalTypeSpec(kind)
    return _source_type(value)


def _types_compatible(source: CanonicalTypeSpec, target: CanonicalTypeSpec) -> bool:
    if source.kind is not target.kind:
        return False
    if source.kind is CanonicalTypeKind.DECIMAL:
        source_precision = source.precision or 18
        source_scale = source.scale or 0
        target_precision = target.precision or source_precision
        target_scale = target.scale if target.scale is not None else source_scale
        return target_precision >= source_precision and target_scale >= source_scale
    if source.kind is CanonicalTypeKind.STRING and target.length:
        return source.length is not None and source.length <= target.length
    return True


def _normalize_multi_source(
    facts: tuple[MultiSourcePolicyFact, ...],
) -> tuple[MultiSourcePolicySpec, ...]:
    result: list[MultiSourcePolicySpec] = []
    for fact in facts:
        relationship = _enum(
            fact.branch_relationship,
            BranchRelationship,
            "multi-source branch relationship",
            "DD-108-multi-source",
        )
        precedence_raw = _single(
            fact.source_precedence,
            "source precedence",
            "DD-108-precedence",
        )
        try:
            precedence_mode = SourcePrecedenceMode(precedence_raw)
            ordered_sources: tuple[str, ...] = ()
        except ValueError:
            prefix = "declared-order:"
            if not precedence_raw.startswith(prefix):
                raise _error(
                    "multi-source.unsupported-precedence",
                    (
                        "source precedence must be not-applicable-disjoint, "
                        "none-without-approved-exact-equivalence, or declared-order:a,b"
                    ),
                    fact.source_precedence,
                    "DD-108-precedence",
                )
            ordered_sources = tuple(
                value.strip()
                for value in precedence_raw.removeprefix(prefix).split(",")
                if value.strip()
            )
            if not ordered_sources:
                raise _error(
                    "multi-source.empty-precedence",
                    "declared-order requires at least one source",
                    fact.source_precedence,
                    "DD-108-precedence",
                )
            if len(set(ordered_sources)) != len(ordered_sources):
                raise _error(
                    "multi-source.duplicate-precedence-source",
                    "declared-order source references must be unique",
                    fact.source_precedence,
                    "DD-108-precedence",
                )
            precedence_mode = SourcePrecedenceMode.DECLARED_ORDER

        if (
            relationship.value is BranchRelationship.DISJOINT
            and precedence_mode is not SourcePrecedenceMode.NOT_APPLICABLE_DISJOINT
        ):
            raise _error(
                "multi-source.disjoint-precedence",
                "disjoint branches require not-applicable-disjoint precedence",
                fact.source_precedence,
                "DD-108-precedence",
            )
        if (
            relationship.value is not BranchRelationship.DISJOINT
            and precedence_mode is SourcePrecedenceMode.NOT_APPLICABLE_DISJOINT
        ):
            raise _error(
                "multi-source.overlap-precedence",
                "overlapping/equivalent branches cannot use disjoint precedence",
                fact.source_precedence,
                "DD-108-precedence",
            )
        if (
            relationship.value is BranchRelationship.OVERLAPPING
            and precedence_mode is not SourcePrecedenceMode.NONE_WITHOUT_EXACT_EQUIVALENCE
        ):
            raise _error(
                "multi-source.overlap-precedence",
                (
                    "overlapping branches must retain branch identity and use "
                    "none-without-approved-exact-equivalence precedence"
                ),
                fact.source_precedence,
                "DD-108-precedence",
            )
        if (
            relationship.value is BranchRelationship.EXACTLY_EQUIVALENT
            and precedence_mode is not SourcePrecedenceMode.DECLARED_ORDER
        ):
            raise _error(
                "multi-source.exact-precedence-missing",
                "exactly-equivalent branches require declared-order:<source,...>",
                fact.source_precedence,
                "DD-108-precedence",
            )

        tests = _texts(
            fact.reconciliation_tests,
            "multi-source reconciliation tests",
            "DD-108-reconciliation",
        )
        conflict = _enum(
            fact.conflict,
            ConflictAction,
            "attribute conflict policy",
            "DD-108-conflict",
        )
        collision = _enum(
            fact.collision,
            CollisionAction,
            "key collision policy",
            "DD-108-collision",
        )
        if (
            relationship.value is BranchRelationship.EXACTLY_EQUIVALENT
            and conflict.value is ConflictAction.RETAIN_BRANCH_VALUES
        ):
            raise _error(
                "multi-source.exact-conflict-retains-branches",
                (
                    "exactly-equivalent conformance cannot retain conflicting branch "
                    "values; use block or quarantine"
                ),
                fact.conflict,
                "DD-108-conflict",
            )
        if (
            relationship.value is BranchRelationship.EXACTLY_EQUIVALENT
            and collision.value is CollisionAction.RETAIN_SOURCE_SCOPED_IDENTITIES
        ):
            raise _error(
                "multi-source.exact-collision-retains-branches",
                (
                    "exactly-equivalent conformance cannot retain colliding source-scoped "
                    "identities; use block or quarantine"
                ),
                fact.collision,
                "DD-108-collision",
            )
        result.append(
            MultiSourcePolicySpec(
                resource_uri=fact.resource_uri,
                relationship=relationship,
                exact_equivalence=ExactEquivalenceSpec(
                    approved=relationship.value is BranchRelationship.EXACTLY_EQUIVALENT,
                    rule_refs=(
                        tests
                        if relationship.value is BranchRelationship.EXACTLY_EQUIVALENT
                        else _default(
                            (),
                            "DD-108-exact-equivalence",
                            "No row-level exact equivalence is approved.",
                        )
                    ),
                ),
                precedence=SourcePrecedenceSpec(
                    mode=_effective(
                        precedence_mode,
                        fact.source_precedence,
                        "DD-108-precedence",
                    ),
                    ordered_sources=_effective(
                        ordered_sources,
                        fact.source_precedence,
                        "DD-108-precedence",
                    ),
                ),
                normalization=NormalizationSpec(
                    _text(
                        fact.normalization,
                        "multi-source normalization policy",
                        "DD-108-normalization",
                    )
                ),
                conflict=conflict,
                collision=collision,
                deletion=_enum(
                    fact.deletion,
                    BranchDeleteAction,
                    "branch deletion policy",
                    "DD-108-delete",
                ),
                late_arrival=_enum(
                    fact.late_arrival,
                    BranchLateArrivalAction,
                    "branch late-arrival policy",
                    "DD-108-late-arrival",
                ),
                reconciliation_tests=tests,
            )
        )
    return tuple(result)


def _normalize_incremental(
    facts: tuple[IncrementalPolicyFact, ...],
) -> tuple[IncrementalPolicySpec, ...]:
    result: list[IncrementalPolicySpec] = []
    seen_resources: set[str] = set()
    for fact in facts:
        if fact.resource_uri in seen_resources:
            raise PolicyNormalizationError(
                "incremental.duplicate-policy",
                "an incremental policy resource may be declared only once",
                rule_id="DD-109-incremental",
                resource_uri=fact.resource_uri,
            )
        seen_resources.add(fact.resource_uri)
        merge_identity = _texts(
            fact.merge_identity,
            "merge identity",
            "DD-109-merge",
            split_commas=True,
        )
        total_order = _texts(
            fact.total_order,
            "total-order tie breakers",
            "DD-109-total-order",
            split_commas=True,
        )
        if not total_order.value:
            raise _error(
                "incremental.incomplete-order",
                "incremental execution requires a complete total-order tie breaker",
                fact.total_order,
                "DD-109-total-order",
            )
        if len(set(total_order.value)) != len(total_order.value):
            raise _error(
                "incremental.duplicate-order-term",
                "total-order tie breakers must be unique and ordered",
                fact.total_order,
                "DD-109-total-order",
            )
        cdc_operation = _text(
            fact.cdc_operation,
            "normalized CDC operation",
            "DD-109-cdc",
        )
        source_updated_at = _text(
            fact.source_updated_at,
            "source update timestamp",
            "DD-109-time",
        )
        source_effective_at = _text(
            fact.source_effective_at,
            "source effective timestamp",
            "DD-109-time",
        )
        ingested_at = _text(
            fact.ingested_at,
            "ingestion timestamp",
            "DD-109-time",
        )
        runtime_fields = (
            cdc_operation.value,
            source_updated_at.value,
            source_effective_at.value,
            ingested_at.value,
        )
        if len(set(runtime_fields)) != len(runtime_fields):
            raise PolicyNormalizationError(
                "incremental.ambiguous-runtime-fields",
                "CDC operation, source-update, source-effective, and ingestion fields "
                "must be distinct",
                rule_id="DD-109-time",
                resource_uri=fact.resource_uri,
            )
        lookback_text = _text(
            fact.lookback,
            "incremental lookback",
            "DD-109-lookback",
        )
        lookback_match = _LOOKBACK.fullmatch(lookback_text.value.strip())
        if lookback_match is None:
            raise _error(
                "incremental.invalid-lookback",
                "lookbackWindow must be a positive integer followed by hours or days",
                fact.lookback,
                "DD-109-lookback",
            )
        lookback = EffectiveValue(
            LookbackWindowSpec(
                amount=int(lookback_match.group(1)),
                unit=LookbackUnit(lookback_match.group(2).lower()),
            ),
            lookback_text.provenance,
        )
        result.append(
            IncrementalPolicySpec(
                resource_uri=fact.resource_uri,
                merge_identity=merge_identity,
                cdc_operation=cdc_operation,
                supported_operations=_default(
                    (
                        CdcOperation.INSERT,
                        CdcOperation.UPDATE,
                        CdcOperation.DELETE,
                        CdcOperation.SOFT_DELETE,
                        CdcOperation.SNAPSHOT,
                    ),
                    "DD-109-cdc",
                    "Medallion policy v1 normalized CDC operation set.",
                ),
                ordering=CdcOrderingSpec(
                    source_updated_at=source_updated_at,
                    source_effective_at=source_effective_at,
                    ingested_at=ingested_at,
                    tie_breakers=total_order,
                ),
                lookback=lookback,
                hard_delete=_enum(
                    fact.hard_delete,
                    DeleteAction,
                    "hard-delete policy",
                    "DD-109-delete",
                ),
                soft_delete=_enum(
                    fact.soft_delete,
                    DeleteAction,
                    "soft-delete policy",
                    "DD-109-delete",
                ),
                late_arrival=_enum(
                    fact.late_arrival,
                    LateArrivalAction,
                    "late-arrival policy",
                    "DD-109-late-arrival",
                ),
                correction=_enum(
                    fact.correction,
                    CorrectionAction,
                    "correction policy",
                    "DD-109-correction",
                ),
                replay=_enum(
                    fact.replay,
                    ReplayAction,
                    "replay policy",
                    "DD-109-replay",
                ),
                backfill=_enum(
                    fact.backfill,
                    BackfillAction,
                    "backfill policy",
                    "DD-109-backfill",
                ),
                schema_evolution=SchemaEvolutionSpec(
                    _enum(
                        fact.schema_change,
                        SchemaEvolutionAction,
                        "incremental schema-change policy",
                        "DD-109-schema-change",
                    )
                ),
            )
        )
    return tuple(result)


def _normalize_hashes(facts: tuple) -> tuple[CanonicalHashPolicySpec, ...]:
    result: list[CanonicalHashPolicySpec] = []
    seen_resources: set[str] = set()
    for fact in facts:
        if fact.resource_uri in seen_resources:
            raise PolicyNormalizationError(
                "hash.duplicate-policy",
                "a canonical hash policy resource may be declared only once",
                rule_id="DD-109-hash",
                resource_uri=fact.resource_uri,
            )
        seen_resources.add(fact.resource_uri)
        algorithm = _text(
            fact.algorithm,
            "hash algorithm",
            "DD-109-hash",
        )
        if algorithm.value != "SHA-256":
            raise _error(
                "hash.unsupported-algorithm",
                "Medallion policy v1 requires SHA-256",
                fact.algorithm,
                "DD-109-hash",
            )
        version = _text(
            fact.version,
            "hash contract version",
            "DD-109-hash-version",
        )
        if version.value != "1":
            raise _error(
                "hash.unsupported-version",
                "Medallion policy v1 requires canonical hash contract version 1",
                fact.version,
                "DD-109-hash-version",
            )
        inputs = _texts(
            fact.inputs,
            "ordered hash inputs",
            "DD-109-hash",
        )
        if not fact.inputs.ordered:
            raise _error(
                "hash.unordered-inputs",
                "multiple canonical hash inputs must be authored as one RDF list",
                fact.inputs,
                "DD-109-hash",
            )
        if len(set(inputs.value)) != len(inputs.value):
            raise _error(
                "hash.duplicate-input",
                "canonical hash inputs must be unique and explicitly ordered",
                fact.inputs,
                "DD-109-hash",
            )
        null_representation = _text(
            fact.null_representation,
            "hash null representation",
            "DD-109-hash",
        )
        if null_representation.value != "typed-length-delimited-null":
            raise _error(
                "hash.unsupported-null-representation",
                "canonical hash contract v1 requires typed-length-delimited-null",
                fact.null_representation,
                "DD-109-hash",
            )
        result.append(
            CanonicalHashPolicySpec(
                resource_uri=fact.resource_uri,
                contract_version=version,
                algorithm=algorithm,
                inputs=inputs,
                encoding=_default(
                    "ordered-typed-length-delimited",
                    "DD-109-hash",
                    "Medallion hash codec mandated by policy v1.",
                ),
                null_representation=null_representation,
            )
        )
    return tuple(result)


def _normalize_temporal(
    facts: tuple[TemporalRelationshipFact, ...],
) -> tuple[TemporalRelationshipSpec, ...]:
    result: list[TemporalRelationshipSpec] = []
    for fact in facts:
        mode = _enum(
            fact.mode,
            TemporalMode,
            "temporal FK mode",
            "DD-109-temporal-fk",
        )
        as_of = (
            _text(
                fact.as_of_column,
                "temporal FK as-of column",
                "DD-109-temporal-fk",
            )
            if fact.as_of_column is not None
            else None
        )
        interval = (
            _enum(
                fact.interval,
                IntervalBoundary,
                "temporal FK interval",
                "DD-109-temporal-fk",
            )
            if fact.interval is not None
            else None
        )
        time_zone = (
            _text(
                fact.time_zone,
                "temporal FK time zone",
                "DD-109-temporal-fk",
            )
            if fact.time_zone is not None
            else None
        )
        precision = (
            _text(
                fact.precision,
                "temporal FK precision",
                "DD-109-temporal-fk",
            )
            if fact.precision is not None
            else None
        )
        temporal_details = (as_of, interval, time_zone, precision)
        if mode.value is TemporalMode.AS_OF and not all(temporal_details):
            raise PolicyNormalizationError(
                "temporal-fk.incomplete-as-of",
                "as-of FK requires column, interval, time zone, and precision",
                rule_id="DD-109-temporal-fk",
                resource_uri=fact.property_uri,
            )
        if mode.value is not TemporalMode.AS_OF and any(temporal_details):
            raise PolicyNormalizationError(
                "temporal-fk.contradictory-details",
                "only as-of FK mode may declare interval comparison details",
                rule_id="DD-109-temporal-fk",
                resource_uri=fact.property_uri,
            )
        if mode.value is TemporalMode.AS_OF:
            if interval is None or interval.value is not IntervalBoundary.CLOSED_OPEN:
                raise PolicyNormalizationError(
                    "temporal-fk.non-half-open-interval",
                    "as-of FK lookup requires a closed-open [from, to) interval",
                    rule_id="DD-109-temporal-fk",
                    resource_uri=fact.property_uri,
                )
            if time_zone is None or time_zone.value != "UTC":
                raise PolicyNormalizationError(
                    "temporal-fk.unsupported-time-zone",
                    "as-of FK lookup requires normalized UTC timestamps",
                    rule_id="DD-109-temporal-fk",
                    resource_uri=fact.property_uri,
                )
            if precision is None or precision.value != "microsecond":
                raise PolicyNormalizationError(
                    "temporal-fk.unsupported-precision",
                    "as-of FK lookup requires microsecond timestamp precision",
                    rule_id="DD-109-temporal-fk",
                    resource_uri=fact.property_uri,
                )
        ambiguous = _enum(
            fact.ambiguous_action,
            ParentAction,
            "ambiguous-parent action",
            "DD-109-temporal-fk",
        )
        if ambiguous.value not in {
            ParentAction.FAIL,
            ParentAction.QUARANTINE,
            ParentAction.RETRY,
        }:
            raise _error(
                "temporal-fk.invalid-ambiguous-action",
                "ambiguous parent action must be fail, quarantine, or retry",
                fact.ambiguous_action,
                "DD-109-temporal-fk",
            )
        cardinality = _enum(
            fact.cardinality,
            LookupCardinality,
            "temporal FK cardinality",
            "DD-109-temporal-fk",
        )
        missing = _enum(
            fact.missing_action,
            ParentAction,
            "missing-parent action",
            "DD-109-temporal-fk",
        )
        if fact.change_detection is None:
            raise PolicyNormalizationError(
                "temporal-fk.change-detection-missing",
                "every temporal FK must explicitly declare change-detection participation",
                rule_id="DD-109-temporal-fk",
                resource_uri=fact.property_uri,
            )
        result.append(
            TemporalRelationshipSpec(
                property_uri=fact.property_uri,
                mode=mode,
                as_of_column=as_of,
                interval=interval,
                time_zone=time_zone,
                precision=precision,
                cardinality=cardinality,
                missing_action=missing,
                ambiguous_action=ambiguous,
                late_parent_action=_enum(
                    fact.late_parent_action,
                    ParentAction,
                    "late-parent action",
                    "DD-109-temporal-fk",
                ),
                participates_in_change_detection=_bool(
                    fact.change_detection,
                    "FK change-detection flag",
                    "DD-109-temporal-fk",
                ),
            )
        )
    return tuple(result)


def _timestamp_semantics(
    source_refs: tuple[str, ...] = (),
    incremental: IncrementalPolicySpec | None = None,
    available_columns_by_source: dict[str, frozenset[str]] | None = None,
    contract_cdc_by_source: dict[str, dict[str, str]] | None = None,
) -> tuple[TimestampSemanticSpec, ...]:
    roles = (
        (
            TimestampRole.INGESTED_AT,
            "_ingested_at",
            TimestampOrigin.SOURCE_INGESTION,
            "ingested_at",
        ),
        (
            TimestampRole.SOURCE_UPDATED_AT,
            "_source_updated_at",
            TimestampOrigin.SOURCE_UPDATE,
            "source_updated_at",
        ),
        (
            TimestampRole.SOURCE_EFFECTIVE_AT,
            "_source_effective_at",
            TimestampOrigin.SOURCE_BUSINESS_EFFECTIVE,
            "source_effective_at",
        ),
    )
    values: list[TimestampSemanticSpec] = [
        TimestampSemanticSpec(
            TimestampRole.LOADED_AT,
            "_loaded_at",
            _default(
                TimestampOrigin.INJECTED_RUN_CLOCK,
                "DD-109-run-clock",
                "One injected run clock supplies load metadata.",
            ),
            supplied=True,
        ),
    ]
    incremental_columns = (
        {
            "ingested_at": incremental.ordering.ingested_at,
            "source_updated_at": incremental.ordering.source_updated_at,
            "source_effective_at": incremental.ordering.source_effective_at,
        }
        if incremental is not None
        else {}
    )
    for role, output_name, supplied_origin, cdc_attribute in roles:
        configured = incremental_columns.get(cdc_attribute)
        source_values: list[TimestampSourceSpec] = []
        for source_ref in source_refs:
            contract_column = (contract_cdc_by_source or {}).get(source_ref, {}).get(cdc_attribute)
            source_column = (
                configured.value
                if (
                    configured is not None
                    and not configured.value.startswith("_")
                    and configured.value
                    in (available_columns_by_source or {}).get(source_ref, frozenset())
                )
                else None
            )
            if source_column is None and contract_column is not None:
                source_column = contract_column
            source_values.append(
                TimestampSourceSpec(
                    source_identity_ref=source_ref,
                    source_column=source_column,
                    origin=(
                        supplied_origin
                        if source_column is not None
                        else TimestampOrigin.NOT_SUPPLIED
                    ),
                    supplied=source_column is not None,
                )
            )
        supplied_columns = tuple(
            sorted({item.source_column for item in source_values if item.source_column is not None})
        )
        supplied = bool(supplied_columns)
        source_column = supplied_columns[0] if len(supplied_columns) == 1 else None
        origin = (
            EffectiveValue(supplied_origin, configured.provenance)
            if configured is not None and supplied
            else _default(
                supplied_origin if supplied else TimestampOrigin.NOT_SUPPLIED,
                "DD-108-lineage-time",
                (
                    f"{output_name} is supplied by the binding load policy."
                    if supplied
                    else f"{output_name} is not supplied; no other timestamp is substituted."
                ),
            )
        )
        values.append(
            TimestampSemanticSpec(
                role=role,
                column_name=output_name,
                origin=origin,
                source_column=source_column,
                supplied=supplied,
                sources=tuple(source_values),
            )
        )
    return tuple(values)


def _normalize_identities(
    facts: tuple[EntityIdentityFact, ...],
    multi_source: tuple[MultiSourcePolicySpec, ...],
    hashes: tuple[CanonicalHashPolicySpec, ...],
    incremental: tuple[IncrementalPolicySpec, ...],
    candidates: tuple[BoundSilverModel, ...],
    issues: list[PolicyIssue],
    contracts: tuple[tuple[str, ContractFact], ...] = (),
) -> tuple[EntityIdentitySpec, ...]:
    multi_by_ref = {item.resource_uri: item for item in multi_source}
    hash_refs = {item.resource_uri for item in hashes}
    incremental_by_ref = {item.resource_uri: item for item in incremental}
    contract_by_identity = {
        contract.identity_resource_uri: contract
        for _, contract in contracts
        if contract.identity_resource_uri
    }
    governed_identity_refs = (
        set(contract_by_identity)
        | {
            candidate.source_identity_ref
            for candidate in candidates
            if candidate.source_identity_ref
        }
        | {
            source_ref
            for fact in facts
            if fact.source_identities is not None
            for source_ref in fact.source_identities.values
            if source_ref
        }
    )
    source_ref_by_relation: dict[str, str] = {}
    source_ref_by_relation.update(
        {
            contract.virtual_source_iri: contract.identity_resource_uri
            for contract in contract_by_identity.values()
        }
    )
    identity_fact_by_class = {fact.resource_uri: fact for fact in facts}
    sources_by_class: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        class_sources = sources_by_class.setdefault(candidate.identity.class_uri, {})
        for source in candidate.sources:
            class_sources.setdefault(source.table_uri, source)
    for class_uri, class_sources in sources_by_class.items():
        identity_fact = identity_fact_by_class.get(class_uri)
        source_refs = (
            identity_fact.source_identities.values
            if identity_fact is not None and identity_fact.source_identities is not None
            else ()
        )
        for source, source_ref in zip(class_sources.values(), source_refs, strict=False):
            source_ref_by_relation.setdefault(source.table_uri, source_ref)
    source_ref_by_relation.update(
        {
            source.table_uri: candidate.source_identity_ref
            for candidate in candidates
            if candidate.source_identity_ref
            for source in candidate.sources
        }
    )
    available_columns: dict[tuple[str, str], set[str]] = {}
    contributor_refs: dict[str, set[str]] = {}
    for candidate in candidates:
        supplied_columns = {
            column.name
            for column in candidate.columns
            if not _NULL_EXPRESSION.match(column.expression or "")
        }
        for source in candidate.sources:
            source_ref = source_ref_by_relation.get(source.table_uri)
            if source_ref is not None:
                contributor_refs.setdefault(
                    candidate.identity.class_uri,
                    set(),
                ).add(source_ref)
                available_columns.setdefault(
                    (candidate.identity.class_uri, source_ref),
                    set(),
                ).update(supplied_columns)
    result: list[EntityIdentitySpec] = []
    for fact in facts:
        strategy = (
            _enum(
                fact.strategy,
                IdentityStrategy,
                "identity strategy",
                "DD-108-identity",
            )
            if fact.strategy is not None
            else None
        )
        if strategy is None:
            raise PolicyNormalizationError(
                "identity.missing-strategy",
                "materialized identity policy requires identityStrategy",
                rule_id="DD-108-identity",
                resource_uri=fact.resource_uri,
            )
        raw_source_refs = (
            tuple(value.strip() for value in fact.source_identities.values if value.strip())
            if fact.source_identities is not None
            else ()
        )
        if len(set(raw_source_refs)) != len(raw_source_refs):
            raise PolicyNormalizationError(
                "identity.duplicate-source-identity",
                "sourceIdentity references must be unique",
                rule_id="DD-108-source-identity",
                resource_uri=fact.resource_uri,
            )
        source_refs = _texts(
            fact.source_identities,
            "prepared source identity",
            "DD-108-source-identity",
        )
        unknown_source_refs = tuple(
            source_ref
            for source_ref in source_refs.value
            if source_ref not in governed_identity_refs
        )
        if unknown_source_refs:
            raise PolicyNormalizationError(
                "identity.unknown-source-identity",
                (
                    "sourceIdentity must reference a source bound by EntityBinding "
                    "or a dbt ContractIdentity; unknown: "
                    f"{', '.join(unknown_source_refs)}"
                ),
                rule_id="DD-108-source-identity",
                resource_uri=fact.resource_uri,
            )
        unverified_contracts = tuple(
            source_ref
            for source_ref in source_refs.value
            if source_ref in contract_by_identity
            and not contract_by_identity[source_ref].identity_verified
        )
        if unverified_contracts:
            issues.append(
                PolicyIssue(
                    code="identity.contract-unverified",
                    message=(
                        "Contract-output identity is unverified and review-only until "
                        "actual passing uniqueness and non-null evidence is tied to the "
                        "current contract content hash; "
                        f"unverified: {', '.join(unverified_contracts)}"
                    ),
                    rule_id="DD-108-contract-identity",
                    resource_uri=fact.resource_uri,
                    blocking=True,
                    projection_blocking=False,
                )
            )
        contract_sources = tuple(
            contract_by_identity[source_ref]
            for source_ref in source_refs.value
            if source_ref in contract_by_identity
        )
        if fact.scd_type is not None:
            required_cdc = {
                "operation",
                "source_updated_at",
                "source_effective_at",
                "ingested_at",
            }
            incomplete = tuple(
                contract.identity_resource_uri
                for contract in contract_sources
                if not required_cdc.issubset(dict(contract.canonical_cdc_bindings))
            )
            if incomplete:
                raise PolicyNormalizationError(
                    "identity.contract-cdc-incomplete",
                    (
                        "SCD1/SCD2 contract identity requires canonical operation, "
                        "source-update, business-effective, and ingestion output bindings; "
                        f"incomplete: {', '.join(incomplete)}"
                    ),
                    rule_id="DD-109-contract-cdc",
                    resource_uri=fact.resource_uri,
                )
        actual_contributors = contributor_refs.get(fact.resource_uri, set())
        if actual_contributors and actual_contributors != set(source_refs.value):
            raise PolicyNormalizationError(
                "identity.source-contributor-mismatch",
                (
                    "sourceIdentity must enumerate every prepared contributor and no "
                    "unmapped contributor; declared "
                    f"{sorted(source_refs.value)!r}, actual {sorted(actual_contributors)!r}"
                ),
                rule_id="DD-108-source-identity",
                resource_uri=fact.resource_uri,
            )
        raw_natural_keys = (
            tuple(
                item.strip()
                for value in fact.natural_keys.values
                for item in value.split(",")
                if item.strip()
            )
            if fact.natural_keys is not None
            else ()
        )
        if len(set(raw_natural_keys)) != len(raw_natural_keys):
            raise PolicyNormalizationError(
                "identity.duplicate-key-component",
                "naturalKey components must be unique and explicitly ordered",
                rule_id="DD-108-business-identity",
                resource_uri=fact.resource_uri,
            )
        natural_keys = _texts(
            fact.natural_keys,
            "business-key properties",
            "DD-108-business-identity",
            required=False,
            split_commas=True,
        )
        natural_keys = EffectiveValue(
            tuple(camel_to_snake(value) for value in natural_keys.value),
            natural_keys.provenance,
        )
        limitation = (
            _text(
                fact.reconciliation_limitation,
                "surrogate-only reconciliation limitation",
                "DD-108-surrogate",
            )
            if fact.reconciliation_limitation is not None
            else None
        )
        if fact.business_grain is None:
            raise PolicyNormalizationError(
                "identity.missing-business-grain",
                "materialized identity policy requires businessGrain",
                rule_id="DD-108-grain",
                resource_uri=fact.resource_uri,
            )
        business_grain = _text(
            fact.business_grain,
            "business grain",
            "DD-108-grain",
        )
        if fact.key_scope is None:
            raise PolicyNormalizationError(
                "identity.missing-key-scope",
                "materialized identity policy requires keyScope",
                rule_id="DD-108-key-scope",
                resource_uri=fact.resource_uri,
            )
        key_scope = _enum(
            fact.key_scope,
            KeyScope,
            "identity key scope",
            "DD-108-key-scope",
        )
        if fact.iri_policy is None:
            raise PolicyNormalizationError(
                "identity.missing-iri-policy",
                "materialized identity policy requires entityInstanceIriPolicy emit or omit",
                rule_id="DD-108-iri",
                resource_uri=fact.resource_uri,
            )
        iri_mode = _enum(
            fact.iri_policy,
            EntityIriMode,
            "entity-instance IRI policy",
            "DD-108-iri",
        )
        if fact.lineage_policy is None:
            raise PolicyNormalizationError(
                "identity.missing-lineage-policy",
                "materialized identity policy requires lineagePolicy",
                rule_id="DD-108-lineage",
                resource_uri=fact.resource_uri,
            )
        lineage_policy = _text(
            fact.lineage_policy,
            "lineage policy",
            "DD-108-lineage",
        )

        if strategy.value is IdentityStrategy.BUSINESS_KEY and not natural_keys.value:
            raise PolicyNormalizationError(
                "identity.business-key-missing",
                "business-key identity requires at least one naturalKey property",
                rule_id="DD-108-business-identity",
                resource_uri=fact.resource_uri,
            )
        if (
            strategy.value
            in {
                IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY,
                IdentityStrategy.EXTERNALLY_MASTERED_IDENTIFIER,
            }
            and not natural_keys.value
        ):
            code = (
                "identity.integration-key-components-missing"
                if strategy.value is IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY
                else "identity.mastered-identifier-missing"
            )
            field = (
                "deterministic integration-key components"
                if strategy.value is IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY
                else "externally mastered identifier columns"
            )
            raise PolicyNormalizationError(
                code,
                f"{strategy.value.value} identity requires naturalKey to declare {field}",
                rule_id="DD-108-identity",
                resource_uri=fact.resource_uri,
            )
        if strategy.value is IdentityStrategy.SURROGATE_ONLY and natural_keys.value:
            raise PolicyNormalizationError(
                "identity.surrogate-only-forbids-natural-key",
                (
                    "surrogate-only identity forbids naturalKey; declare business-key "
                    "identity if those columns establish identity"
                ),
                rule_id="DD-108-surrogate",
                resource_uri=fact.resource_uri,
            )
        if strategy.value is IdentityStrategy.SURROGATE_ONLY and limitation is None:
            raise PolicyNormalizationError(
                "identity.surrogate-limitation-missing",
                "surrogate-only identity requires reconciliationLimitation",
                rule_id="DD-108-surrogate",
                resource_uri=fact.resource_uri,
            )
        if strategy.value is not IdentityStrategy.SURROGATE_ONLY and limitation is not None:
            raise PolicyNormalizationError(
                "identity.unexpected-reconciliation-limitation",
                "reconciliationLimitation is only valid for surrogate-only identity",
                rule_id="DD-108-surrogate",
                resource_uri=fact.resource_uri,
            )
        if (
            strategy.value is IdentityStrategy.SOURCE_SCOPED_IMMUTABLE_KEY
            and key_scope.value not in {KeyScope.SOURCE_TABLE, KeyScope.SOURCE_TABLE_ARRAY_ELEMENT}
        ):
            raise PolicyNormalizationError(
                "identity.source-scoped-key-scope",
                (
                    "source-scoped-immutable-key requires keyScope source-table or "
                    "source-table-array-element"
                ),
                rule_id="DD-108-key-scope",
                resource_uri=fact.resource_uri,
            )
        if strategy.value is IdentityStrategy.SURROGATE_ONLY and key_scope.value not in {
            KeyScope.SOURCE_TABLE,
            KeyScope.SOURCE_TABLE_ARRAY_ELEMENT,
        }:
            raise PolicyNormalizationError(
                "identity.surrogate-only-key-scope",
                (
                    "surrogate-only identity requires keyScope source-table or "
                    "source-table-array-element because its physical key cannot assert "
                    "domain or enterprise identity"
                ),
                rule_id="DD-108-key-scope",
                resource_uri=fact.resource_uri,
            )
        if (
            strategy.value is IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY
            and key_scope.value not in {KeyScope.DOMAIN, KeyScope.ENTERPRISE}
        ):
            raise PolicyNormalizationError(
                "identity.integration-key-scope",
                "deterministic-integration-key requires keyScope domain or enterprise",
                rule_id="DD-108-key-scope",
                resource_uri=fact.resource_uri,
            )
        if (
            strategy.value is IdentityStrategy.EXTERNALLY_MASTERED_IDENTIFIER
            and key_scope.value is not KeyScope.ENTERPRISE
        ):
            raise PolicyNormalizationError(
                "identity.mastered-key-scope",
                "externally-mastered-identifier requires enterprise keyScope",
                rule_id="DD-108-key-scope",
                resource_uri=fact.resource_uri,
            )

        multi_ref = _optional_single(
            fact.multi_source_policy_refs,
            "multi-source policy reference",
            "DD-108-multi-source",
        )
        if multi_ref is not None and multi_ref not in multi_by_ref:
            raise PolicyNormalizationError(
                "identity.unknown-multi-source-policy",
                f"multi-source policy {multi_ref!r} is not declared",
                rule_id="DD-108-multi-source",
                resource_uri=fact.resource_uri,
            )
        if len(source_refs.value) > 1 and multi_ref is None:
            raise PolicyNormalizationError(
                "identity.multi-source-policy-missing",
                "multiple prepared source identities require an explicit multiSourcePolicy",
                rule_id="DD-108-multi-source",
                resource_uri=fact.resource_uri,
            )
        if len(source_refs.value) == 1 and multi_ref is not None:
            raise PolicyNormalizationError(
                "identity.unexpected-multi-source-policy",
                "a single prepared source identity forbids multiSourcePolicy",
                rule_id="DD-108-multi-source",
                resource_uri=fact.resource_uri,
            )
        multi_policy = multi_by_ref.get(multi_ref) if multi_ref is not None else None
        if (
            multi_policy is not None
            and multi_policy.exact_equivalence.approved
            and set(multi_policy.precedence.ordered_sources.value) != set(source_refs.value)
        ):
            raise PolicyNormalizationError(
                "identity.exact-precedence-source-mismatch",
                ("exact-equivalence declared-order must contain every sourceIdentity exactly once"),
                rule_id="DD-108-precedence",
                resource_uri=fact.resource_uri,
            )
        if strategy.value is IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY:
            if multi_policy is None or not multi_policy.exact_equivalence.approved:
                raise PolicyNormalizationError(
                    "identity.integration-key-without-exact-equivalence",
                    (
                        "deterministic-integration-key requires a multiSourcePolicy with "
                        "approved exactly-equivalent branches and reconciliation rules"
                    ),
                    rule_id="DD-108-exact-equivalence",
                    resource_uri=fact.resource_uri,
                )
        elif multi_policy is not None and multi_policy.exact_equivalence.approved:
            raise PolicyNormalizationError(
                "identity.exact-equivalence-without-integration-strategy",
                (
                    "exactly-equivalent branches require identityStrategy "
                    "deterministic-integration-key; other strategies preserve branch identity"
                ),
                rule_id="DD-108-exact-equivalence",
                resource_uri=fact.resource_uri,
            )

        contribution = (
            ContributionLineageSpec(
                policy=_text(
                    fact.contribution_lineage,
                    "contribution lineage policy",
                    "DD-108-contribution-lineage",
                ),
                emits_all_source_records=(
                    _single(
                        fact.contribution_lineage,
                        "contribution lineage policy",
                        "DD-108-contribution-lineage",
                    )
                    == "all-source-record-contributions"
                ),
            )
            if fact.contribution_lineage is not None
            else None
        )
        if contribution is not None and not contribution.emits_all_source_records:
            raise PolicyNormalizationError(
                "lineage.unsupported-contribution-policy",
                ("contributionLineagePolicy must be 'all-source-record-contributions'"),
                rule_id="DD-108-contribution-lineage",
                resource_uri=fact.resource_uri,
            )
        driving_raw = _optional_single(
            fact.driving_source,
            "driving source",
            "DD-108-driving-source",
        )
        if len(source_refs.value) == 1 and driving_raw is not None:
            raise PolicyNormalizationError(
                "identity.unexpected-driving-source",
                (
                    "a single contributor has deterministic only-source driving mode and "
                    "forbids an authored drivingSource"
                ),
                rule_id="DD-108-driving-source",
                resource_uri=fact.resource_uri,
            )
        if driving_raw is not None:
            if driving_raw not in source_refs.value:
                raise PolicyNormalizationError(
                    "identity.unknown-driving-source",
                    f"driving source {driving_raw!r} is not a declared source identity",
                    rule_id="DD-108-driving-source",
                    resource_uri=fact.resource_uri,
                )
            driving = DrivingSourceSpec(
                mode=_effective(
                    DrivingSourceMode.DECLARED,
                    fact.driving_source,
                    "DD-108-driving-source",
                ),
                source_ref=_text(
                    fact.driving_source,
                    "driving source",
                    "DD-108-driving-source",
                ),
            )
        elif len(source_refs.value) == 1:
            driving = DrivingSourceSpec(
                mode=_default(
                    DrivingSourceMode.ONLY_SOURCE,
                    "DD-108-driving-source",
                    "A single contributing source is necessarily driving.",
                ),
                source_ref=_default(
                    source_refs.value[0],
                    "DD-108-driving-source",
                    "Derived from the single prepared source identity.",
                ),
            )
        else:
            raise PolicyNormalizationError(
                "identity.driving-source-missing",
                (
                    "multiple contributors require an explicit drivingSource selected "
                    "from sourceIdentity"
                ),
                rule_id="DD-108-driving-source",
                resource_uri=fact.resource_uri,
            )

        change_detection = (
            _enum(
                fact.change_detection,
                ChangeDetectionStrategy,
                "change-detection strategy",
                "DD-108-change-detection",
            )
            if fact.change_detection is not None
            else None
        )
        if change_detection is None:
            raise PolicyNormalizationError(
                "identity.missing-change-detection",
                "materialized identity policy requires changeDetectionStrategy",
                rule_id="DD-108-change-detection",
                resource_uri=fact.resource_uri,
            )
        hash_ref = _optional_single(
            fact.hash_policy_refs,
            "hash policy reference",
            "DD-109-hash",
        )
        if change_detection.value is ChangeDetectionStrategy.CANONICAL_HASH:
            if hash_ref is None or hash_ref not in hash_refs:
                raise PolicyNormalizationError(
                    "identity.hash-policy-missing",
                    "canonical-hash change detection requires a declared HashPolicy",
                    rule_id="DD-109-hash",
                    resource_uri=fact.resource_uri,
                )
        elif hash_ref is not None:
            raise PolicyNormalizationError(
                "identity.unexpected-hash-policy",
                "hashPolicy is only valid with canonical-hash change detection",
                rule_id="DD-109-hash",
                resource_uri=fact.resource_uri,
            )

        incremental_ref = _optional_single(
            fact.incremental_policy_refs,
            "incremental policy reference",
            "DD-109-incremental",
        )
        if incremental_ref is not None and incremental_ref not in incremental_by_ref:
            raise PolicyNormalizationError(
                "identity.unknown-incremental-policy",
                f"incremental policy {incremental_ref!r} is not declared",
                rule_id="DD-109-incremental",
                resource_uri=fact.resource_uri,
            )

        result.append(
            EntityIdentitySpec(
                entity_uri=fact.resource_uri,
                business_grain=business_grain,
                strategy=strategy,
                key_scope=key_scope,
                source=SourceIdentityPolicy(source_refs),
                business=BusinessIdentityPolicy(
                    keys=natural_keys,
                    authoritative=strategy.value is IdentityStrategy.BUSINESS_KEY,
                ),
                integration=IntegrationIdentityPolicy(
                    emitted=(strategy.value is IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY)
                ),
                mastered=MasteredIdentityPolicy(
                    external_identifier_refs=(
                        natural_keys
                        if strategy.value is IdentityStrategy.EXTERNALLY_MASTERED_IDENTIFIER
                        else _default(
                            (),
                            "DD-108-mastered-identity",
                            "Entity is not externally mastered.",
                        )
                    ),
                    routed_to_mdm=(
                        strategy.value is IdentityStrategy.EXTERNALLY_MASTERED_IDENTIFIER
                    ),
                ),
                surrogate=SurrogateIdentityPolicy(
                    emitted_as_join_key=True,
                    establishes_business_identity=False,
                    reconciliation_limitation=limitation,
                ),
                iri=IriPolicy(iri_mode),
                driving_source=driving,
                change_detection=change_detection,
                lineage=LineageSpec(
                    policy=lineage_policy,
                    contribution=contribution,
                    timestamps=_timestamp_semantics(
                        source_refs.value,
                        incremental_by_ref.get(incremental_ref),
                        {
                            source_ref: frozenset(
                                available_columns.get(
                                    (fact.resource_uri, source_ref),
                                    set(),
                                )
                            )
                            for source_ref in source_refs.value
                        },
                        {
                            source_ref: dict(
                                contract_by_identity[source_ref].canonical_cdc_bindings
                            )
                            for source_ref in source_refs.value
                            if source_ref in contract_by_identity
                        },
                    ),
                ),
                multi_source_policy_ref=multi_ref,
                hash_policy_ref=hash_ref,
                incremental_policy_ref=incremental_ref,
            )
        )

    return tuple(result)


_DQ_PARAMETER_KEYS: dict[DqCheckKind, frozenset[str]] = {
    DqCheckKind.CONTRACT_SHAPE: frozenset({"required"}),
    DqCheckKind.FRESHNESS: frozenset({"column", "unit"}),
    DqCheckKind.VOLUME: frozenset({"metric"}),
    DqCheckKind.DUPLICATE_RATE: frozenset({"columns"}),
    DqCheckKind.RANGE: frozenset({"column", "minimum", "maximum"}),
    DqCheckKind.DISTRIBUTION: frozenset({"column", "allowed"}),
    DqCheckKind.RECONCILIATION: frozenset({"compare_model", "metric", "column", "compare_column"}),
    DqCheckKind.REFERENTIAL_COVERAGE: frozenset({"column", "parent_model", "parent_column"}),
    DqCheckKind.CROSS_FIELD: frozenset({"left", "operator", "right"}),
}
_DQ_SAFE_LITERAL = re.compile(r"^[A-Za-z0-9_.:@/+ -]+$")
_DQ_NUMBER = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


def _canonical_decimal(raw: str, fact: DataQualityRuleFact, label: str) -> str:
    if not _DQ_NUMBER.fullmatch(raw):
        raise PolicyNormalizationError(
            "dq.invalid-numeric-parameter",
            f"{label} must be a finite decimal number, not {raw!r}",
            rule_id="DD-115-dq-check",
            resource_uri=fact.resource_uri,
        )
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the grammar
        raise PolicyNormalizationError(
            "dq.invalid-numeric-parameter",
            f"{label} must be a finite decimal number, not {raw!r}",
            rule_id="DD-115-dq-check",
            resource_uri=fact.resource_uri,
        ) from exc
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered in {"-0", ""} else rendered


def _dq_identifiers(
    raw: str,
    fact: DataQualityRuleFact,
    label: str,
) -> tuple[str, ...]:
    values = tuple(item.strip() for item in raw.split(","))
    if not values or any(not _SAFE_NAME.fullmatch(item) for item in values):
        raise PolicyNormalizationError(
            "dq.invalid-identifier",
            f"{label} must contain only comma-separated dbt identifiers",
            rule_id="DD-115-dq-check",
            resource_uri=fact.resource_uri,
        )
    return values


def _normalize_dq_expression(
    fact: DataQualityRuleFact,
    kind: DqCheckKind,
) -> tuple[DqParameterSpec, ...]:
    raw = _single(
        fact.check_expression,
        "DQ declarative check expression",
        "DD-115-dq-check",
    )
    parsed: dict[str, str] = {}
    for item in raw.split(";"):
        if item.count("=") != 1:
            raise PolicyNormalizationError(
                "dq.invalid-expression",
                (
                    "DQ expressions use only the declarative key=value grammar; "
                    "raw SQL, comments, calls, and statement fragments are forbidden"
                ),
                rule_id="DD-115-dq-check",
                resource_uri=fact.resource_uri,
            )
        key, value = (part.strip() for part in item.split("=", 1))
        if (
            not _SAFE_NAME.fullmatch(key)
            or not value
            or key in parsed
            or key not in _DQ_PARAMETER_KEYS[kind]
        ):
            raise PolicyNormalizationError(
                "dq.invalid-expression-parameter",
                f"{kind.value!r} has an invalid or duplicate parameter {key!r}",
                rule_id="DD-115-dq-check",
                resource_uri=fact.resource_uri,
            )
        parsed[key] = value

    required = {
        DqCheckKind.CONTRACT_SHAPE: {"required"},
        DqCheckKind.FRESHNESS: {"column", "unit"},
        DqCheckKind.VOLUME: {"metric"},
        DqCheckKind.DUPLICATE_RATE: {"columns"},
        DqCheckKind.RANGE: {"column"},
        DqCheckKind.DISTRIBUTION: {"column", "allowed"},
        DqCheckKind.RECONCILIATION: {"compare_model", "metric"},
        DqCheckKind.REFERENTIAL_COVERAGE: {
            "column",
            "parent_model",
            "parent_column",
        },
        DqCheckKind.CROSS_FIELD: {"left", "operator", "right"},
    }[kind]
    missing = sorted(required - parsed.keys())
    if missing:
        raise PolicyNormalizationError(
            "dq.missing-expression-parameter",
            f"{kind.value!r} is missing required parameters: {', '.join(missing)}",
            rule_id="DD-115-dq-check",
            resource_uri=fact.resource_uri,
        )

    values: dict[str, tuple[str, ...]] = {}
    for key, value in parsed.items():
        if key in {
            "column",
            "compare_column",
            "left",
            "parent_column",
            "right",
        }:
            values[key] = _dq_identifiers(value, fact, key)
            if len(values[key]) != 1:
                raise PolicyNormalizationError(
                    "dq.invalid-expression-parameter",
                    f"{key} accepts exactly one identifier",
                    rule_id="DD-115-dq-check",
                    resource_uri=fact.resource_uri,
                )
        elif key in {"columns", "required"}:
            values[key] = _dq_identifiers(value, fact, key)
        elif key in {"compare_model", "parent_model"}:
            values[key] = _dq_identifiers(value, fact, key)
            if len(values[key]) != 1:
                raise PolicyNormalizationError(
                    "dq.invalid-expression-parameter",
                    f"{key} accepts exactly one model identifier",
                    rule_id="DD-115-dq-check",
                    resource_uri=fact.resource_uri,
                )
        elif key in {"minimum", "maximum"}:
            values[key] = (_canonical_decimal(value, fact, key),)
        elif key == "allowed":
            allowed = tuple(item.strip() for item in value.split("|"))
            if not allowed or any(
                not item or not _DQ_SAFE_LITERAL.fullmatch(item) for item in allowed
            ):
                raise PolicyNormalizationError(
                    "dq.invalid-allowed-value",
                    "distribution values use a pipe-separated safe literal list",
                    rule_id="DD-115-dq-check",
                    resource_uri=fact.resource_uri,
                )
            values[key] = allowed
        else:
            values[key] = (value,)

    if kind is DqCheckKind.VOLUME and parsed["metric"] != "row-count":
        raise PolicyNormalizationError(
            "dq.invalid-volume-metric",
            "volume v1 supports only metric=row-count",
            rule_id="DD-115-dq-check",
            resource_uri=fact.resource_uri,
        )
    if kind is DqCheckKind.FRESHNESS and parsed["unit"] not in {
        "seconds",
        "minutes",
        "hours",
        "days",
    }:
        raise PolicyNormalizationError(
            "dq.invalid-freshness-unit",
            "freshness unit must be seconds, minutes, hours, or days",
            rule_id="DD-115-dq-check",
            resource_uri=fact.resource_uri,
        )
    if kind is DqCheckKind.CROSS_FIELD and parsed["operator"] not in {
        "eq",
        "ne",
        "lt",
        "lte",
        "gt",
        "gte",
    }:
        raise PolicyNormalizationError(
            "dq.invalid-cross-field-operator",
            "cross-field operator must be eq, ne, lt, lte, gt, or gte",
            rule_id="DD-115-dq-check",
            resource_uri=fact.resource_uri,
        )
    if kind is DqCheckKind.RECONCILIATION:
        metric = parsed["metric"]
        if metric not in {"count", "sum"}:
            raise PolicyNormalizationError(
                "dq.invalid-reconciliation-metric",
                "reconciliation metric must be count or sum",
                rule_id="DD-115-dq-check",
                resource_uri=fact.resource_uri,
            )
        columns = {"column", "compare_column"}
        if metric == "sum" and not columns.issubset(parsed):
            raise PolicyNormalizationError(
                "dq.missing-expression-parameter",
                "sum reconciliation requires column and compare_column",
                rule_id="DD-115-dq-check",
                resource_uri=fact.resource_uri,
            )
        if metric == "count" and columns & parsed.keys():
            raise PolicyNormalizationError(
                "dq.invalid-expression-parameter",
                "count reconciliation does not accept column parameters",
                rule_id="DD-115-dq-check",
                resource_uri=fact.resource_uri,
            )
    if kind is DqCheckKind.RANGE:
        if not {"minimum", "maximum"} & parsed.keys():
            raise PolicyNormalizationError(
                "dq.missing-expression-parameter",
                "range requires minimum, maximum, or both",
                rule_id="DD-115-dq-check",
                resource_uri=fact.resource_uri,
            )
        if {"minimum", "maximum"}.issubset(parsed) and Decimal(values["minimum"][0]) > Decimal(
            values["maximum"][0]
        ):
            raise PolicyNormalizationError(
                "dq.invalid-range",
                "range minimum cannot exceed maximum",
                rule_id="DD-115-dq-check",
                resource_uri=fact.resource_uri,
            )
    return tuple(DqParameterSpec(key, values[key]) for key in sorted(values))


def _normalize_dq_tolerance(
    fact: DataQualityRuleFact,
    kind: DqCheckKind,
) -> EffectiveValue[DqToleranceSpec]:
    raw = _single(fact.tolerance, "DQ tolerance", "DD-115-dq")
    canonical = _canonical_decimal(raw, fact, "DQ tolerance")
    value = Decimal(canonical)
    tolerance_kind = {
        DqCheckKind.CONTRACT_SHAPE: DqToleranceKind.COUNT,
        DqCheckKind.FRESHNESS: DqToleranceKind.DURATION,
        DqCheckKind.VOLUME: DqToleranceKind.COUNT,
        DqCheckKind.DUPLICATE_RATE: DqToleranceKind.RATIO,
        DqCheckKind.RANGE: DqToleranceKind.RATIO,
        DqCheckKind.DISTRIBUTION: DqToleranceKind.RATIO,
        DqCheckKind.RECONCILIATION: DqToleranceKind.ABSOLUTE_DIFFERENCE,
        DqCheckKind.REFERENTIAL_COVERAGE: DqToleranceKind.RATIO,
        DqCheckKind.CROSS_FIELD: DqToleranceKind.RATIO,
    }[kind]
    if value < 0:
        raise PolicyNormalizationError(
            "dq.invalid-tolerance",
            "DQ tolerance cannot be negative",
            rule_id="DD-115-dq",
            resource_uri=fact.resource_uri,
        )
    if tolerance_kind is DqToleranceKind.RATIO and value > 1:
        raise PolicyNormalizationError(
            "dq.invalid-tolerance",
            "ratio tolerance must be between 0 and 1 inclusive",
            rule_id="DD-115-dq",
            resource_uri=fact.resource_uri,
        )
    if tolerance_kind is DqToleranceKind.COUNT and value != value.to_integral_value():
        raise PolicyNormalizationError(
            "dq.invalid-tolerance",
            "count tolerance must be an integer",
            rule_id="DD-115-dq",
            resource_uri=fact.resource_uri,
        )
    if kind is DqCheckKind.CONTRACT_SHAPE and value != 0:
        raise PolicyNormalizationError(
            "dq.invalid-tolerance",
            "contract-shape is fail-closed and requires tolerance 0",
            rule_id="DD-115-dq",
            resource_uri=fact.resource_uri,
        )
    unit = ""
    if kind is DqCheckKind.FRESHNESS:
        parameters = _normalize_dq_expression(fact, kind)
        unit = next(item.values[0] for item in parameters if item.name == "unit")
    return _effective(
        DqToleranceSpec(tolerance_kind, canonical, unit),
        fact.tolerance,
        "DD-115-dq",
    )


def _normalize_dq(
    facts: tuple[DataQualityRuleFact, ...],
) -> tuple[DataQualityRuleSpec, ...]:
    result: list[DataQualityRuleSpec] = []
    identifiers: set[tuple[str, str]] = set()
    for fact in facts:
        rule_id = _text(fact.rule_id, "DQ rule ID", "DD-115-dq")
        version = _text(fact.version, "DQ rule version", "DD-115-dq")
        identity = (rule_id.value, version.value)
        if identity in identifiers:
            raise PolicyNormalizationError(
                "dq.duplicate-rule",
                f"DQ rule {identity[0]!r} version {identity[1]!r} is duplicated",
                rule_id="DD-115-dq",
                resource_uri=fact.resource_uri,
            )
        identifiers.add(identity)
        check_kind = _enum(
            fact.check_kind,
            DqCheckKind,
            "DQ check kind",
            "DD-115-dq-check",
        )
        parameters = _normalize_dq_expression(fact, check_kind.value)
        test_refs = _texts(
            fact.test_refs,
            "DQ executable test references",
            "DD-115-dq-check",
        )
        expected_ref = f"kairos.dq.{check_kind.value.value}.v1"
        if test_refs.value != (expected_ref,):
            raise PolicyNormalizationError(
                "dq.unsupported-test-reference",
                (
                    f"{check_kind.value.value!r} must use the toolkit-owned "
                    f"test reference {expected_ref!r}; arbitrary SQL and ungoverned "
                    "external tests are not executable DQ authority"
                ),
                rule_id="DD-115-dq-check",
                resource_uri=fact.resource_uri,
            )
        tolerance = _normalize_dq_tolerance(fact, check_kind.value)
        action = _enum(
            fact.action,
            DqAction,
            "DQ action",
            "DD-115-dq-action",
        )
        category = _enum(
            fact.category,
            DqCategory,
            "DQ category",
            "DD-115-dq",
        )
        scope = _text(fact.scope, "DQ scope", "DD-115-dq")
        severity = _enum(
            fact.severity,
            DqSeverity,
            "DQ severity",
            "DD-115-dq",
        )
        owner_role = _text(
            fact.owner_role,
            "DQ owner role",
            "DD-115-dq",
        )
        evidence = _texts(
            fact.evidence,
            "DQ evidence",
            "DD-115-dq",
        )
        rule_hash = hashlib.sha256(
            json.dumps(
                {
                    "action": action.value.value,
                    "category": category.value.value,
                    "check": check_kind.value.value,
                    "evidence": list(evidence.value),
                    "owner_role": owner_role.value,
                    "parameters": [[item.name, list(item.values)] for item in parameters],
                    "rule_id": rule_id.value,
                    "scope": scope.value,
                    "severity": severity.value.value,
                    "test_refs": list(test_refs.value),
                    "tolerance": {
                        "kind": tolerance.value.kind.value,
                        "unit": tolerance.value.unit,
                        "value": tolerance.value.value,
                    },
                    "version": version.value,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        result.append(
            DataQualityRuleSpec(
                resource_uri=fact.resource_uri,
                governing_entity_uri=fact.governing_entity_uri,
                rule_id=rule_id,
                version=version,
                category=category,
                scope=scope,
                check=DqExpressionSpec(
                    check_kind=check_kind,
                    parameters=parameters,
                    test_refs=test_refs,
                ),
                severity=severity,
                tolerance=tolerance,
                owner_role=owner_role,
                action=action,
                evidence=evidence,
                effect=QuarantineEffectSpec(
                    quarantines_rows=action.value is DqAction.QUARANTINE,
                    releases_source_rows=action.value is not DqAction.BLOCK,
                    release_requires_passing_recheck=(action.value is DqAction.QUARANTINE),
                ),
                rule_hash=rule_hash,
            )
        )
    return tuple(result)


def _normalize_deviations(
    facts: tuple,
    issues: list[PolicyIssue],
) -> tuple[ApprovedDeviationSpec, ...]:
    result: list[ApprovedDeviationSpec] = []
    for fact in facts:
        approval = _text(
            fact.approval_status,
            "deviation approval status",
            "DD-114-deviation",
        )
        if approval.value != "approved":
            issues.append(
                PolicyIssue(
                    code="deviation.not-approved",
                    message=(
                        f"Deviation {fact.resource_uri!r} is {approval.value!r}; "
                        "only approvalStatus 'approved' can authorize it."
                    ),
                    rule_id="DD-114-deviation",
                    resource_uri=fact.resource_uri,
                )
            )
        adapter_raw = _optional_single(
            fact.adapter_name,
            "deviation adapter",
            "DD-111-adapter",
        )
        if adapter_raw is not None:
            try:
                adapter = AdapterName(adapter_raw)
            except ValueError as exc:
                raise _error(
                    "deviation.unknown-adapter",
                    f"unknown deviation adapter {adapter_raw!r}",
                    fact.adapter_name,
                    "DD-111-adapter",
                ) from exc
        else:
            adapter = None
        review = _text(
            fact.review_date,
            "deviation review date",
            "DD-114-deviation",
        )
        expiry = _text(
            fact.expiry_date,
            "deviation expiry date",
            "DD-114-deviation",
        )
        try:
            review_date = date.fromisoformat(review.value)
            expiry_date = date.fromisoformat(expiry.value)
        except ValueError as exc:
            raise PolicyNormalizationError(
                "deviation.invalid-date",
                "deviation review/expiry dates must use ISO YYYY-MM-DD",
                rule_id="DD-114-deviation",
                resource_uri=fact.resource_uri,
            ) from exc
        if expiry_date < review_date:
            raise PolicyNormalizationError(
                "deviation.expiry-before-review",
                "deviation expiry cannot precede its review date",
                rule_id="DD-114-deviation",
                resource_uri=fact.resource_uri,
            )
        rationale = _text(
            fact.rationale,
            "deviation rationale",
            "DD-114-deviation",
        )
        evidence = _texts(
            fact.evidence,
            "deviation evidence",
            "DD-114-deviation",
        )
        result.append(
            ApprovedDeviationSpec(
                resource_uri=fact.resource_uri,
                adapter=adapter,
                policy_reference=_text(
                    fact.policy_reference,
                    "deviation policy reference",
                    "DD-114-deviation",
                ),
                scope=_text(
                    fact.scope,
                    "deviation scope",
                    "DD-114-deviation",
                ),
                rationale=rationale,
                owner_role=_text(
                    fact.owner_role,
                    "deviation owner role",
                    "DD-114-deviation",
                ),
                approval_status=approval,
                review_date=review,
                expiry_date=expiry,
                evidence=(fact.resource_uri, rationale.value, *evidence.value),
            )
        )
    return tuple(result)


def _validate_adapter_evidence(
    facts: tuple[AdapterSupportFact, ...],
    issues: list[PolicyIssue],
) -> tuple[AdapterEvidenceSpec, ...]:
    states: dict[tuple[AdapterName, str, str, AdapterCapability], str] = {}
    result: list[AdapterEvidenceSpec] = []
    for fact in facts:
        adapter_raw = _single(
            fact.adapter_name,
            "adapter evidence name",
            "DD-111-adapter",
        )
        try:
            adapter = AdapterName(adapter_raw)
        except ValueError as exc:
            raise _error(
                "adapter-evidence.unknown-adapter",
                f"unknown adapter {adapter_raw!r}",
                fact.adapter_name,
                "DD-111-adapter",
            ) from exc
        status = _enum(
            fact.status,
            AdapterEvidenceStatus,
            "adapter support status",
            "DD-111-capability",
        )
        adapter_version = _text(
            fact.adapter_version,
            "adapter evidence version",
            "DD-111-capability",
        )
        scope = _text(
            fact.scope,
            "adapter evidence scope",
            "DD-111-capability",
        )
        capabilities: list[AdapterCapability] = []
        for raw in _many(
            fact.capabilities,
            "adapter capabilities",
            "DD-111-capability",
        ):
            try:
                capability = AdapterCapability(raw)
            except ValueError as exc:
                raise _error(
                    "adapter-evidence.unknown-capability",
                    f"unknown adapter capability {raw!r}",
                    fact.capabilities,
                    "DD-111-capability",
                ) from exc
            capabilities.append(capability)
            key = (adapter, adapter_version.value, scope.value, capability)
            previous = states.get(key)
            if previous is not None and previous != status.value.value:
                raise PolicyNormalizationError(
                    "adapter-evidence.contradictory-status",
                    (
                        f"{adapter.value}/{capability.value} has conflicting "
                        f"statuses {previous!r} and {status.value.value!r}"
                    ),
                    rule_id="DD-111-capability",
                    resource_uri=fact.resource_uri,
                )
            states[key] = status.value.value
            if status.value is AdapterEvidenceStatus.SUPPORTED and (
                fact.compile_evidence is None or not fact.compile_evidence.values
            ):
                issues.append(
                    PolicyIssue(
                        code="adapter-evidence.compile-missing",
                        message=(
                            f"{adapter.value}/{capability.value} is authored supported "
                            "without successful compile evidence."
                        ),
                        rule_id="DD-111-compile-evidence",
                        resource_uri=fact.resource_uri,
                    )
                )
            if status.value is not AdapterEvidenceStatus.SUPPORTED:
                issues.append(
                    PolicyIssue(
                        code=f"adapter-evidence.{status.value.value}",
                        message=(
                            f"{adapter.value}/{capability.value} evidence is "
                            f"{status.value.value}; "
                            "strict release cannot treat it as supported."
                        ),
                        rule_id="DD-111-capability",
                        resource_uri=fact.resource_uri,
                    )
                )
        result.append(
            AdapterEvidenceSpec(
                resource_uri=fact.resource_uri,
                adapter=_effective(
                    adapter,
                    fact.adapter_name,
                    "DD-111-adapter",
                ),
                adapter_version=adapter_version,
                scope=scope,
                capabilities=_effective(
                    tuple(sorted(set(capabilities), key=lambda item: item.value)),
                    fact.capabilities,
                    "DD-111-capability",
                ),
                status=status,
                compile_evidence=_texts(
                    fact.compile_evidence,
                    "adapter compile evidence",
                    "DD-111-compile-evidence",
                    required=False,
                ),
            )
        )
    return tuple(result)


def _measure_cycle(measures: tuple[MeasureFact, ...]) -> tuple[str, ...] | None:
    graph = {
        fact.resource_uri: tuple(
            fact.measure_dependencies.values if fact.measure_dependencies is not None else ()
        )
        for fact in measures
    }
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(node: str) -> tuple[str, ...] | None:
        if node in visiting:
            index = visiting.index(node)
            return tuple(visiting[index:] + [node])
        if node in visited:
            return None
        visiting.append(node)
        for dependency in graph.get(node, ()):
            cycle = visit(dependency)
            if cycle is not None:
                return cycle
        visiting.pop()
        visited.add(node)
        return None

    for node in sorted(graph):
        cycle = visit(node)
        if cycle is not None:
            return cycle
    return None


def _normalize_measures(facts: tuple[MeasureFact, ...]) -> tuple[MeasureSpec, ...]:
    known = {fact.resource_uri for fact in facts}
    cycle = _measure_cycle(facts)
    if cycle is not None:
        raise PolicyNormalizationError(
            "measure.dependency-cycle",
            f"measure dependency cycle: {' -> '.join(cycle)}",
            rule_id="DD-113-measure-dependencies",
            resource_uri=cycle[0],
        )
    result: list[MeasureSpec] = []
    ids: set[str] = set()
    for fact in facts:
        measure_id = _text(
            fact.measure_id,
            "measure stable identifier",
            "DD-113-measure",
        )
        if measure_id.value in ids:
            raise PolicyNormalizationError(
                "measure.duplicate-id",
                f"measure identifier {measure_id.value!r} is duplicated",
                rule_id="DD-113-measure",
                resource_uri=fact.resource_uri,
            )
        ids.add(measure_id.value)
        lifecycle = _enum(
            fact.lifecycle,
            MeasureLifecycle,
            "measure lifecycle",
            "DD-113-measure-lifecycle",
        )
        expression = (
            _text(
                fact.expression,
                "measure expression",
                "DD-113-measure",
            )
            if fact.expression is not None
            else None
        )
        columns = _texts(
            fact.column_dependencies,
            "measure column dependencies",
            "DD-113-measure-dependencies",
            required=False,
        )
        dependencies = _texts(
            fact.measure_dependencies,
            "measure dependencies",
            "DD-113-measure-dependencies",
            required=False,
        )
        missing = tuple(value for value in dependencies.value if value not in known)
        if missing:
            raise PolicyNormalizationError(
                "measure.unknown-dependency",
                f"measure dependencies do not resolve: {missing!r}",
                rule_id="DD-113-measure-dependencies",
                resource_uri=fact.resource_uri,
            )
        if lifecycle.value is not MeasureLifecycle.INTENT and (
            expression is None or not (columns.value or dependencies.value)
        ):
            raise PolicyNormalizationError(
                "measure.incomplete-governed-measure",
                (
                    "provisional, validated, and approved measures require an "
                    "expression and at least one dependency"
                ),
                rule_id="DD-113-measure-lifecycle",
                resource_uri=fact.resource_uri,
            )
        data_type = (
            _text(
                fact.data_type,
                "measure data type",
                "DD-113-measure",
            )
            if fact.data_type is not None
            else None
        )
        format_string = (
            _text(
                fact.format_string,
                "measure format string",
                "DD-113-measure",
            )
            if fact.format_string is not None
            else None
        )
        folder = (
            _text(
                fact.folder,
                "measure folder",
                "DD-113-measure",
            )
            if fact.folder is not None
            else None
        )
        owner = (
            _text(
                fact.owner_role,
                "measure owner role",
                "DD-113-measure",
            )
            if fact.owner_role is not None
            else None
        )
        tests = _texts(
            fact.tests,
            "measure validation tests",
            "DD-113-measure",
            required=False,
        )
        evidence = _texts(
            fact.evidence,
            "measure validation evidence",
            "DD-113-measure",
            required=False,
        )
        if lifecycle.value is not MeasureLifecycle.INTENT and (
            data_type is None or format_string is None or folder is None
        ):
            raise PolicyNormalizationError(
                "measure.incomplete-semantic-contract",
                (
                    "provisional, validated, and approved measures require "
                    "measureDataType, measureFormatString, and measureFolder"
                ),
                rule_id="DD-113-measure-lifecycle",
                resource_uri=fact.resource_uri,
            )
        if data_type is not None and data_type.value not in {
            "string",
            "boolean",
            "int64",
            "decimal",
            "double",
            "datetime",
            "currency",
            "percentage",
        }:
            raise PolicyNormalizationError(
                "measure.unsupported-data-type",
                f"unsupported measure data type {data_type.value!r}",
                rule_id="DD-113-measure",
                resource_uri=fact.resource_uri,
            )
        if lifecycle.value in {MeasureLifecycle.VALIDATED, MeasureLifecycle.APPROVED} and (
            not tests.value or not evidence.value
        ):
            raise PolicyNormalizationError(
                "measure.validation-evidence-missing",
                "validated and approved measures require tests and validation evidence",
                rule_id="DD-113-measure-lifecycle",
                resource_uri=fact.resource_uri,
            )
        if lifecycle.value is MeasureLifecycle.APPROVED and owner is None:
            raise PolicyNormalizationError(
                "measure.approval-owner-missing",
                "approved measures require an abstract owner role",
                rule_id="DD-113-measure-lifecycle",
                resource_uri=fact.resource_uri,
            )
        result.append(
            MeasureSpec(
                resource_uri=fact.resource_uri,
                measure_id=measure_id,
                definition=_text(
                    fact.definition,
                    "measure business definition",
                    "DD-113-measure",
                ),
                expression=expression,
                dependencies=MeasureDependencySpec(columns, dependencies),
                lifecycle=lifecycle,
                data_type=data_type,
                format_string=format_string,
                folder=folder,
                owner_role=owner,
                validation_tests=tests,
                validation_evidence=evidence,
            )
        )
    return tuple(result)


def _normalize_calendar(fact: CalendarFact) -> CalendarProfileSpec:
    start = _text(fact.start_date, "calendar start date", "DD-113-calendar")
    end = _text(fact.end_date, "calendar end date", "DD-113-calendar")
    try:
        start_date = date.fromisoformat(start.value)
        end_date = date.fromisoformat(end.value)
    except ValueError as exc:
        raise PolicyNormalizationError(
            "calendar.invalid-date",
            "calendar dates must use ISO YYYY-MM-DD",
            rule_id="DD-113-calendar",
            resource_uri=fact.resource_uri,
        ) from exc
    if start_date > end_date:
        raise PolicyNormalizationError(
            "calendar.invalid-range",
            "calendar start date must not be after end date",
            rule_id="DD-113-calendar",
            resource_uri=fact.resource_uri,
        )
    raw_month = _single(
        fact.fiscal_year_start_month,
        "fiscal year start month",
        "DD-113-calendar",
    )
    try:
        month = int(raw_month)
    except ValueError as exc:
        raise _error(
            "calendar.invalid-fiscal-month",
            f"fiscal month must be an integer, not {raw_month!r}",
            fact.fiscal_year_start_month,
            "DD-113-calendar",
        ) from exc
    if month not in range(1, 13):
        raise _error(
            "calendar.invalid-fiscal-month",
            "fiscal year start month must be 1 through 12",
            fact.fiscal_year_start_month,
            "DD-113-calendar",
        )
    approval_status = _text(
        fact.approval_status,
        "calendar approval status",
        "DD-113-calendar",
    )
    if approval_status.value not in {"draft", "approved"}:
        raise PolicyNormalizationError(
            "calendar.invalid-approval-status",
            "calendarApprovalStatus must be draft or approved",
            rule_id="DD-113-calendar",
            resource_uri=fact.resource_uri,
        )
    return CalendarProfileSpec(
        resource_uri=fact.resource_uri,
        start_date=start,
        end_date=end,
        fiscal_year_start_month=_effective(
            month,
            fact.fiscal_year_start_month,
            "DD-113-calendar",
        ),
        week_pattern=_text(
            fact.week_pattern,
            "calendar week pattern",
            "DD-113-calendar",
        ),
        locale=_text(fact.locale, "calendar locale", "DD-113-calendar"),
        holiday_source=_text(
            fact.holiday_source,
            "calendar holiday source",
            "DD-113-calendar",
        ),
        time_zone=_text(
            fact.time_zone,
            "calendar time zone",
            "DD-113-calendar",
        ),
        period_closure=_text(
            fact.period_closure,
            "period-closure policy",
            "DD-113-calendar",
        ),
        role_playing_dates=_texts(
            fact.role_playing_dates,
            "role-playing date bindings",
            "DD-113-calendar",
        ),
        approval_status=approval_status,
    )


def _normalize_security(fact: SecurityFact) -> SecurityPolicySpec:
    fail_closed = _bool(
        fact.fail_closed,
        "security fail-closed flag",
        "DD-113-security",
    )
    if not fail_closed.value:
        raise PolicyNormalizationError(
            "security.not-fail-closed",
            "RLS/OLS security policy must set failClosed true",
            rule_id="DD-113-security",
            resource_uri=fact.resource_uri,
        )
    result = SecurityPolicySpec(
        resource_uri=fact.resource_uri,
        entitlement_source=_text(
            fact.entitlement_source,
            "security entitlement source",
            "DD-113-security",
        ),
        identity_mapping=_text(
            fact.identity_mapping,
            "security identity mapping",
            "DD-113-security",
        ),
        role_policies=_texts(
            fact.role_policies,
            "security role policies",
            "DD-113-security",
        ),
        filter_direction=_text(
            fact.filter_direction,
            "security filter direction",
            "DD-113-security",
        ),
        bindings=_texts(
            fact.bindings,
            "security bindings",
            "DD-113-security",
        ),
        positive_tests=_texts(
            fact.positive_tests,
            "positive security tests",
            "DD-113-security",
        ),
        negative_tests=_texts(
            fact.negative_tests,
            "negative security tests",
            "DD-113-security",
        ),
        test_evidence=_texts(
            fact.test_evidence,
            "security test evidence",
            "DD-113-security",
        ),
        fail_closed=fail_closed,
    )
    if not result.test_evidence.value:
        raise PolicyNormalizationError(
            "security.test-evidence-missing",
            "security policy requires positive/negative test evidence",
            rule_id="DD-113-security",
            resource_uri=fact.resource_uri,
        )
    return result


def _one_linked(
    refs: AuthoredValuesFact | None,
    resources: tuple,
    label: str,
) -> object | None:
    if refs is None:
        return None
    reference = _single(refs, label, "DD-113-gold-profile")
    matches = tuple(item for item in resources if item.resource_uri == reference)
    if len(matches) != 1:
        raise _error(
            "gold.unresolved-resource",
            f"{label} {reference!r} does not resolve exactly once",
            refs,
            "DD-113-gold-profile",
        )
    return matches[0]


def _normalize_gold_table(
    fact: GoldTablePolicyFact,
    incremental: dict[str, IncrementalPolicySpec],
) -> GoldTablePolicySpec:
    role = _enum(
        fact.role,
        GoldTableRole,
        "Gold table role",
        "DD-112-table-role",
    )
    if fact.source_model is None or fact.source_version is None:
        raise PolicyNormalizationError(
            "gold.source-binding-missing",
            "every Gold table requires goldSourceModel and goldSourceVersion",
            rule_id="DD-112-silver-binding",
            resource_uri=fact.resource_uri,
        )
    source_model = _text(
        fact.source_model,
        "Gold source model",
        "DD-112-silver-binding",
    )
    source_version = _text(
        fact.source_version,
        "Gold source model version",
        "DD-112-silver-binding",
    )
    local_name = re.split(r"[/#]", fact.resource_uri.rstrip("/#"))[-1]
    prefix = {
        GoldTableRole.FACT: "fact",
        GoldTableRole.DIMENSION: "dim",
        GoldTableRole.BRIDGE: "bridge",
    }[role.value]
    table_name = (
        _text(fact.table_name, "Gold table name", "DD-112-table-role")
        if fact.table_name is not None
        else _default(
            f"{prefix}_{camel_to_snake(local_name)}",
            "DD-112-table-role",
            "Deterministic profile naming rule.",
        )
    )
    if role.value is GoldTableRole.FACT:
        if fact.fact_grain is None or fact.fact_type is None:
            raise PolicyNormalizationError(
                "gold.incomplete-fact",
                "fact requires factGrain and factType",
                rule_id="DD-112-fact",
                resource_uri=fact.resource_uri,
            )
        if fact.version_binding is None:
            raise PolicyNormalizationError(
                "gold.incomplete-fact-runtime",
                "fact requires dimensionVersionBinding",
                rule_id="DD-112-fact",
                resource_uri=fact.resource_uri,
            )
        incremental_ref = None
        correction = (
            _enum(
                fact.correction,
                CorrectionAction,
                "Gold fact correction policy",
                "DD-112-fact",
            )
            if fact.correction is not None
            else None
        )
        late_arrival = (
            _enum(
                fact.late_arrival,
                LateArrivalAction,
                "Gold fact late-arrival policy",
                "DD-112-fact",
            )
            if fact.late_arrival is not None
            else None
        )
        return GoldTablePolicySpec(
            resource_uri=fact.resource_uri,
            role=role,
            table_name=table_name,
            source_model=source_model,
            source_version=source_version,
            fact_grain=_text(
                fact.fact_grain,
                "fact grain",
                "DD-112-fact",
            ),
            fact_type=_enum(
                fact.fact_type,
                FactType,
                "fact type",
                "DD-112-fact",
            ),
            dimension_exposure=None,
            version_binding=_enum(
                fact.version_binding,
                DimensionVersionBinding,
                "dimension-version binding",
                "DD-112-fact",
            ),
            incremental_policy_ref=incremental_ref,
            correction=correction,
            late_arrival=late_arrival,
            bridge_grain=None,
            bridge_endpoints=None,
            bridge_endpoint_bindings=None,
            bridge_cardinality=None,
            bridge_weight_column=None,
            bridge_allocation=None,
        )
    if role.value is GoldTableRole.DIMENSION:
        if fact.dimension_exposure is None or fact.version_binding is None:
            raise PolicyNormalizationError(
                "gold.dimension-exposure-missing",
                "dimension requires dimensionExposure and dimensionVersionBinding",
                rule_id="DD-112-dimension",
                resource_uri=fact.resource_uri,
            )
        if any(
            (
                fact.fact_grain,
                fact.fact_type,
                fact.bridge_grain,
                fact.bridge_endpoints,
                fact.bridge_endpoint_bindings,
                fact.bridge_cardinality,
                fact.bridge_weight_column,
                fact.bridge_allocation,
            )
        ):
            raise PolicyNormalizationError(
                "gold.dimension-with-fact-policy",
                "dimension cannot declare fact-only grain/type/version policy",
                rule_id="DD-112-table-role",
                resource_uri=fact.resource_uri,
            )
        return GoldTablePolicySpec(
            resource_uri=fact.resource_uri,
            role=role,
            table_name=table_name,
            source_model=source_model,
            source_version=source_version,
            fact_grain=None,
            fact_type=None,
            dimension_exposure=_enum(
                fact.dimension_exposure,
                DimensionExposure,
                "dimension exposure",
                "DD-112-dimension",
            ),
            version_binding=_enum(
                fact.version_binding,
                DimensionVersionBinding,
                "dimension source-version binding",
                "DD-112-dimension",
            ),
            incremental_policy_ref=None,
            correction=None,
            late_arrival=None,
            bridge_grain=None,
            bridge_endpoints=None,
            bridge_endpoint_bindings=None,
            bridge_cardinality=None,
            bridge_weight_column=None,
            bridge_allocation=None,
        )
    if any(
        (
            fact.fact_grain,
            fact.fact_type,
            fact.dimension_exposure,
            fact.version_binding,
        )
    ):
        raise PolicyNormalizationError(
            "gold.bridge-with-fact-dimension-policy",
            "bridge cannot declare fact or dimension-only policy",
            rule_id="DD-112-table-role",
            resource_uri=fact.resource_uri,
        )
    if (
        fact.bridge_grain is None
        or fact.bridge_endpoints is None
        or fact.bridge_endpoint_bindings is None
        or fact.bridge_cardinality is None
        or fact.bridge_allocation is None
    ):
        raise PolicyNormalizationError(
            "gold.incomplete-bridge",
            (
                "bridge requires bridgeGrain, exactly two bridgeEndpoint and "
                "bridgeEndpointBinding values, bridgeCardinality, and "
                "bridgeAllocationSemantics"
            ),
            rule_id="DD-112-bridge",
            resource_uri=fact.resource_uri,
        )
    endpoints = _texts(
        fact.bridge_endpoints,
        "bridge endpoints",
        "DD-112-bridge",
    )
    if len(endpoints.value) != 2 or endpoints.value[0] == endpoints.value[1]:
        raise PolicyNormalizationError(
            "gold.invalid-bridge-endpoints",
            "bridge requires exactly two distinct endpoints",
            rule_id="DD-112-bridge",
            resource_uri=fact.resource_uri,
        )
    endpoint_bindings = _texts(
        fact.bridge_endpoint_bindings,
        "bridge endpoint bindings",
        "DD-112-bridge",
    )
    if len(endpoint_bindings.value) != 2:
        raise PolicyNormalizationError(
            "gold.invalid-bridge-endpoint-bindings",
            "bridge requires exactly two endpoint-column bindings",
            rule_id="DD-112-bridge",
            resource_uri=fact.resource_uri,
        )
    return GoldTablePolicySpec(
        resource_uri=fact.resource_uri,
        role=role,
        table_name=table_name,
        source_model=source_model,
        source_version=source_version,
        fact_grain=None,
        fact_type=None,
        dimension_exposure=None,
        version_binding=None,
        incremental_policy_ref=None,
        correction=None,
        late_arrival=None,
        bridge_grain=_text(
            fact.bridge_grain,
            "bridge grain",
            "DD-112-bridge",
        ),
        bridge_endpoints=EffectiveValue(
            (endpoints.value[0], endpoints.value[1]),
            endpoints.provenance,
        ),
        bridge_endpoint_bindings=EffectiveValue(
            (endpoint_bindings.value[0], endpoint_bindings.value[1]),
            endpoint_bindings.provenance,
        ),
        bridge_cardinality=_enum(
            fact.bridge_cardinality,
            BridgeCardinality,
            "bridge cardinality",
            "DD-112-bridge",
        ),
        bridge_weight_column=(
            _text(
                fact.bridge_weight_column,
                "bridge weight column",
                "DD-112-bridge",
            )
            if fact.bridge_weight_column is not None
            else None
        ),
        bridge_allocation=_text(
            fact.bridge_allocation,
            "bridge allocation semantics",
            "DD-112-bridge",
        ),
    )


def _normalize_gold(
    fact: GoldProductFact,
    incremental: tuple[IncrementalPolicySpec, ...],
    issues: list[PolicyIssue],
) -> GoldProductSpec:
    profile = (
        _enum(
            fact.profile,
            GoldProfileName,
            "Gold product profile",
            "DD-112-profile",
        )
        if fact.profile is not None
        else None
    )
    if profile is not None:
        _gold_registry().get(profile.value)
        if fact.schema is None:
            raise PolicyNormalizationError(
                "gold.schema-missing",
                "Gold profile requires an explicit goldSchema",
                rule_id="DD-112-profile",
                resource_uri=fact.ontology_uri,
            )
    if profile is None and (
        fact.tables or fact.measures or fact.calendars or fact.security_policies
    ):
        issues.append(
            PolicyIssue(
                code="gold.profile-missing",
                message="Gold policy resources exist without goldProductProfile.",
                rule_id="DD-112-profile",
                resource_uri=fact.ontology_uri,
            )
        )

    incremental_index = {item.resource_uri: item for item in incremental}
    tables = tuple(_normalize_gold_table(item, incremental_index) for item in fact.tables)
    measures = _normalize_measures(fact.measures)
    linked_measure_refs = (
        frozenset(
            _many(
                fact.measure_refs,
                "Gold measure references",
                "DD-113-measure",
            )
        )
        if fact.measure_refs is not None
        else frozenset()
    )
    unlinked_measures = tuple(
        item.resource_uri for item in fact.measures if item.resource_uri not in linked_measure_refs
    )
    if profile is not None and unlinked_measures:
        raise PolicyNormalizationError(
            "gold.unlinked-measure",
            f"Gold measures are not linked from the product: {unlinked_measures!r}",
            rule_id="DD-113-measure",
            resource_uri=fact.ontology_uri,
        )

    calendar_fact = _one_linked(
        fact.calendar_refs,
        fact.calendars,
        "calendar profile",
    )
    security_fact = _one_linked(
        fact.security_refs,
        fact.security_policies,
        "security policy",
    )
    perspectives: dict[str, list[str]] = {}
    for table in fact.tables:
        if table.perspectives is None:
            continue
        for value in table.perspectives.values:
            for name in value.split():
                perspectives.setdefault(name, []).append(table.resource_uri)
    return GoldProductSpec(
        profile=profile,
        schema=(
            _text(fact.schema, "Gold schema", "DD-112-profile") if fact.schema is not None else None
        ),
        tables=tables,
        measures=measures,
        calendar=(
            _normalize_calendar(calendar_fact) if isinstance(calendar_fact, CalendarFact) else None
        ),
        security=(
            _normalize_security(security_fact) if isinstance(security_fact, SecurityFact) else None
        ),
        perspectives=tuple(
            PerspectiveSpec(name, tuple(sorted(set(resources))))
            for name, resources in sorted(perspectives.items())
        ),
    )


def _capability_requirements(
    hashes: tuple[CanonicalHashPolicySpec, ...],
    incremental: tuple[IncrementalPolicySpec, ...],
    temporal: tuple[TemporalRelationshipSpec, ...],
    multi_source: tuple[MultiSourcePolicySpec, ...],
    identity_facts: tuple[EntityIdentityFact, ...],
    quality: tuple[DataQualityRuleSpec, ...],
    gold: GoldProductSpec,
    *,
    has_foreign_keys: bool,
    has_contracted_dbt_source: bool,
) -> tuple[CapabilityRequirementSpec, ...]:
    required: set[tuple[AdapterCapability, str, str]] = {
        (AdapterCapability.CANONICAL_TYPES, "project", "DD-111-types")
    }
    if hashes:
        required.add(
            (
                AdapterCapability.CANONICAL_SHA256_HASH,
                "project",
                "DD-109-hash",
            )
        )
    if incremental:
        required.add((AdapterCapability.MERGE_UPSERT, "project", "DD-109-merge"))
        required.add((AdapterCapability.DELETE_SEMANTICS, "project", "DD-109-delete"))
        required.add((AdapterCapability.WINDOW_FUNCTIONS, "project", "DD-109-total-order"))
        required.add((AdapterCapability.TOTAL_ORDERING, "project", "DD-109-total-order"))
    if any(
        fact.scd_type is not None and fact.scd_type.values == (ScdType.TYPE_1.value,)
        for fact in identity_facts
    ):
        required.add((AdapterCapability.INCREMENTAL_SCD1, "silver", "DD-133-stage2-scd1"))
    if any(
        fact.scd_type is not None and fact.scd_type.values == (ScdType.TYPE_2.value,)
        for fact in identity_facts
    ):
        required.add((AdapterCapability.INCREMENTAL_SCD2, "silver", "DD-133-stage2-scd2"))
    if any(
        item.schema_evolution.action.value is SchemaEvolutionAction.FAIL for item in incremental
    ):
        required.add(
            (
                AdapterCapability.SCHEMA_EVOLUTION_FAIL,
                "project",
                "DD-109-schema-change",
            )
        )
    if any(
        item.schema_evolution.action.value is SchemaEvolutionAction.APPROVED_CONTRACT_UPDATE
        for item in incremental
    ):
        required.add(
            (
                AdapterCapability.SCHEMA_EVOLUTION_APPEND_COMPATIBLE,
                "project",
                "DD-109-schema-change",
            )
        )
    if temporal or has_foreign_keys:
        required.add((AdapterCapability.TEMPORAL_LOOKUP, "silver", "DD-109-temporal-fk"))
        required.add((AdapterCapability.CONSTRAINTS, "silver", "DD-110-constraints"))
    if any(item.mode.value is TemporalMode.CURRENT for item in temporal):
        required.add(
            (
                AdapterCapability.TEMPORAL_FK_CURRENT,
                "silver",
                "DD-109-temporal-fk",
            )
        )
    if any(item.mode.value is TemporalMode.AS_OF for item in temporal):
        required.add(
            (
                AdapterCapability.TEMPORAL_FK_AS_OF,
                "silver",
                "DD-109-temporal-fk",
            )
        )
    if any(
        item.relationship.value is BranchRelationship.EXACTLY_EQUIVALENT for item in multi_source
    ):
        required.add(
            (
                AdapterCapability.CONFORMANCE_DEDUPLICATE,
                "silver",
                "DD-133-stage2-conformance",
            )
        )
    elif multi_source:
        required.add(
            (
                AdapterCapability.CONFORMANCE_UNION_ALL,
                "silver",
                "DD-133-stage2-conformance",
            )
        )
    if has_contracted_dbt_source:
        required.add(
            (
                AdapterCapability.CONTRACTED_DBT_SOURCE,
                "source",
                "DD-133-stage2-contracted-source",
            )
        )
    if any(item.action.value in {DqAction.QUARANTINE, DqAction.BLOCK} for item in quality):
        required.add((AdapterCapability.QUARANTINE, "quality", "DD-115-quarantine"))
    if quality:
        required.add((AdapterCapability.DBT_TESTS, "quality", "DD-115-tests"))
    if gold.profile is not None:
        required.add((AdapterCapability.PHYSICAL_LAYOUT, "gold", "DD-111-layout"))
        required.add((AdapterCapability.TMDL, "gold", "DD-113-tmdl"))
    if gold.security is not None:
        required.add((AdapterCapability.SECURITY_RLS_OLS, "gold", "DD-113-security"))
    return tuple(
        CapabilityRequirementSpec(capability, scope, rule_id)
        for capability, scope, rule_id in sorted(
            required,
            key=lambda item: (item[0].value, item[1], item[2]),
        )
    )


def _history(
    identity_fact: EntityIdentityFact | None,
    incremental: dict[str, IncrementalPolicySpec],
) -> HistorySpec | None:
    if identity_fact is None or identity_fact.scd_type is None:
        return None
    scd = _enum(
        identity_fact.scd_type,
        ScdType,
        "SCD type",
        "DD-109-scd",
    )
    time_basis = (
        _enum(
            identity_fact.scd2_time_basis,
            Scd2TimeBasis,
            "SCD2 time basis",
            "DD-109-scd",
        )
        if identity_fact.scd2_time_basis is not None
        else None
    )
    if scd.value is ScdType.TYPE_2 and time_basis is None:
        raise PolicyNormalizationError(
            "history.scd2-time-basis-missing",
            "SCD2 requires business-valid or load-history time basis",
            rule_id="DD-109-scd",
            resource_uri=identity_fact.resource_uri,
        )
    if scd.value is ScdType.TYPE_1 and time_basis is not None:
        raise PolicyNormalizationError(
            "history.scd1-with-time-basis",
            "scd2TimeBasis cannot be declared for SCD type 1",
            rule_id="DD-109-scd",
            resource_uri=identity_fact.resource_uri,
        )
    incremental_ref = _optional_single(
        identity_fact.incremental_policy_refs,
        "incremental policy reference",
        "DD-109-incremental",
    )
    if incremental_ref is None:
        raise PolicyNormalizationError(
            "history.incremental-policy-missing",
            "authored SCD1/SCD2 behavior requires a complete incremental policy",
            rule_id="DD-109-incremental",
            resource_uri=identity_fact.resource_uri,
        )
    runtime = incremental.get(incremental_ref)
    if runtime is None:
        raise PolicyNormalizationError(
            "history.incremental-policy-unknown",
            f"incremental policy {incremental_ref!r} is not declared",
            rule_id="DD-109-incremental",
            resource_uri=identity_fact.resource_uri,
        )
    if (
        scd.value is ScdType.TYPE_2
        and runtime.correction.value is CorrectionAction.APPEND_CORRECTION
    ):
        raise PolicyNormalizationError(
            "history.scd2-append-correction-unsupported",
            (
                "DD-109 SCD2 correctionPolicy 'append-correction' is unsupported: "
                "use 'replace-by-total-order' or 'revise-valid-time'; generated SQL "
                "must not silently apply replacement semantics"
            ),
            rule_id="DD-109-correction",
            resource_uri=identity_fact.resource_uri,
        )
    if runtime.hard_delete.value not in {DeleteAction.TOMBSTONE, DeleteAction.IGNORE}:
        raise PolicyNormalizationError(
            "history.hard-delete-action-unsupported",
            (
                "DD-109 hardDeletePolicy applies only to captured CDC operation='delete'. "
                "Generated runtime supports 'tombstone' or 'ignore'; physical/absence-based "
                "snapshot deletion and external quarantine are not implemented"
            ),
            rule_id="DD-109-delete",
            resource_uri=identity_fact.resource_uri,
        )
    if runtime.soft_delete.value not in {
        DeleteAction.TOMBSTONE,
        DeleteAction.IGNORE,
        DeleteAction.APPLY_OPERATION,
    }:
        raise PolicyNormalizationError(
            "history.soft-delete-action-unsupported",
            (
                "DD-109 softDeletePolicy applies only to normalized "
                "operation='soft-delete'. Use 'apply-operation', 'tombstone', or 'ignore'; "
                "block/quarantine require a runtime artifact not currently generated"
            ),
            rule_id="DD-109-delete",
            resource_uri=identity_fact.resource_uri,
        )
    return HistorySpec(
        scd_type=scd,
        time_basis=time_basis,
        business_valid_from_column="_business_valid_from",
        business_valid_to_column="_business_valid_to",
        system_from_column="_system_from",
        system_to_column="_system_to",
        current_flag_column="is_current",
        deleted_flag_column="_is_deleted",
        correction=runtime.correction,
    )


def _column_role(name: str, fk_names: frozenset[str]) -> SilverColumnRole:
    if name == "_source_record_key":
        return SilverColumnRole.SOURCE_IDENTITY
    if name in {"_loaded_at", "_ingested_at", "_source_updated_at", "_source_effective_at"}:
        return SilverColumnRole.AUDIT
    if name in {
        "_business_valid_from",
        "_business_valid_to",
        "_system_from",
        "_system_to",
        "is_current",
        "_is_deleted",
        "_row_hash",
    }:
        return SilverColumnRole.HISTORY
    if name in fk_names:
        return SilverColumnRole.FOREIGN_KEY
    if name.endswith("_sk"):
        return SilverColumnRole.SURROGATE_JOIN_KEY
    if name == "iri" or name.endswith("_iri"):
        return SilverColumnRole.ENTITY_IRI
    return SilverColumnRole.BUSINESS


def _validate_identity_columns(
    candidate: BoundSilverModel,
    identity: EntityIdentitySpec | None,
) -> None:
    """Require authored identity columns to be materially supplied, never inferred."""
    if (
        identity is None
        or not identity.business.keys.value
        or candidate.identity.outcome is not ModelOutcome.GENERATED
    ):
        return
    columns = {column.name: column for column in candidate.columns}
    missing = tuple(
        key
        for key in identity.business.keys.value
        if key not in columns or _NULL_EXPRESSION.match(columns[key].expression or "")
    )
    if missing:
        raise PolicyNormalizationError(
            "identity.authored-key-not-supplied",
            (
                "authored naturalKey identity OUTPUT column(s) must be explicitly materialized "
                f"as mapped fields on {candidate.identity.model_name!r}; missing output "
                f"column(s): {', '.join(missing)}. Each naturalKey component must correspond to "
                "a field whose target property emits that output column"
            ),
            rule_id="DD-108-business-identity",
            resource_uri=identity.entity_uri,
        )


def _identity_roles(
    identity: EntityIdentitySpec | None,
    model_name: str,
) -> tuple[IdentityRoleSpec, ...]:
    if identity is None:
        return ()
    provenance = identity.strategy.provenance
    roles = [
        IdentityRoleSpec(
            role=SilverColumnRole.SOURCE_IDENTITY,
            columns=("_source_system", "_source_identity_ref", "_source_record_key"),
            emitted=True,
            establishes_business_identity=False,
            key_scope=(
                KeyScope.SOURCE_TABLE_ARRAY_ELEMENT
                if identity.key_scope.value is KeyScope.SOURCE_TABLE_ARRAY_ELEMENT
                else KeyScope.SOURCE_TABLE
            ),
            provenance=identity.source.record_key_refs.provenance,
        ),
        IdentityRoleSpec(
            role=SilverColumnRole.BUSINESS_NATURAL_KEY,
            columns=identity.business.keys.value,
            emitted=bool(identity.business.keys.value),
            establishes_business_identity=identity.business.authoritative,
            key_scope=identity.key_scope.value,
            provenance=identity.business.keys.provenance,
        ),
        IdentityRoleSpec(
            role=SilverColumnRole.INTEGRATION_IDENTITY,
            columns=((f"{model_name}_integration_key",) if identity.integration.emitted else ()),
            emitted=identity.integration.emitted,
            establishes_business_identity=identity.integration.emitted,
            key_scope=identity.key_scope.value,
            provenance=provenance,
        ),
        IdentityRoleSpec(
            role=SilverColumnRole.MASTERED_IDENTIFIER,
            columns=(identity.business.keys.value if identity.mastered.routed_to_mdm else ()),
            emitted=identity.mastered.routed_to_mdm,
            establishes_business_identity=identity.mastered.routed_to_mdm,
            key_scope=identity.key_scope.value,
            provenance=provenance,
        ),
        IdentityRoleSpec(
            role=SilverColumnRole.SURROGATE_JOIN_KEY,
            columns=(f"{model_name}_sk",),
            emitted=identity.surrogate.emitted_as_join_key,
            establishes_business_identity=False,
            key_scope=identity.key_scope.value,
            provenance=provenance,
        ),
        IdentityRoleSpec(
            role=SilverColumnRole.ENTITY_IRI,
            columns=(
                (f"{model_name}_iri",) if identity.iri.mode.value is EntityIriMode.EMIT else ()
            ),
            emitted=identity.iri.mode.value is EntityIriMode.EMIT,
            establishes_business_identity=False,
            key_scope=identity.key_scope.value,
            provenance=identity.iri.mode.provenance,
        ),
    ]
    return tuple(roles)


def _identity_column_nullable(
    role: SilverColumnRole,
    identity: EntityIdentitySpec | None,
) -> bool:
    if role in {
        SilverColumnRole.SOURCE_IDENTITY,
        SilverColumnRole.INTEGRATION_IDENTITY,
        SilverColumnRole.MASTERED_IDENTIFIER,
        SilverColumnRole.SURROGATE_JOIN_KEY,
        SilverColumnRole.ENTITY_IRI,
    }:
        return False
    return not (
        role is SilverColumnRole.BUSINESS_NATURAL_KEY
        and identity is not None
        and identity.strategy.value
        in {
            IdentityStrategy.BUSINESS_KEY,
            IdentityStrategy.DETERMINISTIC_INTEGRATION_KEY,
            IdentityStrategy.EXTERNALLY_MASTERED_IDENTIFIER,
        }
    )


def _resolve_quality_scopes(
    quality: tuple[DataQualityRuleSpec, ...],
    candidates: tuple[BoundSilverModel, ...],
    systems: tuple[SourceSystemFact, ...],
    mappings: SourceMappings,
    fk_policy: ForeignKeyPolicy,
) -> dict[str, str]:
    candidate_classes = {
        candidate.identity.class_uri: candidate.identity.class_uri for candidate in candidates
    }
    candidate_classes.update(
        {candidate.identity.model_name: candidate.identity.class_uri for candidate in candidates}
    )
    table_targets: dict[str, set[str]] = {}
    for mapping in mappings.tables:
        if mapping.target_class_uri in candidate_classes:
            table_targets.setdefault(mapping.source_table_uri, set()).add(mapping.target_class_uri)
    source_column_tables = {
        column.uri: table.uri
        for system in systems
        for table in system.tables
        for column in table.columns
    }
    property_targets: dict[str, set[str]] = {}
    for mapping in mappings.columns:
        table_uri = source_column_tables.get(mapping.source_column_uri)
        if table_uri is None:
            continue
        property_targets.setdefault(mapping.target_property_uri, set()).update(
            table_targets.get(table_uri, ())
        )
    for descriptor in fk_policy.descriptors:
        property_targets.setdefault(descriptor.property_uri, set()).add(descriptor.source_class)

    resolved: dict[str, str] = {}
    valid_classes = set(candidate_classes.values())
    for rule in quality:
        scope = rule.scope.value
        governing = rule.governing_entity_uri
        targets = set()
        direct = candidate_classes.get(scope)
        if direct is not None:
            targets.add(direct)
        targets.update(table_targets.get(scope, ()))
        targets.update(property_targets.get(scope, ()))
        targets.intersection_update(valid_classes)
        if governing and governing in valid_classes:
            if direct is not None and direct != governing:
                raise PolicyNormalizationError(
                    "dq.scope-owner-conflict",
                    (
                        f"DQ rule {rule.rule_id.value!r} scope {scope!r} names a different "
                        f"entity than its governing class {governing!r}"
                    ),
                    rule_id="DD-115-dq-scope",
                    resource_uri=rule.resource_uri,
                )
            if governing in targets or not targets:
                targets = {governing}
        if len(targets) != 1:
            qualifier = "does not resolve" if not targets else "is ambiguous"
            raise PolicyNormalizationError(
                "dq.unrenderable-scope",
                (
                    f"DQ rule {rule.rule_id.value!r} scope {scope!r} {qualifier} "
                    "to exactly one generated Silver model"
                ),
                rule_id="DD-115-dq-scope",
                resource_uri=rule.resource_uri,
            )
        resolved[rule.resource_uri] = next(iter(targets))
    return resolved


def _silver_foreign_key_policy(
    fk_policy: ForeignKeyPolicy,
    candidates: tuple[BoundSilverModel, ...],
) -> ForeignKeyPolicy:
    """Derive the qualified FK view used only by Silver policy normalization."""
    materialized_classes = {
        candidate.identity.class_uri
        for candidate in candidates
        if candidate.identity.class_uri and candidate.identity.outcome is ModelOutcome.GENERATED
    }
    descriptors = []
    for descriptor in fk_policy.descriptors:
        applicable_classes = descriptor.silver_applicable_classes or (
            frozenset({descriptor.source_class})
            if (
                descriptor.redirected
                or descriptor.silver_foreign_key
                or descriptor.silver_column_name is not None
                or descriptor.is_functional
            )
            else descriptor.max_cardinality_classes
        )
        descriptors.extend(
            replace(descriptor, source_class=class_uri)
            for class_uri in sorted(applicable_classes & materialized_classes)
        )
    return ForeignKeyPolicy(
        descriptors=tuple(descriptors),
        diagnostics=fk_policy.diagnostics,
        outgoing_relationship_sources=tuple(
            sorted({descriptor.source_class for descriptor in descriptors})
        ),
    )


def _silver_authorities(
    candidates: tuple[BoundSilverModel, ...],
    identities: tuple[EntityIdentitySpec, ...],
    identity_facts: tuple[EntityIdentityFact, ...],
    multi_source: tuple[MultiSourcePolicySpec, ...],
    incremental: tuple[IncrementalPolicySpec, ...],
    hashes: tuple[CanonicalHashPolicySpec, ...],
    temporal: tuple[TemporalRelationshipSpec, ...],
    quality: tuple[DataQualityRuleSpec, ...],
    fk_policy: ForeignKeyPolicy,
    requirements: tuple[CapabilityRequirementSpec, ...],
    deviations: tuple[ApprovedDeviationSpec, ...],
    quality_scope_targets: dict[str, str],
) -> tuple[SilverModelAuthoritySpec, ...]:
    identity_by_uri = {item.entity_uri: item for item in identities}
    multi_source_by_uri = {item.resource_uri: item for item in multi_source}
    identity_fact_by_uri = {item.resource_uri: item for item in identity_facts}
    incremental_by_uri = {item.resource_uri: item for item in incremental}
    hash_by_uri = {item.resource_uri: item for item in hashes}
    temporal_by_property = {item.property_uri: item for item in temporal}
    history_by_class = {
        class_uri: history
        for class_uri, fact in identity_fact_by_uri.items()
        if (history := _history(fact, incremental_by_uri)) is not None
    }
    descriptors_by_class: dict[str, list] = {}
    for descriptor in fk_policy.descriptors:
        descriptors_by_class.setdefault(descriptor.source_class, []).append(descriptor)

    result: list[SilverModelAuthoritySpec] = []
    for candidate in candidates:
        class_uri = candidate.identity.class_uri
        descriptors = descriptors_by_class.get(class_uri, [])
        fk_names = frozenset(
            item.silver_column_name for item in descriptors if item.silver_column_name is not None
        )
        foreign_keys = tuple(
            temporal_by_property[item.property_uri]
            for item in sorted(descriptors, key=lambda value: value.property_uri)
            if item.property_uri in temporal_by_property
        )
        missing_temporal = sorted(
            item.property_uri
            for item in descriptors
            if item.property_uri not in temporal_by_property
        )
        identity = identity_by_uri.get(class_uri)
        if identity is not None and missing_temporal:
            raise PolicyNormalizationError(
                "temporal-fk.policy-missing",
                (
                    "every materialized Silver FK requires an explicit DD-109 temporal "
                    f"policy: {', '.join(missing_temporal)}"
                ),
                rule_id="DD-109-temporal-fk",
                resource_uri=class_uri,
            )
        _validate_identity_columns(candidate, identity)
        timestamps = identity.lineage.timestamps if identity else _timestamp_semantics()
        history = history_by_class.get(class_uri)
        runtime_authority = None
        if history is not None:
            if identity is None or identity.incremental_policy_ref is None:
                raise PolicyNormalizationError(
                    "incremental.identity-policy-missing",
                    "SCD runtime requires a normalized identity and incremental policy",
                    rule_id="DD-109-incremental",
                    resource_uri=class_uri,
                )
            runtime = incremental_by_uri[identity.incremental_policy_ref]
            hash_policy = (
                hash_by_uri.get(identity.hash_policy_ref)
                if identity.hash_policy_ref is not None
                else None
            )
            runtime_authority = SilverRuntimeAuthoritySpec(
                incremental=runtime,
                history=history,
                change_detection=identity.change_detection,
                canonical_hash=hash_policy,
            )
        for descriptor in descriptors:
            relationship = temporal_by_property.get(descriptor.property_uri)
            if relationship is None:
                continue
            parent_history = history_by_class.get(descriptor.target_class)
            if (
                relationship.mode.value is TemporalMode.NONE
                and parent_history is not None
                and parent_history.scd_type.value is ScdType.TYPE_2
            ):
                raise PolicyNormalizationError(
                    "temporal-fk.none-targets-history",
                    "temporal mode none cannot target an SCD history relation",
                    rule_id="DD-109-temporal-fk",
                    resource_uri=descriptor.property_uri,
                )
            if relationship.mode.value is not TemporalMode.NONE:
                if parent_history is None or parent_history.scd_type.value is not ScdType.TYPE_2:
                    raise PolicyNormalizationError(
                        "temporal-fk.history-target-required",
                        "current/as-of FK lookup requires an SCD2 parent",
                        rule_id="DD-109-temporal-fk",
                        resource_uri=descriptor.property_uri,
                    )
            if relationship.mode.value is TemporalMode.AS_OF and (
                parent_history is None
                or parent_history.time_basis is None
                or parent_history.time_basis.value is not Scd2TimeBasis.BUSINESS_VALID
            ):
                raise PolicyNormalizationError(
                    "temporal-fk.business-valid-parent-required",
                    "as-of FK lookup requires business-valid SCD2 parent history",
                    rule_id="DD-109-temporal-fk",
                    resource_uri=descriptor.property_uri,
                )
            if (
                relationship.late_parent_action.value is ParentAction.RESTATE
                and runtime_authority is None
            ):
                raise PolicyNormalizationError(
                    "temporal-fk.restatement-requires-runtime",
                    "late-parent restatement requires bounded incremental replay",
                    rule_id="DD-109-temporal-fk",
                    resource_uri=descriptor.property_uri,
                )
        all_identity_roles = _identity_roles(identity, candidate.identity.model_name)
        is_final_entity = candidate.kind in {
            SilverModelKind.ENTITY,
            SilverModelKind.UNION,
        }
        identity_roles = (
            all_identity_roles
            if is_final_entity
            else tuple(
                role for role in all_identity_roles if role.role is SilverColumnRole.SOURCE_IDENTITY
            )
        )
        role_by_column = {column: role.role for role in identity_roles for column in role.columns}
        logical_columns = list(candidate.columns)
        logical_column_names = {column.name for column in logical_columns}
        if is_final_entity or candidate.kind is SilverModelKind.SOURCE_BRANCH:
            for role in identity_roles:
                if not role.emitted:
                    continue
                for column_name in role.columns:
                    if column_name not in logical_column_names:
                        logical_columns.append(
                            ColumnSpec(
                                name=column_name,
                                data_type="STRING",
                                description=f"DD-108 {role.role.value}",
                            )
                        )
                        logical_column_names.add(column_name)
            for timestamp in timestamps:
                if (
                    timestamp.supplied
                    and timestamp.column_name not in logical_column_names
                    and not (
                        candidate.kind is SilverModelKind.SOURCE_BRANCH
                        and timestamp.role is TimestampRole.LOADED_AT
                    )
                ):
                    logical_columns.append(
                        ColumnSpec(
                            name=timestamp.column_name,
                            data_type="TIMESTAMP",
                            description=f"DD-108 {timestamp.role.value}",
                        )
                    )
                    logical_column_names.add(timestamp.column_name)
            if is_final_entity and runtime_authority is not None:
                history_columns = [
                    ColumnSpec(
                        name=runtime_authority.history.deleted_flag_column,
                        data_type="BOOLEAN",
                        description="DD-109 explicit delete/tombstone state",
                        include_in_change_detection=False,
                    )
                ]
                if runtime_authority.canonical_hash is not None:
                    history_columns.append(
                        ColumnSpec(
                            name="_row_hash",
                            data_type="STRING",
                            description="DD-109 canonical SHA-256 hash v1",
                            include_in_change_detection=False,
                        )
                    )
                if runtime_authority.history.scd_type.value is ScdType.TYPE_2:
                    history_columns.extend(
                        (
                            ColumnSpec(
                                name=(runtime_authority.history.business_valid_from_column),
                                data_type="TIMESTAMP",
                                description="Inclusive business-valid interval start",
                                include_in_change_detection=False,
                            ),
                            ColumnSpec(
                                name=(runtime_authority.history.business_valid_to_column),
                                data_type="TIMESTAMP",
                                description="Exclusive business-valid interval end",
                                include_in_change_detection=False,
                            ),
                            ColumnSpec(
                                name=runtime_authority.history.system_from_column,
                                data_type="TIMESTAMP",
                                description="Inclusive system/load interval start",
                                include_in_change_detection=False,
                            ),
                            ColumnSpec(
                                name=runtime_authority.history.system_to_column,
                                data_type="TIMESTAMP",
                                description="Exclusive system/load interval end",
                                include_in_change_detection=False,
                            ),
                            ColumnSpec(
                                name=runtime_authority.history.current_flag_column,
                                data_type="BOOLEAN",
                                description="Deterministic current system version",
                                include_in_change_detection=False,
                            ),
                        )
                    )
                for history_column in history_columns:
                    if history_column.name not in logical_column_names:
                        logical_columns.append(history_column)
                        logical_column_names.add(history_column.name)
        multi_source_policy = (
            multi_source_by_uri.get(identity.multi_source_policy_ref)
            if identity is not None and identity.multi_source_policy_ref is not None
            else None
        )
        model_requirements = tuple(
            item.capability for item in requirements if item.scope in {"project", "silver"}
        )
        required_runtime_columns = {"_loaded_at"}
        if runtime_authority is not None:
            required_runtime_columns.add(runtime_authority.history.deleted_flag_column)
            if runtime_authority.canonical_hash is not None:
                required_runtime_columns.add("_row_hash")
            if runtime_authority.history.scd_type.value is ScdType.TYPE_2:
                required_runtime_columns.update(
                    {
                        runtime_authority.history.system_from_column,
                        runtime_authority.history.current_flag_column,
                    }
                )
                if (
                    runtime_authority.history.time_basis is not None
                    and runtime_authority.history.time_basis.value is Scd2TimeBasis.BUSINESS_VALID
                ):
                    required_runtime_columns.add(
                        runtime_authority.history.business_valid_from_column
                    )
        result.append(
            SilverModelAuthoritySpec(
                identity=candidate.identity,
                columns=tuple(
                    SilverColumnAuthoritySpec(
                        column=column,
                        role=_default(
                            role_by_column.get(
                                column.name,
                                _column_role(column.name, fk_names),
                            ),
                            "DD-110-silver-authority",
                            "Classified from the authoritative Silver column role.",
                        ),
                        nullable=_default(
                            _identity_column_nullable(
                                role_by_column.get(
                                    column.name,
                                    _column_role(column.name, fk_names),
                                ),
                                identity,
                            )
                            and column.name not in required_runtime_columns,
                            "DD-110-silver-authority",
                            "Derived from the normalized Silver column contract.",
                        ),
                    )
                    for column in logical_columns
                ),
                entity_identity=identity,
                audit=AuditPolicySpec(
                    columns=timestamps,
                    source_system_column="_source_system",
                    source_record_key_column="_source_record_key",
                ),
                history=history,
                runtime=runtime_authority,
                foreign_keys=foreign_keys,
                quality_rules=tuple(
                    item
                    for item in quality
                    if quality_scope_targets[item.resource_uri] == class_uri
                ),
                required_capabilities=tuple(sorted(set(model_requirements), key=str)),
                deviation_refs=tuple(
                    item.resource_uri
                    for item in deviations
                    if item.scope.value
                    in {
                        "*",
                        "silver",
                        class_uri,
                        candidate.identity.model_name,
                    }
                ),
                identity_roles=identity_roles,
                multi_source=multi_source_policy,
                contribution_lineage=(
                    ContributionLineageRelationSpec(
                        relation_name=(f"{candidate.identity.model_name}__contributions"),
                        parent_key_column=f"{candidate.identity.model_name}_sk",
                    )
                    if identity is not None
                    and identity.lineage.contribution is not None
                    and identity.lineage.contribution.emits_all_source_records
                    else None
                ),
            )
        )
    return tuple(result)


def _gold_registry() -> GoldProductProfileRegistry:
    return GoldProductProfileRegistry(
        profiles=(
            GoldProductProfileSpec(
                name=GoldProfileName.DIMENSIONAL_POWERBI_V1,
                version="1.0",
                required_capabilities=(
                    AdapterCapability.CANONICAL_TYPES,
                    AdapterCapability.PHYSICAL_LAYOUT,
                    AdapterCapability.TMDL,
                ),
            ),
        )
    )


def _not_evaluated_stage(
    stage: str,
    prerequisite: Prerequisite,
    *,
    code_stage: str | None = None,
) -> EvaluationResult[object]:
    owner = {
        "identity": "kairos-design-silver",
        "runtime": "kairos-design-silver",
        "temporal_fk": "kairos-design-silver",
    }.get(stage, "kairos-execute-validate")
    diagnostic = Diagnostic(
        code=f"{code_stage or stage}.not-evaluated",
        message=f"{stage.replace('_', ' ')} checks require available normalization inputs",
        rule_id="DD-108-prerequisite" if stage == "identity" else "DD-109-prerequisite",
        stage=stage,
        owner_skill=owner,
        blocking=False,
        depends_on=prerequisite.diagnostic_ids,
        evidence=tuple(f"prerequisite:{item}" for item in prerequisite.diagnostic_ids),
        remediation=f"Resolve prerequisite blockers before {owner} reevaluates this stage.",
        evaluation_status=EvaluationStatus.NOT_EVALUATED,
    )
    return EvaluationResult.not_evaluated((prerequisite,), (diagnostic,))


def _collect_identities(
    facts: tuple[EntityIdentityFact, ...],
    multi_source: tuple[MultiSourcePolicySpec, ...],
    hashes: tuple[CanonicalHashPolicySpec, ...],
    incremental: tuple[IncrementalPolicySpec, ...],
    candidates: tuple[BoundSilverModel, ...],
    issues: list[PolicyIssue],
    collector: DiagnosticCollector,
    contracts: tuple[tuple[str, ContractFact], ...] = (),
    incremental_result: EvaluationResult[tuple[IncrementalPolicySpec, ...]] | None = None,
) -> EvaluationResult[tuple[EntityIdentitySpec, ...]]:
    """Normalize each independent DD-108 identity root once."""

    runtime_prerequisite = Prerequisite(
        id="runtime",
        status=(
            incremental_result.status if incremental_result is not None else EvaluationStatus.PASSED
        ),
        diagnostic_ids=tuple(
            item.id
            for item in (incremental_result.diagnostics if incremental_result is not None else ())
        ),
    )
    incremental_refs = {item.resource_uri for item in incremental}
    result: list[EntityIdentitySpec] = []
    skipped_prerequisites: list[Prerequisite] = []
    own_diagnostics: list[Diagnostic] = []
    for fact in sorted(facts, key=lambda item: item.resource_uri):
        authored_incremental_refs = {
            value
            for value in (
                fact.incremental_policy_refs.values
                if fact.incremental_policy_refs is not None
                else ()
            )
            if value
        }
        if not runtime_prerequisite.available and not authored_incremental_refs.issubset(
            incremental_refs
        ):
            skipped_prerequisites.append(runtime_prerequisite)
            continue
        before = set(item.id for item in collector.diagnostics)
        try:
            result.extend(
                _normalize_identities(
                    (fact,),
                    multi_source,
                    hashes,
                    incremental,
                    candidates,
                    issues,
                    contracts,
                )
            )
        except PolicyNormalizationError as exc:
            collector.add(exc.diagnostic)
        own_diagnostics.extend(item for item in collector.diagnostics if item.id not in before)

    if skipped_prerequisites:
        combined = Prerequisite(
            id="+".join(sorted({item.id for item in skipped_prerequisites})),
            status=EvaluationStatus.FAILED,
            diagnostic_ids=tuple(
                sorted(
                    {
                        diagnostic_id
                        for item in skipped_prerequisites
                        for diagnostic_id in item.diagnostic_ids
                    }
                )
            ),
        )
        skipped = _not_evaluated_stage("identity", combined)
        own_diagnostics.extend(skipped.diagnostics)
    status = (
        EvaluationStatus.FAILED
        if any(item.evaluation_status is EvaluationStatus.FAILED for item in own_diagnostics)
        else EvaluationStatus.NOT_EVALUATED if skipped_prerequisites else EvaluationStatus.PASSED
    )
    return EvaluationResult(
        status=status,
        value=tuple(result) if result else None,
        diagnostics=tuple(own_diagnostics),
        prerequisites=tuple(dict.fromkeys(skipped_prerequisites)),
    )


def _collect_policy_values(
    authored: tuple,
    normalize,
    collector: DiagnosticCollector,
    *,
    stage: str,
) -> EvaluationResult[tuple]:
    """Evaluate independently-authored roots once and retain successful partial values."""

    values: list[object] = []
    diagnostics: list[Diagnostic] = []
    for fact in sorted(authored, key=lambda item: getattr(item, "resource_uri", "")):
        before = {item.id for item in collector.diagnostics}
        try:
            values.extend(normalize((fact,)))
        except PolicyNormalizationError as exc:
            owner = {
                "runtime": "kairos-design-silver",
                "temporal_fk": "kairos-design-silver",
                "quality": "kairos-design-silver",
                "gold": "kairos-design-gold",
            }.get(stage, exc.diagnostic.owner_skill)
            collector.add(
                replace(
                    exc.diagnostic,
                    stage=stage,
                    owner_skill=owner,
                    remediation=f"Resolve {exc.code} with {owner}.",
                )
            )
        diagnostics.extend(item for item in collector.diagnostics if item.id not in before)
    return EvaluationResult(
        status=EvaluationStatus.FAILED if diagnostics else EvaluationStatus.PASSED,
        value=tuple(values),
        diagnostics=tuple(diagnostics),
    )


def normalize_medallion_policy(
    facts: MedallionPolicyFacts,
    *,
    systems: tuple[SourceSystemFact, ...],
    mappings: SourceMappings,
    silver_candidates: tuple[BoundSilverModel, ...],
    fk_policy: ForeignKeyPolicy,
    target_adapter: str = "fabric",
    target_source: PolicySource = PolicySource.DEFAULT,
    mode: ExecutionMode = ExecutionMode.FAIL_FAST,
    contracts: tuple[tuple[str, ContractFact], ...] = (),
) -> MedallionPolicySpec:
    """Classify all effective policy; this function performs no RDF or file I/O."""
    issues: list[PolicyIssue] = []
    silver_fk_policy = _silver_foreign_key_policy(fk_policy, silver_candidates)
    try:
        adapter = AdapterName(target_adapter)
    except ValueError as exc:
        supported = ", ".join(item.value for item in AdapterName)
        raise PolicyNormalizationError(
            "adapter.unsupported",
            f"unsupported adapter {target_adapter!r}; expected one of: {supported}",
            rule_id="DD-111-adapter",
            resource_uri=facts.ontology_uri,
        ) from exc
    naming = (
        _effective(
            NamingConvention(
                _single(
                    facts.naming_convention,
                    "naming convention",
                    "DD-106-naming",
                )
            ),
            facts.naming_convention,
            "DD-106-naming",
            source=PolicySource.OVERRIDE,
            evidence=("Ontology-level override of the v1 naming default.",),
        )
        if facts.naming_convention is not None
        else _default(
            NamingConvention.CAMEL_TO_SNAKE,
            "DD-106-naming",
            "Medallion policy v1 naming default.",
        )
    )
    collector = DiagnosticCollector(mode)
    multi_source = _normalize_multi_source(facts.multi_source)
    incremental_result = (
        _collect_policy_values(
            facts.incremental, _normalize_incremental, collector, stage="runtime"
        )
        if mode is ExecutionMode.COLLECT
        else EvaluationResult(
            status=EvaluationStatus.PASSED,
            value=_normalize_incremental(facts.incremental),
        )
    )
    incremental = incremental_result.value or ()
    hashes = _normalize_hashes(facts.hashes)
    temporal_result = (
        _collect_policy_values(
            facts.temporal_relationships,
            _normalize_temporal,
            collector,
            stage="temporal_fk",
        )
        if mode is ExecutionMode.COLLECT
        else EvaluationResult(
            status=EvaluationStatus.PASSED,
            value=_normalize_temporal(facts.temporal_relationships),
        )
    )
    temporal = temporal_result.value or ()
    quality_result = (
        _collect_policy_values(facts.data_quality, _normalize_dq, collector, stage="quality")
        if mode is ExecutionMode.COLLECT
        else EvaluationResult(
            status=EvaluationStatus.PASSED,
            value=_normalize_dq(facts.data_quality),
        )
    )
    quality = quality_result.value or ()
    identity_result = (
        _collect_identities(
            facts.identities,
            multi_source,
            hashes,
            incremental,
            silver_candidates,
            issues,
            collector,
            contracts,
            incremental_result,
        )
        if mode is ExecutionMode.COLLECT
        else EvaluationResult(
            status=EvaluationStatus.PASSED,
            value=_normalize_identities(
                facts.identities,
                multi_source,
                hashes,
                incremental,
                silver_candidates,
                issues,
                contracts,
            ),
        )
    )
    identities = identity_result.value or ()
    identity_prerequisite = Prerequisite(
        id="identity",
        status=identity_result.status,
        diagnostic_ids=tuple(item.id for item in identity_result.diagnostics),
    )
    runtime_result: EvaluationResult[object] = incremental_result
    fk_result: EvaluationResult[object] = temporal_result
    if (
        mode is ExecutionMode.COLLECT
        and not identity_prerequisite.available
        and temporal_result.status is EvaluationStatus.PASSED
    ):
        fk_result = _not_evaluated_stage(
            "temporal_fk",
            identity_prerequisite,
            code_stage="foreign_keys",
        )
    identity_uris = {item.entity_uri for item in identities}
    for class_uri in sorted(
        {
            candidate.identity.class_uri
            for candidate in silver_candidates
            if candidate.identity.class_uri and candidate.identity.outcome.value != "skipped"
        }
        - identity_uris
    ):
        issues.append(
            PolicyIssue(
                code="identity.missing-policy",
                message=(
                    f"Materialized entity {class_uri!r} lacks the complete DD-108 "
                    "identity and lineage policy."
                ),
                rule_id="DD-108-identity",
                resource_uri=class_uri,
            )
        )
    deviations = _normalize_deviations(facts.deviations, issues)
    adapter_evidence = _validate_adapter_evidence(facts.adapter_support, issues)
    try:
        gold = _normalize_gold(facts.gold, incremental, issues)
        gold_result: EvaluationResult[object] = EvaluationResult(
            status=EvaluationStatus.PASSED,
            value=gold,
        )
    except PolicyNormalizationError as exc:
        if mode is ExecutionMode.FAIL_FAST:
            raise
        collector.add(exc.diagnostic)
        gold = GoldProductSpec(
            profile=None,
            schema=None,
            tables=(),
            measures=(),
            calendar=None,
            security=None,
            perspectives=(),
        )
        gold_result = EvaluationResult(
            status=EvaluationStatus.FAILED,
            diagnostics=(exc.diagnostic,),
        )
    requirements = _capability_requirements(
        hashes,
        incremental,
        temporal,
        multi_source,
        facts.identities,
        quality,
        gold,
        has_foreign_keys=bool(silver_fk_policy.descriptors),
        has_contracted_dbt_source=any(
            table.ref_model for system in systems for table in system.tables
        ),
    )
    quality_scope_targets = _resolve_quality_scopes(
        quality,
        silver_candidates,
        systems,
        mappings,
        silver_fk_policy,
    )
    if mode is ExecutionMode.COLLECT:
        silver_items: list[SilverModelAuthoritySpec] = []
        normalized_identity_uris = {item.entity_uri for item in identities}
        authored_identity_uris = {item.resource_uri for item in facts.identities}
        before_silver = {item.id for item in collector.diagnostics}
        for candidate in silver_candidates:
            if (
                candidate.identity.class_uri in authored_identity_uris
                and candidate.identity.class_uri not in normalized_identity_uris
            ):
                continue
            try:
                silver_items.extend(
                    _silver_authorities(
                        (candidate,),
                        identities,
                        facts.identities,
                        multi_source,
                        incremental,
                        hashes,
                        temporal,
                        quality,
                        silver_fk_policy,
                        requirements,
                        deviations,
                        quality_scope_targets,
                    )
                )
            except PolicyNormalizationError as exc:
                collector.add(exc.diagnostic)
        silver = tuple(silver_items)
        silver_diagnostics = tuple(
            item for item in collector.diagnostics if item.id not in before_silver
        )
        if silver_diagnostics:
            fk_result = EvaluationResult(
                status=EvaluationStatus.FAILED,
                value=fk_result.value,
                diagnostics=(*fk_result.diagnostics, *silver_diagnostics),
                prerequisites=fk_result.prerequisites,
            )
    else:
        silver = _silver_authorities(
            silver_candidates,
            identities,
            facts.identities,
            multi_source,
            incremental,
            hashes,
            temporal,
            quality,
            silver_fk_policy,
            requirements,
            deviations,
            quality_scope_targets,
        )
    mdm_routing = tuple(
        MdmRoutingSpec(
            entity_uri=item.entity_uri,
            probabilistic_matching_owner="kairos-mdm-runtime",
            survivorship_owner="kairos-mdm-runtime",
            persistent_enterprise_identity_owner="kairos-mdm-runtime",
            merge_split_owner="kairos-mdm-runtime",
            policy=PolicyProvenance(
                source=PolicySource.DEFAULT,
                rule_id="DD-108-mdm-boundary",
                resource_uri=item.entity_uri,
                evidence=("Core records routing ownership only; it imports no MDM code.",),
            ),
        )
        for item in identities
        if item.mastered.routed_to_mdm
    )
    result = MedallionPolicySpec(
        version="1.0",
        target_adapter=EffectiveValue(
            adapter,
            PolicyProvenance(
                source=target_source,
                rule_id="DD-111-adapter",
                resource_uri=facts.ontology_uri,
                evidence=("Exact adapter selection; no fallback or alias.",),
            ),
        ),
        naming_convention=naming,
        identities=identities,
        multi_source=multi_source,
        incremental=incremental,
        hashes=hashes,
        temporal_relationships=temporal,
        data_quality=quality,
        dq_runtime_result=DqRuntimeResultContractSpec(
            schema_version="1.0",
            relation_name="kairos_dq_runtime_results",
            fields=(
                DqRuntimeFieldSpec(
                    "execution_timestamp",
                    "timestamp",
                    False,
                    "Downstream execution timestamp; never projection time.",
                ),
                DqRuntimeFieldSpec("run_id", "string", False, "Downstream dbt run ID."),
                DqRuntimeFieldSpec(
                    "snapshot_id",
                    "string",
                    True,
                    "Optional immutable source snapshot identifier.",
                ),
                DqRuntimeFieldSpec(
                    "adapter_name",
                    "string",
                    False,
                    "Exact adapter used to evaluate the rule.",
                ),
                DqRuntimeFieldSpec(
                    "adapter_version",
                    "string",
                    False,
                    "Compiled adapter capability-profile version.",
                ),
                DqRuntimeFieldSpec("model_name", "string", False, "Evaluated model."),
                DqRuntimeFieldSpec("rule_id", "string", False, "Stable rule ID."),
                DqRuntimeFieldSpec("rule_version", "string", False, "Rule version."),
                DqRuntimeFieldSpec(
                    "rule_hash",
                    "string",
                    False,
                    "SHA-256 of the normalized executable rule.",
                ),
                DqRuntimeFieldSpec(
                    "category",
                    "string",
                    False,
                    "Contract, source, business, or operational.",
                ),
                DqRuntimeFieldSpec(
                    "status",
                    "string",
                    False,
                    "pass, fail, error, or not-evaluated.",
                ),
                DqRuntimeFieldSpec(
                    "observed_value",
                    "string",
                    True,
                    "Portable lexical form of the observed metric.",
                ),
                DqRuntimeFieldSpec(
                    "tolerance",
                    "string",
                    False,
                    "Canonical authored acceptance threshold.",
                ),
                DqRuntimeFieldSpec(
                    "action",
                    "string",
                    False,
                    "Governed warn, quarantine, or block action.",
                ),
                DqRuntimeFieldSpec(
                    "affected_count",
                    "integer",
                    True,
                    "Rows contributing to a failed metric.",
                ),
                DqRuntimeFieldSpec(
                    "quarantined_count",
                    "integer",
                    True,
                    "Rows persisted in the explicit quarantine relation.",
                ),
                DqRuntimeFieldSpec(
                    "reconciliation_values",
                    "string",
                    True,
                    "Portable source and comparison values.",
                ),
                DqRuntimeFieldSpec(
                    "evidence",
                    "string",
                    False,
                    "Governed rule and execution evidence references.",
                ),
                DqRuntimeFieldSpec(
                    "evidence_uri",
                    "string",
                    True,
                    "Immutable imported runtime-evidence URI.",
                ),
            ),
            statuses=tuple(DqResultStatus),
        ),
        silver_models=silver,
        gold_registry=_gold_registry(),
        gold=gold,
        mdm_routing=mdm_routing,
        adapter_evidence=adapter_evidence,
        deviations=deviations,
        capability_requirements=requirements,
        issues=tuple(
            sorted(
                issues,
                key=lambda item: (
                    item.code,
                    item.resource_uri,
                    item.message,
                ),
            )
        ),
    )
    if mode is ExecutionMode.COLLECT and collector.diagnostics:
        raise PolicyCollectionError(
            PolicyNormalizationStages(
                preparation=EvaluationResult(status=EvaluationStatus.PASSED, value=()),
                identity=identity_result,
                runtime=runtime_result,
                foreign_keys=fk_result,
                quality=quality_result,
                gold=gold_result,
            ),
            partial_value=result,
        )
    return result
