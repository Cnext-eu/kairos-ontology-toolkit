# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Discovery and validation for governed custom dbt transformation contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml
from rdflib import Graph, URIRef

SUPPORTED_MATERIALIZATIONS = frozenset({"table", "view", "incremental"})
SUPPORTED_ADAPTERS = frozenset({"fabric", "databricks"})
DECISION_CONFIDENCES = frozenset({"low", "medium", "high"})
DECISION_STATUSES = frozenset(
    {
        "proposed",
        "ai_approved",
        "developer_approved",
        "stakeholder_approved",
        "rejected",
        "superseded",
    }
)
APPROVED_DECISION_STATUSES = frozenset(
    {"ai_approved", "developer_approved", "stakeholder_approved"}
)

# These constraints are owned by the toolkit's generated packages.yml.
APPROVED_DBT_PACKAGES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "dbt-labs/dbt_utils": (">=1.0.0", "<2.0.0"),
        "metaplane/dbt_expectations": (">=0.10.0", "<1.0.0"),
    }
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DECISION_ID_RE = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_MACRO_RE = re.compile(r"^(?!kairos_)[a-z][a-z0-9_]*__[a-z][a-z0-9_]*$")
_RDF_SUFFIXES = frozenset({".ttl", ".rdf", ".xml", ".nt", ".n3", ".trig", ".jsonld"})


class DbtContractError(ValueError):
    """Raised when a custom dbt contract or its bundle is invalid."""


@dataclass(frozen=True)
class DbtContractColumn:
    """One physical output column in a contracted dbt model."""

    name: str
    data_type: str
    description: str | None = None


@dataclass(frozen=True)
class DbtDecisionEvidence:
    """Repository evidence supporting a transformation decision."""

    artifact: str
    subject: str | None = None


@dataclass(frozen=True)
class DbtDecisionApproval:
    """Approval attached to an approved transformation decision."""

    actor: str
    timestamp: datetime


@dataclass(frozen=True)
class DbtContractDecision:
    """Governance provenance for one non-trivial transformation rule."""

    id: str
    statement: str
    evidence: tuple[DbtDecisionEvidence, ...]
    confidence: str
    status: str
    approval: DbtDecisionApproval | None
    implemented_by_model: str
    verified_by: tuple[str, ...]


@dataclass(frozen=True)
class DbtSourceReplacement:
    """Governed replacement of one canonical Bronze source table."""

    table_iri: str


@dataclass(frozen=True)
class DbtContractModel:
    """A fully resolved custom dbt model contract."""

    name: str
    description: str
    materialization: str
    target_class: str
    virtual_source_iri: str
    grain: str
    supported_adapters: tuple[str, ...]
    natural_key: tuple[str, ...]
    required_packages: tuple[str, ...]
    required_macros: tuple[str, ...]
    columns: tuple[DbtContractColumn, ...]
    decisions: tuple[DbtContractDecision, ...]
    properties_path: Path
    sql_path: Path
    replaces_sources: tuple[DbtSourceReplacement, ...] = ()


def _error(path: Path, message: str) -> DbtContractError:
    return DbtContractError(f"{path}: {message}")


def _is_http_iri(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _required_string(data: dict[str, Any], key: str, path: Path, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _error(path, f"{context}.{key} must be a non-empty string")
    return value.strip()


def _string_list(
    value: object,
    path: Path,
    context: str,
    *,
    non_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or (non_empty and not value):
        qualifier = "a non-empty list" if non_empty else "a list"
        raise _error(path, f"{context} must be {qualifier} of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _error(path, f"{context} must contain only non-empty strings")
        result.append(item.strip())
    return tuple(result)


def _safe_existing_file(hub_root: Path, relative: str, source_path: Path) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise _error(source_path, f"evidence artifact path is unsafe: {relative!r}")
    resolved = (hub_root / candidate).resolve()
    if not resolved.is_relative_to(hub_root) or not resolved.is_file():
        raise _error(
            source_path,
            f"evidence artifact does not resolve to a repository file: {relative!r}",
        )
    return resolved


def _validate_bundle_paths(transforms_dir: Path, hub_root: Path) -> tuple[Path, Path]:
    hub_root = hub_root.resolve()
    transforms_dir = transforms_dir.resolve()
    if not transforms_dir.is_relative_to(hub_root):
        raise DbtContractError(
            f"{transforms_dir}: transforms directory must be inside hub root {hub_root}"
        )
    if not transforms_dir.is_dir():
        raise DbtContractError(f"{transforms_dir}: transforms directory does not exist")

    allowed = {
        "models": frozenset({".sql", ".yml", ".yaml"}),
        "macros": frozenset({".sql"}),
        "tests": frozenset({".sql"}),
    }
    for path in transforms_dir.rglob("*"):
        relative = path.relative_to(transforms_dir)
        if relative == Path("README.md"):
            continue
        if not relative.parts or relative.parts[0] not in allowed:
            raise _error(path, "file is outside the permitted models/, macros/, or tests/ paths")
        resolved = path.resolve()
        if not resolved.is_relative_to(transforms_dir):
            raise _error(path, "symlink escapes the custom dbt transforms directory")
        if path.is_dir():
            continue
        if path.suffix.lower() not in allowed[relative.parts[0]]:
            raise _error(path, f"unsupported file type {path.suffix!r}")
        if not resolved.is_file():
            raise _error(path, "path does not resolve to a regular file")
    return transforms_dir, hub_root


def _load_properties(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise _error(path, f"could not parse YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise _error(path, "dbt properties document must be a mapping")
    if loaded.get("version") != 2:
        raise _error(path, "dbt properties document must declare version: 2")
    models = loaded.get("models", [])
    if not isinstance(models, list):
        raise _error(path, "'models' must be a list")
    return loaded


def _declared_test_names(transforms_dir: Path, documents: list[dict[str, Any]]) -> set[str]:
    names = {path.stem for path in (transforms_dir / "tests").rglob("*.sql")}
    for document in documents:
        for unit_test in document.get("unit_tests", []):
            if isinstance(unit_test, dict) and isinstance(unit_test.get("name"), str):
                names.add(unit_test["name"])
        for model in document.get("models", []):
            if not isinstance(model, dict):
                continue
            for holder in [model, *[c for c in model.get("columns", []) if isinstance(c, dict)]]:
                tests = holder.get("data_tests", holder.get("tests", []))
                if not isinstance(tests, list):
                    continue
                for test in tests:
                    if isinstance(test, dict):
                        explicit_name = test.get("name")
                        if isinstance(explicit_name, str):
                            names.add(explicit_name)
                        for definition in test.values():
                            if isinstance(definition, dict):
                                explicit_name = definition.get("name")
                                if isinstance(explicit_name, str):
                                    names.add(explicit_name)
    return names


def _parse_columns(model: dict[str, Any], path: Path, name: str) -> tuple[DbtContractColumn, ...]:
    raw_columns = model.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        raise _error(path, f"model {name!r} must declare a non-empty columns list")
    columns: list[DbtContractColumn] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_columns):
        context = f"model {name!r} columns[{index}]"
        if not isinstance(raw, dict):
            raise _error(path, f"{context} must be a mapping")
        column_name = _required_string(raw, "name", path, context)
        data_type = _required_string(raw, "data_type", path, context)
        if not _IDENTIFIER_RE.fullmatch(column_name):
            raise _error(path, f"{context}.name is not a valid dbt identifier: {column_name!r}")
        folded = column_name.casefold()
        if folded in seen:
            raise _error(path, f"model {name!r} has duplicate output column {column_name!r}")
        seen.add(folded)
        description = raw.get("description")
        if description is not None and not isinstance(description, str):
            raise _error(path, f"{context}.description must be a string")
        columns.append(DbtContractColumn(column_name, data_type, description))
    return tuple(columns)


def _parse_source_replacements(
    raw: object,
    path: Path,
    name: str,
) -> tuple[DbtSourceReplacement, ...]:
    """Parse asserted source replacements without resolving repository RDF."""

    if raw is None:
        return ()
    context = f"model {name!r}.meta.kairos.replaces_sources"
    if not isinstance(raw, list) or not raw:
        raise _error(path, f"{context} must be a non-empty list of mappings")

    replacements: list[DbtSourceReplacement] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        item_context = f"{context}[{index}]"
        if not isinstance(item, dict):
            raise _error(path, f"{item_context} must be a mapping")
        unknown = sorted(set(item) - {"table_iri"})
        if unknown:
            raise _error(path, f"{item_context} contains unknown keys {unknown}")
        table_iri = _required_string(item, "table_iri", path, item_context)
        if not _is_http_iri(table_iri):
            raise _error(path, f"{item_context}.table_iri must be an absolute HTTP(S) IRI")
        if table_iri in seen:
            raise _error(path, f"{context} contains duplicate table_iri {table_iri!r}")
        seen.add(table_iri)
        replacements.append(DbtSourceReplacement(table_iri))
    return tuple(replacements)


def _parse_approval(
    raw: object,
    path: Path,
    context: str,
    required: bool,
) -> DbtDecisionApproval | None:
    if raw is None:
        if required:
            raise _error(path, f"{context}.approval is required for an approved decision")
        return None
    if not isinstance(raw, dict):
        raise _error(path, f"{context}.approval must be a mapping")
    actor = _required_string(raw, "actor", path, f"{context}.approval")
    timestamp_value = raw.get("timestamp")
    if isinstance(timestamp_value, datetime):
        timestamp = timestamp_value
    elif isinstance(timestamp_value, str):
        try:
            timestamp = datetime.fromisoformat(timestamp_value)
        except ValueError as exc:
            raise _error(path, f"{context}.approval.timestamp must be ISO 8601") from exc
    else:
        raise _error(path, f"{context}.approval.timestamp must be ISO 8601")
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise _error(path, f"{context}.approval.timestamp must include a timezone")
    return DbtDecisionApproval(actor, timestamp)


def _parse_evidence(
    raw: object,
    path: Path,
    context: str,
    hub_root: Path,
) -> tuple[DbtDecisionEvidence, ...]:
    if not isinstance(raw, list) or not raw:
        raise _error(path, f"{context}.evidence must be a non-empty list")
    result: list[DbtDecisionEvidence] = []
    for index, item in enumerate(raw):
        item_context = f"{context}.evidence[{index}]"
        if not isinstance(item, dict):
            raise _error(path, f"{item_context} must be a mapping")
        artifact = _required_string(item, "artifact", path, item_context)
        artifact_path = _safe_existing_file(hub_root, artifact, path)
        subject = item.get("subject")
        if subject is not None:
            if not _is_http_iri(subject):
                raise _error(path, f"{item_context}.subject must be an absolute HTTP(S) IRI")
            if artifact_path.suffix.lower() not in _RDF_SUFFIXES:
                raise _error(path, f"{item_context}.subject requires an RDF evidence artifact")
            try:
                graph = Graph()
                graph.parse(artifact_path)
            except Exception as exc:
                raise _error(path, f"could not parse RDF evidence {artifact!r}: {exc}") from exc
            if not any(graph.triples((URIRef(subject), None, None))):
                raise _error(path, f"RDF subject {subject!r} was not found in {artifact!r}")
        result.append(DbtDecisionEvidence(artifact, subject))
    return tuple(result)


def _parse_decisions(
    raw: object,
    path: Path,
    model_name: str,
    hub_root: Path,
    resource_names: set[str],
    test_names: set[str],
) -> tuple[DbtContractDecision, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _error(path, f"model {model_name!r} decisions must be a list")
    result: list[DbtContractDecision] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        context = f"model {model_name!r} decisions[{index}]"
        if not isinstance(item, dict):
            raise _error(path, f"{context} must be a mapping")
        decision_id = _required_string(item, "id", path, context)
        if not _DECISION_ID_RE.fullmatch(decision_id):
            raise _error(path, f"{context}.id is invalid: {decision_id!r}")
        if decision_id in seen:
            raise _error(path, f"model {model_name!r} has duplicate decision id {decision_id!r}")
        seen.add(decision_id)
        statement = _required_string(item, "statement", path, context)
        confidence = _required_string(item, "confidence", path, context)
        if confidence not in DECISION_CONFIDENCES:
            raise _error(
                path, f"{context}.confidence must be one of {sorted(DECISION_CONFIDENCES)}"
            )
        status = _required_string(item, "status", path, context)
        if status not in DECISION_STATUSES:
            raise _error(path, f"{context}.status must be one of {sorted(DECISION_STATUSES)}")
        evidence = _parse_evidence(item.get("evidence"), path, context, hub_root)
        approval = _parse_approval(
            item.get("approval"), path, context, status in APPROVED_DECISION_STATUSES
        )
        implemented = item.get("implemented_by")
        if not isinstance(implemented, dict):
            raise _error(path, f"{context}.implemented_by must be a mapping")
        implemented_model = _required_string(
            implemented, "model", path, f"{context}.implemented_by"
        )
        if implemented_model not in resource_names:
            raise _error(
                path, f"{context} references unknown implementing model {implemented_model!r}"
            )
        if implemented_model != model_name:
            raise _error(path, f"{context} must be implemented by model {model_name!r}")
        verified_by = _string_list(
            item.get("verified_by"), path, f"{context}.verified_by", non_empty=True
        )
        if len(set(verified_by)) != len(verified_by):
            raise _error(path, f"{context}.verified_by must contain unique test names")
        unknown_tests = sorted(set(verified_by) - test_names)
        if unknown_tests:
            raise _error(path, f"{context} references unknown verifying tests {unknown_tests}")
        result.append(
            DbtContractDecision(
                decision_id,
                statement,
                evidence,
                confidence,
                status,
                approval,
                implemented_model,
                verified_by,
            )
        )
    return tuple(result)


def _parse_contract(
    model: dict[str, Any],
    path: Path,
    sql_paths: dict[str, list[Path]],
    hub_root: Path,
    resource_names: set[str],
    test_names: set[str],
) -> DbtContractModel:
    name = _required_string(model, "name", path, "model")
    if not _IDENTIFIER_RE.fullmatch(name):
        raise _error(path, f"model name is not a valid dbt identifier: {name!r}")
    description = _required_string(model, "description", path, f"model {name!r}")
    config = model.get("config")
    if not isinstance(config, dict):
        raise _error(path, f"model {name!r}.config must be a mapping")
    materialization = _required_string(config, "materialized", path, f"model {name!r}.config")
    if materialization not in SUPPORTED_MATERIALIZATIONS:
        raise _error(
            path,
            f"model {name!r} materialization must be one of {sorted(SUPPORTED_MATERIALIZATIONS)}",
        )
    contract = config.get("contract")
    if not isinstance(contract, dict) or contract.get("enforced") is not True:
        raise _error(path, f"model {name!r} must set config.contract.enforced: true")
    if materialization == "incremental" and config.get("on_schema_change") not in {
        "append_new_columns",
        "fail",
    }:
        raise _error(
            path,
            f"incremental model {name!r} requires on_schema_change append_new_columns or fail",
        )

    meta = model["meta"]["kairos"]
    target_class = _required_string(meta, "target_class", path, f"model {name!r}.meta.kairos")
    virtual_source_iri = _required_string(
        meta, "virtual_source_iri", path, f"model {name!r}.meta.kairos"
    )
    for field_name, iri in (
        ("target_class", target_class),
        ("virtual_source_iri", virtual_source_iri),
    ):
        if not _is_http_iri(iri):
            raise _error(
                path,
                f"model {name!r} meta.kairos.{field_name} must be an absolute HTTP(S) IRI",
            )
    grain = _required_string(meta, "grain", path, f"model {name!r}.meta.kairos")
    adapters = _string_list(
        meta.get("supported_adapters"),
        path,
        f"model {name!r}.meta.kairos.supported_adapters",
        non_empty=True,
    )
    if len(set(adapters)) != len(adapters) or set(adapters) != SUPPORTED_ADAPTERS:
        raise _error(
            path,
            f"model {name!r} supported_adapters must declare both {sorted(SUPPORTED_ADAPTERS)}",
        )

    columns = _parse_columns(model, path, name)
    natural_key = _string_list(
        meta.get("natural_key"),
        path,
        f"model {name!r}.meta.kairos.natural_key",
        non_empty=True,
    )
    column_names = {column.name for column in columns}
    if len(set(natural_key)) != len(natural_key) or not set(natural_key) <= column_names:
        raise _error(path, f"model {name!r} natural_key must contain unique contract columns")

    packages = _string_list(
        meta.get("required_packages", []),
        path,
        f"model {name!r}.meta.kairos.required_packages",
    )
    if len(set(packages)) != len(packages):
        raise _error(path, f"model {name!r} required_packages contains duplicates")
    unknown_packages = sorted(set(packages) - APPROVED_DBT_PACKAGES.keys())
    if unknown_packages:
        raise _error(path, f"model {name!r} requires unapproved packages {unknown_packages}")

    macros = _string_list(
        meta.get("required_macros", []),
        path,
        f"model {name!r}.meta.kairos.required_macros",
    )
    if len(set(macros)) != len(macros) or any(not _MACRO_RE.fullmatch(macro) for macro in macros):
        raise _error(
            path,
            f"model {name!r} required macros must be unique and named "
            "<hub-or-domain>__<macro-name> without the reserved kairos_ prefix",
        )

    matches = sql_paths.get(name, [])
    if len(matches) != 1:
        raise _error(path, f"model {name!r} must resolve to exactly one matching model SQL")
    decisions = _parse_decisions(
        meta.get("decisions"), path, name, hub_root, resource_names, test_names
    )
    replaces_sources = _parse_source_replacements(meta.get("replaces_sources"), path, name)
    return DbtContractModel(
        name=name,
        description=description,
        materialization=materialization,
        target_class=target_class,
        virtual_source_iri=virtual_source_iri,
        grain=grain,
        supported_adapters=adapters,
        natural_key=natural_key,
        required_packages=packages,
        required_macros=macros,
        columns=columns,
        decisions=decisions,
        properties_path=path,
        sql_path=matches[0],
        replaces_sources=replaces_sources,
    )


def discover_dbt_contracts(transforms_dir: Path, hub_root: Path) -> tuple[DbtContractModel, ...]:
    """Discover and validate ``meta.kairos`` dbt model contracts.

    The function is read-only. Paths in returned contracts are absolute, resolved paths;
    evidence remains repository-relative so it is portable across hub checkouts.
    """

    transforms_dir, hub_root = _validate_bundle_paths(Path(transforms_dir), Path(hub_root))
    models_dir = transforms_dir / "models"
    yaml_paths = sorted([*models_dir.rglob("*.yml"), *models_dir.rglob("*.yaml")])
    documents = [_load_properties(path) for path in yaml_paths]

    resources: dict[str, Path] = {}
    selected: list[tuple[dict[str, Any], Path]] = []
    for path, document in zip(yaml_paths, documents, strict=True):
        for index, model in enumerate(document.get("models", [])):
            if not isinstance(model, dict):
                raise _error(path, f"models[{index}] must be a mapping")
            name = _required_string(model, "name", path, f"models[{index}]")
            if name in resources:
                raise _error(
                    path,
                    f"duplicate dbt model resource {name!r}; first declared in {resources[name]}",
                )
            resources[name] = path
            meta = model.get("meta")
            if isinstance(meta, dict) and "kairos" in meta:
                if not isinstance(meta["kairos"], dict):
                    raise _error(path, f"model {name!r}.meta.kairos must be a mapping")
                selected.append((model, path))

    sql_paths: dict[str, list[Path]] = {}
    for sql_path in models_dir.rglob("*.sql"):
        sql_paths.setdefault(sql_path.stem, []).append(sql_path.resolve())
    tests = _declared_test_names(transforms_dir, documents)
    contracts = [
        _parse_contract(model, path, sql_paths, hub_root, set(resources), tests)
        for model, path in selected
    ]
    return tuple(sorted(contracts, key=lambda item: item.name))
