# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Versioned, non-persisted projection-readiness report contracts."""

from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any, ClassVar

from .projections.dbt.diagnostics import Diagnostic, diagnostic_from_exception

PHASE_SCOPE_STAGES = {
    "source": frozenset({"binding", "preparation"}),
    "mapping": frozenset({"mapping"}),
    "transformation": frozenset({"transformation"}),
    "silver": frozenset({"identity", "runtime", "temporal_fk", "quality"}),
}
PHASE_SCOPE_OWNERS = {
    "source": "kairos-design-source",
    "mapping": "kairos-design-mapping",
    "transformation": "kairos-develop-dbt-transformation",
    "silver": "kairos-design-silver",
}
PHASE_SCOPE_PREREQUISITES = {
    "source": (),
    "mapping": ("source",),
    "transformation": ("source", "mapping"),
    "silver": ("source", "mapping", "transformation"),
}


@dataclass(frozen=True, slots=True)
class ReadinessBlocker:
    """The first fail-fast blocker reached by projection planning."""

    stage: str
    message: str
    domain: str = ""
    target: str = ""


@dataclass(frozen=True, slots=True)
class RemediationTask:
    """One dependency-ordered action deduplicated by owning root cause."""

    id: str
    owner_skill: str
    stage: str
    remediation: str
    diagnostic_ids: tuple[str, ...]
    impacted_resources: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectionReadinessReport:
    """Stable Release 2 report returned without writing hub files."""

    SCHEMA_VERSION: ClassVar[str] = "1.1"

    toolkit_version: str
    status: str
    targets: tuple[str, ...]
    domains: tuple[str, ...]
    platform: str
    accelerator: str
    namespace: str
    blocker: ReadinessBlocker | None = None
    diagnostics: tuple[dict[str, Any], ...] = ()
    remediation_plan: tuple[RemediationTask, ...] = ()
    schema_version: str = SCHEMA_VERSION
    mode: str = "fail_fast"
    persisted: bool = False
    scope: str = "projection"
    owner_skill: str = "kairos-execute-project"
    prerequisites: tuple[str, ...] = ()
    phase_details: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict[str, Any]:
        """Return the versioned JSON-compatible representation."""

        return asdict(self)

    def to_json(self) -> str:
        """Return deterministic JSON suitable for automation."""

        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProjectionReadinessReport:
        """Read schema 1.0/1.1 evidence while defaulting newly-added collections."""

        blocker = payload.get("blocker")
        tasks = payload.get("remediation_plan", ())
        return cls(
            toolkit_version=str(payload.get("toolkit_version", "")),
            status=str(payload.get("status", "blocked")),
            targets=tuple(payload.get("targets", ())),
            domains=tuple(payload.get("domains", ())),
            platform=str(payload.get("platform", "")),
            accelerator=str(payload.get("accelerator", "")),
            namespace=str(payload.get("namespace", "")),
            blocker=ReadinessBlocker(**blocker) if isinstance(blocker, dict) else None,
            diagnostics=tuple(payload.get("diagnostics", ())),
            remediation_plan=tuple(
                item if isinstance(item, RemediationTask) else RemediationTask(**item)
                for item in tasks
            ),
            schema_version=str(payload.get("schema_version", "1.0")),
            mode=str(payload.get("mode", "fail_fast")),
            persisted=bool(payload.get("persisted", False)),
            scope=str(payload.get("scope", "projection")),
            owner_skill=str(payload.get("owner_skill", "kairos-execute-project")),
            prerequisites=tuple(payload.get("prerequisites", ())),
            phase_details=dict(payload.get("phase_details", {})),
        )

    def to_text(self) -> str:
        """Return a concise versioned human-readable report."""

        lines = [
            f"Projection readiness report v{self.schema_version}",
            f"Status: {self.status.upper()}",
            f"Mode: {self.mode}",
            f"Scope: {self.scope}",
            f"Owner skill: {self.owner_skill}",
            f"Targets: {', '.join(self.targets) or 'none'}",
            f"Domains: {', '.join(self.domains) or 'none'}",
            f"Platform: {self.platform}",
        ]
        if self.accelerator:
            lines.append(f"Accelerator: {self.accelerator}")
        if self.namespace:
            lines.append(f"Namespace: {self.namespace}")
        if self.prerequisites:
            lines.append(f"Prerequisites: {', '.join(self.prerequisites)}")
        if self.blocker:
            scope = "/".join(
                item for item in (self.blocker.target, self.blocker.domain) if item
            )
            lines.append(
                f"Blocker ({self.blocker.stage}{f', {scope}' if scope else ''}): "
                f"{self.blocker.message}"
            )
        if self.diagnostics:
            lines.append("Diagnostics:")
            lines.extend(
                f"- [{item.get('stage', 'planning')}] {item.get('code', 'blocked')}: "
                f"{item.get('message', '')}"
                for item in self.diagnostics
            )
        if self.remediation_plan:
            lines.append("Remediation plan:")
            lines.extend(
                f"- {item.owner_skill}: {item.remediation}"
                for item in self.remediation_plan
            )
        lines.append("Evidence persistence: deferred; this command writes no files.")
        return "\n".join(lines)


def check_projection(
    *,
    ontologies_path: Path,
    catalog_path: Path | None,
    output_path: Path,
    target: str,
    namespace: str | None,
    platform: str,
    emit_aspirational_stubs: bool,
    degraded: bool,
    ref_models_dir: Path | None,
    accelerator: str | None,
    scope: str = "projection",
    hub_root: Path | None = None,
    table_scope: tuple[str, ...] | list[str] = (),
    transformation_stage: str = "silver",
) -> ProjectionReadinessReport:
    """Evaluate projection through physical planning while suppressing generator output."""

    from .projector import run_projections

    if scope not in {"projection", *PHASE_SCOPE_STAGES}:
        raise ValueError(f"unknown readiness scope: {scope}")
    captured_output = StringIO()
    with redirect_stdout(captured_output), redirect_stderr(captured_output):
        projection = run_projections(
            ontologies_path=ontologies_path,
            catalog_path=catalog_path,
            output_path=output_path,
            target=target,
            namespace=namespace,
            platform=platform,
            emit_aspirational_stubs=emit_aspirational_stubs,
            degraded=degraded,
            ref_models_dir=ref_models_dir,
            accelerator=accelerator,
            check_only=True,
            diagnostic_mode=(
                "collect"
                if target in {"dbt", "silver", "powerbi", "all"}
                else "fail_fast"
            ),
        )

    blocker = None
    diagnostic_items: list[dict[str, Any]] = []
    for domain, item in projection.domains.items():
        if item.get("status") != "ok":
            blocker = ReadinessBlocker(
                stage="load",
                domain=domain,
                message=str(item.get("error", "ontology load failed")),
            )
            break
    if blocker is None:
        for item in projection.post_steps:
            if item.get("status") == "error":
                diagnostic_items.extend(item.get("diagnostics", ()))
                blocker = ReadinessBlocker(
                    stage=str(item.get("step", "preflight")),
                    message=str(item.get("reason", "projection preflight failed")),
                )
                break
    if blocker is None:
        for item in projection.projections:
            supplied = item.get("diagnostics", ())
            if supplied:
                diagnostic_items.extend(supplied)
            if item.get("status") == "error":
                if blocker is None:
                    blocker = ReadinessBlocker(
                        stage="planning",
                        domain=str(item.get("domain", "")),
                        target=str(item.get("target", "")),
                        message=str(item.get("error", "projection planning failed")),
                    )
                if not supplied:
                    diagnostic = diagnostic_from_exception(
                        ValueError(str(item.get("error", "projection planning failed"))),
                        stage="normalization",
                    )
                    diagnostic_items.append(_diagnostic_dict(diagnostic))
    if blocker is None and not projection.domains:
        blocker = ReadinessBlocker(
            stage="scope",
            message=f"No ontology files found in {ontologies_path}",
        )

    diagnostics = _ordered_diagnostics(diagnostic_items)
    resolved_hub = None
    active_sources = {
        str(item.get("domain", "")): item.get("details", {}).get("active_sources", [])
        for item in projection.projections
        if item.get("details", {}).get("active_sources")
    }
    phase_details: dict[str, Any] = (
        {"active_sources": active_sources} if active_sources else {}
    )
    if scope in {"mapping", "transformation", "silver"}:
        resolved_hub = _resolve_hub_root(ontologies_path, hub_root)
        transformation_report = _transformation_report(
            resolved_hub,
            table_scope,
            transformation_stage,
        )
        phase_details["transformation_readiness"] = transformation_report.to_dict()
        diagnostics = _ordered_diagnostics(
            [
                *diagnostics,
                *_transformation_diagnostics(transformation_report),
            ]
        )
    if scope == "silver" and resolved_hub is not None:
        diagnostics = _ordered_diagnostics(
            [
                *diagnostics,
                *_silver_sync_diagnostics(
                    resolved_hub,
                    accelerator=accelerator,
                    catalog_path=catalog_path,
                    ref_models_dir=ref_models_dir,
                ),
            ]
        )
    if scope != "projection":
        diagnostics = tuple(
            item for item in diagnostics if _diagnostic_in_scope(item, scope)
        )
        universal_blocker = blocker is not None and blocker.stage in {"load", "scope"}
        blocking = next(
            (item for item in diagnostics if item.get("blocking", True)),
            None,
        )
        if blocking is not None:
            blocker = ReadinessBlocker(
                stage=str(blocking.get("stage", scope)),
                message=str(blocking.get("message", "readiness blocked")),
            )
        elif not universal_blocker:
            blocker = None
    return ProjectionReadinessReport(
        toolkit_version=projection.toolkit_version,
        status="blocked" if blocker else "ready",
        targets=tuple(projection.targets_requested),
        domains=tuple(sorted(projection.domains)),
        platform=platform,
        accelerator=accelerator or "",
        namespace=namespace or "",
        blocker=blocker,
        diagnostics=diagnostics,
        remediation_plan=_remediation_plan(diagnostics),
        mode=(
            "collect"
            if target in {"dbt", "silver", "powerbi", "all"}
            else "fail_fast"
        ),
        scope=scope,
        owner_skill=PHASE_SCOPE_OWNERS.get(scope, "kairos-execute-project"),
        prerequisites=PHASE_SCOPE_PREREQUISITES.get(scope, ()),
        phase_details=phase_details,
    )


def _resolve_hub_root(ontologies_path: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return Path(explicit).resolve()
    path = Path(ontologies_path).resolve()
    if path.name == "ontologies" and path.parent.name == "model":
        return path.parent.parent
    if path.is_file() and path.parent.name == "ontologies" and path.parent.parent.name == "model":
        return path.parent.parent.parent
    raise ValueError("transformation readiness requires an ontology-hub root")


def _transformation_report(
    hub_root: Path,
    table_scope: tuple[str, ...] | list[str],
    stage: str,
) -> Any:
    """Invoke the existing transformation evaluator once for the shared report."""

    from .transformation_candidates import evaluate_transformation_readiness

    return evaluate_transformation_readiness(
        hub_root,
        stage=stage,
        table_scope=table_scope,
    )


def _transformation_diagnostics(report: Any) -> list[dict[str, Any]]:
    """Project existing transformation results into shared diagnostics."""

    diagnostics: list[dict[str, Any]] = []
    for candidate in report.candidates:
        for reason in candidate.reasons:
            prefix, separator, _ = reason.partition(":")
            code = (
                prefix
                if separator and "." in prefix
                else "transformation.readiness-blocked"
            )
            diagnostic = Diagnostic(
                code=code,
                message=reason,
                rule_id="DD-107/DD-118",
                resource_uri=candidate.id,
                stage="transformation",
                owner_skill="kairos-develop-dbt-transformation",
                evidence=(f"candidate:{candidate.id}",),
                remediation=(
                    "Synchronize and complete the governed dbt contract, implementation, "
                    "evidence, dependencies, and tests."
                ),
                blocking=candidate.is_blocking,
            )
            diagnostics.append(_diagnostic_dict(diagnostic))
    return diagnostics


def _silver_sync_diagnostics(
    hub_root: Path,
    *,
    accelerator: str | None = None,
    catalog_path: Path | None = None,
    ref_models_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Project the lifecycle gate's claim/include sync authority into diagnostics.

    The accelerator/catalog/ref-models context must be threaded through so
    ``expected_imports`` accounts for data-domain-activated reference modules;
    otherwise those imports are false-flagged as ``extra import`` (issue #239).
    """

    from .claim_projection_sync import evaluate_projection_sync

    report = evaluate_projection_sync(
        claims_dir=hub_root / "model" / "claims",
        ontologies_dir=hub_root / "model" / "ontologies",
        extensions_dir=hub_root / "model" / "extensions",
        ref_models_dir=ref_models_dir,
        catalog_path=catalog_path,
        accelerator=accelerator,
    )
    diagnostics: list[dict[str, Any]] = []
    for domain in report.domains:
        if domain.in_sync:
            continue
        details = [
            *(f"missing import {value}" for value in domain.missing_imports),
            *(f"extra import {value}" for value in domain.extra_imports),
            *(f"missing include {value}" for value in domain.missing_includes),
            *(f"extra include {value}" for value in domain.extra_includes),
        ]
        if domain.has_bulk_include_imports:
            details.append("bulk include/import authority is not synchronized")
        if domain.error:
            details.append(domain.error)
        diagnostics.append(
            _diagnostic_dict(
                Diagnostic(
                    code="claims.projection-sync",
                    message="; ".join(details) or "claim/include synchronization failed",
                    rule_id="DD-096/DD-100",
                    resource_uri=domain.domain,
                    stage="silver_sync",
                    owner_skill="kairos-design-silver",
                    remediation="Synchronize approved claims, ontology imports, and Silver includes.",
                )
            )
        )
    return diagnostics


def _diagnostic_in_scope(item: dict[str, Any], scope: str) -> bool:
    stage = str(item.get("stage", ""))
    code = str(item.get("code", ""))
    if stage in PHASE_SCOPE_STAGES[scope]:
        return True
    if scope == "source":
        return code.startswith(
            (
                "identity.contract-",
                "identity.duplicate-key-component",
                "identity.duplicate-source-identity",
                "identity.source-contributor-",
                "identity.unknown-source-identity",
            )
        )
    if scope == "mapping":
        return code in {
            "transformation.contract-sync",
            "transformation.contract-invalid",
        }
    if scope == "transformation":
        return (
            stage == "transformation"
            or code.startswith("identity.contract-")
            or "cdc" in code
        )
    if scope == "silver":
        return stage == "silver_sync"
    return False


def _diagnostic_dict(item: Diagnostic) -> dict[str, Any]:
    return {
        "id": item.id,
        "code": item.code,
        "rule_id": item.rule_id,
        "severity": item.severity.value,
        "blocking": item.blocking,
        "stage": item.stage,
        "owner_skill": item.owner_skill,
        "resource_uri": item.resource_uri,
        "predicate_uri": item.predicate_uri,
        "message": item.message,
        "evidence": list(item.evidence),
        "depends_on": list(item.depends_on),
        "remediation": item.remediation,
        "evaluation_status": item.evaluation_status.value,
    }


def _ordered_diagnostics(items: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    stage_order = {
        name: index
        for index, name in enumerate(
            (
                "binding",
                "preparation",
                "mapping",
                "transformation",
                "silver_sync",
                "identity",
                "runtime",
                "temporal_fk",
                "adapter",
                "quality",
                "gold",
                "normalization",
            )
        )
    }
    by_id = {str(item.get("id", "")): item for item in items}
    return tuple(
        sorted(
            by_id.values(),
            key=lambda item: (
                stage_order.get(str(item.get("stage", "")), 999),
                str(item.get("stage", "")),
                str(item.get("resource_uri", "")),
                str(item.get("predicate_uri", "")),
                str(item.get("code", "")),
                str(item.get("id", "")),
            ),
        )
    )


def _remediation_plan(
    diagnostics: tuple[dict[str, Any], ...],
) -> tuple[RemediationTask, ...]:
    """Group impacted resources under one stable root-cause action."""

    blocking_ids = {
        str(item.get("id", ""))
        for item in diagnostics
        if item.get("blocking", True)
    }
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for item in diagnostics:
        if not item.get("blocking", True):
            continue
        roots = tuple(
            value for value in item.get("depends_on", ()) if value in blocking_ids
        )
        root = roots[0] if roots else str(item.get("code", "blocked"))
        key = (
            str(item.get("owner_skill", "kairos-execute-validate")),
            str(item.get("stage", "normalization")),
            root,
            str(item.get("remediation", "")),
        )
        groups.setdefault(key, []).append(item)
    tasks = []
    for index, (key, members) in enumerate(groups.items(), start=1):
        owner, stage, root, remediation = key
        tasks.append(
            RemediationTask(
                id=f"remediation-{index:03d}",
                owner_skill=owner,
                stage=stage,
                remediation=remediation or f"Resolve {root}.",
                diagnostic_ids=tuple(sorted(str(item.get("id", "")) for item in members)),
                impacted_resources=tuple(
                    sorted(
                        {
                            str(item.get("resource_uri", ""))
                            for item in members
                            if item.get("resource_uri")
                        }
                    )
                ),
                depends_on=tuple(
                    sorted(
                        {
                            str(value)
                            for item in members
                            for value in item.get("depends_on", ())
                        }
                    )
                ),
            )
        )
    task_by_diagnostic = {
        diagnostic_id: task.id
        for task in tasks
        for diagnostic_id in task.diagnostic_ids
    }
    normalized = [
        RemediationTask(
            id=task.id,
            owner_skill=task.owner_skill,
            stage=task.stage,
            remediation=task.remediation,
            diagnostic_ids=task.diagnostic_ids,
            impacted_resources=task.impacted_resources,
            depends_on=tuple(
                sorted(
                    {
                        task_by_diagnostic[diagnostic_id]
                        for diagnostic_id in task.depends_on
                        if diagnostic_id in task_by_diagnostic
                        and task_by_diagnostic[diagnostic_id] != task.id
                    }
                )
            ),
        )
        for task in tasks
    ]
    ordered: list[RemediationTask] = []
    remaining = list(normalized)
    while remaining:
        completed = {item.id for item in ordered}
        ready = [item for item in remaining if set(item.depends_on) <= completed]
        if not ready:
            ready = [remaining[0]]
        for item in ready:
            ordered.append(item)
            remaining.remove(item)
    return tuple(ordered)
