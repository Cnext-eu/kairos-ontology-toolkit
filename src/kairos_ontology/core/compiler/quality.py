# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Minimal non-suppressible static safety kernel for the v5 compiler (DD-133 §5).

The kernel is deliberately small and separate from authored data-quality checks: it decides
whether executable SQL may be emitted at all. The full rule set is implemented in the
``v5-compiler-kernel`` phase (it needs resolved symbols from the adapter). This module fixes
the *closed catalogue* of rule codes now so schema, adapter, and kernel agree on one list.
"""

from __future__ import annotations

from .ir import CanonicalProjectIR
from .result import CompileDiagnostic, SourceLocation

# Closed catalogue of non-suppressible safety rules (DD-133 §5). Extended with concrete
# checks in v5-compiler-kernel; the codes themselves are stable.
SAFETY_RULE_CODES: tuple[str, ...] = (
    "safety.source-unresolved",
    "safety.column-unresolved",
    "safety.class-unresolved",
    "safety.property-unresolved",
    "safety.type-incompatible",
    "safety.expression-unsafe",
    "safety.grain-missing",
    "safety.identity-incomplete",
    "safety.identity-role-collision",
    "safety.incremental-identity-incomplete",
    "safety.relationship-endpoint",
    "safety.adapter-unsupported",
    "safety.artifact-collision",
)


def run_safety_kernel(ir: CanonicalProjectIR) -> tuple[CompileDiagnostic, ...]:
    """Return deterministic structural safety diagnostics for the resolved IR."""
    diagnostics: list[CompileDiagnostic] = []
    names: set[str] = set()
    paths: set[str] = set()
    targets = {entity.binding.target_class for entity in ir.entities if not entity.blocked}
    for entity in ir.entities:
        binding = entity.binding
        if binding.name in names:
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.artifact-collision",
                    message=f"duplicate binding name '{binding.name}'",
                    location=SourceLocation(path=binding.source_path, pointer="/metadata/name"),
                )
            )
        names.add(binding.name)
        if not binding.grain.columns:
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.grain-missing",
                    message=f"binding '{binding.name}' has no materialized grain",
                    location=SourceLocation(path=binding.source_path, pointer="/grain/columns"),
                )
            )
        if not binding.identity.source_key:
            diagnostics.append(
                CompileDiagnostic(
                    code="safety.identity-incomplete",
                    message=f"binding '{binding.name}' has no source identity",
                    location=SourceLocation(
                        path=binding.source_path, pointer="/identity/sourceKey"
                    ),
                )
            )
        for relationship in binding.relationships:
            if relationship.external_reference is None and relationship.target not in targets:
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.relationship-endpoint",
                        message=(
                            f"relationship target '{relationship.target}' in "
                            f"'{binding.name}' is not in compile scope"
                        ),
                        location=SourceLocation(path=binding.source_path, pointer="/relationships"),
                    )
                )
        for path in entity.artifact_paths:
            if path in paths:
                diagnostics.append(
                    CompileDiagnostic(
                        code="safety.artifact-collision",
                        message=f"multiple entities own artifact '{path}'",
                        location=SourceLocation(path=binding.source_path),
                    )
                )
            paths.add(path)
    return tuple(diagnostics)
