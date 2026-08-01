# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Ordered compiler diagnostics, explain data, and the in-memory artifact plan (DD-133).

Everything the ``compile`` orchestration returns lives here: a deterministic, ordered
diagnostic stream, the structured explain payload, and the manifest-owned artifact plan
that atomic emission consumes. No file writes happen in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DiagnosticSeverity(str, Enum):
    """Severity of one compiler diagnostic."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Best-effort location of a diagnostic inside an authored document."""

    path: str = ""
    line: int = 0
    column: int = 0
    pointer: str = ""

    def render(self) -> str:
        """Return a stable ``path:line:col`` (plus JSON pointer) rendering."""
        base = self.path or "<binding>"
        if self.line:
            base = f"{base}:{self.line}:{self.column}"
        if self.pointer:
            base = f"{base} at {self.pointer}"
        return base


@dataclass(frozen=True, slots=True)
class CompileDiagnostic:
    """One deterministic, actionable compiler finding."""

    code: str
    message: str
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    location: SourceLocation = field(default_factory=SourceLocation)
    rule_id: str = "DD-133"

    def render(self) -> str:
        """Return a single-line, stable rendering used by ``--check`` text output."""
        return (
            f"[{self.severity.value}] {self.code}: {self.message} "
            f"({self.location.render()}) [{self.rule_id}]"
        )


def _sort_key(item: CompileDiagnostic) -> tuple:
    order = {
        DiagnosticSeverity.ERROR: 0,
        DiagnosticSeverity.WARNING: 1,
        DiagnosticSeverity.INFO: 2,
    }
    return (
        order[item.severity],
        item.location.path,
        item.location.line,
        item.location.column,
        item.code,
        item.message,
    )


def order_compile_diagnostics(
    diagnostics: "list[CompileDiagnostic] | tuple[CompileDiagnostic, ...]",
) -> tuple[CompileDiagnostic, ...]:
    """Return diagnostics in a deterministic severity/location/code order."""
    return tuple(sorted(diagnostics, key=_sort_key))


class CompileError(ValueError):
    """A fatal compiler failure carrying one or more ordered diagnostics."""

    def __init__(self, diagnostics: "list[CompileDiagnostic] | tuple[CompileDiagnostic, ...]"):
        self.diagnostics = order_compile_diagnostics(diagnostics)
        detail = "; ".join(item.render() for item in self.diagnostics) or "compile failed"
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class CompileDiagnostics:
    """A deterministic, ordered diagnostic stream."""

    items: tuple[CompileDiagnostic, ...] = ()

    @property
    def ordered(self) -> tuple[CompileDiagnostic, ...]:
        """Return the diagnostics in canonical order."""
        return order_compile_diagnostics(self.items)

    @property
    def has_errors(self) -> bool:
        """Return True when any diagnostic is an error."""
        return any(item.severity is DiagnosticSeverity.ERROR for item in self.items)

    def with_added(self, *diagnostics: CompileDiagnostic) -> "CompileDiagnostics":
        """Return a new stream with the given diagnostics appended."""
        return CompileDiagnostics(items=(*self.items, *diagnostics))


@dataclass(frozen=True, slots=True)
class ExplainLoad:
    """Closed explain shape for authored load policy."""

    mode: str
    scd: int | None = None
    merge_identity: tuple[str, ...] = ()
    canonical_hash_inputs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExplainRelationship:
    """Closed explain shape for one authored relationship."""

    target: str
    mode: str
    cardinality: str
    temporal: bool = False


@dataclass(frozen=True, slots=True)
class ExplainConformance:
    """Closed explain shape for multi-source conformance."""

    group: str
    source_precedence: int
    conflict: str
    union_mode: str


@dataclass(frozen=True, slots=True)
class ExplainQualityCheck:
    """Closed explain shape for one authored focused data-quality check."""

    kind: str
    columns: tuple[str, ...] = ()
    pointer: str = ""
    emitted_test: str = ""


@dataclass(frozen=True, slots=True)
class ExplainDataQuality:
    """Closed explain shape for one rendered DD-115 class-attached data-quality rule."""

    rule_id: str
    kind: str
    scope: str
    action: str
    severity: str
    result_model: str = ""
    result_test: str = ""
    quarantine: str = ""


@dataclass(frozen=True, slots=True)
class ExplainEntity:
    """Resolved, deterministic explanation of one entity binding."""

    name: str
    source: str
    target_class: str
    grain: tuple[str, ...]
    identity_strategy: str
    fields: tuple[tuple[str, str], ...]
    relationships: tuple[str, ...] = ()
    source_kind: str = "relation"
    load: ExplainLoad = field(default_factory=lambda: ExplainLoad(mode="full-refresh"))
    relationship_shapes: tuple[ExplainRelationship, ...] = ()
    conformance: ExplainConformance | None = None
    quality: tuple[ExplainQualityCheck, ...] = ()
    emitted_tests: tuple[str, ...] = ()
    data_quality: tuple[ExplainDataQuality, ...] = ()
    blocked: bool = False


@dataclass(frozen=True, slots=True)
class ExplainReport:
    """Write-free explanation derived from the same IR used for rendering."""

    domain: str
    provenance_hash: str
    binding_paths: tuple[str, ...]
    ontology_paths: tuple[str, ...]
    entities: tuple[ExplainEntity, ...]
    artifact_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompileResult:
    """Complete in-memory result of one stateless compile invocation."""

    domain: str
    mode: str
    diagnostics: CompileDiagnostics
    provenance_hash: str = ""
    artifacts: tuple[tuple[str, str], ...] = ()
    explain: ExplainReport | None = None
    ir: Any = None
    plan: Any = None

    @property
    def succeeded(self) -> bool:
        """Return whether the safety gate accepted the requested scope."""
        return not self.diagnostics.has_errors

    def artifact_dict(self) -> dict[str, str]:
        """Return the deterministic artifact plan as a new dictionary."""
        return dict(self.artifacts)

    @property
    def can_emit(self) -> bool:
        """Return whether the plan may replace its owned subtree.

        Entity-local safety failures are already filtered from the IR. Project-level
        normalization, collision, and scope failures remain non-emittable.
        """
        if self.succeeded:
            return True
        if self.ir is None or not self.ir.entities:
            return False
        entity_codes = {
            "safety.source-unresolved",
            "safety.column-unresolved",
            "safety.class-unresolved",
            "safety.property-unresolved",
            "safety.expression-unsafe",
            "safety.grain-missing",
            "safety.identity-incomplete",
            "safety.identity-role-collision",
            "safety.incremental-identity-incomplete",
            "safety.relationship-endpoint",
            "safety.type-incompatible",
            "safety.adapter-unsupported",
        }
        if any(entity.blocked for entity in self.ir.entities):
            return all(
                item.code in entity_codes
                or item.code.startswith(
                    ("load-policy.", "temporal.", "dbt-source.", "conformance.")
                )
                for item in self.diagnostics.items
            )
        return all(
            item.code.startswith(("binding.", "expression.")) for item in self.diagnostics.items
        )
