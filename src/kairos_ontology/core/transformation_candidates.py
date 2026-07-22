# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Deterministic inventory and governed readiness for transformation candidates."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .completeness_model import compute_completeness_facts
from .dbt_contract_sync import DbtContractSyncError, sync_dbt_contracts
from .dbt_contracts import DbtContractError, DbtContractModel, discover_dbt_contracts

INVENTORY_RELPATH = Path("model/planning/dbt-transformations/candidates.yaml")
SCHEMA_VERSION = 1
ASSESSMENT_STATUSES = frozenset({"unassessed", "accepted", "deferred", "rejected", "implemented"})
CONFIDENCES = frozenset({"low", "medium", "high"})
AUTHORITY_CLASSIFICATIONS = frozenset(
    {"operational-source", "migration-parity", "downstream-target"}
)
ADVANCED_OPERATIONS = frozenset({"aggregate", "join", "json_expansion", "union", "window"})

_REF_RE = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}", re.IGNORECASE)
_SOURCE_RE = re.compile(
    r"\{\{\s*source\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
    re.IGNORECASE,
)
_RELATION_RE = re.compile(
    r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_.$]*(?:\.[A-Za-z_][A-Za-z0-9_.$]*)*)",
    re.IGNORECASE,
)
_EXCLUDED_PARTS = frozenset(
    {
        "analyses",
        "dbt_packages",
        "generated",
        "logs",
        "macros",
        "output",
        "packages",
        "snapshots",
        "target",
        "test",
        "tests",
    }
)


class TransformationCandidateError(ValueError):
    """Raised when candidate evidence or governed inventory is invalid."""


@dataclass(frozen=True, order=True)
class ResourceReference:
    """One objective dbt or SQL resource reference."""

    kind: str
    name: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "name": self.name}


@dataclass(frozen=True)
class CandidateFacts:
    """Objective facts extracted from one repository artifact."""

    artifact_path: str
    sha256: str
    proposed_model_name: str
    resource_references: tuple[ResourceReference, ...] = ()
    detected_operations: tuple[str, ...] = ()
    declared_grain: str | None = None
    present: bool = True

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "artifact_path": self.artifact_path,
            "sha256": self.sha256,
            "proposed_model_name": self.proposed_model_name,
            "resource_references": [item.to_dict() for item in self.resource_references],
            "detected_operations": list(self.detected_operations),
            "present": self.present,
        }
        if self.declared_grain is not None:
            result["declared_grain"] = self.declared_grain
        return result


@dataclass(frozen=True)
class AssessmentApproval:
    """Repository-recorded approval provenance."""

    actor: str
    timestamp: str

    def to_dict(self) -> dict[str, str]:
        return {"actor": self.actor, "timestamp": self.timestamp}


@dataclass(frozen=True)
class CandidateAssessment:
    """Governed semantic decisions, intentionally separate from detected facts."""

    status: str = "unassessed"
    semantic_target: str | None = None
    authority_classification: str | None = None
    replacement_scope: tuple[str, ...] = ()
    rationale: str | None = None
    confidence: str | None = None
    evidence: tuple[str, ...] = ()
    approval: AssessmentApproval | None = None
    assessed_sha256: str | None = None
    distinct_grain_statement: str | None = None
    implemented_model_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "replacement_scope": list(self.replacement_scope),
            "evidence": list(self.evidence),
        }
        for key in (
            "semantic_target",
            "authority_classification",
            "rationale",
            "confidence",
            "assessed_sha256",
            "distinct_grain_statement",
            "implemented_model_name",
        ):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        if self.approval is not None:
            result["approval"] = self.approval.to_dict()
        return result


@dataclass(frozen=True)
class TransformationCandidate:
    """One stable path identity with facts and a separately governed assessment."""

    id: str
    facts: CandidateFacts
    assessment: CandidateAssessment = field(default_factory=CandidateAssessment)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "facts": self.facts.to_dict(),
            "assessment": self.assessment.to_dict(),
        }


@dataclass(frozen=True)
class CandidateInventory:
    """Committed non-executable candidate authority."""

    roots: tuple[str, ...] = ()
    candidates: tuple[TransformationCandidate, ...] = ()
    schema_version: int = SCHEMA_VERSION
    projection_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "projection_authority": self.projection_authority,
            "roots": list(self.roots),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class CandidateReadiness:
    """Readiness of one candidate for a requested lifecycle checkpoint."""

    id: str
    status: str
    is_blocking: bool
    requires_assessment: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "is_blocking": self.is_blocking,
            "requires_assessment": self.requires_assessment,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class TransformationReadinessReport:
    """Deterministic, non-writing mapping/Silver or release readiness report."""

    stage: str
    inventory_exists: bool
    candidates: tuple[CandidateReadiness, ...] = ()

    @property
    def is_blocking(self) -> bool:
        return any(item.is_blocking for item in self.candidates)

    @property
    def assessment_required(self) -> bool:
        return any(item.requires_assessment for item in self.candidates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "inventory_exists": self.inventory_exists,
            "is_blocking": self.is_blocking,
            "assessment_required": self.assessment_required,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def inventory_path(hub_root: Path) -> Path:
    """Return the canonical planning artifact path."""
    return Path(hub_root) / INVENTORY_RELPATH


def _string(value: object, context: str, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TransformationCandidateError(f"{context} must be a non-empty string")
    return value.strip()


def _string_tuple(value: object, context: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise TransformationCandidateError(f"{context} must be a list of non-empty strings")
    return tuple(value)


def _parse_assessment(data: object, context: str) -> CandidateAssessment:
    if data is None:
        return CandidateAssessment()
    if not isinstance(data, dict):
        raise TransformationCandidateError(f"{context} must be a mapping")
    status = _string(data.get("status", "unassessed"), f"{context}.status", required=True)
    assert status is not None
    if status not in ASSESSMENT_STATUSES:
        raise TransformationCandidateError(
            f"{context}.status must be one of {sorted(ASSESSMENT_STATUSES)}"
        )
    confidence = _string(data.get("confidence"), f"{context}.confidence")
    if confidence is not None and confidence not in CONFIDENCES:
        raise TransformationCandidateError(
            f"{context}.confidence must be one of {sorted(CONFIDENCES)}"
        )
    rationale = _string(data.get("rationale"), f"{context}.rationale")
    if status != "unassessed" and rationale is None:
        raise TransformationCandidateError(f"{context}.rationale is required for {status}")
    semantic_target = _string(data.get("semantic_target"), f"{context}.semantic_target")
    authority = _string(
        data.get("authority_classification"), f"{context}.authority_classification"
    )
    if authority is not None and authority not in AUTHORITY_CLASSIFICATIONS:
        raise TransformationCandidateError(
            f"{context}.authority_classification must be one of "
            f"{sorted(AUTHORITY_CLASSIFICATIONS)}"
        )
    replacement_scope = _string_tuple(
        data.get("replacement_scope"), f"{context}.replacement_scope"
    )
    for index, iri in enumerate(replacement_scope):
        parsed = urlparse(iri)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise TransformationCandidateError(
                f"{context}.replacement_scope[{index}] must be an absolute HTTP(S) IRI"
            )
    if len(set(replacement_scope)) != len(replacement_scope):
        raise TransformationCandidateError(
            f"{context}.replacement_scope must not contain duplicates"
        )
    if authority == "downstream-target" and replacement_scope:
        raise TransformationCandidateError(
            f"{context}.replacement_scope is forbidden for downstream-target evidence"
        )
    distinct_grain = _string(
        data.get("distinct_grain_statement"), f"{context}.distinct_grain_statement"
    )
    if status == "deferred" and distinct_grain is None:
        raise TransformationCandidateError(
            f"{context}.distinct_grain_statement is required for deferred"
        )
    assessed_sha256 = _string(
        data.get("assessed_sha256"), f"{context}.assessed_sha256"
    )
    if assessed_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", assessed_sha256):
        raise TransformationCandidateError(
            f"{context}.assessed_sha256 must be a lowercase SHA-256 digest"
        )
    if status != "unassessed" and assessed_sha256 is None:
        raise TransformationCandidateError(
            f"{context}.assessed_sha256 is required for {status}"
        )
    implemented_model_name = _string(
        data.get("implemented_model_name"), f"{context}.implemented_model_name"
    )
    if status == "implemented" and implemented_model_name is None:
        raise TransformationCandidateError(
            f"{context}.implemented_model_name is required for implemented"
        )
    if status in {"accepted", "implemented"}:
        if semantic_target is None:
            raise TransformationCandidateError(
                f"{context}.semantic_target is required for {status}"
            )
        parsed_target = urlparse(semantic_target)
        if parsed_target.scheme not in {"http", "https"} or not parsed_target.netloc:
            raise TransformationCandidateError(
                f"{context}.semantic_target must be an absolute HTTP(S) IRI"
            )
        if authority is None:
            raise TransformationCandidateError(
                f"{context}.authority_classification is required for {status}"
            )
        if confidence is None:
            raise TransformationCandidateError(
                f"{context}.confidence is required for {status}"
            )
        if not data.get("evidence"):
            raise TransformationCandidateError(
                f"{context}.evidence is required for {status}"
            )
    approval_data = data.get("approval")
    approval = None
    if approval_data is not None:
        if not isinstance(approval_data, dict):
            raise TransformationCandidateError(f"{context}.approval must be a mapping")
        actor = _string(approval_data.get("actor"), f"{context}.approval.actor", required=True)
        timestamp = _string(
            approval_data.get("timestamp"), f"{context}.approval.timestamp", required=True
        )
        assert actor is not None and timestamp is not None
        try:
            datetime.fromisoformat(timestamp)
        except ValueError as exc:
            raise TransformationCandidateError(
                f"{context}.approval.timestamp must be ISO 8601"
            ) from exc
        approval = AssessmentApproval(actor, timestamp)
    if status in {"accepted", "implemented"} and approval is None:
        raise TransformationCandidateError(f"{context}.approval is required for {status}")
    return CandidateAssessment(
        status=status,
        semantic_target=semantic_target,
        authority_classification=authority,
        replacement_scope=replacement_scope,
        rationale=rationale,
        confidence=confidence,
        evidence=_string_tuple(data.get("evidence"), f"{context}.evidence"),
        approval=approval,
        assessed_sha256=assessed_sha256,
        distinct_grain_statement=distinct_grain,
        implemented_model_name=implemented_model_name,
    )


def load_candidate_inventory(hub_root: Path) -> CandidateInventory | None:
    """Load and validate the committed inventory, or return ``None`` when absent."""
    path = inventory_path(hub_root)
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise TransformationCandidateError(f"{path}: could not read inventory: {exc}") from exc
    if not isinstance(data, dict):
        raise TransformationCandidateError(f"{path}: inventory must be a mapping")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise TransformationCandidateError(f"{path}: schema_version must be {SCHEMA_VERSION}")
    if data.get("projection_authority") is not False:
        raise TransformationCandidateError(f"{path}: projection_authority must be false")
    roots = _string_tuple(data.get("roots"), f"{path}.roots")
    raw_candidates = data.get("candidates")
    if not isinstance(raw_candidates, list):
        raise TransformationCandidateError(f"{path}.candidates must be a list")
    candidates: list[TransformationCandidate] = []
    ids: set[str] = set()
    for index, raw in enumerate(raw_candidates):
        context = f"{path}.candidates[{index}]"
        if not isinstance(raw, dict) or not isinstance(raw.get("facts"), dict):
            raise TransformationCandidateError(f"{context} and its facts must be mappings")
        candidate_id = _string(raw.get("id"), f"{context}.id", required=True)
        assert candidate_id is not None
        facts_data = raw["facts"]
        artifact_path = _string(
            facts_data.get("artifact_path"), f"{context}.facts.artifact_path", required=True
        )
        assert artifact_path is not None
        candidate_path = Path(candidate_id)
        if (
            candidate_id != artifact_path
            or candidate_path.is_absolute()
            or candidate_path.as_posix() != candidate_id
            or ".." in candidate_path.parts
        ):
            raise TransformationCandidateError(
                f"{context}.id must equal the normalized repository-relative artifact path"
            )
        if candidate_id in ids:
            raise TransformationCandidateError(f"{context}: duplicate id {candidate_id!r}")
        ids.add(candidate_id)
        references_data = facts_data.get("resource_references", [])
        if not isinstance(references_data, list):
            raise TransformationCandidateError(
                f"{context}.facts.resource_references must be a list"
            )
        references: list[ResourceReference] = []
        for ref_index, reference in enumerate(references_data):
            ref_context = f"{context}.facts.resource_references[{ref_index}]"
            if not isinstance(reference, dict):
                raise TransformationCandidateError(f"{ref_context} must be a mapping")
            kind = _string(reference.get("kind"), f"{ref_context}.kind", required=True)
            name = _string(reference.get("name"), f"{ref_context}.name", required=True)
            assert kind is not None and name is not None
            references.append(ResourceReference(kind, name))
        sha256 = _string(facts_data.get("sha256"), f"{context}.facts.sha256", required=True)
        model_name = _string(
            facts_data.get("proposed_model_name"),
            f"{context}.facts.proposed_model_name",
            required=True,
        )
        assert sha256 is not None and model_name is not None
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise TransformationCandidateError(
                f"{context}.facts.sha256 must be a lowercase SHA-256 digest"
            )
        present = facts_data.get("present", True)
        if not isinstance(present, bool):
            raise TransformationCandidateError(f"{context}.facts.present must be boolean")
        facts = CandidateFacts(
            artifact_path=artifact_path,
            sha256=sha256,
            proposed_model_name=model_name,
            resource_references=tuple(sorted(references)),
            detected_operations=tuple(
                sorted(
                    _string_tuple(
                        facts_data.get("detected_operations"),
                        f"{context}.facts.detected_operations",
                    )
                )
            ),
            declared_grain=_string(
                facts_data.get("declared_grain"), f"{context}.facts.declared_grain"
            ),
            present=present,
        )
        candidates.append(
            TransformationCandidate(
                id=candidate_id,
                facts=facts,
                assessment=_parse_assessment(raw.get("assessment"), f"{context}.assessment"),
            )
        )
    return CandidateInventory(
        roots=roots,
        candidates=tuple(sorted(candidates, key=lambda item: item.id)),
    )


def write_candidate_inventory(hub_root: Path, inventory: CandidateInventory) -> Path:
    """Write deterministic planning YAML with no executable projection authority."""
    if inventory.projection_authority:
        raise TransformationCandidateError("projection_authority must remain false")
    path = inventory_path(hub_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.safe_dump(inventory.to_dict(), sort_keys=False, allow_unicode=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def _repo_relative(path: Path, repository_root: Path) -> str:
    try:
        return path.relative_to(repository_root).as_posix()
    except ValueError as exc:
        raise TransformationCandidateError(
            f"artifact root must be inside repository {repository_root}: {path}"
        ) from exc


def _safe_root(root: Path, repository_root: Path) -> Path:
    lexical = root if root.is_absolute() else repository_root / root
    if not lexical.exists():
        raise TransformationCandidateError(f"artifact root does not exist: {lexical}")
    if lexical.is_symlink():
        raise TransformationCandidateError(f"symlink artifact roots are not allowed: {lexical}")
    resolved = lexical.resolve()
    _repo_relative(resolved, repository_root)
    if not (resolved.is_dir() or resolved.suffix.lower() == ".sql"):
        raise TransformationCandidateError(
            f"artifact root must be a directory or .sql file: {lexical}"
        )
    return resolved


def _dbt_model_roots(root: Path) -> tuple[Path, ...]:
    project_file = root / "dbt_project.yml"
    if not project_file.is_file():
        models = root / "models"
        return (models,) if models.is_dir() else (root,)
    try:
        project = yaml.safe_load(project_file.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise TransformationCandidateError(f"{project_file}: invalid dbt project: {exc}") from exc
    paths = project.get("model-paths", ["models"])
    if not isinstance(paths, list) or any(not isinstance(item, str) for item in paths):
        raise TransformationCandidateError(f"{project_file}: model-paths must be a list")
    model_roots: list[Path] = []
    for item in paths:
        candidate = root / item
        if not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        if not resolved.is_relative_to(root):
            raise TransformationCandidateError(
                f"{project_file}: model path escapes the explicit artifact root: {item!r}"
            )
        model_roots.append(resolved)
    return tuple(model_roots)


def _candidate_files(root: Path, repository_root: Path) -> tuple[Path, ...]:
    if root.is_file():
        paths = [root]
    else:
        paths = [
            path for model_root in _dbt_model_roots(root) for path in model_root.rglob("*.sql")
        ]
    result: list[Path] = []
    for path in sorted(paths):
        if path.is_symlink():
            raise TransformationCandidateError(f"symlink model artifacts are not allowed: {path}")
        resolved = path.resolve()
        _repo_relative(resolved, repository_root)
        relative_parts = {part.lower() for part in resolved.relative_to(repository_root).parts}
        if relative_parts & _EXCLUDED_PARTS:
            continue
        result.append(resolved)
    return tuple(result)


def _declared_grains(root: Path) -> dict[str, str]:
    directory = root.parent if root.is_file() else root
    grains: dict[str, str] = {}
    for path in sorted([*directory.rglob("*.yml"), *directory.rglob("*.yaml")]):
        if {part.lower() for part in path.parts} & _EXCLUDED_PARTS:
            continue
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(document, dict) or not isinstance(document.get("models"), list):
            continue
        for model in document["models"]:
            if not isinstance(model, dict) or not isinstance(model.get("name"), str):
                continue
            meta = model.get("meta")
            kairos = meta.get("kairos") if isinstance(meta, dict) else None
            grain = kairos.get("grain") if isinstance(kairos, dict) else None
            if isinstance(grain, str) and grain.strip():
                grains[model["name"]] = grain.strip()
    return grains


def _analyze_sql(path: Path, repository_root: Path, grain: str | None) -> CandidateFacts:
    content = path.read_bytes()
    try:
        sql = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TransformationCandidateError(f"{path}: SQL must be UTF-8 text: {exc}") from exc
    references = {
        *(ResourceReference("ref", name) for name in _REF_RE.findall(sql)),
        *(
            ResourceReference("source", f"{system}.{table}")
            for system, table in _SOURCE_RE.findall(sql)
        ),
        *(ResourceReference("relation", name) for name in _RELATION_RE.findall(sql)),
    }
    lowered = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL).lower()
    operations: set[str] = set()
    signals = {
        "aggregate": r"\bgroup\s+by\b|\b(?:sum|count|avg|min|max)\s*\(",
        "join": r"\bjoin\b",
        "json_expansion": r"\b(json_|flatten\s*\(|explode\s*\(|openjson\b)",
        "union": r"\bunion(?:\s+all)?\b",
        "window": r"\bover\s*\(",
    }
    for operation, pattern in signals.items():
        if re.search(pattern, lowered):
            operations.add(operation)
    relative = _repo_relative(path, repository_root)
    return CandidateFacts(
        artifact_path=relative,
        sha256=hashlib.sha256(content).hexdigest(),
        proposed_model_name=path.stem,
        resource_references=tuple(sorted(references)),
        detected_operations=tuple(sorted(operations)),
        declared_grain=grain,
    )


def inventory_transformation_candidates(
    hub_root: Path,
    artifact_roots: tuple[Path, ...] | list[Path],
    *,
    repository_root: Path | None = None,
) -> CandidateInventory:
    """Scan only explicit repository-contained roots and preserve path-bound decisions."""
    hub_root = Path(hub_root).resolve()
    repository_root = Path(repository_root or hub_root).resolve()
    if not repository_root.is_dir() or not artifact_roots:
        raise TransformationCandidateError(
            "repository root and at least one artifact root are required"
        )
    roots = tuple(_safe_root(Path(root), repository_root) for root in artifact_roots)
    if not hub_root.is_relative_to(repository_root):
        raise TransformationCandidateError("hub root must be inside the repository root")
    existing = load_candidate_inventory(hub_root)
    previous = {item.id: item for item in existing.candidates} if existing else {}
    found: dict[str, TransformationCandidate] = {}
    for root in roots:
        grains = _declared_grains(root)
        for path in _candidate_files(root, repository_root):
            facts = _analyze_sql(path, repository_root, grains.get(path.stem))
            if facts.artifact_path in found:
                raise TransformationCandidateError(
                    f"duplicate candidate identity from overlapping roots: {facts.artifact_path}"
                )
            prior = previous.get(facts.artifact_path)
            found[facts.artifact_path] = TransformationCandidate(
                id=facts.artifact_path,
                facts=facts,
                assessment=prior.assessment if prior is not None else CandidateAssessment(),
            )
    for candidate_id, prior in previous.items():
        if candidate_id in found:
            continue
        orphan_facts = CandidateFacts(
            artifact_path=prior.facts.artifact_path,
            sha256=prior.facts.sha256,
            proposed_model_name=prior.facts.proposed_model_name,
            resource_references=prior.facts.resource_references,
            detected_operations=prior.facts.detected_operations,
            declared_grain=prior.facts.declared_grain,
            present=False,
        )
        found[candidate_id] = TransformationCandidate(
            id=candidate_id,
            facts=orphan_facts,
            assessment=prior.assessment,
        )
    return CandidateInventory(
        roots=tuple(sorted(_repo_relative(root, repository_root) for root in roots)),
        candidates=tuple(found[key] for key in sorted(found)),
    )


def _implemented_models(
    hub_root: Path,
) -> tuple[dict[str, DbtContractModel], str | None]:
    transforms = hub_root / "integration" / "transforms" / "dbt"
    if not transforms.is_dir():
        return {}, None
    try:
        contracts = discover_dbt_contracts(transforms, hub_root)
        return {model.name: model for model in contracts}, None
    except DbtContractError as exc:
        return {}, str(exc)


def _replacement_completion_reasons(
    hub_root: Path,
    candidate: TransformationCandidate,
    contract: DbtContractModel,
) -> tuple[str, ...]:
    """Reuse canonical completeness facts for an implemented replacement."""
    expected_scope = set(candidate.assessment.replacement_scope)
    reasons: list[str] = []
    if not expected_scope:
        return ()
    completeness = compute_completeness_facts(
        analysis_dir=hub_root / "integration" / "sources" / "_analysis",
        claims_dir=hub_root / "model" / "claims",
        sources_dir=hub_root / "integration" / "sources",
        mappings_dir=hub_root / "model" / "mappings",
        extensions_dir=hub_root / "model" / "extensions",
        hub_root=hub_root,
        transforms_dir=hub_root / "integration" / "transforms" / "dbt",
    )
    for table_iri in sorted(expected_scope):
        matches = [fact for fact in completeness.tables if table_iri in fact.source_table_iris]
        if len(matches) != 1:
            reasons.append(
                f"replacement source {table_iri!r} is not uniquely governed by completeness facts"
            )
            continue
        mapping = matches[0].mapping
        if not mapping.replacement.covered:
            detail = "; ".join(mapping.replacement.reasons or mapping.reasons)
            reasons.append(
                f"replacement source {table_iri!r} is incomplete"
                + (f": {detail}" if detail else "")
            )
        if mapping.direct or mapping.direct_in_registry_domain:
            reasons.append(
                f"replacement source {table_iri!r} has conflicting direct mapping authority"
            )
    return tuple(reasons)


def evaluate_transformation_readiness(
    hub_root: Path,
    *,
    stage: str,
    table_scope: tuple[str, ...] | list[str] = (),
) -> TransformationReadinessReport:
    """Evaluate governed readiness without modifying the inventory or hub."""
    if stage not in {"mapping", "silver", "release"}:
        raise TransformationCandidateError("stage must be mapping, silver, or release")
    hub_root = Path(hub_root).resolve()
    inventory = load_candidate_inventory(hub_root)
    if inventory is None:
        return TransformationReadinessReport(stage=stage, inventory_exists=False)
    implemented_models, contract_error = _implemented_models(hub_root)
    sync_error = None
    try:
        sync_report = sync_dbt_contracts(hub_root, check=True)
        if sync_report.has_drift:
            sync_error = "managed virtual-source vocabulary is missing or stale"
    except (DbtContractError, DbtContractSyncError) as exc:
        sync_error = str(exc)
    scoped_tables = set(table_scope)
    results: list[CandidateReadiness] = []
    for candidate in inventory.candidates:
        assessment = candidate.assessment
        overlapping = not scoped_tables or bool(scoped_tables & set(assessment.replacement_scope))
        stale = (
            assessment.status != "unassessed"
            and assessment.assessed_sha256 != candidate.facts.sha256
        )
        advanced = bool(set(candidate.facts.detected_operations) & ADVANCED_OPERATIONS)
        requires_assessment = assessment.status == "unassessed" and (
            advanced
            or candidate.facts.declared_grain is not None
            or bool(assessment.replacement_scope)
            or not candidate.facts.present
        )
        reasons: list[str] = []
        blocking = False
        if not candidate.facts.present:
            reasons.append("artifact is orphaned; relink or retire its assessment explicitly")
            blocking = overlapping and assessment.status not in {"unassessed", "rejected"}
        if stale:
            reasons.append("artifact checksum changed after assessment")
            blocking = True
        if requires_assessment:
            reasons.append("candidate evidence requires governed assessment")
            blocking = True
        if assessment.status == "deferred":
            if not assessment.rationale or not assessment.distinct_grain_statement:
                reasons.append(
                    "deferred candidate requires rationale and a distinct-grain statement"
                )
                blocking = True
        if assessment.status == "accepted":
            reasons.append("accepted candidate has not yet been implemented as a dbt contract")
            blocking = stage in {"silver", "release"} or (
                overlapping and bool(assessment.replacement_scope)
            )
        if assessment.status == "implemented":
            assert assessment.implemented_model_name is not None
            model_name = assessment.implemented_model_name
            contract = implemented_models.get(model_name)
            if contract is None:
                detail = f": {contract_error}" if contract_error else ""
                reasons.append(f"implemented candidate has no discovered dbt contract{detail}")
                blocking = True
            else:
                actual_scope = {replacement.table_iri for replacement in contract.replaces_sources}
                if set(assessment.replacement_scope) != actual_scope:
                    reasons.append(
                        "candidate replacement scope does not match the discovered dbt contract"
                    )
                    blocking = True
                if sync_error is not None:
                    reasons.append(sync_error)
                    blocking = True
            if contract is not None and not blocking and stage in {"silver", "release"}:
                completion_reasons = _replacement_completion_reasons(
                    hub_root,
                    candidate,
                    contract,
                )
                reasons.extend(completion_reasons)
                blocking = blocking or bool(completion_reasons)
        results.append(
            CandidateReadiness(
                id=candidate.id,
                status=assessment.status,
                is_blocking=blocking,
                requires_assessment=requires_assessment or stale,
                reasons=tuple(reasons),
            )
        )
    return TransformationReadinessReport(
        stage=stage,
        inventory_exists=True,
        candidates=tuple(results),
    )
