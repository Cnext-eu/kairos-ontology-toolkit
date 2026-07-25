# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Cnext.eu
"""Fail-closed DD-114/DD-115 strict-release evaluation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

import yaml


class ReleaseDisposition(str, Enum):
    SUPPORTED = "supported"
    DEVIATION = "deviation"
    BLOCKING = "blocking"


@dataclass(frozen=True, slots=True)
class ReleaseBaselineSpec:
    schema_version: str
    policy_version: str
    approval_status: str
    owner_role: str
    reviewed_at: str
    expires_at: str
    required_adapters: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    artifact_hashes: tuple[tuple[str, str], ...]
    block_warnings: bool
    require_dq_runtime_results: bool
    source_hash: str


@dataclass(frozen=True, slots=True)
class BaselineLoadResult:
    baseline: ReleaseBaselineSpec | None
    error: str = ""


@dataclass(frozen=True, slots=True)
class DqRuntimeObservation:
    execution_timestamp: str
    run_id: str
    model_name: str
    rule_id: str
    rule_version: str
    rule_hash: str
    status: str
    observed_value: str | None
    tolerance: str
    action: str
    evidence: str


@dataclass(frozen=True, slots=True)
class ReleaseFinding:
    rule_id: str
    code: str
    domain: str
    disposition: ReleaseDisposition
    message: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReleaseEvaluationInput:
    strict: bool
    generated_at: str
    toolkit_version: str
    baseline_result: BaselineLoadResult
    domains: tuple[tuple[str, Mapping[str, Any]], ...]
    projection_errors: tuple[str, ...] = ()
    closure_incomplete: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    runtime_results: tuple[DqRuntimeObservation, ...] = ()


@dataclass(frozen=True, slots=True)
class ReleaseEvaluationResult:
    mode: str
    release_ready: bool
    findings: tuple[ReleaseFinding, ...]
    manifest: Mapping[str, Any]
    report: Mapping[str, Any]

    @property
    def blockers(self) -> tuple[ReleaseFinding, ...]:
        return tuple(
            finding
            for finding in self.findings
            if finding.disposition is ReleaseDisposition.BLOCKING
        )


def _required_text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"release baseline {key!r} must be a non-empty string")
    return value.strip()


def _string_tuple(data: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"release baseline {key!r} must be a string list")
    return tuple(sorted(set(item.strip() for item in value)))


def load_release_baseline(path: Path) -> BaselineLoadResult:
    """Load an approved baseline without converting malformed input into success."""
    if not path.is_file():
        return BaselineLoadResult(None, f"release baseline is missing: {path}")
    content = path.read_text(encoding="utf-8")
    try:
        loaded = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        return BaselineLoadResult(None, f"release baseline YAML is invalid: {exc}")
    if not isinstance(loaded, dict):
        return BaselineLoadResult(None, "release baseline root must be a mapping")
    try:
        artifact_hashes = loaded.get("artifact_hashes", {})
        if not isinstance(artifact_hashes, dict) or any(
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(value, str)
            or len(value.strip()) != 64
            for key, value in artifact_hashes.items()
        ):
            raise ValueError(
                "release baseline 'artifact_hashes' must map paths to SHA-256 values"
            )
        block_warnings = loaded.get("block_warnings", True)
        require_results = loaded.get("require_dq_runtime_results", False)
        if not isinstance(block_warnings, bool) or not isinstance(
            require_results, bool
        ):
            raise ValueError("release baseline boolean settings must be true or false")
        baseline = ReleaseBaselineSpec(
            schema_version=_required_text(loaded, "schema_version"),
            policy_version=_required_text(loaded, "policy_version"),
            approval_status=_required_text(loaded, "approval_status"),
            owner_role=_required_text(loaded, "owner_role"),
            reviewed_at=_required_text(loaded, "reviewed_at"),
            expires_at=_required_text(loaded, "expires_at"),
            required_adapters=_string_tuple(loaded, "required_adapters"),
            required_artifacts=_string_tuple(loaded, "required_artifacts"),
            artifact_hashes=tuple(
                sorted(
                    (key.strip(), value.strip().lower())
                    for key, value in artifact_hashes.items()
                )
            ),
            block_warnings=block_warnings,
            require_dq_runtime_results=require_results,
            source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
    except ValueError as exc:
        return BaselineLoadResult(None, str(exc))
    return BaselineLoadResult(baseline)


def load_dq_runtime_results(path: Path) -> tuple[DqRuntimeObservation, ...]:
    """Load immutable downstream observations using the DD-115 status vocabulary."""
    if not path.is_file():
        return ()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    values = loaded.get("results") if isinstance(loaded, dict) else loaded
    if not isinstance(values, list):
        raise ValueError("DQ runtime result evidence must be a list or {'results': [...]}")
    results: list[DqRuntimeObservation] = []
    for index, item in enumerate(values):
        if not isinstance(item, dict):
            raise ValueError(f"DQ runtime result {index} must be an object")
        required = {
            "execution_timestamp",
            "run_id",
            "model_name",
            "rule_id",
            "rule_version",
            "rule_hash",
            "status",
            "tolerance",
            "action",
            "evidence",
        }
        missing = sorted(required - item.keys())
        if missing:
            raise ValueError(
                f"DQ runtime result {index} is missing fields: {', '.join(missing)}"
            )
        if item["status"] not in {"pass", "fail", "error", "not-evaluated"}:
            raise ValueError(
                f"DQ runtime result {index} has unsupported status {item['status']!r}"
            )
        for key in required:
            if not isinstance(item[key], str) or not item[key].strip():
                raise ValueError(
                    f"DQ runtime result {index} field {key!r} must be non-empty"
                )
        results.append(
            DqRuntimeObservation(
                execution_timestamp=item["execution_timestamp"],
                run_id=item["run_id"],
                model_name=item["model_name"],
                rule_id=item["rule_id"],
                rule_version=item["rule_version"],
                rule_hash=item["rule_hash"],
                status=item["status"],
                observed_value=(
                    str(item["observed_value"])
                    if item.get("observed_value") is not None
                    else None
                ),
                tolerance=item["tolerance"],
                action=item["action"],
                evidence=item["evidence"],
            )
        )
    return tuple(
        sorted(
            results,
            key=lambda item: (
                item.model_name,
                item.rule_id,
                item.rule_version,
                item.execution_timestamp,
                item.run_id,
            ),
        )
    )


def _finding(
    findings: list[ReleaseFinding],
    rule_id: str,
    code: str,
    domain: str,
    disposition: ReleaseDisposition,
    message: str,
    evidence: tuple[str, ...] = (),
) -> None:
    findings.append(
        ReleaseFinding(
            rule_id=rule_id,
            code=code,
            domain=domain,
            disposition=disposition,
            message=message,
            evidence=tuple(sorted(set(evidence))),
        )
    )


def _evaluation_date(generated_at: str) -> date:
    try:
        return datetime.fromisoformat(generated_at.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise ValueError(
            f"release generated_at must be an ISO timestamp, not {generated_at!r}"
        ) from exc


def _evaluate_baseline(
    inputs: ReleaseEvaluationInput,
    findings: list[ReleaseFinding],
) -> ReleaseBaselineSpec | None:
    result = inputs.baseline_result
    if result.baseline is None:
        _finding(
            findings,
            "DD-114-baseline",
            "release.baseline-missing-or-invalid",
            "",
            ReleaseDisposition.BLOCKING,
            result.error or "release baseline is unavailable",
        )
        return None
    baseline = result.baseline
    if baseline.schema_version != "1.0":
        _finding(
            findings,
            "DD-114-baseline",
            "release.baseline-schema",
            "",
            ReleaseDisposition.BLOCKING,
            f"unsupported release baseline schema {baseline.schema_version!r}",
            (baseline.source_hash,),
        )
    if baseline.approval_status != "approved":
        _finding(
            findings,
            "DD-114-baseline",
            "release.baseline-not-approved",
            "",
            ReleaseDisposition.BLOCKING,
            "strict release requires approval_status 'approved'",
            (baseline.owner_role, baseline.source_hash),
        )
    evaluation_date = _evaluation_date(inputs.generated_at)
    try:
        reviewed = date.fromisoformat(baseline.reviewed_at)
        expires = date.fromisoformat(baseline.expires_at)
    except ValueError:
        _finding(
            findings,
            "DD-114-baseline",
            "release.baseline-invalid-date",
            "",
            ReleaseDisposition.BLOCKING,
            "reviewed_at and expires_at must use ISO YYYY-MM-DD",
            (baseline.source_hash,),
        )
    else:
        if reviewed > evaluation_date:
            _finding(
                findings,
                "DD-114-baseline",
                "release.baseline-future-review",
                "",
                ReleaseDisposition.BLOCKING,
                "release baseline review date is in the future",
                (baseline.reviewed_at,),
            )
        if expires < evaluation_date:
            _finding(
                findings,
                "DD-114-baseline",
                "release.baseline-expired",
                "",
                ReleaseDisposition.BLOCKING,
                f"release baseline expired on {baseline.expires_at}",
                (baseline.source_hash,),
            )
    return baseline


def _valid_deviation(
    deviation: Mapping[str, Any],
    *,
    adapter: str,
    rule_id: str,
    scope: str,
    evaluation_date: date,
) -> tuple[bool, str]:
    if deviation.get("approval_status") != "approved":
        return False, "deviation is not approved"
    if deviation.get("adapter") not in {None, adapter}:
        return False, "deviation adapter does not match"
    if deviation.get("policy_reference") != rule_id:
        return False, "deviation policy reference does not match"
    if deviation.get("scope") not in {"*", scope}:
        return False, "deviation scope does not match"
    if (
        not deviation.get("owner_role")
        or not deviation.get("rationale")
        or not deviation.get("evidence")
    ):
        return False, "deviation lacks owner, rationale, or evidence"
    try:
        reviewed = date.fromisoformat(str(deviation.get("review_date", "")))
        expiry = date.fromisoformat(str(deviation.get("expiry_date", "")))
    except ValueError:
        return False, "deviation review or expiry date is invalid"
    if reviewed > evaluation_date:
        return False, f"deviation review date {reviewed.isoformat()} is in the future"
    if expiry < evaluation_date:
        return False, f"deviation expired on {expiry.isoformat()}"
    return True, ""


def _evaluate_capabilities(
    domain: str,
    data: Mapping[str, Any],
    evaluation_date: date,
    findings: list[ReleaseFinding],
) -> None:
    adapter = data.get("adapter", {})
    adapter_name = str(adapter.get("name", ""))
    adapter_version = str(adapter.get("version", ""))
    compile_evidence = data.get("adapter_compile_evidence", [])
    deviations = data.get("deviations", [])
    for capability in data.get("capabilities", []):
        name = str(capability.get("capability", ""))
        rule_id = str(capability.get("rule_id", "DD-111-capability"))
        scope = str(capability.get("scope", ""))
        matches = [
            evidence
            for evidence in compile_evidence
            if evidence.get("adapter") == adapter_name
            and evidence.get("adapter_version") == adapter_version
            and evidence.get("scope") in {"*", scope}
            and name in evidence.get("capabilities", [])
        ]
        supported = [
            evidence
            for evidence in matches
            if evidence.get("status") == "supported"
            and evidence.get("compile_evidence")
        ]
        invalid_matches = [
            evidence
            for evidence in matches
            if evidence.get("status") != "supported"
            or not evidence.get("compile_evidence")
        ]
        evidence_values = tuple(
            value
            for evidence in supported
            for value in evidence.get("compile_evidence", [])
        )
        if not supported or invalid_matches:
            _finding(
                findings,
                rule_id,
                "release.adapter-compile-evidence",
                domain,
                ReleaseDisposition.BLOCKING,
                (
                    f"{adapter_name}/{adapter_version} capability {name!r} scope "
                    f"{scope!r} lacks unambiguous supported compile evidence"
                ),
                tuple(
                    str(evidence.get("resource_uri", ""))
                    for evidence in matches
                ),
            )
            continue
        disposition = str(capability.get("disposition", "blocking"))
        if disposition == "supported":
            _finding(
                findings,
                rule_id,
                "release.capability-supported",
                domain,
                ReleaseDisposition.SUPPORTED,
                f"{name} is registry-supported and compile-proven",
                evidence_values,
            )
            continue
        deviation_ref = capability.get("deviation_ref")
        deviation = next(
            (
                item
                for item in deviations
                if item.get("resource_uri") == deviation_ref
            ),
            None,
        )
        valid, reason = (
            _valid_deviation(
                deviation,
                adapter=adapter_name,
                rule_id=rule_id,
                scope=scope,
                evaluation_date=evaluation_date,
            )
            if isinstance(deviation, dict)
            else (False, "required deviation is missing")
        )
        if disposition == "deviation" and valid:
            _finding(
                findings,
                rule_id,
                "release.capability-deviation",
                domain,
                ReleaseDisposition.DEVIATION,
                f"{name} is compile-proven under a valid scoped deviation",
                evidence_values + tuple(deviation.get("evidence", [])),
            )
        else:
            _finding(
                findings,
                rule_id,
                "release.capability-blocking",
                domain,
                ReleaseDisposition.BLOCKING,
                f"{name} is not releasable: {reason or capability.get('reason', '')}",
                evidence_values,
            )


def _artifact_index(
    domains: tuple[tuple[str, Mapping[str, Any]], ...],
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    unqualified: dict[str, list[tuple[str, str]]] = {}
    for domain, data in domains:
        for artifact in data.get("generated_artifacts", []):
            path = str(artifact.get("path", ""))
            digest = str(artifact.get("sha256", ""))
            result[f"{domain}:{path}"] = (domain, digest)
            unqualified.setdefault(path, []).append((domain, digest))
    for path, values in unqualified.items():
        if len(values) == 1:
            result[path] = values[0]
    return result


def _evaluate_artifacts(
    inputs: ReleaseEvaluationInput,
    baseline: ReleaseBaselineSpec | None,
    findings: list[ReleaseFinding],
) -> None:
    index = _artifact_index(inputs.domains)
    for domain, data in inputs.domains:
        generated = {
            str(item.get("path", "")): str(item.get("sha256", ""))
            for item in data.get("generated_artifacts", [])
        }
        parity = data.get("parity_status")
        if inputs.strict and not isinstance(parity, dict):
            _finding(
                findings,
                "DD-110-parity",
                "release.silver-parity-missing",
                domain,
                ReleaseDisposition.BLOCKING,
                "strict release requires a Silver parity manifest and status",
            )
        elif (
            isinstance(parity, dict)
            and parity.get("status") == "not-applicable"
            and parity.get("required") is False
        ):
            pass
        elif isinstance(parity, dict):
            parity_errors: list[str] = []
            if parity.get("status") != "pass":
                parity_errors.extend(
                    str(item) for item in parity.get("errors", ())
                )
                if not parity_errors:
                    parity_errors.append("parity status is not pass")
            manifest_path = str(parity.get("manifest_path", ""))
            manifest_hash = str(parity.get("manifest_sha256", ""))
            if not manifest_path or generated.get(manifest_path) != manifest_hash:
                parity_errors.append("parity manifest is missing or hash-drifted")
            hashes = parity.get("artifact_hashes", {})
            if not isinstance(hashes, dict):
                parity_errors.append("parity artifact hashes are malformed")
            else:
                parity_errors.extend(
                    f"{path}: parity hash drift or missing artifact"
                    for path, expected in sorted(hashes.items())
                    if generated.get(str(path)) != str(expected)
                )
            if parity_errors:
                _finding(
                    findings,
                    "DD-110-parity",
                    "release.silver-parity-drift",
                    domain,
                    ReleaseDisposition.BLOCKING,
                    "Silver dbt/YAML/DDL parity evidence is incomplete or stale",
                    tuple(parity_errors),
                )
            else:
                _finding(
                    findings,
                    "DD-110-parity",
                    "release.silver-parity-pass",
                    domain,
                    ReleaseDisposition.SUPPORTED,
                    "Silver dbt/YAML/DDL parity manifest is complete and hash-consistent",
                    (manifest_hash,),
                )
        completeness = data.get("artifact_completeness", {})
        missing = tuple(str(item) for item in completeness.get("missing", []))
        if completeness.get("status") != "ready" or missing:
            _finding(
                findings,
                "DD-114-artifacts",
                "release.artifact-omission",
                domain,
                ReleaseDisposition.BLOCKING,
                f"generated artifact set is incomplete: {missing!r}",
                missing,
            )
    if baseline is None:
        return
    for path in baseline.required_artifacts:
        if path not in index:
            _finding(
                findings,
                "DD-114-artifacts",
                "release.required-artifact-missing",
                "",
                ReleaseDisposition.BLOCKING,
                f"baseline-required artifact {path!r} was not generated",
                (baseline.source_hash,),
            )
    for path, expected in baseline.artifact_hashes:
        actual = index.get(path)
        if actual is None:
            _finding(
                findings,
                "DD-114-artifact-hash",
                "release.hashed-artifact-missing",
                "",
                ReleaseDisposition.BLOCKING,
                f"hash-pinned artifact {path!r} was not generated",
                (expected,),
            )
        elif actual[1] != expected:
            _finding(
                findings,
                "DD-114-artifact-hash",
                "release.artifact-hash-drift",
                actual[0],
                ReleaseDisposition.BLOCKING,
                f"artifact {path!r} differs from the approved baseline",
                (f"expected:{expected}", f"actual:{actual[1]}"),
            )


def _evaluate_dq(
    inputs: ReleaseEvaluationInput,
    baseline: ReleaseBaselineSpec | None,
    findings: list[ReleaseFinding],
) -> list[dict[str, Any]]:
    observations = {
        (item.model_name, item.rule_id, item.rule_version): item
        for item in inputs.runtime_results
    }
    results: list[dict[str, Any]] = []
    for domain, data in inputs.domains:
        artifact_paths = {
            str(item.get("path")) for item in data.get("generated_artifacts", [])
        }
        for rule in data.get("dq_rules", []):
            rule_id = str(rule.get("rule_id", ""))
            version = str(rule.get("rule_version", ""))
            model = str(rule.get("model_name", ""))
            required_paths = {
                str(rule.get("result_artifact", "")),
                str(rule.get("test_artifact", "")),
            }
            if rule.get("action") == "quarantine":
                required_paths.add(str(rule.get("quarantine_artifact", "")))
            missing = sorted(path for path in required_paths if path not in artifact_paths)
            if missing:
                _finding(
                    findings,
                    rule_id,
                    "release.dq-artifact-missing",
                    domain,
                    ReleaseDisposition.BLOCKING,
                    f"DQ rule artifacts are incomplete: {missing!r}",
                    tuple(missing),
                )
            observation = observations.get((model, rule_id, version))
            status = observation.status if observation is not None else "not-evaluated"
            if observation is not None and (
                observation.rule_hash != rule.get("rule_hash")
                or observation.tolerance
                != str(rule.get("tolerance", {}).get("value", ""))
                or observation.action != rule.get("action")
            ):
                _finding(
                    findings,
                    rule_id,
                    "release.dq-result-mismatch",
                    domain,
                    ReleaseDisposition.BLOCKING,
                    "runtime result does not match the generated rule contract",
                    (observation.run_id, observation.evidence),
                )
            elif status == "error" or (
                status == "fail" and rule.get("action") == "block"
            ):
                _finding(
                    findings,
                    rule_id,
                    "release.dq-result-blocking",
                    domain,
                    ReleaseDisposition.BLOCKING,
                    f"DQ runtime result is {status!r}",
                    (
                        observation.run_id if observation else "",
                        observation.evidence if observation else "",
                    ),
                )
            elif status == "not-evaluated" and baseline is not None and (
                baseline.require_dq_runtime_results
            ):
                _finding(
                    findings,
                    rule_id,
                    "release.dq-result-required",
                    domain,
                    ReleaseDisposition.BLOCKING,
                    "approved baseline requires a matching evaluated DQ result",
                )
            else:
                _finding(
                    findings,
                    rule_id,
                    "release.dq-contract",
                    domain,
                    ReleaseDisposition.SUPPORTED,
                    (
                        f"DQ contract generated; runtime status is {status!r}. "
                        "Monitoring remains downstream."
                    ),
                    tuple(str(item) for item in rule.get("evidence", [])),
                )
            results.append(
                {
                    "action": rule.get("action"),
                    "category": rule.get("category"),
                    "domain": domain,
                    "model_name": model,
                    "observed_value": (
                        observation.observed_value if observation else None
                    ),
                    "rule_hash": rule.get("rule_hash"),
                    "rule_id": rule_id,
                    "rule_version": version,
                    "status": status,
                    "tolerance": rule.get("tolerance"),
                }
            )
    return sorted(
        results,
        key=lambda item: (
            str(item["domain"]),
            str(item["model_name"]),
            str(item["rule_id"]),
            str(item["rule_version"]),
        ),
    )


def _evaluate_domain_status(
    inputs: ReleaseEvaluationInput,
    baseline: ReleaseBaselineSpec | None,
    findings: list[ReleaseFinding],
) -> None:
    evaluation_date = _evaluation_date(inputs.generated_at)
    for domain, data in inputs.domains:
        for issue in data.get("policy_issues", []):
            if issue.get("blocking", True):
                _finding(
                    findings,
                    str(issue.get("rule_id", "DD-114-policy")),
                    str(issue.get("code", "release.policy-issue")),
                    domain,
                    ReleaseDisposition.BLOCKING,
                    str(issue.get("message", "unknown policy issue")),
                    (str(issue.get("resource_uri", "")),),
                )
        if baseline is not None and data.get("policy_version") != baseline.policy_version:
            _finding(
                findings,
                "DD-114-policy-version",
                "release.policy-version-mismatch",
                domain,
                ReleaseDisposition.BLOCKING,
                (
                    f"domain policy {data.get('policy_version')!r} does not match "
                    f"baseline {baseline.policy_version!r}"
                ),
            )
        adapter_name = str(data.get("adapter", {}).get("name", ""))
        if baseline is not None and baseline.required_adapters and (
            adapter_name not in baseline.required_adapters
        ):
            _finding(
                findings,
                "DD-111-adapter",
                "release.adapter-not-approved",
                domain,
                ReleaseDisposition.BLOCKING,
                f"adapter {adapter_name!r} is not in the approved baseline",
                baseline.required_adapters,
            )
        for blocker in data.get("blocking_reasons", []):
            _finding(
                findings,
                str(blocker.get("rule_id", "DD-114-policy")),
                "release.policy-blocker",
                domain,
                ReleaseDisposition.BLOCKING,
                str(blocker.get("reason", "unknown policy blocker")),
            )
        for capability in data.get("mapping_capabilities", []):
            if not capability.get("supported", False):
                _finding(
                    findings,
                    str(capability.get("rule_id", "DD-107-adapter")),
                    "release.mapping-capability",
                    domain,
                    ReleaseDisposition.BLOCKING,
                    str(
                        capability.get("reason")
                        or (
                            f"mapping {capability.get('mapping_resource_uri')!r} "
                            f"requires unsupported {capability.get('capability')!r}"
                        )
                    ),
                )
        for status_name in ("binding_status", "coverage_status"):
            status = data.get(status_name, {})
            if status.get("status") == "blocking":
                _finding(
                    findings,
                    "DD-114-" + status_name.replace("_status", "").replace("_", "-"),
                    f"release.{status_name.replace('_status', '')}-blocking",
                    domain,
                    ReleaseDisposition.BLOCKING,
                    f"{status_name.replace('_', ' ')} is blocking",
                    tuple(
                        json.dumps(item, sort_keys=True)
                        for item in status.get(
                            "missing_required_mappings",
                            status.get("unbound_eligible", []),
                        )
                    ),
                )
        gold = data.get("gold_status", {})
        if gold.get("profile"):
            for name in (
                "tables",
                "measures",
                "calendar",
                "security",
                "adapter",
                "tmdl_compile",
            ):
                if gold.get(name) not in {"ready", "not-applicable"}:
                    _finding(
                        findings,
                        f"DD-113-{name}",
                        f"release.{name}-blocking",
                        domain,
                        ReleaseDisposition.BLOCKING,
                        f"Gold {name} status is {gold.get(name)!r}",
                    )
        _evaluate_capabilities(domain, data, evaluation_date, findings)


def evaluate_release(inputs: ReleaseEvaluationInput) -> ReleaseEvaluationResult:
    """Evaluate strict readiness; ordinary projection is always review-only."""
    findings: list[ReleaseFinding] = []
    baseline = _evaluate_baseline(inputs, findings)
    _evaluate_domain_status(inputs, baseline, findings)
    _evaluate_artifacts(inputs, baseline, findings)
    dq_results = _evaluate_dq(inputs, baseline, findings)
    for message in inputs.projection_errors:
        _finding(
            findings,
            "DD-114-projection",
            "release.projection-error",
            "",
            ReleaseDisposition.BLOCKING,
            message,
        )
    for domain in inputs.closure_incomplete:
        _finding(
            findings,
            "DD-114-closure",
            "release.import-closure-incomplete",
            domain,
            ReleaseDisposition.BLOCKING,
            "ontology import closure is incomplete",
        )
    if baseline is not None and baseline.block_warnings:
        for message in inputs.warnings:
            _finding(
                findings,
                "DD-114-warning-policy",
                "release.warning-blocking",
                "",
                ReleaseDisposition.BLOCKING,
                message,
            )
    ordered = tuple(
        sorted(
            set(findings),
            key=lambda item: (
                item.rule_id,
                item.domain,
                item.code,
                item.disposition.value,
                item.message,
                item.evidence,
            ),
        )
    )
    blockers = tuple(
        item
        for item in ordered
        if item.disposition is ReleaseDisposition.BLOCKING
    )
    release_ready = inputs.strict and not blockers and baseline is not None
    mode = "strict-release" if inputs.strict else "review-only"
    artifact_rows = sorted(
        (
            {
                "domain": domain,
                "path": artifact.get("path"),
                "sha256": artifact.get("sha256"),
            }
            for domain, data in inputs.domains
            for artifact in data.get("generated_artifacts", [])
        ),
        key=lambda item: (str(item["domain"]), str(item["path"])),
    )
    finding_rows = [
        {
            "code": item.code,
            "disposition": item.disposition.value,
            "domain": item.domain,
            "evidence": list(item.evidence),
            "message": item.message,
            "rule_id": item.rule_id,
        }
        for item in ordered
    ]
    versions = [
        {
            "adapter": data.get("adapter"),
            "closure_version": data.get("closure_version"),
            "domain": domain,
            "ontology_version": data.get("ontology_version"),
            "policy_version": data.get("policy_version"),
            "toolkit_version": data.get("toolkit_version"),
        }
        for domain, data in inputs.domains
    ]
    dq_coverage = [
        {
            "domain": domain,
            "evaluated": sum(
                item["domain"] == domain and item["status"] != "not-evaluated"
                for item in dq_results
            ),
            "rules": sum(item["domain"] == domain for item in dq_results),
            "runtime_results_required": (
                baseline.require_dq_runtime_results
                if baseline is not None
                else False
            ),
        }
        for domain, _ in inputs.domains
    ]
    manifest: dict[str, Any] = {
        "artifact_hashes": artifact_rows,
        "baseline_hash": baseline.source_hash if baseline is not None else None,
        "dq_coverage": dq_coverage,
        "dq_results": dq_results,
        "generated_at": inputs.generated_at,
        "mode": mode,
        "release_ready": release_ready,
        "rules": finding_rows,
        "schema_version": "1.0",
        "versions": versions,
    }
    report: dict[str, Any] = {
        "blocking_count": len(blockers),
        "blockers": [
            row for row in finding_rows if row["disposition"] == "blocking"
        ],
        "mode": mode,
        "monitoring_boundary": (
            "The toolkit emits executable tests, contracts, and immutable evidence "
            "schemas only; monitoring, alerting, and trend storage remain downstream."
        ),
        "release_ready": release_ready,
        "schema_version": "1.0",
        "supported_count": sum(
            item.disposition is ReleaseDisposition.SUPPORTED for item in ordered
        ),
        "deviation_count": sum(
            item.disposition is ReleaseDisposition.DEVIATION for item in ordered
        ),
    }
    return ReleaseEvaluationResult(
        mode=mode,
        release_ready=release_ready,
        findings=ordered,
        manifest=manifest,
        report=report,
    )
