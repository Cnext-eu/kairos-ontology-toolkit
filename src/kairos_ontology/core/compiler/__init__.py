# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Kairos v5 compiler package (DD-133).

A stateless ``compile`` path that turns closed YAML ``EntityBinding`` documents into
deterministic dbt artifacts by reusing the existing immutable dbt projection phases. This
package lives entirely in ``core`` and MUST NOT import :mod:`kairos_ontology.mdm`.
"""

from __future__ import annotations

from .adapter import (
    ResolutionContext,
    ResolvedClass,
    ResolvedColumn,
    ResolvedProperty,
    ResolvedRelation,
    adapt_binding,
)
from .bindings import (
    ALLOWED_FUNCTIONS,
    ALLOWED_MACROS,
    ALLOWED_NULL_POLICIES,
    ALLOWED_OPERATORS,
    MAX_EXPRESSION_DEPTH,
    EntityBinding,
    ExprCase,
    ExprCaseBranch,
    ExprColumn,
    ExprFunction,
    ExprLiteral,
    ExprMacro,
    ExprNull,
    ExprOperator,
    FieldMapping,
    GrainSpec,
    IdentitySpec,
    QualityCheck,
    RelationshipJoin,
    RelationshipSpec,
    SourceRef,
    load_entity_binding,
)
from .compile import CompileMode
from .emit import (
    EMIT_MANIFEST_NAME,
    EMIT_MANIFEST_SCHEMA,
    ArtifactCollisionError,
    ArtifactPathError,
    EmissionBusyError,
    EmissionError,
    EmissionPlan,
    EmissionResult,
    EmissionRollbackError,
    ManifestError,
    PlannedArtifact,
    emit_artifacts,
    plan_emission,
)
from .ir import CanonicalProjectIR, EntityBindingSpec
from .kernel import compile_domain, merge_bound_sources, resolve_scope
from .quality import SAFETY_RULE_CODES, run_safety_kernel
from .result import (
    CompileDiagnostic,
    CompileDiagnostics,
    CompileError,
    CompileResult,
    DiagnosticSeverity,
    SourceLocation,
    ExplainEntity,
    ExplainReport,
    order_compile_diagnostics,
)
from .scope import BuildScope, ProvenanceInput

__all__ = [
    "ALLOWED_FUNCTIONS",
    "ALLOWED_MACROS",
    "ALLOWED_NULL_POLICIES",
    "ALLOWED_OPERATORS",
    "MAX_EXPRESSION_DEPTH",
    "ManifestError",
    "BuildScope",
    "CanonicalProjectIR",
    "EMIT_MANIFEST_NAME",
    "EMIT_MANIFEST_SCHEMA",
    "ArtifactCollisionError",
    "ArtifactPathError",
    "CompileDiagnostic",
    "CompileDiagnostics",
    "CompileError",
    "CompileMode",
    "CompileResult",
    "DiagnosticSeverity",
    "EmissionBusyError",
    "EmissionError",
    "EmissionPlan",
    "EmissionResult",
    "EmissionRollbackError",
    "EntityBinding",
    "EntityBindingSpec",
    "ExplainEntity",
    "ExplainReport",
    "ExprCase",
    "ExprCaseBranch",
    "ExprColumn",
    "ExprFunction",
    "ExprLiteral",
    "ExprMacro",
    "ExprNull",
    "ExprOperator",
    "FieldMapping",
    "GrainSpec",
    "IdentitySpec",
    "ProvenanceInput",
    "PlannedArtifact",
    "QualityCheck",
    "RelationshipJoin",
    "RelationshipSpec",
    "ResolutionContext",
    "ResolvedClass",
    "ResolvedColumn",
    "ResolvedProperty",
    "ResolvedRelation",
    "SAFETY_RULE_CODES",
    "SourceLocation",
    "SourceRef",
    "adapt_binding",
    "compile_domain",
    "emit_artifacts",
    "load_entity_binding",
    "order_compile_diagnostics",
    "plan_emission",
    "merge_bound_sources",
    "resolve_scope",
    "run_safety_kernel",
]
