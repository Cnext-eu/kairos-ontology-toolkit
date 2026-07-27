# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Immutable graph-free compiler plan shared by all compiler consumers."""

from __future__ import annotations

from dataclasses import dataclass

from ..projections.dbt.context import MaterializationPlan, ProjectionContract, ShapedProject
from ..projections.dbt.specs import SilverRegistry
from .adapter import ResolutionContext
from .bindings import EntityBinding
from .ir import CanonicalProjectIR
from .result import CompileDiagnostic, CompileDiagnostics
from .scope import BuildScope


@dataclass(frozen=True, slots=True)
class PlannedCompileArtifact:
    """One artifact path selected before byte rendering."""

    path: str
    entity_name: str = ""


@dataclass(frozen=True, slots=True)
class CompileEntityPlan:
    """Plan and blocking outcome for one parsed entity binding."""

    binding: EntityBinding
    diagnostics: tuple[CompileDiagnostic, ...] = ()
    artifact_paths: tuple[str, ...] = ()
    blocked: bool = False


@dataclass(frozen=True, slots=True)
class CompilePlan:
    """Canonical result of resolution, validation, shaping, and materialization.

    The plan deliberately contains no RDF graph and no renderer output. Consumers such as
    Gold and MDM can inspect the same typed contract and Silver registry used by dbt without
    writing files or depending on the private ``BoundSources`` transport shape.
    """

    scope: BuildScope
    resolution: ResolutionContext
    bindings: tuple[EntityBinding, ...]
    normalized_contract: ProjectionContract | None
    shaped_project: ShapedProject | None
    silver_registry: SilverRegistry | None
    materialization_plan: MaterializationPlan | None
    planned_artifacts: tuple[PlannedCompileArtifact, ...]
    entities: tuple[CompileEntityPlan, ...]
    project_diagnostics: tuple[CompileDiagnostic, ...]
    diagnostics: CompileDiagnostics
    project_ir: CanonicalProjectIR
    blocked: bool

    @property
    def domain(self) -> str:
        """Return the selected domain."""
        return self.scope.domain

    @property
    def provenance_hash(self) -> str:
        """Return the deterministic identity of the selected input closure."""
        return self.project_ir.provenance_hash

    @property
    def can_render(self) -> bool:
        """Return whether at least one validated entity can be rendered."""
        return self.shaped_project is not None and any(
            not entity.blocked for entity in self.entities
        )

    @property
    def artifact_paths(self) -> tuple[str, ...]:
        """Return planned artifact paths in canonical order."""
        return tuple(artifact.path for artifact in self.planned_artifacts)
