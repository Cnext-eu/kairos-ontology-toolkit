# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Versioned diagnostic contracts for dbt policy evaluation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Generic, Iterable, TypeVar

T = TypeVar("T")


class ExecutionMode(str, Enum):
    """How an evaluator handles blocking diagnostics."""

    FAIL_FAST = "fail_fast"
    COLLECT = "collect"


class DiagnosticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class EvaluationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Stable diagnostic payload shared by normalization and readiness checks."""

    SCHEMA_VERSION: ClassVar[str] = "1.0"

    code: str
    message: str
    rule_id: str
    resource_uri: str = ""
    predicate_uri: str = ""
    id: str = ""
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    blocking: bool = True
    stage: str = "normalization"
    owner_skill: str = ""
    evidence: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    remediation: str = ""
    evaluation_status: EvaluationStatus = EvaluationStatus.FAILED
    schema_version: str = field(default=SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        if not self.id:
            identity = "\x1f".join(
                (self.stage, self.resource_uri, self.predicate_uri, self.code, self.rule_id)
            )
            digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
            object.__setattr__(self, "id", f"dbt-{digest}")

    @property
    def sort_key(self) -> tuple[int, str, str, str, str, str]:
        """Return the normative deterministic ordering key."""

        stage_order = {
            "binding": 10,
            "preparation": 20,
            "mapping": 30,
            "identity": 40,
            "runtime": 50,
            "temporal_fk": 60,
            "adapter": 70,
            "quality": 80,
            "gold": 90,
            "normalization": 100,
        }
        return (
            stage_order.get(self.stage, 100),
            self.stage,
            self.resource_uri,
            self.predicate_uri,
            self.code,
            self.id,
        )


def order_diagnostics(diagnostics: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    """Return diagnostics in stable contract order."""

    return tuple(sorted(diagnostics, key=lambda item: item.sort_key))


_STAGE_OWNERS = {
    "binding": "kairos-design-source",
    "preparation": "kairos-design-source",
    "mapping": "kairos-design-mapping",
    "identity": "kairos-design-silver",
    "runtime": "kairos-design-silver",
    "temporal_fk": "kairos-design-silver",
    "adapter": "kairos-execute-validate",
    "quality": "kairos-design-silver",
    "gold": "kairos-design-gold",
}


def diagnostic_from_exception(
    error: Exception,
    *,
    stage: str,
    depends_on: Iterable[str] = (),
) -> Diagnostic:
    """Normalize a legacy subsystem exception without changing its fail-fast contract."""

    existing = getattr(error, "diagnostic", None)
    code = str(getattr(error, "code", f"{stage}.blocked"))
    rule_id = str(getattr(error, "rule_id", f"DD-116-{stage}"))
    resource_uri = str(getattr(error, "resource_uri", ""))
    predicate_uri = str(getattr(error, "predicate_uri", ""))
    message = existing.message if isinstance(existing, Diagnostic) else str(error)
    remediation = f"Resolve {code} with {_STAGE_OWNERS.get(stage, 'kairos-execute-validate')}."
    return Diagnostic(
        code=code,
        message=message,
        rule_id=rule_id,
        resource_uri=resource_uri,
        predicate_uri=predicate_uri,
        stage=stage,
        owner_skill=_STAGE_OWNERS.get(stage, "kairos-execute-validate"),
        evidence=tuple(
            value
            for value in (
                f"resource:{resource_uri}" if resource_uri else "",
                f"predicate:{predicate_uri}" if predicate_uri else "",
                f"rule:{rule_id}",
            )
            if value
        ),
        depends_on=tuple(depends_on),
        remediation=remediation,
    )


@dataclass(frozen=True, slots=True)
class Prerequisite:
    """Availability of an upstream evaluation result."""

    id: str
    status: EvaluationStatus
    diagnostic_ids: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.status is EvaluationStatus.PASSED


@dataclass(frozen=True, slots=True)
class EvaluationResult(Generic[T]):
    """Typed result that distinguishes failure from unavailable prerequisites."""

    status: EvaluationStatus
    value: T | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    prerequisites: tuple[Prerequisite, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", order_diagnostics(self.diagnostics))

    @classmethod
    def not_evaluated(
        cls,
        prerequisites: Iterable[Prerequisite],
        diagnostics: Iterable[Diagnostic] = (),
    ) -> EvaluationResult[T]:
        return cls(
            status=EvaluationStatus.NOT_EVALUATED,
            diagnostics=tuple(diagnostics),
            prerequisites=tuple(prerequisites),
        )


class DiagnosticFailure(ValueError):
    """Default fail-fast signal for new diagnostic-aware evaluators."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(diagnostic.message)


class DiagnosticCollector:
    """Small execution-mode bridge for incrementally converted evaluators."""

    def __init__(self, mode: ExecutionMode = ExecutionMode.FAIL_FAST) -> None:
        self.mode = mode
        self._diagnostics: list[Diagnostic] = []

    def add(self, diagnostic: Diagnostic) -> None:
        if self.mode is ExecutionMode.FAIL_FAST and diagnostic.blocking:
            raise DiagnosticFailure(diagnostic)
        self._diagnostics.append(diagnostic)

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return order_diagnostics(self._diagnostics)
