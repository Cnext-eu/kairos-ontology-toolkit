# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Canonical dbt contract identity hashes and warehouse-test evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


EVIDENCE_SCHEMA = "https://kairos.cnext.eu/schemas/dbt-contract-identity-evidence/v2"
EVIDENCE_RELPATH = Path("integration/transforms/dbt/evidence/contract-identity.json")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ContractIdentityEvidenceError(ValueError):
    """Raised when supplied dbt result evidence is malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class ContractIdentityEvidence:
    """Passing warehouse evidence for one exact contracted model revision."""

    model: str
    contract_content_hash: str
    passed_requirements: tuple[str, ...]
    invocation_id: str
    generated_at: str
    artifact_content_fingerprint: str
    dbt_version: str


def canonical_contract_content(contract: Any) -> dict[str, Any]:
    """Return the deterministic identity-relevant contract and implementation content."""

    return {
        "model": contract.name,
        "materialization": contract.materialization,
        "target_class": contract.target_class,
        "virtual_source_iri": contract.virtual_source_iri,
        "grain": contract.grain,
        "grain_key": list(contract.grain_key),
        "columns": [
            {
                "name": column.name,
                "data_type": column.data_type,
                "not_null": column.not_null,
                "tests": list(column.tests),
            }
            for column in contract.columns
        ],
        "replaces_sources": [
            replacement.table_iri for replacement in contract.replaces_sources
        ],
        "canonical_cdc_bindings": dict(contract.canonical_cdc_bindings),
        "decisions": [
            {
                "id": decision.id,
                "status": decision.status,
                "confidence": decision.confidence,
                "evidence": [
                    {"artifact": item.artifact, "subject": item.subject}
                    for item in decision.evidence
                ],
                "verified_by": list(decision.verified_by),
            }
            for decision in contract.decisions
        ],
        "sql_sha256": hashlib.sha256(contract.sql_path.read_bytes()).hexdigest(),
    }


def contract_content_hash(contract: Any) -> str:
    """Hash the canonical contract, SQL, key, tests, CDC, lineage, and decisions."""

    payload = json.dumps(
        canonical_contract_content(contract),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def artifact_content_fingerprint(contract: Any) -> str:
    """Hash the complete authored files and canonical identity contract for one model."""

    payload = {
        "contract_content_hash": contract_content_hash(contract),
        "properties_sha256": _file_sha256(contract.properties_path),
        "sql_sha256": _file_sha256(contract.sql_path),
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def identity_requirements(contract: Any) -> tuple[str, ...]:
    """Return stable machine requirement IDs for contract-output identity."""

    return (
        f"unique:{','.join(contract.grain_key)}",
        *(f"not_null:{column}" for column in contract.grain_key),
    )


def load_evidence(hub_root: Path) -> tuple[ContractIdentityEvidence, ...]:
    """Load the committed deterministic evidence artifact, if present."""

    path = Path(hub_root) / EVIDENCE_RELPATH
    if not path.is_file():
        return ()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractIdentityEvidenceError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("$schema") != EVIDENCE_SCHEMA:
        raise ContractIdentityEvidenceError(f"{path}: unsupported or missing $schema")
    results = raw.get("results")
    if not isinstance(results, list):
        raise ContractIdentityEvidenceError(f"{path}: results must be a list")
    parsed: list[ContractIdentityEvidence] = []
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            raise ContractIdentityEvidenceError(f"{path}: results[{index}] must be an object")
        required = (
            "model",
            "contract_content_hash",
            "passed_requirements",
            "invocation_id",
            "artifact_content_fingerprint",
            "dbt_version",
        )
        if any(not item.get(key) for key in required):
            raise ContractIdentityEvidenceError(
                f"{path}: results[{index}] is missing required fields"
            )
        digest = item["contract_content_hash"]
        requirements = item["passed_requirements"]
        if (
            not isinstance(digest, str)
            or not _SHA256_RE.fullmatch(digest)
            or not _SHA256_RE.fullmatch(str(item["artifact_content_fingerprint"]))
            or not isinstance(requirements, list)
            or any(not isinstance(value, str) for value in requirements)
        ):
            raise ContractIdentityEvidenceError(f"{path}: results[{index}] has invalid fields")
        parsed.append(
            ContractIdentityEvidence(
                model=str(item["model"]),
                contract_content_hash=digest,
                passed_requirements=tuple(sorted(set(requirements))),
                invocation_id=str(item["invocation_id"]),
                generated_at=str(item.get("generated_at", "")),
                artifact_content_fingerprint=str(item["artifact_content_fingerprint"]),
                dbt_version=str(item["dbt_version"]),
            )
        )
    return tuple(sorted(parsed, key=lambda item: item.model))


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metadata(artifact: object, name: str) -> dict[str, Any]:
    if not isinstance(artifact, dict) or not isinstance(artifact.get("metadata"), dict):
        raise ContractIdentityEvidenceError(
            f"{name} lacks metadata; use matching dbt artifacts from the same invocation"
        )
    return artifact["metadata"]


def _invocation_metadata(
    run_results: object, manifest: object
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    run_meta = _metadata(run_results, "run_results.json")
    manifest_meta = _metadata(manifest, "manifest.json")
    run_invocation = run_meta.get("invocation_id")
    manifest_invocation = manifest_meta.get("invocation_id")
    if not isinstance(run_invocation, str) or not run_invocation.strip():
        raise ContractIdentityEvidenceError("run_results.json metadata.invocation_id is missing")
    if not isinstance(manifest_invocation, str) or not manifest_invocation.strip():
        raise ContractIdentityEvidenceError(
            "manifest.json metadata.invocation_id is missing; supply the manifest written "
            "by the same dbt invocation"
        )
    if run_invocation != manifest_invocation:
        raise ContractIdentityEvidenceError(
            "dbt artifact invocation mismatch: run_results.json and manifest.json have "
            "different metadata.invocation_id values"
        )
    run_version = run_meta.get("dbt_version")
    manifest_version = manifest_meta.get("dbt_version")
    if not isinstance(run_version, str) or not run_version.strip():
        raise ContractIdentityEvidenceError("run_results.json metadata.dbt_version is missing")
    if not isinstance(manifest_version, str) or not manifest_version.strip():
        raise ContractIdentityEvidenceError("manifest.json metadata.dbt_version is missing")
    if run_version != manifest_version:
        raise ContractIdentityEvidenceError(
            "dbt artifact version mismatch: run_results.json and manifest.json were produced "
            f"by dbt {run_version!r} and {manifest_version!r}"
        )
    manifest_schema = str(manifest_meta.get("dbt_schema_version", ""))
    if not manifest_schema.endswith("/manifest/v12.json"):
        raise ContractIdentityEvidenceError(
            "manifest.json must use the standard dbt manifest v12 schema"
        )
    results_schema = str(run_meta.get("dbt_schema_version", ""))
    if "/run-results/" not in results_schema:
        raise ContractIdentityEvidenceError(
            "run_results.json metadata.dbt_schema_version is missing or invalid"
        )
    return run_meta, manifest_meta, run_invocation, run_version


def _dbt_file_sha256(path: Path) -> str:
    """Return dbt's source-file hash (UTF-8 text after universal-newline decoding)."""

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractIdentityEvidenceError(f"could not read dbt source file {path}: {exc}") from exc
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _checksum_value(value: object) -> str | None:
    if isinstance(value, str) and _SHA256_RE.fullmatch(value.lower()):
        return value.lower()
    if not isinstance(value, dict):
        return None
    name = str(value.get("name", "")).lower()
    checksum = value.get("checksum")
    if name in {"sha256", "sha-256"} and isinstance(checksum, str):
        normalized = checksum.lower()
        if _SHA256_RE.fullmatch(normalized):
            return normalized
    return None


def _normalize_path(value: object) -> str:
    return str(value or "").replace("\\", "/").removeprefix("./")


def _require_source_node(
    node: dict[str, Any], source_path: Path, transforms: Path, *, kind: str
) -> None:
    try:
        expected_path = source_path.resolve().relative_to(transforms.resolve()).as_posix()
        current = source_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeError, ValueError) as exc:
        raise ContractIdentityEvidenceError(f"could not verify current {kind} source: {exc}") from exc
    if _normalize_path(node.get("original_file_path")) != expected_path:
        raise ContractIdentityEvidenceError(
            f"{kind} node has wrong original_file_path; expected {expected_path!r}"
        )
    raw_code = node.get("raw_code", node.get("raw_sql"))
    if not isinstance(raw_code, str) or raw_code.replace("\r\n", "\n") != current:
        raise ContractIdentityEvidenceError(
            f"{kind} node raw_code does not match the current source file"
        )
    if _checksum_value(node.get("checksum")) != _dbt_file_sha256(source_path):
        raise ContractIdentityEvidenceError(
            f"{kind} node checksum does not match dbt's SHA-256 of the current source file"
        )


def _mapping_subset(expected: object, actual: object) -> bool:
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return expected == actual
    return all(key in actual and _mapping_subset(value, actual[key]) for key, value in expected.items())


def _constraints_match(expected: object, actual: object) -> bool:
    return (
        isinstance(expected, list)
        and isinstance(actual, list)
        and len(expected) == len(actual)
        and all(_mapping_subset(left, right) for left, right in zip(expected, actual, strict=True))
    )


def _current_properties_model(contract: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        document = yaml.safe_load(contract.properties_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ContractIdentityEvidenceError(
            f"model {contract.name!r}: could not read current contract YAML: {exc}"
        ) from exc
    models = document.get("models") if isinstance(document, dict) else None
    matches = [
        item for item in models or [] if isinstance(item, dict) and item.get("name") == contract.name
    ]
    if len(matches) != 1:
        raise ContractIdentityEvidenceError(
            f"model {contract.name!r}: current YAML must contain exactly one model definition"
        )
    return document, matches[0]


def _verify_manifest_model_semantics(node: dict[str, Any], contract: Any) -> dict[str, Any]:
    document, authored = _current_properties_model(contract)
    for key, default in (("description", ""), ("meta", {})):
        if node.get(key, default) != authored.get(key, default):
            raise ContractIdentityEvidenceError(
                f"model {contract.name!r}: manifest {key} is stale or does not match current YAML"
            )
    authored_config = authored.get("config", {})
    if not _mapping_subset(authored_config, node.get("config")):
        raise ContractIdentityEvidenceError(
            f"model {contract.name!r}: manifest config/contract is stale or does not match "
            "current YAML"
        )
    if not _constraints_match(authored.get("constraints", []), node.get("constraints", [])):
        raise ContractIdentityEvidenceError(
            f"model {contract.name!r}: manifest model constraints do not match current YAML"
        )

    authored_columns = authored.get("columns", [])
    manifest_columns = node.get("columns")
    if not isinstance(manifest_columns, dict) or {
        item.get("name") for item in authored_columns if isinstance(item, dict)
    } != set(manifest_columns):
        raise ContractIdentityEvidenceError(
            f"model {contract.name!r}: manifest columns do not exactly match current YAML"
        )
    for column in authored_columns:
        name = column["name"]
        manifest_column = manifest_columns.get(name)
        if not isinstance(manifest_column, dict):
            raise ContractIdentityEvidenceError(
                f"model {contract.name!r}: manifest column {name!r} is missing"
            )
        for key, default in (
            ("name", name),
            ("description", ""),
            ("data_type", None),
            ("meta", {}),
            ("constraints", []),
        ):
            if key == "constraints":
                matches = _constraints_match(
                    column.get(key, default), manifest_column.get(key, default)
                )
            else:
                matches = manifest_column.get(key, default) == column.get(key, default)
            if not matches:
                raise ContractIdentityEvidenceError(
                    f"model {contract.name!r}: manifest column {name!r} {key} is stale or "
                    "does not match current YAML"
                )
    return document


def _model_node(nodes: dict[str, Any], model: str) -> tuple[str, dict[str, Any]]:
    matches = [
        (unique_id, node)
        for unique_id, node in nodes.items()
        if isinstance(node, dict)
        and node.get("resource_type") == "model"
        and node.get("name", str(node.get("unique_id", "")).split(".")[-1]) == model
    ]
    if len(matches) != 1:
        raise ContractIdentityEvidenceError(
            f"model {model!r}: manifest must contain exactly one matching model node; "
            f"found {len(matches)}"
        )
    return matches[0]


def _node_depends_on(node: dict[str, Any], model_unique_id: str) -> bool:
    dependencies = node.get("depends_on", {}).get("nodes", [])
    return isinstance(dependencies, list) and dependencies.count(model_unique_id) == 1


def _generic_test_declarations(model: dict[str, Any]) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    holders = [(model, None), *[(column, column.get("name")) for column in model.get("columns", [])]]
    for holder, column_name in holders:
        tests = holder.get("data_tests", holder.get("tests", []))
        for raw in tests:
            if isinstance(raw, str):
                declarations.append({"name": raw, "column_name": column_name, "args": {}, "config": {}})
                continue
            if not isinstance(raw, dict) or len(raw) != 1:
                continue
            name, details = next(iter(raw.items()))
            details = details if isinstance(details, dict) else {}
            arguments = details.get("arguments", {})
            args = dict(arguments) if isinstance(arguments, dict) else {}
            args.update(
                {
                    key: value
                    for key, value in details.items()
                    if key not in {"arguments", "config", "name"}
                }
            )
            declarations.append(
                {
                    "name": name,
                    "column_name": column_name,
                    "args": args,
                    "config": details.get("config", {}),
                }
            )
    return declarations


def _test_tied_to_model(node: dict[str, Any], model_unique_id: str) -> bool:
    return node.get("attached_node") == model_unique_id or _node_depends_on(node, model_unique_id)


def _match_generic_test(
    declaration: dict[str, Any],
    test_nodes: list[tuple[str, dict[str, Any]]],
    model_unique_id: str,
) -> tuple[str, dict[str, Any]]:
    matches = []
    for unique_id, node in test_nodes:
        metadata = node.get("test_metadata")
        kwargs = metadata.get("kwargs", {}) if isinstance(metadata, dict) else {}
        if (
            isinstance(metadata, dict)
            and str(metadata.get("name", "")).split(".")[-1]
            == str(declaration["name"]).split(".")[-1]
            and node.get("column_name") == declaration["column_name"]
            and _test_tied_to_model(node, model_unique_id)
            and _mapping_subset(declaration["args"], kwargs)
            and _mapping_subset(declaration["config"], node.get("config", {}))
        ):
            matches.append((unique_id, node))
    if len(matches) != 1:
        raise ContractIdentityEvidenceError(
            f"model {model_unique_id!r}: current generic test {declaration['name']!r} on "
            f"{declaration['column_name']!r} must have exactly one matching manifest node; "
            f"found {len(matches)}"
        )
    return matches[0]


def _verify_unit_tests(manifest: dict[str, Any], document: dict[str, Any], model: str) -> None:
    expected = [
        item
        for item in document.get("unit_tests", [])
        if isinstance(item, dict) and item.get("model") == model
    ]
    unit_tests = manifest.get("unit_tests", {})
    actual = [
        item
        for item in unit_tests.values()
        if isinstance(item, dict) and item.get("model") == model
    ] if isinstance(unit_tests, dict) else []
    keys = ("name", "model", "given", "expect", "overrides")
    canonical_expected = [
        {key: item[key] for key in keys if key in item}
        for item in expected
    ]
    canonical_actual = [
        {key: item[key] for key in keys if key in item}
        for item in actual
    ]
    if canonical_actual != canonical_expected:
        raise ContractIdentityEvidenceError(
            f"model {model!r}: manifest unit-test definitions do not match current YAML"
        )


def _verify_singular_tests(
    transforms: Path,
    nodes: dict[str, Any],
    model: str,
    model_unique_id: str,
) -> list[str]:
    result_ids: list[str] = []
    for path in sorted((transforms / "tests").rglob("*.sql")):
        code = path.read_text(encoding="utf-8")
        if not re.search(rf"\bref\(\s*['\"]{re.escape(model)}['\"]\s*\)", code):
            continue
        matches = [
            (unique_id, node)
            for unique_id, node in nodes.items()
            if isinstance(node, dict)
            and node.get("resource_type") == "test"
            and not isinstance(node.get("test_metadata"), dict)
            and node.get("name") == path.stem
            and _node_depends_on(node, model_unique_id)
        ]
        if len(matches) != 1:
            raise ContractIdentityEvidenceError(
                f"model {model!r}: singular test {path.stem!r} must have exactly one matching "
                f"manifest node; found {len(matches)}"
            )
        unique_id, node = matches[0]
        _require_source_node(node, path, transforms, kind=f"singular test {path.stem!r}")
        result_ids.append(unique_id)
    return result_ids


def capture_dbt_run_results(
    hub_root: Path,
    run_results_path: Path,
    manifest_path: Path,
) -> Path:
    """Capture only actual passing dbt uniqueness/non-null results.

    dbt ``run_results.json`` supplies execution status while ``manifest.json`` supplies
    test metadata. Declared tests absent from the supplied result are never treated as run.
    """

    root = Path(hub_root).resolve()
    try:
        run_results = json.loads(Path(run_results_path).read_text(encoding="utf-8"))
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractIdentityEvidenceError(f"could not read supplied dbt artifacts: {exc}") from exc
    run_meta, manifest_meta, invocation_id, dbt_version = _invocation_metadata(
        run_results, manifest
    )
    nodes = manifest.get("nodes") if isinstance(manifest, dict) else None
    results = run_results.get("results") if isinstance(run_results, dict) else None
    if not isinstance(nodes, dict) or not isinstance(results, list):
        raise ContractIdentityEvidenceError("supplied dbt artifacts lack nodes/results")

    from .dbt_contracts import discover_dbt_contracts

    transforms = root / "integration" / "transforms" / "dbt"
    contracts = discover_dbt_contracts(transforms, root)
    result_by_id: dict[str, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        unique_id = result.get("unique_id")
        if not isinstance(unique_id, str):
            continue
        if unique_id in result_by_id:
            raise ContractIdentityEvidenceError(
                f"run_results.json contains ambiguous duplicate result {unique_id!r}"
            )
        result_by_id[unique_id] = result

    output_results = []
    for contract in contracts:
        requirements = set(identity_requirements(contract))
        model_unique_id, model_node = _model_node(nodes, contract.name)
        _require_source_node(
            model_node, contract.sql_path, transforms, kind=f"model {contract.name!r}"
        )
        document = _verify_manifest_model_semantics(model_node, contract)
        _verify_unit_tests(manifest, document, contract.name)

        manifest_test_nodes = [
            (unique_id, node)
            for unique_id, node in nodes.items()
            if isinstance(node, dict) and node.get("resource_type") == "test"
        ]
        matched_test_ids: set[str] = set()
        actual_requirements: set[str] = set()
        _, authored_model = _current_properties_model(contract)
        for declaration in _generic_test_declarations(authored_model):
            unique_id, node = _match_generic_test(
                declaration, manifest_test_nodes, model_unique_id
            )
            matched_test_ids.add(unique_id)
            if result_by_id.get(unique_id, {}).get("status") not in {"pass", "success"}:
                raise ContractIdentityEvidenceError(
                    f"model {contract.name!r}: invocation {invocation_id!r} lacks a passing "
                    f"result for generic test {unique_id!r}"
                )
            metadata = node["test_metadata"]
            kwargs = metadata.get("kwargs", {})
            test_name = metadata.get("name")
            column = node.get("column_name") or kwargs.get("column_name")
            if test_name == "not_null" and column:
                actual_requirements.add(f"not_null:{column}")
            elif test_name == "unique" and column:
                actual_requirements.add(f"unique:{column}")
            elif test_name in {
                "unique_combination_of_columns",
                "dbt_utils.unique_combination_of_columns",
            }:
                columns = kwargs.get("combination_of_columns")
                if isinstance(columns, list) and all(isinstance(value, str) for value in columns):
                    actual_requirements.add(f"unique:{','.join(columns)}")

        supported = {"not_null", "unique", "unique_combination_of_columns"}
        extra = [
            unique_id
            for unique_id, node in manifest_test_nodes
            if _test_tied_to_model(node, model_unique_id)
            and isinstance(node.get("test_metadata"), dict)
            and str(node["test_metadata"].get("name", "")).split(".")[-1] in supported
            and unique_id not in matched_test_ids
        ]
        if extra:
            raise ContractIdentityEvidenceError(
                f"model {contract.name!r}: manifest contains identity test nodes not declared "
                f"by the current YAML: {', '.join(sorted(extra))}"
            )

        singular_test_ids = _verify_singular_tests(
            transforms, nodes, contract.name, model_unique_id
        )
        for unique_id in singular_test_ids:
            if result_by_id.get(unique_id, {}).get("status") not in {"pass", "success"}:
                raise ContractIdentityEvidenceError(
                    f"model {contract.name!r}: invocation {invocation_id!r} lacks a passing "
                    f"result for singular test {unique_id!r}"
                )

        missing = sorted(requirements - actual_requirements)
        if missing:
            raise ContractIdentityEvidenceError(
                f"model {contract.name!r}: invocation {invocation_id!r} lacks passing results "
                f"for {', '.join(missing)}"
            )
        fingerprint = artifact_content_fingerprint(contract)
        output_results.append(
            {
                "model": contract.name,
                "contract_content_hash": contract_content_hash(contract),
                "passed_requirements": sorted(requirements),
                "invocation_id": invocation_id,
                "generated_at": str(run_meta.get("generated_at", "")),
                "artifact_content_fingerprint": fingerprint,
                "dbt_version": dbt_version,
            }
        )
    output = root / EVIDENCE_RELPATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {"$schema": EVIDENCE_SCHEMA, "results": output_results},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return output
